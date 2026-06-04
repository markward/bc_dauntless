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
    """Phaser damage falloff: linear from MaxDamage at dist=0 to 0 at
    dist=MaxDamageDistance.  Returns 0 if MaxDamageDistance is 0 or
    dist >= MaxDamageDistance."""
    if max_damage_distance <= 0.0 or dist >= max_damage_distance:
        return 0.0
    return max_damage * (1.0 - dist / max_damage_distance) * dt


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
    for torpedo, ship, subsystem, hit_point in hits:
        apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship, subsystem=subsystem,
                  normal=None, host=host, ship_instances=ship_instances,
                  weapon_type="torpedo")

    hit_vfx.update_ages(dt)
    from engine.appc import camera_shake
    camera_shake.update(dt)

    # Continuous phaser damage tick.  Each ship's PhaserSystem has banks
    # set firing by StartFiring; advance them here: re-check arc (auto-
    # stop drifters), compute distance falloff, and route damage through
    # apply_hit (which routes shields → subsystem → hull, calls
    # hit_feedback.dispatch, and broadcasts WeaponHitEvent).
    from engine.appc.subsystems import _emitter_in_arc, _is_offline
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
            target_sub = (ship.GetTargetSubsystem()
                          if hasattr(ship, "GetTargetSubsystem") else None)
            if target_sub is not None and hasattr(target_sub, "GetWorldLocation"):
                target_pos = target_sub.GetWorldLocation()
            else:
                target_pos = target.GetWorldLocation()
                target_sub = None
            emitter_pos = bank._strip_emit_position(target_pos)
            dx = target_pos.x - emitter_pos.x
            dy = target_pos.y - emitter_pos.y
            dz = target_pos.z - emitter_pos.z
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            if dist > 1e-6:
                aim_unit = TGPoint3(dx / dist, dy / dist, dz / dist)
                if not _emitter_in_arc(bank, ship, aim_unit):
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
                          source=ship, subsystem=target_sub,
                          normal=impact_normal,
                          host=host, ship_instances=ship_instances,
                          weapon_type="phaser")

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
            "position": (pos.x, pos.y, pos.z),
            "normal":   (n.x, n.y, n.z) if n is not None else (0.0, 0.0, 0.0),
            "severity": entry["severity"],
            "age":      entry["age"],
        })
    return out


