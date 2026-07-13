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
from engine import host_io
from engine.appc.ship_iter import (
    iter_set_objects as _iter_set_objects,
    iter_ships as _iter_ships,
    iter_active_ships as _iter_active_ships,
)
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
# Engine-rumble names come from LoadTacticalSounds.LoadSounds(); bridge/alert
# names from the real LoadBridge.LoadSounds() at mission load (against a live
# backend, since init_audio_backend() runs before the mission loads).
from engine.audio.tg_sound import TGSoundManager  # noqa: F401

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
from engine.ui import bridge_officer_picking
from engine.core.game import Game_GetCurrentGame
from engine.appc import (
    projectiles,
    hit_vfx,
    particles,
    ship_death,
    camera_shake,
    hit_feedback,
    combat,
    damage_eligibility,
    weapon_tactical_commands,
    render_instances,
)
from engine.appc import viewscreen_static as _vss
# combat is imported as a module (not `from combat import apply_hit`) so call
# sites read combat.apply_hit at call time — tests monkeypatch that attribute.
from engine.appc.sensor_detection import can_detect, is_hidden_by_cloak
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.ships import ShipClass
from engine.appc.ship_death import _out_of_action as _oa
from engine.appc.ship_motion import _effective_motion, _cap_keep, _asymptote_step
from engine.appc.subsystems import (
    TorpedoTube,
    _EnergyWeaponFireMixin,
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


_audio_backend_ready = False


def init_audio_backend() -> None:
    """Boot the audio backend (idempotent).

    Must run before the SDK's LoadBridge.Load -> LoadSounds() at mission load
    so bridge SFX load into a live backend. Null backend if OPEN_STBC_AUDIO=0.
    """
    global _audio_backend_ready
    if _audio_mod is None or _audio_backend_ready:
        return
    backend = "null" if _os_mod.environ.get("OPEN_STBC_AUDIO") == "0" else "openal"
    _audio_mod.init(backend=backend)
    _audio_backend_ready = True


def init_audio() -> None:
    """Finish audio setup: backend (if not already up) + event listeners."""
    if _audio_mod is None:
        return
    init_audio_backend()
    install_engine_rumble_listener()
    _alert_listener.reset()


def shutdown_audio() -> None:
    global _audio_backend_ready
    if _audio_mod is None:
        return
    _audio_mod.shutdown()
    _audio_backend_ready = False


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

    # NOTE: TacticalInterfaceHandlers.Initialize (fire / targeting / camera /
    # turn handlers on the TCW) is deliberately NOT called here. The TCW
    # singleton is recreated by reset_sdk_globals on every mission (re)load,
    # which orphans any handlers registered on the boot instance; so that
    # function is the sole registrar, re-wiring the fresh TCW each load. Doing
    # it here too would double-register on the boot mission (double fire per
    # keypress).

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

    `host` supplies the `keys` constant submodule (button codes). The
    button-edge queries route through host_io, which no-ops safely when the
    native module is absent (e.g. headless test setup without a window).
    No-op when host lacks the `keys` submodule.
    """
    if host is None or not hasattr(host, "keys"):
        return
    import App  # deferred: module-top import reorders sound-manager init
    # Left-click → phasers (primary), right-click → torpedoes (secondary),
    # middle-click → disruptors/pulse weapons (tertiary).  Matches the SDK's
    # DefaultKeyboardBinding mouse bindings (WC_LBUTTON/RBUTTON/MBUTTON).
    for glfw_btn, wc in (
        (host.keys.MOUSE_BUTTON_LEFT,   App.WC_LBUTTON),
        (host.keys.MOUSE_BUTTON_RIGHT,  App.WC_RBUTTON),
        (host.keys.MOUSE_BUTTON_MIDDLE, App.WC_MBUTTON),
    ):
        if host_io.mouse_button_pressed(glfw_btn):
            App.g_kInputManager.OnKeyDown(wc)
        if host_io.mouse_button_released(glfw_btn):
            App.g_kInputManager.OnKeyUp(wc)


# Previous-frame F-key levels for edge detection (host has key_pressed for
# rising edges but no key_released; deriving both edges from key_state keeps
# the pair symmetric). Module-level so tests can reset it.
_fn_key_prev: dict = {}


def _poll_key_table(keymap) -> None:
    """Edge-detect each (glfw_key, WC_code) in `keymap` and forward rising/
    falling edges to g_kInputManager.OnKeyDown/OnKeyUp.  Shares the module
    _fn_key_prev level cache so every polled key derives both edges from
    host_io.key_state (the host exposes key_pressed for rising edges but no
    key_released)."""
    import App  # deferred: module-top import reorders sound-manager init
    for glfw_key, wc in keymap:
        down = bool(host_io.key_state(glfw_key))
        was_down = _fn_key_prev.get(glfw_key, False)
        if down and not was_down:
            App.g_kInputManager.OnKeyDown(wc)
        elif was_down and not down:
            App.g_kInputManager.OnKeyUp(wc)
        _fn_key_prev[glfw_key] = down


def _poll_function_keys(host, input_map) -> None:
    """Forward the crew-talk keys (F1-F5 by default) into g_kInputManager.

    The physical key for each crew-talk action comes from `input_map`; the
    WC_F1..F5 code feeding the BC binding stays fixed, so DefaultKeyboardBinding's
    WC_F1→ET_INPUT_TALK_TO_* mapping is unchanged — only which key drives each
    WC slot is remappable.  See docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md.

    `host` is unused (key reads route through host_io, which no-ops safely when
    the native module is absent); kept in the signature for callsite symmetry
    with the other pollers.
    """
    del host  # noqa: F841 — key reads go through host_io, not this handle.
    import App  # deferred: module-top import reorders sound-manager init
    _poll_key_table((
        (input_map.code("talk_helm"),        App.WC_F1),
        (input_map.code("talk_tactical"),    App.WC_F2),
        (input_map.code("talk_xo"),          App.WC_F3),
        (input_map.code("talk_science"),     App.WC_F4),
        (input_map.code("talk_engineering"), App.WC_F5),
    ))


def _poll_fire_keys(host, input_map) -> None:
    """Forward the weapon-fire keys (F/X/G by default) into g_kInputManager.

    Primary → ET_INPUT_FIRE_PRIMARY (phasers), Secondary → SECONDARY (torpedoes),
    Tertiary → TERTIARY (disruptors/pulse weapons).  The physical key for each
    comes from `input_map`; the WC_F/WC_X/WC_G codes feeding the BC binding stay
    fixed (DefaultKeyboardBinding.py:96-103 maps them to the fire events, and
    TacticalInterfaceHandlers routes those to FireWeapons → StartFiring with
    keydown=1/keyup=0).

    Firing still requires a selected target — FireWeapons no-ops when
    pShip.GetTarget() is None.

    `host` is unused (key reads route through host_io, which no-ops safely when
    the native module is absent); kept in the signature for callsite symmetry
    with the other pollers.
    """
    del host  # noqa: F841 — key reads go through host_io, not this handle.
    import App  # deferred: module-top import reorders sound-manager init
    _poll_key_table((
        (input_map.code("fire_primary"),   App.WC_F),
        (input_map.code("fire_secondary"), App.WC_X),
        (input_map.code("fire_tertiary"),  App.WC_G),
    ))


_tractor_toggle_prev: bool = False


def _poll_tractor_toggle(host) -> None:
    """Forward the Alt+T tractor-beam toggle chord into the toggle event.

    BC binds WC_ALT_T (DefaultKeyboardBinding.py:42) → ET_OTHER_BEAM_TOGGLE_CLICKED,
    but the Alt-modifier WC constants are unwired in our input pipeline (input.py
    intentionally leaves the ALT_ variants as stubs).  So we detect the chord
    directly off the host key state and post the toggle event to the tactical
    control window, where TacticalInterfaceHandlers registered
    BridgeHandlers.ToggleTractorBeam (which flips the beam toggle and re-fires to
    App._TacWeaponsCtrl → StartFiring/StopFiring on the player's tractor).

    Rising-edge only: one toggle per press.  No-ops on a stale binary whose
    `keys` submodule predates KEY_T (graceful — tractor stays toggle-via-UI).
    """
    global _tractor_toggle_prev
    if host is None:
        return
    keys = getattr(host, "keys", None)
    if keys is None or not hasattr(keys, "KEY_T"):
        return
    alt = (bool(host_io.key_state(keys.KEY_LEFT_ALT))
           or bool(host_io.key_state(keys.KEY_RIGHT_ALT)))
    chord = alt and bool(host_io.key_state(keys.KEY_T))
    if chord and not _tractor_toggle_prev:
        import App  # deferred: module-top import reorders sound-manager init
        App.ToggleTractorFromInput()
    _tractor_toggle_prev = chord


_cloak_toggle_prev: bool = False


def _poll_cloak_toggle(host) -> None:
    """Forward the Alt+C cloak toggle chord into the cloak toggle event.

    BC binds WC_ALT_C (DefaultKeyboardBinding.py:43) → ET_OTHER_CLOAK_TOGGLE_CLICKED,
    but the Alt-modifier WC constants are unwired in our input pipeline, so detect
    the chord directly off the host key state and drive App.ToggleCloakFromInput()
    (which no-ops for ships without a cloaking device).  Mirrors
    _poll_tractor_toggle exactly.

    Rising-edge only: one toggle per press.  No-ops on a stale binary whose
    `keys` submodule predates KEY_C (graceful — cloak stays toggle-via-UI).
    """
    global _cloak_toggle_prev
    if host is None:
        return
    keys = getattr(host, "keys", None)
    if keys is None or not hasattr(keys, "KEY_C"):
        return
    alt = (bool(host_io.key_state(keys.KEY_LEFT_ALT))
           or bool(host_io.key_state(keys.KEY_RIGHT_ALT)))
    chord = alt and bool(host_io.key_state(keys.KEY_C))
    if chord and not _cloak_toggle_prev:
        import App  # deferred: module-top import reorders sound-manager init
        App.ToggleCloakFromInput()
    _cloak_toggle_prev = chord


_skip_dialogue_prev: bool = False


def _poll_skip_dialogue(host, input_map) -> None:
    """Backspace (remappable: skip_dialogue) skips the current dialogue line.

    BC binds WC_BACKSPACE → ET_INPUT_SKIP_EVENTS (DefaultKeyboardBinding.py:120)
    and every interface handler routes that to TacticalInterfaceHandlers.SkipEvents,
    which calls App.TGActionManager_SkipEvents().  Our engine doesn't run the SDK
    keyboard-binding path, so poll the physical key here: broadcast the SDK event
    (any mission-registered ET_INPUT_SKIP_EVENTS handler still hears it) and call
    the Appc endpoint directly.  A double SkipEvents from both paths is harmless —
    the second call finds nothing left to skip.

    Rising-edge only.  The callsite sits inside the `not pause.sim_frozen` sim
    block, so Backspace typed into pause-menu panels (Controls remap capture,
    config fields) never skips dialogue.
    """
    global _skip_dialogue_prev
    del host  # noqa: F841 — key reads go through host_io, not this handle.
    down = bool(host_io.key_state(input_map.code("skip_dialogue")))
    if down and not _skip_dialogue_prev:
        import App  # deferred: module-top import reorders sound-manager init
        ev = App.TGEvent_Create()
        ev.SetEventType(App.ET_INPUT_SKIP_EVENTS)
        App.g_kEventManager.AddEvent(ev)
        App.TGActionManager_SkipEvents()
    _skip_dialogue_prev = down


def _push_cloak_refraction(r, session, player) -> None:
    """Per-frame cloak VFX wiring.

    For each cloak-capable ship: hide the opaque hull the moment cloaking
    *begins* (``frac > 0``) and hand the hull over to the cloak pass, which
    re-draws it as a translucent, glow-keyed, refracting shell.  Because the
    shell owns the hull for the whole transition, its opacity fades gradually
    (no instant pop at ``frac == 1``) and it shimmers/wobbles as it engages.

    Push list:
      * ``frac <= 0`` — fully decloaked: hull visible, not pushed.
      * ``0 < frac < 1`` — transition (any ship): hull hidden, pushed so it
        shimmers and fades out.
      * ``frac >= 1`` **player** — pushed at ``1.0`` (the player keeps a faint,
        glow-keyed textured hull so the pilot can place the ship).
      * ``frac >= 1`` **enemy** — hidden and NOT pushed: truly invisible,
        preserving BC stealth gameplay.

    Visibility is recomputed from the live cloak state every frame, so any
    decloak — including an InstantDecloak that skips the DECLOAKING state —
    restores the hull with no leaked bookkeeping."""
    if session is None:
        return
    ships = getattr(session, "ship_instances", None)
    if not ships:
        r.set_cloak_ships([])
        return
    cloak_list = []
    for ship, iid in list(ships.items()):
        getter = getattr(ship, "GetCloakingSubsystem", None)
        if getter is None:
            continue
        cloak = getter()
        if cloak is None:
            continue
        frac = cloak.GetTransitionFraction()
        # Hull leaves the opaque pass as soon as cloaking begins; the cloak
        # shell renders it (translucent, fading) for the whole frac > 0 range.
        try:
            r.set_visible(iid, frac <= 0.0)
        except Exception as _e:
            dev_mode.log_swallowed("cloak set_visible", _e)
        if frac <= 0.0:
            continue                          # fully decloaked: no shell
        if bool(cloak.IsCloaked()) and ship is not player:
            continue                          # fully-cloaked enemy: invisible
        cloak_list.append((iid, frac))
    r.set_cloak_ships(cloak_list)


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
                # isinstance, NOT hasattr: TGObject.__getattr__ returns a truthy
                # _Stub for any missing attribute, so hasattr() is vacuously True
                # on every subsystem. The old hasattr(emitter, "UpdateCharge")
                # guard therefore CALLED a no-op stub on every torpedo tube, every
                # frame -- ranks 1 and 2 of docs/stub_heatmap.md, 4.5M hits.
                # Charge is an EnergyWeapon concept (App.py:6426-6440); a
                # TorpedoTube cannot have it.
                if isinstance(emitter, TorpedoTube):
                    emitter.UpdateReload(dt)
                elif isinstance(emitter, _EnergyWeaponFireMixin):
                    emitter.UpdateCharge(dt)


def _phaser_damage_for_tick(max_damage: float,
                             max_damage_distance: float,
                             dist: float,
                             dt: float) -> float:
    """Phaser damage: plateau within MaxDamageDistance, then R/d decay.

    Verified against the real BC engine via dev-console instrumentation
    (docs/instrumented_experiments/2026-06-29-weapon-exchange-console-probe.md,
    probe q09). Damage is FULL while `dist <= MaxDamageDistance` (R), then
    decays inverse-linearly as `MaxDamage * (R / dist)` beyond R — so a shot
    still deals ~30% at ~2.9*R. The curve is continuous at dist=R (both
    branches give `MaxDamage * dt`). Returns 0 if MaxDamageDistance is 0
    (uninitialized property).

    This replaced the earlier inverse-square `MaxDamage/(1+(dist/R)**2)`
    guess, which under-damaged at every range beyond ~0.5*R.

    No hard distance cutoff here — the system-level fire gate
    (PhaserSystem at PHASER_MAX_RANGE_GU = 700 GU ≈ 122.5 km) prevents
    fire on out-of-range targets, so this function only runs for shots
    the engine already decided to take."""
    if max_damage_distance <= 0.0:
        return 0.0
    if dist <= max_damage_distance:
        return max_damage * dt                       # plateau within R
    return max_damage * (max_damage_distance / dist) * dt   # R/d beyond


def _advance_combat(ships, dt: float, ship_instances=None) -> None:
    """Per-frame torpedo motion + collision + damage + renderer push.

    Walks the active torpedo registry, advances motion, routes hits
    through combat.apply_hit (which calls hit_feedback.dispatch and
    broadcasts WeaponHitEvent), ages out expired VFX, and pushes current
    torpedo + hit-VFX lists to the renderer.

    All hit/damage/VFX native touches route through the engine.host_io
    façade (which no-ops when headless), so no raw host module is needed.

    `ship_instances` maps ship → renderer instance id; passed through to
    apply_hit so hit_feedback.dispatch can fire the shield flash (via
    host_io.shield_hit) on the SHIELD severity path.
    """
    ships_list = list(ships)

    # Refresh damage-carve eligibility for this tick before any hits are
    # processed: player always + capped nearest/largest ships.
    # See engine.appc.damage_eligibility.
    damage_eligibility.update(ships_list)

    hits = projectiles.update_all(
        dt, ships_list,
        ship_instances=ship_instances,
    )
    for torpedo, ship, hit_point, hit_normal in hits:
        combat.apply_hit(ship, torpedo._damage, hit_point,
                  source=torpedo._source_ship,
                  normal=hit_normal, ship_instances=ship_instances,
                  weapon_type="torpedo",
                  hardpoint_weapon=torpedo)

    hit_vfx.update_ages(dt)
    from engine.appc import shockwaves
    shockwaves.advance(dt)
    particles.advance(dt)
    ship_death.advance(dt)
    from engine.appc import subsystem_cascade, warp_core_breach
    subsystem_cascade.advance(dt)
    warp_core_breach.advance(dt, ship_instances=ship_instances)
    from engine.appc import core_breach_carve
    core_breach_carve.advance(dt, ship_instances=ship_instances)
    from engine.appc import visible_damage
    visible_damage.advance(dt, ship_instances=ship_instances)
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
        # Power-off gate: a system turned off via the power slider (IsOn()==0)
        # must also stop any already-firing banks immediately.  _is_offline
        # only checks IsDisabled/IsDestroyed and does NOT cover the powered-
        # down case, so we gate on IsOn() here as a separate check.
        if _is_offline(sys_) or not sys_.IsOn():
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
                    ship_instances=ship_instances, ship=target,
                    ray_origin=emitter_pos,
                    ray_direction=(aim_unit if dist > 1e-6 else None),
                    max_dist=(dist * 1.5 if dist > 1e-6 else 0.0),
                    fallback_point=target_pos,
                )
                # LIGHT (PP_LOW) phaser power is "disable, don't destroy":
                # damage routes to subsystems only, the hull takes no condition
                # damage and is not voxel-carved (verified by dev-console probe).
                # `sys_` is the firing PhaserSystem; read PP_LOW off it directly.
                damage_hull = (sys_.GetPowerLevel() != sys_.PP_LOW
                               if hasattr(sys_, "GetPowerLevel") else True)
                combat.apply_hit(target, damage, impact_point,
                          source=ship,
                          normal=impact_normal,
                          ship_instances=ship_instances,
                          weapon_type="phaser",
                          hardpoint_weapon=bank,
                          damage_hull=damage_hull)

    # Held-trigger pulse weapons (disruptors/cannons): re-fire eligible cannons
    # as they recharge while the trigger stays down — mirrors the phaser
    # retry_held_fire above. No damage routing here: pulse bolts are spawned
    # into projectiles._active by PulseWeapon.Fire and handled by the torpedo
    # hit loop / render push above. retry_held_fire self-stops if the system
    # is offline or the target died, and no-ops unless the trigger is held.
    for ship in ships_list:
        psys = (ship.GetPulseWeaponSystem()
                if hasattr(ship, "GetPulseWeaponSystem") else None)
        if psys is not None:
            psys.retry_held_fire()

    # Tractor beams (hold/tow/pull/push/dock): sustain the held grab beam as the
    # target stays in range, then apply the mode's physics to the target.
    # retry_held_fire keeps one sustained beam (SingleFire) and self-stops if the
    # system is offline / target died / target left range; advance_tractors moves
    # the target (and reciprocally the source) via direct position displacement.
    # Both no-op for ships without a firing tractor (production stays identical).
    for ship in ships_list:
        tsys = (ship.GetTractorBeamSystem()
                if hasattr(ship, "GetTractorBeamSystem") else None)
        if tsys is not None and hasattr(tsys, "retry_held_fire"):
            tsys.retry_held_fire()
    from engine.appc import tractor as _tractor
    _tractor.advance_tractors(ships_list, dt)

    # Per-frame VFX descriptor lists route through the host_io façade, which
    # no-ops when the native module is absent (headless). The hit/damage
    # bindings (ray_trace_mesh, shield_hit, world_to_body, …) inside the
    # _build_* helpers and the combat/carve advances now route through
    # host_io too, so nothing below consumes the raw `host` module.
    host_io.set_torpedoes(_build_torpedo_render_data())
    from engine.appc import shockwaves as _shockwaves
    host_io.set_shockwaves(_shockwaves.render_data())
    host_io.set_hit_vfx(_build_hit_vfx_render_data())
    host_io.set_particle_emitters(_build_particle_render_data(ship_instances))
    host_io.set_phaser_beams(_build_phaser_beam_render_data(
        ships_list, ship_instances=ship_instances))
    host_io.set_tractor_beams(_build_tractor_beam_render_data(
        ships_list, ship_instances=ship_instances))


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


def _dim_color(c, scale):
    """Scale a color tuple's RGB by `scale`, leaving alpha untouched."""
    return (c[0] * scale, c[1] * scale, c[2] * scale, c[3])


def _build_torpedo_render_data():
    """Convert projectiles._active into the dict shape set_torpedoes expects."""
    out = []
    for t in projectiles._active:
        out.append({
            "position":      (t._position.x, t._position.y, t._position.z),
            "core_texture":  _resolve_game_texture(t._core_texture),
            "core_color":    _dim_color(_color_tuple(t._core_color),
                                        TORPEDO_BRIGHTNESS),
            "core_size_a":   t._core_size_a,
            "core_size_b":   t._core_size_b,
            "glow_texture":  _resolve_game_texture(t._glow_texture),
            "glow_color":    _dim_color(_color_tuple(t._glow_color),
                                        TORPEDO_BRIGHTNESS),
            "glow_size_a":   t._glow_size_a,
            "glow_size_b":   t._glow_size_b,
            "glow_size_c":   t._glow_size_c,
            "flares_texture": _resolve_game_texture(t._flares_texture),
            "flares_color":  _dim_color(_color_tuple(t._flares_color),
                                        TORPEDO_BRIGHTNESS),
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

# Brightness scale on phaser beam colours (additive blend) — dims the beam
# without touching the hardpoint hue. Mirrors TRACTOR_BEAM_BRIGHTNESS below.
PHASER_BEAM_BRIGHTNESS = 0.75

# Brightness scale on torpedo/bolt layer colours (core, glow, flares) —
# projectiles read too hot against the HDR pipeline (tune-by-eye).
TORPEDO_BRIGHTNESS = 0.75


def _beam_descriptor_pair(ship, bank, ship_instances):
    """Build the (outer-shell, inner-core) beam descriptor pair for one firing
    energy emitter — a phaser bank OR a tractor emitter.  Both inherit the same
    beam visual getters (NumSides / MainRadius / shell+core colours / texture
    speed / taper) from PhaserProperty, and the same strip/point emit geometry,
    so the render build is identical; only the parent system differs (handled
    by the callers).  Returns [] when the bank has no target.

    When `ship_instances` is supplied, the beam endpoint is clipped to the
    mesh-trace surface point (via host_io.ray_trace_mesh inside
    combat._resolve_hit_point) so the visible beam ends on the target's hull
    rather than at its bounding-sphere centre.
    """
    target = bank._target
    if target is None:
        return []
    target_sub = (ship.GetTargetSubsystem()
                  if hasattr(ship, "GetTargetSubsystem") else None)
    if target_sub is not None and hasattr(target_sub, "GetWorldLocation"):
        target_pos = target_sub.GetWorldLocation()
    else:
        target_pos = target.GetWorldLocation()
    # Strip emit point for curved phaser banks; point emitters (tractors,
    # Length 0) collapse this to the emitter mount world position.
    emitter_pos = bank._strip_emit_position(target_pos)
    dx = target_pos.x - emitter_pos.x
    dy = target_pos.y - emitter_pos.y
    dz = target_pos.z - emitter_pos.z
    raw_length = (dx * dx + dy * dy + dz * dz) ** 0.5
    beam_length = raw_length
    beam_end = target_pos
    if raw_length > 1e-6 and ship_instances is not None:
        aim_unit = TGPoint3(dx / raw_length, dy / raw_length, dz / raw_length)
        clipped, _clipped_normal = combat._resolve_hit_point(
            ship_instances=ship_instances, ship=target,
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
    # SDK four-channel-colour layout (galaxy.py phaser :418-431, tractor :869-877)
    # is OuterShell / InnerShell / OuterCore / InnerCore.  We approximate with
    # two concentric beams: the outer shell (the dominant tint — orange for
    # phasers, blue for tractors) and a thinner inner-core sheen.  The inner
    # uses reduced alpha (0.35) so its additive contribution is a subtle
    # highlight rather than a saturating wash.
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
    return [
        {**common, "color": outer_color, "width": float(outer_half)},
        {**common, "color": inner_color, "width": float(inner_half)},
    ]


def _build_phaser_beam_render_data(ships, ship_instances=None):
    """Snapshot active phaser beams for the renderer.

    Walks every ship's PhaserSystem; for each bank IsFiring()=1, yields the
    outer-shell + inner-core descriptor pair via _beam_descriptor_pair.
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
            for d in _beam_descriptor_pair(ship, bank, ship_instances):
                c = d["color"]
                d["color"] = (c[0] * PHASER_BEAM_BRIGHTNESS,
                              c[1] * PHASER_BEAM_BRIGHTNESS,
                              c[2] * PHASER_BEAM_BRIGHTNESS,
                              c[3])
                out.append(d)
    return out


# Tractor beam funnels OUT toward the captured target — the target end flares to
# this multiple of the body radius (the shader widens the target-end taper
# instead of pinching it).
TRACTOR_BEAM_END_WIDTH_SCALE = 1.25

# Brightness scale on the tractor beam colour (additive blend) — dims the beam
# without touching the hardpoint hue.
TRACTOR_BEAM_BRIGHTNESS = 0.5


def _build_tractor_beam_render_data(ships, ship_instances=None):
    """Snapshot active tractor beams for the renderer.

    Mirrors _build_phaser_beam_render_data but walks each ship's
    TractorBeamSystem.  Tractor emitters are TractorBeamProperty-backed and
    inherit the full beam visual surface from PhaserProperty, so the descriptor
    build is shared (_beam_descriptor_pair) — the Galaxy hardpoint's blue
    colours / TractorBeam.tga / 12 sides come straight off the emitter.
    Rendered by the same weapon-agnostic beam pass (g_phaser_pass) via the
    set_tractor_beams host binding.

    Tractor beams keep the emitter taper-in and normal body width, but flare the
    TARGET end out to TRACTOR_BEAM_END_WIDTH_SCALE × the body radius (the shader
    reads end_width_scale to make the target-end taper widen instead of pinch).
    """
    out = []
    for ship in ships:
        sys_ = (ship.GetTractorBeamSystem()
                if hasattr(ship, "GetTractorBeamSystem") else None)
        if sys_ is None:
            continue
        for i in range(sys_.GetNumWeapons()):
            bank = sys_.GetWeapon(i)
            if bank is None or not bank.IsFiring():
                continue
            for d in _beam_descriptor_pair(ship, bank, ship_instances):
                d["end_width_scale"] = TRACTOR_BEAM_END_WIDTH_SCALE
                c = d["color"]
                d["color"] = (c[0] * TRACTOR_BEAM_BRIGHTNESS,
                              c[1] * TRACTOR_BEAM_BRIGHTNESS,
                              c[2] * TRACTOR_BEAM_BRIGHTNESS,
                              c[3])
                out.append(d)
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


def _game_asset_path(p):
    """Resolve a game-relative asset path to an absolute path string.
    Mirrors _place_one_character's local _abs helper; defined here so it can
    be passed to BridgeCharacterAnimController as the asset_resolver."""
    return str(PROJECT_ROOT / "game" / p) if p else None


def _clip_duration(renderer, rel_path) -> float:
    """Max keyframe time across a clip's tracks - the clip's real length.

    Feeds App.g_kAnimationManager.set_duration_provider so
    GetAnimationLength("db_PtoL1_P") returns the real walk-clip duration
    instead of 0.0 (PicardAnimations.py:145 schedules the lift door at
    GetAnimationLength(walk) - 1.25). Any failure degrades to 0.0 rather
    than raising, so a missing/broken clip can never stall a TGSequence.
    """
    try:
        clips = renderer.load_animation_clips(_game_asset_path(rel_path))
    except Exception:
        return 0.0
    if not clips:
        return 0.0
    longest = 0.0
    for track in clips[0].get("tracks", []):
        for channel in ("translation", "rotation"):
            keys = track.get(channel) or []
            if keys:
                longest = max(longest, float(keys[-1][0]))
    return longest


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
# Captain camera-mode "place by direction" movement, harvested from the SDK
# GalaxyBridgeCaptain mode (CameraModes.py): ((mx, my, mz), start_rad, end_rad)
# or None. Applied by _eye_offset as a gradual lift as the view turns off
# bridge-forward: the eye eases out (forward -Y + up +Z) over the SDK angle band
# — matching the original's rise on turn. None → no movement (e.g. Sovereign).
_BRIDGE_CAMERA_MOVE: tuple = None
# Feel knob over the SDK movement magnitude (SDK = 1.0). Tune to taste.
_BRIDGE_CAMERA_MOVE_SCALE: float = 1.0
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

# In-warp lighting (streak phase). The system the player left is torn down, so
# its sun is gone; the only light is the warp tunnel rushing toward the ship.
# A bright cool key from AHEAD (down travel_dir) lights the front of the hull as
# if by the tunnel, with a dim cool back-fill so the rear isn't black, over a low
# cool ambient. Direction is a deliberate cinematic vector (the warp heading),
# not a world-up reference. Biased strong for first-look calibration — dial down
# to taste (calibrate up, then down). All three scale by streak_intensity so the
# warp look fades in at the burst and out at the exit.
_WARP_LIGHT_KEY: tuple = (0.7, 0.9, 1.6)      # cool blue-white, from ahead
_WARP_LIGHT_FILL: tuple = (0.12, 0.16, 0.30)  # dim cool, from behind
_WARP_LIGHT_AMBIENT: tuple = (0.05, 0.07, 0.13)

# Galaxy-map units/sec the procedural-sky vantage flies forward during transit.
# Galaxy systems sit ~50-260 units apart, so ~15 u/s over a 10-20s transit
# covers a full inter-system hop — clear cluster/nebula parallax. Tunable.
_WARP_SKY_RATE: float = 15.0


def _warp_transit_backdrops(wvfx):
    """Procedural-sky backdrops projected from the warp manager's advancing
    vantage, so the distant clusters/nebulae stream past during transit. Falls
    back to a blacked-out sky ([]) when the source wasn't galaxy-mapped (no
    vantage) or the procedural sky is off."""
    vantage = wvfx.sky_vantage(_WARP_SKY_RATE)
    if vantage is None or not r.procedural_sky_enabled():
        return []
    from engine.appc import sky_projection as sp
    return sp.project_sky(vantage, sp.load_sector_model())


def _warp_transit_lighting(travel, streak):
    """(ambient, directionals) for the in-warp scene.

    `travel` is the world-space warp heading; `streak` (0..1) fades the whole
    rig in/out. The key light points TOWARD the travel direction (lit from where
    the ship is flying into); the fill comes from directly behind.
    """
    tx, ty, tz = travel
    m = (tx * tx + ty * ty + tz * tz) ** 0.5
    fwd = (0.0, 1.0, 0.0) if m < 1e-6 else (tx / m, ty / m, tz / m)
    back = (-fwd[0], -fwd[1], -fwd[2])
    s = 0.0 if streak < 0.0 else (1.0 if streak > 1.0 else streak)
    key = tuple(c * s for c in _WARP_LIGHT_KEY)
    fill = tuple(c * s for c in _WARP_LIGHT_FILL)
    amb = tuple(c * s for c in _WARP_LIGHT_AMBIENT)
    return amb, [(fwd, key), (back, fill)]

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

    def __init__(self, input_map=None):
        # Single source of truth for action → physical key.  Defaults to a
        # fresh InputMap (stock keys, no file) so headless tests that build
        # _PlayerControl() keep the W/S/A/D/Q/E/R/0 defaults.
        if input_map is None:
            from engine.input_map import InputMap
            input_map = InputMap()
        self._input_map = input_map
        self.impulse_level = 0  # signed: -2..9; 0 = stop
        self._current_speed = 0.0
        self._current_pitch_rate = 0.0
        self._current_yaw_rate   = 0.0
        self._current_roll_rate  = 0.0
        self._warp_boost = False
        self._drift_velocity = None   # TGPoint3 while drifting (f==0), else None
        # Set by the warp sequence (host) during a warp: forces the ship's speed
        # (0 = hold during align, >0 = burst forward during transit) along its
        # current warp-aligned heading, ignoring throttle/input. None = normal
        # player control. The camera follows, so the dust velocity-smear adds to
        # the warp streak.
        self._warp_speed_override = None
        # True while a helm AI (player.GetAI() non-None) owns ship motion —
        # apply() then skips the whole ship-motion path (translation AND
        # rotation) and the AI setpoints + _step_ship_motion integrate the
        # transform instead. Tracked so both handoff edges can re-sync state
        # (manual→AI: seed the ship-side integrator; AI→manual: resume from
        # the ship's actual motion with no velocity snap).
        self._ai_owned = False
        # Scroll-wheel throttle nudges arrive outside apply() (see
        # _route_scroll_wheel); latch them so a nudge while an AI owns the
        # ship counts as manual input and cancels the AI next apply().
        self._manual_throttle_nudge = False

    def nudge_throttle(self, notches: int) -> None:
        """Step the discrete impulse throttle one notch per detent.

        Level set: REVERSE_LEVEL (-2), 0 (stop), 1..9 (impulse). There is
        no -1: down from 0 jumps to reverse, up from reverse returns to 0.
        Forward caps at 9; reverse floors at REVERSE_LEVEL.
        """
        for _ in range(abs(int(notches))):
            if notches > 0:
                if self.impulse_level < 0:
                    self.impulse_level = 0
                elif self.impulse_level < 9:
                    self.impulse_level += 1
            elif notches < 0:
                if self.impulse_level <= 0:
                    self.impulse_level = self.REVERSE_LEVEL
                else:
                    self.impulse_level -= 1
        if notches:
            self._manual_throttle_nudge = True

    # ── Hardpoint accessors ──────────────────────────────────────────────────

    @staticmethod
    def _get_ies(player):
        getter = getattr(player, "GetImpulseEngineSubsystem", None)
        return getter() if getter else None

    def GetTargetSpeed(self, player) -> float:
        """Convert impulse_level into the throttle-commanded target speed,
        scaled by the impulse engine power factor so the command and the
        _effective_motion cap agree.

        Throttle is a fraction of the *effective* (power-scaled) max speed:
        at 125 % power, full throttle targets 1.25 × authored MaxSpeed; at
        50 % power, full throttle targets 0.5 × authored MaxSpeed. The
        _cap_keep clamp in apply() still prevents over-driving, but now the
        command reaches the boosted cap instead of stopping at raw MaxSpeed.

        Forward speed is additionally multiplied by WARP_BOOST_FACTOR when
        the in-system warp toggle is on (Ctrl+I); reverse is unaffected.
        """
        ies = self._get_ies(player)
        raw_max = ies.GetMaxSpeed() if ies is not None else 0.0
        power_factor = ies.GetNormalPowerPercentage() if ies is not None else 1.0
        effective_max = raw_max * power_factor
        boost = self.WARP_BOOST_FACTOR if self._warp_boost else 1.0
        if raw_max > 0.0:
            if self.impulse_level >= 0:
                return (self.impulse_level / 9.0) * effective_max * boost
            return -self.REVERSE_FRACTION * effective_max
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

    # ── Helm-AI ownership handoff ────────────────────────────────────────────
    #
    # When a helm AI is installed on the player (MissionLib.SetPlayerAI —
    # Orbit Planet, All Stop/Stay, Intercept...), the AI's setpoints +
    # engine/appc/ship_motion._step_ship_motion own BOTH translation and
    # rotation; apply() must not run its ship-motion path or it clobbers the
    # integrator (unconditional SetVelocity at the bottom of apply() zeroes
    # the AI-set velocity; _apply_body_rotation fights the AI's angular
    # setpoints). The rate mapping between the two integrators: ship
    # ._current_angular_velocity applies (x, z, y) about (X, Z, Y) with no
    # negation (_integrate_rotation), while _apply_body_rotation negates yaw
    # and roll — so pitch ≡ cav.x, yaw ≡ −cav.z, roll ≡ −cav.y.

    def _detect_manual_flight_input(self, h) -> bool:
        """True when the player is actively flying this tick: a throttle edge
        (reverse / full stop / digit, honoring the same modifier guards as
        the normal throttle path) or any held rotation key. Used only while
        an AI owns the ship — BC semantics: a manual helm input overrides
        the current order."""
        im = self._input_map
        keys = getattr(h, "keys", None)
        _super_held = (
            h.key_state(keys.KEY_LEFT_SUPER)
            if keys is not None and hasattr(keys, "KEY_LEFT_SUPER") else False
        )
        _ctrl_held = (
            h.key_state(keys.KEY_LEFT_CONTROL)
            if keys is not None and hasattr(keys, "KEY_LEFT_CONTROL") else False
        )
        if h.key_pressed(im.code("reverse")) and not (_super_held or _ctrl_held):
            return True
        if h.key_pressed(im.code("full_stop")):
            return True
        if keys is not None and not _shift_held(h):
            digit_codes = (
                keys.KEY_1, keys.KEY_2, keys.KEY_3, keys.KEY_4, keys.KEY_5,
                keys.KEY_6, keys.KEY_7, keys.KEY_8, keys.KEY_9,
            )
            for code in digit_codes:
                if h.key_pressed(code):
                    return True
        for action in ("pitch_down", "pitch_up", "yaw_left", "yaw_right",
                       "roll_left", "roll_right"):
            if h.key_state(im.code(action)):
                return True
        return False

    def _sync_ship_integrator_from_control(self, player) -> None:
        """Manual → AI handoff: seed the ship-side integrator state
        (ship._current_speed / ._current_angular_velocity) from the
        player-control state so the AI ramp starts from the ship's actual
        motion instead of a stale value from a previous AI period."""
        player._current_speed = self._current_speed
        cav = getattr(player, "_current_angular_velocity", None)
        if cav is not None:
            cav.x = self._current_pitch_rate
            cav.z = -self._current_yaw_rate
            cav.y = -self._current_roll_rate

    def _sync_control_from_ship(self, player) -> None:
        """AI → manual handoff: resume player control from the ship's actual
        motion so there is no velocity/rotation snap. Speed is the published
        velocity projected onto ship-forward (manual flight is always along
        facing); angular rates map through the yaw/roll negation (see the
        section comment above). The AI's setpoints are cleared so
        _step_ship_motion disengages and stops double-driving the ship."""
        fwd = player.GetWorldRotation().GetCol(1)
        v = player.GetVelocity()
        self._current_speed = v.x * fwd.x + v.y * fwd.y + v.z * fwd.z
        cav = getattr(player, "_current_angular_velocity", None)
        if cav is not None:
            self._current_pitch_rate = cav.x
            self._current_yaw_rate   = -cav.z
            self._current_roll_rate  = -cav.y
        player._speed_setpoint = None
        player._target_angular_velocity_setpoint = None
        # Taking the conn also aborts any AI-initiated in-system-warp
        # transit (BC: touching the helm cancels the autopilot's warp).
        player._insystem_warp_transit = None

    def _cancel_player_ai(self, player) -> None:
        """Clear the player's helm AI (BC: manual input overrides the current
        order). Mirrors the SDK cancel path — MissionLib.SetPlayerAI(ctrl,
        None) → pPlayer.ClearAI() + g_sPlayerShipController update — without
        importing MissionLib from the engine: clear the AI directly and
        best-effort sync the SDK-visible controller global when the module
        is already loaded (TacticalInterfaceHandlers / BridgeHandlers gate
        manual-fire paths on it being None/'Captain')."""
        player.ClearAI()
        ml = sys.modules.get("MissionLib")
        if ml is not None and hasattr(ml, "g_sPlayerShipController"):
            try:
                ml.g_sPlayerShipController = None
            except Exception as _e:
                dev_mode.log_swallowed("sync g_sPlayerShipController", _e)

    # ── Per-tick step ────────────────────────────────────────────────────────

    def apply(self, player, dt: float, h) -> None:
        """Read keys, update player transform.

        `h` is the _dauntless_host bindings module (or any object with
        key_state, key_pressed, and `keys.KEY_*` attributes).
        """
        # Warp override: while warping the WarpVFX manager owns the ship (the
        # turn is applied by _warp_apply_turn). Burst forward at the override
        # speed (or hold at 0 during align) along the current warp-aligned
        # heading, ignoring throttle/input so the ship can't be steered mid-warp
        # and there's a single motion path (no double-translate).
        if self._warp_speed_override is not None:
            s = float(self._warp_speed_override)
            self._current_speed = s
            if s != 0.0:
                fwd = player.GetWorldRotation().GetCol(1)
                p = player.GetTranslate()
                player.SetTranslateXYZ(p.x + fwd.x * s * dt,
                                       p.y + fwd.y * s * dt,
                                       p.z + fwd.z * s * dt)
                player.SetVelocity(TGPoint3(fwd.x * s, fwd.y * s, fwd.z * s))
            return
        # Helm-AI ownership arbitration (see section comment above apply()).
        nudged = self._manual_throttle_nudge
        self._manual_throttle_nudge = False
        ai = player.GetAI() if hasattr(player, "GetAI") else None
        if ai is not None:
            if nudged or self._detect_manual_flight_input(h):
                # BC: a manual helm input overrides the current order —
                # cancel the AI, resume from the ship's actual motion, and
                # fall through so this same tick's input registers.
                self._cancel_player_ai(player)
                self._sync_control_from_ship(player)
                self._ai_owned = False
            else:
                # AI owns ship motion — skip the entire ship-motion path
                # (the camera update lives in _apply_input and still runs).
                if not self._ai_owned:
                    self._ai_owned = True
                    self._sync_ship_integrator_from_control(player)
                return
        elif self._ai_owned:
            # AI released the conn (order finished / cleared) — resume
            # manual control from the ship's actual motion, no snap.
            self._sync_control_from_ship(player)
            self._ai_owned = False
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
        if h.key_pressed(self._input_map.code("reverse")) and not (_super_held or _ctrl_held):
            self.impulse_level = self.REVERSE_LEVEL
        elif h.key_pressed(self._input_map.code("full_stop")):
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
        im = self._input_map
        if h.key_state(im.code("pitch_down")): pitch_target -= ang_rate
        if h.key_state(im.code("pitch_up")):   pitch_target += ang_rate
        if h.key_state(im.code("yaw_left")):   yaw_target   -= ang_rate
        if h.key_state(im.code("yaw_right")):  yaw_target   += ang_rate
        if h.key_state(im.code("roll_left")):  roll_target  += ang_rate
        if h.key_state(im.code("roll_right")): roll_target  -= ang_rate
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
    """Bridge/exterior view modality — a stateless facade over the SDK
    TopWindow flags (engine/appc/top_window.py), which are the single
    source of truth (pull model; spec
    docs/superpowers/specs/2026-07-05-mission-view-camera-input-locks-design.md §1).

    SPACE dispatches ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL through
    TopWindow's instance-handler chain so missions can swallow the toggle
    (E1M1/E1M2 TacticalToggleHandler); the bottom-of-chain default
    performs the flag flip synchronously during dispatch. SDK calls like
    ForceBridgeVisible are plain flag writes the next frame's read picks
    up — no listeners, nothing to re-wire on mission swap.
    """

    @property
    def is_bridge(self) -> bool:
        from engine.appc.top_window import bridge_flag
        return bridge_flag()

    @property
    def is_exterior(self) -> bool:
        return not self.is_bridge

    def toggle(self) -> None:
        from engine.appc.top_window import TopWindow_GetTopWindow
        TopWindow_GetTopWindow().ToggleBridgeAndTactical()

    def set_bridge(self) -> None:
        """Force bridge view (used to start a bridge cutscene)."""
        from engine.appc.top_window import TopWindow_GetTopWindow
        TopWindow_GetTopWindow().ForceBridgeVisible()

    def apply(self, h) -> None:
        """Poll space-pressed; on edge, route through the SDK chain.

        The bridge/tactical toggle is suppressed during a cutscene:

        * MissionLib cutscene mode (StartCutscene .. EndCutscene). BC blocks
          the view toggle while a cutscene plays and re-enables it at
          EndCutscene — E1M1's "Captain, the bridge is yours" beat. This is
          independent of RemoveControl/AllowKeyboardInput, which gates *ship*
          control (helm, fire) and is NOT returned at that beat, yet the view
          toggle works there.
        * A bridge-cutscene camera path is queued or playing. Such a path
          forces the view to bridge every frame (_compute_camera's set_bridge),
          so a toggle would flip to exterior for a single frame before being
          reverted — a visible flash. Suppress the toggle outright instead.
        """
        if h.key_pressed(h.keys.KEY_SPACE):
            from engine.appc.top_window import (
                TopWindow_GetTopWindow,
                dispatch_toggle_bridge_and_tactical,
            )
            if TopWindow_GetTopWindow().IsCutsceneMode():
                return
            from engine.bridge_cutscene import get_controller
            ctrl = get_controller()
            if ctrl is not None and ctrl.has_pending_camera():
                return
            dispatch_toggle_bridge_and_tactical()


def _tactical_hud_visible(*, is_exterior: bool, spv_open: bool,
                          cutscene_active: bool) -> bool:
    """Whether the tactical HUD (ship displays, sensors, target list,
    weapons) should show this frame. It is an exterior-view element, hidden
    while the Ship Property Viewer owns the frame, and hidden during a
    cutscene so the letterbox frame stays cinematic (BC hides the tactical
    UI during StartCutscene..EndCutscene)."""
    return is_exterior and not spv_open and not cutscene_active


def _bridge_freelook_suppressed(*, crew_menu_open: bool,
                                cutscene_active: bool,
                                bridge_cutscene_pending: bool = False) -> bool:
    """Whether the bridge camera's mouse free-look is suppressed this frame.
    Suppressed while a crew menu is open (the cursor is freed to click it),
    during a cutscene (the letterbox pins the view — no free-look), and while a
    bridge cutscene camera is pending/active (the walk-on hand-off gap where the
    mission owns the view before StartCutscene sets cutscene_active; this is the
    yaw-drift window that froze the E1M1 view on the empty XO chair).

    NOT suppressed merely because the mission removed *ship* control
    (MissionLib.RemoveControl -> AllowKeyboardInput(0)/AllowMouseInput(0)): BC's
    RemoveControl disables helm/tactical control, not bridge interaction. E1M1's
    character-selection tutorial runs with ship control removed for the whole
    beat, yet the player MUST look around to aim at and select officers. Gating
    free-look on IsMouseInputAllowed() (the earlier walk-on-gap fix, 6d5f38db)
    broke that — the entire bridge locked up post-undock. The gap is covered
    instead by bridge_cutscene_pending, which is False during char-selection."""
    return crew_menu_open or cutscene_active or bridge_cutscene_pending


def _pump_walk_controller(walk_ctrl, renderer, dt, *, paused: bool) -> None:
    """Advance the CharacterAction AT_MOVE walk lifecycle for one frame.

    Runs every UNPAUSED frame regardless of view mode. This is deliberately NOT
    gated on ``view_mode.is_bridge`` like the purely-visual bridge-character
    pumps (idle gestures, gesture/turn anim, lip-sync, node anim): a walk's
    SETTLE fires the CharacterAction's Completed(), which advances the mission
    TGSequence. E1M1's UndockCutscene chains Picard's ``AT_MOVE "P"``
    (walk-to-chair) -> Inspection (enables the crew menus) -> collision re-enable
    right AFTER an exterior drydock cutscene, so the active view is not the
    bridge when the AT_MOVE fires. Gating this pump on bridge view left that
    walk unpumped -> never settled -> Completed() never fired -> the sequence
    jammed before Inspection (crew menus never enabled, control never restored:
    freelook + F1-F5 dead). The intro walk-on runs in bridge view, so it never
    hit this. Keep this view-independent. Idle when no move is pending/active
    (walk_ctrl.update early-returns), so the always-on pump is free."""
    if paused:
        return
    walk_ctrl.update(dt, renderer=renderer)


def _pump_bridge_doors(cutscene, renderer, *, paused: bool) -> None:
    """Drain queued lift-door TGAnimActions every unpaused frame, regardless
    of view mode.

    cutscene.update() (the CAMERA half of the per-tick bridge pump) only runs
    inside ``if view_mode.is_bridge:`` -- appropriate for the camera, which
    has nothing to drive outside that view. But LiftDoorAction's own
    TGSoundAction plays view-independently the instant its builder sequence
    fires (see PicardAnimations.MoveFromL1ToP1's 0.125s-delayed door step),
    so an AT_MOVE fired from EXTERIOR view (the same E1M1 UndockCutscene beat
    documented on _pump_walk_controller) played the door SOUND on time but
    left the door draw queued until the player next entered bridge view --
    where it swung open with nobody there. Keep this view-independent; the
    camera half of cutscene.update() stays view-gated where it already is."""
    if paused:
        return
    import App as _App
    cutscene._update_doors(renderer, _App.g_kAnimationManager)


def _devtools_frozen(h) -> bool:
    """True while the CEF DevTools window (F12) is open.

    Editing the overlay's DOM/CSS in DevTools is useless if the world keeps
    running underneath — the UI state you are inspecting scrolls away and
    per-frame panel pushes overwrite your edits. So DevTools freezes the sim
    exactly like the pause menu, minus the menu itself (see
    _PauseMenuController.sim_frozen).

    Reads the live window state, not an F12 latch, so closing DevTools via its
    own close button also unfreezes. The AttributeError fallback is for fake
    hosts in tests: the real binary can't be missing this binding —
    renderer._REQUIRED_BINDINGS hard-fails at boot if it is.
    """
    if h is None:
        return False
    try:
        return bool(h.cef_devtools_open())
    except AttributeError:
        return False


class _PauseMenuController:
    """ESC-toggled pause-menu overlay.

    Edge-triggered on KEY_ESCAPE. Owns the single boolean that the host
    loop reads to decide whether to advance the simulation this tick —
    see the tick body in host_loop.run(). When open, the world keeps
    rendering (frozen) and the CEF overlay paints a placeholder; AI,
    physics, weapons, combat, ship/camera input, and audio tick all
    skip.

    Two distinct questions, deliberately separate properties:
      is_open    — is the MENU up? Drives menu visibility, cursor unlock,
                   pause-menu input routing, mouse forwarding to CEF.
      sim_frozen — must the WORLD hold still? is_open, OR an external freeze
                   (today: the DevTools window). The host loop gates the
                   simulation on this one, so DevTools can stop the world
                   without raising a menu over the UI being inspected.
    """

    def __init__(self):
        self._open = False
        self._quit_requested = False
        self._external_freeze = False

    @property
    def is_open(self) -> bool: return self._open

    @property
    def sim_frozen(self) -> bool:
        return self._open or self._external_freeze

    def set_external_freeze(self, frozen: bool) -> None:
        """Freeze the sim without opening the menu. Host loop calls this once
        per frame from _devtools_frozen()."""
        self._external_freeze = bool(frozen)

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
    """Mirror the view-mode flag into renderer-side state (cursor lock,
    engine-rumble mute, bridge ambient). Idempotent — only fires when the mode
    has changed since the last call. The bridge render PASS is driven
    separately by _apply_bridge_pass_state (it also folds in the cutscene
    override). `h` is the bindings module (or fake) exposing set_cursor_locked.
    """
    target = view_mode.is_bridge
    last = getattr(view_mode, "_last_synced_is_bridge", None)
    if last == target:
        return
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


def _apply_bridge_pass_state(effective_bridge, h, latch_owner):
    """Drive bridge_pass_set_enabled from the EFFECTIVE bridge-render state
    (view_mode.is_bridge AND no in-space cutscene camera owns the frame).
    Idempotent/latched on latch_owner._last_synced_bridge_pass.

    Split out of _apply_view_mode_side_effects so the bridge render PASS can
    turn off for an in-space cutscene while cursor lock / engine-rumble mute /
    bridge ambient stay keyed on the raw bridge flag — the player is still on
    the bridge in state; only what they SEE changes."""
    if h is None:
        return
    last = getattr(latch_owner, "_last_synced_bridge_pass", None)
    if last == effective_bridge:
        return
    h.bridge_pass_set_enabled(effective_bridge)
    latch_owner._last_synced_bridge_pass = effective_bridge


class _NullPicker:
    """Stand-in used when dev_mode is disabled (no MissionPicker
    constructed). Always reports closed so the pause-menu side-effects
    predicate degrades to its original behaviour."""
    def is_open(self) -> bool:
        return False


_NULL_PICKER = _NullPicker()


def _register_ai_inspector(registry):
    """Register the dev-only AI Inspector panel + its pause-menu row.

    Mirrors the inline DeveloperOptionsPanel / ShipPropertyViewerPanel
    registration: the panel is only constructed under the developer flag, so
    production never builds it and the render path stays byte-identical. When
    dev mode is off this is a no-op that returns the shared _NULL_PICKER stub
    (is_open() -> False) so the modal-blocker list degrades cleanly.

    Returns the panel (real AIInspectorPanel under --developer, else
    _NULL_PICKER) so the caller can add it to _modal_blockers for ESC routing.
    """
    if not dev_mode.is_enabled():
        return _NULL_PICKER
    from engine.ui.ai_inspector_panel import AIInspectorPanel
    panel = AIInspectorPanel()
    registry.register(panel)
    dev_mode.register_dev_pause_menu_entry("AI Inspector…", panel.open)
    return panel


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
    _apply_view_mode_side_effects call re-applies cursor lock from
    whatever view mode is current. (The bridge render pass is driven
    separately by _apply_bridge_pass_state, which self-heals every frame,
    so it needs no latch invalidation here.)
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


def _apply_crew_menu_side_effects(crew_menu_panel, view_mode, pause, h,
                                  setting_course_panel=None,
                                  quick_battle_setup_panel=None) -> None:
    """Free the mouse cursor while a crew menu (F1-F5) is open on the
    bridge, then re-lock on close.

    On the bridge the cursor is held in mouse-look mode
    (set_cursor_locked(True)); a crew menu is a CEF overlay the player must
    click, so it needs a real cursor. Unlike the pause menu this does NOT
    freeze the simulation — stock BC keeps the world running under a crew
    menu — only the cursor lock (here) and the camera mouse-look (in the
    bridge render block) change.

    Idempotent and latched on crew_menu_panel._last_synced_cursor_free.
    Mirrors _apply_pause_menu_side_effects: on close it invalidates the
    view-mode latch so the next _apply_view_mode_side_effects call re-locks
    the cursor from the current view mode. Gated on `not pause.is_open` so
    the pause applier remains the sole cursor writer while paused (ESC
    closes an open crew menu before the pause menu can open, so the two
    don't normally coincide).
    """
    # The Set Course modal is a centred CEF overlay opened from the (bridge)
    # Helm crew menu; it needs a real cursor too. Clicking Set Course clears
    # the open crew menu, so has_open_menu() is False while the modal is up —
    # key the cursor-free state off the modal as well.
    # The Quick Battle Setup panel is the same kind of centred CEF modal and
    # also needs a real cursor while it is open.
    modal_open = (
        (setting_course_panel is not None and setting_course_panel.is_open())
        or (quick_battle_setup_panel is not None
            and quick_battle_setup_panel.is_open())
    )
    target = (((view_mode.is_bridge and crew_menu_panel.has_open_menu())
               or modal_open)
              and not pause.is_open)
    last = getattr(crew_menu_panel, "_last_synced_cursor_free", None)
    if last == target:
        return
    if target:
        h.set_cursor_locked(False)
    else:
        # Re-lock on close by letting the view-mode applier re-sync.
        view_mode._last_synced_is_bridge = None
    crew_menu_panel._last_synced_cursor_free = target


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


def _handle_controls_capture(panel, h) -> None:
    """Owns the keyboard while the Controls tab is capturing a key.

    Scans the bindable GLFW codes and forwards the first press as
    configuration/bind:<action>:<KEY>; Esc sends capture_cancel.  The panel's
    handle_input early-returns during capture, and the caller skips the modal
    ESC/close dispatch, so this is the sole consumer of the press.
    """
    action_id = getattr(panel, "capturing_action", None)
    if action_id is None or h is None:
        return
    keys = getattr(h, "keys", None)
    esc = getattr(keys, "KEY_ESCAPE", None) if keys is not None else None
    if esc is not None and h.key_pressed(esc):
        panel.dispatch_event("capture_cancel")
        return
    from engine.input_map import GLFW_KEYS
    for name, code in GLFW_KEYS.items():
        try:
            if h.key_pressed(code):
                panel.dispatch_event("bind:%s:%s" % (action_id, name))
                return
        except Exception:
            continue


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
    FOV_Y_RAD         = _math.radians(45.0)   # tuned to the original bridge feel
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
        """Captain's-chair eye for the current horizontal facing. Base is the
        SDK GalaxyBridgeCaptain mode's BasePosition (= GetBaseCameraPosition,
        z=50), harvested at mission load into _BRIDGE_CAMERA_EYE.

        Applies the SDK PlaceByDirection Movement as a gradual lift as the view
        turns away from forward: eye = base + Movement * frac, where frac
        smoothsteps over [StartMoveAngle, EndMoveAngle] by the horizontal angle
        of the look direction off bridge-forward (-Y), scaled by the feel knob
        _BRIDGE_CAMERA_MOVE_SCALE. Facing the viewscreen (angle 0) → no lift;
        turning toward the rear eases the eye up (+Z) and forward (-Y). Matches
        the original's gradual rise on turn. None movement → static base."""
        base = _BRIDGE_CAMERA_EYE
        move = _BRIDGE_CAMERA_MOVE
        if move is None:
            return base
        (mx, my, mz), start, end = move
        # Horizontal angle from forward: forward (toward viewscreen) is
        # bridge-local -Y; our forward at yaw is (-sin yaw, cos yaw, 0), so the
        # deviation from facing-forward is |wrap_to_pi(yaw - pi)| in [0, pi]
        # (= 0 at yaw=pi facing the viewscreen, = pi at yaw=0 facing the rear).
        horiz = abs(self.yaw_rad % (2.0 * _math.pi) - _math.pi)
        if horiz <= start:
            band = 0.0
        elif end > start and horiz >= end:
            band = 1.0
        elif end > start:
            band = 0.5 - 0.5 * _math.cos(_math.pi * (horiz - start) / (end - start))
        else:
            band = 1.0 if horiz > start else 0.0
        frac = band * _BRIDGE_CAMERA_MOVE_SCALE
        return (base[0] + mx * frac, base[1] + my * frac, base[2] + mz * frac)

    @staticmethod
    def _smoothstep(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    def set_zoom_target(self, world_xyz, dt: float, snap: bool = False) -> None:
        """Select (world_xyz != None) or deselect (None) an officer to zoom
        onto; advance the ease by dt at rate 1/zoom_time, clamped to [0, 1].
        snap=True jumps straight to fully-framed (AT_LOOK_AT_ME_NOW).
        Mouse-look is suspended whenever a zoom is in progress (see apply)."""
        self._zoom_active = world_xyz is not None
        if world_xyz is not None:
            self._zoom_target_world = world_xyz
            if snap:
                self._zoom_t = 1.0        # AT_LOOK_AT_ME_NOW: jump, don't ease
                return
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
        the SDK eye (which lifts gradually as the view turns off-forward, see
        _eye_offset) + base FOV. When an officer is selected the look direction
        eases toward that officer's world position and the FOV narrows toward
        FOV_Y_RAD * min_zoom, both over the SDK zoom time."""
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
                    # Re-derive a roll-free up for the eased forward. Easing only
                    # the forward leaves local_up frozen at its pre-zoom (yawed/
                    # pitched) orientation, so it no longer lies in the new
                    # forward's vertical plane and the camera rolls. Rebuilding up
                    # from forward against bridge-up (+Z) keeps the horizon level
                    # throughout the zoom and at the station, matching free-look.
                    zr = (
                        local_fwd[1]*1.0 - local_fwd[2]*0.0,
                        local_fwd[2]*0.0 - local_fwd[0]*1.0,
                        local_fwd[0]*0.0 - local_fwd[1]*0.0,
                    )
                    zrl = _math.sqrt(zr[0]**2 + zr[1]**2 + zr[2]**2)
                    if zrl > 1e-6:
                        zr = (zr[0]/zrl, zr[1]/zrl, zr[2]/zrl)
                        local_up = (
                            zr[1]*local_fwd[2] - zr[2]*local_fwd[1],
                            zr[2]*local_fwd[0] - zr[0]*local_fwd[2],
                            zr[0]*local_fwd[1] - zr[1]*local_fwd[0],
                        )
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


def _resolve_bridge_focus_world(watch_ctrl, crew_menu_panel, r):
    """The world point the captain's-eye camera should frame this bridge frame,
    or None (free-look). Precedence: an AT_WATCH_ME / AT_LOOK_AT_ME target (the
    watched character's head-centre) over the crew-menu zoom-to-officer. A baked
    cutscene camera path is handled separately (set_anim_pose) and outranks both."""
    if watch_ctrl is not None:
        w = watch_ctrl.resolve_target_world(r)
        if w is not None:
            return w
    return _active_zoom_officer_world(crew_menu_panel, r)


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
    # Deferred-completion timers just died with the managers above; drop the
    # matching skip-candidate registry so Backspace can't "skip" stale actions
    # from the prior mission.
    from engine.appc import actions as _appc_actions
    _appc_actions.reset_deferred_playing()
    # Drop the object→render-instance mirror; the instances themselves are
    # torn down with the set, and the next mission's realize loops repopulate.
    render_instances.reset()
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
    # Clear MissionLib's "viewscreen in use" flag. If a mission is swapped
    # away mid-briefing (while its bridge viewscreen shows a comm character),
    # g_bViewscreenOn is left at 1. On the next mission's load, the briefing's
    # ViewscreenOn() then sees the viewscreen as already in use and enters a
    # 2-second retry loop that never completes — the comm character (e.g. Liu
    # in E1M1) never speaks or renders. ResetViewscreen() clears the flag
    # (first thing it does) and re-enables the Hail/Contact menus; call it
    # before _sets.clear() so its CallWaiting() still sees the live bridge.
    # Best-effort, matching the surrounding reset discipline.
    try:
        import MissionLib
        MissionLib.ResetViewscreen()
        # Drop any master action sequence carried over from the previous
        # mission. QueueActionToPlay stores the master's id in
        # g_idMasterSequenceObj and appends every subsequent queued action onto
        # it; a stalled/leftover master from the prior mission would otherwise
        # swallow the next mission's queued cutscene/comm sequences. Completed
        # masters already invalidate their id (TGSequence.Completed), so this is
        # a belt-and-suspenders reset for a master left mid-play at swap time.
        MissionLib.g_idMasterSequenceObj = App.NULL_ID
    except Exception as _e:
        dev_mode.log_swallowed("MissionLib.ResetViewscreen on swap", _e)
    # Re-apply the identifier-centric ShowPointerArrow/HidePointerArrows
    # override (engine/ui/ui_attention.py). MissionLib the module is never
    # reloaded/re-imported by a mission swap — it stays cached in
    # sys.modules and its globals persist (see the "MissionLib globals leak
    # across swaps" gotcha) — so this call is a no-op after the first, but it
    # lives right here, alongside the other MissionLib re-touches this
    # function already makes per load, so a future change to how MissionLib
    # is (re)acquired can't silently drop the override.
    try:
        from engine.ui import ui_attention
        ui_attention.install()
    except Exception as _e:
        dev_mode.log_swallowed("ui_attention.install on swap", _e)
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
        _fresh_tcw = _TCW.GetInstance()
        App.g_kKeyboardBinding.SetDefaultDestination(_fresh_tcw)
        # Re-register the tactical input handlers (fire / targeting / camera /
        # turn) on the fresh TCW. BC's native engine wires these when it
        # creates the tactical window; we recreate the window singleton on
        # every mission (re)load just above, so the handlers must be re-applied
        # here or every TCW-routed keyboard control silently dies after the
        # load — most visibly weapon fire (ET_INPUT_FIRE_PRIMARY -> FireWeapons).
        # That is exactly why firing worked in the boot QuickBattle but not in
        # any mission swapped in afterward; the direct host-loop pollers (ship
        # turn, camera, Shift+alert) kept working, which masked the gap. This is
        # now the SOLE registrar — _bootstrap_firing_pipeline no longer calls
        # Initialize — so handlers register exactly once per TCW (no double
        # dispatch).
        try:
            import TacticalInterfaceHandlers
            TacticalInterfaceHandlers.Initialize(_fresh_tcw)
        except Exception as _e_tih:
            dev_mode.log_swallowed(
                "TacticalInterfaceHandlers.Initialize after TCW reset", _e_tih)
        # ORDERING IS LOAD-BEARING: TacticalInterfaceHandlers.Initialize (just
        # above) registers the SDK's own BridgeHandlers.TalkTo* handlers on this
        # same TCW for the same ET_INPUT_TALK_TO_* events that
        # crew_menu_hotkeys.rewire() (just below) also registers _on_talk_to
        # for. Event dispatch is LIFO, so rewire() running SECOND puts our
        # handler on top, and _on_talk_to does not call CallNextHandler — that
        # is what stops the chain before the SDK handler runs. Swap this
        # ordering (or make _on_talk_to forward) and F1-F5 fire TWO MenuUp()s
        # per press: ours, then the SDK's bridge-character-menu path, doubling
        # the "Yes sir" acknowledgement.
        from engine.ui import crew_menu_hotkeys
        crew_menu_hotkeys.rewire()
    except Exception as _e:
        dev_mode.log_swallowed("crew_menu_hotkeys.rewire after TCW reset", _e)
    # Clear the nebula tracker so stale membership state from the prior set
    # (or mission) doesn't suppress enter-events in the next mission.
    if _nebula_tracker is not None:
        _nebula_tracker.reset()
    if _nebula_thunder is not None:
        _nebula_thunder.reset()
    if _hull_discharge is not None:
        _hull_discharge.reset()
    if _nebula_wake is not None:
        _nebula_wake.reset()
    # Clear concealment lock-break latches so a new mission's ships don't
    # inherit stale id()-keyed latches from the prior mission.
    from engine.appc.sensor_detection import reset_concealment_state
    reset_concealment_state()
    # Force the next tick to re-run sensor identification for the new mission.
    global _last_identify_gt
    _last_identify_gt = None


def _episode_tgl_path(mission_module_name: str) -> Optional[str]:
    """Derive the episode-level TGL path from a mission module name, matching the
    string the episode's own SetDatabase uses. e.g.
    ``Maelstrom.Episode1.E1M2.E1M2`` -> ``data/TGL/Maelstrom/Episode 1/Episode1.tgl``
    (package ``Episode1`` -> display ``Episode 1``, keeping the file name
    ``Episode1.tgl``). Returns None for module names too short to carry a
    family+episode."""
    import re
    parts = mission_module_name.split(".")
    if len(parts) < 3:
        return None
    family, episode_pkg = parts[0], parts[1]
    display = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", episode_pkg)   # Episode1 -> Episode 1
    return "data/TGL/%s/%s/%s.tgl" % (family, display, episode_pkg)


def _campaign_tgl_path(mission_module_name: str) -> Optional[str]:
    """Derive the campaign-level TGL path from a mission module name, matching
    the string the campaign's own SetDatabase uses (Maelstrom.py:40 does
    ``pGame.SetDatabase("data/TGL/Maelstrom/Maelstrom.tgl")``). e.g.
    ``Maelstrom.Episode1.E1M2.E1M2`` -> ``data/TGL/Maelstrom/Maelstrom.tgl``.
    This DB holds cross-episode object display names (Haven, Facility, Moon).
    Returns None for module names too short to carry a family."""
    parts = mission_module_name.split(".")
    if len(parts) < 2:
        return None
    family = parts[0]
    return "data/TGL/%s/%s.tgl" % (family, family)


def _init_campaign_context(game, mission_module_name: str) -> None:
    """Set the campaign-level (game) TGL so object display names resolve.

    BC boots the campaign via Game.LoadEpisode, whose campaign module Initialize
    calls ``pGame.SetDatabase(<campaign tgl>)``. The dev picker skips that
    cascade, so the game DB is never set and object display names (Haven ->
    "Vesuvi 6 - Haven", Facility -> "Haven Facility") fall back to raw names.
    Mirrors _init_episode_context: derive + load the DB only, no campaign
    Initialize side effects. Best-effort."""
    path = _campaign_tgl_path(mission_module_name)
    if path is None:
        return
    try:
        import App
        db = App.g_kLocalizationManager.Load(path)
        if db is not None:
            game.SetDatabase(db)
    except Exception as e:
        dev_mode.log_swallowed("campaign DB init", e)


def _init_episode_context(episode, mission_module_name: str) -> None:
    """Set the episode-level TGL so goals resolve to localized text.

    BC boots an episode via Game.LoadEpisode -> Episode.Initialize, which calls
    ``pEpisode.SetDatabase(<episode tgl>)`` before loading the default mission.
    The dev picker loads a specific mission directly and skips that cascade, so
    the episode DB is never set and goals fall back to raw string ids
    (``E1DestroyDebrisGoal`` instead of ``Clear Debris``). We restore just the DB
    by deriving its path (see _episode_tgl_path) and loading it — no episode
    Initialize, so none of its side effects (music, sound, event-handler,
    real-bridge-module imports) leak into the process. Best-effort: a missing or
    unreadable TGL leaves goals labelled by raw id and never blocks the load."""
    path = _episode_tgl_path(mission_module_name)
    if path is None:
        return
    try:
        import App
        db = App.g_kLocalizationManager.Load(path)
        if db is not None:
            episode.SetDatabase(db)
    except Exception as e:
        dev_mode.log_swallowed("episode DB init", e)


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

    # Establish episode-level context (esp. the episode TGL) BEFORE the mission's
    # Initialize, so goals registered during the opening cutscene resolve to
    # their localized text ("Clear Debris") rather than the raw string id
    # ("E1DestroyDebrisGoal"). The dev picker loads a mission directly, skipping
    # the episode cascade that BC's Game.LoadEpisode would run.
    _init_campaign_context(game, mission_module_name)
    _init_episode_context(episode, mission_module_name)

    mod = importlib.import_module(mission_module_name)
    if hasattr(mod, "PreLoadAssets"):
        mod.PreLoadAssets(mission)
    mod.Initialize(mission)

    # Register localized object display names now that the mission's objects
    # exist and the campaign/episode/mission TGLs are loaded — before the
    # per-tick sensor identification builds Hail buttons / target rows off
    # GetDisplayName().
    from engine.appc import display_names
    display_names.apply_display_names()

    start_evt = TGEvent()
    start_evt.SetEventType(App.ET_MISSION_START)
    start_evt.SetDestination(episode)
    App.g_kEventManager.AddEvent(start_evt)

    return mission, episode, game, mod


def _live_sets() -> list:
    """The set(s) whose astro bodies belong in the world scene: just the active
    space set (the one the player occupies) when determinable, else every set
    (legacy fallback). Mirrors iter_ships' active-set filtering so the player at
    Serris 3 doesn't see other systems' planets/suns bleed into the scene."""
    from engine.appc.ship_iter import active_set
    act = active_set()
    if act is not None:
        return [act]
    import App
    return list(App.g_kSetManager._sets.values())


def _iter_planets(*, verbose: bool = False) -> Iterable:
    """Walk every Planet (non-Sun) in the active set (see _live_sets)."""
    from engine.appc.planet import Planet, Sun
    for pSet in _live_sets():
        for obj in _iter_set_objects(pSet):
            if isinstance(obj, Planet) and not isinstance(obj, Sun):
                yield obj


def _iter_suns() -> Iterable:
    """Walk every Sun in the active set (see _live_sets)."""
    from engine.appc.planet import Sun
    for pSet in _live_sets():
        for obj in _iter_set_objects(pSet):
            if isinstance(obj, Sun):
                yield obj


def _aggregate_suns() -> list:
    """Collect sun render descriptors in BC native world units."""
    from engine.appc.planet import aggregate_suns_for_renderer
    return aggregate_suns_for_renderer(PROJECT_ROOT, _live_sets())


# ── Warp-VFX (Stage 2) host helpers: sun dim + cinematic ship turn ──────────

# Fraction of a sun's radius removed at peak streak (streak_intensity == 1.0).
# 0.7 -> suns shrink to 30% radius at the tunnel's brightest. Tunable.
_WARP_SUN_DIM = 0.7

# Warp ship-speed profile (see engine/warp_vfx.ship_speed for the envelope):
#   * cruise at impulse level _WARP_ALIGN_IMPULSE_LEVEL while aligning,
#   * ramp up to in-system warp (impulse max speed × _WARP_IN_SYSTEM_FACTOR) in
#     the last second before the burst flash,
#   * glide back to 0 over the 2s after arrival.
# Both speeds are derived per-ship from the impulse engine's max speed. Tunable.
_WARP_ALIGN_IMPULSE_LEVEL = 5.0   # of 9 throttle notches -> cruise while aligning
_WARP_IN_SYSTEM_FACTOR = 100.0    # × impulse max speed = in-system warp speed
_WARP_MAX_SPEED_FALLBACK = 6.3    # GU/s (Galaxy) when the IES can't be read


def _warp_phase_speeds(player):
    """(nominal_cruise, in_system_warp) GU/s for the warp speed profile, derived
    from the player's impulse-engine max speed. Fail-soft to the Galaxy default
    so the profile always has sane magnitudes."""
    ms = 0.0
    try:
        ies = player.GetImpulseEngineSubsystem()
        if ies is not None:
            ms = ies.GetMaxSpeed()
    except Exception:
        ms = 0.0
    if ms <= 0.0:
        ms = _WARP_MAX_SPEED_FALLBACK
    nominal = ms * (_WARP_ALIGN_IMPULSE_LEVEL / 9.0)
    return nominal, ms * _WARP_IN_SYSTEM_FACTOR

# Player rotation captured at align start; the slerp target is anchored to it so
# the turn is stable across frames (cleared when the warp ends).
_warp_turn_start_R = None

# True while the local scene is hidden for the warp tunnel (streak > 0). Tracked
# so visibility is restored on the frame the streak ends.
_warp_hidden = False

# Dev-mode warp diagnostics: per-warp peak flash/streak/turn, logged on warp end.
_warp_diag: dict = {}

# Nebula membership tracker — lazy-init on first sim tick so that importing
# this module does NOT trigger `import App` at module-load time (nebula_runtime
# has a top-level `import App`; importing it here would perturb sound-manager
# init order — same constraint as the other hoisted imports above).  The
# tracker is a pure-Python singleton: cheap to construct, stateless until the
# first tick that contains a nebula.
_nebula_tracker = None  # NebulaTracker | None
_nebula_thunder = None  # NebulaThunderDriver | None
# Game-time of the last sensor-identification sweep (throttle ~4 Hz). None
# until the first sweep; reset on mission swap so a new mission re-identifies.
_last_identify_gt = None  # float | None
_hull_discharge = None  # HullDischargeDriver | None
_nebula_wake = None     # NebulaWakeTracker | None


def _dim_suns(suns, streak):
    """Shrink sun radius/corona_radius by (1 - DIM*streak) for the warp dim.

    The sun render descriptor (engine/appc/planet.aggregate_suns_for_renderer)
    carries no brightness field; sun_pass scales apparent brightness with the
    on-screen radius, so radius is the only available dim lever. Returns new
    dicts (never mutates the aggregated descriptors)."""
    scale = 1.0 - _WARP_SUN_DIM * float(streak)
    if scale < 0.0:
        scale = 0.0
    out = []
    for s in suns:
        d = dict(s)
        if "radius" in d:
            d["radius"] = d["radius"] * scale
        if "corona_radius" in d:
            d["corona_radius"] = d["corona_radius"] * scale
        out.append(d)
    return out


def _warp_apply_turn(player, frac, heading):
    """Slerp the player's rotation toward the warp heading by `frac` (0..1).

    Builds the target rotation by keeping the captured UP (col 2) and setting
    forward (col 1) = heading, deriving right (col 0) = forward x up — the
    right-handed AlignToVectors construction (CLAUDE.md), replicated here on a
    bare TGMatrix3 because AlignToVectors is an ObjectClass method, not a
    matrix method. nlerp_rotation blends col-by-col then re-orthonormalizes."""
    global _warp_turn_start_R
    from engine.appc.math import TGPoint3, TGMatrix3
    from engine.core.interpolate import nlerp_rotation

    R0 = player.GetWorldRotation()
    if _warp_turn_start_R is None:
        _warp_turn_start_R = R0
    start_R = _warp_turn_start_R

    up = start_R.GetCol(2)
    fwd = TGPoint3(heading[0], heading[1], heading[2])
    fwd.Unitize()
    # Orthogonalize up against forward, then right = forward x up (det = +1).
    dot = fwd.Dot(up)
    u = TGPoint3(up.x - dot * fwd.x, up.y - dot * fwd.y, up.z - dot * fwd.z)
    u.Unitize()
    right = fwd.Cross(u)
    right.Unitize()
    target = TGMatrix3()
    target.SetCol(0, right)
    target.SetCol(1, fwd)
    target.SetCol(2, u)

    player.SetMatrixRotation(nlerp_rotation(start_R, target, frac))


def _warp_clear_turn():
    global _warp_turn_start_R
    _warp_turn_start_R = None


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


def _aggregate_nebulae(pSet):
    """Render descriptors for MetaNebula volumes in pSet (world-space GU).

    Returns [] for sets without a nebula (renderer early-outs → stock BC).
    """
    import App
    if pSet is None:
        return []
    out = []
    for obj in pSet.GetClassObjectList(App.CT_NEBULA):
        neb = App.MetaNebula_Cast(obj)
        if neb is None:
            continue
        spheres = [tuple(s) for s in neb.GetNebulaSpheres()]
        if not spheres:
            continue
        out.append({
            "spheres": spheres,
            "rgb": neb.GetTintRGB(),
            "visibility": neb.GetVisibility(),
            "external_tex": neb.GetExternalTexture(),
            "internal_tex": neb.GetInternalTexture(),
            "fbm": neb.GetFbmDials(),
            "seed": neb.GetSeed(),
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


def _ship_texture_replacements(ship):
    """BC ReplaceTexture swaps queued for `ship` (Federation registry / hull
    name), as `[(old_substring, new_abs_path), ...]`, or None when none are
    pending. Passed to renderer.load_model to bake a per-registry model variant.
    """
    from engine.appc import registry_texture
    reps = registry_texture.replacements_for(ship)
    return reps or None


def _ship_load_key(nif_path, reps):
    """Model-cache key for a ship load. Bare NIF path when no registry swap
    (byte-identical to the legacy key, so non-fed ships + planets are
    unaffected); NIF path + a stable registry suffix otherwise, so two hulls of
    the same class with DIFFERENT registries don't collapse onto one handle."""
    if not reps:
        return nif_path
    return nif_path + "|" + ";".join(f"{old}={new}" for old, new in reps)


def _resolve_active_set(player):
    """Return the SetClass whose lights & backdrops apply to the rendered
    scene. Order:
      1. g_kSetManager.get_explicit_rendered_set() — set explicitly via
         MissionLib.MakeRenderedSet during scene transitions.
      2. The set containing the player ship — Phase 1 fallback.
      3. None — caller falls through to per-system defaults
         (lighting only; backdrops simply absent).

    Considers both _lights and _backdrops when deciding whether a set
    is 'live' so backdrop-only sets (rare but legal) are picked up.
    """
    import App
    rendered = App.g_kSetManager.get_explicit_rendered_set()
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


def _authored_backdrops(pSet):
    """Stock-BC backdrops: this set's authored BackdropSphere objects."""
    from engine.appc.backdrops import aggregate_for_renderer
    return aggregate_for_renderer(pSet, PROJECT_ROOT)


def _aggregate_backdrops(pSet):
    """Backdrop descriptors for the active set.

    Procedural toggle ON  -> map-driven sky (the sector model projected from
    this system's vantage), falling back to authored backdrops if the system
    is unmapped. Toggle OFF -> stock BC (authored backdrops).
    """
    name = pSet.GetName() if pSet is not None else None
    if r.procedural_sky_enabled():
        from engine.appc import sky_projection as sp
        model = sp.load_sector_model()
        vantage = sp.vantage_for_set(pSet, model)
        if vantage is not None:
            return sp.project_sky(vantage, model)
    return _authored_backdrops(pSet)


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


def _model_sphere_radius_from_aabb(center: tuple, half_extents: tuple) -> float:
    """Bounding-sphere radius of a NIF whose geometry is an origin-centred
    sphere — the largest single-axis half-extent, which equals that sphere's
    radius (and the NIF's authored bound_radius).

    This is the correct divisor for planet/moon render scaling: BC computes
    render_scale = GetRadius() / NIF_bound_radius, so the model draws at
    exactly GetRadius() game units. `_model_extent_from_aabb` returns the AABB
    *corner* distance instead (|half| = R·√3 for a sphere), which is ~1.73×
    too large and shrinks the planet to GetRadius()/√3. See
    docs/instrumented_experiments/2026-07-07-planet-render-scale.md.

    All stock planet/moon NIFs are origin-centred spheres, so max-half-extent
    is exact here; it is not a general model radius."""
    hx, hy, hz = half_extents
    return max(abs(hx), abs(hy), abs(hz))


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


def _rim_strength_for(ship) -> float:
    """Fresnel rim intensity for a ship instance: the hardpoint stats'
    'SpecularCoef' when authored (captured by ShipClass.SetSpecularKs via
    loadspacehelper), else DEFAULT_RIM_STRENGTH."""
    from engine.renderer import DEFAULT_RIM_STRENGTH
    try:
        ks = ship.GetSpecularKs()
        if ks is not None:
            return float(ks)
    except Exception as _e:
        dev_mode.log_swallowed("rim GetSpecularKs probe", _e)
    return DEFAULT_RIM_STRENGTH


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


def _iter_ships_in_set(pSet) -> Iterable:
    """Walk every ShipClass object held by a single set."""
    from engine.appc.ships import ShipClass
    for obj in _iter_set_objects(pSet):
        if isinstance(obj, ShipClass):
            yield obj


def _iter_planets_in_set(pSet) -> Iterable:
    """Walk every Planet (non-Sun) object held by a single set."""
    from engine.appc.planet import Planet, Sun
    for obj in _iter_set_objects(pSet):
        if isinstance(obj, Planet) and not isinstance(obj, Sun):
            yield obj


def realize_set_objects(session, pSet, renderer, *, verbose: bool = False) -> None:
    """Build render instances for ONE set's ships/planets mid-mission.

    Mirrors the ship/planet instance-building loops in `_MissionLoader.load`,
    filtered to a single set and made idempotent: any object already present in
    `session.ship_instances` / `session.planet_instances` is skipped. That
    idempotency is how the warp spine reuses the player's instance (the player
    has been moved into the destination set before this runs) — its instance is
    neither rebuilt nor leaked.

    Texture-search lists and the two-layer scaling are taken directly from the
    loader; do not diverge or the realized instances stop matching load-time
    ones. Note `realize_set_objects` does not consult the controller-level
    nif_to_handle cache (it has no controller here); it loads per object, which
    is correct — the renderer dedupes identical NIFs internally.
    """
    r_ = renderer

    shared_search = [
        str(PROJECT_ROOT / "game" / DEFAULT_TEXTURE_SEARCH),
        str(PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedBases" / "High"),
    ]
    for ship in _iter_ships_in_set(pSet):
        if ship in session.ship_instances:
            continue
        nif_path = _ship_nif_path(ship, verbose=verbose)
        if nif_path is None:
            continue
        tex_search = [str(Path(nif_path).parent / "High"), *shared_search]
        reps = _ship_texture_replacements(ship)
        try:
            handle = r_.load_model(nif_path, tex_search, reps)
        except Exception as e:
            if verbose:
                print(f"[host_loop]   realize: skip ship: load_model({nif_path}) "
                      f"raised: {type(e).__name__}: {e}", flush=True)
            continue
        center, half_extents = r_.model_aabb(handle)
        extent = _model_extent_from_aabb(center, half_extents)
        if ship.GetRadius() <= 0.0:
            try:
                ship.SetRadius(extent * BC_MODEL_SCALE)
            except Exception as _e:
                dev_mode.log_swallowed("realize ship.SetRadius fallback", _e)
        iid = r_.create_instance(handle)
        r_.set_world_transform(iid, _ship_world_matrix(ship, BC_MODEL_SCALE))
        session.ship_instances[ship] = iid
        render_instances.register(ship, iid)
        # Fresnel rim applies to ship hulls only — planets share the opaque
        # shader and must stay rim-free (default ineligible).
        r_.set_rim_eligible(iid, True)
        r_.set_rim_strength(iid, _rim_strength_for(ship))

        # Subsystem glow dimming (best-effort VFX); never block spawn.
        try:
            from engine.appc.subsystem_glow import ShipGlowController
            session.ship_glow_controllers[iid] = ShipGlowController(r_, iid, ship)
        except Exception as _e:
            dev_mode.log_swallowed("realize ShipGlowController register", _e)

        # Shield render state. No-op for ships without a ShieldProperty.
        try:
            from engine.shields import register_ship_shield
            register_ship_shield(
                r_, instance_id=iid, ship=ship,
                aabb_center=center, aabb_half_extents=half_extents,
            )
        except Exception as e:
            if verbose:
                print(f"[host_loop]   realize: shield register skipped for ship: "
                      f"{type(e).__name__}: {e}", flush=True)

    planet_tex_search = str(PROJECT_ROOT / "game" / DEFAULT_PLANET_TEXTURE_SEARCH)
    for planet in _iter_planets_in_set(pSet):
        if planet in session.planet_instances:
            continue
        nif_path = _planet_nif_path(planet, verbose=verbose)
        if nif_path is None:
            continue
        try:
            handle = r_.load_model(nif_path, planet_tex_search)
        except Exception as e:
            if verbose:
                print(f"[host_loop]   realize: skip planet: load_model({nif_path}) "
                      f"raised: {type(e).__name__}: {e}", flush=True)
            continue
        center, half_extents = r_.model_aabb(handle)
        extent = _model_extent_from_aabb(center, half_extents)
        sphere_radius = _model_sphere_radius_from_aabb(center, half_extents)
        if planet.GetRadius() <= 0.0:
            try:
                planet.SetRadius(extent * BC_MODEL_SCALE)
            except Exception as _e:
                dev_mode.log_swallowed("realize planet.SetRadius fallback", _e)
        radius = planet.GetRadius()
        # Divide by the bound-sphere radius (BC's render_scale divisor), not the
        # AABB corner, so the planet draws at exactly GetRadius() game units.
        natural_scale = (radius / sphere_radius) if sphere_radius > 0.0 else 1.0
        iid = r_.create_instance(handle)
        r_.set_world_transform(iid, _astro_world_matrix(planet, natural_scale))
        session.planet_instances[planet] = iid
        session.planet_natural_scale[planet] = natural_scale


def teardown_set_objects(session, pSet, renderer) -> None:
    """Destroy render instances for this set's REMAINING objects and forget them.

    The warp spine moves the player out of the source set before terminating it,
    so the player is no longer enumerated here and survives. Objects outside
    `pSet` are never touched."""
    for ship in list(_iter_ships_in_set(pSet)):
        iid = session.ship_instances.pop(ship, None)
        if iid is not None:
            renderer.destroy_instance(iid)
            # ship_glow_controllers is keyed by instance id.
            session.ship_glow_controllers.pop(iid, None)
    for planet in list(_iter_planets_in_set(pSet)):
        iid = session.planet_instances.pop(planet, None)
        if iid is not None:
            renderer.destroy_instance(iid)
            session.planet_natural_scale.pop(planet, None)


def _reconcile_runtime_instances(session, renderer, *,
                                 on_player_change=None,
                                 verbose: bool = False) -> None:
    """Reconcile renderer instances against the set's LIVE ship roster.

    Load-time realization (`_MissionLoader.load`) only realizes the ships that
    exist at mission load. Ships created at RUNTIME — QuickBattle's player ship
    (StartSimulation2 -> RecreatePlayer destroys+recreates the player) and
    reinforcement spawns in other missions — never get a render instance, and
    ships removed from the set leak their instance. This pass, run once per tick
    before `_sync_instance_transforms`, closes both gaps with a cheap set-diff
    over the live ship list:

      * ADDITIONS — any ship now in a set but not in `session.ship_instances` is
        realized via `realize_set_objects` (per-set, idempotent: it skips ships
        already realized, so re-running is a no-op and models are not reloaded).
      * REMOVALS — any ship in `session.ship_instances` no longer present in any
        set has its instance destroyed and is dropped from the dict (the same
        teardown `teardown_set_objects` does, but driven by the diff so it works
        for individual despawns, not just whole-set termination).
      * PLAYER/CAMERA — if `Game_GetCurrentGame().GetPlayer()` is a different
        object than `session.player` (identity change, e.g. RecreatePlayer's
        destroy+recreate), `session.player` is updated to the new ship and the
        `on_player_change` callback (if any) fires with the new player so the
        host can retarget the camera. The camera follows `session.player`, so
        updating it is the retarget.

    Steady state (every ship present at load, unchanged player) is a true no-op:
    no additions, no removals, callback not fired. This keeps existing missions
    byte-identical to the pre-reconciliation path.
    """
    import App

    # QuickBattle creates/recreates the player ship LATE (StartSimulation2 ->
    # RecreatePlayer destroy+recreate), so the rendered player often isn't the
    # one load_quickbattle saw. Apply BC's Federation "default NCC" registry to
    # the current player just before the ADD loop realizes it, so its hull reads
    # a name (Galaxy -> Dauntless) rather than the stock Enterprise. Guarded to a
    # QB session + a not-yet-realized player with no registry already queued, so
    # it runs once per player and never overrides a scripted swap.
    if session.mission_name == "QuickBattle":
        from engine.appc import registry_texture
        _g = Game_GetCurrentGame()
        _p = _g.GetPlayer() if _g is not None else None
        if (_p is not None and _p not in session.ship_instances
                and not registry_texture.has_replacements(_p)):
            registry_texture.apply_class_default(_p)

    # ADDITIONS: realize un-realized ships in the ACTIVE set only. BC keeps one
    # space set live at a time; realizing every set here would re-bleed other
    # systems' ships (the Serris2 Cardassians, the Vesuvi6 Facility, Starbase 12)
    # into the player's scene the tick after load. Idempotent — realize_set_objects
    # skips ships already in session.ship_instances. When no active set is
    # determinable (no player yet) fall back to the legacy all-sets reconcile.
    from engine.appc.ship_iter import active_set as _active_set
    act = _active_set()
    if act is not None:
        live_ships = set(_iter_ships_in_set(act))
        if any(ship not in session.ship_instances for ship in live_ships):
            realize_set_objects(session, act, renderer, verbose=verbose)
    else:
        live_ships = set()
        for pSet in App.g_kSetManager._sets.values():
            set_ships = list(_iter_ships_in_set(pSet))
            live_ships.update(set_ships)
            if any(ship not in session.ship_instances for ship in set_ships):
                realize_set_objects(session, pSet, renderer, verbose=verbose)

    # REMOVALS: any realized ship not in the live (active-set) roster is destroyed
    # and forgotten — covers both despawns and ships left behind when the player
    # warps to another set.
    for ship in list(session.ship_instances.keys()):
        if ship not in live_ships:
            iid = session.ship_instances.pop(ship, None)
            if iid is not None:
                renderer.destroy_instance(iid)
                # ship_glow_controllers is keyed by instance id.
                session.ship_glow_controllers.pop(iid, None)

    # PLAYER/CAMERA: detect a player identity change (covers RecreatePlayer).
    game = Game_GetCurrentGame()
    new_player = game.GetPlayer() if game is not None else None
    if new_player is not None and new_player is not session.player:
        session.player = new_player
        if on_player_change is not None:
            on_player_change(new_player)


def _fire_pending_preload_done() -> None:
    """Fire the current game's stored preload-done event once, if pending.

    QuickBattle.StartSimulationAction stores a TGEvent(ET_PRELOAD_DONE,
    destination=mission) via Game.SetPreLoadDoneEvent, trusting the engine to
    fire it once asset preloading finishes. In dauntless asset loading is
    synchronous, so we fire it on the next tick. The event's handler is
    QuickBattle.StartSimulation2, which CREATES the player ship — so the host
    loop calls this BEFORE _reconcile_runtime_instances on the same tick, and
    the reconciliation pass then realizes the freshly-spawned ship.

    Fire-once + re-entrancy safe: the slot is cleared BEFORE the event is
    posted, so a handler that re-enters the loop (or a second call this tick)
    sees no pending event. Everything is guarded — no game and no pending event
    are both silent no-ops.
    """
    import App  # deferred: module-top `import App` is intentionally avoided.

    game = Game_GetCurrentGame()
    if game is None:
        return
    event = getattr(game, "_preload_done_event", None)
    if event is None:
        return
    # Clear before firing: fire-once / re-entrancy safe.
    game._preload_done_event = None
    App.g_kEventManager.AddEvent(event)


def _process_object_deletions() -> None:
    """Remove objects flagged via SetDeleteMe(1) from their set.

    BC's engine deletes delete-me-flagged objects every tick. QuickBattle's
    EndSimulation ("End Combat") flags every non-player ship + torpedo this way
    to clear the battle; without this they linger in the set and on screen.
    After removal the per-tick reconciliation tears down their render instances.
    Reads the flag via __dict__ (not getattr) so a TGObject __getattr__ _Stub
    can never masquerade as a truthy flag and delete live objects."""
    import App
    sets = getattr(App.g_kSetManager, "_sets", None)
    if not sets:
        return
    for pSet in list(sets.values()):
        objs = getattr(pSet, "_objects", None)
        if not objs:
            continue
        doomed = [name for name, obj in list(objs.items())
                  if obj.__dict__.get("_delete_me", False)]
        for name in doomed:
            pSet.RemoveObjectFromSet(name)


def _sync_quick_battle_panel(controller) -> None:
    """Mirror the QuickBattle config dialog's open/closed state onto the CEF
    Quick Battle Setup panel.

    QuickBattle.g_bDialogUp is the SDK's "config dialog is up" flag: 0 after
    InitGlobals (boot), 1 once OpenConfigDialog runs (the XO "Quick Battle
    Setup" button fires ET_OPEN_DIALOG), back to 0 on CloseConfigDialog /
    StartQuickBattle. We render our own panel instead of the SDK's g_pPane, so
    the panel follows that flag: boot leaves it closed (the player opens it from
    the XO menu, in cursor mode), and Close/Start close it. Fully guarded — a
    no-op when QuickBattle isn't the active module or the panel is absent."""
    panel = getattr(controller, "quick_battle_setup_panel", None)
    if panel is None:
        return
    try:
        import importlib
        qb = importlib.import_module("QuickBattle.QuickBattle")
        up = bool(getattr(qb, "g_bDialogUp", 0))
    except Exception:
        return
    if up and not panel.is_open():
        panel.open()
    elif not up and panel.is_open():
        panel.close()


def _sync_quickbattle_player_revert(controller) -> None:
    """Revert to the player's original ship when combat ends.

    The player's ship outside the simulation is captured ONCE (the boot
    QuickBattle default, before they pick anything). Every "Set As Player Ship"
    pick — in config OR mid-combat — is temporary: when bInSimulation goes 1->0
    (End Combat, panel or XO menu), restore g_sPlayerType to the original and
    RecreatePlayer so the player is never left stuck on the ship they flew in
    the sim. Fully guarded — a no-op when QuickBattle isn't active or the ship
    is already the original."""
    try:
        import importlib
        qb = importlib.import_module("QuickBattle.QuickBattle")
        in_sim = bool(getattr(qb, "bInSimulation", 0))
    except Exception:
        return
    # Capture the original (pre-pick) ship once, on the first tick.
    if not hasattr(controller, "_qb_original_player_type"):
        controller._qb_original_player_type = getattr(qb, "g_sPlayerType", None)
    last = getattr(controller, "_qb_last_in_sim", False)
    controller._qb_last_in_sim = in_sim
    if last and not in_sim:                 # End Combat
        orig = controller._qb_original_player_type
        if orig is not None and getattr(qb, "g_sPlayerType", None) != orig:
            qb.g_sPlayerType = orig
            try:
                qb.RecreatePlayer()
            except Exception as _e:
                import engine.dev_mode as _dev
                _dev.log_swallowed("quickbattle player-ship revert", _e)


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
        # Bounding-sphere radius per NIF path — the planet/moon render-scale
        # divisor (see _model_sphere_radius_from_aabb). Cached alongside extent.
        self.nif_to_sphere_radius: dict[str, float] = {}
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
        from engine.appc import subsystem_cascade
        subsystem_cascade.reset()
        from engine.appc import warp_core_breach
        warp_core_breach.reset()
        from engine.appc import core_breach_carve
        core_breach_carve.reset()
        from engine.appc import visible_damage
        visible_damage.reset()
        from engine.appc import registry_texture
        registry_texture.reset()
        from engine.appc import shockwaves
        shockwaves.reset()
        from engine.appc import particles
        particles.reset()
        damage_eligibility.reset()
        hit_feedback._last_carve_time.clear()
        hit_feedback._pending_carve_strength.clear()
        reset_sdk_globals()
        # A mission swap mid-warp would otherwise leak the WarpVFX manager
        # (reset_sdk_globals zeroes the timer manager, cancelling the pending
        # ReturnControl / stop chain). Tear it down explicitly so the next
        # mission starts with no stale streak/flash, no stale ship turn, and
        # control restored.
        try:
            from engine import warp_vfx as _wv
            _wv.get().stop()
        except Exception:
            pass
        try:
            # end_flythrough() (no ship) releases EVERY registered ship and
            # sets each back to WES_NOT_WARPING — not warp_state.reset(),
            # which only drops the registration and leaves the ship's own
            # warp state untouched. It is a strict superset of reset() and
            # harmless on a ship about to be destroyed by this same swap.
            from engine.appc import warp_state as _warp_state
            _warp_state.end_flythrough()
        except Exception:
            pass
        try:
            _warp_clear_turn()
        except Exception:
            pass
        try:
            import MissionLib
            MissionLib.ReturnControl()
        except Exception:
            pass
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
        _init_mission(mission_name)
        return self._realize_session(MissionSession(mission_name=mission_name))

    def load_quickbattle(self) -> MissionSession:
        """Boot the REAL SDK QuickBattle entry cascade and realize its scene.

        This is the headless-testable half of the no-mission-name boot path:
        it deliberately does NOT touch GLFW/window setup. It mirrors
        _init_mission's current-game wiring (reset_sdk_globals + a fresh
        Game/_set_current_game), then runs QuickBattleGame.Initialize(game),
        which cascades through Game.LoadEpisode ->
        QuickBattleEpisode.Initialize -> Episode.LoadMission ->
        QuickBattle.Initialize (Task 1), building the QuickBattleRegion set,
        the GalaxyBridge, and the initial player ship.

        After the cascade it injects the faithful player-only default state and
        posts ET_START_SIMULATION to the SDK's own g_pXO via the event manager
        — never calling StartSimulation* directly — so the SDK's 2s TGSequence,
        StartSimulationAction/SetPreLoadDoneEvent, _fire_pending_preload_done,
        and StartSimulation2 carry the flow. Finally it runs the same scene
        realization walk load() uses and returns the MissionSession.
        """
        import App
        from engine.core.game import Game, _set_current_game

        reset_sdk_globals()
        game = Game()
        _set_current_game(game)

        # The real game always has an Options.cfg on disk (the launcher/menu
        # writes it). QuickBattle.BuildDialog early-returns — skipping the
        # config-dialog buttons including g_pStartButton — when
        # LoadConfigFile("Options.cfg") returns 0, and StartSimulation later
        # dereferences g_pStartButton unconditionally. Headless there is no
        # launcher, so guarantee the file exists (matching the real launch
        # invariant) before the cascade builds the dialog.
        if App.g_kConfigMapping.LoadConfigFile("Options.cfg") == 0:
            App.g_kConfigMapping.SaveConfigFile("Options.cfg")

        import QuickBattle.QuickBattleGame as _QBGame
        _QBGame.Initialize(game)

        # BC gives a Federation player ship a default registry / hull name
        # ("Dauntless" for a Galaxy, etc. — MissionLib's "default NCC"). QuickBattle
        # runs no script ReplaceTexture, so apply the class default here (before
        # realization) so the player's hull reads a name rather than the stock
        # Enterprise registry. Non-Federation players map to nothing and are left
        # unchanged. Queued on the ship, consumed by _realize_session's loader.
        try:
            from engine.appc import registry_texture
            _qb_player = game.GetPlayer()
            if _qb_player is not None:
                registry_texture.apply_class_default(_qb_player)
        except Exception as _e:
            dev_mode.log_swallowed("QB registry default", _e)

        self._inject_quickbattle_player_defaults()
        return self._realize_session(MissionSession(mission_name="QuickBattle"))

    @staticmethod
    def _inject_quickbattle_player_defaults() -> None:
        """Set the player-only QuickBattle defaults and post the faithful
        ET_START_SIMULATION through the SDK's own globals/handlers.

        Galaxy player ship + GalaxyBridge, the QuickBattleRegion as the
        selected region, and empty enemy/friend lists (a player-only battle).
        The event is targeted at QuickBattle.g_pXO (the SDK BuildDialog
        registered StartSimulation there) and posted via g_kEventManager so the
        SDK handler runs unchanged.
        """
        import App
        import QuickBattle.QuickBattle as QB

        QB.g_sPlayerType = "Galaxy"
        QB.g_sBridgeType = "GalaxyBridge"
        QB.g_sSelectedRegion = "QuickBattleRegion"
        QB.g_kEnemyList = []
        QB.g_kFriendList = []

    def start_quickbattle(self) -> None:
        """Post ET_START_SIMULATION to g_pXO via the SDK event manager.

        Separated from load_quickbattle so the boot path can stage the menu
        defaults before the player triggers (or the host auto-triggers) the
        battle. Faithful: routes through g_pXO's registered StartSimulation
        handler, never calling StartSimulation directly.
        """
        import App
        import QuickBattle.QuickBattle as QB

        evt = App.TGEvent_Create()
        evt.SetEventType(QB.ET_START_SIMULATION)
        evt.SetDestination(QB.g_pXO)
        App.g_kEventManager.AddEvent(evt)

    def _realize_session(self, sess: MissionSession) -> MissionSession:
        import App
        r_ = self._c.renderer

        shared_search = [
            str(PROJECT_ROOT / "game" / DEFAULT_TEXTURE_SEARCH),
            str(PROJECT_ROOT / "game" / "data" / "Models" / "SharedTextures" / "FedBases" / "High"),
        ]
        for ship in _iter_active_ships(verbose=self._verbose):
            nif_path = _ship_nif_path(ship, verbose=self._verbose)
            if nif_path is None:
                continue
            # BC ships split textures: a per-ship High/ dir for hull-specific
            # assets (Sovereign, FedStarbase) plus the shared FedShips/FedBases
            # directories (Galaxy and many others ship nothing locally).
            tex_search = [str(Path(nif_path).parent / "High"), *shared_search]
            # Federation registry / hull-name swaps make the same NIF a distinct
            # model, so the handle cache is keyed by (nif, registry). The extent
            # is pure geometry — identical across registries — so it stays keyed
            # by nif_path.
            reps = _ship_texture_replacements(ship)
            load_key = _ship_load_key(nif_path, reps)
            handle = self._c.nif_to_handle.get(load_key)
            if handle is None:
                try:
                    handle = r_.load_model(nif_path, tex_search, reps)
                except Exception as e:
                    if self._verbose:
                        print(f"[host_loop]   skip ship: load_model({nif_path}) raised: "
                              f"{type(e).__name__}: {e}", flush=True)
                    continue
                self._c.nif_to_handle[load_key] = handle
                if nif_path not in self._c.nif_to_extent:
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
            render_instances.register(ship, iid)
            # Fresnel rim applies to ship hulls only — planets share the
            # opaque shader and must stay rim-free (default ineligible).
            r_.set_rim_eligible(iid, True)
            r_.set_rim_strength(iid, _rim_strength_for(ship))

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
                self._c.nif_to_sphere_radius[nif_path] = \
                    _model_sphere_radius_from_aabb(center, half_extents)
            extent = self._c.nif_to_extent.get(nif_path, 1.0)
            sphere_radius = self._c.nif_to_sphere_radius.get(nif_path, extent)
            if planet.GetRadius() <= 0.0:
                try:
                    planet.SetRadius(extent * BC_MODEL_SCALE)
                except Exception as _e:
                    dev_mode.log_swallowed("planet.SetRadius fallback", _e)
            radius = planet.GetRadius()
            # Divide by the bound-sphere radius (BC's render_scale divisor), not
            # the AABB corner, so the planet draws at exactly GetRadius() GU.
            natural_scale = (radius / sphere_radius) if sphere_radius > 0.0 else 1.0
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


# Pixels of CEF scroll per wheel detent (GLFW yoffset == 1.0). Positive
# delta_y scrolls panel content up. Tune to feel; sign confirmed in live
# verify.
_WHEEL_PX_PER_NOTCH = 40


def _route_scroll_wheel(scroll_y, *, route_to_panel, mx, my,
                        send_wheel, player_control, can_throttle) -> None:
    """Route one frame's accumulated mouse-wheel delta.

    route_to_panel True (a pause/config modal is open, or the cursor is over
    a HUD panel) → forward to CEF as a scaled pixel delta. Otherwise, when
    can_throttle (exterior view + a live player), step the ship throttle one
    impulse notch per detent. A no-op when scroll_y is 0.
    """
    if not scroll_y:
        return
    if route_to_panel:
        if send_wheel is not None:
            send_wheel(int(mx), int(my),
                       int(round(scroll_y * _WHEEL_PX_PER_NOTCH)))
        return
    if can_throttle and player_control is not None:
        # Throttle direction: a wheel-up gesture must INCREASE speed. The
        # raw accumulator sign is inverted relative to that on the target
        # platform (confirmed in live verify), so negate it here. The panel
        # path above keeps the raw sign — CEF expects the accumulator's own
        # direction.
        notches = -int(round(scroll_y))
        if notches:
            player_control.nudge_throttle(notches)


def _apply_input(view_mode, player_control, director,
                 *, player, dt, h) -> None:
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
        director.chase.apply(dt, h)
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


# ── ViewscreenZoomTarget (VZT) framing ─────────────────────────────────────────
# The bridge viewscreen auto-focuses the player's current target (BC's
# first-valid-wins viewscreen mode chain), rendering the SAME framing the
# exterior view shows when holding Z (camera_zoom_target): eye placed close
# behind the target on the ship->target axis, looking at the target's
# subsystem aim point, FOV unchanged from the exterior view (never narrowed).
# Lengths in game units.
VS_NEAR: float = 1.0
VS_FAR: float = 5000.0


def _viewscreen_scene_feed(player, forward_fov):
    """Resolve the ViewscreenZoomTarget scene feed: the SAME framing the
    exterior view shows when holding Z (camera_zoom_target), rendered into the
    bridge viewscreen RTT. Returns (eye, target, up, fov_y_rad, near, far) or
    None to leave the plain forward feed.

    BC's viewscreen mode chain is first-valid-wins, so a live Target IS the
    engagement. The frame-to-frame `_vs_last_player_target` compare stands in for
    Camera.PlayerTargetChanged (we never dispatch ET_TARGET_WAS_CHANGED), which
    lets MissionLib.ViewscreenWatchObject(obj) persist until the player retargets.

    Framing reuses engine.cameras.tracking._TrackingCamera in ZoomTarget mode —
    the identical solver the exterior Z zoom uses (eye close behind the target on
    the ship->target axis, look-at the subsystem aim point, FOV unchanged at the
    exterior value). Rigid (dt=None): no spring smoothing, which for an inset
    reads as a clean lock rather than a swoop.

    Pull-model: reads SDK state, never writes bridge_flag()/GetRenderedSet()."""
    if player is None:
        return None
    from engine.appc.camera_modes import _target_alive
    game = Game_GetCurrentGame()
    if game is None:
        return None
    cam = game.GetPlayerCamera()
    if cam is None:
        return None
    mode = cam.GetNamedCameraMode("ViewscreenZoomTarget")   # Target holder only
    if mode is None:
        return None

    cur = player.GetTarget()
    if cur is not cam._vs_last_player_target:      # stands in for PlayerTargetChanged
        mode.SetAttrIDObject("Target", cur)
        cam._vs_last_player_target = cur

    tgt = mode.GetAttrIDObject("Target")            # mission watch persists until then
    if not _target_alive(tgt):
        return None                                  # -> ViewscreenForward

    from engine.cameras.tracking import _TrackingCamera
    from engine.ui.target_reticle import target_aim_point
    tc = _TrackingCamera()
    tc.set_ship_radius(max(player.GetRadius(), 1e-6))
    tc.enter_zoom_target()
    # Subsystem-aware aim only when watching the player's OWN target; a mission
    # ViewscreenWatchObject on a different object frames that object's centre.
    aim = target_aim_point(player) if tgt is player.GetTarget() else None
    eye, look_at, up = tc.compute(player=player, target=tgt, dt=None, aim_point=aim)
    return (eye, look_at, up, forward_fov, VS_NEAR, VS_FAR)


def _select_viewscreen_source(r, comm_feed, scene_feed):
    """Push the viewscreen RTT source for this frame with precedence
    comm hail > VZT scene > forward. `comm_feed` is the tuple already resolved
    by _active_comm_feed (or None); `scene_feed` is _viewscreen_scene_feed's
    return (or None). Exactly one of comm/scene is active at a time; the other
    source is always cleared, so an unset source can never linger.
    Returns "comm" | "scene" | "forward"."""
    if comm_feed is not None:
        # Caller renders the comm source (it owns the set-bounds framing); we
        # only guarantee the scene source is cleared so it can't co-render.
        r.clear_viewscreen_scene_source()
        return "comm"
    r.clear_viewscreen_comm_source()
    if scene_feed is not None:
        r.set_viewscreen_scene_source(*scene_feed)
        return "scene"
    r.clear_viewscreen_scene_source()
    return "forward"


def _active_cutscene_camera():
    """If the rendered set has an active cutscene camera with a live mode,
    return (camera, mode); else None.

    Mission scripts do ChangeRenderedSet(space_set) + CutsceneCameraBegin +
    a camera-mode action (LockedView/ChaseCam/TargetWatch), which pushes a
    CameraMode onto the set's active camera. When that's present we drive the
    exterior view from the mode (see the exterior branch below). Otherwise we
    fall through to the player director, unchanged.

    Gated on a live IsValid() mode so plain comm 'maincamera's, mode-less
    cameras, and dead-target modes all return None and the director resumes.
    """
    import App as _App
    rendered = _App.g_kSetManager.get_explicit_rendered_set()
    if rendered is None:
        return None
    get_active = getattr(rendered, "GetActiveCamera", None)
    cam = get_active() if callable(get_active) else None
    if cam is None:
        return None
    get_mode = getattr(cam, "GetCurrentCameraMode", None)
    mode = get_mode() if callable(get_mode) else None
    if mode is None or not mode.IsValid():
        return None
    return (cam, mode)


def _cutscene_pose(mode, dt):
    """Convert a cutscene CameraMode's Update() result — (eye, forward_dir, up)
    in world game units — into the (eye, look_at_point, up) triple the main
    scene camera consumes. Update returns a forward DIRECTION; r.set_camera
    expects a look-at POINT, so add eye. (Fixes the direction-as-point seam the
    merged in-space controller (365207f7) shipped with.)"""
    eye, fwd, up = mode.Update(dt)
    look_at = (eye[0] + fwd[0], eye[1] + fwd[1], eye[2] + fwd[2])
    return (eye, look_at, up)


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
        elif not is_bridge:
            # Mission swap re-realizes this comm set against a fresh SetClass
            # carrier (reset_sdk_globals cleared g_kSetManager._sets), so this
            # guard is True. Tear down the prior load's comm instances for this
            # set — room geometry AND posed characters share the per-set list —
            # and reset it before re-realizing, or they orphan in the Pass::Comm
            # scenegraph and comm_instances_by_set grows unbounded. Gated by the
            # fresh-carrier geometry guard so a same-carrier re-realize (guard
            # False) skips teardown and recreate together, staying consistent.
            # Mirrors the bridge officer-instance teardown below.
            _prior = controller.comm_instances_by_set.get(set_name, [])
            if _prior and dev_mode.is_enabled():
                print("[host_loop] comm-set %r swap: tearing down %d prior "
                      "instance(s)" % (set_name, len(_prior)), flush=True)
            for _iid in _prior:
                try:
                    r.destroy_instance(_iid)
                except Exception as _e:
                    dev_mode.log_swallowed("destroy comm instance (teardown)", _e)
            controller.comm_instances_by_set[set_name] = []

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
    for name, s in list(mgr.iter_sets()):          # use the manager's set map
        if name == "bridge":
            realize_set(controller, r, s, is_bridge=True)
    _realize_comm_sets(controller, r)


def _realize_comm_sets(controller, r) -> None:
    """Realize every comm/remote set (one that declares a background model or
    characters) that isn't realized yet, allocating it a stable comm_set_id.

    Runs at load (from realize_all_sets) AND once per tick, so a comm set
    created LATE gets realized too. E6M2's FedOutpostSet_Graff is built lazily
    by Systems/Starbase12/Starbase12_S.SetupGraffSet when the player docks —
    long after the one-shot load-time realize pass — so without a per-tick sweep
    its room geometry (fedoutpost.nif) and Graff's model never realize and its
    viewscreen shows a black void (no comm_set_id => _active_comm_feed can't
    resolve the feed either).

    Idempotent + cheap: realize_set skips already-built instances (render_instance
    guard) and a set keeps its existing id, so per-tick this is a dict-vs-
    iter_sets diff over a handful of sets. comm_set_id allocation stays
    monotonic (max existing + 1) so an already-tagged set is never renumbered.
    """
    import App as _App
    mgr = _App.g_kSetManager
    ids = controller.comm_set_ids
    next_id = (max(ids.values()) + 1) if ids else 1
    for name, s in list(mgr.iter_sets()):
        if name == "bridge":
            continue
        _nif = s.GetBackgroundModelNIF()
        _chars = _iter_set_characters(s) or []
        if _nif is None and not _chars:
            continue
        comm_set_id = ids.get(name)
        if comm_set_id is None:
            comm_set_id = next_id
            ids[name] = comm_set_id
            next_id += 1
        # create_comm_instance is a REQUIRED renderer binding (validated at
        # boot), so it is always present.
        realize_set(controller, r, s, is_bridge=False, comm_set_id=comm_set_id)


def _iter_set_characters(set_obj):
    """Enumerate every CharacterClass in a set — the same walk the old
    bridge-officer loop used (GetClassObjectList(CharacterClass))."""
    from engine.appc.characters import CharacterClass
    return set_obj.GetClassObjectList(CharacterClass)


def _live_bridge_characters():
    """Realised, visible bridge officers (each carries _render_instance set by
    _place_one_character). Empty when no bridge set exists."""
    import App as _App
    bridge = _App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return []
    return [c for c in _iter_set_characters(bridge)
            if getattr(c, "_render_instance", None) is not None and not c.IsHidden()]


def _live_speech_characters(controller):
    """Every realised character lip-sync may need to drive: the player-bridge
    officers PLUS the comm-set characters (a hailing Soams / Admiral on the
    viewscreen). The lip-sync resolver matches the crew-speech speaker by name
    against this list, so a comm speaker omitted here gets subtitles + audio but
    a frozen mouth (its viseme textures are uploaded; only the driver misses it).
    Comm characters are included whenever they carry a render instance —
    visibility is handled by the renderer, and only the named speaker is ever
    driven, so a momentarily-hidden instance is harmless."""
    import App as _App
    chars = list(_live_bridge_characters())
    for set_name in getattr(controller, "comm_set_ids", {}):
        s = _App.g_kSetManager.GetSet(set_name)
        if s is None:
            continue
        chars.extend(c for c in _iter_set_characters(s)
                     if getattr(c, "_render_instance", None) is not None)
    return chars


def _sync_comm_character_visibility(controller, r) -> None:
    """Drive each realized comm-set character's instance visibility from its SDK
    IsHidden() flag.

    Comm characters are assembled up front but start hidden (SetHidden(1) in the
    mission setup). MissionLib.ViewscreenOn un-hides just the hailing character
    (SetHidden(0)) at runtime; this per-frame sync turns that flag into actual
    renderer visibility, so the hailing character appears on the viewscreen and
    the rest of the room's characters stay hidden. Cheap: a handful of
    characters across the mission's comm sets."""
    import App as _App
    for set_name in getattr(controller, "comm_set_ids", {}):
        s = _App.g_kSetManager.GetSet(set_name)
        if s is None:
            continue
        for ch in _iter_set_characters(s):
            iid = getattr(ch, "_render_instance", None)
            if iid is None:
                continue
            try:
                r.set_visible(iid, not ch.IsHidden())
            except Exception as _e:
                dev_mode.log_swallowed("comm char visibility sync", _e)


def _bridge_characters_for_sync(controller):
    """Every realized-or-not bridge CharacterClass (the player bridge set). Split
    out so the visibility sync is unit-testable without a live set manager."""
    import App as _App
    s = _App.g_kSetManager.GetSet("bridge")
    if s is None:
        return []
    return list(_iter_set_characters(s))


def _sync_bridge_character_visibility(controller, r) -> None:
    """Drive each realized bridge character's instance visibility from its SDK
    IsHidden() flag — the bridge analogue of _sync_comm_character_visibility.

    Bridge walk-on characters (E1M1 Picard/Saffi) are realized on demand and
    revealed by the walk controller's SetHidden(0); this per-frame sync turns any
    IsHidden toggle into actual renderer visibility. Cheap: a handful of bridge
    characters."""
    for ch in _bridge_characters_for_sync(controller):
        iid = getattr(ch, "_render_instance", None)
        if iid is None:
            continue
        try:
            r.set_visible(iid, not ch.IsHidden())
        except Exception as _e:
            dev_mode.log_swallowed("bridge char visibility sync", _e)


def _tag_comm_instance(r, iid, comm_set_id) -> None:
    """Tag a comm instance with its set's id so the bridge pass can render the
    set into the viewscreen RTT. set_comm_set_id is a REQUIRED renderer binding
    (validated at boot), so it is always present."""
    if comm_set_id is None:
        return
    try:
        r.set_comm_set_id(iid, comm_set_id)
    except Exception as _e:
        dev_mode.log_swallowed("set_comm_set_id", _e)


def _place_one_character(controller, r, character, set_name, is_bridge,
                         *, comm_set_id: int = None) -> None:
    """Pose one SDK CharacterClass at its station and create its skinned
    instance. Delegates the instance-building tail to
    _realize_character_instance; the only change is create_bridge_instance vs
    create_comm_instance and the comm_instances_by_set bookkeeping.

    Leak-free + idempotent: per-character _render_instance tag prevents
    double-placement within a load (a fresh set rebuild enumerates fresh,
    untagged characters).
    """
    from engine.appc.bridge_placement import capture_placement

    if getattr(character, "_render_instance", None) is not None:
        return                                       # already placed this load
    try:
        placement = capture_placement(character)
        if not placement:
            return
        # Bridge officers explicitly hidden (e.g. E1M1 Picard waiting in the
        # turbolift) stay unplaced. Comm-set characters are different: the SDK
        # mission setup hides them at load (SetHidden(1)) and dynamically
        # un-hides just the hailing one at runtime via
        # MissionLib.ViewscreenOn -> SetHidden(0). We must therefore build their
        # skinned instance up front (start it invisible) and drive its
        # visibility from IsHidden() each frame — see
        # _sync_comm_character_visibility. Otherwise the room renders on the
        # viewscreen but the character never does (Soams / Admiral Liu missing).
        if placement["hidden"] and is_bridge:
            return
        _realize_character_instance(
            controller, r, character, set_name, is_bridge,
            comm_set_id=comm_set_id, start_hidden=placement["hidden"])
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


def _realize_character_instance(controller, r, character, set_name, is_bridge,
                                *, comm_set_id: int = None,
                                start_hidden: bool = False):
    """Build the skinned instance for a character at its CURRENT placement, tag
    _render_instance, wire breathing, and register it. Returns the iid or None.

    Extracted from _place_one_character so the walk controller can realize a
    hidden bridge character on demand (AT_MOVE reveal). start_hidden hides the
    fresh instance (comm path); the walk controller passes start_hidden=False and
    reveals via SetHidden(0)."""
    from engine.appc.bridge_placement import capture_placement, capture_breathing

    placement = capture_placement(character)
    if not placement:
        return None

    def _abs(p):
        return str(PROJECT_ROOT / "game" / p) if p else None

    create = r.create_bridge_instance if is_bridge else r.create_comm_instance

    ap = character.appearance()
    if not ap.get("body_nif"):
        return None

    _facial = getattr(character, "_facial_images", {}) or {}
    _slot_of = {"SpeakA": "a", "SpeakE": "e", "SpeakU": "u",
                "Blink0": "blink1", "Blink1": "blink2", "Blink2": "eyesclosed"}
    face_images = {slot: _abs(_facial[k])
                   for k, slot in _slot_of.items() if _facial.get(k)}

    model = r.assemble_officer(
        _abs(ap.get("body_nif")), _abs(ap.get("head_nif")),
        _abs(ap.get("body_tex")), _abs(ap.get("head_tex")),
        _abs(placement["clip_nif"]),
        placement["sample_at_start"],
        face_images=face_images,
    )
    iid = create(model)
    try:
        r.set_world_transform(iid, OFFICER_TRANSFORM)
        r.set_instance_rest_pose(iid, 0, placement["sample_at_start"])
    except Exception:
        try:
            r.destroy_instance(iid)
        except Exception as _e:
            dev_mode.log_swallowed("destroy officer instance (rollback)", _e)
        raise
    character._render_instance = iid
    if start_hidden:
        try:
            r.set_visible(iid, False)
        except Exception as _e:
            dev_mode.log_swallowed("char initial hide", _e)
    try:
        breathing = capture_breathing(character)
        if breathing:
            bidx = r.load_instance_clip(iid, _abs(breathing["clip_nif"]))
            if bidx is not None and bidx >= 0:
                r.play_instance_idle(iid, bidx)
                from engine.bridge_character_anim import get_controller
                _ca = get_controller()
                if _ca is not None:
                    _ca.set_idle(iid, bidx)
    except Exception as _e:
        dev_mode.log_swallowed("establish breathing", _e)
    if is_bridge:
        controller.officer_instances.append(iid)
    else:
        controller.comm_instances_by_set.setdefault(set_name, []).append(iid)
        _tag_comm_instance(r, iid, comm_set_id)
    return iid


def _viewscreen_feed_on(viewscreen_obj) -> bool:
    """The viewscreen RTT feed is on iff a realized viewscreen object reports
    IsOn(). Off (or no viewscreen) -> the step-5b blank panel."""
    return bool(viewscreen_obj is not None and viewscreen_obj.IsOn())


class ViewscreenBrightnessRamp:
    """Brightness fade-in that accompanies the ViewOn/ViewOff sounds. The
    viewscreen feed has a "signature" — one of ('off',), ('forward',) or
    ('comm', set_id). Whenever the signature changes (comm appears on
    ViewscreenOn, or reverts to forward on ViewscreenOff), the brightness
    restarts at 0 and ramps linearly to 1 over DURATION_S. The sounds already
    fire via TGSoundAction; this is the matching visual."""

    DURATION_S = 0.3

    def __init__(self):
        self._sig = None
        self._elapsed = 0.0

    def update(self, signature, dt):
        if signature != self._sig:
            self._sig = signature
            self._elapsed = 0.0
        else:
            self._elapsed += dt
        b = self._elapsed / self.DURATION_S
        if b < 0.0:
            return 0.0
        if b > 1.0:
            return 1.0
        return b


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


def drive_viewscreen_static_and_brightness(r, controller, ramp, dt,
                                           *, intensity_fn=_vss.static_intensity):
    """Per-frame: push the static overlay + ViewOn/ViewOff brightness fade to
    the renderer from the SDK-driven ViewScreenObject state. Pure w.r.t. the
    renderer/controller it's given, so it's unit-tested with fakes."""
    vs = getattr(controller, "viewscreen_obj", None)

    # Feed signature for the brightness ramp.
    if vs is None or not vs.IsOn():
        signature = ("off",)
    else:
        feed = _active_comm_feed(controller)
        signature = ("comm", feed[0]) if feed is not None else ("forward",)
    r.set_viewscreen_brightness(ramp.update(signature, dt))

    # Static overlay (only when the SDK turned it on with a positive range).
    static_on = False
    intensity = 0.0
    if (vs is not None and vs.IsStaticOn()
            and getattr(vs, "_static_max", 0.0) > 0.0):
        paths = _vss.static_texture_paths(getattr(vs, "_static_icon_group", None))
        if paths and paths != getattr(controller, "_vs_static_paths_sent", None):
            r.set_viewscreen_static_source(paths)
            controller._vs_static_paths_sent = paths
        fmin = getattr(vs, "_static_min", 0.0)
        fmax = getattr(vs, "_static_max", 0.0)
        intensity = intensity_fn(fmin, fmax)
        static_on = True
        r.set_viewscreen_static(True, intensity)
    else:
        fmin = fmax = 0.0
        r.set_viewscreen_static(False, 0.0)

    # Dev-mode change log: emit once per state change; silent every frame
    # when dev mode is off (is_enabled() is a single bool getattr, no I/O).
    if dev_mode.is_enabled():
        log_key = (signature, static_on)
        if log_key != getattr(controller, "_vs_static_log_state", None):
            controller._vs_static_log_state = log_key
            if signature[0] == "off":
                feed_str = "off"
            elif signature[0] == "comm":
                feed_str = "comm:%s" % (signature[1],)
            else:
                feed_str = "forward"
            if static_on:
                print(
                    "[viewscreen] feed=%s static=on min=%.2f max=%.2f intensity=%.2f"
                    % (feed_str, fmin, fmax, intensity),
                    flush=True,
                )
            else:
                print(
                    "[viewscreen] feed=%s static=off" % (feed_str,),
                    flush=True,
                )


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


def resolve_officer_menu_layout() -> None:
    """Run the SDK's tactical-control-window layout so the officer-menu window
    resolves an absolute on-screen rect.

    The SDK's Tactical/Interface/TacticalControlWindow positions the officer-menu
    window (InterfacePane.GetNthChild(TACTICAL_MENU)) via ResizeUI (SetMaximumSize)
    + RepositionUI (SetPosition(0,0) then pTacCtrlWindow.Layout()). With
    TacticalControlWindow.Layout() now real, that pass caches the window's
    _abs_rect, so GetScreenOffset returns the RESOLVED absolute rect instead
    of falling back to local placement — unblocking the SDK-driven CEF
    positioning (GetScreenOffset / ResizeUI rects) tasks downstream.

    Two entry paths:
      * campaign / QuickBattle — LoadBridge.Load already ran CreateMenus (which
        builds the interface pane and ends with ResizeUI/RepositionUI). We re-run
        ResizeUI/RepositionUI; it is idempotent and re-drives Layout().
      * dev mission picker — swaps the mission WITHOUT LoadBridge.Load, so the TCW
        exists but has no interface pane. Build the menus once (CreateMenus ends
        with its own ResizeUI/RepositionUI). Never call CreateMenus when the pane
        already exists: the TCW is a singleton and a repeat appends duplicate panes.

    Guarded: a layout hiccup must never take down mission load, so any exception is
    logged with a traceback and swallowed.
    """
    import App as _App
    from engine.appc.windows import INTERFACE_PANE
    try:
        tcw = _App.TacticalControlWindow_GetTacticalControlWindow()
        if tcw is None:
            return
        import Tactical.Interface.TacticalControlWindow as _TCW
        if tcw.GetNthChild(INTERFACE_PANE) is None:
            # Dev-picker path: menus not built yet. CreateMenus ends with its
            # own ResizeUI()/RepositionUI() -> TacticalControlWindow.Layout().
            import Bridge.TacticalMenuHandlers as _TMH
            _TMH.CreateMenus()
        else:
            # Campaign / QB path: interface pane already built. Re-drive the
            # SDK resize+reposition (RepositionUI ends with TCW.Layout()).
            _TCW.ResizeUI()
            _TCW.RepositionUI()
    except Exception:
        import logging
        import traceback
        logging.getLogger(__name__).warning(
            "resolve_officer_menu_layout failed; officer menu may be unpositioned:\n%s",
            traceback.format_exc(),
        )


def _sync_instance_transforms(r, session, player, xform_buf, interp_alpha,
                              game_time, model_scale, player_control=None) -> None:
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
    # Warp blackout: once we jump to lightspeed (streak > 0) the whole local
    # scene is left behind — hide every non-player ship/station + planet so the
    # transit is just the player in the dust tunnel. _apply re-runs while
    # hiding (so objects realised mid-window are caught) plus the single frame
    # we stop (to restore visibility). Off-parity: no calls when not warping.
    global _warp_hidden
    from engine import warp_vfx as _wv_hide
    _wh = _wv_hide.get()
    _warp_hide = _wh.is_active() and _wh.streak_intensity() > 0.0
    _warp_apply_vis = _warp_hide or _warp_hidden
    _warp_hidden = _warp_hide
    _live_ship_iids = []
    # Hull-discharge emissive boost for the player: `_hull_discharge` is a
    # module global (HullDischargeDriver | None).  Returns exactly 1.0 when
    # idle / toggle-off / driver-None, so the hull is never left stuck bright.
    _hd_boost = (_hull_discharge.emissive_boost()
                 if (_hull_discharge is not None
                     and r.nebula_lightning_enabled())
                 else 1.0)
    # Player's commanded impulse notch (1-9) as a 0..1 fraction; drives the
    # impulse-glow boost for the player ship (AI ships derive their own from the
    # speed setpoint inside the controller). abs() so reverse still brightens.
    _player_throttle_frac = None
    if player_control is not None:
        _lvl = getattr(player_control, "impulse_level", 0) or 0
        _player_throttle_frac = min(abs(int(_lvl)), 9) / 9.0
    for ship, iid in session.ship_instances.items():
        _wg = session.ship_glow_controllers.get(iid)
        if _wg is not None:
            _wg.update(game_time,
                       _player_throttle_frac if ship is player else None)
        # Destroyed (dying/dead) ships lose self-illumination —
        # a dark hulk in space. Hull stays lit by external light.
        if _oa(ship):
            r.set_emissive_scale(iid, 0.0)
        elif ship is player:
            r.set_emissive_scale(iid, _hd_boost)
        else:
            r.set_emissive_scale(iid, 1.0)
        if iid == _player_iid:
            r.set_world_transform(
                iid, _ship_world_matrix(ship, model_scale))
            continue
        _live_ship_iids.append(iid)
        if _warp_apply_vis:
            r.set_visible(iid, not _warp_hide)
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
        if _warp_apply_vis:
            r.set_visible(iid, not _warp_hide)


def run(mission_name: Optional[str] = None,
        max_ticks: Optional[int] = None) -> int:
    """Boot the renderer, init the named mission, run until the window closes
    or max_ticks is reached. Returns 0 on clean exit.

    Mission resolution: an explicit ``mission_name`` argument loads that single
    mission (byte-for-byte the existing path); with no mission name the host
    boots the REAL SDK QuickBattle entry cascade to an auto-started player-only
    battle. ``SHIP_GATE_MISSION`` is still available to callers that pass it.

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
    # No mission name => boot the REAL SDK QuickBattle entry cascade (auto-start
    # player-only battle). A caller that passes an explicit mission_name (the
    # test harness, dev mission picker, every existing mission) keeps the
    # single-mission path byte-for-byte. SHIP_GATE_MISSION stays available for
    # callers that want it explicitly.
    boot_quickbattle = mission_name is None

    _setup_sdk()

    import App
    from engine.core.loop import GameLoop
    # Hoisted out of the per-tick loop body — imported once per run()
    # rather than every frame. Both are only used inside the loop below.
    from engine.appc import collisions
    from engine.appc import camera_shake

    r.init(1280, 720, "open_stbc")
    # Verify the native module exposes every binding the renderer façade calls.
    # Catches a stale/incomplete .so at boot (a recurring hazard — host_bindings
    # compiles into both this module and build/dauntless) instead of as a
    # silently-dead feature mid-mission. strict under --developer: a developer
    # wants to be stopped cold; production logs loudly and keeps running.
    r.validate_bindings(strict=dev_mode.is_enabled())
    # Same check for the non-render façade (engine.host_io): host_bindings.cc
    # compiles into both build/dauntless and the _dauntless_host module, so a
    # forgotten `cmake --build` can leave the window/input/VFX/damage surface
    # stale exactly as it can the renderer surface. Validate both façades at the
    # same boot point so a missing REQUIRED host_io binding fails loudly here
    # (strict under --developer; ERROR-logged in production) rather than as a
    # silently-dead feature mid-mission. verify_keys() likewise catches the host
    # `keys` submodule diverging from engine.input_map's table.
    host_io.validate_bindings(strict=dev_mode.is_enabled())
    host_io.verify_keys()
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
        _fb_w, _fb_h = host_io.framebuffer_size()
        _win_w, _win_h = host_io.window_size()
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

        # Warp spine render hooks (Stage 1 hard cut): the warp sequence loads
        # the destination set then calls realize; on arrival it tears down the
        # source set. Bound here to the live session+renderer. Unset hooks make
        # those steps headless no-ops, so this wiring is what gives the spine a
        # renderer.
        from engine.appc import warp as _warp
        def _warp_realize(pSet):
            if controller.session is not None:
                realize_set_objects(controller.session, pSet, controller.renderer)
        def _warp_teardown(pSet):
            if controller.session is not None:
                teardown_set_objects(controller.session, pSet, controller.renderer)
        _warp.configure_warp_hooks(
            realize=_warp_realize, teardown=_warp_teardown,
            current_player=lambda: (controller.session.player
                                    if controller.session is not None else None))

        # Warp-VFX flythrough (Stage 2): when the "Warp Flythrough" toggle is on
        # AND the procedural sky is on, WarpSequence_Create builds a timed
        # transit whose length scales with the galaxy-map distance between the
        # source and destination systems. The host supplies: the live-enabled
        # predicate, the start/stop manager hooks (ticked per frame above), and a
        # vantage resolver that maps EITHER a live source SetClass OR a
        # destination module string to a galaxy (x, y, z).
        from engine import warp_vfx as _wv
        from engine.appc import sky_projection as _sp
        from engine.appc import sector_model as _sm
        from engine.appc import warp as _wp

        def _flythrough_enabled():
            return bool(r.warp_flythrough_enabled()) and r.procedural_sky_enabled()

        def _vantage_of(key):
            # key is a live SetClass (the source) or a module string (the
            # destination). The destination set is NOT loaded yet at
            # sequence-build time, so for a module string we resolve the system
            # position straight from sector_model by its system id (module ->
            # set name -> system_id_for_set -> system["position"]) — the same
            # id path the Set Course catalog uses, no live set required.
            try:
                model = _sp.load_sector_model()
                if hasattr(key, "GetName"):
                    v = _sp.vantage_for_set(key, model)
                else:
                    set_name = _wp._set_name_from_module(key)
                    if not set_name:
                        return None
                    sysid = _sm.system_id_for_set(set_name)
                    v = None
                    for s in model.get("systems", []):
                        if s.get("id") == sysid:
                            v = s.get("position")
                            break
                return None if v is None else (v[0], v[1], v[2])
            except Exception:
                return None

        def _vfx_start(heading, t_align, t_transit, vantage=None,
                       dst_vantage=None):
            # WarpSequence (Task 3) computes the heading + explicit align/transit
            # times; start the per-frame manager at the current game time. The
            # vantage (source system's galaxy position) anchors the procedural
            # sky; dst_vantage (destination's) lets it fly src->dst and arrive,
            # so the destination nebula envelops on exit instead of streaming past.
            _wv.get().start(heading, t_align, t_transit,
                            App.g_kUtopiaModule.GetGameTime(), vantage,
                            dst_vantage)

        _wp.configure_warp_vfx(
            start=_vfx_start, stop=_wv.get().stop,
            enabled=_flythrough_enabled, vantage_of=_vantage_of)

        # Starbase warp gate (Task 4): segment-vs-mesh test against the
        # starbase's loaded NIF via host_io.ray_trace_mesh. Returns True if the
        # segment from->to hits the starbase mesh (occluded). Any missing piece
        # (no bindings / no session / no instance) => False, so the
        # warp_gates._near_starbase check degrades to "don't block".
        from engine.appc import warp_gates as _wg

        def _starbase_ray_collide(starbase, from_pt, to_pt):
            if controller.session is None:
                return False
            iid = controller.session.ship_instances.get(starbase)
            if iid is None:
                return False
            import math
            dx = to_pt[0] - from_pt[0]
            dy = to_pt[1] - from_pt[1]
            dz = to_pt[2] - from_pt[2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dist <= 1e-6:
                return False
            try:
                hit = host_io.ray_trace_mesh(iid, from_pt, (dx, dy, dz), dist)
            except Exception:
                return False
            return hit is not None

        _wg.configure_gate_hooks(ray_collide=_starbase_ray_collide)

        # CEF Set Course popup: selecting a warp point SETS THE COURSE — record
        # the destination set-module on the SDK warp button. The player then
        # engages the warp from the Helm "Warp" button (on_warp_engage below).
        def on_course_set(module):
            import App
            btn = App.SortedRegionMenu_GetWarpButton()
            if btn is not None:
                btn.SetDestination(module)
            # Stock BC's SortedRegionMenu course buttons fired ET_SET_COURSE
            # at the Helm menu (Kiska's "ready to warp" ack); the CEF modal
            # replaced that menu, so fire it here.
            try:
                from engine.bridge_officers import announce_course_set
                announce_course_set()
            except Exception as _e:
                dev_mode.log_swallowed("announce course set", _e)

        # Helm "Warp" button click -> engage the warp spine directly. Stage 1
        # deliberately bypasses the SDK ET_WARP_BUTTON_PRESSED / WarpPressed
        # path: WarpPressed does camera/cinematic + control work whose engine
        # support is deferred to Stages 2-3, and it runs live before our spine
        # could (a raise there is swallowed at the CEF boundary). Calling the
        # spine directly loads the destination set, moves the player, and
        # terminates the source. execute_warp reads the button's destination.
        def on_warp_engage(button):
            from engine.appc import warp as _w
            from engine.appc import warp_gates as _wg
            import App
            player = App.Game_GetCurrentPlayer()
            if player is None and controller.session is not None:
                player = controller.session.player
            result = _wg.warp_gate(player)
            if not result.allowed:
                if dev_mode.is_enabled():
                    print("[warp] gated: %s (line=%s)"
                          % (result.reason or "unknown",
                             result.deny_line or "-"), flush=True)
                if result.deny_line is not None:
                    _wg.speak_deny(player, result.deny_line)
                return
            _w.execute_warp(button)

        # Register the bridge cutscene controller BEFORE the initial mission
        # load so that TGAnimActions created during Initialize()/Briefing()
        # find a live controller and defer correctly (not instant-complete).
        # The controller stays registered for the lifetime of run(); mission
        # swaps reuse it without re-registering.
        from engine.bridge_cutscene import (
            BridgeCutsceneController, set_controller,
        )
        cutscene = BridgeCutsceneController(asset_resolver=_game_asset_path)
        set_controller(cutscene)

        from engine.bridge_character_anim import (
            BridgeCharacterAnimController, set_controller as set_char_anim,
        )
        from engine.bridge_node_anim import BridgeNodeAnimController
        from engine.bridge_idle_gestures import IdleGestureScheduler
        import random as _random
        char_anim = BridgeCharacterAnimController(asset_resolver=_game_asset_path)
        set_char_anim(char_anim)

        from engine.bridge_character_walk import (
            BridgeCharacterWalkController, set_controller as set_walk_ctrl,
        )
        walk_ctrl = BridgeCharacterWalkController(
            realize_fn=lambda ch: _realize_character_instance(
                controller, r, ch, "bridge", True, start_hidden=False),
            asset_resolver=_game_asset_path)
        set_walk_ctrl(walk_ctrl)

        from engine.bridge_camera_watch import (
            BridgeCameraWatchController, set_controller as set_watch_ctrl,
        )
        watch_ctrl = BridgeCameraWatchController()
        set_watch_ctrl(watch_ctrl)
        node_anim = BridgeNodeAnimController(
            bridge_iid_getter=lambda: controller.bridge_instance,
            asset_resolver=_game_asset_path,
        )
        char_anim.set_node_controller(node_anim)
        idle_gestures = IdleGestureScheduler(_random.Random(0xB1D6E))

        # Lip-sync: drives officer mouth visemes from .LIP timing via crew-speech
        # (engine/lip_sync_runtime.py). Resolves the speaking officer by name
        # against the live characters; idle blinks the rest. Uses
        # _live_speech_characters so BOTH player-bridge officers AND comm-set
        # characters (e.g. a hailing Soams on the viewscreen) get driven —
        # otherwise a comm speaker gets subtitles + audio but a frozen mouth.
        from engine.lip_sync_runtime import LipSyncRuntime
        lip_runtime = LipSyncRuntime(
            r, lambda: _live_speech_characters(controller))

        from engine.bridge_hit_reactions import HitReactionHandler
        import App as _App
        # Wire the walk-off lift door's real timing (Task 3, SP: lift door
        # ownership): headless test/harness runs never reach here, so
        # GetAnimationLength stays a safe 0.0 there.
        _App.g_kAnimationManager.set_duration_provider(
            lambda rel_path: _clip_duration(r, rel_path))
        def _get_player():
            g = Game_GetCurrentGame()
            return g.GetPlayer() if g is not None else None
        _hit_reactions = HitReactionHandler(
            char_anim,
            get_player=_get_player,
            get_characters=_live_bridge_characters,
            anim_mgr=_App.g_kAnimationManager,
        )
        _hit_wrapper = _App.TGPythonInstanceWrapper()
        _hit_wrapper.SetPyWrapper(_hit_reactions)
        controller._hit_reaction_wrapper = _hit_wrapper   # keep alive past run() scope

        # Bridge interior is created by the SDK path (LoadBridge.Load ->
        # Bridge.<name>.CreateBridgeModel) during the mission load below, then
        # realized into a render instance by realize_all_sets in
        # _after_mission_loaded. No eager pre-game load — the SDK is the single
        # source of the bridge mesh.

        # Bring the audio backend up BEFORE the mission loads: the mission's
        # StartMission runs the real SDK LoadBridge.Load -> LoadSounds(), which
        # must load bridge SFX into a live backend. Listener installs stay in
        # init_audio() below (relocating them would change spawn-event capture).
        init_audio_backend()
        if boot_quickbattle:
            # Real SDK QuickBattle entry cascade: builds the QuickBattleRegion
            # set, GalaxyBridge, and initial player, injects the player-only
            # defaults. We deliberately do NOT call start_quickbattle() here —
            # auto-posting ET_START_SIMULATION at boot fires
            # DisableSimulationMenus (greying the SDK config button) and drops
            # straight into the fight. Instead boot lands on the Quick Battle
            # Setup panel (opened just below, after the panel is constructed);
            # the player's Start there reconciles the start in a later task.
            # start_quickbattle() itself is kept for that reconciliation.
            controller.session = controller.loader.load_quickbattle()
        else:
            controller.session = controller.loader.load(mission_name)
        # The SDK's CreateAndPopulateBridgeSet plays AmbBridge at load
        # (LoadBridge.py:213); silence it now since the initial view is space.
        # bridge_ambient remains the sole authority on when the hum plays.
        _bridge_ambient_set(False)
        if verbose:
            ss = controller.session
            print(f"[host_loop] mission={mission_name}", flush=True)
            total = len(ss.ship_instances) + len(ss.planet_instances)
            print(f"[host_loop] {total} render instance(s) created "
                  f"({len(ss.ship_instances)} ships, "
                  f"{len(ss.planet_instances)} planets)", flush=True)

        # Per-tick player input → ship-transform integrator.
        # Central action → physical-key map, loaded from Keybindings.cfg (falls
        # back to defaults for missing/unknown entries).  _PlayerControl, the
        # camera handler, the fire/function pollers, and the Configuration →
        # Controls tab all read/edit this single instance.
        from engine.input_map import InputMap
        input_map = InputMap()
        input_map.load()
        player_control = _PlayerControl(input_map)
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
            global _BRIDGE_CAMERA_EYE, _BRIDGE_CAMERA_MOVE
            global _BRIDGE_ZOOM_MIN, _BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_TIME
            import App as _App
            _bridge = _App.g_kSetManager.GetSet("bridge")
            # Documented SDK deviation: LoadBridge.Load (run by the mission's
            # StartMission just before this hook fires) never calls the bridge
            # config module's LoadSounds() -- see engine/bridge_sounds.py for
            # the full account of why we call it ourselves here.
            from engine import bridge_sounds
            bridge_sounds.load_bridge_module_sounds(_bridge)
            _cam = _bridge.GetCamera("maincamera") if _bridge is not None else None
            if _cam is not None and hasattr(_cam, "position"):
                # The seated captain eye is the bridge's pushed camera MODE's
                # BasePosition, NOT the camera's .position. GalaxyBridge pushes a
                # PlaceByDirection mode whose BasePosition (= GetBaseCameraPosition,
                # z=50) is the eye; .position is the ConfigureCharacters override
                # (z=61.93) used only when the mode is popped (cutscenes).
                # Sovereign pushes no mode and base_position == .position.
                _mode = (_cam.GetCurrentCameraMode()
                         if hasattr(_cam, "GetCurrentCameraMode") else None)
                _base = _mode.GetAttrPoint("BasePosition") if _mode is not None else None
                if _base is not None:                  # PlaceByDirection captain mode
                    _BRIDGE_CAMERA_EYE = (_base.x, _base.y, _base.z)
                    _mov = _mode.GetAttrPoint("Movement")
                    if _mov is not None:
                        _BRIDGE_CAMERA_MOVE = ((_mov.x, _mov.y, _mov.z),
                                               _mode.GetAttrFloat("StartMoveAngle"),
                                               _mode.GetAttrFloat("EndMoveAngle"))
                    else:
                        _BRIDGE_CAMERA_MOVE = None
                else:                                  # no mode (e.g. Sovereign)
                    _BRIDGE_CAMERA_EYE = getattr(_cam, "base_position", None) or _cam.position
                    _BRIDGE_CAMERA_MOVE = None
                _BRIDGE_ZOOM_MIN = _cam.GetMinZoom()
                _BRIDGE_ZOOM_MAX = _cam.GetMaxZoom()
                _BRIDGE_ZOOM_TIME = _cam.GetZoomTime()
            # Realize every SDK-created set (the player bridge + any comm/
            # remote sets) into render instances. The bridge is realized as
            # is_bridge=True; comm sets with geometry/characters as False.
            realize_all_sets(controller, r)
            _wire_target_menu_to_player_set(controller)
            # SDK LoadBridge.ConfigureForShip equivalent: attach each bridge
            # officer's menu-acknowledgement handlers (per-character guarded —
            # one station's unimplemented Appc surface must not silence the
            # rest). Must run per load: reset_sdk_globals recreates the TCW,
            # bridge and menus, dropping every prior registration. The whole
            # block lives in engine/bridge_officers so the host-level tests
            # exercise the exact code the live boot runs.
            from engine.bridge_officers import wire_after_mission_load
            wire_after_mission_load()
            # Run the SDK tactical-control-window layout so the officer-menu
            # window resolves an absolute rect (GetScreenOffset). Must run per
            # load: reset_sdk_globals recreates the TCW + panes each swap, and
            # the dev-picker path builds the menus here (no LoadBridge.Load).
            resolve_officer_menu_layout()
            # Re-register the hit-reaction broadcast handler after every
            # reset_sdk_globals() call (swap or initial load). The handler
            # object (_hit_reactions) is swap-safe — it re-fetches player and
            # characters per event via lambdas. Only the registration entry in
            # g_kEventManager._broadcast_handlers is wiped by reset_sdk_globals,
            # so we re-add it here via the persistent wrapper.
            _App.g_kEventManager.AddBroadcastPythonMethodHandler(
                _App.ET_WEAPON_HIT, _hit_wrapper, "on_weapon_hit", None)
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
            # Default stub-observability telemetry ON under --developer so every
            # dev session passively accumulates coverage into stub_hits.jsonl
            # (DAUNTLESS_STUB_TELEMETRY=0 force-disables). See
            # docs/superpowers/specs/2026-07-10-stub-telemetry-accumulation-design.md.
            dev_mode.enable_stub_telemetry()
            _picker_registry_cache: list = [None]
            def _get_mission_registry():
                if _picker_registry_cache[0] is None:
                    from pathlib import Path
                    project_root = Path(__file__).resolve().parent.parent
                    sdk_scripts = project_root / "sdk" / "Build" / "scripts"
                    reg = _missions.discover(sdk_scripts)
                    # Dev-only synthetic family: in-repo preview missions that
                    # don't live under sdk/. The single "." episode is collapsed
                    # by the picker so the mission rows sit directly under
                    # "Developer".
                    from engine.missions import (
                        FamilyEntry, EpisodeEntry, MissionEntry)
                    reg.families.append(FamilyEntry(
                        dir_name="Developer", display_name="Developer",
                        episodes=[EpisodeEntry(
                            dir_name=".", display_name="Developer",
                            missions=[MissionEntry(
                                module_name="engine.dev_missions.damage_preview",
                                dir_name="Damage Preview",
                                display_name="Damage Preview",
                            )],
                        )],
                    ))
                    _picker_registry_cache[0] = reg
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

        # AI Inspector — dev-only live AI-tree inspector modal. Registers its
        # pause-menu row + the panel into `registry` (created below). Done via
        # a helper so the registration is unit-testable; a no-op returning
        # _NULL_PICKER in production. Menu entry must be added before
        # default_pause_menu() snapshots dev_pause_menu_entries(), so the
        # registry is constructed (empty) ahead of the pause menu and gets its
        # legacy handler wired afterwards.
        from engine.ui.panel_registry import PanelRegistry
        registry = PanelRegistry()
        ai_inspector = _register_ai_inspector(registry)

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
            tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay"),
                  ("controls", "Controls")],
            initial_settings=SettingsSnapshot(
                dust_on=True,
                specular_on=True,
                hdr_on=True,
                rim_on=True,
                decals_on=True,
                smaa_on=True,
                shadows_on=True,
                procedural_sky_on=r.procedural_sky_enabled(),
                filmic_on=r.filmic_enabled(),
                motion_blur_on=r.motion_blur_enabled(),
                warp_flythrough_on=r.warp_flythrough_enabled(),
                volumetric_nebulae_on=r.volumetric_nebulae_enabled(),
                nebula_lightning_on=r.nebula_lightning_enabled(),
                hdr_lens_flare_on=r.hdr_lens_flare_enabled(),
                fov_deg=int(round(_math.degrees(
                    director.fov_y_rad
                ))),
                subtitles_on=_crew_speech.subtitles_enabled(),
                disable_annoying_dialogue_on=_crew_speech.annoying_dialogue_disabled(),
                ai_difficulty=App.Game_GetDifficulty(),
            ),
            set_dust=r.set_dust_enabled,
            set_specular=r.set_specular_enabled,
            set_hdr=r.set_hdr_enabled,
            set_rim=r.set_rim_enabled,
            set_decals=r.set_decals_enabled,
            set_smaa=r.set_smaa_enabled,
            set_subtitles=_crew_speech.set_subtitles_enabled,
            set_disable_annoying_dialogue=_crew_speech.set_annoying_dialogue_disabled,
            set_ai_difficulty=App.Game_SetDifficulty,
            set_fov_rad=director.set_fov,
            set_shadows=r.set_shadows_enabled,
            set_procedural_sky=r.set_procedural_sky_enabled,
            set_filmic=r.set_filmic_enabled,
            set_motion_blur=r.set_motion_blur_enabled,
            set_warp_flythrough=r.set_warp_flythrough_enabled,
            set_volumetric_nebulae=r.set_volumetric_nebulae_enabled,
            set_nebula_lightning=r.set_nebula_lightning_enabled,
            set_hdr_lens_flare=r.set_hdr_lens_flare_enabled,
            input_map=input_map,
        )

        # Quick Battle Setup panel — on-theme tabbed-modal shell (Ships tab).
        # Production-visible (NOT dev-only). Boot opens this instead of
        # auto-starting the battle (see the boot_quickbattle block above).
        # The panel's Start drives the proven SP1 start path (start_quickbattle
        # posts ET_START_SIMULATION to g_pXO -> StartSimulation -> ...), using
        # whatever roster the player built via the panel's Add buttons.
        from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel
        quick_battle_setup_panel = QuickBattleSetupPanel(
            on_start=lambda: controller.loader.start_quickbattle())
        controller.quick_battle_setup_panel = quick_battle_setup_panel

        from engine.ui.pause_menu import default_pause_menu
        pause_menu = default_pause_menu(
            on_exit=pause.request_quit,
            on_configuration=configuration_panel.open,
            on_resume=pause.close,
        )
        # `registry` was created earlier (before the pause menu) so dev panels
        # could register their menu rows ahead of the snapshot; wire its legacy
        # handler now that pause_menu exists.
        registry._legacy = pause_menu.dispatch_event
        controller.panel_registry = registry  # expose to _drain_pending_swap
        registry.register(target_list_view)
        registry.register(sensors_panel)
        from engine.appc.sdk_mirror_panel import SDKMirrorPanel
        sdk_mirror = SDKMirrorPanel()
        registry.register(sdk_mirror)
        from engine.ui.setting_course_panel import SettingCoursePanel
        setting_course_panel = SettingCoursePanel(on_course_set=on_course_set)
        from engine.ui.crew_menu_panel import CrewMenuPanel
        crew_menu_panel = CrewMenuPanel(
            on_set_course=setting_course_panel.open,
            on_warp_engage=on_warp_engage)
        registry.register(crew_menu_panel)
        registry.register(setting_course_panel)
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
        registry.register(quick_battle_setup_panel)
        # The panel is NOT opened at boot: the player opens it from the XO
        # menu's "Quick Battle Setup" button (ET_OPEN_DIALOG -> g_bDialogUp=1),
        # which _sync_quick_battle_panel mirrors onto the panel each tick. Boot
        # leaves the player on the bridge (in flight/cursor mode as usual).
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

        # Engineering power-grid panel — live power state: sliders, Power Used
        # bar, column gauges, and tractor/cloak siphon lines.  Always registered
        # (production panel, not dev-only); the panel emits {"visible":False}
        # when there is no player or when the Engineering crew menu is not open.
        from engine.ui.engineering_power_panel import EngineeringPowerPanel
        def _engpower_get_player():
            g = Game_GetCurrentGame()
            return g.GetPlayer() if g is not None else None
        # Resolve the Engineering menu label once (TGL: "Engineering" key in
        # Bridge Menus.tgl; headless fallback returns the key itself).
        try:
            _eng_tgl = App.g_kLocalizationManager.Load(
                "data/TGL/Bridge Menus.tgl")
            _eng_label = str(_eng_tgl.GetString("Engineering"))
            App.g_kLocalizationManager.Unload(_eng_tgl)
        except Exception:
            _eng_label = "Engineering"
        def _engpower_is_engineering_open():
            return crew_menu_panel.open_menu_label() == _eng_label
        engineering_power_panel = EngineeringPowerPanel(
            get_player=_engpower_get_player,
            is_engineering_open=_engpower_is_engineering_open)
        registry.register(engineering_power_panel)

        # Bindings older than the orbit-camera change won't expose
        # consume_scroll_y; fall back to a zero-delta lambda so host_loop
        # still runs against an old _dauntless_host.so without rebuilding.
        _consume_scroll = getattr(_h, "consume_scroll_y", None) if _h else None
        # Newer bindings expose CEF mouse-forwarding + a JS→Python event
        # channel; older builds fall back to no-ops so the pause menu
        # still navigates by keyboard.
        _cef_send_mouse_move  = getattr(_h, "cef_send_mouse_move",  None) if _h else None
        _cef_send_mouse_click = getattr(_h, "cef_send_mouse_click", None) if _h else None
        _cef_send_wheel       = getattr(_h, "cef_send_mouse_wheel", None) if _h else None
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
        # True while a bridge-officer left-click is held (press was intercepted
        # for the crew menu); used to swallow the matching release edge so it
        # never leaks to phaser fire. See the officer-pick block below.
        _bridge_left_pick_active = False
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
                           ship_property_viewer, ai_inspector,
                           configuration_panel, setting_course_panel]

        while not r.should_close():
            # --- Track window resizes: re-lay-out the CEF overlay at the new
            # size so it reflows instead of being stretched. Guarded so
            # WasResized only fires when the logical size or DPR actually
            # changes; _CEF_VIEW_W/H stay authoritative for mouse-forward
            # scaling and the panel-corner layout math below.
            if _cef_resize is not None and _h is not None:
                try:
                    _fbw, _fbh = host_io.framebuffer_size()
                    _wnw, _wnh = host_io.window_size()
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
            # Per-frame cursor + panel-hit state, defaulted so the scroll
            # router (below) always has them defined — even when _h is None
            # or neither mouse-forward branch runs this frame.
            _mx, _my = 0, 0
            _cursor_in_panel = False
            if _h is not None:
                # ESC priority: mission picker first (dev only), then the
                # developer options panel (dev only), then the ship property
                # viewer (dev only), then the configuration panel, then the
                # crew menu, otherwise the pause menu toggle. All four modal
                # blockers close on ESC and return the user to the pause menu.
                # Controls-tab key capture owns the keyboard (incl. Esc) while
                # active; skip the normal modal-ESC dispatch so Esc cancels the
                # capture instead of closing the Configuration panel.
                if configuration_panel.capturing_action is not None:
                    _handle_controls_capture(configuration_panel, _h)
                else:
                    _dispatch_modal_esc(_modal_blockers, crew_menu_panel, pause, _h)
                _apply_pause_menu_side_effects(
                    pause, view_mode, _h, _modal_blockers,
                )
                # Crew menus (F1-F5) are unpaused CEF overlays — free the
                # cursor while one is open so it can be clicked, then re-lock
                # on close. Runs every frame; idempotent + latched.
                _apply_crew_menu_side_effects(
                    crew_menu_panel, view_mode, pause, _h,
                    setting_course_panel,
                    controller.quick_battle_setup_panel)
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
                        if host_io.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, True)
                        if host_io.mouse_button_released(_h.keys.MOUSE_BUTTON_LEFT):
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
                from engine.appc.top_window import TopWindow_GetTopWindow
                _tac_visible = _tactical_hud_visible(
                    is_exterior=view_mode.is_exterior,
                    spv_open=ship_property_viewer.is_open(),
                    cutscene_active=TopWindow_GetTopWindow().IsCutsceneMode())
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
                # Surface 2 of weapons-config: reconcile the equipment-gated
                # weapon/defense command rows on the F2 Tactical menu. Idempotent
                # + raise-safe + early-out when no Tactical menu exists, so it's
                # cheap every tick and self-heals the per-bridge-load rebuild.
                if _player is not None:
                    weapon_tactical_commands.sync(_player)
                # Drop the player's weapon lock the instant its target finishes
                # cloaking: you can't hold a lock on (or fire torpedoes at) a
                # ship you can no longer see. FireWeapons no-ops with no target,
                # so this also silences the player's weapons and clears the
                # reticle. AI ships re-select via SelectTarget; the player has
                # no such preprocessor, so the lock would otherwise persist.
                if _player is not None and hasattr(_player, "GetTarget"):
                    _ptgt = _player.GetTarget()
                    if _ptgt is not None and is_hidden_by_cloak(_ptgt):
                        _player.SetTarget(None)

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
                         or ship_display_target.visible
                         or crew_menu_panel.has_open_menu())
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
                    # Top-right corner (#engpower-root): position:fixed;
                    # top:8px; right:8px; width:540px (v28 redesign — wider
                    # grid + battery pillars). The Engineering power-grid panel
                    # lives here; its rows are only clickable if clicks over
                    # this box reach CEF. Gated on is_showing() (player + power
                    # present + Engineering menu open) so the box doesn't
                    # swallow clicks / phaser fire when the panel is hidden.
                    # Height covers sliders (4×~24px) + grid (~55px) + bgroup
                    # (~140px) + padding — 420px is generous but safe.
                    _TR_W, _TR_H = 540 + 16, 420   # +16 for CSS padding/border
                    _TR_X = _CEF_VIEW_W - 8 - _TR_W
                    _TR_Y = 8
                    _cursor_in_top_right = (
                        engineering_power_panel.is_showing()
                        and _TR_X <= _mx < _TR_X + _TR_W
                        and _TR_Y <= _my < _TR_Y + _TR_H
                    )
                    # The Set Course and Quick Battle Setup modals are
                    # full-viewport cp-* backdrops: any click while one is open
                    # belongs to CEF (a button or the inert backdrop), never to
                    # phaser fire or the bridge view below.
                    _cursor_in_modal = (
                        setting_course_panel.is_open()
                        or controller.quick_battle_setup_panel.is_open()
                    )
                    _cursor_in_panel = (
                        _cursor_in_left_column or _cursor_in_bottom_row
                        or _cursor_in_top_right
                        or _cursor_in_modal
                    )
                    if _cef_send_mouse_click is not None and _cursor_in_panel:
                        if host_io.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, True)
                        if host_io.mouse_button_released(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, False)

            # --- Sim advance: fixed-timestep accumulator ---
            # frame_dt is the real wall-clock since the previous frame.
            # While frozen we force it to 0 so the accumulator cannot
            # grow and there is no catch-up burst on resume. The cap
            # bounds the inner while-loop after a stalled render frame.
            # Frozen = pause menu OR the DevTools window (which stops the
            # world so the overlay under inspection holds still).
            pause.set_external_freeze(_devtools_frozen(_h))
            _now = time.monotonic()
            _frame_dt = _now - _previous_real_time
            _previous_real_time = _now
            if pause.sim_frozen:
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
            _player_dt = 0.0 if pause.sim_frozen else min(max(_frame_dt, 0.0), MAX_FRAME_DT)
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
                    char_anim.reset()
                    walk_ctrl.reset()
                    watch_ctrl.reset()
                    idle_gestures.reset()
                    node_anim.reset(renderer=r)
                    lip_runtime.clear()
                controller._drain_pending_swap()
                if had_pending_swap:
                    director.snap()
                    _xform_buf.reset_all()
            else:
                had_pending_swap = False

            session = controller.session
            # Fire QuickBattle's stored preload-done event (if pending) BEFORE
            # reconciliation. Its handler (StartSimulation2) spawns the player
            # ship; firing first means the reconciliation pass below realizes
            # that ship in the same tick. Fire-once and fully guarded — a no-op
            # for missions that never set a preload-done event.
            _fire_pending_preload_done()
            # Remove SetDeleteMe(1)-flagged objects from their set (QuickBattle
            # "End Combat" clears the battle this way); the reconciliation below
            # then tears down their render instances.
            _process_object_deletions()
            # Mirror the SDK config-dialog flag onto the Quick Battle Setup
            # panel: opens it when the player clicks the XO menu's config
            # button, closes it on Close/Start. Boot leaves it closed.
            _sync_quick_battle_panel(controller)
            # Capture the player ship at combat start; revert to it on End
            # Combat (so a mid-combat ship swap is temporary).
            _sync_quickbattle_player_revert(controller)
            # Per-tick realization reconciliation: realize ships created at
            # RUNTIME (QuickBattle's RecreatePlayer, reinforcement spawns) and
            # tear down ships removed from the set. Also retargets the camera if
            # the player object identity changed (RecreatePlayer destroy+
            # recreate). Runs BEFORE reading session.player below so the new
            # player is followed this same frame. No-op for steady-state
            # missions (all ships present at load) — see
            # _reconcile_runtime_instances. Verbose mirrors loader verbosity.
            if session is not None:
                def _on_player_change(new_player, _d=director, _xb=_xform_buf):
                    # The camera follows session.player (re-read below). Snap so
                    # the new player doesn't lerp from the destroyed ship's pose,
                    # and re-seed the director's ship-radius distances.
                    _r = new_player.GetRadius()
                    _d.chase.set_ship_radius(_r)
                    _d.tracking.set_ship_radius(_r)
                    _d.snap()
                    _xb.reset_all()
                _reconcile_runtime_instances(
                    session, controller.renderer,
                    on_player_change=_on_player_change, verbose=verbose)
            player = session.player if session is not None else None
            if had_pending_swap and player is not None:
                _r = player.GetRadius()
                director.chase.set_ship_radius(_r)
                director.tracking.set_ship_radius(_r)

            # Mouse-wheel routing (runs every frame, paused or not). Scroll
            # delta is consumed once per tick — the single consumer of the
            # accumulator. Over a CEF surface (a pause/config modal is open,
            # or the cursor is over a HUD panel) → scroll that panel; over
            # open space in exterior view → step the ship throttle. Replaces
            # the old camera scroll-zoom. Old bindings without the accumulator
            # return 0.0 via the fallback.
            scroll_y = _consume_scroll() if _consume_scroll is not None else 0.0
            _route_scroll_wheel(
                scroll_y,
                route_to_panel=(pause.is_open or _cursor_in_panel),
                mx=_mx, my=_my,
                send_wheel=_cef_send_wheel,
                player_control=player_control,
                can_throttle=(player is not None and view_mode.is_exterior),
            )

            if not pause.is_open:
                # Dev-mode keybindings (no-op when --developer is not set).
                # register_for_frame re-binds handlers that close over the
                # current player/session each tick; dispatch_dev_key reads
                # _h.key_pressed for every registered key and fires matching
                # handlers. Skipped silently when dev_mode.is_enabled() is False.
                if _h is not None and dev_mode.is_enabled():
                    dev_keybindings.register_for_frame(_h, session, player)
                    for key, _desc in dev_mode.keybinding_descriptions():
                        if host_io.key_pressed(key):
                            dev_mode.dispatch_dev_key(key)

                # F12: toggle CEF DevTools for the UI overlay.
                if _h is not None and host_io.key_pressed(_h.keys.KEY_F12):
                    _h.cef_toggle_devtools()

                # Cmd+R / Ctrl+R: hot-reload the CEF overlay's HTML.
                # Reload only when Cmd (macOS) or Ctrl (Linux/Windows) is held;
                # bare R is reverse-thrust and must not be intercepted.
                if _h is not None and host_io.key_pressed(_h.keys.KEY_R):
                    _cmd_held = host_io.key_state(_h.keys.KEY_LEFT_SUPER) if hasattr(_h.keys, "KEY_LEFT_SUPER") else False
                    _ctrl_held = host_io.key_state(_h.keys.KEY_LEFT_CONTROL) if hasattr(_h.keys, "KEY_LEFT_CONTROL") else False
                    if _cmd_held or _ctrl_held:
                        _h.cef_reload()

            # Everything below is SIMULATION — ship/camera input, firing,
            # weapons, combat, sensors, nebula — so it gates on sim_frozen,
            # not on the menu. The DevTools keys above deliberately sit in the
            # is_open block instead: DevTools freezes the sim, so gating F12 on
            # sim_frozen would make it impossible to press F12 a second time to
            # close DevTools again.
            if not pause.sim_frozen:
                # Apply keyboard input to the player ship's transform and to the
                # orbit camera (see _apply_input below).

                if player is not None and _h is not None:
                    # Alert keys (Shift+1/2/3) run before the throttle handler;
                    # _PlayerControl.apply checks _shift_held() to skip digit
                    # throttling on the same press.
                    _apply_alert_keys(_h, player)
                    # C-key: toggle Chase ↔ Tracking (only enters Tracking if
                    # the player has a valid target). key_pressed fires once per
                    # key-down event (not while held). Gate on exterior view so
                    # the mode cannot flip silently while the bridge is active.
                    if view_mode.is_exterior and host_io.key_pressed(input_map.code("camera_cycle")):
                        director.toggle_mode(player=player)
                    # Z-key: ZoomTarget framing while held. Held-state (not
                    # press-edge) so the camera enters/exits as the key state
                    # changes. The `not director.tracking.zoom_target_active`
                    # retry guard lets a Z-held-during-target-acquisition
                    # succeed on whichever frame the target appears.
                    z_held_now = view_mode.is_exterior and host_io.key_state(input_map.code("camera_zoom_target"))
                    if z_held_now and not director.tracking.zoom_target_active:
                        director.start_zoom_target(player=player)
                    elif z_held_prev and not z_held_now:
                        director.end_zoom_target()
                    z_held_prev = z_held_now
                    # =/- sticky zoom: press-edge (OS auto-repeat for hold).
                    if view_mode.is_exterior and host_io.key_pressed(input_map.code("camera_zoom_in")):
                        director.zoom_in()
                    if view_mode.is_exterior and host_io.key_pressed(input_map.code("camera_zoom_out")):
                        director.zoom_out()
                    # V-key: Reverse Chase while held. Same hold-state
                    # edge detection as Z, with a retry guard so a
                    # V-held-during-mode-transition succeeds on the
                    # next eligible frame.
                    v_held_now = view_mode.is_exterior and host_io.key_state(input_map.code("camera_reverse_chase"))
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
                        mouse_dx_exterior, mouse_dy_exterior = host_io.consume_mouse_delta()
                    shift_held = view_mode.is_exterior and (
                        host_io.key_state(_h.keys.KEY_LEFT_SHIFT) or
                        host_io.key_state(_h.keys.KEY_RIGHT_SHIFT)
                    )
                    if shift_held and director.mode is CameraMode.CHASE:
                        director.chase.apply_mouse_delta(
                            mouse_dx_exterior, mouse_dy_exterior)
                    # dt = _player_dt (wall-clock frame delta), not TICK_DT —
                    # see comment at the accumulator step. _apply_input fires
                    # once per render frame, so its dt is the wall delta.
                    _apply_input(view_mode, player_control, director,
                                 player=player, dt=_player_dt, h=_h)

                # Bridge crew-menu click. On the bridge the cursor is locked for
                # mouse-look, so the player AIMS by looking: the reticle is
                # screen centre.
                #   - No menu open: centre an officer and left-click → open that
                #     officer's crew menu (else the click falls through to
                #     _poll_mouse_buttons and fires phasers).
                #   - Menu open: the cursor is freed for the CEF menu; a click on
                #     the menu itself is consumed earlier by the CEF panel
                #     forwarding, so any left press we still see here is OFF the
                #     menu → close it.
                # mouse_button_pressed consumes the edge, so we only call it once
                # we've decided to intercept — leaving genuine empty-space clicks
                # to fire phasers.
                if view_mode.is_bridge and _h is not None:
                    _bridge_left_pick_active = bridge_officer_picking.handle_click(
                        _h, r, bridge_camera, crew_menu_panel,
                        _bridge_left_pick_active)

                # Forward mouse button edges into the input manager (fire
                # events route via g_kKeyboardBinding → TCW handlers).
                _poll_mouse_buttons(_h)
                _poll_function_keys(_h, input_map)
                _poll_fire_keys(_h, input_map)
                _poll_tractor_toggle(_h)
                _poll_cloak_toggle(_h)
                _poll_skip_dialogue(_h, input_map)

                # Advance weapon charge / reload for every ship in every
                # active set.  Runs after AI/physics (approximate — the host
                # loop is single-threaded and Python AI runs in the gameloop
                # tick above) so emitters are ready when AI fire calls land.
                # Materialize the ship list once per frame — both consumers
                # re-walked every set independently before.
                _ships_this_tick = list(_all_ships_for_tick())
                _advance_weapons(_ships_this_tick, TICK_DT)
                _advance_combat(
                    _ships_this_tick, TICK_DT,
                    ship_instances=(session.ship_instances if session is not None else None),
                )

                # Sensor contact identification → drives the SDK bridge Hail /
                # scan buttons + unlocks target-info panels (all gate on
                # IsObjectKnown). Throttled ~4 Hz; cheap once contacts are known.
                # Sim-gated by the enclosing `not pause.sim_frozen`.
                if player is not None:
                    import App  # deferred: matches host-loop convention
                    global _last_identify_gt
                    _now_gt = App.g_kUtopiaModule.GetGameTime()
                    if (_last_identify_gt is None
                            or _now_gt - _last_identify_gt >= 0.25):
                        _last_identify_gt = _now_gt
                        from engine.appc import sensor_identification
                        sensor_identification.identify_contacts(player)

                # Nebula membership → enter/exit events, environmental
                # damage, sensor scaling. Sim dt (TICK_DT); gated by the
                # enclosing `not pause.sim_frozen` (no effects while frozen);
                # no-op for sets without a nebula.
                _neb_set = _resolve_active_set(player)
                if _neb_set is not None:
                    global _nebula_tracker
                    if _nebula_tracker is None:
                        from engine.appc.nebula_runtime import NebulaTracker
                        _nebula_tracker = NebulaTracker()
                    import App  # deferred: matches host-loop convention
                    _nebula_tracker.update(
                        _neb_set,
                        _neb_set.GetClassObjectList(App.CT_SHIP),
                        TICK_DT,
                    )
                    # Shared nebula-state locals used by ALL nebula drivers
                    # (thunder, hull-discharge, wake).  Computed once here so
                    # each per-toggle block can read them without duplication.
                    player_id = id(player) if player is not None else None
                    in_neb = player_id is not None and any(
                        player_id in ships
                        for ships in _nebula_tracker._inside.values()
                    )
                    _gt = App.g_kUtopiaModule.GetGameTime()

                    # Nebula lightning: tick the thunder driver while the player
                    # is in a nebula.  Visual/audio only; gated by the toggle.
                    # Lazy construct (mirrors _nebula_tracker).
                    global _nebula_thunder
                    if r.nebula_lightning_enabled():
                        if _nebula_thunder is None:
                            from engine.appc.nebula_thunder import NebulaThunderDriver
                            _nebula_thunder = NebulaThunderDriver()
                        fwd = player.GetWorldForwardTG() if player is not None else None
                        fwd_t = (fwd.x, fwd.y, fwd.z) if fwd is not None else (0.0, 1.0, 0.0)
                        _nebula_thunder.update(in_neb, TICK_DT, _gt, fwd_t)
                        for name in _nebula_thunder.pop_due_audio(_gt):
                            try:
                                from engine.audio.tg_sound import TGSoundManager
                                TGSoundManager.instance().PlaySound(name)
                            except Exception:
                                pass
                        # Hull electrical discharges: crackle on the hull while
                        # in a nebula, rate ∝ the nebula's damage.  Gated by
                        # the Nebula Lightning toggle (shared with the flashes).
                        # Lazy construct mirrors _nebula_thunder above.
                        global _hull_discharge
                        if _hull_discharge is None:
                            from engine.appc.hull_discharge import HullDischargeDriver
                            _hull_discharge = HullDischargeDriver()
                        dmg_rate = 0.0
                        hull_pts = []
                        if in_neb and player is not None:
                            pset = player.GetContainingSet()
                            if pset is not None:
                                for obj in pset.GetClassObjectList(App.CT_NEBULA):
                                    neb = App.MetaNebula_Cast(obj)
                                    if neb is not None and neb.IsObjectInNebula(player):
                                        dmg_rate = neb.GetDamage()[0]
                                        break
                            # Anchor sparks across the WHOLE hull (saucer rim,
                            # nacelles, pylons) via the model's surface-point
                            # sample, not just the central subsystem mounts.
                            _piid = (session.ship_instances.get(player)
                                     if session is not None else None)
                            if _piid is not None:
                                hull_pts = r.instance_surface_points(_piid)
                            if not hull_pts:
                                # Fallback: subsystem mounts (central, but better
                                # than nothing) when no surface sample is available.
                                from engine.appc.subsystems import subsystem_world_position
                                for sub in player.GetSubsystems():
                                    wp = subsystem_world_position(sub, player)
                                    hull_pts.append((wp.x, wp.y, wp.z))
                        _hull_discharge.update(in_neb, dmg_rate, TICK_DT, hull_pts, _gt)

                    # Nebula ship wake: record the player's path while in a nebula.
                    # Gated by Volumetric Nebulae ONLY (spec §7: "no cloud → no
                    # wake"), independent of the Nebula Lightning toggle.
                    global _nebula_wake
                    if r.volumetric_nebulae_enabled():
                        if _nebula_wake is None:
                            from engine.appc.nebula_wake import NebulaWakeTracker
                            _nebula_wake = NebulaWakeTracker()
                        _emitters = []
                        if in_neb and player is not None:
                            from engine.appc.subsystems import active_impulse_emitters
                            _emitters = active_impulse_emitters(player)
                        _nebula_wake.update(in_neb, _emitters, _gt)

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
                # Advance BC's warp FSM before collisions: a ship in warp is
                # non-collidable (collisions._collisions_enabled), so a dewarp
                # that completes this frame must be collidable THIS frame, not
                # next. sync_flythrough is the leak guard — once the warp
                # animator is inactive the flythrough ship cannot still read as
                # warping, however the sequence ended.
                from engine.appc import warp_state as _warp_state
                from engine import warp_vfx as _wv_state
                _warp_state.tick_warp_states(_player_dt)
                _warp_state.sync_flythrough(_wv_state.get().is_active())

                collisions.tick_collisions(
                    _player_dt,
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
                        App.g_kUtopiaModule.GetGameTime(), BC_MODEL_SCALE,
                        player_control=player_control)

            # --- Render (always runs, including while paused) ---
            # Camera: orbit + zoom around the player ship (or origin fallback).
            # In-space cutscene camera on the EXPLICITLY-rendered set: when a
            # live valid mode owns the frame, the bridge render pass turns
            # off and the main scene shows the exterior cutscene — even while
            # the bridge flag is set (the player is on the bridge in state
            # but sees the exterior; get_explicit_rendered_set() is the
            # render-target authority; bridge_flag()/GetRenderedSet() are
            # untouched). Reverts when CutsceneCameraEnd pops the mode.
            _cc = None if pause.sim_frozen else _active_cutscene_camera()
            _apply_bridge_pass_state(
                view_mode.is_bridge and _cc is None, _h, view_mode)
            # AT_MOVE walk completion advances the mission TGSequence (E1M1
            # UndockCutscene -> Inspection enables the crew menus), so it must be
            # pumped every unpaused frame regardless of view — NOT inside the
            # is_bridge render block below (that block is purely visual). See
            # _pump_walk_controller.
            _pump_walk_controller(walk_ctrl, r, _player_dt, paused=pause.sim_frozen)
            # The door half of the bridge cutscene pump is likewise
            # view-independent — see _pump_bridge_doors.
            _pump_bridge_doors(cutscene, r, paused=pause.sim_frozen)
            if fixed_camera:
                fixed_radius = player.GetRadius() if player is not None else 1.0
                eye = (0.0, 0.0, CAM_MAX_RADII * fixed_radius)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            elif player is not None:
                eye, target, up_vec = _compute_camera(
                    view_mode, director,
                    player=player, dt=_player_dt)
                # Cutscene camera (computed above) drives the main-scene pose,
                # converting the mode's forward DIRECTION to a look-at POINT.
                if _cc is not None:
                    eye, target, up_vec = _cutscene_pose(_cc[1], _player_dt)
                # Camera shake — apply to the exterior view. The bridge
                # first-person camera below gets its own perturb call
                # against the shared shake state.
                eye, target, up_vec = camera_shake.perturb(eye, target, up_vec)
                # If a cutscene camera path is queued or playing, pull the
                # view back to bridge so the update pump below can reach it.
                if cutscene.has_pending_camera() and not pause.sim_frozen:
                    view_mode.set_bridge()
                if view_mode.is_bridge:
                    import App as _App
                    if not pause.sim_frozen:
                        # CAMERA half only — the door half (_update_doors) is
                        # pumped view-independently above (_pump_bridge_doors).
                        cutscene.update(
                            _player_dt,
                            bridge_camera=bridge_camera,
                            view_mode=view_mode,
                            renderer=r,
                            anim_mgr=_App.g_kAnimationManager,
                        )
                        idle_gestures.update(
                            _player_dt, _live_bridge_characters(),
                            renderer=r, anim_mgr=_App.g_kAnimationManager,
                            controller=char_anim)
                        char_anim.update(
                            _player_dt, renderer=r,
                            anim_mgr=_App.g_kAnimationManager)
                        # walk_ctrl is pumped view-independently above
                        # (_pump_walk_controller) — its completion drives the
                        # mission sequence and must not be gated on bridge view.
                        try:
                            lip_runtime.update()
                        except Exception as _e:
                            dev_mode.log_swallowed("lip-sync update", _e)
                        # node_anim reads node_overrides written by r.frame() above; intentionally one frame behind — do NOT reorder.
                        node_anim.update(r)
                    mouse_dx, mouse_dy = host_io.consume_mouse_delta()
                    # While paused we still drain the accumulated mouse
                    # delta (so it doesn't snap the look on resume) but
                    # skip the yaw/pitch advance so the bridge camera
                    # stays frozen alongside the rest of the world.
                    if not pause.sim_frozen:
                        # Zoom-to-officer still runs while a crew menu is open
                        # (that's what frames the station). But the cursor is
                        # freed to click the menu, so zero the mouse-look delta
                        # — otherwise moving toward a menu row swings the view.
                        # (set_zoom_target's zoom already suspends mouse-look
                        # once an officer resolves; this also covers the case
                        # where no officer resolves and the zoom stays at 0.)
                        # Free-look is also suppressed during a cutscene: the
                        # letterbox pins the view where the mission wants it.
                        from engine.appc.top_window import TopWindow_GetTopWindow
                        _tw = TopWindow_GetTopWindow()
                        if _bridge_freelook_suppressed(
                                crew_menu_open=crew_menu_panel.has_open_menu(),
                                cutscene_active=_tw.IsCutsceneMode(),
                                bridge_cutscene_pending=cutscene.has_pending_camera()):
                            mouse_dx, mouse_dy = 0.0, 0.0
                        _focus = _resolve_bridge_focus_world(
                            watch_ctrl, crew_menu_panel, r)
                        bridge_camera.set_zoom_target(
                            _focus, _player_dt,
                            snap=watch_ctrl.consume_snap())
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
                # Phaser strip (always) + firing-arc (selected) overlay; the
                # Weapon Arcs toggle adds envelopes for EVERY arc weapon.
                from engine.ui.phaser_overlay import build_phaser_overlay
                r.set_spv_overlay_beams(
                    build_phaser_overlay(
                        player,
                        ship_property_viewer.selected_name(),
                        show_all_arcs=ship_property_viewer.show_weapon_arcs)
                )
                # Glow regions as orange wireframe cylinders (debug volume
                # pass): the toggle shows every subsystem's; with it off, a
                # selected subsystem still reveals its own (mirroring the
                # selected-pin firing arc).
                from engine.ui.glow_region_overlay import (
                    build_glow_region_overlay,
                )
                r.set_debug_cylinders(build_glow_region_overlay(
                    player,
                    selected_name=ship_property_viewer.selected_name(),
                    show_all=ship_property_viewer.show_glow_regions))
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
                    r.clear_debug_cylinders()
                    r.set_hologram_only_mode(False, (0.0, 0.0, 0.0))
                    _spv_hidden_iid = None
                r.set_camera(eye=eye, target=target, up=up_vec,
                             fov_y_rad=director.fov_y_rad,
                             near=1.0, far=5000.0)
                # Reticle is an exterior-view HUD element; in bridge view it
                # would draw over the bridge scene. Also hidden during a
                # cutscene started with bHideReticle (BC's clean cinematic
                # frame) — reticle_hidden() folds in the bHideReticle arg so
                # E1M2's bHideReticle=FALSE cutscenes keep it.
                from engine.appc.top_window import TopWindow_GetTopWindow
                if (player is not None and view_mode.is_exterior
                        and not TopWindow_GetTopWindow().reticle_hidden()):
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
            # Realize any comm/remote set that appeared after mission load —
            # E6M2's FedOutpostSet_Graff is built lazily at dock time — so its
            # background geometry + characters render on the viewscreen instead
            # of a black void. Idempotent; before the character visibility sync
            # + RTT below.
            _realize_comm_sets(controller, r)
            # Reveal/hide comm-set characters per their SDK IsHidden() flag
            # (MissionLib.ViewscreenOn un-hides the hailing one) before the RTT
            # renders the set.
            _sync_comm_character_visibility(controller, r)
            _sync_bridge_character_visibility(controller, r)
            # Comm-set feed: if the viewscreen's remote cam belongs to a comm
            # set, render that set into the RTT from its maincamera; otherwise
            # the RTT keeps the forward space view.
            _feed = _active_comm_feed(controller)
            _scene = None
            if _feed is None:
                _scene = _viewscreen_scene_feed(player, director.fov_y_rad)
            _vs_src = _select_viewscreen_source(r, _feed, _scene)
            if _vs_src == "comm":
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
            # Static overlay + ViewOn/ViewOff brightness fade (SDK-driven).
            _vs_ramp = getattr(controller, "_viewscreen_brightness_ramp", None)
            if _vs_ramp is None:
                _vs_ramp = ViewscreenBrightnessRamp()
                controller._viewscreen_brightness_ramp = _vs_ramp
            drive_viewscreen_static_and_brightness(
                r, controller, _vs_ramp, _player_dt)
            _player_iid_vs = (session.ship_instances.get(player)
                              if session is not None and player is not None else None)
            # Use the EFFECTIVE bridge state (same predicate as the bridge
            # render pass): while an in-space cutscene camera owns the frame the
            # player ship IS the subject of the shot and must render, even though
            # the player is on the bridge in state. Without this the hide-on-
            # bridge (so the ship doesn't show on its own viewscreen) leaves the
            # cutscene exterior empty — the ship you're watching is invisible.
            _apply_bridge_player_visibility(
                r, _player_iid_vs,
                is_bridge=view_mode.is_bridge and _cc is None, spv_open=_spv_open)

            # Audio listener (skipped while paused — silence the rumble).
            if not pause.sim_frozen:
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

            if not pause.sim_frozen:
                _update_ui_for_tick(player, view_mode, session, active_set)

            ambient, directionals = _aggregate_lights(active_set)
            if _nebula_thunder is not None and r.nebula_lightning_enabled():
                flashes = _nebula_thunder.active_flashes()
                if flashes:
                    thunder = [((f.dir[0], f.dir[1], f.dir[2]),
                                (f.color[0] * f.intensity, f.color[1] * f.intensity,
                                 f.color[2] * f.intensity)) for f in flashes]
                    keep = max(0, 4 - len(thunder))
                    directionals = list(directionals)[:keep] + thunder[:4]
            r.set_lighting(ambient, directionals)

            bridge_ambient, bridge_directionals = _aggregate_bridge_lights()
            # Red-alert dim: bridge INTERIOR ambient scales to 50% when the
            # player ship is at red alert. Matches BC's red-alert bridge
            # lighting (dimmer overall while the red emergency strip lights
            # pulse — that pulse is deferred work). Sent as a separate scale
            # (not baked into the ambient) so the comm-set viewscreen feed —
            # the other ship's room — keeps constant brightness across alert
            # levels.
            _bridge_dim = 1.0
            if player is not None:
                try:
                    if player.GetAlertLevel() == 2:  # ShipClass.RED_ALERT
                        _bridge_dim = 0.5
                except Exception as _e:
                    dev_mode.log_swallowed("red-alert bridge-dim probe", _e)
            r.set_bridge_ambient_scale(_bridge_dim)
            r.set_bridge_lighting(bridge_ambient, bridge_directionals)
            # BC's NiFlipController observes *game time*, not wall time
            # — controllers advance with g_kTimerManager (which the
            # original engine scaled, instrumentation Q3). Feeding wall
            # time made the LCARS animation play noticeably faster than
            # in stock BC; game time matches the original cadence.
            r.set_bridge_wall_time(App.g_kUtopiaModule.GetGameTime())

            # Age every ship's persistent damage-decal ring on the same game
            # clock used for decal birth_time (engine.appc.damage_decals).
            # damage_decals_tick is a REQUIRED renderer binding (validated at
            # boot), so it is always present — no guard needed.
            r.damage_decals_tick(App.g_kUtopiaModule.GetGameTime())

            # Warp-VFX (Stage 2 — ST dust streak): tick the animator on the GAME
            # clock (App.g_kUtopiaModule.GetGameTime() == g_kTimerManager.get_time(),
            # the SAME clock the WarpSequence's TGSequence delay runs on, so the
            # transit visuals line up with the set swap), then feed the dust pass
            # (streak/flash/travel) and apply the cinematic ship turn. The speed
            # sensation comes from the DUST streaking along travel_dir — the
            # backdrops and local suns/planets aggregate normally (off-parity:
            # non-warp rendering is byte-identical when is_active() is False).
            from engine import warp_vfx as _wv
            _w = _wv.get()
            if _w.is_active():
                _w.tick(App.g_kUtopiaModule.GetGameTime())
                r.set_warp_streak_intensity(_w.streak_intensity())
                r.set_warp_flash_intensity(_w.flash_intensity())
                r.set_warp_travel_dir(_w.travel_dir())
                # Cinematic turn onto the warp heading — but NOT during the exit
                # decel: after arrival the placement owns the ship's orientation,
                # so forcing the warp heading would mis-aim the arrived ship.
                if player is not None and _w.phase() != "exit":
                    _warp_apply_turn(player, _w.turn_fraction(), _w.travel_dir())
                # Ship-speed profile (engine/warp_vfx.ship_speed): cruise at
                # impulse-5 while aligning, ramp up to in-system warp in the last
                # 1s before the burst flash, hold ~still (camera-wise) through the
                # blacked-out transit, then glide warp->0 over 2s as the new
                # system appears. Driven via the _PlayerControl override.
                if player is not None:
                    _nom, _wsp = _warp_phase_speeds(player)
                    player_control._warp_speed_override = _w.ship_speed(_nom, _wsp)
                # Dev diagnostic: track the peaks so we can confirm live that the
                # flash / streak / turn are actually driving (the visuals are
                # exterior-view only; this works from any view).
                global _warp_diag
                _warp_diag["flash"] = max(_warp_diag.get("flash", 0.0), _w.flash_intensity())
                _warp_diag["streak"] = max(_warp_diag.get("streak", 0.0), _w.streak_intensity())
                _warp_diag["turn"] = max(_warp_diag.get("turn", 0.0), _w.turn_fraction())
            else:
                if _warp_diag and dev_mode.is_enabled():
                    print("[warp] peaks: flash=%.2f streak=%.2f turn=%.2f"
                          % (_warp_diag.get("flash", 0.0),
                             _warp_diag.get("streak", 0.0),
                             _warp_diag.get("turn", 0.0)), flush=True)
                _warp_diag = {}
                r.set_warp_streak_intensity(0.0)
                r.set_warp_flash_intensity(0.0)
                _warp_clear_turn()
                player_control._warp_speed_override = None

            # During warp (streak > 0) the LOCAL system is gone (suns + local
            # objects torn down at burst), but the deep-space procedural sky
            # stays — and flies. We re-project it each frame from a vantage that
            # advances along the warp heading (_warp_transit_backdrops), so the
            # distant clusters and nebulae stream past: "moving through the
            # galaxy". During the align beat (active but streak 0) the real
            # system is still shown normally.
            _warp_streaking = _w.is_active() and _w.streak_intensity() > 0.0
            if _warp_streaking:
                backdrops = _warp_transit_backdrops(_w)
            else:
                backdrops = _aggregate_backdrops(active_set)
            r.set_backdrops(backdrops)

            suns = [] if _warp_streaking else _aggregate_suns()
            r.set_suns(suns)

            # In-warp lighting: the system's sun is gone (torn down at burst), so
            # replace the earlier set_lighting() with a cool warp-tunnel key from
            # ahead. Overrides this frame's lighting only while streaking.
            if _warp_streaking:
                _wamb, _wdirs = _warp_transit_lighting(
                    _w.travel_dir(), _w.streak_intensity())
                r.set_lighting(_wamb, _wdirs)

            planets = _aggregate_planets(
                list(App.g_kSetManager._sets.values()))
            r.set_dust_planets(planets)

            nebulae = [] if _warp_streaking else _aggregate_nebulae(active_set)
            r.set_nebulae(nebulae)

            godrays = []
            if _nebula_thunder is not None and not _warp_streaking and r.nebula_lightning_enabled():
                godrays = [{"dir": f.dir, "intensity": f.intensity, "color": f.color}
                           for f in _nebula_thunder.active_flashes()]
            r.set_nebula_godrays(godrays)

            discharges = []
            if (_hull_discharge is not None
                    and r.nebula_lightning_enabled()
                    and not _warp_streaking):
                discharges = _hull_discharge.active_discharges()
            r.set_hull_discharges(discharges)

            wake_pts = []
            if (_nebula_wake is not None and r.volumetric_nebulae_enabled()
                    and not _warp_streaking):
                wake_pts = _nebula_wake.trail_points()
            r.set_nebula_wake(wake_pts)

            # The image-based Modern Lens Flares and the classic per-sun billboard
            # flares are mutually exclusive: when the modern flare is on, suppress
            # the billboards so only the screen-space flare renders.
            lens_flares = [] if r.hdr_lens_flare_enabled() else _aggregate_lens_flares()
            r.set_lens_flares(lens_flares)

            _push_cloak_refraction(r, session, player)

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
