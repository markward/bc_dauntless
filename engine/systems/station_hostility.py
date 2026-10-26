"""A station the player attacks twice within a minute turns hostile.

Spec: docs/superpowers/specs/2026-10-26-station-self-defence-design.md
(§5.1 what a station is, §5.2 what counts as a hit, §5.3 turning hostile, §6).

The rule, active only while Quick Battle (free roam included) is running:

* a STATION is a ship whose ship property is stationary, or a home station
  (never genus: that takes in comm arrays and lights);
* a HIT is an ET_WEAPON_HIT fired by the current player at a station that is
  the player's current target, with a phaser or torpedo weapon type and damage
  above 0 (shield hits count);
* counted hits are at least HIT_GAP_S apart, in game time; two counted hits
  within WINDOW_S turn the station hostile.

Turning hostile records the station in a register (the readable fact other
systems ask), swaps its name from the friendly/neutral groups into the REAL
enemy group, and gives an ARMED station BC's StarbaseAttack AI aimed at the
mission's friendly group by NAME. An unarmed station's AI is never touched.
Stations are never put in QuickBattle.g_kShips: they neither count towards nor
block a battle's win.

Hostility ends when the player enters a set in another system (a station's
counted hits are forgotten then too), and when a battle starts or ends.
"""
from __future__ import annotations

from dataclasses import dataclass

HIT_GAP_S: float = 5.0
WINDOW_S: float = 60.0

_HANDLER_HIT = "engine.systems.station_hostility.on_weapon_hit"
_HANDLER_ENTER = "engine.systems.station_hostility.on_entered_set"


@dataclass
class Hostility:
    station: object
    name: str
    system: str
    since: float
    prior_groups: tuple = ()
    # (QB AI module leaf, AI level) of the AI that was replaced; None when the
    # station had none (a home station) or its AI was never replaced.
    prior_ai: tuple | None = None
    # True only when the station's AI was replaced (an armed station).
    replaced_ai: bool = False


_active: bool = False
_counts: dict = {}      # station obj id -> counted hit times (game time)
_register: dict = {}    # station obj id -> Hostility
_count_system: dict = {}  # station obj id -> system key its hits were made in


def _game_time() -> float:
    import App
    return App.g_kUtopiaModule.GetGameTime()


def _mission():
    import App
    game = App.Game_GetCurrentGame()
    if game is None:
        return None
    episode = game.GetCurrentEpisode()
    return episode.GetCurrentMission() if episode is not None else None


def _register_handler(event_type, mission, name) -> None:
    import App
    for _dest, registered, _filter in App.g_kEventManager._broadcast_handlers.get(
            event_type, []):
        if registered == name:
            return
    App.g_kEventManager.AddBroadcastPythonFuncHandler(event_type, mission, name)


def activate() -> None:
    """Turn the rule on and register the broadcast handlers (once)."""
    global _active
    import App
    _active = True
    mission = _mission()
    _register_handler(App.ET_WEAPON_HIT, mission, _HANDLER_HIT)
    _register_handler(App.ET_ENTERED_SET, mission, _HANDLER_ENTER)


def deactivate() -> None:
    global _active
    _active = False


def reset() -> None:
    """Forget every hit and the register, and deactivate. Restores nothing."""
    deactivate()
    _counts.clear()
    _count_system.clear()
    _register.clear()


def is_station(ship) -> bool:
    from engine.systems import home_stations
    if ship is None:
        return False
    stationary = getattr(ship, "IsStationary", None)
    if stationary is not None and stationary():
        return True
    return home_stations.home_station_of(ship) is not None


def _is_player(source) -> bool:
    import App
    player = App.Game_GetCurrentGame().GetPlayer() if App.Game_GetCurrentGame() else None
    if player is None or source is None:
        return False
    return source is player or source.GetName() == player.GetName()


def _system_key(set_name: str) -> str:
    from engine.appc import sector_model
    return sector_model.system_id_for_set(set_name) or set_name


def _system_of(station) -> str:
    return _system_key(station.GetContainingSetName())


def _armed(station) -> bool:
    return any(getter() is not None for getter in (
        station.GetPhaserSystem, station.GetTorpedoSystem,
        station.GetPulseWeaponSystem))


def _prior_quick_battle_ai(station):
    try:
        import QuickBattle.QuickBattle as qb
    except ImportError:
        return None
    entry = getattr(qb, "g_kShips", {}).get(station.GetObjID())
    if entry is None:
        return None
    return (entry[0], entry[3])


