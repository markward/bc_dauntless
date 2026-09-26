"""Warp Stage 1 — the hard-cut warp spine.

WarpSequence_Create builds a TGSequence that (1) loads + switches to the
destination set, (2) moves the player into it at the placement, (3) drops the
source set's render instances and restores player control. The source set
itself is never deleted -- it stands, ready to be re-realized on return.
Renderer realize/teardown is reached via module-level hooks the host
registers; unset hooks make those steps no-ops (headless set/placement logic
still runs). See docs/superpowers/specs/2026-06-22-warp-stage1-hard-cut-design.md.
"""
import math

from engine.appc.actions import TGAction, TGSequence

# Name of the set the player occupies WHILE in warp transit. At burst the
# player is pulled out of the source set into this one (no lights, no
# backdrops, no other ships unless a mission put them there) until the
# destination swap lands, and the source set's RENDER INSTANCES are dropped --
# the set itself stands, it is not deleted. So during transit nothing from the
# system left behind keeps drawing or lighting the scene, but its objects
# still simulate and the set is there to return to.
#
# This is BC's own persistent "warp" set (spec §1b), not an engine-only
# artifact: E6M5/E7M6 load placements into it and queue cutscenes there,
# E6M1-E6M5's PlayerEntersWarpSet handler (ET_ENTERED_SET) creates ships in it
# during the tunnel, and 12 missions test GetName() == "warp" as their
# in-transit guard. It is created on first use and never deleted by the
# tunnel itself -- only MissionLib.DeleteShipsFromWarpSetExceptForMe (a
# mission's own housekeeping) or a mission change clears it.
_WARP_TRANSIT_SET_NAME = "warp"


def WarpSequence_GetWarpSet():
    """BC's warp set: one set named "warp", created on first use and kept.
    E6M5/E7M6 load placements into it (Warp_P.LoadPlacements("warp")) and
    E6M1-E6M5 create ships there on ET_ENTERED_SET; MissionLib.
    DeleteShipsFromWarpSetExceptForMe clears it. Persistent by design
    (spec §1b, HelmMenuHandlers.py:407)."""
    import App
    from engine.appc.sets import SetClass_Create
    s = App.g_kSetManager.GetSet(_WARP_TRANSIT_SET_NAME)
    if s is None:
        s = SetClass_Create()
        App.g_kSetManager.AddSet(s, _WARP_TRANSIT_SET_NAME)
    return s

# Host-registered render hooks: fn(pSet) -> None. None => skip (headless).
_realize_hook = None
_teardown_hook = None
# Optional current-player fallback when App.Game_GetCurrentPlayer() is None.
_player_hook = None


def configure_warp_hooks(realize=None, teardown=None, current_player=None):
    global _realize_hook, _teardown_hook, _player_hook
    _realize_hook = realize
    _teardown_hook = teardown
    _player_hook = current_player


# ── Warp-VFX flythrough (Stage 2) ────────────────────────────────────────────
# Distance-based transit duration. T = clamp(T_MIN, T_MAX, T_BASE + K*dist),
# dist in galaxy-map units between the source and destination system vantages.
# K tuned so a mid-galaxy hop (~150 units) lands ≈ 20 s. Unmapped vantage (None
# on either side) => T_BASE (a short transit, no parallax). Scaled 4× over the
# original (T_MIN/T_MAX/T_BASE/K = 2/10/2/0.02) per live tuning — the streak
# phase reads too brief at the base values.
_T_MIN, _T_MAX, _T_BASE, _K = 8.0, 40.0, 8.0, 0.08

# Align/turn phase: the ship slows + swings onto the warp heading before the
# streak transit begins. The duration is derived from the actual turn angle and
# the ship's impulse-engine max angular velocity (so the turn respects the
# ship's real turn-rate limit — a big swing takes longer than a small one),
# clamped so a near-zero turn still has a brief beat and a 180 isn't endless.
_T_ALIGN_MIN, _T_ALIGN_MAX = 0.5, 8.0
_OMEGA_FALLBACK = 0.5   # rad/s (~29 deg/s) when no impulse subsystem reports one

# When the flash/whoosh occurs inside "Enter Warp.wav" (s from the clip start).
# The clip is 2.65s; the old fixed-1.5s align stayed in sync, so the flash sits
# ~1.5s in. The SFX is started t_align - this so the flash lands on the burst.
# Tunable to the real clip.
_SFX_ENTER_FLASH_AT = 1.5


def _align_duration(ship, heading):
    """Seconds to swing onto `heading` at the ship's max angular velocity."""
    try:
        fwd = ship.GetWorldRotation().GetCol(1)
        dot = fwd.x * heading[0] + fwd.y * heading[1] + fwd.z * heading[2]
    except Exception:
        return _T_ALIGN_MIN
    dot = -1.0 if dot < -1.0 else (1.0 if dot > 1.0 else dot)
    angle = math.acos(dot)            # radians, 0..pi
    omega = 0.0
    try:
        ies = ship.GetImpulseEngineSubsystem()
        if ies is not None:
            omega = ies.GetMaxAngularVelocity()
    except Exception:
        omega = 0.0
    if omega <= 1e-4:
        omega = _OMEGA_FALLBACK
    # The manager eases the turn with a smoothstep (peak rate ~1.5x the mean),
    # so stretch the window by 1.5 to keep the PEAK turn rate <= omega.
    t = 1.5 * angle / omega
    return _T_ALIGN_MIN if t < _T_ALIGN_MIN else (_T_ALIGN_MAX if t > _T_ALIGN_MAX else t)

# Host-registered VFX hooks (None => instant Stage-1 path, headless-safe).
_vfx_start = None         # start(heading, t_align, t_transit, vantage, dst_vantage)
_vfx_stop = None          # stop()
_vfx_enabled = None       # () -> bool  (toggle AND renderer AND procedural sky)
_vfx_vantage_of = None    # (set_or_module) -> (x, y, z) | None


def configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None):
    global _vfx_start, _vfx_stop, _vfx_enabled, _vfx_vantage_of
    _vfx_start, _vfx_stop, _vfx_enabled, _vfx_vantage_of = (
        start, stop, enabled, vantage_of)


