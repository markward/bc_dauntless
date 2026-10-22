"""Quick Battle late groups: game-time arrivals through BC's warp-in routine.

Spec 2026-10-22-warp-in-arrivals-and-qb-delay §6.5. `spawn.generate_ships`
pre-counts every late ship and hands the late orders here. One TGTimer per
DISTINCT delay -- groups sharing a delay arrive in one tick, so the crew
calls them out once per side -- posts an int event (the delay's key) to
QuickBattle's XO, the way BC's own end-of-battle timer does
(QuickBattle.py:3303-3315). On that event each group picks a random face
around the player's CURRENT pose and its ships are created the E5M4 way: a
run-time PlacementObject at the spot, then
`loadspacehelper.CreateShip(..., placement, 1)` (flash + 2 s slide).

`EndSimulation` (wrapped by `spawn.install_end_simulation_hook`) cancels
everything pending, which covers End Combat, Restart and the end-of-battle
timer. A ship that cannot be spawned is un-counted, and the win check
QuickBattle.ShipDestroyed runs is repeated, so a broken reinforcement never
leaves a battle that cannot be won.
"""
from __future__ import annotations

import logging
import random

_log = logging.getLogger(__name__)

_HANDLER = __name__ + ".on_timer"

# Event type, allocated lazily at schedule time and forgotten by reset():
# App._next_event_type_id restarts at 1200 on every mission swap
# (host_loop.reset_sdk_globals), so a type cached across a swap could collide
# with one the next mission's SDK scripts allocate.
_ET = None
_rng = random.Random()
_qb = None             # the QuickBattle module that scheduled the pending keys
_xo_registered = None  # (XO object, event type) our handler is registered for
_next_key = 0
# key -> {"orders": [(n, SpawnOrder)], "timer": timer id}
_pending: dict = {}
_radii: dict = {}      # SpawnOrder.entry_id -> probe radius (GU)


def _event_type() -> int:
    global _ET
    if _ET is None:
        import App
        _ET = App.Mission_GetNextEventType()
    return _ET


def set_rng(rng) -> None:
    """Tests: inject the RNG that picks each group's arrival face."""
    global _rng
    _rng = rng


def pending_enemy_count() -> int:
    """Late enemy ships pre-counted in g_iNumEnemies that have not arrived."""
    return sum(1 for entry in _pending.values()
               for _n, order in entry["orders"] if order.allegiance == "enemy")


def _register_handler(xo) -> None:
    global _xo_registered
    et = _event_type()
    if _xo_registered is not None and _xo_registered[0] is xo \
            and _xo_registered[1] == et:
        return
    xo.AddPythonFuncHandlerForInstance(et, _HANDLER)
    _xo_registered = (xo, et)


def schedule(qb, late_orders, radii) -> None:
    """Schedule `late_orders` ([(1-based plan index, SpawnOrder)]) to arrive
    `warp_in_s` of game time from now. `radii` maps SpawnOrder.entry_id to
    the radius placement uses for that ship."""
    import App
    global _qb, _next_key
    _qb = qb
    _radii.update(radii)
    by_delay: dict = {}
    for n, order in late_orders:
        by_delay.setdefault(order.warp_in_s, []).append((n, order))
    if not by_delay:
        return
    _register_handler(qb.g_pXO)
    now = App.g_kUtopiaModule.GetGameTime()
    for delay in sorted(by_delay):
        _next_key += 1
        evt = App.TGIntEvent_Create()
        evt.SetEventType(_event_type())
        evt.SetDestination(qb.g_pXO)
        evt.SetInt(_next_key)
        timer = App.TGTimer_Create()
        timer.SetTimerStart(now + delay)
        timer.SetDelay(0)
        timer.SetDuration(0)
        timer.SetEvent(evt)
        _pending[_next_key] = {"orders": by_delay[delay],
                               "timer": App.g_kTimerManager.AddTimer(timer)}


def cancel_all() -> None:
    """Delete every pending arrival timer and forget its orders."""
    if _pending:
        import App
        for entry in _pending.values():
            App.g_kTimerManager.DeleteTimer(entry["timer"])
    _pending.clear()
    _radii.clear()


