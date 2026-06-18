"""Bridge Phase 1 mission init/tick to the renderer host.

The constants below are placeholders pinned in Task 25 from the
pick_simplest_mission.py / pick_default_skybox.py scan results.
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import os as _os_mod

from engine import renderer as r
from engine.appc.ship_iter import iter_set_objects as _iter_set_objects, iter_ships as _iter_ships
import engine.dev_keybindings as dev_keybindings
import engine.dev_mode as dev_mode
from engine.dev_mission_picker import MissionPicker
import engine.missions as _missions
from engine.ui.target_reticle import build_target_reticle
from engine.ui.reticle_text import build_reticle_text, _ReticleCam

import math as _math

# ── Audio integration ────────────────────────────────────────────────────────
try:
    import _dauntless_host as _host_mod
    _audio_mod = _host_mod.audio
except (ImportError, AttributeError):
    _audio_mod = None

from engine.audio.alert_audio import AlertAudioListener
from engine.audio.engine_rumble import install_engine_rumble_listener
# tg_sound import — eagerly constructs the manager singleton at host_loop
# import time so SDK code that imports App and uses App.g_kSoundManager is
# well-defined from frame 0. register_default_sounds is called from
# init_audio so engine rumble + alert names resolve before first spawn.
from engine.audio.tg_sound import TGSoundManager, register_default_sounds  # noqa: F401

# ── Per-frame imports (hoisted from function bodies; cleanup issue #2) ─────────
# These names are used on the 60 Hz tick/render path. They were originally
# imported inside their functions; hoisting is code-hygiene (a per-tick
# sys.modules dict hit removed). None of these modules import host_loop at load
# time, so there is no circular-import back-edge.
# NOTE: `import App` is intentionally NOT hoisted here. Importing the App
# shim at host_loop module-load time perturbs sound-manager init order so
# AmbBridge loads early during LoadBridge.Load (breaks a bridge-load test).
# Kept deferred inside _poll_mouse_buttons / _poll_function_keys.
from engine.audio.engine_rumble import update_positions, set_muted as _rumble_set_muted
from engine.audio.bridge_ambient import set_active as _bridge_ambient_set
from engine.ui import crew_menu_hotkeys
from engine.core.game import Game_GetCurrentGame
from engine.appc import (
    projectiles,
    hit_vfx,
    particles,
    ship_death,
    subsystem_emitters,
    camera_shake,
    hit_feedback,
    combat,
    damage_eligibility,
)
# combat is imported as a module (not `from combat import apply_hit`) so call
# sites read combat.apply_hit at call time — tests monkeypatch that attribute.
from engine.appc.sensor_detection import can_detect
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.ships import ShipClass
from engine.appc.ship_death import _out_of_action as _oa
from engine.appc.ship_motion import _effective_motion, _cap_keep, _asymptote_step
from engine.appc.subsystems import (
    TorpedoTube,
    _emitter_in_arc,
    _is_offline,
    _resolve_bank_aim_world,
    impulse_online_fraction,
)
from engine.ui.target_list_visibility import update_target_list_visibility

_alert_listener: "AlertAudioListener" = AlertAudioListener()


def _project_root_for_cef():
    """Return the project root path for resolving native/assets/ui-cef/ files."""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent


def init_audio() -> None:
    """Boot the audio subsystem. Null backend if OPEN_STBC_AUDIO=0."""
    if _audio_mod is None:
        return
    backend = "null" if _os_mod.environ.get("OPEN_STBC_AUDIO") == "0" else "openal"
    _audio_mod.init(backend=backend)
    register_default_sounds()
    install_engine_rumble_listener()
    _alert_listener.reset()


def shutdown_audio() -> None:
    if _audio_mod is None:
        return
    _audio_mod.shutdown()


def tick_audio(*, camera_position, camera_forward, camera_up, dt, player) -> None:
    if _audio_mod is None:
        return
    # Push ship positions to looping rumble sources before set_listener,
    # so positional math sees up-to-date source positions.
    update_positions()
    px, py, pz = camera_position
    fx, fy, fz = camera_forward
    ux, uy, uz = camera_up
    _audio_mod.update(px, py, pz, fx, fy, fz, ux, uy, uz, dt)
    _alert_listener.tick(player)


def _bootstrap_firing_pipeline() -> None:
    """Bring up the SDK-faithful input chain + tactical-control window
    after audio is alive.  Registers default keybindings, installs
    TacticalInterfaceHandlers on the TCW, loads weapon SFX names.

    Idempotent against re-entry — DefaultKeyboardBinding ends up
    registering the same WC entries / bindings each call, which is fine
    because the registration tables are dicts keyed by (WC, KS).

    All SDK imports are guarded: any missing shim surface is logged as a
    warning but never crashes the host loop.
    """
    # Install the sensor-damage AI gate first so it is live regardless of
    # whether any later pipeline step short-circuits. Idempotent.
    from engine.appc.sensor_detection import install_ai_sensor_gate
    install_ai_sensor_gate()

    import App

    # Default destination for fire events.
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)

    # Register WC_* unicode keys with the input manager.  Without this,
    # OnKeyDown(WC_RBUTTON) etc. silently no-op because the key isn't in
    # g_kInputManager._registered.  KeyConfig.MapScancodes registers
    # every keyboard scancode plus mouse buttons (WC_LBUTTON / WC_RBUTTON
    # / WC_MBUTTON) the SDK knows about.
    try:
        import KeyConfig
        KeyConfig.MapScancodes()
    except Exception as _e:
        print(f"[host_loop] WARNING: KeyConfig.MapScancodes() failed: {_e}",
              flush=True)

    # Register the canonical key + binding tables (SDK script).
    try:
        import DefaultKeyboardBinding
        DefaultKeyboardBinding.Initialize()
    except Exception as _e:
        print(f"[host_loop] WARNING: DefaultKeyboardBinding.Initialize() failed: {_e}",
              flush=True)

    # Wire TacticalInterfaceHandlers' fire-event handlers onto the TCW so
    # ET_INPUT_FIRE_PRIMARY/SECONDARY/TERTIARY route to FireWeapons.
    try:
        import TacticalInterfaceHandlers
        TacticalInterfaceHandlers.Initialize(tcw)
    except Exception as _e:
        print(f"[host_loop] WARNING: TacticalInterfaceHandlers.Initialize() failed: {_e}",
              flush=True)

    # Load weapon SFX via the SDK's canonical sound script — no hard-coded
    # names anywhere in the engine.  "Galaxy Phaser Start"/"Loop", "Photon
    # Torpedo", "Tractor Beam", etc. get registered with file paths the
    # SDK script encodes.
    try:
        import LoadTacticalSounds
        LoadTacticalSounds.LoadSounds()
    except Exception as _e:
        print(f"[host_loop] WARNING: LoadTacticalSounds.LoadSounds() failed: {_e}",
              flush=True)

    # Damage-impact sounds — Shield Hit + Subsystem Critical pool.
    # Depends on LoadTacticalSounds having loaded first (rebinds
    # GetRandomSound from there).
    try:
        import LoadDamageHitSounds
        LoadDamageHitSounds.LoadSounds()
    except Exception as _e:
        print(f"[host_loop] WARNING: LoadDamageHitSounds.LoadSounds() failed: {_e}",
              flush=True)

    # NOTE: MissionLib.FriendlyFireHandler registration is deliberately
    # NOT done here.  The SDK script (sdk/.../MissionLib.py:3699) calls
    # pObject.CallNextHandler(pEvent) — pObject is the broadcast `dest`
    # field, which mission setup populates with the running mission via
    # AddBroadcastPythonFuncHandler(ET_WEAPON_HIT, pMission, ...).  We
    # don't have a mission to bind at bootstrap time, so we leave the
    # registration to whatever mission script wants it.  Per-ship hit
    # events still flow via SetDestination(target) in combat.apply_hit.


def _poll_mouse_buttons(host) -> None:
    """Forward host-side mouse rising/falling edges into g_kInputManager.

    `host` is the _dauntless_host module (the binding from host_bindings.cc).
    No-op when host doesn't expose the button-poll methods (e.g. headless
    test setup that imports host_loop without a window).
    """
    if host is None or not hasattr(host, "mouse_button_pressed"):
        return
    import App  # deferred: module-top import reorders sound-manager init
    # PR 2c re-enables left-click (phasers) alongside right-click
    # (torpedoes).  Middle-click is still out of scope — tractor beam is
    # deferred to a future PR.
    for glfw_btn, wc in (
        (host.keys.MOUSE_BUTTON_LEFT,  App.WC_LBUTTON),
        (host.keys.MOUSE_BUTTON_RIGHT, App.WC_RBUTTON),
    ):
        if host.mouse_button_pressed(glfw_btn):
            App.g_kInputManager.OnKeyDown(wc)
        if host.mouse_button_released(glfw_btn):
            App.g_kInputManager.OnKeyUp(wc)


# Previous-frame F-key levels for edge detection (host has key_pressed for
# rising edges but no key_released; deriving both edges from key_state keeps
# the pair symmetric). Module-level so tests can reset it.
_fn_key_prev: dict = {}


def _poll_function_keys(host) -> None:
    """Forward F1-F5 edges into g_kInputManager (WC_F1..F5).

    From there the SDK pipeline (KeyConfig registration +
    DefaultKeyboardBinding bindings) produces ET_INPUT_TALK_TO_* events —
    see docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md.
    """
    if host is None or not hasattr(host, "key_state"):
        return
    keys = getattr(host, "keys", None)
    if keys is None or not hasattr(keys, "KEY_F1"):
        return
    import App  # deferred: module-top import reorders sound-manager init
    for glfw_key, wc in (
        (keys.KEY_F1, App.WC_F1),
        (keys.KEY_F2, App.WC_F2),
        (keys.KEY_F3, App.WC_F3),
        (keys.KEY_F4, App.WC_F4),
        (keys.KEY_F5, App.WC_F5),
    ):
        down = bool(host.key_state(glfw_key))
        was_down = _fn_key_prev.get(glfw_key, False)
        if down and not was_down:
            App.g_kInputManager.OnKeyDown(wc)
        elif was_down and not down:
            App.g_kInputManager.OnKeyUp(wc)
        _fn_key_prev[glfw_key] = down


def _advance_weapons(ships, dt: float) -> None:
    """Per-frame charge / reload advancement for every weapon emitter.

    Walks all ships × all four weapon groups × all child emitters and
    calls UpdateCharge (energy) or UpdateReload (torpedo).  AI ships are
    included — their AI scripts call StartFiring expecting charged
    emitters.
    """
    for ship in ships:
        for group in (
            ship.GetPhaserSystem(),
            ship.GetPulseWeaponSystem(),
            ship.GetTractorBeamSystem(),
            ship.GetTorpedoSystem(),
        ):
            if group is None:
                continue
            for i in range(group.GetNumWeapons()):
                emitter = group.GetWeapon(i)
                if emitter is None:
                    continue
                if hasattr(emitter, "UpdateCharge"):
                    emitter.UpdateCharge(dt)
                if isinstance(emitter, TorpedoTube):
                    emitter.UpdateReload(dt)


def _phaser_damage_for_tick(max_damage: float,
                             max_damage_distance: float,
                             dist: float,
                             dt: float) -> float:
    """Phaser damage with inverse-square falloff scaled by MaxDamageDistance.

    `damage = MaxDamage / (1 + (dist / MaxDamageDistance)**2) * dt`. At
    dist=MaxDamageDistance the damage is half MaxDamage; falls off as
    1/dist² in the far field. Returns 0 if MaxDamageDistance is 0
    (uninitialized property).

    No hard distance cutoff here — the system-level fire gate
    (PhaserSystem at PHASER_MAX_RANGE_GU = 700 GU ≈ 122.5 km) prevents
    fire on out-of-range targets, so this function only runs for shots
    the engine already decided to take."""
    if max_damage_distance <= 0.0:
        return 0.0
    k = dist / max_damage_distance
    return max_damage / (1.0 + k * k) * dt


def _advance_combat(ships, dt: float, host=None, ship_instances=None) -> None:
    """Per-frame torpedo motion + collision + damage + renderer push.

    Walks the active torpedo registry, advances motion, routes hits
    through combat.apply_hit (which calls hit_feedback.dispatch and
    broadcasts WeaponHitEvent), ages out expired VFX, and pushes current
    torpedo + hit-VFX lists to the renderer.

    `host` is the _dauntless_host module (the binding from
    host_bindings.cc).  When None (headless tests), the renderer pushes
    are skipped — combat logic still runs.

    `ship_instances` maps ship → renderer instance id; passed through to
    apply_hit so hit_feedback.dispatch can fire host.shield_hit on the
    SHIELD severity path.
    """
    ships_list = list(ships)

    # Refresh damage-carve eligibility for this tick before any hits are
    # processed: player always + capped nearest/largest ships.
    # See engine.appc.damage_eligibility.
    damage_eligibility.update(ships_list)

    hits = projectiles.update_all(
        dt, ships_list,
        host=host, ship_instances=ship_instances,
    )
    for torpedo, ship, hit_point, hit_normal in hits:
        combat.apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship,
                  normal=hit_normal, host=host, ship_instances=ship_instances,
                  weapon_type="torpedo",
                  hardpoint_weapon=torpedo)

    hit_vfx.update_ages(dt)
    particles.advance(dt)
    ship_death.advance(dt)
    subsystem_emitters.pump(ships_list, _camera_world_pos(host), dt)
    camera_shake.update(dt)

    # Continuous phaser damage tick.  Each ship's PhaserSystem has banks
    # set firing by StartFiring; advance them here: re-check arc (auto-
    # stop drifters), compute distance falloff, and route damage through
    # apply_hit (which routes shields → subsystem → hull, calls
    # hit_feedback.dispatch, and broadcasts WeaponHitEvent).
    for ship in ships_list:
        sys_ = ship.GetPhaserSystem() if hasattr(ship, "GetPhaserSystem") else None
        if sys_ is None:
            continue
        # Disabled-weapons gate: parent aggregates child IsDisabled. When
        # the system flips disabled mid-tick (incoming hit during the
        # previous frame's damage routing), stop any active banks and
        # skip the damage loop for this ship. Spec §4.2.
        if _is_offline(sys_):
            sys_.StopFiring()
            continue
        # While LBUTTON is held, re-fire banks that recharged above the
        # minimum threshold (BC behavior: continuous fire keeps re-firing
        # individual banks as they cycle through their charge curves).
        if hasattr(sys_, "retry_held_fire"):
            sys_.retry_held_fire()
        for i in range(sys_.GetNumWeapons()):
            bank = sys_.GetWeapon(i)
            if bank is None or not bank.IsFiring():
                continue
            target = bank._target
            if target is None or (hasattr(target, "IsDead") and target.IsDead()):
                bank.StopFiring()
                continue
            # Sensor gate (authoritative): this is the per-tick chokepoint where
            # continuous phaser damage is actually applied. A bank can be left
            # IsFiring by an AI that stopped updating (e.g. the firing ship's
            # own SelectTarget cleared its target once its sensors degraded, so
            # FireScript bailed via PS_DONE without StopFiring), so gating only
            # FireScript.TargetVisible isn't enough — stranded banks would keep
            # dealing damage here. A ship that can't detect its target can't
            # keep firing at it. See engine/appc/sensor_detection.can_detect.
            if not can_detect(ship, target):
                bank.StopFiring()
                continue
            target_sub = (ship.GetTargetSubsystem()
                          if hasattr(ship, "GetTargetSubsystem") else None)
            if target_sub is not None and hasattr(target_sub, "GetWorldLocation"):
                target_pos = target_sub.GetWorldLocation()
            else:
                target_pos = target.GetWorldLocation()
                target_sub = None
            emitter_pos = bank._strip_emit_position(target_pos)
            # Distance: emit point → target (drives damage falloff).
            dx = target_pos.x - emitter_pos.x
            dy = target_pos.y - emitter_pos.y
            dz = target_pos.z - emitter_pos.z
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            aim_unit = TGPoint3(dx / dist, dy / dist, dz / dist) if dist > 1e-6 else None
            # Arc check: aim from bank Position → target (NOT emit_pos →
            # target). The firing cone originates at the mount, not at
            # the emit point. Mismatch between this site and StartFiring
            # was Bug F — a bank could pass arc at fire-time and fail
            # on the next tick because its emit point sat past the
            # target on the strip. See research doc § Bug F.
            arc_aim = _resolve_bank_aim_world(bank, target_sub or target)
            if not _emitter_in_arc(bank, ship, arc_aim):
                bank.StopFiring()
                continue
            damage = _phaser_damage_for_tick(
                max_damage=bank.GetMaxDamage(),
                max_damage_distance=bank.GetMaxDamageDistance(),
                dist=dist,
                dt=dt,
            )
            if damage > 0:
                impact_point, impact_normal = combat._resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=(aim_unit if dist > 1e-6 else None),
                    max_dist=(dist * 1.5 if dist > 1e-6 else 0.0),
                    fallback_point=target_pos,
                )
                combat.apply_hit(target, damage, impact_point,
                          source=ship,
                          normal=impact_normal,
                          host=host, ship_instances=ship_instances,
                          weapon_type="phaser",
                          hardpoint_weapon=bank)

    if host is not None and hasattr(host, "set_torpedoes"):
        host.set_torpedoes(_build_torpedo_render_data())
    if host is not None and hasattr(host, "set_hit_vfx"):
        host.set_hit_vfx(_build_hit_vfx_render_data())
    if host is not None and hasattr(host, "set_particle_emitters"):
        host.set_particle_emitters(_build_particle_render_data(ship_instances))
    if host is not None and hasattr(host, "set_phaser_beams"):
        host.set_phaser_beams(_build_phaser_beam_render_data(
            ships_list, host=host, ship_instances=ship_instances))


def _color_tuple(color):
    """TGColorA → (r, g, b, a) tuple, or white when None."""
    if color is None:
        return (1.0, 1.0, 1.0, 1.0)
    # TGColorA in our shim has GetRed/Green/Blue/Alpha or r/g/b/a attrs.
    for attr_set in (("r", "g", "b", "a"),
                     ("GetRed", "GetGreen", "GetBlue", "GetAlpha")):
        try:
            vals = []
            for a in attr_set:
                v = getattr(color, a)
                vals.append(v() if callable(v) else v)
            return tuple(float(v) for v in vals)
        except Exception:
            continue
    return (1.0, 1.0, 1.0, 1.0)


def _resolve_game_texture(path: str) -> str:
    """SDK projectile scripts reference textures by 'data/Textures/...' which
    in BC means relative-to-game-root.  Our binary's CWD is the project
    root; prepend 'game/' so the renderer's ifstream resolves."""
    if not path:
        return ""
    abs_path = PROJECT_ROOT / "game" / path
    return str(abs_path)


def _build_torpedo_render_data():
    """Convert projectiles._active into the dict shape set_torpedoes expects."""
    out = []
    for t in projectiles._active:
        out.append({
            "position":      (t._position.x, t._position.y, t._position.z),
            "core_texture":  _resolve_game_texture(t._core_texture),
            "core_color":    _color_tuple(t._core_color),
            "core_size_a":   t._core_size_a,
            "core_size_b":   t._core_size_b,
            "glow_texture":  _resolve_game_texture(t._glow_texture),
            "glow_color":    _color_tuple(t._glow_color),
            "glow_size_a":   t._glow_size_a,
            "glow_size_b":   t._glow_size_b,
            "glow_size_c":   t._glow_size_c,
            "flares_texture": _resolve_game_texture(t._flares_texture),
            "flares_color":  _color_tuple(t._flares_color),
            "num_flares":    t._num_flares,
            "flares_size_a": t._flares_size_a,
            "flares_size_b": t._flares_size_b,
            "age":           t._age,
        })
    return out