def _transit_duration(src_vantage, dst_vantage):
    """Distance-scaled transit length (s). Either vantage None => T_BASE."""
    if src_vantage is None or dst_vantage is None:
        return _T_BASE
    dx = dst_vantage[0] - src_vantage[0]
    dy = dst_vantage[1] - src_vantage[1]
    dz = dst_vantage[2] - src_vantage[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    t = _T_BASE + _K * dist
    return _T_MIN if t < _T_MIN else (_T_MAX if t > _T_MAX else t)


def _warp_heading(src_vantage, dst_vantage):
    """Normalized galaxy-map direction toward the destination system. The source
    set is often NOT galaxy-mapped (mission sets aren't in the sector model), so
    a None source is treated as the galaxy origin — the ship still turns toward
    the real destination direction. Only a missing/zero destination falls back to
    default ship-forward (0, 1, 0)."""
    if dst_vantage is None:
        return (0.0, 1.0, 0.0)
    sx, sy, sz = src_vantage if src_vantage is not None else (0.0, 0.0, 0.0)
    dx = dst_vantage[0] - sx
    dy = dst_vantage[1] - sy
    dz = dst_vantage[2] - sz
    m = math.sqrt(dx * dx + dy * dy + dz * dz)
    return (0.0, 1.0, 0.0) if m < 1e-6 else (dx / m, dy / m, dz / m)


class _WarpSoundAction(TGAction):
    """Play a registered 2D/3D SFX by name (enter/exit warp). Fail-open: a
    missing sound / absent manager never blocks the warp chain."""

    def __init__(self, name):
        super().__init__()
        self._name = name

    def _do_play(self):
        try:
            import App
            App.g_kSoundManager.PlaySound(self._name)
        except Exception:
            pass


def _clear_all_targets(ship) -> None:
    """Drop the player's target + subsystem lock the instant warp engages.

    The target LIST needs no clearing: it is derived from the player's
    containing set, which mid-warp is BC's persistent "warp" set (spec §1b) --
    empty unless a mission has parked ships there (E6M1's Artrus ships), in
    which case the list lists them, as BC's would. Either way it repopulates
    from the destination on arrival. Fail-open: a failure here never blocks
    the warp.

    ⚠️ THIS IS THE ENGAGE-TIME CLEAR, AND IT DOES NOT STICK ON ITS OWN. It is
    ours, not BC's -- BC clears on ARRIVAL (PostWarpEnableMenu). Read
    `_ArrivalClearTargetsAction`, which is the one that holds, before deleting
    either as a duplicate of the other.
    """
    try:
        if ship is not None:
            if hasattr(ship, "SetTarget"):
                ship.SetTarget(None)
            if hasattr(ship, "SetTargetSubsystem"):
                ship.SetTargetSubsystem(None)
    except Exception:
        pass
    try:
        from engine.appc.target_menu import STTargetMenu_GetTargetMenu
        menu = STTargetMenu_GetTargetMenu()
        if menu is not None:
            menu.ClearPersistentTarget()
    except Exception:
        pass


def _stand_down_player_ai(ship) -> None:
    """Drop the player's bridge-officer AI: the Helm has the conn for the warp.

    ⚠️ MUST RUN AFTER `_clear_all_targets`, NOT BEFORE — the order is the whole
    point. Clearing the target posts ET_TARGET_WAS_CHANGED synchronously, and
    the SDK handler `Bridge.TacticalMenuHandlers.TargetChanged` responds by
    calling `UpdateOrders` -> `StartAI`, which BUILDS A FRESH ATTACK AI. Stand
    down first and that rebuild simply undoes it.

    Without this, an attack AI ordered before the warp keeps running for the
    whole align + transit, and its `SelectTarget` re-acquires the enemy one
    frame after the engage clear (via `AutoTargetChange` — see
    `_ArrivalClearTargetsAction` for the full chain). Live-reported 2026-09-07:
    the reticle, the target ship-display panel and the range/speed readouts all
    stayed on the ship being left behind for the entire warp.

    Same operation, and the same SDK justification, as
    `host_loop._PlayerControl._cancel_player_ai` (manual input overrides the
    current order) — `MissionLib.SetPlayerAI(ctrl, None)` is
    `pPlayer.ClearAI()` plus a controller update, done directly so this module
    never imports MissionLib. The controller is reset to **None, not "Helm"**:
    `TacticalMenuHandlers.GetOrderString` returns None for any controller
    outside `(None, "Tactical")`, so parking it on "Helm" would leave Tactical
    unable to take orders after the warp.

    Felix is not stood down permanently — `g_iOrderState` is untouched, so the
    next `UpdateOrders` restores him, which the player's first target pick in
    the destination system triggers through the same TargetChanged path.
    """
    if ship is None:
        return
    if hasattr(ship, "ClearAI"):
        ship.ClearAI()
    import sys
    ml = sys.modules.get("MissionLib")
    if ml is not None and hasattr(ml, "g_sPlayerShipController"):
        ml.g_sPlayerShipController = None


class _ClearTargetsAction(TGAction):
    """Drop every target at warp engage. Runs on BOTH the flythrough and the
    instant hard-cut path (added first in each), so the target list is empty
    the instant warp begins regardless of the Modern-VFX toggle. Fail-open.

    Also stands the player's AI down, which is what makes the clear HOLD for
    the transit rather than survive a single frame — see
    `_stand_down_player_ai`, whose ordering after the clear is load-bearing."""

    def __init__(self, ship):
        super().__init__()
        self._ship = ship

    def _do_play(self):
        _clear_all_targets(self._ship)
        try:
            _stand_down_player_ai(self._ship)
        except Exception as _e:
            from engine import dev_mode
            dev_mode.log_swallowed("stand down player AI for warp", _e)


class _ArrivalClearTargetsAction(TGAction):
    """Drop the target AGAIN on arrival — BC's clear, and the one that holds.

    Ported from the second half of `PostWarpEnableMenu`
    (Bridge/HelmMenuHandlers.py:939-948), which stock BC schedules at the end
    of its warp sequence (WarpSequence.py:324) and comments: "Clear the
    player's target, and the persistent target info in the target menu, so
    that we don't retarget the same thing when we return to the old set (or if
    the object follows us to the new set)." We had ported that function's
    menu-enable half as `_EnableHelmMenuAction` and left this half behind.

    WHY THE ENGAGE-TIME `_ClearTargetsAction` IS NOT ENOUGH, and why deleting
    this as a duplicate of it re-opens a reported bug: clearing at engage posts
    ET_TARGET_WAS_CHANGED, whose SDK handler
    `Bridge.TacticalMenuHandlers.TargetChanged` runs `UpdateOrders` ->
    `StartAI`. That rebuilds the player's AI from a still-live Tactical attack
    order, reading `GetTarget()` — now None — so the new `SelectTarget` starts
    with no target. On its next update the player is STILL IN THE SOURCE SET
    (the flythrough align phase lasts seconds), so it re-picks the same enemy
    and pushes it back via `AutoTargetChange`, which is gated only on the
    "Target At Will" button that `CreateTacticalMenu` builds SetChosen(1) — on
    by default. The player then arrived in the new system still targeting a
    ship left behind in the source set: the reticle and tracking
    camera stayed welded to it while the target list, being derived from the
    current set, could not list it, so it could be neither selected nor cycled
    away from.

    Clearing HERE is immune to that race by construction rather than by
    timing: the player is already in the destination set, so every name the AI
    can push resolves against the new system or resolves to nothing.

    Added only on the branches that perform a REAL warp — a falsy destination
    degrades to "nothing happened", and a no-op warp must not eat the target.
    """

    def __init__(self, ship):
        super().__init__()
        self._ship = ship

    def _do_play(self):
        _clear_all_targets(self._ship)


class _EnableHelmMenuAction(TGAction):
    """Restore the Helm menu on arrival — the counterpart to the
    `disable_helm_menu()` that `warp_button.engage` performs at engage time.

    BC's equivalent is PostWarpEnableMenu (Bridge/HelmMenuHandlers.py:918),
    which stock BC schedules into its own warp sequence at
    WarpSequence.py:324. This sequence is ours, so the scheduling is explicit.

    ⚠️ THIS IS ONLY PostWarpEnableMenu's FIRST HALF. Its second half clears the
    player's target, and lives here as `_ArrivalClearTargetsAction` — split out
    because that half must NOT run on a no-op warp, while this half must.

    Added UNCONDITIONALLY on both branches, deliberately outside the
    `_module_is_empty` guards: a falsy destination degrades the hard-cut path
    to "nothing happened", but the menu was already disabled at engage time,
    so a path that skips the re-enable leaves it dead for the session."""

    def __init__(self):
        super().__init__()

    def _do_play(self):
        from engine.bridge_officers import enable_helm_menu
        enable_helm_menu()


class _WarpVfxBeginAction(TGAction):
    """Align start: remove player control, slow the ship to a stop, and start
    the WarpVFX manager on the warp heading. Targets are cleared by the separate
    _ClearTargetsAction (added alongside this one). Every step is fail-open — a
    failure here never blocks the set-swap chain (control is restored on arrival
    by _ArriveFinalizeAction regardless)."""

    def __init__(self, ship, heading, t_align, t_transit, vantage=None,
                 dst_vantage=None):
        super().__init__()
        self._ship = ship
        self._a = (heading, t_align, t_transit, vantage, dst_vantage)

    def _do_play(self):
        try:
            import MissionLib
            MissionLib.RemoveControl()
        except Exception:
            pass
        # Enter BC's warp FSM. This is the state BC's own scripts read
        # (WarpSequence.py:638, HelmMenuHandlers.py:2465), and it is what makes
        # the ship non-collidable for the flight (collisions._collisions_enabled).
        try:
            from engine.appc import warp_state
            from engine.appc.subsystems import WarpEngineSubsystem
            warp_state.begin_flythrough(self._ship)
            warp_state.set_state(self._ship, WarpEngineSubsystem.WES_WARP_INITIATED)
        except Exception:
            pass
        # Ship motion during warp is driven by the host's _PlayerControl warp
        # speed profile — a ship-level SetSpeed here is inert for the player and
        # is intentionally omitted.
        if _vfx_start is not None:
            try:
                _vfx_start(*self._a)
            except Exception:
                pass


class _WarpVfxEndAction(TGAction):
    """Defensive late-stop for the WarpVFX manager. The manager self-deactivates
    after its post-arrival decel tail (the host drives the speed glide-down to 0
    over those final seconds); this action is scheduled to fire just after the
    tail as a belt-and-suspenders stop. Fail-open.

    Takes the ship this sequence belongs to and releases only THAT ship's
    flythrough registration — the registry can hold more than one ship at
    once (e.g. an NPC warping out mid-align alongside the player), and
    releasing everyone here would clear a still-in-flight ship's state early.
    """

    def __init__(self, ship):
        super().__init__()
        self._ship = ship

    def _do_play(self):
        if _vfx_stop is not None:
            try:
                _vfx_stop()
            except Exception:
                pass
        # Leave the warp FSM: the decel tail is done, the ship is back at
        # impulse, and it becomes collidable again.
        try:
            from engine.appc import warp_state
            warp_state.end_flythrough(self._ship)
        except Exception:
            pass


class _MissionChangePoint(TGAction):
    """The point in transit, after the after-during queue, where a
    cross-mission warp changes mission (spec §2). A name equal to the current
    one -- or a change a direct load already made (E5M4) -- is a no-op."""

    def __init__(self, seq):
        super().__init__()
        self._seq = seq

    def _do_play(self):
        mission = self._seq.GetDestinationMission()
        episode = self._seq.GetDestinationEpisode()
        if mission or episode:
            from engine.core import mission_change
            mission_change.change(mission=mission, episode=episode)


class _HoldUntilAction(TGAction):
    """Completes no earlier than the start of the nominal transit's exit
    flash (sequence start + t_align + 0.9 * t_transit), so a transit whose
    queues finish early still lasts its full length -- the swap follows the
    release 0.1 * t_transit later, at transit end under the flash. Completes
    at once when that deadline has already passed -- a queue or the master
    sequence ran long and the streak has been held (spec §1 "Transit holds").
    Game time, via g_kTimerManager, like TGSequence's own step delays."""

    def __init__(self, seq, t_align, t_transit):
        super().__init__()
        self._seq = seq
        self._span = float(t_align) + 0.9 * float(t_transit)

    def Play(self):
        import App
        self._playing = True
        start = self._seq._t_start
        now = App.g_kUtopiaModule.GetGameTime()
        # A sequence never Play()ed has no start: fail open to an early swap.
        remaining = 0.0 if start is None else start + self._span - now
        # <= 0 completes inline; otherwise a game-time timer (Abort cancels).
        self._complete_after(remaining, mgr=App.g_kTimerManager)


class _TransitReleaseAction(TGAction):
    """End the transit hold: the WarpVFX resumes with its exit flash to play.
    Releases iff _WarpDepartAction took the hold (seq._vfx_held). Fail-open,
    like _WarpVfxBeginAction -- never blocks the swap."""

    def __init__(self, seq):
        super().__init__()
        self._seq = seq

    def _do_play(self):
        if not self._seq._vfx_held:
            return
        self._seq._vfx_held = False
        try:
            import App
            from engine import warp_vfx
            warp_vfx.get().release(App.g_kUtopiaModule.GetGameTime())
        except Exception:
            pass


def _module_is_empty(module):
    """True when there's no destination module to load (None / empty /
    whitespace). Mirrors BC's `if pcDestModule != None:` guard in
    WarpSequence.SetupSequence — a falsy destination means 'no set change'."""
    return module is None or not str(module).strip()


def _set_name_from_module(module):
    """'Systems.Vesuvi.Vesuvi4' -> 'Vesuvi4' (mirrors WarpSequence.py)."""
    if _module_is_empty(module):
        return None
    s = str(module).strip()
    return s[s.rfind(".") + 1:] if "." in s else s


class ChangeRenderedSetAction(TGAction):
    """Load (if needed) and switch the rendered set. Faithful to BC's
    ChangeRenderedSetAction_Create(module) / _CreateFromSet(set)."""

    def __init__(self, module=None, pSet=None):
        super().__init__()
        self._module = module
        self._set = pSet

    def _do_play(self):
        import App
        pSet = self._set
        if pSet is None:
            # No explicit set AND no module to load => no set change (no-op).
            # Mirrors BC's `if pcDestModule != None:` guard. A non-empty module
            # that fails to import/register still raises below (fail loud).
            if _module_is_empty(self._module):
                return
            name = _set_name_from_module(self._module)
            pSet = App.g_kSetManager.GetSet(name)
            if pSet is None:
                # Lazy-load: import the region module and Initialize() it.
                # Fail loud — a bad module raises here.
                import importlib
                mod = importlib.import_module(self._module)
                mod.Initialize()
                pSet = App.g_kSetManager.GetSet(name)
                if pSet is None:
                    raise RuntimeError(
                        "warp: module %r Initialize() did not register set %r"
                        % (self._module, name))
        App.g_kSetManager.MakeRenderedSet(pSet.GetName())
        if _realize_hook is not None:
            _realize_hook(pSet)


def ChangeRenderedSetAction_Create(module):
    return ChangeRenderedSetAction(module=module)


def ChangeRenderedSetAction_CreateFromSet(pSet):
    return ChangeRenderedSetAction(pSet=pSet)


class _PlacePlayerAction(TGAction):
    """Move the player ship from its source set into the destination set and
    position it at the named placement."""

    def __init__(self, ship, dest_name, placement):
        super().__init__()
        self._ship = ship
        self._dest_name = dest_name
        self._placement = placement

    def _do_play(self):
        import App
        ship = self._ship
        # No destination set (e.g. None warp destination) => nothing to move
        # the player into. Degrade to a no-op: leave the ship where it is.
        if not self._dest_name:
            return
        dest = App.g_kSetManager.GetSet(self._dest_name)
        if dest is None:
            return
        # Remove from whatever set currently holds it.
        for s in list(App.g_kSetManager._sets.values()):
            if s.GetObject(ship.GetName()) is ship:
                s.RemoveObjectFromSet(ship.GetName())
        dest.AddObjectToSet(ship, ship.GetName())
        ship.PlaceObjectByName(self._placement)

        # Warp arrival velocity: EXACTLY ZERO. The ship arrives at rest.
        #
        # BC derives velocity by one of three rules during drop-out, and at
        # completion the not-warping entry action sets velocity to the ZERO
        # VECTOR. Established, not assumed: 243 reads of that vector, one
        # write, all three components zeroed.
        #
        # ⚠️ This replaced a WRONG implementation (2026-08-09) that preserved
        # the commanded throttle and re-aimed it along the placement's new
        # facing. That was a chosen default adopted because the reference could
        # not then reach the answer — and it was not what BC does. Do not
        # reintroduce it because arriving at rest feels worse to fly.
        #
        # Before either version, NOTHING set velocity here at all: whatever
        # vector the ship carried in survived the teleport.
        from engine.appc.math import TGPoint3
        if hasattr(ship, "SetVelocity"):
            ship.SetVelocity(TGPoint3(0.0, 0.0, 0.0))


def _silence_ship_weapons(ship):
    """Stop any looping weapon-fire SFX on a ship's weapon banks.

    Energy banks (phaser/pulse) start a looped _PlayingSound on Fire() and stop
    it in StopFiring(). Warping out doesn't go through the normal cease-fire, so
    a mid-fire bank would loop forever in the new system. Walk each weapon
    system's child banks and StopFiring() any that expose it.

    Ship-only. Both callers hand us every member of the source set — waypoints,
    light placements and planets included — and only a ShipClass carries weapon
    systems. isinstance, NOT hasattr: TGObject.__getattr__ returns a truthy
    _Stub for any missing engine method, so the four getters (and the
    GetNumChildSubsystems probe on each result) were called on every inert set
    member on every warp. That is the whole of heatmap ranks 25-28 / 40-43 /
    53-56 / 78-81 / 99-102 / 115-118."""
    from engine.appc.ships import ShipClass
    if not isinstance(ship, ShipClass):
        return
    for getter in ("GetPhaserSystem", "GetPulseWeaponSystem",
                   "GetTorpedoSystem", "GetTractorBeamSystem"):
        get = getattr(ship, getter, None)
        if not callable(get):
            continue
        try:
            wsys = get()
        except Exception:
            continue
        if wsys is None or not hasattr(wsys, "GetNumChildSubsystems"):
            continue
        try:
            n = wsys.GetNumChildSubsystems()
        except Exception:
            continue
        for i in range(n):
            bank = wsys.GetChildSubsystem(i)
            stop = getattr(bank, "StopFiring", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass


class _WarpDepartAction(TGAction):
    """Fires at BURST (transit start): drop the render instances of the system
    being left behind. The set itself is NOT deleted -- BC never deletes a set
    on warp.

    Silences every source-set ship's weapon loops, moves the player into BC's
    persistent warp set (get-or-create; never recreated, so a mission's own
    placements/ships already parked there survive), makes that the rendered
    set (so lighting + backdrops fall to neutral — the source sun stops
    lighting the scene), and tears down the source set's render instances
    only (its objects keep existing and the set stands, ready to be
    re-realized on return). The held destination swap still lands at
    transit-end.

    Fail-open: each step is guarded, and _ArriveFinalizeAction repeats the
    render teardown on arrival anyway (idempotent) if departure didn't
    complete.

    `hard_cut`: the no-flythrough warp's departure. It parks the ship in the
    warp set all the same -- a mission change carries only the warp set's
    occupant, and missions script "entered warp" (E6M1 PlayerEntersWarpSet
    creates the Artrus ships there) -- but sets no WES_WARPING, which only the
    flythrough's _WarpVfxEndAction clears, and for an NPC touches nothing the
    player sees (no rendered-set change, no teardown, no silencing)."""

    def __init__(self, source_set, ship, seq=None, hard_cut=False):
        super().__init__()
        self._source = source_set
        self._ship = ship
        self._seq = seq     # records whether we took the WarpVFX hold
        self._hard_cut = hard_cut

    def _do_play(self):
        import App
        src = self._source
        ship = self._ship
        # Whether this departure changes the player's scene.
        scene = not self._hard_cut or _is_current_player(ship)
        # Burst: the ship is now at warp.
        if not self._hard_cut:
            try:
                from engine.appc import warp_state
                from engine.appc.subsystems import WarpEngineSubsystem
                warp_state.set_state(ship, WarpEngineSubsystem.WES_WARPING)
            except Exception:
                pass
        # 1. Silence looping weapon SFX on every source-set ship (incl. the
        #    player) before its render instances are torn down — otherwise a
        #    bank firing at the moment of warp loops on into transit / the new
        #    system.
        if scene and src is not None:
            for obj in list(getattr(src, "_objects", {}).values()):
                _silence_ship_weapons(obj)
        # 2. Park the player in BC's persistent warp set and render that, so
        #    the lighting/backdrop aggregation (which keys off the
        #    rendered/player set) yields neutral defaults instead of the
        #    source system's sun. The warp set is get-or-create -- it is
        #    never recreated, so a mission's placements/ships already parked
        #    there (spec §1b) survive departure.
        try:
            transit = WarpSequence_GetWarpSet()
            if ship is not None:
                for s in list(App.g_kSetManager._sets.values()):
                    if s.GetObject(ship.GetName()) is ship:
                        s.RemoveObjectFromSet(ship.GetName())
                transit.AddObjectToSet(ship, ship.GetName())
            if scene:
                App.g_kSetManager.MakeRenderedSet(_WARP_TRANSIT_SET_NAME)
        except Exception:
            pass
        # The streak holds at its plateau until _TransitReleaseAction: the
        # swap now waits on the queues and the master sequence (spec §1).
        # Player only -- the WarpVFX singleton is the player's tunnel, and an
        # NPC warp must not freeze it. Only with a sequence, whose
        # _TransitReleaseAction is what lets go again.
        if self._seq is not None and _is_current_player(ship):
            try:
                from engine import warp_vfx
                warp_vfx.get().hold()
                self._seq._vfx_held = True
            except Exception:
                pass
        # 3. Drop the source set's RENDER instances. The set itself stands:
        #    departure is not a lifetime operation. BC's region modules delete
        #    a set only in Terminate(), which nothing calls; the bound is the
        #    mission change (host_loop's _sets.clear()). Returning to this set
        #    re-realizes it through _realize_hook.
        if scene and src is not None and _teardown_hook is not None:
            try:
                _teardown_hook(src)
            except Exception:
                pass


class _ArriveFinalizeAction(TGAction):
    """Silence weapon-fire loops, drop the source set's render instances (if
    departure did not already), and return player control. Neither the
    source set nor the (persistent) warp set is deleted here. Idempotent
    w.r.t. the render teardown so it is safe whether or not
    _WarpDepartAction already ran it."""

    def __init__(self, source_set, ship=None):
        super().__init__()
        self._source = source_set
        self._ship = ship

    def _do_play(self):
        import App
        src = self._source
        # Arrival: the exit-decel glide starts now, so the ship is dewarping —
        # still non-collidable until the animator finishes and _WarpVfxEndAction
        # clears the state. On the hard-cut path there is no flythrough ship
        # registered, so this correctly stays a no-op.
        try:
            from engine.appc import warp_state
            from engine.appc.subsystems import WarpEngineSubsystem
            if self._ship is not None and warp_state.is_flythrough(self._ship):
                warp_state.set_state(self._ship, WarpEngineSubsystem.WES_DEWARP_ENDING)
        except Exception:
            pass
        # Silence looping weapon SFX before we leave: the warping ship (which
        # has already moved to the destination) plus every ship left behind in
        # the source set, whose RENDER INSTANCES are about to be torn down (the
        # set itself stands). Otherwise a phaser fired at the moment of warp
        # loops forever in the new system.
        _silence_ship_weapons(self._ship)
        if src is not None:
            for obj in list(getattr(src, "_objects", {}).values()):
                _silence_ship_weapons(obj)
        # Drop the source set's render instances if departure did not (the
        # instant path has no departure). The set itself stands -- see
        # _WarpDepartAction step 3.
        if src is not None and App.g_kSetManager.GetSet(src.GetName()) is src:
            if App.g_kSetManager.get_explicit_rendered_set() is not src:
                if _teardown_hook is not None:
                    _teardown_hook(src)
        # The warp set itself is never deleted here -- it is BC's persistent
        # "warp" set (spec §1b): a mission's placements/ships parked there
        # survive arrival, and only MissionLib.DeleteShipsFromWarpSetExceptForMe
        # or a mission change clears it.
        # Undo SDK WarpPressed's RemoveControl (no-op if MissionLib absent).
        try:
            import MissionLib
            MissionLib.ReturnControl()
        except Exception:
            pass


class WarpSequence(TGSequence):
    def __init__(self, ship, dest_module, warp_time, placement, mission=None, episode=None, queues=None):
        super().__init__()
        self._ship = ship
        self._dest_module = dest_module
        self._warp_time = float(warp_time)
        self._placement = placement
        # Mission and episode names are carried from the warp button's
        # SetDestination call, which records the button's mission/episode
        # context so that cross-mission warps later have the context they need.
        self._dest_mission = mission or None
        self._dest_episode = episode or None
        # The five action queues from the button (BC SDK App.py:8723-8738),
        # played at their points by WarpSequence_Create (spec §1).
        self._queues = queues or {k: [] for k in ("before", "before_during", "during", "after_during", "after")}
        self._t_start = None    # game time of Play(); _HoldUntilAction's origin
        self._vfx_held = False  # _WarpDepartAction held the WarpVFX

    def GetShip(self):          return self._ship
    def GetDestination(self):   return self._dest_module
    def GetPlacementName(self):  return self._placement

    def _warp_engine(self):
        ship = self._ship
        get = getattr(ship, "GetWarpEngineSubsystem", None)
        return get() if callable(get) else None

    def Play(self) -> None:
        # Attach BEFORE the actions start so a ConditionWarpingToSet created
        # mid-warp (SetupInitialState reads GetWarpSequence) sees us, and so
        # SetWarpSequence's ET_SET_WARP_SEQUENCE ping reaches the ones that
        # already exist. spec #8: nothing called SetWarpSequence in production.
        engine = self._warp_engine()
        if engine is not None:
            engine.SetWarpSequence(self)
        # _HoldUntilAction measures the nominal transit from here.
        import App
        self._t_start = App.g_kUtopiaModule.GetGameTime()
        super().Play()

    def Completed(self) -> None:
        super().Completed()
        # Stated assumption: BC clears the sequence on arrival. The same
        # ping fires, so the condition re-reads None and turns off.
        self._detach_from_engine()

    def Abort(self) -> None:
        # An aborted warp must not leave ConditionWarpingToSet reading
        # "warping" forever -- mirror Completed()'s detach.
        super().Abort()
        self._detach_from_engine()

    def _detach_from_engine(self) -> None:
        """Clear the engine's warp sequence, but only if it's still us --
        never clobber a newer sequence that has since attached."""
        engine = self._warp_engine()
        if engine is not None and engine.GetWarpSequence() is self:
            engine.SetWarpSequence(None)

    # ── Cross-mission / cross-episode destination ────────────────────────────
    # BC's WarpSequence can target a new mission or episode as well as a new
    # set (WarpSequence_GetDestinationMission 0x0061f7a0,
    # _GetDestinationEpisode 0x0061f810), set via SetEventDestination.
    #
    # Dauntless only ever builds SET warps -- WarpSequence_Create takes a
    # dest_module and nothing writes a mission or episode -- so both are
    # legitimately empty here. They must still EXIST and return a real falsy
    # value: Conditions/ConditionWarpingToMission.py:23 does
    #     if pWarpSequence and (GetDestinationMission() or GetDestinationEpisode())
    # and a missing attribute resolves to a TRUTHY _Stub, which made that
    # condition fire for every warp in the game (heatmap rank 95).
    #
    # When cross-mission warp is built, store the target here rather than
    # reintroducing the stub.
    def GetDestinationMission(self):  return self._dest_mission
    def GetDestinationEpisode(self):  return self._dest_episode


def WarpSequence_Cast(obj):
    """SWIG downcast. Returns the object if it IS a WarpSequence, else None.

    Load-bearing for the warp conditions: both
    Conditions/ConditionWarpingToSet.CheckState and .SequenceSet wrap
    GetWarpSequence() in this cast and then branch on `if pWarpSequence`.
    Undefined, it resolved to a truthy _Stub, so a ship with NO warp sequence
    still tested as warping (heatmap rank 62 -- 286 hits, the single
    highest-traffic name in this gap).
    """
    return obj if isinstance(obj, WarpSequence) else None


def WarpSequence_Create(ship, dest_module, warp_time=0.0, placement="Player Start", mission=None, episode=None, queues=None):
    import App
    seq = WarpSequence(ship, dest_module, warp_time, placement, mission=mission, episode=episode, queues=queues)
    dest_name = _set_name_from_module(dest_module)
    # Capture the source set NOW (before the player is moved).
    source = None
    for s in App.g_kSetManager._sets.values():
        if s.GetObject(ship.GetName()) is ship:
            source = s
            break
    # Stage 2 timed flythrough: only when the flythrough is live (toggle AND
    # renderer AND procedural sky, via the host predicate) AND there's a real
    # destination to fly to. The set swap is HELD until the transit ends AND
    # the in-transit queues / master sequence finish (spec §1 "Transit
    # holds"); the begin/end actions drive the WarpVFX manager. Fail-open: the
    # begin/end hook calls are try/excepted, so a VFX failure never blocks the
    # swap chain.
    flythrough = (bool(_vfx_enabled and _vfx_enabled())
                  and not _module_is_empty(dest_module))
    if flythrough:
        src_v = _vfx_vantage_of(source) if (_vfx_vantage_of and source) else None
        dst_v = _vfx_vantage_of(dest_module) if _vfx_vantage_of else None
        heading = _warp_heading(src_v, dst_v)
        t_transit = _transit_duration(src_v, dst_v)
        t_align = _align_duration(ship, heading)
        # Align start: remove control + start VFX (root @ 0). The "Enter Warp"
        # SFX is a separate root scheduled so its in-file flash (~_SFX_ENTER_
        # FLASH_AT into the clip) lands on the BURST (= t_align), now that the
        # align length is angle-driven (the old fixed-1.5s align kept it in sync
        # by luck). The set-swap is CHAINED behind departure, the in-transit
        # queues, _HoldUntilAction and the exit flash (no earlier than
        # t_align + t_transit);
        # placement + teardown + exit SFX + VFX-end chain after the swap,
        # firing on arrival.
        # Procedural-sky vantage to fly the backdrop from during transit: the
        # source system's galaxy position (fall back to the destination's when
        # the source is unmapped). None => the sky stays blacked out.
        sky_vantage = src_v if src_v is not None else dst_v
        seq.AddAction(_ClearTargetsAction(ship))
        # Pass the destination vantage too: when both endpoints are mapped the
        # sky vantage travels src->dst and arrives, so the destination's own
        # nebula looms ahead and envelops on exit instead of streaming past.
        seq.AddAction(_WarpVfxBeginAction(ship, heading, t_align, t_transit,
                                          sky_vantage, dst_v))
        enter_delay = t_align - _SFX_ENTER_FLASH_AT
        if enter_delay < 0.0:
            enter_delay = 0.0
        seq.AddAction(_WarpSoundAction("Enter Warp"), enter_delay)
        # At BURST (t_align): drop the render instances of the system being left
        # behind and park the player in BC's persistent warp set (spec §1b --
        # not necessarily empty, a mission may have parked ships there), so
        # during the held transit the source system no longer draws or lights
        # the scene (the set itself stands, and its ships keep simulating --
        # see the Plan-2 note on left-behind-ship audibility).
        _add_before_queue(seq)
        depart = _WarpDepartAction(source, ship, seq)
        seq.AddAction(depart, t_align)
        # Transit is chained, not timed (spec §1 "Transit holds"): departure ->
        # SDK WaitForQueued (player only) -> the in-transit queues -> the
        # mission-change point -> no earlier than 90 % of the nominal transit ->
        # release the streak (the exit flash plays) -> swap 0.1 * t_transit
        # later, at transit end under the flash. The SDK's own WaitForQueued
        # holds for MissionLib's master dialogue sequence; where BC's C++ puts
        # it in the chain is inferred.
        prev = depart
        if _is_current_player(ship):
            wait = App.TGScriptAction_Create("WarpSequence", "WaitForQueued")
            seq.AddAction(wait, prev)
            prev = wait
        prev = _add_transit_queues(seq, prev)
        hold = _HoldUntilAction(seq, t_align, t_transit)
        seq.AddAction(hold, prev)
        release = _TransitReleaseAction(seq)
        seq.AddAction(release, hold)
        swap = ChangeRenderedSetAction_Create(dest_module)
        seq.AddAction(swap, release, 0.1 * t_transit)
        seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
        seq.AppendAction(_ArriveFinalizeAction(source, ship))
        # BC's PostWarpEnableMenu clear — the player is in the destination set
        # by now, so this is the clear that holds. Placed at ARRIVAL rather
        # than at the end of the tail below: the reticle must drop the instant
        # you come out of warp, not _T_EXIT_DECEL seconds later.
        seq.AppendAction(_ArrivalClearTargetsAction(ship))
        seq.AppendAction(_WarpSoundAction("Exit Warp"))
        # The manager keeps running for _T_EXIT_DECEL seconds after arrival to
        # glide the ship from in-system warp speed down to 0; schedule the
        # defensive stop just past that tail (the manager also self-deactivates).
        from engine.warp_vfx import _T_EXIT_DECEL
        seq.AppendAction(_WarpVfxEndAction(ship), _T_EXIT_DECEL + 0.5)
        seq.AppendAction(_EnableHelmMenuAction())
        _append_after_queue(seq)
        return seq

    # Falsy destination => no set change/placement/teardown: the whole warp
    # degrades to "nothing happened" (BC's `if pcDestModule != None:` guard).
    # The per-action _do_play guards are the robust floor; skipping placement
    # and source teardown here keeps the player in its current set. Targets are
    # only cleared when a real warp actually happens (real destination).
    if not _module_is_empty(dest_module):
        seq.AddAction(_ClearTargetsAction(ship))
    # Same queue order as the flythrough, with no tunnel to hold: the SDK's
    # WaitForQueued (player only) still gates the swap on the master sequence.
    _add_before_queue(seq)
    swap = ChangeRenderedSetAction_Create(dest_module)
    prev = None
    if not _module_is_empty(dest_module):
        prev = _WarpDepartAction(source, ship, hard_cut=True)
        seq.AddAction(prev)
    if _is_current_player(ship):
        wait = App.TGScriptAction_Create("WarpSequence", "WaitForQueued")
        if prev is None:
            seq.AddAction(wait)
        else:
            seq.AddAction(wait, prev)
        prev = wait
    seq.AddAction(swap, _add_transit_queues(seq, prev))
    if not _module_is_empty(dest_module):
        seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
        seq.AppendAction(_ArriveFinalizeAction(source, ship))
        seq.AppendAction(_ArrivalClearTargetsAction(ship))
    seq.AppendAction(_EnableHelmMenuAction())
    _append_after_queue(seq)
    return seq


def _is_current_player(ship):
    import App
    try:
        player = App.Game_GetCurrentPlayer()
    except Exception:
        return False
    return player is not None and player is ship


def _add_before_queue(seq):
    """The button's "before" queue: roots, at their delays from the start."""
    for action, delay in seq._queues.get("before", ()):
        seq.AddAction(action, delay)


def _add_transit_queues(seq, prev):
    """Chain before-during -> during -> after-during -> _MissionChangePoint
    after `prev` (None => the first is a root). Returns the last action."""
    for key in ("before_during", "during", "after_during"):
        for action, delay in seq._queues.get(key, ()):
            if prev is None:
                seq.AddAction(action, delay)
            else:
                seq.AddAction(action, prev, delay)
            prev = action
    point = _MissionChangePoint(seq)
    if prev is None:
        seq.AddAction(point)
    else:
        seq.AddAction(point, prev)
    return point


def _append_after_queue(seq):
    """The button's "after" queue: after control returns, at their delays."""
    for action, delay in seq._queues.get("after", ()):
        seq.AppendAction(action, delay)


def find_set_course_menu():
    """The live Helm > Set Course menu, or None before the bridge builds it.

    Same walk MissionLib.GetSystemOrRegionMenu:2582-2593 does, minus the bridge
    character: straight off the TacticalControlWindow, so it works whether the
    menus were built by HelmMenuHandlers.CreateMenus or by a test. Labels come
    from Bridge Menus.tgl for the same reason the SDK loads it — they are
    localized, and a hardcoded "Helm" would miss on a translated build.

    None (never a truthy _Stub) when anything is missing: callers treat it as
    "no mission override recorded" and fall back to BC's default placement.
    """
    import App
    try:
        tcw = App.TacticalControlWindow_GetTacticalControlWindow()
        db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
        try:
            helm = tcw.FindMenu(db.GetString("Helm"))
            if helm is None:
                return None
            return helm.GetSubmenuW(db.GetString("Set Course"))
        finally:
            App.g_kLocalizationManager.Unload(db)
    except Exception as _e:
        from engine import dev_mode
        dev_mode.log_swallowed("find Set Course menu", _e)
        return None


def set_course_placement(button, dest_module) -> None:
    """Record on the warp button where `dest_module` should drop the player out,
    and which mission (if any) that course starts.

    Called when a course is plotted. In stock BC the SortedRegionMenu's own
    course button carried this across; our CEF Set Course modal replaced those
    buttons, so the engine performs the same carry here.

    Always assigns — including the defaults — because one warp button serves
    every course in the game. Plotting an un-overridden system after an
    overridden one must not inherit the previous arrival point, mission, or
    episode.
    """
    from engine.appc.tg_ui.st_widgets import DEFAULT_ARRIVAL_PLACEMENT
    menu = region_menu_for_destination(dest_module, find_set_course_menu())
    button.SetPlacementName(
        menu.GetPlacementName() if menu else DEFAULT_ARRIVAL_PLACEMENT)
    # BC's "warping here starts mission X" (SortedRegionMenu.SetMissionName /
    # SetEpisodeName, 67 SDK sites). Always assigned, like the placement, so a
    # plain course never inherits a previous one's mission (spec §1).
    button.set_course_mission(menu.GetMissionName() if menu else "",
                              menu.GetEpisodeName() if menu else "")


def region_menu_for_destination(dest_module, course_menu):
    """The live SortedRegionMenu offering `dest_module`, or None when the Set
    Course subtree has no such entry (or doesn't exist yet).

    BC keeps the mission's arrival/mission/episode overrides on the menu, not
    on the destination: MissionLib.LinkMenuToPlacement resolves a system (or a
    region inside it) to its SortedRegionMenu and calls SetPlacementName on
    it, and SetMissionName/SetEpisodeName follow the same pattern. So the
    lookup is "find the region menu that offers this destination module" — a
    walk of the LIVE Set Course subtree, deliberately not a module->menu
    registry, because a registry outlives the mission that filled it and the
    menu tree is rebuilt per mission (see the SDK's own ClearSetCourseMenu).

    Recursive: a system menu can hold per-region submenus, and
    GetSystemOrRegionMenu links either level.
    """
    from engine.appc.tg_ui.st_widgets import SortedRegionMenu
    if not dest_module or course_menu is None:
        return None
    target = str(dest_module)

    def _walk(node):
        if (isinstance(node, SortedRegionMenu)
                and node.GetRegionModule() == target):
            return node
        # __dict__ read, not getattr: TGObject.__getattr__ hands back a truthy
        # _Stub for any missing name, and iterating a _Stub never terminates.
        # STMenu stores children flat; TGPane stores (child, x, y) triples —
        # the Set Course subtree is menus, but it hangs off panes, so accept
        # both rather than depend on which one a caller hands us.
        for entry in node.__dict__.get("_children", []):
            child = entry[0] if isinstance(entry, tuple) else entry
            found = _walk(child)
            if found is not None:
                return found
        return None

    return _walk(course_menu)


def placement_name_for_destination(dest_module, course_menu):
    """The arrival placement a mission has linked to `dest_module`, or the
    default when it has not linked one.

    Fail-soft. Every caller is on the warp path, where the sane degradation is
    BC's own default arrival rather than an exception — the same reason
    WarpSequence_Create's `placement` argument has a default at all.
    """
    from engine.appc.tg_ui.st_widgets import DEFAULT_ARRIVAL_PLACEMENT
    menu = region_menu_for_destination(dest_module, course_menu)
    return menu.GetPlacementName() if menu else DEFAULT_ARRIVAL_PLACEMENT


def execute_warp(button, event=None):
    """Builds and plays the warp spine for the button's destination.

    Called by `engine.appc.warp_button.engage` — the last step of the
    ET_WARP_BUTTON_PRESSED chain (spec §1), which stands in for SDK
    WarpPressed rather than being registered as a handler alongside it."""
    import App
    dest = button.GetDestination()
    if not dest:
        return
    player = App.Game_GetCurrentPlayer()
    if player is None and _player_hook is not None:
        player = _player_hook()
    if player is None:
        return
    # The button carries the mission's arrival placement (set when the course
    # was plotted). This used to be the hardcoded literal "Player Start", which
    # silently discarded every MissionLib.LinkMenuToPlacement override — most
    # visibly E1M1's, dropping the player 93 km from the Starbase 12 nav point
    # instead of the scripted 312 km.
    placement = button.GetPlacementName()
    WarpSequence_Create(player, dest, button.GetWarpTime(), placement,
                        mission=button.get_mission_name() or None,
                        episode=button.get_episode_name() or None,
                        queues=button.take_queues()).Play()