# Tunable scale applied to SDK-declared beam radii (PhaserWidth /
# MainRadius / TaperRadius).  The instrumentation pass confirmed
# SetPosition is in world units, but the beam-radius family was never
# directly verified — the SDK's 0.30 / 0.15 read as much smaller than
# BC's visible beam at typical Galaxy framing.  4× is a feel-tuned
# nominal; the right long-term fix is a focused instrumentation pass
# that reads back beam render geometry from the live engine.
PHASER_BEAM_WIDTH_MUTATOR = 4.0


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
            # Clip the *rendered* beam to MaxDamageDistance so very
            # distant targets still produce a sensibly proportioned
            # beam (not a sub-pixel hairline 400 wu long).  Damage
            # falloff already drops to zero past this distance.
            # DEFERRED: phasers shouldn't *fire* at out-of-range
            # targets at all — see
            # docs/superpowers/deferred/2026-05-18-phaser-fire-range-gate.md.
            dx = target_pos.x - emitter_pos.x
            dy = target_pos.y - emitter_pos.y
            dz = target_pos.z - emitter_pos.z
            raw_length = (dx * dx + dy * dy + dz * dz) ** 0.5
            max_range = bank.GetMaxDamageDistance() or 0.0
            beam_length = raw_length
            beam_end = target_pos
            if max_range > 0.0 and raw_length > max_range:
                from engine.appc.math import TGPoint3
                scale = max_range / raw_length
                beam_end = TGPoint3(emitter_pos.x + dx * scale,
                                    emitter_pos.y + dy * scale,
                                    emitter_pos.z + dz * scale)
                beam_length = max_range
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

    # ── Hardpoint accessors ──────────────────────────────────────────────────

    @staticmethod
    def _get_ies(player):
        getter = getattr(player, "GetImpulseEngineSubsystem", None)
        return getter() if getter else None

    def GetTargetSpeed(self, player) -> float:
        """Convert impulse_level into a target speed using the ship's
        ImpulseEngineProperty.MaxSpeed when present, or the legacy
        per-level placeholder otherwise.

        Forward speed is multiplied by WARP_BOOST_FACTOR when the
        in-system warp toggle is on (Ctrl+I); reverse is unaffected.

        Disabled-engines gate (Project 5 §4.1): when the IES reports
        IsDisabled or IsDestroyed, target is unconditionally 0 — the
        ship coasts under the ship_motion drag fraction.
        """
        from engine.appc.subsystems import _is_offline
        ies = self._get_ies(player)
        if _is_offline(ies):
            return 0.0
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

    def _max_accel(self, player) -> float:
        ies = self._get_ies(player)
        if ies is not None and ies.GetMaxSpeed() > 0.0:
            a = ies.GetMaxAccel()
            return a if a > 0.0 else self.FALLBACK_MAX_ACCEL
        return self.FALLBACK_MAX_ACCEL

    def _angular_rate(self, player) -> float:
        ies = self._get_ies(player)
        if ies is not None and ies.GetMaxAngularVelocity() > 0.0:
            return ies.GetMaxAngularVelocity()
        return self.TURN_RATE_RAD_PER_S

    def _angular_accel(self, player) -> float:
        """Per-axis angular acceleration (rad/s²).  When the IES has no
        MaxAngularAccel value, falls back to a very large rate so the legacy
        snap-to-rate semantics are preserved (tests using fake ships keep
        seeing instant rotation onset)."""
        ies = self._get_ies(player)
        if ies is not None and ies.GetMaxAngularVelocity() > 0.0:
            a = ies.GetMaxAngularAccel()
            return a if a > 0.0 else self.FALLBACK_MAX_ACCEL
        return self.FALLBACK_MAX_ACCEL

    def GetCurrentPitchRate(self) -> float: return self._current_pitch_rate
    def GetCurrentYawRate(self)   -> float: return self._current_yaw_rate
    def GetCurrentRollRate(self)  -> float: return self._current_roll_rate

    @staticmethod
    def _ramp_toward(current: float, target: float, step: float) -> float:
        delta = target - current
        if abs(delta) <= step:
            return target
        return current + (step if delta > 0 else -step)

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

        # Disabled-engines gate: read once, applied to both linear and
        # angular ramps. Spec §4.1.
        from engine.appc.subsystems import _is_offline
        from engine.appc.ship_motion import (
            DISABLED_ENGINE_DRAG_FRACTION,
            _linear_step_magnitude,
        )
        engines_offline = _is_offline(self._get_ies(player))

        # 2. Linear speed ramp toward target — BC's rate-limited asymptote
        #    (linear at MaxAccel until the gap drops below MaxAccel·τ,
        #    then exponential closure with τ=1 s). Disabled engines: scale
        #    ramp by drag fraction so velocity decays gradually rather
        #    than at full MaxAccel. Spec §4.1.
        target_speed = self.GetTargetSpeed(player)
        linear_step = _linear_step_magnitude(
            player, target_speed - self._current_speed, dt,
        )
        if engines_offline:
            linear_step *= DISABLED_ENGINE_DRAG_FRACTION
        self._current_speed = self._ramp_toward(
            self._current_speed,
            target_speed,
            linear_step,
        )

        # 3. Angular rates: held keys set a per-axis target rate; current rate
        #    ramps toward target at MaxAngularAccel.
        # Key → on-screen effect:
        #   W = nose DOWN,  S = nose UP
        #   A = yaw LEFT,   D = yaw RIGHT
        #   Q = roll LEFT,  E = roll RIGHT
        # Sign convention: under right-hand rule with col-vector matrices
        # (see CLAUDE.md), +ω_x = nose UP, +ω_z = yaw LEFT, +ω_y = roll LEFT.
        # The key→sign mapping below produces the documented visual effect.
        ang_rate    = self._angular_rate(player)
        ang_step    = self._angular_accel(player) * dt
        if engines_offline:
            ang_step *= DISABLED_ENGINE_DRAG_FRACTION
        pitch_target = 0.0
        yaw_target   = 0.0
        roll_target  = 0.0
        if h.key_state(h.keys.KEY_W): pitch_target -= ang_rate
        if h.key_state(h.keys.KEY_S): pitch_target += ang_rate
        if h.key_state(h.keys.KEY_A): yaw_target   -= ang_rate
        if h.key_state(h.keys.KEY_D): yaw_target   += ang_rate
        if h.key_state(h.keys.KEY_Q): roll_target  += ang_rate
        if h.key_state(h.keys.KEY_E): roll_target  -= ang_rate
        if engines_offline:
            pitch_target = 0.0
            yaw_target = 0.0
            roll_target = 0.0
        self._current_pitch_rate = self._ramp_toward(self._current_pitch_rate, pitch_target, ang_step)
        self._current_yaw_rate   = self._ramp_toward(self._current_yaw_rate,   yaw_target,   ang_step)
        self._current_roll_rate  = self._ramp_toward(self._current_roll_rate,  roll_target,  ang_step)
        pitch_rate = self._current_pitch_rate
        yaw_rate   = self._current_yaw_rate
        roll_rate  = self._current_roll_rate

        # 4. Rotation integration.  BC uses column-vector matrices where
        #    v_world = R · v_body (see CLAUDE.md ↦ "Rotation matrix
        #    convention").  A body-frame delta D acts on v_body first:
        #    v_world = R · (D · v_body) = (R · D) · v_body.  So body-frame
        #    rotation is POST-multiply (R · D).  Pitch → yaw → roll Euler
        #    order.
        from engine.appc.math import TGMatrix3, TGPoint3
        X_AXIS = TGPoint3(1.0, 0.0, 0.0)
        Y_AXIS = TGPoint3(0.0, 1.0, 0.0)
        Z_AXIS = TGPoint3(0.0, 0.0, 1.0)

        R = player.GetWorldRotation()
        if pitch_rate or yaw_rate or roll_rate:
            R_pitch = TGMatrix3(); R_pitch.MakeRotation(pitch_rate * dt, X_AXIS)
            R_yaw   = TGMatrix3(); R_yaw.MakeRotation(yaw_rate   * dt, Z_AXIS)
            R_roll  = TGMatrix3(); R_roll.MakeRotation(roll_rate  * dt, Y_AXIS)
            delta = R_pitch.MultMatrix(R_yaw).MultMatrix(R_roll)
            R = R.MultMatrix(delta)
            player.SetMatrixRotation(R)

        # 5. Position integration (forward = ship-local Y axis in world).
        if self._current_speed != 0.0:
            forward = R.GetCol(1)
            p = player.GetTranslate()
            player.SetTranslateXYZ(
                p.x + forward.x * self._current_speed * dt,
                p.y + forward.y * self._current_speed * dt,
                p.z + forward.z * self._current_speed * dt,
            )


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


