"""Quick Battle battle end: one place that wins or loses a battle.

Spec 2026-10-23-quickbattle-victory-conditions-design §4.1-4.5, §5.1-5.2.

A battle is ARMED by `begin` (called from the GenerateShips hook, after our
plan or BC's original spawns the ships) and ENDED by `end_battle`, which posts
BC's own ET_END_SIMULATION to the XO -- int 2 for a win, 1 for a loss -- one
second of game time later, the way QuickBattle.ShipDestroyed does for the
player's death (QuickBattle.py:3300-3316). EndSimulationEvent then runs
EndSimulation, the win or lose sequence and the fanfare.

- A win ENDS the battle for every type, Elimination included: a deliberate
  departure from BC, where a win leaves you flying.
- Only one ending per battle. The player's death beats everything: it deletes
  any end timer of ours and leaves BC's own loss timer in place. Otherwise the
  first ending evaluated wins.
- Every clock (the end delay, the time limit, the countdown) is a game-time
  TGTimer on App.g_kTimerManager, so it freezes under pause. `reset()` deletes
  them all; the EndSimulation hook calls it, which covers End Combat, XO
  Restart and the end timer itself, and the host calls it on a mission swap.

Three SDK functions are wrapped (`install`), never edited:

- ShipDestroyed: the step order in `_ship_destroyed` decides all precedence.
  While a battle is armed, BC's own instant win branch (QuickBattle.py:3356)
  is suppressed by holding bWonOrLost at 1 across the call; its enemy count
  and destroyed callouts still run.
- GenerateLoseSequence: BC's sequence with the XO's line swapped for ours when
  the protected ship died or time ran out.
- GenerateWinSequence: BC's Felix line, then, when this module ended the
  battle as a win, back to the bridge and BC's own win tail (menus turned
  back, Saffi's menu up).

EndSimulation runs `reset()` BEFORE EndSimulationEvent builds the win or lose
sequence, so `reset()` hands the ending (won, reason) to the two sequence
wrappers as a one-shot `_outcome`, separate from the forgotten state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Optional

_log = logging.getLogger(__name__)

REASON_ELIMINATION = "elimination"
REASON_PLAYER = "player"
REASON_PROTECTED = "protected"
REASON_TIME = "time"

END_DELAY_S = 1.0          # QuickBattle.py:3310 -- GetGameTime() + 1.0

# The countdown's whole minutes. E8M2 records Countdown10..1, but the even
# ones belong to that mission ("We have two minutes to reach a minimum safe
# distance!", "...until the sun destroys the solar system..."); only the odd
# ones are a plain "<N> minute(s) remaining" (spec §4.3 lists exactly these).
COUNTDOWN_MINUTES = (9, 7, 5, 3, 1)
_TIME_UP_KEY = 0           # our timer event int: 0 = time up, N = N min left

CREW_TGL = "data/TGL/Dauntless Crew.tgl"
COUNTDOWN_TGL = "data/TGL/Maelstrom/Episode 8/E8M2.TGL"
PROTECTED_LOST_KEY = "SaffiQBProtectedLost1"
TIME_UP_KEY = "SaffiQBTimeUp1"
COUNTDOWN_KEY = "E8M2Countdown%d"

OBJ_DESTROY = "Destroy all enemy ships"
OBJ_PROTECT = "Protect %s"
OBJ_TIME = "Win within %d min"

_HANDLER = __name__ + ".on_timer"
_ORIG_ATTR = "_dauntless_battle_end_orig"


@dataclass
class BattleState:
    type: str
    protected_name: Optional[str]
    ended: bool = False
    won: Optional[bool] = None
    reason: Optional[str] = None


_state: Optional[BattleState] = None
_qb = None                   # the QuickBattle module the armed battle runs in
_protected_id = None         # its object id, when it existed at begin()
_end_timer = None            # our pending ET_END_SIMULATION timer id
_timers: list = []           # our time-limit / countdown timer ids
_markers: list = []          # ship names we put a marker on
_objectives_shown = False    # we made the Objectives submenu visible
_outcome = None              # (won, reason) handed to the sequence wrappers
_dbs: dict = {}              # TGL filename -> loaded database
# Event type, allocated lazily and forgotten by reset(): App's event-type
# counter restarts on every mission swap (see late_arrivals._event_type).
_ET = None
_xo_registered = None        # (XO, event type) our handler is registered for


def _event_type() -> int:
    global _ET
    if _ET is None:
        import App
        _ET = App.Mission_GetNextEventType()
    return _ET


def state() -> Optional[BattleState]:
    """A copy of the armed battle's state, or None when no battle is armed."""
    return None if _state is None else replace(_state)


