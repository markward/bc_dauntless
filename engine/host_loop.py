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

import math as _math

# ── Audio integration ────────────────────────────────────────────────────────
try:
    import _open_stbc_host as _host_mod
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

    `host` is the _open_stbc_host module (the binding from host_bindings.cc).
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
    through combat.apply_hit (which broadcasts WeaponHitEvent), spawns
    hit VFX, ages out expired VFX, and pushes current torpedo + hit-VFX
    lists to the renderer.

    `host` is the _open_stbc_host module (the binding from
    host_bindings.cc).  When None (headless tests), the renderer pushes
    are skipped — combat logic still runs.

    `ship_instances` maps ship → renderer instance id; when provided we
    also fire host.shield_hit on the target's bubble so the shield-impact
    pass can splash at the strike point.
    """
    from engine.appc import projectiles, hit_vfx
    from engine.appc.combat import apply_hit

    ships_list = list(ships)
    hits = projectiles.update_all(dt, ships_list)
    for torpedo, ship, subsystem in hits:
        apply_hit(ship, torpedo._damage, torpedo._position,
                  source=torpedo._source_ship, subsystem=subsystem)
        hit_vfx.spawn(torpedo._position)
        if (host is not None
                and ship_instances is not None
                and hasattr(host, "shield_hit")):
            iid = ship_instances.get(ship)
            if iid is not None:
                # Use the torpedo's collision point directly — it lies on
                # or just inside the bubble shell, where the shield-pass
                # splash falloff produces a visible splash.
                host.shield_hit(
                    instance_id=iid,
                    point=(torpedo._position.x, torpedo._position.y, torpedo._position.z),
                    rgba=(0.0, 0.0, 0.0, 0.0),
                    intensity=1.0,
                )

    hit_vfx.update_ages(dt)

    # Continuous phaser damage tick.  Each ship's PhaserSystem has banks
    # set firing by StartFiring; advance them here: re-check arc (auto-
    # stop drifters), compute distance falloff, and route damage through
    # apply_hit (which already routes shields → subsystem → hull and
    # broadcasts WeaponHitEvent).  Shield-impact splash piggybacks on the
    # same host.shield_hit call torpedoes use.
    from engine.appc.subsystems import _emitter_in_arc
    from engine.appc.math import TGPoint3
    for ship in ships_list:
        sys_ = ship.GetPhaserSystem() if hasattr(ship, "GetPhaserSystem") else None
        if sys_ is None:
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
                apply_hit(target, damage, target_pos,
                          source=ship, subsystem=target_sub)
                if (host is not None
                        and ship_instances is not None
                        and hasattr(host, "shield_hit")):
                    iid = ship_instances.get(target)
                    if iid is not None:
                        host.shield_hit(
                            instance_id=iid,
                            point=(target_pos.x, target_pos.y, target_pos.z),
                            rgba=(0.0, 0.0, 0.0, 0.0),
                            intensity=1.0,
                        )

    if host is not None and hasattr(host, "set_torpedoes"):
        host.set_torpedoes(_build_torpedo_render_data())
    if host is not None and hasattr(host, "set_hit_vfx"):
        host.set_hit_vfx(_build_hit_vfx_render_data())
    if host is not None and hasattr(host, "set_phaser_beams"):
        host.set_phaser_beams(_build_phaser_beam_render_data(ships_list))


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
        out.append({
            "position": (pos.x, pos.y, pos.z),
            "age":      entry["age"],
        })
    return out


def _build_phaser_beam_render_data(ships):
    """Snapshot active phaser beams for the renderer.

    Walks every ship's PhaserSystem; for each bank IsFiring()=1, yields
    {emitter, target, color, width}.  Color is Federation amber (default
    until per-faction beam color is wired); width is a small constant.
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
            out.append({
                "emitter": (emitter_pos.x, emitter_pos.y, emitter_pos.z),
                "target":  (target_pos.x,  target_pos.y,  target_pos.z),
                # Federation amber, additive.  Per-faction colors are a
                # follow-up — PR 2c only ships the player Galaxy.
                "color":   (1.0, 0.6, 0.2, 1.0),
                # Width in world units.  Galaxy GetRadius() ≈ 4.4 wu;
                # ~0.4 reads as a clean beam line without dominating the
                # silhouette.
                "width":   0.4,
            })
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
    """Yaw/pitch/roll in degrees from a BC row-vector TGMatrix3.

    BC convention: Row 0 = right, Row 1 = forward (Y), Row 2 = up (Z).
    Yaw:   atan2(forward.x, forward.y) - heading around world Z
    Pitch: asin(forward.z)             - elevation (+ = nose up)
    Roll:  atan2(-right.z, up.z)       - bank (+ = right wing down)
    """
    fwd = R.GetRow(1)
    up  = R.GetRow(2)
    rgt = R.GetRow(0)
    yaw_deg   = _math.degrees(_math.atan2(fwd.x, fwd.y))
    pitch_deg = _math.degrees(_math.asin(max(-1.0, min(1.0, fwd.z))))
    roll_deg  = _math.degrees(_math.atan2(-rgt.z, up.z))
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