def _build_hit_vfx_render_data():
    out = []
    for entry in hit_vfx.snapshot():
        pos = entry["position"]
        n = entry["normal"]
        out.append({
            "position":    (pos.x, pos.y, pos.z),
            "normal":      (n.x, n.y, n.z) if n is not None else (0.0, 0.0, 0.0),
            "severity":    entry["severity"],
            "age":         entry["age"],
            "instance_id": entry.get("instance_id"),
            "body_point":  entry.get("body_point"),
            "body_normal": entry.get("body_normal"),
            "weapon_kind": entry.get("weapon_kind", 1),
            "spark_count": entry.get("spark_count", 0),
        })
    return out


def _emit_from_instance_id(emit_from, ship_instances):
    """Map an emit-from object to its renderer instance id.

    Reuses the session.ship_instances dict passed through from
    _advance_combat (the same map used by set_hit_vfx). Returns None
    when the object isn't a known live ship or when ship_instances is
    unavailable.
    """
    if ship_instances is None or emit_from is None:
        return None
    return ship_instances.get(emit_from)


def _build_particle_render_data(ship_instances=None):
    """Build one render descriptor per active particle controller.

    `ship_instances` is the session's ship→instance-id map (same dict
    used by set_hit_vfx). When None, emitters render unattached at their
    world emit_pos (instance_id will be None in every descriptor).
    """

    def _resolve_emit_attach(emit_from):
        """Map a controller's emit-from object to its renderer instance id +
        world velocity. Returns None when the object isn't a live attachable
        ship. Exception-safe: any failure yields None rather than aborting
        the frame."""
        try:
            inst = _emit_from_instance_id(emit_from, ship_instances)
            if inst is None:
                return None
            vel = (0.0, 0.0, 0.0)
            if hasattr(emit_from, "GetVelocity"):
                v = emit_from.GetVelocity()
                vel = (v.x, v.y, v.z)
            return {"instance_id": inst, "velocity": vel}
        except Exception:
            return None

    return particles.snapshot_descriptors(resolve_attach=_resolve_emit_attach)


# Tunable scale applied to SDK-declared beam radii (PhaserWidth /
# MainRadius / TaperRadius).  The instrumentation pass confirmed
# SetPosition is in world units, but the beam-radius family was never
# directly verified — the SDK's 0.30 / 0.15 read as much smaller than
# BC's visible beam at typical Galaxy framing.  3× is a feel-tuned
# nominal; the right long-term fix is a focused instrumentation pass
# that reads back beam render geometry from the live engine.
PHASER_BEAM_WIDTH_MUTATOR = 3.0


def _build_phaser_beam_render_data(ships, host=None, ship_instances=None):
    """Snapshot active phaser beams for the renderer.

    Walks every ship's PhaserSystem; for each bank IsFiring()=1, yields
    {emitter, target, color, width}.  Color is Federation amber (default
    until per-faction beam color is wired); width is a small constant.

    When `host` + `ship_instances` are supplied, each beam's endpoint is
    clipped to the mesh-trace surface point so the visible beam ends on
    the target's hull rather than at its bounding-sphere centre.
    """
    out = []
    for ship in ships:
        sys_ = ship.GetPhaserSystem() if hasattr(ship, "GetPhaserSystem") else None
        if sys_ is None:
            continue
        for i in range(sys_.GetNumWeapons()):
            bank = sys_.GetWeapon(i)
            if bank is None or not bank.IsFiring():
                continue
            target = bank._target
            if target is None:
                continue
            target_sub = (ship.GetTargetSubsystem()
                          if hasattr(ship, "GetTargetSubsystem") else None)
            if target_sub is not None and hasattr(target_sub, "GetWorldLocation"):
                target_pos = target_sub.GetWorldLocation()
            else:
                target_pos = target.GetWorldLocation()
            emitter_pos = bank._strip_emit_position(target_pos)
            dx = target_pos.x - emitter_pos.x
            dy = target_pos.y - emitter_pos.y
            dz = target_pos.z - emitter_pos.z
            raw_length = (dx * dx + dy * dy + dz * dz) ** 0.5
            beam_length = raw_length
            beam_end = target_pos
            # Clip the visible beam to the same mesh-trace point that
            # _advance_combat feeds into apply_hit / shield_hit, so the
            # rendered beam terminates on the hull surface (not at the
            # bounding-sphere centre).
            if raw_length > 1e-6 and host is not None and ship_instances is not None:
                aim_unit = TGPoint3(dx / raw_length,
                                    dy / raw_length,
                                    dz / raw_length)
                clipped, _clipped_normal = combat._resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=aim_unit,
                    max_dist=raw_length * 1.5,
                    fallback_point=beam_end,
                )
                if clipped is not None:
                    beam_end = clipped
                    cdx = beam_end.x - emitter_pos.x
                    cdy = beam_end.y - emitter_pos.y
                    cdz = beam_end.z - emitter_pos.z
                    beam_length = (cdx * cdx + cdy * cdy + cdz * cdz) ** 0.5
            tile_per_unit = bank.GetLengthTextureTilePerUnit()
            u_tiles = max(1.0, beam_length * tile_per_unit) if tile_per_unit > 0 else 1.0
            # SDK four-channel-colour layout (per galaxy.py:418-431) is
            # OuterShell / InnerShell / OuterCore / InnerCore.  We
            # approximate with two concentric beams: the outer shell
            # (orange halo) and a thinner inner-core sheen (white-hot
            # streak).  The inner uses reduced alpha (0.35) so its
            # additive contribution is a subtle highlight rather than
            # a saturating wash — the outer's orange remains the
            # dominant tint.
            mut = PHASER_BEAM_WIDTH_MUTATOR
            core_scale   = bank.GetCoreScale() or 0.50
            outer_half   = (bank.GetPhaserWidth() or 0.30) * mut
            inner_half   = (bank.GetMainRadius() or 0.15) * core_scale * mut
            taper_radius = (bank.GetTaperRadius() or 0.01) * mut
            outer_color  = bank.GetOuterShellColor()
            ic = bank.GetInnerCoreColor()
            inner_color = (ic[0], ic[1], ic[2], 0.35)
            common = {
                "emitter":          (emitter_pos.x, emitter_pos.y, emitter_pos.z),
                "target":           (beam_end.x,    beam_end.y,    beam_end.z),
                "u_tiles":          float(u_tiles),
                "num_sides":        int(bank.GetNumSides() or 6),
                "taper_radius":     float(taper_radius),
                "taper_ratio":      float(bank.GetTaperRatio() or 0.25),
                "taper_min_length": float(bank.GetTaperMinLength() or 5.0),
                "taper_max_length": float(bank.GetTaperMaxLength() or 30.0),
                "perimeter_tile":   float(bank.GetPerimeterTile() or 1.0),
                "texture_speed":    float(bank.GetTextureSpeed() or 0.0),
            }
            out.append({**common,
                         "color": outer_color,
                         "width": float(outer_half)})
            out.append({**common,
                         "color": inner_color,
                         "width": float(inner_half)})
    return out


def _all_ships_for_tick():
    """Iterator over every ship the per-frame weapon tick should advance.

    Uses iter_ships() from engine.appc.ship_iter — the same pattern
    engine_rumble uses — which walks App.g_kSetManager._sets and yields
    ShipClass instances only.
    """
    try:
        return _iter_ships()
    except Exception:
        return iter(())


def _camera_world_pos(host):
    """Best-effort camera world position for plume distance culling; None if
    unavailable (culling then disabled, cap still applies)."""
    if host is not None and hasattr(host, "get_camera_world_pos"):
        try:
            p = host.get_camera_world_pos()
            return (p[0], p[1], p[2])
        except Exception:
            return None
    return None


def _extract_ypr(R) -> tuple:
    """Yaw/pitch/roll in degrees from a BC column-vector TGMatrix3
    (see CLAUDE.md ↦ "Rotation matrix convention").

    BC convention: Col 0 = right, Col 1 = forward (Y), Col 2 = up (Z).

    Sign convention for the displayed numbers (chosen to preserve the
    HUD readings the user had before the row/column unification):
      Yaw +θ = MakeZRotation(+θ).  Pitch +θ = MakeXRotation(-θ).
      Roll +θ = MakeYRotation(-θ).
    Under right-hand rule with col-vector matrices these are the
    "inverse" rotations, so the formulas negate the relevant signs.
    """
    fwd = R.GetCol(1)
    up  = R.GetCol(2)
    rgt = R.GetCol(0)
    yaw_deg   = _math.degrees(_math.atan2(-fwd.x, fwd.y))
    pitch_deg = _math.degrees(_math.asin(max(-1.0, min(1.0, -fwd.z))))
    roll_deg  = _math.degrees(_math.atan2(rgt.z, up.z))
    return yaw_deg, pitch_deg, roll_deg


_ALERT_LEVEL_NAMES = {0: "Green", 1: "Yellow", 2: "Red"}


def _format_alert_level(level: int) -> str:
    """Map ShipClass.{GREEN,YELLOW,RED}_ALERT to a display string."""
    return _ALERT_LEVEL_NAMES.get(int(level), "---")


def _shift_held(h) -> bool:
    """True if either shift key is held. Tolerates older bindings that
    didn't expose the shift keys — returns False there so the alert
    handler is a no-op until the C++ host is rebuilt."""
    ks = getattr(h, "keys", None)
    if ks is None:
        return False
    l = getattr(ks, "KEY_LEFT_SHIFT", None)
    r = getattr(ks, "KEY_RIGHT_SHIFT", None)
    if l is not None and h.key_state(l):
        return True
    if r is not None and h.key_state(r):
        return True
    return False


def _apply_alert_keys(h, player) -> None:
    """Shift+1/2/3 → SetAlertLevel(GREEN/YELLOW/RED) on the player ship.

    Mirrors BC's DefaultKeyboardBinding: !/@/# → ET_SET_ALERT_LEVEL with
    EST_ALERT_{GREEN,YELLOW,RED}. Called once per tick before the throttle
    handler — the same digit keys are reused by _PlayerControl for impulse
    level, so the throttle handler ignores digits while shift is held.
    """
    if player is None or not _shift_held(h):
        return
    keys = h.keys
    if h.key_pressed(keys.KEY_1):
        player.SetAlertLevel(ShipClass.GREEN_ALERT)
    elif h.key_pressed(keys.KEY_2):
        player.SetAlertLevel(ShipClass.YELLOW_ALERT)
    elif h.key_pressed(keys.KEY_3):
        player.SetAlertLevel(ShipClass.RED_ALERT)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# v1 ship-gate selections — Task 25 pins these from the pick_*.py scan results.
SHIP_GATE_MISSION = "Custom.Tutorial.Episode.M2Objects.M2Objects"
DEFAULT_TEXTURE_SEARCH = "data/Models/SharedTextures/FedShips/High"
DEFAULT_PLANET_TEXTURE_SEARCH = "data/Models/Environment"

# Bridge geometry (PoC: hardcoded DBridge for all ships).
# On-disk casing is "Dbridge.NIF" — MissionLib references it as
# "DBridge.nif" but most modern filesystems are case-insensitive; we
# match the on-disk casing so this works on case-sensitive volumes too.
DBRIDGE_NIF_REL = "data/Models/Sets/DBridge/Dbridge.NIF"
DBRIDGE_TEX_REL = "data/Models/Sets/DBridge/High"
EBRIDGE_NIF_REL = "data/Models/Sets/EBridge/EBridge.nif"
EBRIDGE_TEX_REL = "data/Models/Sets/EBridge/High"

# Bridge geometry renders at world identity: the bridge pass camera works in
# bridge-local frame, so the bridge's world position is irrelevant.
IDENTITY_MAT4 = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]

# Officer instance world transform — IDENTITY (bridge-set space, the same frame
# as the bridge mesh, which realize_set also places at identity).
#
# Why NOT the negate-X-basis flip the replaced placement layer assumed: in this
# renderer u_model multiplies the whole posed vertex (gl_Position =
# proj·view·u_model·skin·v in skinned_bridge.vert), and the placement clip's
# root track bakes the STATION translation into `skin`. An X-flip u_model
# therefore mirrors not just the body geometry but the station position across
# the bridge centerline, dropping laterally-offset officers (the Commander/XO)
# into their mirror-image seat (the guest chair) — the symptom seen in live
# verify. Ships avoid this because their world translation rides in the matrix's
# 4th column (unflipped); an officer's station translation does not — it is
# inside the palette. The skinned bridge sub-pass disables back-face culling
# (bridge_pass.cc) and bridge.frag does no normal-based lighting, so identity
# does NOT render officers inside-out/dark — the flip's only effects here were
# the (buggy) position mirror plus a left/right body-geometry mirror.
#
# Live-tuning anchor: keeping the body's authored handedness AND the station
# position both correct needs the station translation pulled out of the bone
# palette into u_model's 4th column (ship-style) — a renderer-side follow-up.
# Until then identity prioritises correct seating. Row-major.
OFFICER_TRANSFORM = list(IDENTITY_MAT4)

# Captain's-chair eye position + zoom params, taken from the SDK
# ZoomCameraObjectClass ("maincamera") at mission load (see
# _after_mission_loaded). Defaults are GalaxyBridge's create-time values; the
# host overwrites them per bridge — config-driven for every bridge.
# The zoom params are FOV multipliers + seconds consumed by _BridgeCamera's
# zoom state machine.
_BRIDGE_CAMERA_EYE: tuple = (0.683736, 86.978439, 50.0)
_BRIDGE_ZOOM_MIN: float = 1.0     # SDK GetMinZoom — zoomed-in FOV factor
_BRIDGE_ZOOM_MAX: float = 1.0     # SDK GetMaxZoom — captain FOV factor
_BRIDGE_ZOOM_TIME: float = 0.0    # SDK GetZoomTime — ease duration (seconds)

# Lighting defaults — used by both the per-tick fallback (when no active set
# has lights) and as the conceptual source of truth that the C++
# host_bindings.cc default-constructed Lighting struct mirrors.
DEFAULT_AMBIENT: tuple[float, float, float] = (0.1, 0.1, 0.1)
DEFAULT_DIRECTIONALS: list = [
    # Single top-down directional matching frame.cc's pre-Phase-1 default.
    # ((dx, dy, dz) toward light, (r, g, b))
    ((0.3, 1.0, 0.2), (1.0, 1.0, 1.0)),
]

from engine.cameras import (
    CAM_BACK_RADII, CAM_UP_RADII, CAM_MIN_RADII, CAM_MAX_RADII,
    CameraMode,
)


