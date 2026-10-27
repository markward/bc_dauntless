"""Quick Battle battle end: one place that wins or loses a battle, from the
Victory and Defeat condition stacks.

Spec 2026-10-27-quickbattle-victory-defeat-conditions-design §4 (the rules)
and §5 (markers, lines, objectives); phase 1's ending path (spec
2026-10-23-quickbattle-victory-conditions-design §4.1-4.5) is kept.

A battle is ARMED by `begin` (called from the GenerateShips hook, after our
plan or BC's original spawns the ships) and ENDED by `end_battle`, which posts
BC's own ET_END_SIMULATION to the XO -- int 2 for a win, 1 for a loss -- one
second of game time later, the way QuickBattle.ShipDestroyed does for the
player's death (QuickBattle.py:3300-3316). EndSimulationEvent then runs
EndSimulation, the win or lose sequence and the fanfare.

- Each stack has an implicit default (Victory: every enemy destroyed;
  Defeat: the player destroyed) plus the plan's added conditions
  (`plan.victory.conditions`): Ships Destroyed (ANY / ALL of a list) and at
  most one Timer per side. Any one condition met settles its stack.
- A win ENDS the battle: a deliberate departure from BC, where a win leaves
  you flying.
- Only one ending, and a loss can overturn a pending win (spec §4.3): any
  defeat condition met inside the END_DELAY_S before a win is posted cancels
  that win's timer and ends the battle lost instead. A pending loss is never
  overturned. The player's death beats everything: it deletes any end timer
  of ours and leaves BC's own loss timer in place.
- A ship counts as destroyed in every condition listing it, whoever destroys
  it. Ships are matched by object name AND, for a ship that existed at begin,
  object id, so a same-named stranger never counts; a late (warp-in) ship is
  matched by name only.
- Timers: one per side; the Victory timer is not scheduled when it is not
  earlier than the Defeat timer (a tie is a loss), and the countdown follows
  the earlier scheduled timer.
- Every clock (the end delay, the timers, the countdown) is a game-time
  TGTimer on App.g_kTimerManager, so it freezes under pause. `reset()` deletes
  them all; the EndSimulation hook calls it, which covers End Combat, XO
  Restart and the end timer itself, and the host calls it on a mission swap.

Three SDK functions are wrapped (`install`), never edited:

- ShipDestroyed: the step order in `_ship_destroyed` decides all precedence.
  While a battle is armed, BC's own instant win branch (QuickBattle.py:3356)
  is suppressed by holding bWonOrLost at 1 across the call; its enemy count
  and destroyed callouts still run.
- GenerateLoseSequence: BC's sequence with the XO's line swapped for ours when
  a protected ship (or every one) died or the Defeat timer ran out.
- GenerateWinSequence: BC's Felix line -- or, for a Victory timer win, the
  XO's survived line in its place -- then, when this module ended the battle
  as a win, back to the bridge and BC's own win tail (menus turned back,
  Saffi's menu up).

EndSimulation runs `reset()` BEFORE EndSimulationEvent builds the win or lose
sequence, so `reset()` hands the ending (won, reason) to the two sequence
wrappers as a one-shot `_outcome`, separate from the forgotten state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Optional

_log = logging.getLogger(__name__)

REASON_ELIMINATION = "elimination"     # Victory default: every enemy destroyed
REASON_TARGETS = "targets"             # a Victory Ships Destroyed met
REASON_SURVIVED = "survived"           # the Victory timer ran out
REASON_PLAYER = "player"               # Defeat default: the player destroyed
REASON_PROTECTED = "protected"         # a Defeat Ships Destroyed met (ANY, or one ship)
REASON_PROTECTED_ALL = "protected_all"  # a Defeat Ships Destroyed ALL of several
REASON_TIME = "time"                   # the Defeat timer ran out

END_DELAY_S = 1.0          # QuickBattle.py:3310 -- GetGameTime() + 1.0

# The countdown's whole minutes. E8M2 records Countdown10..1, but the even
# ones belong to that mission ("We have two minutes to reach a minimum safe
# distance!", "...until the sun destroys the solar system..."); only the odd
# ones are a plain "<N> minute(s) remaining" (spec §4.3 lists exactly these).
COUNTDOWN_MINUTES = (9, 7, 5, 3, 1)
# Our timer event ints: N > 0 = N minutes left on the countdown.
_DEFEAT_TIME_UP = 0
_VICTORY_TIME_UP = -1

CREW_TGL = "data/TGL/Dauntless Crew.tgl"
COUNTDOWN_TGL = "data/TGL/Maelstrom/Episode 8/E8M2.TGL"
PROTECTED_LOST_KEY = "SaffiQBProtectedLost1"
PROTECTED_LOST_ALL_KEY = "SaffiQBProtectedLostAll1"
TIME_UP_KEY = "SaffiQBTimeUp1"
SURVIVED_KEY = "SaffiQBSurvived1"
COUNTDOWN_KEY = "E8M2Countdown%d"

# Objectives (spec §5.4; wording rulings in the plan's constraints: no
# articles, lists "A", "A and B", "A, B and C", "A, B, C and N more").
OBJ_DESTROY = "Destroy all enemy ships"
OBJ_DESTROY_SHIPS = "Destroy %s"
OBJ_SURVIVE = "Survive for %d min"
OBJ_PROTECT = "Protect %s"
OBJ_KEEP_ALIVE = "Keep %s alive"
OBJ_TIME = "Win within %d min"
_OBJ_LIST_MAX = 3

_HANDLER = __name__ + ".on_timer"
_ORIG_ATTR = "_dauntless_battle_end_orig"


@dataclass
class ArmedCondition:
    """One added condition as the armed battle tracks it."""
    side: str                  # victory.VICTORY / DEFEAT
    kind: str                  # victory.SHIPS / TIMER
    mode: str                  # victory.ANY / ALL
    names: tuple = ()          # Ships: object names, in plan order
    labels: tuple = ()         # Ships: objective labels, parallel to names
    time_s: float = 0.0        # Timer: its game-time length
    destroyed: set = field(default_factory=set)   # Ships: names destroyed

    def met(self) -> bool:
        """A Ships Destroyed condition is met (a Timer is met by its timer)."""
        from engine.quickbattle import victory as vic
        if self.kind != vic.SHIPS or not self.names:
            return False
        if self.mode == vic.ALL:
            return all(n in self.destroyed for n in self.names)
        return bool(self.destroyed)


@dataclass
class BattleState:
    conditions: tuple = ()     # ArmedCondition, in the plan's stored order
    ended: bool = False
    won: Optional[bool] = None
    reason: Optional[str] = None


_state: Optional[BattleState] = None
_qb = None                   # the QuickBattle module the armed battle runs in
_ship_ids: dict = {}         # listed object name -> its object id, at begin()
_end_timer = None            # our pending ET_END_SIMULATION timer id
_timers: list = []           # our Timer / countdown timer ids
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
    if _state is None:
        return None
    return replace(_state, conditions=tuple(
        replace(c, destroyed=set(c.destroyed)) for c in _state.conditions))


def _names_on(side) -> list:
    from engine.quickbattle import victory as vic
    out = []
    if _state is not None:
        for c in _state.conditions:
            if c.side == side and c.kind == vic.SHIPS:
                out.extend(n for n in c.names if n not in out)
    return out


def protected_names() -> list:
    """Object names of every ship in the armed battle's Defeat Ships
    Destroyed conditions, first listing order; [] when none or unarmed."""
    from engine.quickbattle import victory as vic
    return _names_on(vic.DEFEAT)


def target_names() -> list:
    """Object names of every ship in the armed battle's Victory Ships
    Destroyed conditions, first listing order; [] when none or unarmed."""
    from engine.quickbattle import victory as vic
    return _names_on(vic.VICTORY)


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

def _arm_condition(order_of, c) -> Optional[ArmedCondition]:
    """The ArmedCondition for one ConditionOrder, or None when a Ships
    condition names no ship of the plan. `order_of`: entry id -> (1-based
    plan index, SpawnOrder); the object name is naming.object_name(title, n)
    as the spawner names it, the label `display_name or <object name>`."""
    from engine.quickbattle import naming
    from engine.quickbattle import victory as vic
    if c.kind == vic.TIMER:
        return ArmedCondition(c.side, c.kind, c.mode, time_s=float(c.time_s))
    names, labels = [], []
    for eid in c.entry_ids:
        found = order_of.get(eid)
        if found is None:
            _log.warning("quickbattle: %s condition ship %r is not in the plan; "
                         "ignored", c.side, eid)
            continue
        n, order = found
        name = naming.object_name(order.title, n)
        names.append(name)
        labels.append(order.display_name or name)
    if not names:
        _log.warning("quickbattle: %s Ships Destroyed condition has no ship "
                     "in the plan; ignored", c.side)
        return None
    return ArmedCondition(c.side, c.kind, c.mode, tuple(names), tuple(labels))


def begin(qb, plan) -> None:
    """Arm one battle. `plan` is the BattlePlan the ships came from, or None
    when BC's own GenerateShips ran (the two defaults only)."""
    global _state, _qb, _outcome
    import App
    reset()
    _outcome = None
    conds, late = (), set()
    if plan is not None:
        order_of = {o.entry_id: (n, o) for n, o in enumerate(plan.orders, start=1)}
        conds = tuple(a for a in (_arm_condition(order_of, c)
                                  for c in plan.victory.conditions) if a is not None)
        from engine.quickbattle import naming
        late = {naming.object_name(o.title, n) for n, o in enumerate(plan.orders, start=1)
                if o.warp_in_s > 0}
    _state = BattleState(conds)
    _qb = qb
    protected, targets = protected_names(), target_names()
    for name in protected + targets:
        if name in late:
            continue                       # arrives later: matched by name
        ship = _guard("listed ship lookup", App.ShipClass_GetObject, qb.g_pSet, name)
        if ship is None:
            _log.warning("quickbattle: the listed ship %s did not spawn; "
                         "the battle carries on without it", name)
        else:
            _ship_ids[name] = ship.GetObjID()
    for name in protected:
        _guard("protect marker", _set_marker, name, "protect")
    for name in targets:
        _guard("target marker", _set_marker, name, "target")
    if protected or targets:
        # Enemies weight every protected ship and friendlies every hunt
        # target, E6M1's way (km_targeting). Before StartSimulation2's AI
        # loop, which runs right after GenerateShips.
        from engine.quickbattle import km_targeting
        _guard("listed ship targeting", km_targeting.arm, qb, plan, protected,
               targets, set(_ship_ids))
    _guard("objectives", _show_objectives, conds)
    _guard("timers", _schedule_timers, qb, conds)