def _db(filename):
    db = _dbs.get(filename)
    if db is None:
        import App
        db = App.g_kLocalizationManager.Load(filename)
        _dbs[filename] = db
    return db


def _guard(what, fn, *args):
    """Run `fn(*args)`; log (never raise) on failure. SDK callback paths."""
    try:
        return fn(*args)
    except Exception:
        _log.exception("quickbattle battle end: %s failed", what)
        return None


# ── arming ──────────────────────────────────────────────────────────────────

def _protected_order(plan):
    """(1-based plan index, SpawnOrder) of the ship to protect, or None."""
    v = plan.victory
    if v.protect_entry_id is None:
        return None
    for n, order in enumerate(plan.orders, start=1):
        if order.entry_id == v.protect_entry_id:
            return n, order
    return None


def begin(qb, plan) -> None:
    """Arm one battle. `plan` is the BattlePlan the ships came from, or None
    when BC's own GenerateShips ran (Elimination)."""
    global _state, _qb, _protected_id, _outcome
    import App
    from engine.quickbattle import naming
    from engine.quickbattle import victory as vic
    reset()
    _outcome = None
    victory = plan.victory if plan is not None else None
    vtype = victory.type if victory is not None else vic.ELIMINATION
    protected = shown = None
    late = False
    if plan is not None and vtype == vic.KOBAYASHI_MARU:
        found = _protected_order(plan)
        if found is None:
            _log.warning("quickbattle: Kobayashi Maru has no ship to protect "
                         "(entry %r is not in the plan); nothing to protect",
                         victory.protect_entry_id)
        else:
            n, order = found
            protected = naming.object_name(order.title, n)
            shown = order.display_name or protected
            late = order.warp_in_s > 0
    _state = BattleState(vtype, protected)
    _qb = qb
    _protected_id = None
    if protected is not None and not late:
        ship = _guard("protected ship lookup", App.ShipClass_GetObject, qb.g_pSet, protected)
        if ship is None:
            _log.warning("quickbattle: the protected ship %s did not spawn; "
                         "the battle carries on without it", protected)
        else:
            _protected_id = ship.GetObjID()
    if protected is not None:
        _guard("protect marker", _set_marker, protected)
        # Enemies weight the protected ship, E6M1's way (km_targeting). Before
        # StartSimulation2's AI loop, which runs right after GenerateShips.
        from engine.quickbattle import km_targeting
        _guard("Kobayashi Maru targeting", km_targeting.arm, qb, plan, protected,
               _protected_id is not None)
    limit_s = float(victory.time_limit_s) if victory is not None else 0.0
    _guard("objectives", _show_objectives, shown, limit_s)
    if limit_s > 0:
        _guard("time limit", _schedule_time_limit, qb, limit_s)


def _set_marker(name) -> None:
    from engine.ui import target_markers
    target_markers.set_marker(name, "protect")
    _markers.append(name)


def _show_objectives(protect_label, limit_s) -> None:
    """Quick Battle hides the Objectives submenu (QuickBattle.py:735-739):
    show it, empty it, and list this battle's goals."""
    global _objectives_shown
    from engine.appc import mission_goals
    menu = mission_goals.objectives_submenu()
    if menu is None:
        _log.warning("quickbattle: no XO Objectives menu; goals not shown")
        return
    menu.SetVisible()
    _objectives_shown = True
    menu.KillChildren()
    mission_goals.add_goal_button(OBJ_DESTROY)
    if protect_label is not None:
        mission_goals.add_goal_button(OBJ_PROTECT % protect_label)
    if limit_s > 0:
        mission_goals.add_goal_button(OBJ_TIME % int(round(limit_s / 60.0)))