class _PlayerControl:
    """Keyboard-driven ship-transform integrator.

    Throttle:
        1-9 → target speed = (level/9) × MaxSpeed
        0   → target = 0
        R   → target = -0.25 × MaxSpeed (BC's "reverse 1/4 impulse" idiom)

    Speed ramps from current toward target at MaxAccel rate (units/s²).
    Held W/S/A/D/Q/E turns at MaxAngularVelocity (no angular ramp in v1).

    When the ship has no ImpulseEngineSubsystem with non-zero MaxSpeed,
    falls back to legacy IMPULSE_UNIT × level so fake-ship tests and
    ships before SetupProperties has run still work.
    """

    # Legacy fallbacks — used when the live impulse subsystem isn't populated.
    TURN_RATE_RAD_PER_S = 1.5    # ~86°/s
    IMPULSE_UNIT        = 50.0   # BC units/s per level
    FALLBACK_MAX_ACCEL  = 1.0e9  # effectively instant — preserves legacy semantics
    REVERSE_LEVEL       = -2

    # Reverse magnitude as a fraction of MaxSpeed (BC convention: ¼ impulse).
    REVERSE_FRACTION = 0.25

    # Ctrl+I "in-system warp" boost: forward target speed is multiplied by
    # this factor while the toggle is on. Lets us reach distant astro
    # objects (suns ~63 km out) in seconds without piping through BC's
    # full WarpSequence machinery. Forward only — no reverse boost.
    WARP_BOOST_FACTOR = 100.0

    def __init__(self):
        self.impulse_level = 0  # signed: -2..9; 0 = stop
        self._current_speed = 0.0
        self._current_pitch_rate = 0.0
        self._current_yaw_rate   = 0.0
        self._current_roll_rate  = 0.0
        self._warp_boost = False
        self._drift_velocity = None   # TGPoint3 while drifting (f==0), else None

    # ── Hardpoint accessors ──────────────────────────────────────────────────

    @staticmethod
    def _get_ies(player):
        getter = getattr(player, "GetImpulseEngineSubsystem", None)
        return getter() if getter else None

    def GetTargetSpeed(self, player) -> float:
        """Convert impulse_level into the throttle-commanded target speed
        against the ship's BASE MaxSpeed (unscaled). Degradation caps are
        applied by the keep-rule clamp in apply(), so a ship above its
        reduced cap is not braked. Forward speed is multiplied by
        WARP_BOOST_FACTOR when the in-system warp toggle is on (Ctrl+I);
        reverse is unaffected.
        """
        ies = self._get_ies(player)
        max_speed = ies.GetMaxSpeed() if ies is not None else 0.0
        boost = self.WARP_BOOST_FACTOR if self._warp_boost else 1.0
        if max_speed > 0.0:
            if self.impulse_level >= 0:
                return (self.impulse_level / 9.0) * max_speed * boost
            return -self.REVERSE_FRACTION * max_speed
        if self.impulse_level >= 0:
            return self.impulse_level * self.IMPULSE_UNIT * boost
        return self.impulse_level * self.IMPULSE_UNIT

    def GetCurrentSpeed(self) -> float:
        return self._current_speed

    def GetCurrentPitchRate(self) -> float: return self._current_pitch_rate
    def GetCurrentYawRate(self)   -> float: return self._current_yaw_rate
    def GetCurrentRollRate(self)  -> float: return self._current_roll_rate

    @staticmethod
    def _ramp_toward(current: float, target: float, step: float) -> float:
        delta = target - current
        if abs(delta) <= step:
            return target
        return current + (step if delta > 0 else -step)

    @staticmethod
    def _apply_body_rotation(player, pitch_rate: float, yaw_rate: float,
                             roll_rate: float, dt: float) -> None:
        """Integrate body-frame pitch/yaw/roll rates into the player's world
        rotation for one tick. Column-vector matrices, body-frame delta
        POST-multiplies (R · D); pitch (X) → yaw (Z) → roll (Y) Euler order.
        See CLAUDE.md ↦ 'Rotation matrix convention'. No-op when all rates
        are zero.

        Yaw (about Z) and roll (about Y) are negated relative to the input
        rates: the 2026-06-18 un-mirror made the ship frame right-handed
        (AlignToVectors builds forward × up, so GetCol(0) flipped sign). The
        body-frame yaw/roll deltas move forward/up toward body ±X, which maps
        to world through that flipped GetCol(0) — so the on-screen swing
        reversed for yaw and roll, while pitch (toward body +Z = unchanged
        GetCol(2)) stayed put. Negating restores "press right → turn right /
        roll right". See docs/superpowers/plans/2026-06-18-render-handedness-
        unmirror.md."""
        if not (pitch_rate or yaw_rate or roll_rate):
            return
        R = player.GetWorldRotation()
        R_pitch = TGMatrix3(); R_pitch.MakeRotation( pitch_rate * dt, TGPoint3(1.0, 0.0, 0.0))
        R_yaw   = TGMatrix3(); R_yaw.MakeRotation(  -yaw_rate  * dt, TGPoint3(0.0, 0.0, 1.0))
        R_roll  = TGMatrix3(); R_roll.MakeRotation( -roll_rate * dt, TGPoint3(0.0, 1.0, 0.0))
        delta = R_pitch.MultMatrix(R_yaw).MultMatrix(R_roll)
        player.SetMatrixRotation(R.MultMatrix(delta))

    # ── Per-tick step ────────────────────────────────────────────────────────

    def apply(self, player, dt: float, h) -> None:
        """Read keys, update player transform.

        `h` is the _dauntless_host bindings module (or any object with
        key_state, key_pressed, and `keys.KEY_*` attributes).
        """
        # 1. Throttle (one-shot edges).  R is checked before digits.
        # Shift+digit is reserved for alert-level binding (Shift+1/2/3 →
        # SetAlertLevel); suppress digit throttle while shift is held so
        # the two bindings don't fire together.
        # Cmd+R / Ctrl+R is the CEF reload hotkey and must not also
        # trigger reverse-thrust; suppress when either modifier is held.
        _super_held = h.key_state(h.keys.KEY_LEFT_SUPER) if hasattr(h.keys, "KEY_LEFT_SUPER") else False
        _ctrl_held = h.key_state(h.keys.KEY_LEFT_CONTROL) if hasattr(h.keys, "KEY_LEFT_CONTROL") else False
        # Ctrl+I → toggle in-system warp boost. Snap _current_speed to the
        # new target so the boost engages instantly rather than ramping
        # over many seconds at the IES's normal MaxAccel.
        if (
            _ctrl_held
            and hasattr(h.keys, "KEY_I")
            and h.key_pressed(h.keys.KEY_I)
        ):
            self._warp_boost = not self._warp_boost
            # While drifting (all engines offline) _current_speed is frozen and
            # _drift_velocity drives motion; don't snap it — drift-exit re-seeds
            # it from the drift magnitude. The boost flag still flips so it
            # takes effect once an engine is repaired.
            if self._drift_velocity is None:
                self._current_speed = self.GetTargetSpeed(player)
            print(
                f"[host_loop] in-system warp {'ON' if self._warp_boost else 'OFF'}",
                flush=True,
            )
        if h.key_pressed(h.keys.KEY_R) and not (_super_held or _ctrl_held):
            self.impulse_level = self.REVERSE_LEVEL
        elif h.key_pressed(h.keys.KEY_0):
            self.impulse_level = 0
        elif not _shift_held(h):
            digit_codes = [
                h.keys.KEY_1, h.keys.KEY_2, h.keys.KEY_3, h.keys.KEY_4,
                h.keys.KEY_5, h.keys.KEY_6, h.keys.KEY_7, h.keys.KEY_8,
                h.keys.KEY_9,
            ]
            for level, code in enumerate(digit_codes, start=1):
                if h.key_pressed(code):
                    self.impulse_level = level
                    break

        # ── Engine effectiveness for this tick (spec 2026-06-10) ─────────
        ies = self._get_ies(player)
        f = impulse_online_fraction(ies)

        # ── Total loss → inertial drift ─────────────────────────────────
        if f <= 0.0:
            if self._drift_velocity is None:
                fwd = player.GetWorldRotation().GetCol(1)
                self._drift_velocity = TGPoint3(
                    fwd.x * self._current_speed,
                    fwd.y * self._current_speed,
                    fwd.z * self._current_speed,
                )
            # residual rotation: held rates, no thrust, no decay
            self._apply_body_rotation(
                player, self._current_pitch_rate, self._current_yaw_rate,
                self._current_roll_rate, dt,
            )
            d = self._drift_velocity
            p = player.GetTranslate()
            player.SetTranslateXYZ(p.x + d.x * dt, p.y + d.y * dt, p.z + d.z * dt)
            player.SetVelocity(TGPoint3(d.x, d.y, d.z))
            return

        # ── Powered flight: clear drift, re-seed speed ──────────────────
        if self._drift_velocity is not None:
            self._current_speed = self._drift_velocity.Length()
            self._drift_velocity = None

        em = _effective_motion(player, f)

        # Linear ramp toward (capped) target.
        commanded = self.GetTargetSpeed(player)
        if em.has_linear:
            target_speed = _cap_keep(commanded, self._current_speed, em.max_speed)
            accel = em.max_accel if em.max_accel > 0.0 else self.FALLBACK_MAX_ACCEL
            linear_step = _asymptote_step(accel, target_speed - self._current_speed, dt)
        else:
            target_speed = commanded
            linear_step = self.FALLBACK_MAX_ACCEL * dt
        self._current_speed = self._ramp_toward(
            self._current_speed, target_speed, linear_step,
        )

        # Angular: held keys → per-axis target rate, capped + ramped.
        # W=nose DOWN S=nose UP A=yaw LEFT D=yaw RIGHT Q=roll LEFT E=roll RIGHT
        if em.has_angular:
            ang_rate = em.max_ang_vel
            aa = em.max_ang_accel if em.max_ang_accel > 0.0 else self.FALLBACK_MAX_ACCEL
            ang_step = aa * dt
        else:
            ang_rate = self.TURN_RATE_RAD_PER_S
            ang_step = self.FALLBACK_MAX_ACCEL * dt
        pitch_target = 0.0; yaw_target = 0.0; roll_target = 0.0
        if h.key_state(h.keys.KEY_W): pitch_target -= ang_rate
        if h.key_state(h.keys.KEY_S): pitch_target += ang_rate
        if h.key_state(h.keys.KEY_A): yaw_target   -= ang_rate
        if h.key_state(h.keys.KEY_D): yaw_target   += ang_rate
        if h.key_state(h.keys.KEY_Q): roll_target  += ang_rate
        if h.key_state(h.keys.KEY_E): roll_target  -= ang_rate
        if em.has_angular:
            pitch_target = _cap_keep(pitch_target, self._current_pitch_rate, em.max_ang_vel)
            yaw_target   = _cap_keep(yaw_target,   self._current_yaw_rate,   em.max_ang_vel)
            roll_target  = _cap_keep(roll_target,  self._current_roll_rate,  em.max_ang_vel)
        self._current_pitch_rate = self._ramp_toward(self._current_pitch_rate, pitch_target, ang_step)
        self._current_yaw_rate   = self._ramp_toward(self._current_yaw_rate,   yaw_target,   ang_step)
        self._current_roll_rate  = self._ramp_toward(self._current_roll_rate,  roll_target,  ang_step)
        # Rotation integration (R · D body-frame delta; see CLAUDE.md).
        self._apply_body_rotation(
            player, self._current_pitch_rate, self._current_yaw_rate,
            self._current_roll_rate, dt,
        )

        # Position integration (powered: velocity follows facing).
        # Publish world velocity unconditionally so GetVelocity() is
        # authoritative for the collision system (zero when stationary).
        forward = player.GetWorldRotation().GetCol(1)
        vx = forward.x * self._current_speed
        vy = forward.y * self._current_speed
        vz = forward.z * self._current_speed
        player.SetVelocity(TGPoint3(vx, vy, vz))
        if self._current_speed != 0.0:
            p = player.GetTranslate()
            player.SetTranslateXYZ(p.x + vx * dt, p.y + vy * dt, p.z + vz * dt)


from engine.cameras.chase import _ChaseCamera as _CameraControl


class _ViewModeController:
    """Bridge/exterior view modality.

    Edge-triggered on KEY_SPACE. Owns the single mode flag that input,
    camera, and HUD dispatch off — see _apply_input and _compute_camera.

    Bridge mode is currently a stub: the camera anchors at the ship
    origin looking along ship-Y forward, ship input is suppressed (the
    ship coasts on existing velocity), and a "BRIDGE VIEW" HUD panel
    becomes visible. No bridge geometry yet.
    """
    EXTERIOR = 0
    BRIDGE   = 1

    def __init__(self):
        self._mode = self.BRIDGE

    @property
    def is_exterior(self) -> bool: return self._mode == self.EXTERIOR
    @property
    def is_bridge(self)   -> bool: return self._mode == self.BRIDGE

    def toggle(self) -> None:
        self._mode = self.BRIDGE if self.is_exterior else self.EXTERIOR

    def set_bridge(self) -> None:
        """Force bridge view (used to start a bridge cutscene)."""
        self._mode = self.BRIDGE

    def apply(self, h) -> None:
        """Poll space-pressed and toggle on edge."""
        if h.key_pressed(h.keys.KEY_SPACE):
            self.toggle()


class _PauseMenuController:
    """ESC-toggled pause-menu overlay.

    Edge-triggered on KEY_ESCAPE. Owns the single boolean that the host
    loop reads to decide whether to advance the simulation this tick —
    see the tick body in host_loop.run(). When open, the world keeps
    rendering (frozen) and the CEF overlay paints a placeholder; AI,
    physics, weapons, combat, ship/camera input, and audio tick all
    skip.
    """

    def __init__(self):
        self._open = False
        self._quit_requested = False

    @property
    def is_open(self) -> bool: return self._open

    @property
    def quit_requested(self) -> bool: return self._quit_requested

    def toggle(self) -> None:
        self._open = not self._open

    def close(self) -> None:
        self._open = False

    def request_quit(self) -> None:
        """Pause-menu handler for 'Exit Program'. Sets a flag the host
        loop checks once per tick to break out of the main loop and
        fall through into the existing GL/CEF teardown."""
        self._quit_requested = True

    def apply(self, h) -> None:
        """Poll escape-pressed and toggle on edge."""
        if h.key_pressed(h.keys.KEY_ESCAPE):
            self.toggle()


def _apply_view_mode_side_effects(view_mode: "_ViewModeController", h) -> None:
    """Mirror the view-mode flag into renderer-side state. Idempotent —
    only fires when the mode has changed since the last call. `h` is
    the bindings module (or fake) exposing bridge_pass_set_enabled and
    set_cursor_locked.
    """
    target = view_mode.is_bridge
    last = getattr(view_mode, "_last_synced_is_bridge", None)
    if last == target:
        return
    h.bridge_pass_set_enabled(target)
    h.set_cursor_locked(target)
    # Engine rumble is direct radiation from each ship — silenced when
    # the player is inside the bridge.
    _rumble_set_muted(target)
    # Bridge ambient hum (AmbBridge): start when entering, stop when
    # leaving. Mirrors LoadBridge.py:213-217's play-at-load behaviour
    # but gated on view mode so it only sounds when the player is
    # actually on the bridge.
    _bridge_ambient_set(target)
    # View-mode change — drop any leftover camera-shake energy so
    # the new view doesn't inherit a rumble from the old one.
    camera_shake.reset()
    hit_feedback.reset_audio_throttle()
    view_mode._last_synced_is_bridge = target


class _NullPicker:
    """Stand-in used when dev_mode is disabled (no MissionPicker
    constructed). Always reports closed so the pause-menu side-effects
    predicate degrades to its original behaviour."""
    def is_open(self) -> bool:
        return False


_NULL_PICKER = _NullPicker()

# Install the real particle backend so Spec B plume state machine drives
# actual SDK smoke controllers.  set_backend() only stores the reference and
# sets _manager = None — no simulation side-effects at import time.
from engine.appc import subsystem_emitters as _se_for_backend
from engine.appc import particles as _particles_for_backend
_se_for_backend.set_backend(_particles_for_backend.ParticleBackend())


def _any_blocker_open(blockers) -> bool:
    """True if any of the supplied panel-like objects (each exposing
    is_open()) is currently visible. Used to gate the pause-menu
    visibility — the menu must hide whenever a modal overlays it."""
    return any(b.is_open() for b in blockers)


def _apply_pause_menu_side_effects(pause: "_PauseMenuController",
                                   view_mode: "_ViewModeController",
                                   h,
                                   blockers) -> None:
    """Mirror the pause flag into renderer state: show/hide the CEF
    pause-menu div and unlock the cursor while paused so the player can
    interact with the overlay. Idempotent — only fires when the
    effective visibility has changed since the last call. `h` is the
    bindings module (or fake) exposing cef_execute_javascript and
    set_cursor_locked. `blockers` is an iterable of objects with an
    is_open() method (today: mission picker + developer options panel +
    ship property viewer + configuration panel); when any is open, the pause-menu must hide regardless of
    pause.is_open so the blocker isn't occluded.

    On close, the view-mode sync latch is invalidated so the next
    _apply_view_mode_side_effects call re-applies cursor lock + bridge
    pass state from whatever view mode is current.
    """
    target = pause.is_open and not _any_blocker_open(blockers)
    last = getattr(pause, "_last_synced_is_open", None)
    if last == target:
        return
    display = "'flex'" if target else "'none'"
    h.cef_execute_javascript(
        "document.getElementById('pause-menu').style.display = " + display + ";"
    )
    if target:
        h.set_cursor_locked(False)
    else:
        view_mode._last_synced_is_bridge = None
    pause._last_synced_is_open = target


def _dispatch_modal_esc(blockers, crew_menu_panel, pause, h) -> None:
    """ESC routing across the modal stack, in priority order.

    The first open blocker (each a CEF panel exposing is_open() +
    handle_key_esc()) consumes ESC; otherwise the crew menu closes its
    open submenu; otherwise ESC falls through to the pause-menu toggle
    via pause.apply(h).

    key_pressed(KEY_ESCAPE) is read inside the taken branch only — never
    before pause.apply — so the ESC edge isn't consumed out from under
    the pause toggle. Mirrors the original elif ladder exactly: at most
    one key_pressed(KEY_ESCAPE) call per frame, and zero at this site
    when the fall-through to pause.apply runs.
    """
    for b in blockers:
        if b.is_open():
            if h.key_pressed(h.keys.KEY_ESCAPE):
                b.handle_key_esc()
            return
    if crew_menu_panel.has_open_menu():
        if h.key_pressed(h.keys.KEY_ESCAPE):
            crew_menu_panel.close_open_menu()
        return
    pause.apply(h)


def _dispatch_modal_pause_input(blockers, pause_menu, h) -> None:
    """Keyboard-input routing while the pause menu is open, in priority
    order.

    The first open blocker that owns keyboard input (exposes
    handle_input) consumes this frame's input. A blocker that is open
    but click-only (the mission picker — CEF events, no handle_input)
    blocks the pause menu without consuming input itself. When no
    blocker is open the pause menu navigates and re-emits its row
    payload. This reproduces the original ladder's
    ``elif not mission_picker.is_open()`` guard as "an open click-only
    blocker suppresses pause_menu.handle_input".
    """
    for b in blockers:
        if b.is_open():
            handler = getattr(b, "handle_input", None)
            if handler is not None:
                handler(h)
            return
    pause_menu.handle_input(h)
    _script = pause_menu.render_payload()
    if _script is not None:
        h.cef_execute_javascript(_script)


def _forward_mouse_to_cef(h, send_mouse_move, view_w, view_h) -> tuple:
    """Scale the framebuffer-pixel cursor into CEF OSR view space, send
    it as a mouse-move, and return the (mx, my) view-space coords for
    any follow-up click forwarding.

    cursor_pos() returns FRAMEBUFFER (physical) pixels — see
    renderer/window.cc:173-182 — but the CEF OSR view was initialised in
    logical pixels (view_w x view_h, the dims passed to cef_initialize).
    On Retina the two spaces differ by the device-pixel ratio, so scale
    framebuffer → view-space here. mouse_move forwarding is
    unconditional because it doesn't touch the mouse-button edge state.
    Extracted so a future Retina fix touches one place (was copy-pasted
    in the paused + unpaused mouse-forwarding paths).
    """
    mx_fb, my_fb = h.cursor_pos()
    fb_w, fb_h = h.framebuffer_size()
    sx = (view_w / fb_w) if fb_w > 0 else 1.0
    sy = (view_h / fb_h) if fb_h > 0 else 1.0
    mx = int(mx_fb * sx)
    my = int(my_fb * sy)
    send_mouse_move(mx, my)
    return mx, my


def _compute_cef_resize(fb_w, fb_h, win_w, win_h,
                        cur_view_w, cur_view_h, cur_dsf):
    """Decide whether the windowless CEF browser must be resized to track
    the host window, and to what logical size + device-scale-factor.

    CEF lays out HTML/CSS in *logical* pixels (window points) and
    rasterises at logical x dsf device pixels. To keep the overlay 1:1
    with the framebuffer — no bilinear stretch, DPI-correct text — the
    logical view must equal the window size in **points** (NOT the
    framebuffer pixels, which would re-introduce the 2x stretch on
    Retina) and dsf must equal framebuffer/window.

    Returns (new_view_w, new_view_h, new_dsf) when a change is needed,
    else None. A zero-size window (minimised) is ignored.
    """
    if win_w <= 0 or win_h <= 0:
        return None
    new_dsf = (float(fb_w) / float(win_w)) if fb_w > 0 else cur_dsf
    unchanged = (
        win_w == cur_view_w
        and win_h == cur_view_h
        and abs(new_dsf - cur_dsf) < 1e-3
    )
    if unchanged:
        return None
    return (win_w, win_h, new_dsf)