def _set_marker(name, kind) -> None:
    from engine.ui import target_markers
    target_markers.set_marker(name, kind)
    _markers.append(name)


def _join(labels, word) -> str:
    """"A", "A <word> B", "A, B <word> C"; more than _OBJ_LIST_MAX names:
    "A, B, C and N more"."""
    labels = list(labels)
    if len(labels) > _OBJ_LIST_MAX:
        return "%s and %d more" % (", ".join(labels[:_OBJ_LIST_MAX]),
                                   len(labels) - _OBJ_LIST_MAX)
    if len(labels) == 1:
        return labels[0]
    return "%s %s %s" % (", ".join(labels[:-1]), word, labels[-1])


def _objective(c) -> str:
    """The Objectives entry for one condition (spec §5.4). ANY joins with
    "or" on Victory and "and" on Defeat, ALL the reverse; a Defeat ALL of
    several reads "Keep ... alive"."""
    from engine.quickbattle import victory as vic
    if c.kind == vic.TIMER:
        minutes = int(round(c.time_s / 60.0))
        return (OBJ_SURVIVE if c.side == vic.VICTORY else OBJ_TIME) % minutes
    if c.side == vic.VICTORY:
        return OBJ_DESTROY_SHIPS % _join(c.labels, "or" if c.mode == vic.ANY else "and")
    if c.mode == vic.ALL and len(c.labels) > 1:
        return OBJ_KEEP_ALIVE % _join(c.labels, "or")
    return OBJ_PROTECT % _join(c.labels, "and")