# Camera-follow distances as multiples of the player ship's GetRadius().
# BC's stock framing ratio is ~1.2× the ship's mesh diameter, which in our
# convention is ~2.4 × GetRadius (GetRadius corresponds to the AABB outer-
# corner sphere, larger than any single half-extent).
CAM_BACK_RADII =  1.5
CAM_UP_RADII   =  0.25
CAM_MIN_RADII  =  0.6
CAM_MAX_RADII  = 30.0
# Look-at offset along ship's body-up. Positive values move the ship
# downward on screen (because target shifts upward in world). Expressed
# as multiples of ship radius so framing is scale-invariant across ships.
CAM_LOOK_UP_RADII = 0.20
# Target-lock only: lift the chase eye along world-Z by this multiple
# of the player ship's GetRadius(), in addition to the line-extension
# placement. Pushes the ship lower in frame when the camera sits on
# the target→ship line (where there is otherwise no vertical offset).
CAM_TARGET_LOCK_LIFT_RADII = 1.0


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

    def __init__(self):
        self.impulse_level = 0  # signed: -2..9; 0 = stop
        self._current_speed = 0.0
        self._current_pitch_rate = 0.0
        self._current_yaw_rate   = 0.0
        self._current_roll_rate  = 0.0

    # ── Hardpoint accessors ──────────────────────────────────────────────────

    @staticmethod
    def _get_ies(player):
        getter = getattr(player, "GetImpulseEngineSubsystem", None)
        return getter() if getter else None

    def GetTargetSpeed(self, player) -> float:
        """Convert impulse_level into a target speed using the ship's
        ImpulseEngineProperty.MaxSpeed when present, or the legacy
        per-level placeholder otherwise."""
        ies = self._get_ies(player)
        max_speed = ies.GetMaxSpeed() if ies is not None else 0.0
        if max_speed > 0.0:
            if self.impulse_level >= 0:
                return (self.impulse_level / 9.0) * max_speed
            return -self.REVERSE_FRACTION * max_speed
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

        `h` is the _open_stbc_host bindings module (or any object with
        key_state, key_pressed, and `keys.KEY_*` attributes).
        """
        # 1. Throttle (one-shot edges).  R is checked before digits.
        # Shift+digit is reserved for alert-level binding (Shift+1/2/3 →
        # SetAlertLevel); suppress digit throttle while shift is held so
        # the two bindings don't fire together.
        if h.key_pressed(h.keys.KEY_R):
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

        # 2. Linear speed ramp toward target at MaxAccel rate.
        self._current_speed = self._ramp_toward(
            self._current_speed,
            self.GetTargetSpeed(player),
            self._max_accel(player) * dt,
        )

        # 3. Angular rates: held keys set a per-axis target rate; current rate
        #    ramps toward target at MaxAngularAccel.
        # Sign convention (row-vector matrices, Y=forward, Z=up):
        #   +X rotation tilts forward (row 1) toward -Z = nose DOWN.
        #   +Z rotation tilts forward toward +X = yaw RIGHT.
        #   +Y rotation tilts up (row 2) toward -X = roll LEFT.
        ang_rate    = self._angular_rate(player)
        ang_step    = self._angular_accel(player) * dt
        pitch_target = 0.0
        yaw_target   = 0.0
        roll_target  = 0.0
        if h.key_state(h.keys.KEY_W): pitch_target += ang_rate
        if h.key_state(h.keys.KEY_S): pitch_target -= ang_rate
        if h.key_state(h.keys.KEY_A): yaw_target   += ang_rate
        if h.key_state(h.keys.KEY_D): yaw_target   -= ang_rate
        if h.key_state(h.keys.KEY_Q): roll_target  -= ang_rate
        if h.key_state(h.keys.KEY_E): roll_target  += ang_rate
        self._current_pitch_rate = self._ramp_toward(self._current_pitch_rate, pitch_target, ang_step)
        self._current_yaw_rate   = self._ramp_toward(self._current_yaw_rate,   yaw_target,   ang_step)
        self._current_roll_rate  = self._ramp_toward(self._current_roll_rate,  roll_target,  ang_step)
        pitch_rate = self._current_pitch_rate
        yaw_rate   = self._current_yaw_rate
        roll_rate  = self._current_roll_rate

        # 4. Rotation integration.  BC uses row-vector matrices where
        #    v_world = v_body * R, so the rows of R are the body axes in
        #    world space.  Composing a body-frame delta D means D acts on
        #    the body vector first: v_world = (v_body * D) * R = v_body *
        #    (D * R).  So body-frame rotation is PRE-multiply (D * R), not
        #    post-multiply.  Pitch → yaw → roll Euler order.
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
            R = delta.MultMatrix(R)
            player.SetMatrixRotation(R)

        # 5. Position integration (forward = ship-local Y axis in world).
        if self._current_speed != 0.0:
            forward = R.GetRow(1)
            p = player.GetTranslate()
            player.SetTranslateXYZ(
                p.x + forward.x * self._current_speed * dt,
                p.y + forward.y * self._current_speed * dt,
                p.z + forward.z * self._current_speed * dt,
            )


class _CameraControl:
    """Arrow-key orbit + scroll-wheel zoom around the player ship.

    The orbit angles and distance are stored in the ship's body frame, so
    the camera "rotates with" the ship: when the ship banks/pitches/yaws,
    the relative camera position is preserved.

    Conventions:
      orbit_yaw_rad   — rotation around ship-Z. 0 = directly behind, +ve =
                        camera moves to ship-right, -ve = ship-left.
                        Wraps freely; not clamped.
      orbit_pitch_rad — elevation above the ship's XY plane. 0 = level with
                        the ship; +ve = camera above. Clamped to ±PITCH_LIMIT.
      distance        — eye-to-ship distance, multiplicative on scroll.

    Defaults reproduce the pre-orbit (-forward*600 + up*200) framing so
    existing setups look unchanged until the user touches arrows or scroll.
    """

    TURN_RATE_RAD_PER_S    = 1.5                                # ~86°/s
    ZOOM_FACTOR_PER_NOTCH  = 0.9                                # one scroll click ≈ 10%
    PITCH_LIMIT_RAD        = _math.radians(85)                  # avoid pole flip
    DEFAULT_YAW_RAD        = 0.0
    DEFAULT_PITCH_RAD      = _math.atan2(CAM_UP_RADII, CAM_BACK_RADII)
    SPRING_TAU_S           = 0.50                               # ~95% catch-up in 1.5s

    def __init__(self):
        self.orbit_yaw_rad      = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad    = self.DEFAULT_PITCH_RAD
        self._smoothed_rot      = None  # seeded on first compute_camera(..., dt=...)
        self.look_up_offset     = 0.0
        self.target_lock_enabled = True
        # Vertical shift of the look-at below the target as a fraction of
        # the eye→target distance — pushes the target up in the frame so
        # the player ship and target sit on opposite sides of screen
        # centre. ~sin(angular offset): 0.15 ≈ 9° ≈ 30% above centre at
        # 60° vertical FOV. 0 = target dead centre.
        self.target_lock_bias    = 0.15
        self.set_ship_radius(1.0)

    def set_ship_radius(self, radius: float) -> None:
        """Bind chase distances to the player ship's GetRadius(). Re-seeds
        self.distance if it was sitting at the prior default; preserves any
        user zoom that has occurred since the last reset."""
        radius = max(radius, 1e-6)
        prev_default = getattr(self, "default_distance", None)
        self.default_distance    = _math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * radius
        self.distance_min        = CAM_MIN_RADII * radius
        self.distance_max        = CAM_MAX_RADII * radius
        self.look_up_offset      = CAM_LOOK_UP_RADII * radius
        self.target_lock_z_lift  = CAM_TARGET_LOCK_LIFT_RADII * radius
        if prev_default is None or getattr(self, "distance", prev_default) == prev_default:
            self.distance = self.default_distance

    def reset_orbit(self) -> None:
        """Snap orbit angles and distance back to defaults. Does not change
        target_lock_enabled or the rotation-smoothing state."""
        self.orbit_yaw_rad   = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad = self.DEFAULT_PITCH_RAD
        self.distance        = self.default_distance

    def lock_to_target(self) -> None:
        """Snap orbit to defaults and enable target lock. Use on fresh
        target selection to give a clean 'over-the-shoulder, look at
        target' framing regardless of any manual orbit the user had set."""
        self.reset_orbit()
        self.target_lock_enabled = True

    def snap(self) -> None:
        """Drop smoothed rotation so the next compute_camera(..., dt=...) call
        aligns the camera immediately with the live ship rotation. Use on hard
        cuts (mission swap, teleport, warp exit)."""
        self._smoothed_rot = None

    def apply(self, dt: float, h, scroll_y: float) -> None:
        """Read arrow keys + C reset + accumulated scroll, update orbit state.

        `h` is the bindings module (or fake) with key_state/key_pressed and a
        `keys` namespace containing KEY_LEFT/RIGHT/UP/DOWN/C.
        `scroll_y` is the total wheel delta accumulated since the last call.
        """
        if h.key_pressed(h.keys.KEY_C):
            self.reset_orbit()
            self.target_lock_enabled = False
            return

        if h.key_state(h.keys.KEY_RIGHT): self.orbit_yaw_rad   += self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_LEFT):  self.orbit_yaw_rad   -= self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_UP):    self.orbit_pitch_rad += self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_DOWN):  self.orbit_pitch_rad -= self.TURN_RATE_RAD_PER_S * dt

        if self.orbit_pitch_rad >  self.PITCH_LIMIT_RAD: self.orbit_pitch_rad =  self.PITCH_LIMIT_RAD
        if self.orbit_pitch_rad < -self.PITCH_LIMIT_RAD: self.orbit_pitch_rad = -self.PITCH_LIMIT_RAD

        if scroll_y != 0.0:
            self.distance *= self.ZOOM_FACTOR_PER_NOTCH ** scroll_y
            if self.distance < self.distance_min: self.distance = self.distance_min
            if self.distance > self.distance_max: self.distance = self.distance_max

    def compute_camera(self, ship_loc, ship_rot, dt=None) -> tuple:
        """Return (eye, target, up) as 3-tuples in world space.

        Offset is built in ship body frame (X=right, Y=forward, Z=up):
            offset_body = (sin(y)*cos(p), -cos(y)*cos(p), sin(p)) * distance
        At y=0, p=0 the camera sits directly behind on the body-Y axis.
        Mapping body→world uses BC's row-vector convention: world_axis_j =
        basis.GetRow(j).

        When `dt` is given, the basis used here is a smoothed copy of the
        ship's rotation that lags the live value with time constant
        SPRING_TAU_S. This produces the "spring" feel where the ship visibly
        rotates against the camera during a manoeuvre, then settles. When
        `dt` is None the live rotation is used directly and no smoothing
        state is touched (legacy / pure-projection path used by tests).
        """
        basis = self._advance_smoothing(ship_rot, dt) if dt is not None else ship_rot

        cy = _math.cos(self.orbit_yaw_rad)
        sy = _math.sin(self.orbit_yaw_rad)
        cp = _math.cos(self.orbit_pitch_rad)
        sp = _math.sin(self.orbit_pitch_rad)
        d  = self.distance

        ox =  sy * cp * d
        oy = -cy * cp * d
        oz =       sp * d

        rgt = basis.GetRow(0)
        fwd = basis.GetRow(1)
        up  = basis.GetRow(2)

        # Shift look-target up along ship body-Z so the ship sits below
        # screen center. Eye is also shifted by the same amount so the
        # pitch angle (eye→target) stays unchanged — pure pan.
        lu = self.look_up_offset
        eye = (
            ship_loc.x + ox * rgt.x + oy * fwd.x + oz * up.x + lu * up.x,
            ship_loc.y + ox * rgt.y + oy * fwd.y + oz * up.y + lu * up.y,
            ship_loc.z + ox * rgt.z + oy * fwd.z + oz * up.z + lu * up.z,
        )
        target = (
            ship_loc.x + lu * up.x,
            ship_loc.y + lu * up.y,
            ship_loc.z + lu * up.z,
        )
        up_vec = (up.x, up.y, up.z)
        return eye, target, up_vec

    def _advance_smoothing(self, ship_rot, dt: float):
        """Blend self._smoothed_rot toward ship_rot, renormalize, and return
        the smoothed basis. Seeds from ship_rot on the first call."""
        from engine.appc.math import TGMatrix3, TGPoint3

        if self._smoothed_rot is None:
            seed = TGMatrix3()
            for i in range(3):
                seed.SetRow(i, ship_rot.GetRow(i))
            self._smoothed_rot = seed
            return self._smoothed_rot

        alpha = 1.0 - _math.exp(-dt / self.SPRING_TAU_S) if dt > 0.0 else 0.0
        blended = [None, None, None]
        for i in range(3):
            s = self._smoothed_rot.GetRow(i)
            l = ship_rot.GetRow(i)
            blended[i] = TGPoint3(
                s.x + alpha * (l.x - s.x),
                s.y + alpha * (l.y - s.y),
                s.z + alpha * (l.z - s.z),
            )

        # Gram-Schmidt re-orthonormalize: keep forward (row 1) as primary
        # axis, project up (row 2) perpendicular to it, derive right via
        # cross product. Body axes are right-handed: forward × up = right.
        def _norm(v):
            m = _math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
            return TGPoint3(v.x/m, v.y/m, v.z/m)

        f = _norm(blended[1])
        u_in = blended[2]
        dot_uf = u_in.x*f.x + u_in.y*f.y + u_in.z*f.z
        u = _norm(TGPoint3(
            u_in.x - dot_uf * f.x,
            u_in.y - dot_uf * f.y,
            u_in.z - dot_uf * f.z,
        ))
        r = TGPoint3(
            f.y * u.z - f.z * u.y,
            f.z * u.x - f.x * u.z,
            f.x * u.y - f.y * u.x,
        )

        self._smoothed_rot.SetRow(0, r)
        self._smoothed_rot.SetRow(1, f)
        self._smoothed_rot.SetRow(2, u)
        return self._smoothed_rot


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
        self._mode = self.EXTERIOR

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
    view_mode._last_synced_is_bridge = target