def _register_handler(xo) -> None:
    global _xo_registered
    et = _event_type()
    if _xo_registered is not None and _xo_registered[0] is xo \
            and _xo_registered[1] == et:
        return
    xo.AddPythonFuncHandlerForInstance(et, _HANDLER)
    _xo_registered = (xo, et)


def _add_timer(at, event_type, dest, value) -> int:
    import App
    evt = App.TGIntEvent_Create()
    evt.SetEventType(event_type)
    evt.SetDestination(dest)
    evt.SetInt(value)
    timer = App.TGTimer_Create()
    timer.SetTimerStart(at)
    timer.SetDelay(0)
    timer.SetDuration(0)
    timer.SetEvent(evt)
    tid = timer.GetObjID()
    App.g_kTimerManager.AddTimer(timer)
    return tid


def _schedule_time_limit(qb, limit_s) -> None:
    """The time-up timer, then E8M2's countdown (E8M2.py:2984-3020) at each
    of COUNTDOWN_MINUTES that fits inside the limit."""
    import App
    _register_handler(qb.g_pXO)
    start = App.g_kUtopiaModule.GetGameTime()
    et = _event_type()
    _timers.append(_add_timer(start + limit_s, et, qb.g_pXO, _TIME_UP_KEY))
    for minutes in COUNTDOWN_MINUTES:
        if minutes * 60.0 > limit_s:
            continue
        _timers.append(_add_timer(start + limit_s - minutes * 60.0, et,
                                  qb.g_pXO, minutes))


def on_timer(pObject, pEvent) -> None:
    """XO instance handler for our time-limit and countdown timers. Each
    battle allocates a fresh event type, so an event of an older type (a
    previous battle's timer that somehow survived reset) is ignored."""
    if _ET is not None and pEvent.GetEventType() == _ET:
        _guard("timer", _on_timer, pEvent.GetInt())
    pObject.CallNextHandler(pEvent)


def _on_timer(key) -> None:
    qb, st = _qb, _state
    if qb is None or st is None or st.ended or not getattr(qb, "bInSimulation", 0):
        return
    if key == _TIME_UP_KEY:
        end_battle(qb, False, REASON_TIME)
    else:
        _countdown(key)


def _countdown(minutes) -> None:
    import App
    bridge = App.g_kSetManager.GetSet("bridge")
    sci = App.CharacterClass_GetObject(bridge, "Science") if bridge is not None else None
    if sci is None:
        _log.warning("quickbattle: no Science officer for the countdown")
        return
    sci.SayLine(_db(COUNTDOWN_TGL), COUNTDOWN_KEY % minutes, "Captain", 1)


# ── ending ──────────────────────────────────────────────────────────────────

def end_battle(qb, won: bool, reason: str) -> bool:
    """End the armed battle: hold bWonOrLost at 1 and post ET_END_SIMULATION
    (2 = won, 1 = lost) to the XO END_DELAY_S of game time from now, its timer
    id in qb.g_idTimer (QuickBattle.py:3300-3316). False when no battle is
    armed or it has already ended."""
    global _end_timer
    import App
    st = _state
    if st is None or st.ended:
        return False
    tid = _add_timer(App.g_kUtopiaModule.GetGameTime() + END_DELAY_S,
                     qb.ET_END_SIMULATION, qb.g_pXO, 2 if won else 1)
    _end_timer = tid
    qb.g_idTimer = tid
    qb.bWonOrLost = 1
    st.ended, st.won, st.reason = True, bool(won), reason
    return True


def _cancel_end_timer(qb) -> None:
    global _end_timer
    if _end_timer is None:
        return
    import App
    App.g_kTimerManager.DeleteTimer(_end_timer)
    if qb is not None and getattr(qb, "g_idTimer", None) == _end_timer:
        qb.g_idTimer = App.NULL_ID
    _end_timer = None