def reset() -> None:
    """Mission swap / host teardown / test isolation."""
    global _qb, _xo_registered, _rng, _ET
    try:
        cancel_all()
    except Exception as e:
        _log.warning("quickbattle: late arrival reset could not delete timers: %s", e)
        _pending.clear()
        _radii.clear()
    _qb = None
    _xo_registered = None
    _ET = None
    _rng = random.Random()


def check_win(qb) -> None:
    """QuickBattle.ShipDestroyed's win branch (QuickBattle.py:3356-3367)."""
    if qb.g_iNumEnemies == 0 and qb.bInSimulation and qb.bWonOrLost == 0:
        qb.bWonOrLost = 1
        qb.GenerateWinSequence()
        import BridgeHandlers
        BridgeHandlers.DropMenusTurnBack()
        qb.g_pXO.MenuUp()


OTHER_CALLOUT_KEY = "gs025"
_callout_warned: set = set()


def enemy_callout_key(n_arrived: int, enemies_already: bool):
    """Spec §6.7: the tactical officer's Incoming line, or None for no enemies."""
    if n_arrived <= 0:
        return None
    if enemies_already:
        return "Incoming6"
    return "Incoming%d" % min(n_arrived, 5)


def _warn_once(what: str) -> None:
    if what not in _callout_warned:
        _callout_warned.add(what)
        _log.warning("quickbattle: arrival callout skipped: %s", what)


def _say(qb, char_attr: str, key: str) -> None:
    import App
    char = getattr(qb, char_attr, None)
    if char is None:
        _warn_once("no %s" % char_attr)
        return
    db = None if char.GetDatabase() is not None else getattr(qb, "g_pGeneralDatabase", None)
    if db is None and char.GetDatabase() is None:
        _warn_once("no database for %s" % char_attr)
        return
    line = App.CharacterAction_Create(char, App.CharacterAction.AT_SAY_LINE,
                                      key, "Captain", 1, db)
    seq = App.TGSequence_Create()
    seq.AddAction(line)
    seq.Play()


def callout(qb, arrived: dict, enemies_already: bool) -> None:
    """Crew callout for one arrival tick: one line per side (spec §6.7)."""
    key = enemy_callout_key(arrived.get("enemy", 0), enemies_already)
    if key is not None:
        try:
            _say(qb, "g_pTact", key)
        except Exception as e:
            _log.error("quickbattle: enemy callout failed: %s", e)
    if arrived.get("other", 0) > 0:
        try:
            _say(qb, "g_pSci", OTHER_CALLOUT_KEY)
        except Exception as e:
            _log.error("quickbattle: friendly callout failed: %s", e)


def on_timer(pObject, pEvent) -> None:
    """XO instance handler for an arrival timer; `pEvent.GetInt()` is the key."""
    try:
        _arrive(pEvent.GetInt())
    except Exception as e:
        _log.error("quickbattle: late arrival failed: %s", e)
    pObject.CallNextHandler(pEvent)


def _uncount(qb, order) -> None:
    if order.allegiance == "enemy":
        qb.g_iNumEnemies = qb.g_iNumEnemies - 1
    elif order.allegiance == "friendly":
        qb.g_iNumFriends = qb.g_iNumFriends - 1


def _arrive(key) -> None:
    import App
    qb = _qb
    if qb is None or key not in _pending or not getattr(qb, "bInSimulation", 0):
        _pending.pop(key, None)
        return
    enemies_before = qb.g_iNumEnemies - pending_enemy_count()
    orders = _pending.pop(key)["orders"]
    pSet = qb.g_pSet                       # read now: ChangeRegion may swap it
    game = App.Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    if pSet is None or player is None:
        _log.error("quickbattle: %d late ship(s) cannot arrive (no battle set or "
                   "player); un-counting them", len(orders))
        for _n, order in orders:
            _uncount(qb, order)
        check_win(qb)
        return
    arrived = {"enemy": 0, "other": 0}
    try:
        for members in _by_group(orders):
            results: list = []                  # (order, spawned), member order
            try:
                _arrive_group(qb, pSet, player, members, results)
            except Exception as e:
                # Group setup (or bookkeeping) raised: every member it had not
                # reached yet is un-counted, so the battle stays winnable.
                _log.error("quickbattle: late group %s failed: %s",
                           members[0][1].group_id, e)
                results.extend((order, False) for _n, order in members[len(results):])
            for order, ok in results:
                if ok:
                    arrived["enemy" if order.allegiance == "enemy" else "other"] += 1
                else:
                    _uncount(qb, order)
    finally:
        try:
            callout(qb, arrived, enemies_before > 0)
        except Exception as e:
            _log.error("quickbattle: late arrival callout failed: %s", e)
        check_win(qb)