def _turn_hostile(station, now) -> None:
    import App
    mission = _mission()
    if mission is None:
        return
    name = station.GetName()
    prior_groups = []
    for label, group in (("friendly", mission.GetFriendlyGroup()),
                         ("neutral", mission.GetNeutralGroup())):
        if group.IsNameInGroup(name):
            group.RemoveName(name)
            prior_groups.append(label)
    mission.GetEnemyGroup().AddName(name)
    record = Hostility(station, name, _system_of(station), now,
                       tuple(prior_groups))
    _register[station.GetObjID()] = record
    if _armed(station):
        import AI.Compound.StarbaseAttack
        record.prior_ai = _prior_quick_battle_ai(station)
        station.SetAI(AI.Compound.StarbaseAttack.CreateAI(
            station,
            App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies")))
        record.replaced_ai = True


def _count(station, now) -> None:
    oid = station.GetObjID()
    times = _counts.setdefault(oid, [])
    _count_system[oid] = _system_of(station)
    if times and now - times[-1] < HIT_GAP_S:
        return
    times.append(now)
    times[:] = [t for t in times if now - t <= WINDOW_S]
    if len(times) >= 2:
        _turn_hostile(station, now)


def _pass_on(pObject, pEvent) -> None:
    call_next = getattr(pObject, "CallNextHandler", None)
    if call_next is not None:
        call_next(pEvent)


def on_weapon_hit(pObject, pEvent) -> None:
    """Broadcast handler for ET_WEAPON_HIT."""
    from engine.appc.events import WeaponHitEvent
    if _active:
        station = pEvent.GetTarget()
        if (is_station(station)
                and pEvent.GetWeaponType() in (WeaponHitEvent.PHASER,
                                               WeaponHitEvent.TORPEDO)
                and pEvent.GetDamage() > 0
                and _is_player(pEvent.GetSource())
                and _is_players_target(station)
                and not _in_enemy_group(station)
                and station.GetObjID() not in _register):
            _count(station, _game_time())
    _pass_on(pObject, pEvent)


def _is_players_target(station) -> bool:
    """A stray shot at a station the player is not aiming at is no intent."""
    import App
    game = App.Game_GetCurrentGame()
    player = game.GetPlayer() if game else None
    target = player.GetTarget() if player is not None else None
    return target is not None and (
        target is station or target.GetName() == station.GetName())


def _in_enemy_group(station) -> bool:
    mission = _mission()
    return mission is not None and bool(
        mission.GetEnemyGroup().IsNameInGroup(station.GetName()))


def on_entered_set(pObject, pEvent) -> None:
    """Broadcast handler for ET_ENTERED_SET: the player entering a set in
    another system ends hostility there (the warp transit set is no
    destination)."""
    from engine.appc import warp
    if _active:
        ship = pEvent.GetDestination()
        if ship is not None and _is_player(ship):
            where = ship.GetContainingSet()
            name = where.GetName() if where is not None else None
            if name and name != warp._WARP_TRANSIT_SET_NAME:
                _left_for(_system_key(name))
    _pass_on(pObject, pEvent)


def _left_for(system: str) -> None:
    for oid, record in list(_register.items()):
        if record.system != system:
            end_in_system(record.system)
    for oid in list(_counts):
        if oid not in _register and _count_system.get(oid) != system:
            _forget_counts(oid)


def _restore_ai(record) -> None:
    station = record.station
    if not record.replaced_ai:
        return
    if record.prior_ai is None:
        station.SetAI(None)
        return
    import importlib
    import QuickBattle.QuickBattle as qb
    leaf, level = record.prior_ai
    qb.g_iCurrentAILevel = level
    station.SetAI(importlib.import_module("QuickBattle." + leaf).CreateAI(station))


def _restore_groups(record) -> None:
    """Group membership is by NAME, so it is undone even for a dead station: a
    rebuilt station of the same name must not inherit the enemy flag."""
    mission = _mission()
    if mission is None:
        return
    name = record.name
    mission.GetEnemyGroup().RemoveName(name)
    for label in record.prior_groups:
        group = (mission.GetFriendlyGroup() if label == "friendly"
                 else mission.GetNeutralGroup())
        group.AddName(name)


def _restore(record) -> None:
    _restore_groups(record)
    if not (record.station.IsDead() or record.station.IsDying()):
        _restore_ai(record)


def _forget_counts(oid) -> None:
    _counts.pop(oid, None)
    _count_system.pop(oid, None)


def end_in_system(system: str) -> None:
    """Restore every hostile station of `system`: groups, then AI."""
    for oid, record in list(_register.items()):
        if record.system != system:
            continue
        del _register[oid]
        _forget_counts(oid)
        _restore(record)


def end_all() -> None:
    for system in {r.system for r in _register.values()}:
        end_in_system(system)
    _counts.clear()
    _count_system.clear()


_MARK = "_dauntless_station_hostility_orig"


def _chain(fn):
    seen = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        yield fn
        links = getattr(fn, "__dict__", {})
        fn = next((v for k, v in links.items()
                   if k.startswith("_dauntless_") and k.endswith("_orig")),
                  None)


def _wrap(qb, name) -> bool:
    current = qb.__dict__.get(name)
    if current is None or any(_MARK in getattr(f, "__dict__", {})
                              for f in _chain(current)):
        return False

    def wrapper(*args):
        try:
            end_all()
        except Exception:  # noqa: BLE001 - never stop BC's start/end
            import logging
            logging.getLogger(__name__).exception(
                "station hostility: restoring stations failed")
        return current(*args)
    wrapper.__name__ = name
    setattr(wrapper, _MARK, current)
    setattr(qb, name, wrapper)
    return True


def install(qb) -> bool:
    """Turn the rule on and clear hostility whenever a battle starts or ends.
    Returns True when a wrapper was added (never installed twice)."""
    activate()
    added = _wrap(qb, "StartSimulation2")
    return _wrap(qb, "EndSimulation") or added


def is_hostile(station) -> bool:
    _prune()
    return station is not None and station.GetObjID() in _register


def hostile_stations(system: str | None = None) -> list:
    _prune()
    return [r for r in _register.values()
            if system is None or r.system == system]


def _prune() -> None:
    for oid, record in list(_register.items()):
        if record.station.IsDying() or record.station.IsDead():
            del _register[oid]
            _forget_counts(oid)
            _restore_groups(record)