def _apply_pause_menu_side_effects(pause: "_PauseMenuController",
                                   view_mode: "_ViewModeController",
                                   h,
                                   picker) -> None:
    """Mirror the pause flag into renderer state: show/hide the CEF
    pause-menu div and unlock the cursor while paused so the player can
    interact with the overlay. Idempotent — only fires when the
    effective visibility has changed since the last call. `h` is the
    bindings module (or fake) exposing cef_execute_javascript and
    set_cursor_locked. `picker` is the MissionPicker (or any object
    with an is_open() method); when the picker is open the pause-menu
    must hide regardless of pause.is_open so the picker isn't
    occluded.

    On close, the view-mode sync latch is invalidated so the next
    _apply_view_mode_side_effects call re-applies cursor lock + bridge
    pass state from whatever view mode is current.
    """
    target = pause.is_open and not picker.is_open()
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

    # MissionLib.py:1475-1483 — DBridge captain's-chair offset.
    BRIDGE_LOCAL_OFFSET   = (0.0, 50.0, 47.0)

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

        eye = self.BRIDGE_LOCAL_OFFSET
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


# Universal NIF→world conversion. Calibrated from BC's Galaxy reading
# (GetRadius=4.3665, model_aabb outer extent=403.258). Used to derive a
# meaningful GetRadius() for Phase-1 shim ships that don't have one set,
# so downstream code (camera-follow, shield bubble) reads sensible numbers.
NIF_TO_WORLD = 4.3665 / 403.258  # ≈ 0.01083


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
    flip = -1.0 if _rot_determinant(rot) > 0.0 else 1.0
    sx = s * flip
    return [
        rot._m[0][0]*sx, rot._m[0][1]*s, rot._m[0][2]*s, loc.x,
        rot._m[1][0]*sx, rot._m[1][1]*s, rot._m[1][2]*s, loc.y,
        rot._m[2][0]*sx, rot._m[2][1]*s, rot._m[2][2]*s, loc.z,
        0.0,             0.0,            0.0,            1.0,
    ]


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
    flip = -1.0 if _rot_determinant(rot) > 0.0 else 1.0
    sx = s * flip
    return [
        rot._m[0][0]*sx, rot._m[0][1]*s, rot._m[0][2]*s, loc.x,
        rot._m[1][0]*sx, rot._m[1][1]*s, rot._m[1][2]*s, loc.y,
        rot._m[2][0]*sx, rot._m[2][1]*s, rot._m[2][2]*s, loc.z,
        0.0,             0.0,            0.0,            1.0,
    ]