def _bc_win(qb) -> None:
    """BC's own win branch (QuickBattle.py:3356-3367), for a battle this
    module never armed: a win leaves you flying."""
    if qb.g_iNumEnemies == 0 and qb.bInSimulation and qb.bWonOrLost == 0:
        qb.bWonOrLost = 1
        qb.GenerateWinSequence()
        import BridgeHandlers
        BridgeHandlers.DropMenusTurnBack()
        qb.g_pXO.MenuUp()


def check_win(qb) -> None:
    """Every enemy gone (late arrivals included in g_iNumEnemies): end the
    armed battle as a win. With no armed battle, BC's own win branch."""
    st = _state
    if st is None:
        _bc_win(qb)
        return
    if st.ended or not qb.bInSimulation or qb.bWonOrLost != 0 \
            or qb.g_iNumEnemies != 0:
        return
    end_battle(qb, True, REASON_ELIMINATION)


def _is_protected(ship) -> bool:
    st = _state
    if st is None or st.protected_name is None or ship.GetName() != st.protected_name:
        return False
    return _protected_id is None or ship.GetObjID() == _protected_id


def _before_bc(qb, ship) -> None:
    """ShipDestroyed steps 2-3, before BC's own handler runs."""
    import App
    st = _state
    game = App.Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    if player and ship.GetName() == player.GetName():
        if qb.bInSimulation:
            # The player's death beats everything (spec §4.1): BC's handler
            # posts its own loss timer next, so ours must go.
            _cancel_end_timer(qb)
            st.ended, st.won, st.reason = True, False, REASON_PLAYER
    elif _is_protected(ship) and not st.ended and qb.bInSimulation:
        end_battle(qb, False, REASON_PROTECTED)


def _ship_destroyed(qb, orig, pObject, pEvent):
    import App
    ship = _guard("destroyed ship cast",
                  lambda: App.ShipClass_Cast(pEvent.GetDestination()))
    if _state is None:
        result = orig(pObject, pEvent)
        _guard("check win", check_win, qb)
        return result
    if ship is not None:
        _guard("ship destroyed", _before_bc, qb, ship)
    saved = qb.bWonOrLost
    qb.bWonOrLost = 1                     # suppress BC's instant win branch
    try:
        result = orig(pObject, pEvent)
    finally:
        if _state is None or not _state.ended:
            qb.bWonOrLost = saved
    _guard("check win", check_win, qb)
    return result


def _take_outcome():
    global _outcome
    out, _outcome = _outcome, None
    return out


def _lose_sequence(qb, line_key) -> None:
    """BC's GenerateLoseSequence (QuickBattle.py:3380-3420), the XO's line
    swapped for ours."""
    import App
    App.TopWindow_GetTopWindow().ForceBridgeVisible()
    xo = qb.g_pXO
    seq = App.TGSequence_Create()
    seq.AppendAction(App.TGScriptAction_Create("MissionLib", "StartCutscene"))
    seq.AppendAction(App.CharacterAction_Create(xo, App.CharacterAction.AT_LOOK_AT_ME))
    seq.AppendAction(App.CharacterAction_Create(
        xo, App.CharacterAction.AT_SPEAK_LINE, line_key, "Captain", 0, _db(CREW_TGL)))
    seq.AppendAction(App.CharacterAction_Create(xo, App.CharacterAction.AT_LOOK_AT_ME))
    seq.AppendAction(App.TGScriptAction_Create("MissionLib", "EndCutscene"))
    seq.AppendAction(App.CharacterAction_Create(xo, App.CharacterAction.AT_MENU_UP), 1.0)
    button = qb.g_pXOMenu.GetButtonW(qb.g_pMissionDatabase.GetString("Start Simulation"))
    if button is None:
        button = qb.g_pXOMenu.GetButtonW(qb.g_pMissionDatabase.GetString("Restart Simulation"))
    seq.AppendAction(App.TGScriptAction_Create(qb.__name__, "MoveMouseToButton", button, 1))
    seq.Play()