def _show_objectives(conds) -> None:
    """Quick Battle hides the Objectives submenu (QuickBattle.py:735-739):
    show it, empty it, and list this battle's goals -- the Victory stack (its
    default, then its conditions in stored order), then the Defeat stack's
    conditions. The player's death gets no entry (it is implied)."""
    global _objectives_shown
    from engine.appc import mission_goals
    from engine.quickbattle import victory as vic
    menu = mission_goals.objectives_submenu()
    if menu is None:
        _log.warning("quickbattle: no XO Objectives menu; goals not shown")
        return
    menu.SetVisible()
    _objectives_shown = True
    menu.KillChildren()
    mission_goals.add_goal_button(OBJ_DESTROY)
    for side in (vic.VICTORY, vic.DEFEAT):
        for c in conds:
            if c.side == side:
                mission_goals.add_goal_button(_objective(c))


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


def _timer_s(conds, side) -> float:
    from engine.quickbattle import victory as vic
    return next((c.time_s for c in conds
                 if c.side == side and c.kind == vic.TIMER and c.time_s > 0), 0.0)


def _schedule_timers(qb, conds) -> None:
    """The Defeat and Victory time-up timers -- the Victory one only when it
    is earlier than the Defeat one, so a tie is a loss (spec §4.2) -- then
    E8M2's countdown (E8M2.py:2984-3020) against the earlier scheduled timer,
    at each of COUNTDOWN_MINUTES that fits inside it."""
    import App
    from engine.quickbattle import victory as vic
    win_s, lose_s = _timer_s(conds, vic.VICTORY), _timer_s(conds, vic.DEFEAT)
    if win_s > 0 and lose_s > 0 and win_s >= lose_s:
        _log.info("quickbattle: the victory timer (%.0f s) is not earlier than "
                  "the defeat timer (%.0f s); the defeat timer settles it",
                  win_s, lose_s)
        win_s = 0.0
    if win_s <= 0 and lose_s <= 0:
        return
    _register_handler(qb.g_pXO)
    start = App.g_kUtopiaModule.GetGameTime()
    et = _event_type()
    if lose_s > 0:
        _timers.append(_add_timer(start + lose_s, et, qb.g_pXO, _DEFEAT_TIME_UP))
    if win_s > 0:
        _timers.append(_add_timer(start + win_s, et, qb.g_pXO, _VICTORY_TIME_UP))
    first = min(s for s in (win_s, lose_s) if s > 0)
    for minutes in COUNTDOWN_MINUTES:
        if minutes * 60.0 > first:
            continue
        _timers.append(_add_timer(start + first - minutes * 60.0, et,
                                  qb.g_pXO, minutes))


