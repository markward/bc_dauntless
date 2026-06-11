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
    from engine.audio.engine_rumble import update_positions
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
    import App
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


def _advance_weapons(ships, dt: float) -> None:
    """Per-frame charge / reload advancement for every weapon emitter.

    Walks all ships × all four weapon groups × all child emitters and
    calls UpdateCharge (energy) or UpdateReload (torpedo).  AI ships are
    included — their AI scripts call StartFiring expecting charged
    emitters.
    """
    from engine.appc.subsystems import TorpedoTube
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
    from engine.appc import projectiles, hit_vfx
    from engine.appc.combat import apply_hit, _resolve_hit_point

    ships_list = list(ships)

    hits = projectiles.update_all(
        dt, ships_list,
        host=host, ship_instances=ship_instances,
    )
    for torpedo, ship, hit_point, hit_normal in hits:
        apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship,
                  normal=hit_normal, host=host, ship_instances=ship_instances,
                  weapon_type="torpedo",
                  hardpoint_weapon=torpedo)

    hit_vfx.update_ages(dt)
    from engine.appc import subsystem_emitters
    subsystem_emitters.pump(ships_list, _camera_world_pos(host), dt)
    from engine.appc import camera_shake
    camera_shake.update(dt)

    # Continuous phaser damage tick.  Each ship's PhaserSystem has banks
    # set firing by StartFiring; advance them here: re-check arc (auto-
    # stop drifters), compute distance falloff, and route damage through
    # apply_hit (which routes shields → subsystem → hull, calls
    # hit_feedback.dispatch, and broadcasts WeaponHitEvent).
    from engine.appc.subsystems import _emitter_in_arc, _is_offline, _resolve_bank_aim_world
    from engine.appc.sensor_detection import can_detect
    from engine.appc.math import TGPoint3
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
                impact_point, impact_normal = _resolve_hit_point(
                    host=host, ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=(aim_unit if dist > 1e-6 else None),
                    max_dist=(dist * 1.5 if dist > 1e-6 else 0.0),
                    fallback_point=target_pos,
                )
                apply_hit(target, damage, impact_point,
                          source=ship,
                          normal=impact_normal,
                          host=host, ship_instances=ship_instances,
                          weapon_type="phaser",
                          hardpoint_weapon=bank)

    if host is not None and hasattr(host, "set_torpedoes"):
        host.set_torpedoes(_build_torpedo_render_data())
    if host is not None and hasattr(host, "set_hit_vfx"):
        host.set_hit_vfx(_build_hit_vfx_render_data())
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
    from engine.appc import projectiles
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
    from engine.appc import hit_vfx
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
    from engine.appc.combat import _resolve_hit_point
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
                from engine.appc.math import TGPoint3
                aim_unit = TGPoint3(dx / raw_length,
                                    dy / raw_length,
                                    dz / raw_length)
                clipped, _clipped_normal = _resolve_hit_point(
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
        from engine.appc.ship_iter import iter_ships
        return iter_ships()
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
    from engine.appc.ships import ShipClass
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

# Maps the BC LoadBridge.Load(name) argument to (nif_rel, tex_rel).
# Mirrors sdk/Build/scripts/Bridge/GalaxyBridge.py and SovereignBridge.py.
_BRIDGE_NIF_MAP: dict[str, tuple[str, str]] = {
    "GalaxyBridge":    (DBRIDGE_NIF_REL, DBRIDGE_TEX_REL),
    "SovereignBridge": (EBRIDGE_NIF_REL, EBRIDGE_TEX_REL),
}

# Captain's-chair camera position in bridge-local NIF space, per
# Bridge.<X>.GetBaseCameraPosition() in the SDK scripts. Mirrors
# sdk/Build/scripts/Bridge/GalaxyBridge.py:84 and SovereignBridge.py:80.
# Used by _BridgeCamera at compute time; resolved per frame against
# LoadBridge.LAST_REQUESTED so a bridge swap is picked up without
# rebuilding the camera.
_BRIDGE_CAMERA_OFFSETS: dict[str, tuple[float, float, float]] = {
    "GalaxyBridge":    (0.683736, 86.978439, 50.0),
    "SovereignBridge": (0.683736, 129.585,   70.678),
}

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
        are zero."""
        if not (pitch_rate or yaw_rate or roll_rate):
            return
        from engine.appc.math import TGMatrix3, TGPoint3
        R = player.GetWorldRotation()
        R_pitch = TGMatrix3(); R_pitch.MakeRotation(pitch_rate * dt, TGPoint3(1.0, 0.0, 0.0))
        R_yaw   = TGMatrix3(); R_yaw.MakeRotation(yaw_rate   * dt, TGPoint3(0.0, 0.0, 1.0))
        R_roll  = TGMatrix3(); R_roll.MakeRotation(roll_rate  * dt, TGPoint3(0.0, 1.0, 0.0))
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
        from engine.appc.subsystems import impulse_online_fraction
        from engine.appc.ship_motion import (
            _effective_motion, _cap_keep, _asymptote_step,
        )
        from engine.appc.math import TGPoint3

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
    from engine.audio.engine_rumble import set_muted as _rumble_set_muted
    _rumble_set_muted(target)
    # Bridge ambient hum (AmbBridge): start when entering, stop when
    # leaving. Mirrors LoadBridge.py:213-217's play-at-load behaviour
    # but gated on view mode so it only sounds when the player is
    # actually on the bridge.
    from engine.audio.bridge_ambient import set_active as _bridge_ambient_set
    _bridge_ambient_set(target)
    # View-mode change — drop any leftover camera-shake energy so
    # the new view doesn't inherit a rumble from the old one.
    from engine.appc import camera_shake
    camera_shake.reset()
    from engine.appc import hit_feedback
    hit_feedback.reset_audio_throttle()
    view_mode._last_synced_is_bridge = target


class _NullPicker:
    """Stand-in used when dev_mode is disabled (no MissionPicker
    constructed). Always reports closed so the pause-menu side-effects
    predicate degrades to its original behaviour."""
    def is_open(self) -> bool:
        return False


_NULL_PICKER = _NullPicker()


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

    # Captain's-chair offset used when LoadBridge.LAST_REQUESTED isn't in
    # the per-bridge table. Mirrors GalaxyBridge.GetBaseCameraPosition()
    # — sdk/Build/scripts/Bridge/GalaxyBridge.py:84.
    DEFAULT_BRIDGE_OFFSET = (0.683736, 86.978439, 50.0)

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

    def _eye_offset(self) -> tuple:
        """Resolve the per-bridge captain's-chair offset from
        LoadBridge.LAST_REQUESTED. Called every frame so a mid-session
        bridge swap is picked up without re-constructing the camera."""
        try:
            import LoadBridge as _LB
            name = getattr(_LB, "LAST_REQUESTED", "")
        except Exception:
            name = ""
        return _BRIDGE_CAMERA_OFFSETS.get(name, self.DEFAULT_BRIDGE_OFFSET)

    def apply(self, mouse_dx: float, mouse_dy: float) -> None:
        """Accumulate mouse delta into yaw/pitch with sign conventions:
        right-mouse (+dx) → look-right (-yaw); up-mouse (-dy in screen
        coords) → look-up (+pitch). Pitch clamps; yaw wraps freely."""
        self.yaw_rad   -= mouse_dx * self.MOUSE_SENSITIVITY
        self.pitch_rad -= mouse_dy * self.MOUSE_SENSITIVITY
        if self.pitch_rad >  self.PITCH_LIMIT_RAD: self.pitch_rad =  self.PITCH_LIMIT_RAD
        if self.pitch_rad < -self.PITCH_LIMIT_RAD: self.pitch_rad = -self.PITCH_LIMIT_RAD

    def compute_camera(self) -> tuple:
        """Return (eye, target, up) as 3-tuples in bridge-local space.

        Bridge geometry is at world identity; the camera is too. No
        ship_loc / ship_rot coupling — see class docstring.
        """
        local_fwd = (0.0, 1.0, 0.0)   # bridge-local +Y
        local_up  = (0.0, 0.0, 1.0)   # bridge-local +Z

        # Yaw around the world-up axis (Z).
        local_fwd = _rot_around(local_fwd, (0.0, 0.0, 1.0), self.yaw_rad)

        # Pitch around the local right axis (forward × up).
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
        target = (
            eye[0] + local_fwd[0],
            eye[1] + local_fwd[1],
            eye[2] + local_fwd[2],
        )
        return eye, target, local_up


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
    interpolation path. Applies the determinant-normalization X-flip
    (see _ship_world_matrix docstring) so every rendered instance reaches
    the GPU with det < 0 under glFrontFace(GL_CW).
    """
    flip = -1.0 if _rot_determinant(rot) > 0.0 else 1.0
    sx = s * flip
    return [
        rot._m[0][0]*sx, rot._m[0][1]*s, rot._m[0][2]*s, loc.x,
        rot._m[1][0]*sx, rot._m[1][1]*s, rot._m[1][2]*s, loc.y,
        rot._m[2][0]*sx, rot._m[2][1]*s, rot._m[2][2]*s, loc.z,
        0.0,             0.0,            0.0,            1.0,
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

    Determinant normalization (workaround): the renderer is configured
    with glFrontFace(GL_CW) and assumes the world matrix has det < 0 —
    which holds for ships whose rotation came from AlignToVectors (it
    builds right = up × forward, giving det = -1). Ships placed by
    other paths (e.g. Akira at the "Docking Exit" hardpoint, or any
    ship with identity rotation) arrive with a proper rotation
    (det = +1), and render inside-out because their world matrix flips
    screen-space winding the wrong way under GL_CW. Until the coupled
    fix lands (AlignToVectors → proper rotation, pipeline.cc →
    glFrontFace(GL_CCW), backdrop/sun cull state → GL_BACK), we negate
    the X body axis here when det > 0 so every rendered ship reaches
    the GPU with det < 0. ship.GetWorldRotation() is left untouched —
    camera-follow, physics, and AI continue to see the original
    rotation.
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
        self.bridge_instance: Optional[Any] = None  # InstanceId from create_bridge_instance
        # NIF path currently bound to bridge_instance. _ensure_bridge_for_session
        # compares against the BC bridge_name → NIF map to decide whether to swap.
        self.current_bridge_nif_abs: Optional[str] = None
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
        from engine.appc import subsystem_emitters
        subsystem_emitters.reset_manager()
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
                except Exception:
                    pass
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
            except Exception:
                pass  # glow dimming is best-effort VFX; never block spawn

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
                except Exception:
                    pass
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


_BRIDGE_IDENTITY_MAT4 = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]


def _ensure_bridge_for_session(controller) -> None:
    """Swap the renderer's bridge model to whatever the last mission
    requested via LoadBridge.Load(name).

    Mission scripts call LoadBridge.Load("SovereignBridge" |
    "GalaxyBridge") during StartMission; the shim records the value as
    LoadBridge.LAST_REQUESTED. This helper reads it back, maps it to a
    NIF path via _BRIDGE_NIF_MAP, and replaces controller.bridge_instance
    if the path differs from what's currently loaded. Model handles are
    cached in controller.nif_to_handle so repeated swaps don't re-upload.
    """
    import LoadBridge as _LoadBridge
    bridge_name = getattr(_LoadBridge, "LAST_REQUESTED", "GalaxyBridge")
    mapping = _BRIDGE_NIF_MAP.get(bridge_name)
    if mapping is None:
        return
    nif_rel, tex_rel = mapping
    nif_abs = str(PROJECT_ROOT / "game" / nif_rel)
    if nif_abs == controller.current_bridge_nif_abs:
        return
    r_ = controller.renderer
    tex_abs = str(PROJECT_ROOT / "game" / tex_rel)
    handle = controller.nif_to_handle.get(nif_abs)
    if handle is None:
        handle = r_.load_model(nif_abs, tex_abs)
        controller.nif_to_handle[nif_abs] = handle
    if controller.bridge_instance is not None:
        r_.destroy_instance(controller.bridge_instance)
    controller.bridge_instance = r_.create_bridge_instance(handle)
    r_.set_world_transform(controller.bridge_instance, _BRIDGE_IDENTITY_MAT4)
    controller.current_bridge_nif_abs = nif_abs


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
    except Exception:
        pass
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

        # Bridge interior — eagerly loaded once and reused across mission
        # swaps. Instance lives on the controller, not the per-mission
        # session, so MissionSession.teardown doesn't destroy it.
        bridge_nif_abs = str(PROJECT_ROOT / "game" / DBRIDGE_NIF_REL)
        bridge_tex_abs = str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL)
        bridge_handle  = r.load_model(bridge_nif_abs, bridge_tex_abs)
        controller.nif_to_handle[bridge_nif_abs] = bridge_handle
        controller.bridge_instance = r.create_bridge_instance(bridge_handle)
        controller.current_bridge_nif_abs = bridge_nif_abs
        # Eagerly register the "bridge" SetClass so its CreateAmbientLight
        # value reaches the renderer via aggregate_bridge_for_renderer.
        # Stock missions only call LoadBridge.Load() when they need it,
        # but our bridge mesh is always loaded — the lighting needs to
        # match.
        import LoadBridge as _LoadBridge
        _LoadBridge.Load()
        # Identity transform — the bridge pass camera works in
        # bridge-local frame, so the bridge's world position is irrelevant.
        IDENTITY_MAT4 = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        r.set_world_transform(controller.bridge_instance, IDENTITY_MAT4)

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
            _ensure_bridge_for_session(controller)
            _wire_target_menu_to_player_set(controller)
        controller.post_load_hook = _after_mission_loaded
        _after_mission_loaded()

        bridge_camera  = _BridgeCamera()
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
        configuration_panel = ConfigurationPanel(
            tabs=[("graphics", "Graphics")],
            initial_settings=SettingsSnapshot(
                dust_on=True,
                specular_on=True,
                hdr_on=True,
                rim_on=True,
                decals_on=True,
                fxaa_on=True,
                fov_deg=int(round(_math.degrees(
                    director.fov_y_rad
                ))),
            ),
            set_dust=r.set_dust_enabled,
            set_specular=r.set_specular_enabled,
            set_hdr=r.set_hdr_enabled,
            set_rim=r.set_rim_enabled,
            set_decals=r.set_decals_enabled,
            set_fxaa=r.set_fxaa_enabled,
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

        while not r.should_close():
            # --- Input dispatch + modality (ESC always live; SPACE only when unpaused) ---
            # _apply_view_mode_side_effects mirrors the SPACE flag into
            # renderer state (bridge pass enable + cursor lock) and is
            # idempotent — only fires when the mode changed.
            if _h is not None:
                # ESC priority: mission picker first (dev only), then the
                # developer options panel (dev only), then the ship property
                # viewer (dev only), then the configuration panel, otherwise
                # the pause menu toggle. All four modal blockers close on ESC
                # and return the user to the pause menu.
                if mission_picker.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        mission_picker.handle_key_esc()
                elif developer_options_panel.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        developer_options_panel.handle_key_esc()
                elif ship_property_viewer.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        ship_property_viewer.handle_key_esc()
                elif configuration_panel.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        configuration_panel.handle_key_esc()
                else:
                    pause.apply(_h)
                _apply_pause_menu_side_effects(
                    pause, view_mode, _h,
                    [mission_picker, developer_options_panel,
                     ship_property_viewer, configuration_panel],
                )
                if pause.is_open:
                    # When a settings modal is open it consumes keyboard
                    # input — pause-menu navigation would otherwise activate
                    # rows hidden behind the modal.
                    if configuration_panel.is_open():
                        configuration_panel.handle_input(_h)
                    elif developer_options_panel.is_open():
                        developer_options_panel.handle_input(_h)
                    elif ship_property_viewer.is_open():
                        ship_property_viewer.handle_input(_h)
                    elif not mission_picker.is_open():
                        pause_menu.handle_input(_h)
                        _script = pause_menu.render_payload()
                        if _script is not None:
                            _h.cef_execute_javascript(_script)
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
                        _mx_fb, _my_fb = _h.cursor_pos()
                        _fb_w, _fb_h = _h.framebuffer_size()
                        _sx = (_CEF_VIEW_W / _fb_w) if _fb_w > 0 else 1.0
                        _sy = (_CEF_VIEW_H / _fb_h) if _fb_h > 0 else 1.0
                        _mx = int(_mx_fb * _sx)
                        _my = int(_my_fb * _sy)
                        _cef_send_mouse_move(_mx, _my)
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
                import App as _App_sv
                _menu = _App_sv.STTargetMenu_GetTargetMenu()
                from engine.core.game import Game_GetCurrentGame
                _game = Game_GetCurrentGame()
                _player = _game.GetPlayer() if _game is not None else None
                _player_set = getattr(_player, "_containing_set", None) if _player is not None else None
                if _menu is not None and _player is not None and _player_set is not None:
                    from engine.appc.subsystems import update_target_list_visibility
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
                    _mx_fb, _my_fb = _h.cursor_pos()
                    _fb_w, _fb_h = _h.framebuffer_size()
                    _sx = (_CEF_VIEW_W / _fb_w) if _fb_w > 0 else 1.0
                    _sy = (_CEF_VIEW_H / _fb_h) if _fb_h > 0 else 1.0
                    _mx = int(_mx_fb * _sx)
                    _my = int(_my_fb * _sy)
                    _cef_send_mouse_move(_mx, _my)
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

                # Advance weapon charge / reload for every ship in every
                # active set.  Runs after AI/physics (approximate — the host
                # loop is single-threaded and Python AI runs in the gameloop
                # tick above) so emitters are ready when AI fire calls land.
                _advance_weapons(_all_ships_for_tick(), TICK_DT)
                _advance_combat(
                    _all_ships_for_tick(), TICK_DT, host=_h,
                    ship_instances=(session.ship_instances if session is not None else None),
                )

                # Collision detection + response (ships/asteroids/moons/
                # planets). Runs once per render frame after motion + player
                # input, so every body's post-thrust position is current.
                # Reuses combat.apply_hit for impact damage; injects a
                # mass-weighted impulse into each body's decaying
                # _collision_velocity overlay. Spec
                # docs/superpowers/specs/2026-06-11-collision-response-design.md.
                from engine.appc import collisions
                collisions.tick_collisions(
                    TICK_DT, host=_h,
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
                    # player is always set when a session exists, so
                    # _player_iid is a real iid (never None) at runtime.
                    _player_iid = session.ship_instances.get(player)
                    _live_ship_iids = []
                    # Same game clock the decal system ages on
                    # (engine.appc.damage_decals). Read once per frame.
                    import App as _App_wg
                    _wg_now = _App_wg.g_kUtopiaModule.GetGameTime()
                    for ship, iid in session.ship_instances.items():
                        _wg = session.ship_glow_controllers.get(iid)
                        if _wg is not None:
                            _wg.update(_wg_now)
                        if iid == _player_iid:
                            r.set_world_transform(
                                iid, _ship_world_matrix(ship, BC_MODEL_SCALE))
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
                        _xform_buf.set_current(
                            iid, ship.GetWorldLocation(), ship.GetWorldRotation())
                        _sampled = _xform_buf.sample(iid, _interp_alpha)
                        _iloc, _irot = _sampled
                        r.set_world_transform(
                            iid, _world_matrix_from(_iloc, _irot, BC_MODEL_SCALE * _ps))
                    _xform_buf.prune(_live_ship_iids)
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
                from engine.appc import camera_shake
                eye, target, up_vec = camera_shake.perturb(eye, target, up_vec)
                if view_mode.is_bridge:
                    mouse_dx, mouse_dy = _h.consume_mouse_delta() if _h else (0.0, 0.0)
                    # While paused we still drain the accumulated mouse
                    # delta (so it doesn't snap the look on resume) but
                    # skip the yaw/pitch advance so the bridge camera
                    # stays frozen alongside the rest of the world.
                    if not pause.is_open:
                        bridge_camera.apply(mouse_dx, mouse_dy)
                    b_eye, b_target, b_up = bridge_camera.compute_camera()
                    # Bridge first-person camera uses separate (eye, target,
                    # up) vectors from the exterior view, so it needs its own
                    # perturb call. The camera_shake module is global state,
                    # so the shake energy / phase is shared with the
                    # exterior perturb above.
                    b_eye, b_target, b_up = camera_shake.perturb(b_eye, b_target, b_up)
                    r.set_bridge_camera(
                        eye=b_eye, target=b_target, up=b_up,
                        fov_y_rad=_BridgeCamera.FOV_Y_RAD,
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
                except Exception:
                    pass
            r.set_bridge_lighting(bridge_ambient, bridge_directionals)
            # BC's NiFlipController observes *game time*, not wall time
            # — controllers advance with g_kTimerManager (which the
            # original engine scaled, instrumentation Q3). Feeding wall
            # time made the LCARS animation play noticeably faster than
            # in stock BC; game time matches the original cadence.
            import App as _App
            r.set_bridge_wall_time(_App.g_kUtopiaModule.GetGameTime())

            # Age every ship's persistent damage-decal ring on the same game
            # clock used for decal birth_time (engine.appc.damage_decals).
            # hasattr-guarded so an older _dauntless_host.so still runs.
            if hasattr(r, "damage_decals_tick"):
                r.damage_decals_tick(_App.g_kUtopiaModule.GetGameTime())

            backdrops = _aggregate_backdrops(active_set)
            r.set_backdrops(backdrops)

            suns = _aggregate_suns()
            r.set_suns(suns)

            planets = _aggregate_planets(
                list(_App.g_kSetManager._sets.values()))
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