_LOSE_LINES = {REASON_PROTECTED: PROTECTED_LOST_KEY, REASON_TIME: TIME_UP_KEY}


def _generate_lose_sequence(qb, orig):
    out = _take_outcome()
    key = _LOSE_LINES.get(out[1]) if out is not None else None
    if key is not None:
        try:
            return _lose_sequence(qb, key)
        except Exception:
            _log.exception("quickbattle: our lose sequence failed; playing BC's")
    return orig()


def _win_tail(qb) -> None:
    """Back to the bridge (ruling 5, GenerateLoseSequence's first step,
    QuickBattle.py:3381-3383), then BC's win tail (QuickBattle.py:3365-3368)."""
    import App
    import BridgeHandlers
    _guard("force bridge visible",
           lambda: App.TopWindow_GetTopWindow().ForceBridgeVisible())
    BridgeHandlers.DropMenusTurnBack()
    qb.g_pXO.MenuUp()


def _generate_win_sequence(qb, orig, pSequence=None):
    out = _take_outcome()
    result = orig(pSequence)
    if out is not None and out[0]:
        _guard("win tail", _win_tail, qb)
    return result


def install(qb) -> bool:
    """Wrap qb.ShipDestroyed, GenerateLoseSequence and GenerateWinSequence.
    Idempotent: a second call finds the `_dauntless_battle_end_orig` marks and
    returns False. The SDK resolves all three by name at call time (the
    ShipDestroyed broadcast handler is a "module.func" string), so replacing
    the module attributes is enough."""
    made = {
        "ShipDestroyed": lambda orig: lambda pObject, pEvent:
            _ship_destroyed(qb, orig, pObject, pEvent),
        "GenerateLoseSequence": lambda orig: lambda:
            _generate_lose_sequence(qb, orig),
        "GenerateWinSequence": lambda orig: lambda pSequence=None:
            _generate_win_sequence(qb, orig, pSequence),
    }
    installed = False
    for name, make in made.items():
        current = getattr(qb, name, None)
        if current is None or getattr(current, _ORIG_ATTR, None) is not None:
            continue
        wrapper = make(current)
        wrapper.__name__ = name
        setattr(wrapper, _ORIG_ATTR, current)
        setattr(qb, name, wrapper)
        installed = True
    return installed


# ── reset ───────────────────────────────────────────────────────────────────

def _hide_objectives() -> None:
    from engine.appc import mission_goals
    menu = mission_goals.objectives_submenu()
    if menu is not None:
        menu.KillChildren()
        menu.SetNotVisible()


def reset() -> None:
    """Cancel every timer this module made, empty and hide the Objectives it
    showed, clear its markers, restore BC's enemy targeting and forget the
    battle. An ending already decided is kept only as the one-shot
    `_outcome` for the sequence wrappers that EndSimulationEvent runs right
    after EndSimulation."""
    global _state, _qb, _protected_id, _objectives_shown, _outcome, _ET, \
        _xo_registered
    st, qb = _state, _qb
    _outcome = (st.won, st.reason) if st is not None and st.ended else None
    try:
        import App
        for tid in _timers:
            App.g_kTimerManager.DeleteTimer(tid)
    except Exception:
        _log.exception("quickbattle battle end: could not delete timers")
    _timers.clear()
    _guard("end timer cancel", _cancel_end_timer, qb)
    if _objectives_shown:
        _guard("objectives hide", _hide_objectives)
    _objectives_shown = False
    if _markers:
        from engine.ui import target_markers
        for name in _markers:
            target_markers.clear_marker(name)
        _markers.clear()
    if _dbs:
        try:
            import App
            for db in _dbs.values():
                App.g_kLocalizationManager.Unload(db)
        except Exception:
            _log.exception("quickbattle battle end: could not unload databases")
        _dbs.clear()
    try:
        from engine.quickbattle import km_targeting
        km_targeting.reset()
    except Exception:
        _log.exception("quickbattle battle end: could not reset enemy targeting")
    _state = None
    _qb = None
    _protected_id = None
    _ET = None
    _xo_registered = None