@dataclass
class MissionSession:
    """Per-mission scene state owned by HostController.

    Tracks the renderer instances created for the current mission so a
    swap can destroy them without re-deriving them from the SDK's set
    manager (which is itself about to be cleared).
    """
    mission_name: str
    ship_instances:   dict[Any, int] = field(default_factory=dict)
    planet_instances: dict[Any, int] = field(default_factory=dict)
    # Per-object natural_scale = GetRadius() / NIF_extent, cached at load.
    # Read by _ship_world_matrix / _astro_world_matrix; multiplied by
    # GetScale() at draw time.
    ship_natural_scale:   dict[Any, float] = field(default_factory=dict)
    planet_natural_scale: dict[Any, float] = field(default_factory=dict)
    player: Optional[Any] = None

    def teardown(self, renderer) -> None:
        for iid in list(self.ship_instances.values()):
            renderer.destroy_instance(iid)
        for iid in list(self.planet_instances.values()):
            renderer.destroy_instance(iid)
        self.ship_instances.clear()
        self.planet_instances.clear()
        self.ship_natural_scale.clear()
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
            # BC's compiled engine populates GetRadius() from the loaded NIF.
            # Phase-1's shim skips that, so derive it here when missing.
            if ship.GetRadius() <= 0.0:
                try:
                    ship.SetRadius(extent * NIF_TO_WORLD)
                except Exception:
                    pass
            natural_scale = (ship.GetRadius() / extent) if extent > 0.0 else 1.0
            iid = r_.create_instance(handle)
            r_.set_world_transform(iid, _ship_world_matrix(ship, natural_scale))
            sess.ship_instances[ship] = iid
            sess.ship_natural_scale[ship] = natural_scale

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
                    planet.SetRadius(extent * NIF_TO_WORLD)
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
    # Initialise the CEF UI overlay. Resolves hello.html relative to the
    # project root (two parents up from this file). _CEF_VIEW_W/H are
    # reused by the pause-menu mouse-forwarding path to scale
    # framebuffer-pixel cursor coords back into the OSR view's logical
    # pixel space on Retina.
    _CEF_VIEW_W, _CEF_VIEW_H = 1280, 720
    _cef_html = _project_root_for_cef() / "native" / "assets" / "ui-cef" / "hello.html"
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
        controller.post_load_hook = lambda: _wire_target_menu_to_player_set(controller)
        _wire_target_menu_to_player_set(controller)

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

        from engine.ui.pause_menu import default_pause_menu
        from engine.ui.panel_registry import PanelRegistry
        pause_menu = default_pause_menu(
            on_exit=pause.request_quit,
            on_cancel=pause.close,
        )
        registry = PanelRegistry(legacy_handler=pause_menu.dispatch_event)
        controller.panel_registry = registry  # expose to _drain_pending_swap
        registry.register(target_list_view)
        registry.register(sensors_panel)
        from engine.appc.sdk_mirror_panel import SDKMirrorPanel
        sdk_mirror = SDKMirrorPanel()
        registry.register(sdk_mirror)
        if dev_mode.is_enabled():
            registry.register(mission_picker)

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

        # Speed readout (bottom-row, left of the player ship-display).
        # Read-only — reads current_speed + warp_boost off the local
        # _PlayerControl instance via dependency injection.
        from engine.ui.speed_display import SpeedDisplay
        speed_display = SpeedDisplay(player_control=player_control)
        registry.register(speed_display)

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

        while not r.should_close():
            # --- Input dispatch + modality (ESC always live; SPACE only when unpaused) ---
            # _apply_view_mode_side_effects mirrors the SPACE flag into
            # renderer state (bridge pass enable + cursor lock) and is
            # idempotent — only fires when the mode changed.
            if _h is not None:
                # ESC priority: when the mission picker is open it
                # consumes ESC (closes the picker, returns to the
                # pause menu). Otherwise ESC toggles the pause menu
                # as before.
                if mission_picker.is_open():
                    if _h.key_pressed(_h.keys.KEY_ESCAPE):
                        mission_picker.handle_key_esc()
                else:
                    pause.apply(_h)
                _apply_pause_menu_side_effects(pause, view_mode, _h, mission_picker)
                if pause.is_open:
                    # Suppress pause-menu keyboard input when the
                    # mission picker is open — pause menu is hidden
                    # behind the picker, so navigation/Enter on it
                    # would activate invisible rows.
                    if not mission_picker.is_open():
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
                target_list_view.visible    = view_mode.is_exterior
                sensors_panel.visible       = view_mode.is_exterior
                ship_display_player.visible = view_mode.is_exterior
                ship_display_target.visible = view_mode.is_exterior
                speed_display.visible       = view_mode.is_exterior

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
                    # hello.css; new panels need a bbox here or their
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
                        (ship_display_player.visible or speed_display.visible)
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
            for _ in range(_sim_ticks_this_frame):
                loop.tick()

            # Only snap the camera when a sim tick actually fired —
            # no tick means no state change to follow.
            if _sim_ticks_this_frame > 0:
                had_pending_swap = controller.pending_swap is not None
                controller._drain_pending_swap()
                if had_pending_swap:
                    director.snap()
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
                    # key-down event (not while held).
                    if _h.key_pressed(_h.keys.KEY_C):
                        director.toggle_mode(player=player)
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

                # Sync transforms for known instances.
                if session is not None:
                    for ship, iid in session.ship_instances.items():
                        ns = session.ship_natural_scale.get(ship, 1.0)
                        r.set_world_transform(iid, _ship_world_matrix(ship, ns))
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
                    player=player, dt=TICK_DT)
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
            r.set_camera(eye=eye, target=target, up=up_vec,
                         fov_y_rad=1.0472, near=1.0, far=5000.0)

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

            backdrops = _aggregate_backdrops(active_set)
            r.set_backdrops(backdrops)

            suns = _aggregate_suns()
            r.set_suns(suns)

            lens_flares = _aggregate_lens_flares()
            r.set_lens_flares(lens_flares)

            if verbose and ticks == 0:
                print(f"[host_loop] tick 0 camera eye={eye} target={target}", flush=True)
                print(f"[host_loop] tick 0 lighting ambient={ambient} "
                      f"directionals={directionals}", flush=True)
                print(f"[host_loop] tick 0 backdrops: "
                      f"{len(backdrops)} layer(s)", flush=True)
                print(f"[host_loop] tick 0 suns: {len(suns)} sun(s)", flush=True)
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