def on_timer(pObject, pEvent) -> None:
    """XO instance handler for our Timer and countdown timers. Each battle
    allocates a fresh event type, so an event of an older type (a previous
    battle's timer that somehow survived reset) is ignored."""
    if _ET is not None and pEvent.GetEventType() == _ET:
        _guard("timer", _on_timer, pEvent.GetInt())
    pObject.CallNextHandler(pEvent)


def _on_timer(key) -> None:
    qb, st = _qb, _state
    if qb is None or st is None or not getattr(qb, "bInSimulation", 0):
        return
    if key == _DEFEAT_TIME_UP:
        _lose(qb, REASON_TIME)             # may overturn a pending win
    elif st.ended:
        return
    elif key == _VICTORY_TIME_UP:
        end_battle(qb, True, REASON_SURVIVED)
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


def _lose(qb, reason) -> bool:
    """End the armed battle lost. A pending win (ended, won, its end timer
    not yet fired) is overturned: its timer is deleted and the loss posted
    in its place (spec §4.3). A loss already decided stands. False when
    nothing changed."""
    st = _state
    if st is None:
        return False
    if st.ended:
        if not st.won or _end_timer is None:
            return False
        _cancel_end_timer(qb)
        st.ended, st.won, st.reason = False, None, None
    return end_battle(qb, False, reason)


def _defeat_reason(c) -> str:
    from engine.quickbattle import victory as vic
    if c.mode == vic.ALL and len(c.names) > 1:
        return REASON_PROTECTED_ALL
    return REASON_PROTECTED


def _mark_destroyed(ship) -> bool:
    """Mark `ship` destroyed in every Ships condition listing it. A listed
    ship that existed at begin matches by object id too, so a same-named
    stranger never counts. True when any condition lists it."""
    st = _state
    name = ship.GetName()
    known = _ship_ids.get(name)
    if known is not None and ship.GetObjID() != known:
        return False
    hit = False
    for c in st.conditions:
        if name in c.names:
            c.destroyed.add(name)
            hit = True
    return hit


def _settle(qb) -> None:
    """Defeat conditions first, then Victory (spec §4.3). A met Defeat
    condition ends the battle lost, overturning a pending win; a met Victory
    condition ends it won only if nothing has ended yet."""
    from engine.quickbattle import victory as vic
    st = _state
    for c in st.conditions:
        if c.side == vic.DEFEAT and c.met():
            _lose(qb, _defeat_reason(c))
            return
    if st.ended:
        return
    if any(c.side == vic.VICTORY and c.met() for c in st.conditions):
        end_battle(qb, True, REASON_TARGETS)


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
    elif qb.bInSimulation and _mark_destroyed(ship):
        _settle(qb)


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


_LOSE_LINES = {REASON_PROTECTED: PROTECTED_LOST_KEY,
               REASON_PROTECTED_ALL: PROTECTED_LOST_ALL_KEY,
               REASON_TIME: TIME_UP_KEY}


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


def _survived_sequence(qb, pSequence=None) -> None:
    """BC's GenerateWinSequence (QuickBattle.py:3429-3436) with the XO's
    survived line, spoken as _lose_sequence speaks, in place of Felix's."""
    import App
    if pSequence is None:
        pSequence = App.TGSequence_Create()
    pSequence.AppendAction(App.CharacterAction_Create(
        qb.g_pXO, App.CharacterAction.AT_SPEAK_LINE, SURVIVED_KEY, "Captain", 0,
        _db(CREW_TGL)))
    pSequence.Play()


def _generate_win_sequence(qb, orig, pSequence=None):
    out = _take_outcome()
    result = None
    if out is not None and out[0] and out[1] == REASON_SURVIVED:
        try:
            _survived_sequence(qb, pSequence)
        except Exception:
            _log.exception("quickbattle: our win sequence failed; playing BC's")
            result = orig(pSequence)
    else:
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
    global _state, _qb, _objectives_shown, _outcome, _ET, _xo_registered
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
    _ship_ids.clear()
    _ET = None
    _xo_registered = None