def _handle_esc_for_view_mode(view_mode: "_ViewModeController") -> None:
    """ESC in bridge mode returns to exterior. ESC in exterior mode does
    nothing here (the mission-picker handler still gets its turn — see
    run()). The side-effect sync runs on the next tick and releases the
    cursor / disables the bridge pass."""
    if view_mode.is_bridge:
        view_mode.toggle()


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
    MOUSE_SENSITIVITY = 0.005           # rad per pixel
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

    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    register_input_handlers(App.g_kEventManager)
    App.g_kSetManager._sets.clear()
    _waypoint_registry.clear()
    App._next_event_type_id = 1200


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

    BC's TGMatrix3 is row-vector (rows = body axes in world). The OpenGL shader
    consumes u_model column-vector (columns = body axes), so the rotation is
    transposed on the way out.

    Determinant normalization (workaround): the renderer is configured with
    glFrontFace(GL_CW) and assumes the world matrix has det < 0 — which holds
    for ships whose rotation came from AlignToVectors (it builds right = up ×
    forward, giving det = -1). Ships placed by other paths (e.g. Akira at the
    "Docking Exit" hardpoint, or any ship with identity rotation) arrive with
    a proper rotation (det = +1), and render inside-out because their world
    matrix flips screen-space winding the wrong way under GL_CW. Until the
    coupled fix lands (AlignToVectors → proper rotation, pipeline.cc →
    glFrontFace(GL_CCW), backdrop/sun cull state → GL_BACK), we negate the X
    body axis here when det > 0 so every rendered ship reaches the GPU with
    det < 0. ship.GetWorldRotation() is left untouched — camera-follow,
    physics, and AI continue to see the original rotation.
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
        rot._m[0][0]*sx, rot._m[1][0]*s, rot._m[2][0]*s, loc.x,
        rot._m[0][1]*sx, rot._m[1][1]*s, rot._m[2][1]*s, loc.y,
        rot._m[0][2]*sx, rot._m[1][2]*s, rot._m[2][2]*s, loc.z,
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
        rot._m[0][0]*sx, rot._m[1][0]*s, rot._m[2][0]*s, loc.x,
        rot._m[0][1]*sx, rot._m[1][1]*s, rot._m[2][1]*s, loc.y,
        rot._m[0][2]*sx, rot._m[1][2]*s, rot._m[2][2]*s, loc.z,
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
        # Invoked once after each successful loader.load(). host_loop wires
        # this to TargetListController.rebuild_from_snapshot so the panel
        # filters the player ship (Game.SetPlayer runs during loader.load
        # AFTER the ship is added to the set, so the initial publish_added
        # for the player can't filter itself out).
        self.post_load_hook: Optional[Callable[[], None]] = None

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

    Mirrors the surface of _open_stbc_host that _PlayerControl touches.
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