def _by_group(orders) -> list:
    groups: dict = {}
    for n, order in orders:
        groups.setdefault(order.group_id, []).append((n, order))
    return list(groups.values())


def _arrive_group(qb, pSet, player, members, out) -> None:
    """Create one group's ships on warp-in placements, appending
    (order, spawned) to `out` in member order as each one is decided."""
    import App
    from engine.quickbattle import placement, scenario, spawn
    ppos = spawn._vec(player.GetWorldLocation())
    cols = spawn._cols(player.GetWorldRotation())
    direction = _rng.choice(scenario.DIRECTIONS)
    radii = [_radii.get(order.entry_id, 0.0) for _n, order in members]
    positions = placement.group_positions(ppos, cols, direction,
                                          members[0][1].distance_gu, radii)
    lateral = placement.lateral_for(direction, cols)
    placed = [(ppos, player.GetRadius())]
    for obj in pSet.GetClassObjectList(App.CT_DAMAGEABLE_OBJECT):
        if obj is not player:
            placed.append((spawn._vec(obj.GetWorldLocation()), obj.GetRadius()))
    for (n, order), pos, r in zip(members, positions, radii):
        ok = False
        try:
            final = spawn._resolve_position(qb, pos, r, lateral, placed,
                                            label=order.title)
            placed.append((final, r))
            ok = _spawn_one(qb, pSet, player, ppos, cols, n, order, final)
        except Exception as e:
            _log.error("quickbattle: late ship %s (%s) failed: %s",
                       order.title, order.ship_file, e)
        out.append((order, ok))
    for _n, order in members[len(out):]:
        _log.error("quickbattle: no arrival position for late ship %s (%s)",
                   order.title, order.ship_file)
        out.append((order, False))


def _spawn_one(qb, pSet, player, ppos, cols, n, order, pos) -> bool:
    import App
    import loadspacehelper
    from engine.quickbattle import naming, spawn
    name = naming.object_name(order.title, n)
    pname = "QB warp in %s %d" % (order.group_id, n)
    plc = App.PlacementObject_Create(pname, pSet.GetName(), None)
    plc.SetTranslate(App.TGPoint3(*pos))
    spawn._face(plc, pos, player, ppos, cols, order.allegiance)
    plc.UpdateNodeOnly()
    ship = loadspacehelper.CreateShip(order.ship_file, pSet, name, pname, 1)
    if ship is None or App.IsNull(ship):
        _log.error("quickbattle: late ship %s (%s) did not spawn", name, order.ship_file)
        return False
    # The ship exists from here on, so it stays counted: g_kShips gets its
    # row (ShipDestroyed un-counts it on death) and every other step only
    # logs on failure.
    side = spawn._SIDE.get(order.allegiance)
    ai = None
    if side is not None:
        try:
            ai, msg = spawn._details(qb, order.class_id, side)
        except Exception as e:
            _log.error("quickbattle: no AI details for %s, using BC's fallback: %s",
                       name, e)
            ai, msg = spawn._FALLBACK[side]
        qb.g_kShips[ship.GetObjID()] = (ai, msg, side, order.ai_level)
    try:
        spawn._apply_identity(ship, order, name)
        if side is None:
            App.Game_GetCurrentGame().GetCurrentEpisode().GetCurrentMission() \
                .GetNeutralGroup().AddName(ship.GetName())
        else:
            (qb.pEnemies if side == "Enemy" else qb.pFriendlies).AddName(ship.GetName())
            # StartSimulation2's AI loop (QuickBattle.py:3113-3124), one ship.
            qb.g_iCurrentAILevel = order.ai_level
            ship.SetAI(__import__(ai).CreateAI(ship), 0, 0)
        pm = pSet.GetProximityManager()
        if pm:
            pm.UpdateObject(ship)
    except Exception as e:
        _log.error("quickbattle: late ship %s arrived but its setup failed: %s", name, e)
    return True