class _BridgeCamera:
    """First-person bridge camera with mouse-look.

    The bridge interior is rendered as a standalone scene at world
    origin — its scene is independent of the space scene's world frame
    while the viewscreen-as-RTT path (deferred work item #26) is off.
    So the camera lives in bridge-local space, with no coupling to the
    player ship's world transform.

    Eye sits at the MissionLib-pinned DBridge captain's-chair offset
    (sdk/Build/scripts/MissionLib.py:1475-1483). Default forward is
    +Y (into bridge interior, toward the viewscreen); default up is
    +Z. Mouse motion accumulates yaw (around bridge-up = +Z) and pitch
    (around the local right axis). Yaw wraps freely; pitch clamps at
    ±85° to avoid pole flip.

    The MissionLib pose also specifies a rotation (axis-angle
    -1.55 rad around +Z). The Gamebryo-side default forward and what
    that rotation actually composes with isn't pinned down in this
    cleanroom yet, so we leave the initial pose at "forward = +Y" and
    let mouse-look + visual iteration discover the right default.
    """

    # PoC starting values; tuned by feel during visual verification.
    NEAR              = 1.0
    FAR               = 800.0
    FOV_Y_RAD         = _math.radians(60.0)
    MOUSE_SENSITIVITY = 0.0015          # rad per pixel
    PITCH_LIMIT_RAD   = _math.radians(85)

    # Initial yaw flips the default +Y forward to -Y, which visually
    # corresponds to "looking into the bridge interior" with the
    # DBridge mesh as authored — the +Y direction lands the camera
    # facing the rear wall.
    INITIAL_YAW_RAD = _math.pi

    def __init__(self):
        self.yaw_rad   = self.INITIAL_YAW_RAD
        self.pitch_rad = 0.0
        # Zoom-into-officer state (step 5a). _zoom_t eases 0 (captain view) ->
        # 1 (framed on officer). _zoom_target_world is the look-at point (kept
        # during ease-out until _zoom_t returns to 0). _zoom_active = a target
        # is currently selected.
        self._zoom_t = 0.0
        self._zoom_active = False
        self._zoom_target_world = None
        # Cutscene animation override: when set, compute_camera returns this
        # (eye, target, up) verbatim and mouse-look is frozen. Driven by
        # BridgeCutsceneController.update (engine/bridge_cutscene.py).
        self._anim_pose = None

    def _eye_offset(self) -> tuple:
        """Captain's-chair eye, taken from the SDK maincamera at mission load
        (module global _BRIDGE_CAMERA_EYE), config-driven for every bridge."""
        return _BRIDGE_CAMERA_EYE

    @staticmethod
    def _smoothstep(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    def set_zoom_target(self, world_xyz, dt: float) -> None:
        """Select (world_xyz != None) or deselect (None) an officer to zoom
        onto; advance the ease by dt at rate 1/zoom_time, clamped to [0, 1].
        Mouse-look is suspended whenever a zoom is in progress (see apply)."""
        self._zoom_active = world_xyz is not None
        if world_xyz is not None:
            self._zoom_target_world = world_xyz
        step = dt / max(_BRIDGE_ZOOM_TIME, 1e-6)
        if self._zoom_active:
            self._zoom_t = min(1.0, self._zoom_t + step)
        else:
            self._zoom_t = max(0.0, self._zoom_t - step)
            if self._zoom_t == 0.0:
                self._zoom_target_world = None

    def set_anim_pose(self, eye, target, up) -> None:
        """Override the camera with a cutscene-sampled pose (bridge-local)."""
        self._anim_pose = (tuple(eye), tuple(target), tuple(up))

    def clear_anim_pose(self) -> None:
        self._anim_pose = None

    def apply(self, mouse_dx: float, mouse_dy: float) -> None:
        """Accumulate mouse delta into yaw/pitch with sign conventions:
        right-mouse (+dx) → look-right (-yaw); up-mouse (-dy in screen
        coords) → look-up (+pitch). Pitch clamps; yaw wraps freely."""
        if self._anim_pose is not None:
            return
        # Mouse-look is frozen while a zoom is in progress or held — the camera
        # is framing the officer; it resumes only at the full captain view.
        if self._zoom_t > 0.0 or self._zoom_active:
            return
        self.yaw_rad   -= mouse_dx * self.MOUSE_SENSITIVITY
        self.pitch_rad -= mouse_dy * self.MOUSE_SENSITIVITY
        if self.pitch_rad >  self.PITCH_LIMIT_RAD: self.pitch_rad =  self.PITCH_LIMIT_RAD
        if self.pitch_rad < -self.PITCH_LIMIT_RAD: self.pitch_rad = -self.PITCH_LIMIT_RAD

    def compute_camera(self) -> tuple:
        """Return (eye, target, up, fov_y_rad). Captain view is mouse-look at
        the SDK eye + base FOV. When an officer is selected the look direction
        eases toward that officer's world position and the FOV narrows toward
        FOV_Y_RAD * min_zoom, both over the SDK zoom time. The camera never
        leaves the chair (eye is fixed)."""
        if self._anim_pose is not None:
            eye, target, up = self._anim_pose
            return eye, target, up, self.FOV_Y_RAD * _BRIDGE_ZOOM_MAX
        local_fwd = (0.0, 1.0, 0.0)   # bridge-local +Y
        local_up  = (0.0, 0.0, 1.0)   # bridge-local +Z

        local_fwd = _rot_around(local_fwd, (0.0, 0.0, 1.0), self.yaw_rad)
        right = (
            local_fwd[1]*local_up[2] - local_fwd[2]*local_up[1],
            local_fwd[2]*local_up[0] - local_fwd[0]*local_up[2],
            local_fwd[0]*local_up[1] - local_fwd[1]*local_up[0],
        )
        rlen = _math.sqrt(right[0]**2 + right[1]**2 + right[2]**2)
        if rlen > 1e-6:
            right = (right[0]/rlen, right[1]/rlen, right[2]/rlen)
            local_fwd = _rot_around(local_fwd, right, self.pitch_rad)
            local_up  = _rot_around(local_up,  right, self.pitch_rad)

        eye = self._eye_offset()
        fov = self.FOV_Y_RAD * _BRIDGE_ZOOM_MAX

        if self._zoom_t > 0.0 and self._zoom_target_world is not None:
            e = self._smoothstep(self._zoom_t)
            dx = self._zoom_target_world[0] - eye[0]
            dy = self._zoom_target_world[1] - eye[1]
            dz = self._zoom_target_world[2] - eye[2]
            dl = _math.sqrt(dx*dx + dy*dy + dz*dz)
            if dl > 1e-6:
                ofwd = (dx/dl, dy/dl, dz/dl)
                bx = self._lerp(local_fwd[0], ofwd[0], e)
                by = self._lerp(local_fwd[1], ofwd[1], e)
                bz = self._lerp(local_fwd[2], ofwd[2], e)
                bl = _math.sqrt(bx*bx + by*by + bz*bz)
                if bl > 1e-6:
                    local_fwd = (bx/bl, by/bl, bz/bl)
            fov = self.FOV_Y_RAD * self._lerp(_BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_MIN, e)

        target = (eye[0] + local_fwd[0], eye[1] + local_fwd[1], eye[2] + local_fwd[2])
        return eye, target, local_up, fov


def _rot_around(v, axis_xyz, angle_rad):
    """Rotate v=(x,y,z) around the given unit axis using Rodrigues' formula."""
    ax, ay, az = axis_xyz
    ca = _math.cos(angle_rad)
    sa = _math.sin(angle_rad)
    vx, vy, vz = v
    dot = vx*ax + vy*ay + vz*az
    cross = (ay*vz - az*vy, az*vx - ax*vz, ax*vy - ay*vx)
    return (
        vx*ca + cross[0]*sa + ax*dot*(1.0 - ca),
        vy*ca + cross[1]*sa + ay*dot*(1.0 - ca),
        vz*ca + cross[2]*sa + az*dot*(1.0 - ca),
    )


def _active_zoom_officer_world(crew_menu_panel, r):
    """World-space centre (x, y, z) of the officer whose crew menu is open, or
    None. Resolves the open menu's label -> bridge CharacterClass (via
    crew_menu_hotkeys.resolve_character) -> its step-4 render instance ->
    get_instance_head_center. Any missing hop -> None (captain view, no zoom).

    Uses the posed HEAD centre, NOT get_instance_bounds: officers sit at an
    identity instance transform with their station offset baked into the bone
    palette, so the static-AABB bounds collapse every officer to ~the model
    origin (which made all crew zoom to the same low spot far off the captain's
    forward); the body centre reads too low, so the look-at targets the head."""
    if crew_menu_panel is None:
        return None
    label = crew_menu_panel.open_menu_label()
    if not label:
        return None
    off = crew_menu_hotkeys.resolve_character(label)
    if off is None:
        return None
    iid = getattr(off, "_render_instance", None)
    if iid is None:
        return None
    center = r.get_instance_head_center(iid)
    if not center:
        return None
    return (center[0], center[1], center[2])


def _setup_sdk() -> None:
    """Install SDK finder + AST transforms so SDK script imports work."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools import mission_harness
    mission_harness.setup_sdk()


def reset_sdk_globals() -> None:
    """Clear the SDK globals that a mission populates.

    Called once at start-of-mission and again on every in-process swap.
    Keep this list in lockstep with what the SDK actually mutates.

    After clearing _broadcast_handlers the engine's own keyboard-dispatch
    handler is immediately re-registered so that the input pipeline stays
    functional across mission swaps.  _next_event_type_id is reset to 1200
    — just above the stable ET_INPUT_* block (1001–1053) — so dynamic
    event-type allocations restart from a predictable value.
    """
    import App
    from engine.appc.placement import _waypoint_registry
    from engine.appc.input import register_input_handlers
    from engine.appc import top_window

    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    # Clear the event manager's handler tables so stale handlers from the
    # prior mission don't fire against the new mission's state. SDK
    # conditions register handlers on g_kEventManager during mission init.
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    register_input_handlers(App.g_kEventManager)
    # Reset the TopWindow shim so cutscene/fade/view/input flags don't
    # bleed across missions or in-process swaps. See
    # docs/superpowers/specs/2026-06-03-top-window-shim-design.md.
    top_window.reset_for_tests()
    # Clear the global crew-speech channel so a line still "live" at swap
    # time can't suppress the next mission's first SpeakLine. The subtitle
    # crew slot itself is cleared transitively by reset_for_tests (it
    # rebuilds _SubtitleWindow).
    from engine.appc import crew_speech
    crew_speech.bus().reset()
    # Unhook the target-menu subscriber from the live bridge set so a
    # mission swap doesn't leave a dangling subscription on a recreated
    # set. unwire_from_bridge_set is idempotent — safe to call even when
    # no subscription is active.
    try:
        import App as _App
        from engine.appc.target_menu import unwire_from_bridge_set
        _bridge = _App.g_kSetManager.GetSet("bridge")
        if _bridge is not None:
            unwire_from_bridge_set(_bridge)
    except Exception:
        # Defensive: subscriber-cleanup failure must not block the rest
        # of the reset. Matches the broader reset_sdk_globals discipline
        # (each step is independently best-effort).
        pass
    App.g_kSetManager._sets.clear()
    _waypoint_registry.clear()
    App._next_event_type_id = 1200
    App._reset_target_menu_singleton()
    # Reset the TacticalControlWindow singleton so a TCW built for the prior
    # mission doesn't carry its menu list into the next mission's
    # LoadBridge.Load() call. The SDK LoadBridge rebuilds its menus per Load,
    # so no LoadBridge-side reset is needed.
    try:
        from engine.appc.windows import TacticalControlWindow as _TCW
        _TCW._instance = None
        # Warp-button / sorted-region registry must not leak across missions.
        from engine.appc.tg_ui import st_widgets
        st_widgets._reset_module_state()
        # Re-arm the per-bridge ShipDisplay slots (player + target) —
        # ShipDisplay_Create raises on the 3rd call per bridge load.
        from engine.sdk_ui.widgets import ship_display
        ship_display._reset_for_bridge_teardown()
        # Re-point keyboard dispatch at the fresh singleton — the old
        # instance was just orphaned and still held the default destination.
        App.g_kKeyboardBinding.SetDefaultDestination(
            _TCW.GetInstance())
        from engine.ui import crew_menu_hotkeys
        crew_menu_hotkeys.rewire()
    except Exception as _e:
        dev_mode.log_swallowed("crew_menu_hotkeys.rewire after TCW reset", _e)


def _init_mission(mission_module_name: str):
    """Initialize a mission via the same path gameloop_harness uses.

    Returns (mission, episode, game, mod) for the caller to use.
    """
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.events import TGEvent
    import App

    reset_sdk_globals()

    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    mod = importlib.import_module(mission_module_name)
    if hasattr(mod, "PreLoadAssets"):
        mod.PreLoadAssets(mission)
    mod.Initialize(mission)

    start_evt = TGEvent()
    start_evt.SetEventType(App.ET_MISSION_START)
    start_evt.SetDestination(episode)
    App.g_kEventManager.AddEvent(start_evt)

    return mission, episode, game, mod


def _iter_planets(*, verbose: bool = False) -> Iterable:
    """Walk every Planet (non-Sun) in every active set."""
    import App
    from engine.appc.planet import Planet, Sun
    for set_name, pSet in App.g_kSetManager._sets.items():
        for obj in _iter_set_objects(pSet):
            if isinstance(obj, Planet) and not isinstance(obj, Sun):
                yield obj


def _iter_suns() -> Iterable:
    """Walk every Sun in every active set."""
    import App
    from engine.appc.planet import Sun
    for pSet in App.g_kSetManager._sets.values():
        for obj in _iter_set_objects(pSet):
            if isinstance(obj, Sun):
                yield obj


def _aggregate_suns() -> list:
    """Collect sun render descriptors in BC native world units."""
    from engine.appc.planet import aggregate_suns_for_renderer
    import App
    return aggregate_suns_for_renderer(
        PROJECT_ROOT, list(App.g_kSetManager._sets.values()))


def _aggregate_planets(pSets):
    """Return list[dict] {position, radius} for Planet objects across pSets,
    feeding the dust pass's proximity density scaling. Planets with
    radius <= 0 are dropped (they cannot define an influence sphere)."""
    from engine.appc.planet import Planet, Sun
    out = []
    for pSet in pSets:
        for obj in getattr(pSet, "_objects", {}).values():
            # Sun subclasses Planet; suns are fed via the separate sun list,
            # so exclude them here (planets are density-only).
            if not isinstance(obj, Planet) or isinstance(obj, Sun):
                continue
            radius = obj.GetRadius()
            if radius <= 0:
                continue
            loc = obj.GetWorldLocation()
            out.append({
                "position": (loc.x, loc.y, loc.z),
                "radius": float(radius),
            })
    return out


def _aggregate_lens_flares() -> list:
    """Collect lens-flare descriptors in BC native world units."""
    from engine.appc.lens_flare import aggregate_lens_flares_for_renderer
    import App
    return aggregate_lens_flares_for_renderer(
        PROJECT_ROOT, list(App.g_kSetManager._sets.values()))


def _planet_nif_path(planet, *, verbose: bool = False) -> Optional[str]:
    """Return absolute path to the planet's NIF, or None if unavailable."""
    rel = planet.GetModelPath()
    if not rel:
        if verbose:
            print(f"[host_loop]   skip planet: GetModelPath() returned empty", flush=True)
        return None
    abs_path = PROJECT_ROOT / "game" / rel
    if not abs_path.is_file():
        if verbose:
            print(f"[host_loop]   skip planet: NIF not found at {abs_path}", flush=True)
        return None
    return str(abs_path)


def _ship_nif_path(ship, *, verbose: bool = False) -> Optional[str]:
    """Return absolute path to the ship's high-LOD NIF, or None if not found.

    When verbose is True, prints the specific reason for any None return
    (script lookup, import, stats access, file-not-found) so the host's
    diagnostic mode can surface why ships aren't getting render instances.
    """
    try:
        script_name = ship.GetScript()
    except Exception as e:
        if verbose:
            print(f"[host_loop]   skip: ship.GetScript() raised: {e!r}", flush=True)
        return None
    if not script_name:
        if verbose:
            print(f"[host_loop]   skip: ship.GetScript() returned empty: {script_name!r}", flush=True)
        return None
    try:
        mod = importlib.import_module(script_name)
    except Exception as e:
        if verbose:
            print(f"[host_loop]   skip: import_module({script_name!r}) raised: {type(e).__name__}: {e}", flush=True)
        return None
    try:
        stats = mod.GetShipStats()
    except Exception as e:
        if verbose:
            print(f"[host_loop]   skip: {script_name}.GetShipStats() raised: {type(e).__name__}: {e}", flush=True)
        return None
    if not isinstance(stats, dict):
        if verbose:
            print(f"[host_loop]   skip: {script_name}.GetShipStats() returned non-dict: {type(stats).__name__}", flush=True)
        return None
    rel = stats.get("FilenameHigh")
    if not rel:
        if verbose:
            print(f"[host_loop]   skip: {script_name}.GetShipStats() missing 'FilenameHigh' (keys: {list(stats.keys())})", flush=True)
        return None
    abs_path = PROJECT_ROOT / "game" / rel
    if not abs_path.is_file():
        if verbose:
            print(f"[host_loop]   skip: NIF file not found at {abs_path}", flush=True)
        return None
    return str(abs_path)


def _resolve_active_set(player):
    """Return the SetClass whose lights & backdrops apply to the rendered
    scene. Order:
      1. g_kSetManager.GetRenderedSet() — set explicitly via
         MissionLib.MakeRenderedSet during scene transitions.
      2. The set containing the player ship — Phase 1 fallback.
      3. None — caller falls through to per-system defaults
         (lighting only; backdrops simply absent).

    Considers both _lights and _backdrops when deciding whether a set
    is 'live' so backdrop-only sets (rare but legal) are picked up.
    """
    import App
    rendered = App.g_kSetManager.GetRenderedSet()
    if rendered is not None and (
        getattr(rendered, "_lights", None) or
        getattr(rendered, "_backdrops", None)
    ):
        return rendered
    if player is not None:
        for s in App.g_kSetManager._sets.values():
            if any(o is player for o in getattr(s, "_objects", {}).values()):
                if (getattr(s, "_lights", None) or
                    getattr(s, "_backdrops", None)):
                    return s
    return None


# Back-compat alias — existing lighting tests reference this name.
_resolve_active_lighting_set = _resolve_active_set


def _aggregate_lights(pSet):
    """Thin wrapper over engine.appc.lights.aggregate_for_renderer that
    plugs in this module's DEFAULT_AMBIENT / DEFAULT_DIRECTIONALS. Kept
    as a private symbol so existing tests and call sites don't have to
    juggle the defaults at every call site."""
    from engine.appc.lights import aggregate_for_renderer
    return aggregate_for_renderer(pSet, DEFAULT_AMBIENT, DEFAULT_DIRECTIONALS)


def _aggregate_bridge_lights():
    """Wrapper over aggregate_bridge_for_renderer plugging in this
    module's DEFAULT_AMBIENT / DEFAULT_DIRECTIONALS as the no-bridge-set
    fallback. Mirrors _aggregate_lights's relationship with the space
    aggregator."""
    from engine.appc.lights import aggregate_bridge_for_renderer
    return aggregate_bridge_for_renderer(DEFAULT_AMBIENT, DEFAULT_DIRECTIONALS)


def _aggregate_backdrops(pSet):
    """Thin wrapper over engine.appc.backdrops.aggregate_for_renderer
    that supplies PROJECT_ROOT, mirroring _aggregate_lights's wrapping
    of aggregate_for_renderer in lights.py."""
    from engine.appc.backdrops import aggregate_for_renderer
    return aggregate_for_renderer(pSet, PROJECT_ROOT)


# BC's universal NIF→world scale.  Sourced from BC's ModelPropertyEditor
# preview default (sdk/Tools/ModelPropertyEditor/modelpropertyeditor.reg →
# HKCU\Software\Totally Games\ModelPropertyEditor\Options\ModelScale =
# 0x3C23D70A = 0.01).  Empirical calibration against the Galaxy lands at
# ~0.0102 -- within ~2% of the MPE preview scale, treated as authoring
# noise.  The constant is flat across ship classes: GetRadius() is a
# *gameplay* value (splash damage, AI threat range) and is NOT a
# rendering input.  See research doc Bug E for the prior incorrect
# derivation that this replaces.
BC_MODEL_SCALE = 0.01


def _model_extent_from_aabb(center: tuple, half_extents: tuple) -> float:
    """Outer model-space radius for a NIF: |center| + |half_extents|.
    Conservative upper bound on the maximum vertex distance from origin.
    Used as the divisor in the per-ship natural scale (load-time)."""
    cx, cy, cz = center
    hx, hy, hz = half_extents
    return _math.sqrt(cx*cx + cy*cy + cz*cz) + _math.sqrt(hx*hx + hy*hy + hz*hz)


def _rot_determinant(rot) -> float:
    """3x3 determinant of a row-major BC TGMatrix3 stored as nested lists."""
    m = rot._m
    return (m[0][0] * (m[1][1]*m[2][2] - m[1][2]*m[2][1])
          - m[0][1] * (m[1][0]*m[2][2] - m[1][2]*m[2][0])
          + m[0][2] * (m[1][0]*m[2][1] - m[1][1]*m[2][0]))


def _world_matrix_from(loc, rot, s: float) -> list:
    """Row-major TRS mat4 from an explicit (loc, rot) and combined scale s.

    Shared by _ship_world_matrix, _astro_world_matrix, and the render
    interpolation path.

    Right-handed convention (post un-mirror, 2026-06-18): the rotation goes to
    the GPU untouched. The previous determinant-normalization X-flip — which
    negated body-X when det(rot) > 0 to force det < 0 under glFrontFace(GL_CW) —
    REFLECTED every ship, the cause of the mirrored hull registry text. It is
    removed in concert with AlignToVectors (now right-handed) and pipeline.cc
    (now glFrontFace(GL_CCW)). See docs/superpowers/plans/2026-06-18-render-
    handedness-unmirror.md.
    """
    return [
        rot._m[0][0]*s, rot._m[0][1]*s, rot._m[0][2]*s, loc.x,
        rot._m[1][0]*s, rot._m[1][1]*s, rot._m[1][2]*s, loc.y,
        rot._m[2][0]*s, rot._m[2][1]*s, rot._m[2][2]*s, loc.z,
        0.0,            0.0,            0.0,            1.0,
    ]


def _ship_world_matrix(ship, natural_scale: float) -> list:
    """Row-major TRS mat4 for a ship.

    Two-layer scaling:
      natural_scale  — load-time GetRadius() / NIF_extent, makes the rendered
                       outer radius match BC's GetRadius() reading by default.
      ship.GetScale()— per-frame multiplier applied by SDK scripts
                       (DockWithStarbase, asteroid systems, etc.).

    BC's TGMatrix3 is column-vector (cols = body axes in world; see
    CLAUDE.md ↦ "Rotation matrix convention"). The OpenGL shader's
    u_model is also column-vector, so the rotation is sent directly —
    no transpose.

    Right-handed convention (2026-06-18 un-mirror): the rotation is drawn
    directly with NO reflection. AlignToVectors now builds right = forward × up
    (det = +1) and pipeline.cc uses glFrontFace(GL_CCW), so every ship reaches
    the GPU true-handed — the hull is no longer mirror-imaged. The previous
    determinant-normalization X-flip (which forced det < 0 for the old GL_CW
    state) was removed from _world_matrix_from. See docs/superpowers/plans/
    2026-06-18-render-handedness-unmirror.md.
    """
    loc = ship.GetWorldLocation()
    rot = ship.GetWorldRotation()
    try:
        py_scale = float(ship.GetScale())
    except Exception:
        py_scale = 1.0
    s = natural_scale * py_scale
    return _world_matrix_from(loc, rot, s)


def _astro_world_matrix(obj, natural_scale: float) -> list:
    """Row-major TRS mat4 for a planet/moon. Same two-layer formula as ships:
    natural_scale (load-time GetRadius/NIF_extent) × GetScale() (per-frame).
    Position is BC world-native (no global multiplier).

    See `_ship_world_matrix` for the determinant-normalization rationale.
    """
    loc = obj.GetWorldLocation()
    rot = obj.GetWorldRotation()
    try:
        py_scale = float(obj.GetScale())
    except Exception:
        py_scale = 1.0
    s = natural_scale * py_scale
    return _world_matrix_from(loc, rot, s)


@dataclass
class MissionSession:
    """Per-mission scene state owned by HostController.

    Tracks the renderer instances created for the current mission so a
    swap can destroy them without re-deriving them from the SDK's set
    manager (which is itself about to be cleared).
    """
    mission_name: str
    ship_instances:   dict[Any, int] = field(default_factory=dict)
    # Subsystem glow-dimming controllers, keyed by render instance id.
    # Best-effort VFX; ships without the relevant subsystems get fewer regions.
    ship_glow_controllers: dict[int, Any] = field(default_factory=dict)
    planet_instances: dict[Any, int] = field(default_factory=dict)
    # Per-planet natural_scale = GetRadius() / NIF_extent, cached at load.
    # Ships share a single flat NIF→world scale (BC_MODEL_SCALE) so they
    # need no per-object cache; planets vary in size class and still use
    # the GetRadius-derived per-object scale.
    planet_natural_scale: dict[Any, float] = field(default_factory=dict)
    player: Optional[Any] = None

    def teardown(self, renderer) -> None:
        for iid in list(self.ship_instances.values()):
            renderer.destroy_instance(iid)
        for iid in list(self.planet_instances.values()):
            renderer.destroy_instance(iid)
        self.ship_instances.clear()
        self.ship_glow_controllers.clear()
        self.planet_instances.clear()
        self.planet_natural_scale.clear()
        self.player = None


class HostController:
    """Per-process state for the running renderer + a single mission.

    The nif_to_handle cache lives here (not in MissionSession) so the
    same NIF doesn't re-upload when the next mission reuses it.
    """
    def __init__(self) -> None:
        self.renderer: Any = None
        self.loader: Any = None
        self.nif_to_handle: dict[str, int] = {}
        # Outer model-space extent per NIF path; survives mission swaps so
        # repeated loads of the same ship don't re-query model_aabb.
        self.nif_to_extent: dict[str, float] = {}
        self.session: Optional[MissionSession] = None
        self.pending_swap: Optional[str] = None
        self.bridge_instance: Optional[Any] = None  # InstanceId; set by realize_set
        self.viewscreen_instance: Optional[Any] = None  # InstanceId; set by realize_set
        self.viewscreen_obj: Optional[Any] = None  # set by realize_set
        # NIF path currently bound to bridge_instance. Set by
        # realize_set when the SDK-created bridge object is realized.
        self.current_bridge_nif_abs: Optional[str] = None
        # InstanceIds of placed-and-posed bridge officers. Owned by the
        # controller (like bridge_instance) so it survives mission swaps;
        # repopulated each load by realize_set's character loop, which
        # destroys the prior load's instances first.
        self.officer_instances: list = []
        # InstanceIds of comm-set background geometry, keyed by set name.
        # Populated by realize_set for non-bridge sets; survives mission swaps.
        self.comm_instances_by_set: dict = {}
        # Stable small positive int id per comm set name, allocated at
        # realize_all_sets time (sequential from 1). The renderer tags each
        # comm instance with its set's id (r.set_comm_set_id); the bridge pass
        # renders one tagged set into the viewscreen RTT. _active_comm_feed
        # resolves which (if any) is the live viewscreen feed each frame.
        self.comm_set_ids: dict = {}
        # Invoked once after each successful loader.load(). Stage 2 CEF
        # integration will wire this to rebuild UI state so the panel
        # filters the player ship (Game.SetPlayer runs during loader.load
        # AFTER the ship is added to the set, so the initial publish_added
        # for the player can't filter itself out).
        self.post_load_hook: Optional[Callable[[], None]] = None
        # Set by the host loop after PanelRegistry is constructed so that
        # _drain_pending_swap can invalidate all panel caches on swap.
        self.panel_registry: Any = None

    def swap_mission(self, mission_name: str) -> None:
        self.pending_swap = mission_name

    def _drain_pending_swap(self) -> None:
        if self.pending_swap is None:
            return
        name = self.pending_swap
        self.pending_swap = None
        if self.session is not None:
            self.session.teardown(self.renderer)
        from engine.appc import ship_lifecycle
        ship_lifecycle.reset()
        from engine.appc import ship_death
        ship_death.reset()
        from engine.appc import subsystem_emitters
        subsystem_emitters.reset_manager()
        from engine.appc import particles
        particles.reset()
        damage_eligibility.reset()
        hit_feedback._last_carve_time.clear()
        reset_sdk_globals()
        if self.panel_registry is not None:
            self.panel_registry.invalidate_all()
        assert self.loader is not None, "HostController.loader must be set"
        try:
            self.session = self.loader.load(name)
        except Exception as e:
            import traceback
            print(f"[host] mission swap to {name!r} failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            self.session = None
            return
        if self.post_load_hook is not None:
            self.post_load_hook()


class _MissionLoader:
    """Bundles _init_mission + render-instance construction so HostController
    can call a single .load(name) method.

    Kept inside this module so it can use the existing _iter_ships /
    _iter_planets / _ship_nif_path / _planet_nif_path helpers without
    re-exporting them.
    """
    def __init__(self, controller: "HostController", verbose: bool):
        self._c = controller
        self._verbose = verbose

    def load(self, mission_name: str) -> MissionSession:
        import App
        _init_mission(mission_name)
        sess = MissionSession(mission_name=mission_name)
        r_ = self._c.renderer

        shared_search = [
            str(PROJECT_ROOT / "game" / DEFAULT_TEXTURE_SEARCH),
            str(PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedBases" / "High"),
        ]
        for ship in _iter_ships(verbose=self._verbose):
            nif_path = _ship_nif_path(ship, verbose=self._verbose)
            if nif_path is None:
                continue
            # BC ships split textures: a per-ship High/ dir for hull-specific
            # assets (Sovereign, FedStarbase) plus the shared FedShips/FedBases
            # directories (Galaxy and many others ship nothing locally).
            tex_search = [str(Path(nif_path).parent / "High"), *shared_search]
            handle = self._c.nif_to_handle.get(nif_path)
            if handle is None:
                try:
                    handle = r_.load_model(nif_path, tex_search)
                except Exception as e:
                    if self._verbose:
                        print(f"[host_loop]   skip ship: load_model({nif_path}) raised: "
                              f"{type(e).__name__}: {e}", flush=True)
                    continue
                self._c.nif_to_handle[nif_path] = handle
                center, half_extents = r_.model_aabb(handle)
                self._c.nif_to_extent[nif_path] = _model_extent_from_aabb(center, half_extents)
            extent = self._c.nif_to_extent.get(nif_path, 1.0)
            # Seed a gameplay GetRadius() for shim ships that lack one
            # (camera-follow distance, AI threat range, splash damage).
            # Use the same flat NIF→world scale we render with so the
            # gameplay radius matches the visible mesh bound.
            if ship.GetRadius() <= 0.0:
                try:
                    ship.SetRadius(extent * BC_MODEL_SCALE)
                except Exception as _e:
                    dev_mode.log_swallowed("ship.SetRadius fallback", _e)
            iid = r_.create_instance(handle)
            r_.set_world_transform(iid, _ship_world_matrix(ship, BC_MODEL_SCALE))
            sess.ship_instances[ship] = iid
            # Fresnel rim applies to ship hulls only — planets share the
            # opaque shader and must stay rim-free (default ineligible).
            r_.set_rim_eligible(iid, True)

            # Subsystem glow dimming (best-effort VFX). Ships missing a warp /
            # impulse / sensor subsystem simply register fewer regions; any
            # failure must never block spawning the ship instance.
            try:
                from engine.appc.subsystem_glow import ShipGlowController
                sess.ship_glow_controllers[iid] = ShipGlowController(
                    r_, iid, ship)
            except Exception as _e:
                # glow dimming is best-effort VFX; never block spawn
                dev_mode.log_swallowed("ShipGlowController register", _e)

            # Register shield render state. Reads ShieldProperty data-bag
            # for glow color, decay, and skin-mode flag. No-op for ships
            # without a ShieldProperty (asteroids, debris).
            try:
                from engine.shields import register_ship_shield
                center, half_extents = r_.model_aabb(handle)
                register_ship_shield(
                    r_, instance_id=iid, ship=ship,
                    aabb_center=center, aabb_half_extents=half_extents,
                )
            except Exception as e:
                if self._verbose:
                    print(f"[host_loop]   shield register skipped for ship: "
                          f"{type(e).__name__}: {e}", flush=True)

        planet_tex_search = str(PROJECT_ROOT / "game" / DEFAULT_PLANET_TEXTURE_SEARCH)
        for planet in _iter_planets(verbose=self._verbose):
            nif_path = _planet_nif_path(planet, verbose=self._verbose)
            if nif_path is None:
                continue
            handle = self._c.nif_to_handle.get(nif_path)
            if handle is None:
                try:
                    handle = r_.load_model(nif_path, planet_tex_search)
                except Exception as e:
                    if self._verbose:
                        print(f"[host_loop]   skip planet: load_model({nif_path}) raised: "
                              f"{type(e).__name__}: {e}", flush=True)
                    continue
                self._c.nif_to_handle[nif_path] = handle
                center, half_extents = r_.model_aabb(handle)
                self._c.nif_to_extent[nif_path] = _model_extent_from_aabb(center, half_extents)
            extent = self._c.nif_to_extent.get(nif_path, 1.0)
            if planet.GetRadius() <= 0.0:
                try:
                    planet.SetRadius(extent * BC_MODEL_SCALE)
                except Exception as _e:
                    dev_mode.log_swallowed("planet.SetRadius fallback", _e)
            radius = planet.GetRadius()
            natural_scale = (radius / extent) if extent > 0.0 else 1.0
            iid = r_.create_instance(handle)
            r_.set_world_transform(iid, _astro_world_matrix(planet, natural_scale))
            sess.planet_instances[planet] = iid
            sess.planet_natural_scale[planet] = natural_scale

        player = None
        for pSet in App.g_kSetManager._sets.values():
            cand = pSet.GetObject("player")
            if cand is not None:
                player = cand
                break
        if player is None and sess.ship_instances:
            player = next(iter(sess.ship_instances.keys()))
        sess.player = player
        return sess


class _NoInputReader:
    """Bindings stub used for _PlayerControl in bridge view.

    _PlayerControl.apply() reads input AND integrates ship state in one
    body. Bridge mode wants the integration to keep running (so engines
    keep coasting and the ship continues moving) but the input keys to
    have no effect. Passing this stub satisfies both: every key check
    returns False, so impulse_level stays put and angular targets are
    zero, while the ramp + integration steps still execute.

    Mirrors the surface of _dauntless_host that _PlayerControl touches.
    Singleton — see _NO_INPUT below — to avoid per-tick allocation.
    """
    class _Keys:
        KEY_R = KEY_0 = KEY_1 = KEY_2 = KEY_3 = KEY_4 = 0
        KEY_5 = KEY_6 = KEY_7 = KEY_8 = KEY_9 = 0
        KEY_W = KEY_S = KEY_A = KEY_D = KEY_Q = KEY_E = 0
    keys = _Keys()
    @staticmethod
    def key_pressed(_): return False
    @staticmethod
    def key_state(_):   return False


_NO_INPUT = _NoInputReader()


def _apply_input(view_mode, player_control, director,
                 *, player, dt, h, scroll_y) -> None:
    """Per-tick input dispatch.

    Exterior mode drives both ship and camera from the keyboard. Bridge
    mode keeps the ship-physics integration running (engines keep
    coasting; angular rates ramp toward zero since no input is held)
    by calling player_control.apply() with a no-input reader, but does
    not advance the orbit camera so its state is preserved for when we
    toggle back to exterior.
    """
    if view_mode.is_exterior:
        player_control.apply(player, dt, h)
        director.chase.apply(dt, h, scroll_y)
    else:
        player_control.apply(player, dt, _NO_INPUT)


def _compute_camera(view_mode, director, *, player, dt) -> tuple:
    """Per-tick camera dispatch.

    Bridge mode anchors at the ship origin looking along ship-Y
    forward. Exterior mode delegates to the director, which chooses
    between Chase Mode (free orbit) and Tracking Mode (two-angle
    solver). Returns (eye, look_at, up) as 3-tuples in world space.
    """
    loc = player.GetWorldLocation()
    rot = player.GetWorldRotation()
    if view_mode.is_bridge:
        fwd = rot.GetCol(1)
        up  = rot.GetCol(2)
        eye    = (loc.x, loc.y, loc.z)
        target = (loc.x + fwd.x, loc.y + fwd.y, loc.z + fwd.z)
        up_vec = (up.x, up.y, up.z)
        return eye, target, up_vec
    return director.compute(player=player, dt=dt)





def _update_ui_for_tick(player, view_mode, session, active_set) -> None:
    """CEF integration hook — Stage 2 wires this up. Currently a no-op."""
    return


def realize_set(controller, r, set_obj, *, is_bridge: bool,
                comm_set_id: int = None) -> None:
    """Realize any SDK set's renderable content into the renderer.

    Generic replacement for the retired bridge-specific realize functions
    (geometry, viewscreen, officer placement). Honors the SDK calls that
    declared the content:
      - bridge: BridgeObjectClass carrier (set.GetObject("bridge").nif)
      - comm:   set.GetBackgroundModelNIF()  (SetBackgroundModel)
    Idempotent + leak-free: a carrier that already has a render instance is
    reused; a fresh carrier (set rebuild) destroys the prior instance first.

    `comm_set_id` (comm sets only): a small positive int the caller allocated
    for this set; every comm instance created here is tagged via
    r.set_comm_set_id so the bridge pass can render this set into the
    viewscreen RTT.
    """
    import App as _App
    set_name = set_obj.GetName()

    # ── Background geometry ────────────────────────────────────────────────
    if is_bridge:
        carrier = set_obj.GetObject("bridge")
        nif = getattr(carrier, "nif", None) if carrier is not None else None
    else:
        carrier = set_obj
        nif = set_obj.GetBackgroundModelNIF()

    # NOTE: use __dict__, not getattr — the comm carrier is a SetClass whose
    # __getattr__ returns a truthy _RendererStub for any unknown attribute, so
    # getattr(carrier, "render_instance", None) would NEVER be None and the
    # room geometry would never realize. __dict__ sees only real attributes.
    if nif and carrier.__dict__.get("render_instance") is None:
        if is_bridge and controller.bridge_instance is not None:
            try:
                r.destroy_instance(controller.bridge_instance)
            except Exception as _e:
                dev_mode.log_swallowed("destroy bridge instance", _e)
            controller.bridge_instance = None

        nif_abs = str(PROJECT_ROOT / "game" / nif)
        env = _App.g_kModelManager.env_for(nif)
        if env:
            tex_abs = str(PROJECT_ROOT / "game" / env)
        else:
            # No LoadModel-recorded env — comm sets declare geometry via
            # SetBackgroundModel, not LoadModel, so env_for is None. Set
            # textures live in <model_dir>/High by BC convention; use that
            # rather than the DBridge fallback (which holds only DBridge's tgas).
            import posixpath as _pp
            tex_abs = str(PROJECT_ROOT / "game" / _pp.dirname(nif) / "High")
        if is_bridge:
            handle = r.load_model(nif_abs, tex_abs)
            iid = r.create_bridge_instance(handle)
        else:
            # A comm/remote set is non-critical: if its NIF or a texture fails
            # to load, log and skip so one bad set can't abort the whole mission.
            try:
                handle = r.load_model(nif_abs, tex_abs)
            except Exception as _e:
                dev_mode.log_swallowed("comm set load_model %r" % set_name, _e)
                handle = None
            iid = r.create_comm_instance(handle) if handle is not None else None
        if iid is not None:
            r.set_world_transform(iid, IDENTITY_MAT4)
            if hasattr(carrier, "render_instance"):
                carrier.render_instance = iid
            controller.nif_to_handle[nif_abs] = handle
            if is_bridge:
                controller.bridge_instance = iid
                controller.current_bridge_nif_abs = nif_abs
            else:
                controller.comm_instances_by_set.setdefault(set_name, []).append(iid)
                _tag_comm_instance(r, iid, comm_set_id)

    # ── Viewscreen (bridge only) ───────────────────────────────────────────
    if is_bridge:
        from engine.appc.bridge_set import ViewScreenObject
        vs = set_obj.GetViewScreen()
        if isinstance(vs, ViewScreenObject) and vs.render_instance is None:
            if controller.viewscreen_instance is not None:
                try:
                    r.destroy_instance(controller.viewscreen_instance)
                except Exception as _e:
                    dev_mode.log_swallowed("destroy viewscreen instance", _e)
                controller.viewscreen_instance = None
            vs_nif_abs = str(PROJECT_ROOT / "game" / vs.nif)
            vs_env = _App.g_kModelManager.env_for(vs.nif)
            vs_tex = (str(PROJECT_ROOT / "game" / vs_env) if vs_env
                      else str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL))
            vs_handle = r.load_model(vs_nif_abs, vs_tex)
            vs_iid = r.create_bridge_instance(vs_handle)
            r.set_world_transform(vs_iid, IDENTITY_MAT4)
            vs.render_instance = vs_iid
            controller.viewscreen_instance = vs_iid
            controller.nif_to_handle[vs_nif_abs] = vs_handle
            r.set_viewscreen_model(vs_handle)
            vs.SetIsOn(1)
            controller.viewscreen_obj = vs

    # ── Characters ─────────────────────────────────────────────────────────
    # Characters: tear down prior officer instances before re-placing (mission
    # swap re-realizes the bridge set; without this the old instances leak).
    if is_bridge:
        for _iid in controller.officer_instances:
            try:
                r.destroy_instance(_iid)
            except Exception as _e:
                dev_mode.log_swallowed("destroy officer instance (teardown)", _e)
        controller.officer_instances = []
    for character in _iter_set_characters(set_obj):     # same enumeration the
        _place_one_character(controller, r, character,  # old officer loop used
                             set_name, is_bridge, comm_set_id=comm_set_id)


def realize_all_sets(controller, r) -> None:
    """Realize every SDK-created set into the renderer after mission load.

    The 'bridge' set is the player bridge; any other set that declared a
    background model or characters is a comm/remote set. Replaces the old
    bridge-specific geometry / viewscreen / officer-placement call sequence —
    the bridge is now just one set realized through the generic realize_set
    path.
    """
    import App as _App
    mgr = _App.g_kSetManager
    _next_comm_id = 1
    for name, s in list(mgr.iter_sets()):          # use the manager's set map
        if name == "bridge":
            realize_set(controller, r, s, is_bridge=True)
        elif hasattr(r, "create_comm_instance") and (
                s.GetBackgroundModelNIF() is not None or _iter_set_characters(s)):
            # hasattr guard: skip comm-set realization cleanly against a stale
            # renderer build that predates the create_comm_instance binding.
            # Allocate a stable small positive id for this comm set so its
            # instances can be tagged + the viewscreen RTT can render it.
            comm_set_id = controller.comm_set_ids.get(name)
            if comm_set_id is None:
                comm_set_id = _next_comm_id
                controller.comm_set_ids[name] = comm_set_id
            _next_comm_id = max(_next_comm_id, comm_set_id) + 1
            realize_set(controller, r, s, is_bridge=False,
                        comm_set_id=comm_set_id)


def _iter_set_characters(set_obj):
    """Enumerate every CharacterClass in a set — the same walk the old
    bridge-officer loop used (GetClassObjectList(CharacterClass))."""
    from engine.appc.characters import CharacterClass
    return set_obj.GetClassObjectList(CharacterClass)


def _tag_comm_instance(r, iid, comm_set_id) -> None:
    """Tag a comm instance with its set's id so the bridge pass can render the
    set into the viewscreen RTT. Guarded: renderer builds without the binding
    (and the FakeRenderer in unit tests) silently skip the tag."""
    if comm_set_id is None:
        return
    if hasattr(r, "set_comm_set_id"):
        try:
            r.set_comm_set_id(iid, comm_set_id)
        except Exception as _e:
            dev_mode.log_swallowed("set_comm_set_id", _e)


def _place_one_character(controller, r, character, set_name, is_bridge,
                         *, comm_set_id: int = None) -> None:
    """Pose one SDK CharacterClass at its station and create its skinned
    instance. Body extracted verbatim from the prior bridge-officer placement
    loop; the only change is create_bridge_instance vs create_comm_instance
    and the comm_instances_by_set bookkeeping.

    Leak-free + idempotent: per-character _render_instance tag prevents
    double-placement within a load (a fresh set rebuild enumerates fresh,
    untagged characters).
    """
    from engine.appc.bridge_placement import capture_placement

    if getattr(character, "_render_instance", None) is not None:
        return                                       # already placed this load

    def _abs(p):
        return str(PROJECT_ROOT / "game" / p) if p else None

    create = r.create_bridge_instance if is_bridge else r.create_comm_instance

    try:
        placement = capture_placement(character)
        if not placement or placement["hidden"]:
            return
        ap = character.appearance()
        if not ap.get("body_nif"):
            return

        model = r.assemble_officer(
            _abs(ap.get("body_nif")), _abs(ap.get("head_nif")),
            _abs(ap.get("body_tex")), _abs(ap.get("head_tex")),
            _abs(placement["clip_nif"]),
            placement["sample_at_start"],
        )
        iid = create(model)
        try:
            r.set_world_transform(iid, OFFICER_TRANSFORM)
            r.set_instance_animation(
                iid, 0, False, placement["sample_at_start"])
        except Exception:
            try:
                r.destroy_instance(iid)
            except Exception as _e:
                dev_mode.log_swallowed(
                    "destroy officer instance (rollback)", _e)
            raise
        character._render_instance = iid
        if is_bridge:
            controller.officer_instances.append(iid)
        else:
            controller.comm_instances_by_set.setdefault(set_name, []).append(iid)
            _tag_comm_instance(r, iid, comm_set_id)
    except Exception:
        name = ""
        try:
            name = character.GetCharacterName()
        except Exception as _e:
            dev_mode.log_swallowed("character.GetCharacterName in error path", _e)
        import traceback
        print(f"[host_loop] WARNING: failed to place character {name!r}",
              flush=True)
        traceback.print_exc()


def _viewscreen_feed_on(viewscreen_obj) -> bool:
    """The viewscreen RTT feed is on iff a realized viewscreen object reports
    IsOn(). Off (or no viewscreen) -> the step-5b blank panel."""
    return bool(viewscreen_obj is not None and viewscreen_obj.IsOn())


def _active_comm_feed(controller):
    """If the bridge viewscreen's remote cam is a comm set's 'maincamera',
    return (comm_set_id, camera); else None (forward-view fallback).

    MissionLib.ViewscreenOn sets the look-at set's "maincamera" as the
    viewscreen's remote cam (SetRemoteCam). We identity-match that camera back
    to the set it belongs to, then look up the set's allocated comm_set_id.
    """
    vs = getattr(controller, "viewscreen_obj", None)
    if vs is None or not vs.IsOn():
        return None
    cam = vs.GetRemoteCam()
    if cam is None:
        return None
    import App as _App
    for name, s in list(_App.g_kSetManager.iter_sets()):
        if s.GetCamera("maincamera") is cam:
            set_id = controller.comm_set_ids.get(name)
            if set_id is not None:
                return (set_id, cam)
            return None
    return None


def _comm_camera_params(cam):
    """Convert a CameraObjectClass into the viewscreen-RTT camera tuple
    (eye, target, up, fov_y_rad, near, far), all in game units.

    CameraObjectClass.orientation is the BC-object convention (col0=right,
    col1=forward, col2=up) for BOTH camera sources: the explicit angle-axis
    D/E coords cameras (CameraObjectClass_Create) and the embedded NiCamera
    sets, whose Gamebryo camera frame (-Z view axis) is converted into this
    convention by CameraObjectClass_CreateFromNiCamera. So world-forward is
    GetCol(1) and world-up is GetCol(2) here, uniformly.

    fov_y is derived from the _NiFrustum top/bottom + near as
    2*atan(((top-bottom)/2)/near); a degenerate frustum falls back to the bridge
    base FOV.
    """
    eye = tuple(cam.position)
    R = cam.orientation
    fwd = R.GetCol(1)
    up = R.GetCol(2)
    target = (eye[0] + fwd.x, eye[1] + fwd.y, eye[2] + fwd.z)
    up_t = (up.x, up.y, up.z)

    near = cam.GetNearDistance()
    far = cam.GetFarDistance()
    fov = _BridgeCamera.FOV_Y_RAD          # sane default for degenerate frustum
    fr = cam.GetNiFrustum()
    if fr is not None:
        half_h = (fr.m_fTop - fr.m_fBottom) * 0.5
        if half_h > 1e-6 and near > 1e-6:
            fov = 2.0 * _math.atan(half_h / near)
    return eye, target, up_t, fov, near, far


def _comm_feed_view(cam, get_bounds):
    """Resolve the comm viewscreen camera view from the set's authored camera.

    Returns (eye, target, up, fov_y_rad, near, far) in game units, framed by the
    camera's authored orientation (CameraObjectClass.orientation — the faithful
    NiCamera shot for embedded-camera sets, the explicit angle-axis pose for the
    D/E coords-fallback cameras).

    ``get_bounds`` is a 0-arg callable returning the comm room geometry's
    (x, y, z, radius) bounds or None. It is consulted ONLY as a graceful fallback
    when the authored orientation is degenerate (a zero/uninitialised matrix
    yields no view direction), in which case the camera aims at the room centre
    so the set is still framed. This replaced the former unconditional
    aim-at-centre hack, which ignored the authored orientation entirely."""
    eye, target, up, fov, near, far = _comm_camera_params(cam)
    fwd_len = _math.sqrt(sum((target[i] - eye[i]) ** 2 for i in range(3)))
    if fwd_len < 1e-6:                       # degenerate orientation -> aim at centre
        b = get_bounds()
        if b:
            target = (b[0], b[1], b[2])
            up = (0.0, 0.0, 1.0)
    return eye, target, up, fov, near, far


def _apply_bridge_player_visibility(r, player_iid, *, is_bridge, spv_open) -> None:
    """Hide the player ship while in bridge view so it doesn't appear on its
    own viewscreen feed (and the centre-mounted forward cam doesn't clip its
    hull). No-op while the Ship Property Viewer owns the frame (it manages
    visibility itself). Idempotent — safe to call every frame."""
    if spv_open or player_iid is None:
        return
    r.set_visible(player_iid, not is_bridge)


def _wire_target_menu_to_player_set(controller) -> None:
    """Subscribe the target-menu singleton to the player's containing
    spatial set, then bulk-rebuild rows for ships already there.

    Idempotent. Called once at startup AND from controller.post_load_hook
    after every mission swap (reset_sdk_globals clears the singleton and
    unwires the previous subscription, so a fresh wire is required).

    The player's _containing_set is the spatial set the mission added
    them to (e.g. "Biranu1") — NOT the "bridge" set, which in this
    codebase holds the bridge-interior ObjectClass and is enumerated
    by the renderer's bridge pass.
    """
    import App as _App
    if _App.STTargetMenu_GetTargetMenu() is None:
        _App.STTargetMenu_CreateW("Targets")
    spatial_set = None
    if controller.session is not None and controller.session.player is not None:
        spatial_set = getattr(controller.session.player, "_containing_set", None)
    if spatial_set is None:
        return
    from engine.appc.target_menu import wire_to_bridge_set
    wire_to_bridge_set(spatial_set)
    menu = _App.STTargetMenu_GetTargetMenu()
    if menu is not None:
        menu.RebuildShipMenus(spatial_set)
        menu.ResetAffiliationColors()


def _sync_instance_transforms(r, session, player, xform_buf, interp_alpha,
                              game_time, model_scale) -> None:
    """Push ship + planet world transforms to the renderer for one frame.

    Player ship: pushed live (it is integrated per render frame on
    wall-clock dt in _PlayerControl, so it is already smooth in world
    space).

    Non-player ships: integrated on the fixed 60 Hz tick, so they are
    rendered at lerp(prev, cur, interp_alpha) to hide the discrete
    steps. xform_buf.roll() ran earlier this frame (only when a tick
    fired); here we capture the new current state and push the
    interpolated pose. This only affects what is sent to the renderer —
    the ship objects keep live transforms, so physics/AI/combat (which
    ran earlier this frame) are unaffected.

    Also ages each ship's glow controller on `game_time` (the same game
    clock the decal system ages on, engine.appc.damage_decals), drops
    self-illumination for out-of-action hulks, prunes the transform
    buffer + dead glow controllers, and pushes planet transforms.
    `model_scale` is BC_MODEL_SCALE; non-player ships additionally
    multiply by their live GetScale().
    """
    # player is always set when a session exists, so _player_iid is a
    # real iid (never None) at runtime.
    _player_iid = session.ship_instances.get(player)
    _live_ship_iids = []
    for ship, iid in session.ship_instances.items():
        _wg = session.ship_glow_controllers.get(iid)
        if _wg is not None:
            _wg.update(game_time)
        # Destroyed (dying/dead) ships lose self-illumination —
        # a dark hulk in space. Hull stays lit by external light.
        r.set_emissive_scale(iid, 0.0 if _oa(ship) else 1.0)
        if iid == _player_iid:
            r.set_world_transform(
                iid, _ship_world_matrix(ship, model_scale))
            continue
        _live_ship_iids.append(iid)
        # NOTE: scale is read live, not interpolated — the
        # buffer only stores loc+rot. Fine for steady scale;
        # a mid-animation GetScale() change applies the
        # current scale to the blended pose (imperceptible).
        try:
            _ps = float(ship.GetScale())
        except Exception:
            _ps = 1.0
        xform_buf.set_current(
            iid, ship.GetWorldLocation(), ship.GetWorldRotation())
        _sampled = xform_buf.sample(iid, interp_alpha)
        _iloc, _irot = _sampled
        r.set_world_transform(
            iid, _world_matrix_from(_iloc, _irot, model_scale * _ps))
    xform_buf.prune(_live_ship_iids)
    # Drop controllers for instances no longer present. The
    # player iid is excluded from _live_ship_iids (handled by
    # the continue above), so key the keep-set on the full
    # live ship_instances values, not _live_ship_iids.
    _wg_live_iids = set(session.ship_instances.values())
    for _dead in list(session.ship_glow_controllers.keys()):
        if _dead not in _wg_live_iids:
            del session.ship_glow_controllers[_dead]
    for planet, iid in session.planet_instances.items():
        ns = session.planet_natural_scale.get(planet, 1.0)
        r.set_world_transform(iid, _astro_world_matrix(planet, ns))


def run(mission_name: Optional[str] = None,
        max_ticks: Optional[int] = None) -> int:
    """Boot the renderer, init the named mission, run until the window closes
    or max_ticks is reached. Returns 0 on clean exit.

    Mission resolution: ``mission_name`` argument wins; otherwise
    ``SHIP_GATE_MISSION`` (the default M2Objects ship-gate mission).

    Debug knobs (env vars):
      OPEN_STBC_HOST_HEADLESS=1     — hide the window (used by tests).
      OPEN_STBC_HOST_VERBOSE=1      — print loaded ships, player position,
                                      camera state on the first tick.
      OPEN_STBC_HOST_FIXED_CAMERA=1 — ignore third-person follow; use a
                                      fixed camera at (0, 0, 150) looking
                                      at the world origin.
    """
    import os as _os
    verbose = _os.environ.get("OPEN_STBC_HOST_VERBOSE") == "1"
    fixed_camera = _os.environ.get("OPEN_STBC_HOST_FIXED_CAMERA") == "1"
    if mission_name is None:
        mission_name = SHIP_GATE_MISSION

    _setup_sdk()

    import App
    from engine.core.loop import GameLoop
    # Hoisted out of the per-tick loop body — imported once per run()
    # rather than every frame. Both are only used inside the loop below.
    from engine.appc import collisions
    from engine.appc import camera_shake

    r.init(1280, 720, "open_stbc")
    # Initialise the CEF UI overlay. Resolves index.html relative
    # to the project root (two parents up from this file). _CEF_VIEW_W/H
    # are reused by the pause-menu mouse-forwarding path to scale
    # framebuffer-pixel cursor coords back into the OSR view's logical
    # pixel space on Retina.
    _CEF_VIEW_W, _CEF_VIEW_H = 1280, 720
    _cef_html = _project_root_for_cef() / "native" / "assets" / "ui-cef" / "index.html"
    # Detect the framebuffer's device-pixel ratio so CEF renders at
    # high-DPI density on Retina. Without this, the composite pass
    # bilinear-upscales a 1280x720 bitmap to the 2560x1440 framebuffer
    # and text reads as soft/blurry.
    _cef_dsf = 1.0
    try:
        import _dauntless_host as _h_init
        _fb_w, _fb_h = _h_init.framebuffer_size()
        _win_w, _win_h = _h_init.window_size()
        if _win_w > 0:
            _cef_dsf = float(_fb_w) / float(_win_w)
    except Exception as _e:
        dev_mode.log_swallowed("CEF device-pixel-ratio probe", _e)
    if not r.cef_initialize(_CEF_VIEW_W, _CEF_VIEW_H, str(_cef_html),
                            device_scale_factor=_cef_dsf):
        # Non-fatal in builds where CEF is disabled (the stub returns False).
        # If CEF is enabled and initialize failed, the binary will print the
        # framework-load error to stderr — surface it but keep running so the
        # 3D scene still renders.
        import sys as _sys
        print("[host_loop] cef_initialize returned False — overlay disabled",
              file=_sys.stderr)
    try:
        # Controller owns the renderer, the nif-handle cache, and the
        # current mission session. _MissionLoader.load() runs the
        # mission init + scene build; HostController.swap_mission()
        # queues a deferred swap that drains at the next tick.
        controller = HostController()
        controller.renderer = r
        controller.loader = _MissionLoader(controller, verbose=verbose)

        # Register the bridge cutscene controller BEFORE the initial mission
        # load so that TGAnimActions created during Initialize()/Briefing()
        # find a live controller and defer correctly (not instant-complete).
        # The controller stays registered for the lifetime of run(); mission
        # swaps reuse it without re-registering.
        from engine.bridge_cutscene import (
            BridgeCutsceneController, set_controller,
        )
        cutscene = BridgeCutsceneController()
        set_controller(cutscene)

        # Bridge interior is created by the SDK path (LoadBridge.Load ->
        # Bridge.<name>.CreateBridgeModel) during the mission load below, then
        # realized into a render instance by realize_all_sets in
        # _after_mission_loaded. No eager pre-game load — the SDK is the single
        # source of the bridge mesh.

        controller.session = controller.loader.load(mission_name)
        if verbose:
            ss = controller.session
            print(f"[host_loop] mission={mission_name}", flush=True)
            total = len(ss.ship_instances) + len(ss.planet_instances)
            print(f"[host_loop] {total} render instance(s) created "
                  f"({len(ss.ship_instances)} ships, "
                  f"{len(ss.planet_instances)} planets)", flush=True)

        # Per-tick player input → ship-transform integrator.
        player_control = _PlayerControl()
        from engine.cameras import _CameraDirector
        director       = _CameraDirector()
        z_held_prev = False
        v_held_prev = False
        if controller.session is not None and controller.session.player is not None:
            _r = controller.session.player.GetRadius()
            director.chase.set_ship_radius(_r)
            director.tracking.set_ship_radius(_r)
        view_mode      = _ViewModeController()
        pause          = _PauseMenuController()
        from engine.ui.target_list_view import TargetListView
        from engine.ui.sensors_panel import SensorsPanel
        target_list_view = TargetListView()
        sensors_panel = SensorsPanel()

        # Wire (and re-wire on mission swap) the target-menu singleton
        # to the player's spatial set. controller.post_load_hook fires
        # after every successful loader.load() — both the initial load
        # and any pending_swap drain — so this hook keeps the target
        # list pointed at the current mission's ship roster.
        def _after_mission_loaded():
            # The mission's own StartMission calls the real SDK
            # LoadBridge.Load(name) during loader.load(), creating the "bridge"
            # SetClass + crew via the SDK path against loud stubs. Realize the
            # bridge objects below, then print the loud stub summary so any
            # still-unimplemented SDK surface is visible.
            # Step 5a: take the captain's-chair eye + zoom params from the SDK
            # maincamera (config-driven; replaces the hardcoded offsets table).
            global _BRIDGE_CAMERA_EYE, _BRIDGE_ZOOM_MIN, _BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_TIME
            import App as _App
            _bridge = _App.g_kSetManager.GetSet("bridge")
            _cam = _bridge.GetCamera("maincamera") if _bridge is not None else None
            if _cam is not None and hasattr(_cam, "position"):
                _BRIDGE_CAMERA_EYE = _cam.position
                _BRIDGE_ZOOM_MIN = _cam.GetMinZoom()
                _BRIDGE_ZOOM_MAX = _cam.GetMaxZoom()
                _BRIDGE_ZOOM_TIME = _cam.GetZoomTime()
            # Realize every SDK-created set (the player bridge + any comm/
            # remote sets) into render instances. The bridge is realized as
            # is_bridge=True; comm sets with geometry/characters as False.
            realize_all_sets(controller, r)
            _wire_target_menu_to_player_set(controller)
        controller.post_load_hook = _after_mission_loaded

        bridge_camera  = _BridgeCamera()

        _after_mission_loaded()
        try:
            import _dauntless_host as _h
        except ImportError:
            _h = None  # bindings module not built; skip input handling.

        # Dev-only mission picker construction. Done BEFORE
        # default_pause_menu(...) so register_dev_pause_menu_entry
        # adds the "Load Mission…" row before the menu is built.
        # PanelRegistry registration happens further down, after
        # PanelRegistry itself exists.
        # See docs/superpowers/specs/2026-06-02-dev-mission-loader-design.md.
        mission_picker = _NULL_PICKER  # noop until we know dev mode is on
        developer_options_panel = _NULL_PICKER  # noop until dev mode confirmed
        ship_property_viewer = _NULL_PICKER  # noop until dev mode confirmed
        if dev_mode.is_enabled():
            _picker_registry_cache: list = [None]
            def _get_mission_registry():
                if _picker_registry_cache[0] is None:
                    from pathlib import Path
                    project_root = Path(__file__).resolve().parent.parent
                    sdk_scripts = project_root / "sdk" / "Build" / "scripts"
                    _picker_registry_cache[0] = _missions.discover(sdk_scripts)
                return _picker_registry_cache[0]

            def _on_pick_mission(module_name: str) -> None:
                controller.swap_mission(module_name)
                pause.close()

            mission_picker = MissionPicker(
                registry_getter=_get_mission_registry,
                on_pick=_on_pick_mission,
            )
            dev_mode.register_dev_pause_menu_entry(
                "Load Mission…", mission_picker.open,
            )

            from engine.ui.developer_options_panel import DeveloperOptionsPanel
            developer_options_panel = DeveloperOptionsPanel()
            dev_mode.register_dev_pause_menu_entry(
                "Developer Options…", developer_options_panel.open,
            )

            # Ship Property Viewer — dev-only orbiting hologram inspector.
            # ship_getter returns the live player ship (same object the
            # render block maps to a render InstanceId via
            # session.ship_instances), or None between missions.
            from engine.ui.ship_property_viewer_panel import (
                ShipPropertyViewerPanel,
            )
            def _spv_player():
                sess = controller.session
                return sess.player if sess is not None else None
            ship_property_viewer = ShipPropertyViewerPanel(
                ship_getter=_spv_player,
            )
            dev_mode.register_dev_pause_menu_entry(
                "Ship Property Viewer", ship_property_viewer.open,
            )

        # Configuration panel — production-visible pause-menu modal
        # exposing the Graphics tab (dust, specular, FOV). Settings
        # apply live; no persistence in this iteration. Construction
        # uses the live director FOV so opening the panel doesn't lie
        # about the current value.
        from engine.ui.configuration_panel import (
            ConfigurationPanel, SettingsSnapshot,
        )
        from engine.appc import crew_speech as _crew_speech
        configuration_panel = ConfigurationPanel(
            tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay")],
            initial_settings=SettingsSnapshot(
                dust_on=True,
                specular_on=True,
                hdr_on=True,
                rim_on=True,
                decals_on=True,
                hull_damage_on=True,
                fxaa_on=True,
                fov_deg=int(round(_math.degrees(
                    director.fov_y_rad
                ))),
                subtitles_on=_crew_speech.subtitles_enabled(),
            ),
            set_dust=r.set_dust_enabled,
            set_specular=r.set_specular_enabled,
            set_hdr=r.set_hdr_enabled,
            set_rim=r.set_rim_enabled,
            set_decals=r.set_decals_enabled,
            set_hull_damage=r.set_hull_damage_enabled,
            set_fxaa=r.set_fxaa_enabled,
            set_subtitles=_crew_speech.set_subtitles_enabled,
            set_fov_rad=director.set_fov,
        )

        from engine.ui.pause_menu import default_pause_menu
        from engine.ui.panel_registry import PanelRegistry
        pause_menu = default_pause_menu(
            on_exit=pause.request_quit,
            on_configuration=configuration_panel.open,
            on_resume=pause.close,
        )
        registry = PanelRegistry(legacy_handler=pause_menu.dispatch_event)
        controller.panel_registry = registry  # expose to _drain_pending_swap
        registry.register(target_list_view)
        registry.register(sensors_panel)
        from engine.appc.sdk_mirror_panel import SDKMirrorPanel
        sdk_mirror = SDKMirrorPanel()
        registry.register(sdk_mirror)
        from engine.ui.crew_menu_panel import CrewMenuPanel
        crew_menu_panel = CrewMenuPanel()
        registry.register(crew_menu_panel)
        try:
            from engine.ui import crew_menu_hotkeys
            crew_menu_hotkeys.wire(
                App.TacticalControlWindow_GetTacticalControlWindow(),
                crew_menu_panel)
        except Exception as _e:
            print(f"[host_loop] WARNING: crew_menu_hotkeys.wire() failed: {_e}",
                  flush=True)
        from engine.ui.info_box_panel import InfoBoxPanel
        info_box_panel = InfoBoxPanel()
        registry.register(info_box_panel)
        registry.register(configuration_panel)
        if dev_mode.is_enabled():
            registry.register(mission_picker)
            registry.register(developer_options_panel)
            registry.register(ship_property_viewer)

        # SDK ShipDisplay factories register against this same registry.
        # In stock BC, Bridge/TacticalMenuHandlers.py:517,714 invokes
        # App.ShipDisplay_Create twice during tactical-UI construction.
        # That path doesn't yet run in our host loop, so we construct
        # the two panels eagerly here. Each panel resolves its bound
        # ship via MissionLib.GetPlayer / player.GetTarget on every
        # render — no SetShipID is needed.
        from engine.sdk_ui.widgets.ship_display import (
            set_panel_registry,
            _reset_for_bridge_teardown,
            ShipDisplay_Create,
        )
        _reset_for_bridge_teardown()  # belt-and-braces: clear any stale state
        set_panel_registry(registry)  # inject the live registry
        ship_display_player = ShipDisplay_Create()  # ROLE_PLAYER, registers
        ship_display_target = ShipDisplay_Create()  # ROLE_TARGET, registers

        # WeaponsDisplay — player-only panel rendering the per-bank
        # phaser arc icons + indicators over a small centred silhouette
        # (SDK's Tactical/Interface/WeaponsDisplay.py reproduction).
        # Its header doubles as BC's speed readout, replacing the
        # standalone SpeedDisplay panel — the original game used the
        # WeaponsDisplay title for the "Speed {imp} : {vel} kph"
        # text (see BridgeHandlers.HelmUpdateToolTip in the SDK).
        from engine.ui.weapons_display_panel import WeaponsDisplayPanel
        weapons_display = WeaponsDisplayPanel(player_control=player_control)
        registry.register(weapons_display)

        # Bindings older than the orbit-camera change won't expose
        # consume_scroll_y; fall back to a zero-delta lambda so host_loop
        # still runs against an old _dauntless_host.so without rebuilding.
        _consume_scroll = getattr(_h, "consume_scroll_y", None) if _h else None
        # Newer bindings expose CEF mouse-forwarding + a JS→Python event
        # channel; older builds fall back to no-ops so the pause menu
        # still navigates by keyboard.
        _cef_send_mouse_move  = getattr(_h, "cef_send_mouse_move",  None) if _h else None
        _cef_send_mouse_click = getattr(_h, "cef_send_mouse_click", None) if _h else None
        # Window-resize forwarding: re-lay-out the OSR overlay when the
        # window changes size (older builds lack it -> overlay stays at its
        # init size and stretches, the prior behaviour).
        _cef_resize = getattr(_h, "cef_resize", None) if _h else None
        _cef_set_event_handler = getattr(_h, "cef_set_event_handler", None) if _h else None
        if _cef_set_event_handler is not None:
            _cef_set_event_handler(registry.dispatch)
        _cef_set_load_end = getattr(_h, "cef_set_load_end_handler", None) if _h else None
        if _cef_set_load_end is not None:
            def _on_cef_load_end():
                # Drop snapshot caches so next tick re-emits state. Handles
                # both initial load and Cmd+R reloads.
                registry.invalidate_all()
                # Publish the dev flag to JS/HTML on every document load.
                # When off we leave window.__DAUNTLESS_DEV__ undefined and
                # body[data-dev] unset so CSS hides .dev-only elements by
                # default (fails closed if this push is ever missed).
                if dev_mode.is_enabled() and _h is not None:
                    _h.cef_execute_javascript(
                        "window.__DAUNTLESS_DEV__ = true;"
                        " document.body.dataset.dev = '1';"
                    )
            _cef_set_load_end(_on_cef_load_end)
        TICK_DT = 1.0 / 60.0
        MAX_FRAME_DT = 0.25  # Fiedler spiral-of-death cap

        loop = GameLoop()
        ticks = 0
        init_audio()
        _bootstrap_firing_pipeline()

        # Fixed-timestep accumulator state — sim runs at TICK_DT (60 Hz)
        # regardless of render refresh rate. See engine/core/timestep.py.
        import time
        from engine.core.timestep import step_accumulator
        _previous_real_time = time.monotonic()
        _accumulator = 0.0
        from engine.core.transform_buffer import TransformBuffer
        _xform_buf = TransformBuffer()

        # Ship Property Viewer (dev-only) transition state. _spv_hidden_iid
        # remembers which solid hull was hidden so it can be restored, and
        # _spv_was_open detects the open→closed edge so restore/clear runs
        # exactly once. Both stay None/False when the viewer is never opened,
        # so the render path is byte-identical in production.
        _spv_hidden_iid = None
        _spv_was_open = False

        # Ordered modal blockers (highest priority first). Each is a CEF
        # panel exposing is_open()/handle_key_esc(); the keyboard-input
        # ones (developer options, ship property viewer, configuration)
        # also expose handle_input(). The mission picker is click-only.
        # In production (no --developer) the first three are _NULL_PICKER
        # whose is_open() is False, so they never fire. One list drives
        # ESC routing, pause-menu visibility, and pause-input routing.
        _modal_blockers = [mission_picker, developer_options_panel,
                           ship_property_viewer, configuration_panel]

        while not r.should_close():
            # --- Track window resizes: re-lay-out the CEF overlay at the new
            # size so it reflows instead of being stretched. Guarded so
            # WasResized only fires when the logical size or DPR actually
            # changes; _CEF_VIEW_W/H stay authoritative for mouse-forward
            # scaling and the panel-corner layout math below.
            if _cef_resize is not None and _h is not None:
                try:
                    _fbw, _fbh = _h.framebuffer_size()
                    _wnw, _wnh = _h.window_size()
                    _delta = _compute_cef_resize(
                        _fbw, _fbh, _wnw, _wnh,
                        _CEF_VIEW_W, _CEF_VIEW_H, _cef_dsf)
                    if _delta is not None:
                        _CEF_VIEW_W, _CEF_VIEW_H, _cef_dsf = _delta
                        _cef_resize(_CEF_VIEW_W, _CEF_VIEW_H,
                                    device_scale_factor=_cef_dsf)
                except Exception as _e:
                    dev_mode.log_swallowed("CEF window-resize forward", _e)

            # --- Input dispatch + modality (ESC always live; SPACE only when unpaused) ---
            # _apply_view_mode_side_effects mirrors the SPACE flag into
            # renderer state (bridge pass enable + cursor lock) and is
            # idempotent — only fires when the mode changed.
            if _h is not None:
                # ESC priority: mission picker first (dev only), then the
                # developer options panel (dev only), then the ship property
                # viewer (dev only), then the configuration panel, then the
                # crew menu, otherwise the pause menu toggle. All four modal
                # blockers close on ESC and return the user to the pause menu.
                _dispatch_modal_esc(_modal_blockers, crew_menu_panel, pause, _h)
                _apply_pause_menu_side_effects(
                    pause, view_mode, _h, _modal_blockers,
                )
                if pause.is_open:
                    # When a settings modal is open it consumes keyboard
                    # input — pause-menu navigation would otherwise activate
                    # rows hidden behind the modal.
                    _dispatch_modal_pause_input(_modal_blockers, pause_menu, _h)
                    # Forward mouse to CEF only while paused — keeps
                    # normal-gameplay input out of the overlay. The
                    # event-handler callback installed at startup turns
                    # JS clicks into pause_menu.dispatch_event(name).
                    #
                    # cursor_pos() returns FRAMEBUFFER (physical) pixels —
                    # see renderer/window.cc:173-182 — but the CEF OSR
                    # view was initialised in logical pixels (1280x720).
                    # On Retina the two spaces differ by the device-pixel
                    # ratio, so we scale framebuffer → view-space here.
                    # _CEF_VIEW_W/H mirror the dims passed to
                    # cef_initialize above.
                    if _cef_send_mouse_move is not None:
                        _mx, _my = _forward_mouse_to_cef(
                            _h, _cef_send_mouse_move,
                            _CEF_VIEW_W, _CEF_VIEW_H)
                    if _cef_send_mouse_click is not None:
                        if _h.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, True)
                        if _h.mouse_button_released(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, False)
                    if pause.quit_requested:
                        break
                else:
                    # Re-emit the menu's row list on the next open so the
                    # DOM picks it up after the visibility flip (the
                    # contents survive across opens, but a hot-reload of
                    # the page resets them — invalidate every close to be
                    # safe).
                    pause_menu.invalidate()
                    view_mode.apply(_h)
                    _apply_view_mode_side_effects(view_mode, _h)

            # Pump all CEF panels (target list, etc.) every tick. The
            # registry returns only payloads whose state changed since
            # the last call, so this is cheap when nothing's moving.
            #
            # CEF's OnLoadEnd hook (set up at startup via
            # cef_set_load_end_handler) calls registry.invalidate_all
            # once when the page is ready, so the next render_all
            # re-emits even though state hasn't changed since the
            # previous tick. No per-tick retry needed.
            if _h is not None:
                # Target list only renders in the exterior tactical view.
                # SPACE toggles view_mode.is_exterior ↔ view_mode.is_bridge.
                # The setter is idempotent so writing every tick is cheap.
                # The Ship Property Viewer takes over the whole frame, so hide
                # the tactical panels while it's open (as bridge view does).
                # _NULL_PICKER.is_open() is False, so this is a no-op in
                # production / non-dev.
                _tac_visible = view_mode.is_exterior and not ship_property_viewer.is_open()
                target_list_view.visible    = _tac_visible
                sensors_panel.visible       = _tac_visible
                ship_display_player.visible = _tac_visible
                ship_display_target.visible = _tac_visible
                weapons_display.visible     = _tac_visible

                # Sensor-visibility update — flip per-row IsVisible
                # based on range from the player. TargetListView
                # filters rows where IsVisible() == 0. We walk the
                # player's spatial set (e.g. "Biranu1"), not the
                # bridge set (which holds bridge-interior objects).
                _menu = App.STTargetMenu_GetTargetMenu()
                _game = Game_GetCurrentGame()
                _player = _game.GetPlayer() if _game is not None else None
                _player_set = getattr(_player, "_containing_set", None) if _player is not None else None
                if _menu is not None and _player is not None and _player_set is not None:
                    update_target_list_visibility(
                        _menu, _player_set.GetObjectList(), _player
                    )

                _scripts = registry.render_all()
                for _panel_script in _scripts:
                    _h.cef_execute_javascript(_panel_script)

                # Forward mouse to CEF outside the pause overlay so
                # non-pause panels (target list) are clickable. The
                # pause-open branch above already forwards mouse for
                # the pause menu's own clicks; here we cover the
                # unpaused path. cursor_pos returns framebuffer pixels;
                # convert to CEF view space (same scaling as the paused
                # branch).
                #
                # Click forwarding consumes the mouse-button edge state
                # (mouse_button_released advances g_prev_mouse_state in
                # the bindings), so if we forward unconditionally the
                # _poll_mouse_buttons call below never sees the LEFT
                # edge — phasers stop firing. Gate click forwarding on
                # the cursor being inside the target-list panel's
                # bounding box: cursor over panel → CEF gets the click
                # (and firing doesn't); cursor anywhere else → firing
                # gets the click. mouse_move forwarding stays
                # unconditional because it doesn't touch button state
                # and the panel needs it for CSS :hover.
                if not pause.is_open and _cef_send_mouse_move is not None:
                    _mx, _my = _forward_mouse_to_cef(
                        _h, _cef_send_mouse_move,
                        _CEF_VIEW_W, _CEF_VIEW_H)
                    # Panel bboxes in CEF view space. Click forwarding is
                    # gated on these because forwarding consumes the
                    # mouse-button edge state — see the rationale comment
                    # above. Bboxes track the layout zones defined in
                    # global.css; new panels need a bbox here or their
                    # buttons will silently swallow clicks.
                    #
                    # Left column (#tactical-left-column): position:fixed;
                    # top:24px; left:24px; bottom:24px; width:224px.
                    # Hosts target ship-display, target list, and radar
                    # — one bbox covers all three.
                    _LC_X, _LC_Y = 24, 24
                    _LC_W = 224
                    _LC_H = _CEF_VIEW_H - 24 - _LC_Y  # to bottom:24
                    _cursor_in_left_column = (
                        (target_list_view.visible or sensors_panel.visible
                         or ship_display_target.visible)
                        and _LC_X <= _mx < _LC_X + _LC_W
                        and _LC_Y <= _my < _LC_Y + _LC_H
                    )
                    # Bottom row (#tactical-bottom-row): position:fixed;
                    # right:0; bottom:0; padding:0 12px 12px 0;
                    # justify-content:flex-end. Panels stack right→left;
                    # bbox right-edge = view_w - 12 (padding). Width
                    # covers speed (12vw min 160) + 12px gap + player
                    # ship-display (16vw min 220) + a little slack.
                    # Speed itself isn't clickable but the cursor passing
                    # over it shouldn't fire phasers; widen the bbox to
                    # silently swallow those clicks.
                    _BR_W, _BR_H = 420, 360
                    _BR_X = _CEF_VIEW_W - 12 - _BR_W
                    _BR_Y = _CEF_VIEW_H - 12 - _BR_H
                    _cursor_in_bottom_row = (
                        (ship_display_player.visible
                         or weapons_display.visible)
                        and _BR_X <= _mx < _BR_X + _BR_W
                        and _BR_Y <= _my < _BR_Y + _BR_H
                    )
                    _cursor_in_panel = (
                        _cursor_in_left_column or _cursor_in_bottom_row
                    )
                    if _cef_send_mouse_click is not None and _cursor_in_panel:
                        if _h.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, True)
                        if _h.mouse_button_released(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, False)

            # --- Sim advance: fixed-timestep accumulator ---
            # frame_dt is the real wall-clock since the previous frame.
            # During pause we force it to 0 so the accumulator cannot
            # grow and there is no catch-up burst on resume. The cap
            # bounds the inner while-loop after a stalled render frame.
            _now = time.monotonic()
            _frame_dt = _now - _previous_real_time
            _previous_real_time = _now
            if pause.is_open:
                _frame_dt = 0.0
            _accumulator, _sim_ticks_this_frame = step_accumulator(
                _accumulator, _frame_dt, TICK_DT, MAX_FRAME_DT
            )
            # Per-render-frame delta for the player input integrator.
            # _apply_input runs once per render frame, so its dt must
            # be the wall-clock delta since the last frame — not the
            # fixed sim TICK_DT. Otherwise at 120 Hz monitor refresh
            # the player ship rotates / accelerates 2× too fast (BC
            # Galaxy 360° yaw collapses from 24 s to 12 s). Clamp
            # matches step_accumulator's spiral-of-death cap so a
            # stalled frame doesn't teleport the player.
            _player_dt = 0.0 if pause.is_open else min(max(_frame_dt, 0.0), MAX_FRAME_DT)
            _interp_alpha = _accumulator / TICK_DT  # in [0, 1) after step_accumulator
            if _sim_ticks_this_frame > 0:
                _xform_buf.roll()
            for _ in range(_sim_ticks_this_frame):
                loop.tick()

            # Only snap the camera when a sim tick actually fired —
            # no tick means no state change to follow.
            if _sim_ticks_this_frame > 0:
                had_pending_swap = controller.pending_swap is not None
                # Clear any stale cutscene from the OUTGOING mission BEFORE the
                # drain — the drain runs the incoming mission's Initialize()/
                # Briefing(), which queues that mission's own camera/door
                # requests. Resetting after the drain would wipe the freshly
                # queued walk-on (the camera then never moves).
                if had_pending_swap:
                    cutscene.reset()
                controller._drain_pending_swap()
                if had_pending_swap:
                    director.snap()
                    _xform_buf.reset_all()
            else:
                had_pending_swap = False

            session = controller.session
            player = session.player if session is not None else None
            if had_pending_swap and player is not None:
                _r = player.GetRadius()
                director.chase.set_ship_radius(_r)
                director.tracking.set_ship_radius(_r)

            if not pause.is_open:
                # Dev-mode keybindings (no-op when --developer is not set).
                # register_for_frame re-binds handlers that close over the
                # current player/session each tick; dispatch_dev_key reads
                # _h.key_pressed for every registered key and fires matching
                # handlers. Skipped silently when dev_mode.is_enabled() is False.
                if _h is not None and dev_mode.is_enabled():
                    dev_keybindings.register_for_frame(_h, session, player)
                    for key, _desc in dev_mode.keybinding_descriptions():
                        if _h.key_pressed(key):
                            dev_mode.dispatch_dev_key(key)

                # F12: toggle CEF DevTools for the UI overlay.
                if _h is not None and _h.key_pressed(_h.keys.KEY_F12):
                    _h.cef_toggle_devtools()

                # Cmd+R / Ctrl+R: hot-reload the CEF overlay's HTML.
                # Reload only when Cmd (macOS) or Ctrl (Linux/Windows) is held;
                # bare R is reverse-thrust and must not be intercepted.
                if _h is not None and _h.key_pressed(_h.keys.KEY_R):
                    _cmd_held = _h.key_state(_h.keys.KEY_LEFT_SUPER) if hasattr(_h.keys, "KEY_LEFT_SUPER") else False
                    _ctrl_held = _h.key_state(_h.keys.KEY_LEFT_CONTROL) if hasattr(_h.keys, "KEY_LEFT_CONTROL") else False
                    if _cmd_held or _ctrl_held:
                        _h.cef_reload()

                # Apply keyboard input to the player ship's transform and to the
                # orbit camera. Scroll delta is consumed once per tick; old
                # bindings without the binding return 0.0 via the fallback.
                scroll_y = _consume_scroll() if _consume_scroll is not None else 0.0

                if player is not None and _h is not None:
                    # Alert keys (Shift+1/2/3) run before the throttle handler;
                    # _PlayerControl.apply checks _shift_held() to skip digit
                    # throttling on the same press.
                    _apply_alert_keys(_h, player)
                    # C-key: toggle Chase ↔ Tracking (only enters Tracking if
                    # the player has a valid target). key_pressed fires once per
                    # key-down event (not while held). Gate on exterior view so
                    # the mode cannot flip silently while the bridge is active.
                    if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_C):
                        director.toggle_mode(player=player)
                    # Z-key: ZoomTarget framing while held. Held-state (not
                    # press-edge) so the camera enters/exits as the key state
                    # changes. The `not director.tracking.zoom_target_active`
                    # retry guard lets a Z-held-during-target-acquisition
                    # succeed on whichever frame the target appears.
                    z_held_now = view_mode.is_exterior and _h.key_state(_h.keys.KEY_Z)
                    if z_held_now and not director.tracking.zoom_target_active:
                        director.start_zoom_target(player=player)
                    elif z_held_prev and not z_held_now:
                        director.end_zoom_target()
                    z_held_prev = z_held_now
                    # =/- sticky zoom: press-edge (OS auto-repeat for hold).
                    if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_EQUAL):
                        director.zoom_in()
                    if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_MINUS):
                        director.zoom_out()
                    # V-key: Reverse Chase while held. Same hold-state
                    # edge detection as Z, with a retry guard so a
                    # V-held-during-mode-transition succeeds on the
                    # next eligible frame.
                    v_held_now = view_mode.is_exterior and _h.key_state(_h.keys.KEY_V)
                    if v_held_now and not director.chase.reverse_active:
                        director.start_reverse()
                    elif v_held_prev and not v_held_now:
                        director.end_reverse()
                    v_held_prev = v_held_now
                    # Shift+mouse: orbit yaw/pitch additive on top of
                    # arrow keys. Drain the mouse delta unconditionally
                    # in exterior view so non-Shift mouse motion doesn't
                    # accumulate and snap the camera on the next Shift
                    # press.
                    mouse_dx_exterior, mouse_dy_exterior = 0.0, 0.0
                    if view_mode.is_exterior:
                        mouse_dx_exterior, mouse_dy_exterior = _h.consume_mouse_delta()
                    shift_held = view_mode.is_exterior and (
                        _h.key_state(_h.keys.KEY_LEFT_SHIFT) or
                        _h.key_state(_h.keys.KEY_RIGHT_SHIFT)
                    )
                    if shift_held and director.mode is CameraMode.CHASE:
                        director.chase.apply_mouse_delta(
                            mouse_dx_exterior, mouse_dy_exterior)
                    # dt = _player_dt (wall-clock frame delta), not TICK_DT —
                    # see comment at the accumulator step. _apply_input fires
                    # once per render frame, so its dt is the wall delta.
                    _apply_input(view_mode, player_control, director,
                                 player=player, dt=_player_dt, h=_h,
                                 scroll_y=scroll_y)

                # Forward mouse button edges into the input manager (fire
                # events route via g_kKeyboardBinding → TCW handlers).
                _poll_mouse_buttons(_h)
                _poll_function_keys(_h)

                # Advance weapon charge / reload for every ship in every
                # active set.  Runs after AI/physics (approximate — the host
                # loop is single-threaded and Python AI runs in the gameloop
                # tick above) so emitters are ready when AI fire calls land.
                # Materialize the ship list once per frame — both consumers
                # re-walked every set independently before.
                _ships_this_tick = list(_all_ships_for_tick())
                _advance_weapons(_ships_this_tick, TICK_DT)
                _advance_combat(
                    _ships_this_tick, TICK_DT, host=_h,
                    ship_instances=(session.ship_instances if session is not None else None),
                )

                # Collision detection + response (ships/asteroids/moons/
                # planets). Runs once per render frame after motion + player
                # input, so every body's post-thrust position is current.
                # Reuses combat.apply_hit for impact damage; injects a
                # mass-weighted impulse into each body's decaying
                # _collision_velocity overlay. Spec
                # docs/superpowers/specs/2026-06-11-collision-response-design.md.
                # dt = _player_dt (clamped wall-clock frame delta), matching
                # the player integrator — the collision-velocity overlay is
                # real-time motion, so it advances/decays on real elapsed time,
                # not the fixed sim TICK_DT.
                collisions.tick_collisions(
                    _player_dt, host=_h,
                    ship_instances=(session.ship_instances if session is not None else None),
                )

                # Sync transforms for known instances.
                #
                # Player ship: pushed live (it is integrated per render
                # frame on wall-clock dt in _PlayerControl, so it is
                # already smooth in world space).
                #
                # Non-player ships: integrated on the fixed 60 Hz tick,
                # so they are rendered at lerp(prev, cur, _interp_alpha)
                # to hide the discrete steps. _xform_buf.roll() ran above
                # before this frame's ticks (only when a tick fired); here
                # we capture the new current state and push the interpolated
                # pose. This only affects what is sent to the renderer — the
                # ship objects keep live transforms, so physics/AI/combat
                # (which ran earlier this frame) are unaffected.
                if session is not None:
                    # Same game clock the decal system ages on
                    # (engine.appc.damage_decals). Read once per frame.
                    _sync_instance_transforms(
                        r, session, player, _xform_buf, _interp_alpha,
                        App.g_kUtopiaModule.GetGameTime(), BC_MODEL_SCALE)

            # --- Render (always runs, including while paused) ---
            # Camera: orbit + zoom around the player ship (or origin fallback).
            if fixed_camera:
                fixed_radius = player.GetRadius() if player is not None else 1.0
                eye = (0.0, 0.0, CAM_MAX_RADII * fixed_radius)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, director,
                    player=player, dt=_player_dt)
                # Camera shake — apply to the exterior view. The bridge
                # first-person camera below gets its own perturb call
                # against the shared shake state.
                eye, target, up_vec = camera_shake.perturb(eye, target, up_vec)
                # If a cutscene camera path is queued or playing, pull the
                # view back to bridge so the update pump below can reach it.
                if cutscene.has_pending_camera() and not pause.is_open:
                    view_mode.set_bridge()
                if view_mode.is_bridge:
                    import App as _App
                    if not pause.is_open:
                        cutscene.update(
                            _player_dt,
                            bridge_camera=bridge_camera,
                            view_mode=view_mode,
                            renderer=r,
                            anim_mgr=_App.g_kAnimationManager,
                        )
                    mouse_dx, mouse_dy = _h.consume_mouse_delta() if _h else (0.0, 0.0)
                    # While paused we still drain the accumulated mouse
                    # delta (so it doesn't snap the look on resume) but
                    # skip the yaw/pitch advance so the bridge camera
                    # stays frozen alongside the rest of the world.
                    if not pause.is_open:
                        bridge_camera.set_zoom_target(
                            _active_zoom_officer_world(crew_menu_panel, r),
                            _player_dt)
                        bridge_camera.apply(mouse_dx, mouse_dy)
                    b_eye, b_target, b_up, b_fov = bridge_camera.compute_camera()
                    # Bridge first-person camera uses separate (eye, target,
                    # up) vectors from the exterior view, so it needs its own
                    # perturb call. The camera_shake module is global state,
                    # so the shake energy / phase is shared with the
                    # exterior perturb above.
                    b_eye, b_target, b_up = camera_shake.perturb(b_eye, b_target, b_up)
                    r.set_bridge_camera(
                        eye=b_eye, target=b_target, up=b_up,
                        fov_y_rad=b_fov,
                        near=_BridgeCamera.NEAR,
                        far=_BridgeCamera.FAR,
                    )
            else:
                eye = (0.0, 30.0, 200.0)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)

            # --- Ship Property Viewer override (dev-only) ---
            # When the viewer is open the world is already frozen (the
            # pause menu zeroes frame_dt → no sim ticks), so we just
            # repoint the camera, hide the solid hull, draw the hologram,
            # and place the subsystem pins. On the open→closed edge we
            # restore the hull and clear the passes exactly once. None of
            # this constructs or runs unless --developer opened the panel,
            # so production rendering is untouched.
            _spv_open = (dev_mode.is_enabled()
                         and ship_property_viewer.is_open()
                         and ship_property_viewer.camera is not None)
            if _spv_open:
                _player_iid_spv = (
                    session.ship_instances.get(player)
                    if session is not None else None
                )
                # On the open edge, frame the orbit camera to the ship's real
                # world-space bounding sphere so it fills the view. The
                # subsystem-centroid fit in open() is only a fallback (it
                # underestimates the hull extent and leaves the ship small).
                if not _spv_was_open and _player_iid_spv is not None:
                    _bounds = r.get_instance_bounds(_player_iid_spv)
                    if _bounds is not None:
                        _bx, _by, _bz, _br = _bounds
                        ship_property_viewer.frame_to_bounds((_bx, _by, _bz), _br)
                # Take over the frame: solid background, no space scene / bridge.
                r.set_hologram_only_mode(True, (0.0, 0.0, 0.0))
                _cam = ship_property_viewer.camera
                r.set_camera(eye=_cam.eye(), target=_cam.target,
                             up=_cam.up(), fov_y_rad=_cam.fov_y_rad,
                             near=_cam.near, far=_cam.far)
                if _player_iid_spv is not None:
                    r.set_visible(_player_iid_spv, False)
                    r.set_hologram_ship(_player_iid_spv)
                r.set_subsystem_pins([
                    (d["world_pos"], d["icon_id"],
                     i == ship_property_viewer.selected_index)
                    for i, d in enumerate(ship_property_viewer.descriptors())
                ])
                # Phaser strip (always) + firing-arc (selected) overlay.
                from engine.ui.phaser_overlay import build_phaser_overlay
                r.set_spv_overlay_beams(
                    build_phaser_overlay(player,
                                         ship_property_viewer.selected_name())
                )
                # The gameplay target reticle is hidden while the viewer owns
                # the frame; it returns on close via the else branch below.
                r.clear_target_reticle()
                r.clear_reticle_text()
                _spv_hidden_iid = _player_iid_spv
            else:
                if _spv_was_open:
                    # open → closed: restore + clear once.
                    if _spv_hidden_iid is not None:
                        r.set_visible(_spv_hidden_iid, True)
                    r.clear_hologram_ship()
                    r.clear_subsystem_pins()
                    r.clear_spv_overlay_beams()
                    r.set_hologram_only_mode(False, (0.0, 0.0, 0.0))
                    _spv_hidden_iid = None
                r.set_camera(eye=eye, target=target, up=up_vec,
                             fov_y_rad=director.fov_y_rad,
                             near=1.0, far=5000.0)
                if player is not None:
                    r.set_target_reticle(build_target_reticle(player))
                    _rcam = _ReticleCam(eye=eye, target=target, up=up_vec,
                                        fov_y_rad=director.fov_y_rad,
                                        near=1.0, far=5000.0)
                    r.set_reticle_text(build_reticle_text(
                        player, _rcam, (_CEF_VIEW_W, _CEF_VIEW_H)))
                else:
                    r.clear_target_reticle()
                    r.clear_reticle_text()
            _spv_was_open = _spv_open

            # Step 5c: drive the viewscreen RTT feed on/off from the realized
            # viewscreen object, and hide the player ship while in bridge view
            # so it doesn't show on its own screen.
            _vs_obj = getattr(controller, "viewscreen_obj", None)
            r.set_viewscreen_enabled(_viewscreen_feed_on(_vs_obj))
            # Comm-set feed: if the viewscreen's remote cam belongs to a comm
            # set, render that set into the RTT from its maincamera; otherwise
            # the RTT keeps the forward space view.
            _feed = _active_comm_feed(controller)
            if _feed is not None:
                _set_id, _cam = _feed
                # Frame the comm set by the camera's AUTHORED orientation (the
                # faithful NiCamera shot, or the D/E explicit angle-axis pose).
                # Aim-at-room-centre survives only as a degenerate-orientation
                # fallback inside _comm_feed_view: a 0-arg bounds getter over the
                # set's first comm instance.
                def _comm_bounds(_set_id=_set_id):
                    _set_name = next((n for n, i in controller.comm_set_ids.items()
                                      if i == _set_id), None)
                    _iids = controller.comm_instances_by_set.get(_set_name, [])
                    if not _iids:
                        return None
                    try:
                        return r.get_instance_bounds(_iids[0])
                    except Exception as _e:
                        dev_mode.log_swallowed("comm get_instance_bounds", _e)
                        return None
                _eye, _tgt, _up, _fov, _near, _far = _comm_feed_view(
                    _cam, _comm_bounds)
                r.set_viewscreen_comm_source(_set_id, _eye, _tgt, _up,
                                             _fov, _near, _far)
            else:
                r.clear_viewscreen_comm_source()
            _player_iid_vs = (session.ship_instances.get(player)
                              if session is not None and player is not None else None)
            _apply_bridge_player_visibility(
                r, _player_iid_vs,
                is_bridge=view_mode.is_bridge, spv_open=_spv_open)

            # Audio listener (skipped while paused — silence the rumble).
            if not pause.is_open:
                # Compute audio listener forward from (eye → target).
                _fx0 = target[0] - eye[0]
                _fy0 = target[1] - eye[1]
                _fz0 = target[2] - eye[2]
                _flen = _math.sqrt(_fx0*_fx0 + _fy0*_fy0 + _fz0*_fz0) or 1.0
                tick_audio(
                    camera_position=eye,
                    camera_forward=(_fx0/_flen, _fy0/_flen, _fz0/_flen),
                    camera_up=up_vec,
                    dt=TICK_DT,
                    player=player,
                )

            active_set = _resolve_active_set(player)

            if not pause.is_open:
                _update_ui_for_tick(player, view_mode, session, active_set)

            ambient, directionals = _aggregate_lights(active_set)
            r.set_lighting(ambient, directionals)

            bridge_ambient, bridge_directionals = _aggregate_bridge_lights()
            # Red-alert dim: bridge ambient scales to 50% when the
            # player ship is at red alert. Matches BC's red-alert
            # bridge lighting (dimmer overall while the red emergency
            # strip lights pulse — that pulse is deferred work).
            if player is not None:
                try:
                    if player.GetAlertLevel() == 2:  # ShipClass.RED_ALERT
                        bridge_ambient = tuple(c * 0.5 for c in bridge_ambient)
                except Exception as _e:
                    dev_mode.log_swallowed("red-alert bridge-dim probe", _e)
            r.set_bridge_lighting(bridge_ambient, bridge_directionals)
            # BC's NiFlipController observes *game time*, not wall time
            # — controllers advance with g_kTimerManager (which the
            # original engine scaled, instrumentation Q3). Feeding wall
            # time made the LCARS animation play noticeably faster than
            # in stock BC; game time matches the original cadence.
            r.set_bridge_wall_time(App.g_kUtopiaModule.GetGameTime())

            # Age every ship's persistent damage-decal ring on the same game
            # clock used for decal birth_time (engine.appc.damage_decals).
            # hasattr-guarded so an older _dauntless_host.so still runs.
            if hasattr(r, "damage_decals_tick"):
                r.damage_decals_tick(App.g_kUtopiaModule.GetGameTime())

            backdrops = _aggregate_backdrops(active_set)
            r.set_backdrops(backdrops)

            suns = _aggregate_suns()
            r.set_suns(suns)

            planets = _aggregate_planets(
                list(App.g_kSetManager._sets.values()))
            r.set_dust_planets(planets)

            lens_flares = _aggregate_lens_flares()
            r.set_lens_flares(lens_flares)

            if verbose and ticks == 0:
                print(f"[host_loop] tick 0 camera eye={eye} target={target}", flush=True)
                print(f"[host_loop] tick 0 lighting ambient={ambient} "
                      f"directionals={directionals}", flush=True)
                print(f"[host_loop] tick 0 backdrops: "
                      f"{len(backdrops)} layer(s)", flush=True)
                print(f"[host_loop] tick 0 suns: {len(suns)} sun(s)", flush=True)
                print(f"[host_loop] tick 0 dust planets: "
                      f"{len(planets)} planet(s)", flush=True)
                print(f"[host_loop] tick 0 lens flares: "
                      f"{len(lens_flares)} flare(s)", flush=True)

            r.frame()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break

        if controller.session is not None:
            controller.session.teardown(r)
    finally:
        shutdown_audio()
        r.cef_shutdown()  # tear down CEF while GL context still alive
        r.shutdown()

    return 0