def _cursor_over_panel(h, panel_id: int) -> bool:
    """True when the cursor's framebuffer-pixel position falls inside
    the panel's screen rect.  Returns False when bindings are missing
    or the panel hasn't been laid out yet."""
    cursor_pos = getattr(h, "cursor_pos", None)
    panel_bounds = getattr(h, "panel_bounds", None)
    if cursor_pos is None or panel_bounds is None:
        return False
    cx, cy = cursor_pos()
    px, py, pw, ph = panel_bounds(panel_id)
    if pw <= 0.0 or ph <= 0.0:
        return False
    return (px <= cx < px + pw) and (py <= cy < py + ph)


def _apply_input(view_mode, player_control, cam_control,
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
        cam_control.apply(dt, h, scroll_y)
    else:
        player_control.apply(player, dt, _NO_INPUT)


def _compute_camera(view_mode, cam_control, *, player, dt) -> tuple:
    """Per-tick camera dispatch.

    Exterior mode delegates to _CameraControl.compute_camera (orbit +
    spring-lag). Bridge mode anchors at the ship origin looking along
    ship-Y forward (row 1 of the rotation matrix) with ship-Z as up
    (row 2). Returns (eye, target, up) as 3-tuples in world space, the
    same shape r.set_camera consumes.

    Target lock: in exterior mode, if cam_control.target_lock_enabled is
    True and the player has a non-self target via GetTarget(), the eye is
    rebuilt in a frame aligned with the ship→target axis. The chase
    distance (|eye - ship|) and the vertical lift (component along
    up_vec) from the body-frame chase camera are preserved; any sideways
    body-frame offset is folded into the chase distance. The result: as
    the target orbits around the ship, the camera smoothly orbits in the
    opposite direction, always keeping the ship between camera and
    target with a constant zoom and lift. Look-at is then placed on the
    target, shifted DOWN along image-up by cam_control.target_lock_bias
    × |eye→target| so the target projects into the upper portion of the
    frame. bias ≈ sin(angular offset), so 0.15 ≈ 9° (~30% above centre
    in a 60° vertical FOV). C toggles the lock flag.
    """
    loc = player.GetWorldLocation()
    rot = player.GetWorldRotation()
    if view_mode.is_bridge:
        fwd = rot.GetRow(1)
        up  = rot.GetRow(2)
        eye    = (loc.x, loc.y, loc.z)
        target = (loc.x + fwd.x, loc.y + fwd.y, loc.z + fwd.z)
        up_vec = (up.x, up.y, up.z)
        return eye, target, up_vec
    eye, target, up_vec = cam_control.compute_camera(loc, rot, dt=dt)
    if getattr(cam_control, "target_lock_enabled", False):
        tgt = player.GetTarget() if hasattr(player, "GetTarget") else None
        if tgt is not None and tgt is not player:
            try:
                tloc = tgt.GetWorldLocation()
                eye, up_vec = _relocate_eye_for_target_lock(
                    eye, up_vec, loc, tloc)
                z_lift = getattr(cam_control, "target_lock_z_lift", 0.0)
                if z_lift != 0.0:
                    eye = (eye[0], eye[1], eye[2] + z_lift)
                bias = getattr(cam_control, "target_lock_bias", 0.15)
                dx = tloc.x - eye[0]
                dy = tloc.y - eye[1]
                dz = tloc.z - eye[2]
                dist = _math.sqrt(dx*dx + dy*dy + dz*dz)
                s = bias * dist
                target = (
                    tloc.x - s * up_vec[0],
                    tloc.y - s * up_vec[1],
                    tloc.z - s * up_vec[2],
                )
            except AttributeError:
                pass
    return eye, target, up_vec


def _relocate_eye_for_target_lock(eye, up_vec, ship_loc, target_loc):
    """Place the eye on the line target→ship extended past the ship.

    Direction b_hat = (ship - target) / |ship - target| points from the
    target through the ship and out the far side. The camera sits at
    ship + b_hat × |original eye - ship|, so camera, ship, and target
    are exactly collinear with the ship between camera and target. The
    chase distance (|eye - ship|) is preserved so zoom carries over.

    up_vec is reprojected perpendicular to b_hat so the camera up stays
    orthogonal to the view axis. Falls back to world-Z, then world-X,
    when the original up_vec is parallel to the view axis (looking
    straight up/down at the target).

    Degenerate case: target ≈ ship — return inputs unchanged.
    """
    bx = ship_loc.x - target_loc.x
    by = ship_loc.y - target_loc.y
    bz = ship_loc.z - target_loc.z
    bm = _math.sqrt(bx*bx + by*by + bz*bz)
    if bm < 1e-6:
        return eye, up_vec
    bx, by, bz = bx/bm, by/bm, bz/bm

    ex = eye[0] - ship_loc.x
    ey = eye[1] - ship_loc.y
    ez = eye[2] - ship_loc.z
    chase_dist = _math.sqrt(ex*ex + ey*ey + ez*ez)

    new_eye = (
        ship_loc.x + bx * chase_dist,
        ship_loc.y + by * chase_dist,
        ship_loc.z + bz * chase_dist,
    )

    ux, uy, uz = up_vec
    u_dot_b = ux*bx + uy*by + uz*bz
    upx = ux - u_dot_b * bx
    upy = uy - u_dot_b * by
    upz = uz - u_dot_b * bz
    upm = _math.sqrt(upx*upx + upy*upy + upz*upz)
    if upm < 1e-6:
        upx = -bz * bx
        upy = -bz * by
        upz = 1.0 - bz * bz
        upm = _math.sqrt(upx*upx + upy*upy + upz*upz)
        if upm < 1e-6:
            upx = 1.0 - bx * bx
            upy = -bx * by
            upz = -bx * bz
            upm = _math.sqrt(upx*upx + upy*upy + upz*upz)
            if upm < 1e-6:
                return new_eye, up_vec
    return new_eye, (upx/upm, upy/upm, upz/upm)


def run(mission_name: str = SHIP_GATE_MISSION,
        max_ticks: Optional[int] = None) -> int:
    """Boot the renderer, init the named mission, run until the window closes
    or max_ticks is reached. Returns 0 on clean exit.

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

    _setup_sdk()

    import App
    from engine.core.loop import GameLoop

    r.init(1280, 720, "open_stbc",
           str(PROJECT_ROOT / "native" / "assets" / "ui"))
    try:
        from engine import ui
        from engine.ui.target_list import TargetListController
        ui.init()

        # Target list panel — mirrors live ships from ship_lifecycle.
        # Stage 1: ship names + affiliation only. Flip show_subsystems=True
        # to add populated subsystem buttons per row (stage 2).
        target_panel = ui.UiPanel(id="targets", anchor="top-left",
                                  width_vw=18.0, height_vh=55.0,
                                  title="Targets")
        target_list = TargetListController(
            target_panel,
            player_provider=lambda: App.Game_GetCurrentPlayer(),
            show_subsystems=True,
        )

        # Debug stat panel, top-right. Replaces the old hud.rml document.
        # Height accommodates the title + 5 stat rows + the "Load Mission"
        # button at the bottom without clipping (the panel has overflow:
        # hidden so under-tall heights silently cut the button off).
        debug_panel = ui.UiPanel(id="debug", anchor="top-right",
                                 width_vw=18.0, height_vh=28.0,
                                 title="Debug", collapsible=True)
        stat_ship   = debug_panel.stat("Ship",   "---")
        stat_system = debug_panel.stat("System", "---")
        stat_pos    = debug_panel.stat("Pos",    "0 0 0")
        stat_rot    = debug_panel.stat("Rot",    "Y0\xb0 P0\xb0 R0\xb0")
        stat_alert  = debug_panel.stat("Alert",  "---")

        # Bridge view marker — visible only when KEY_SPACE has toggled
        # _ViewModeController into bridge mode. PoC: text-only, no
        # bridge geometry yet.
        bridge_hud = ui.UiPanel(id="bridge_hud", anchor="top",
                                width_vw=20.0, height_vh=6.0,
                                title="BRIDGE VIEW")
        bridge_hud.set_visible(False)

        # Controller owns the renderer, the nif-handle cache, and the
        # current mission session. _MissionLoader.load() runs the
        # mission init + scene build; HostController.swap_mission()
        # queues a deferred swap that drains at the next tick.
        controller = HostController()
        controller.renderer = r
        controller.loader = _MissionLoader(controller, verbose=verbose)
        controller.post_load_hook = target_list.rebuild_from_snapshot

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
        target_list.rebuild_from_snapshot()    # filter player after Game.SetPlayer

        if verbose:
            ss = controller.session
            print(f"[host_loop] mission={mission_name}", flush=True)
            total = len(ss.ship_instances) + len(ss.planet_instances)
            print(f"[host_loop] {total} render instance(s) created "
                  f"({len(ss.ship_instances)} ships, "
                  f"{len(ss.planet_instances)} planets)", flush=True)

        # Mission picker — scans the SDK script tree and offers an
        # in-process swap via controller.swap_mission().
        from engine.missions import discover as discover_missions
        from engine.mission_picker import MissionPicker

        registry = discover_missions(PROJECT_ROOT / "sdk" / "Build" / "scripts")
        picker = MissionPicker(
            registry=registry,
            on_load=controller.swap_mission,
            on_cancel=lambda: None,
        )
        debug_panel.button("Load Mission", on_click=picker.open, radio=False)

        # Per-tick player input → ship-transform integrator.
        player_control = _PlayerControl()
        cam_control    = _CameraControl()
        if controller.session is not None and controller.session.player is not None:
            cam_control.set_ship_radius(controller.session.player.GetRadius())
        view_mode      = _ViewModeController()
        bridge_camera  = _BridgeCamera()
        # Selecting a ship in the target panel snaps the chase orbit back
        # to defaults and engages target lock — overrides any manual
        # orbit the player had set. C key reverses (resets + unlocks).
        target_list.on_target_change = lambda _ship: cam_control.lock_to_target()
        try:
            import _open_stbc_host as _h
        except ImportError:
            _h = None  # bindings module not built; skip input handling.
        # Bindings older than the orbit-camera change won't expose
        # consume_scroll_y; fall back to a zero-delta lambda so host_loop
        # still runs against an old _open_stbc_host.so without rebuilding.
        _consume_scroll = getattr(_h, "consume_scroll_y", None) if _h else None
        TICK_DT = 1.0 / 60.0

        loop = GameLoop()
        ticks = 0
        _dust_enabled = True   # mirrors DustPass default
        init_audio()
        _bootstrap_firing_pipeline()
        while not r.should_close():
            loop.tick()

            # Drain deferred picker actions (close + on_load/on_cancel)
            # first — picker click handlers fire inside RmlUi's dispatch
            # so they queue rather than tear panels down synchronously.
            # Then drain any queued mission swap before scene work.
            picker.drain()
            had_pending_swap = controller.pending_swap is not None
            controller._drain_pending_swap()
            if had_pending_swap:
                cam_control.snap()
            session = controller.session
            player = session.player if session is not None else None
            if had_pending_swap and player is not None:
                cam_control.set_ship_radius(player.GetRadius())

            # SPACE toggles bridge/exterior view modality. Polled before
            # the F-key handlers so the modality switch happens first in
            # the tick. _apply_view_mode_side_effects mirrors the flag
            # into renderer state (bridge pass enable + cursor lock) and
            # is idempotent — only fires when the mode changed.
            if _h is not None:
                view_mode.apply(_h)
                _apply_view_mode_side_effects(view_mode, _h)
            # F7 toggles space dust; F8 toggles the RmlUi debugger
            # overlay; F9 toggles whole-UI visibility; ESC dismisses the
            # mission picker (no-op when it isn't open).
            if _h is not None and _h.key_pressed(_h.keys.KEY_F7):
                _dust_enabled = not _dust_enabled
                _h.dust_set_enabled(_dust_enabled)
            if _h is not None and _h.key_pressed(_h.keys.KEY_F8):
                _h.toggle_ui_debugger()
            if _h is not None and _h.key_pressed(_h.keys.KEY_F9):
                _h.toggle_ui_visibility()
            # F10: debug shield-hit on the shield surface. Real BC weapons
            # impact the bubble at a surface point; firing at the ship
            # center would put the hit too far inside the bubble for the
            # distance falloff to ever exceed zero on the visible shell.
            # Offset along the ship's forward axis by ~1.5 × the ship's
            # GetRadius() so the hit lands near the bubble surface.
            if (_h is not None
                    and _h.key_pressed(_h.keys.KEY_F10)
                    and player is not None
                    and session is not None):
                iid = session.ship_instances.get(player)
                if iid is not None:
                    from engine.shields import fire_debug_hit
                    wp = player.GetWorldLocation()
                    try:
                        fwd = player.GetWorldRotation().GetRow(1)
                        fx, fy, fz = float(fwd.x), float(fwd.y), float(fwd.z)
                    except Exception:
                        fx, fy, fz = 1.0, 0.0, 0.0
                    offset = 1.0 * player.GetRadius()
                    fire_debug_hit(_h, instance_id=iid,
                                   world_point=(wp.x + fx * offset,
                                                wp.y + fy * offset,
                                                wp.z + fz * offset))
            if _h is not None and _h.key_pressed(_h.keys.KEY_ESCAPE):
                # Order: exit bridge mode first, then dismiss any open
                # picker. If both apply, ESC handles both.
                _handle_esc_for_view_mode(view_mode)
                picker.handle_key_esc()

            # Apply keyboard input to the player ship's transform and to the
            # orbit camera. Scroll delta is consumed once per tick; old
            # bindings without the binding return 0.0 via the fallback.
            scroll_y = _consume_scroll() if _consume_scroll is not None else 0.0

            # Route scroll: cursor over the targets panel -> list scroll.
            # Otherwise camera zoom (the existing path).
            if scroll_y != 0.0 and _h is not None:
                if _cursor_over_panel(_h, target_panel.panel_id):
                    target_list.scroll(-int(round(scroll_y)))
                    scroll_y = 0.0  # consumed by panel; camera gets nothing

            if player is not None and _h is not None:
                # Alert keys (Shift+1/2/3) run before the throttle handler;
                # _PlayerControl.apply checks _shift_held() to skip digit
                # throttling on the same press.
                _apply_alert_keys(_h, player)
                _apply_input(view_mode, player_control, cam_control,
                             player=player, dt=TICK_DT, h=_h,
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

            # Camera: orbit + zoom around the player ship (or origin fallback).
            if fixed_camera:
                fixed_radius = player.GetRadius() if player is not None else 1.0
                eye = (0.0, 0.0, CAM_MAX_RADII * fixed_radius)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, cam_control,
                    player=player, dt=TICK_DT)
                if view_mode.is_bridge:
                    mouse_dx, mouse_dy = _h.consume_mouse_delta() if _h else (0.0, 0.0)
                    bridge_camera.apply(mouse_dx, mouse_dy)
                    b_eye, b_target, b_up = bridge_camera.compute_camera()
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

            bridge_hud.set_visible(view_mode.is_bridge)

            active_set = _resolve_active_set(player)

            if player is not None:
                _R = player.GetWorldRotation()
                _p = player.GetWorldLocation()
                _yaw, _pitch, _roll = _extract_ypr(_R)
                _set_name = next(
                    (n for n, s in App.g_kSetManager._sets.items()
                     if s is active_set),
                    ""
                ) if active_set is not None else ""
                try:
                    _raw_script = player.GetScript() or ""
                except Exception:
                    _raw_script = ""
                _ship_display = _raw_script.split(".")[-1] if _raw_script else "---"
                stat_ship.set_value(_ship_display)
                stat_system.set_value(_set_name or "---")
                stat_pos.set_value("%.1f %.1f %.1f" % (_p.x, _p.y, _p.z))
                stat_rot.set_value(
                    "Y%.0f\xb0 P%.0f\xb0 R%.0f\xb0" % (_yaw, _pitch, _roll))
                stat_alert.set_value(_format_alert_level(player.GetAlertLevel()))

            ambient, directionals = _aggregate_lights(active_set)
            r.set_lighting(ambient, directionals)

            bridge_ambient, bridge_directionals = _aggregate_bridge_lights()
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
        r.shutdown()

    return 0
