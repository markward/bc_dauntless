"""A station the player attacks twice within a minute turns hostile.

Spec: docs/superpowers/specs/2026-10-26-station-self-defence-design.md
(§5.1 what a station is, §5.2 what counts as a hit, §5.3 turning hostile, §6).

The rule, active only while Quick Battle (free roam included) is running:

* a STATION is a ship whose ship property is stationary, or a home station
  (never genus: that takes in comm arrays and lights);
* a HIT is an ET_WEAPON_HIT fired by the current player at a station, with a
  phaser or torpedo weapon type and damage above 0 (shield hits count);
* counted hits are at least HIT_GAP_S apart, in game time; two counted hits
  within WINDOW_S turn the station hostile.

Turning hostile records the station in a register (the readable fact other
systems ask), swaps its name from the friendly/neutral groups into the REAL
enemy group, and gives an ARMED station BC's StarbaseAttack AI aimed at the
mission's friendly group by NAME. An unarmed station's AI is never touched.
Stations are never put in QuickBattle.g_kShips: they neither count towards nor
block a battle's win.

This module only turns stations hostile; ending hostility is a later step.
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


def _system_of(station) -> str:
    from engine.appc import sector_model
    return sector_model.system_id_for_set(station.GetContainingSetName())


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
        record.replaced_ai = True
        station.SetAI(AI.Compound.StarbaseAttack.CreateAI(
            station,
            App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies")))


def _count(station, now) -> None:
    oid = station.GetObjID()
    times = _counts.setdefault(oid, [])
    if times and now - times[-1] < HIT_GAP_S:
        return
    times.append(now)
    if len([t for t in times if now - t <= WINDOW_S]) >= 2:
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
                and not _in_enemy_group(station)
                and station.GetObjID() not in _register):
            _count(station, _game_time())
    _pass_on(pObject, pEvent)


def _in_enemy_group(station) -> bool:
    mission = _mission()
    return mission is not None and bool(
        mission.GetEnemyGroup().IsNameInGroup(station.GetName()))


def on_entered_set(pObject, pEvent) -> None:
    """Broadcast handler for ET_ENTERED_SET (body added by a later step)."""
    _pass_on(pObject, pEvent)


def is_hostile(station) -> bool:
    _prune()
    return station is not None and station.GetObjID() in _register


def hostile_stations(system: str | None = None) -> list:
    _prune()
    return [r for r in _register.values()
            if system is None or r.system == system]


def _prune() -> None:
    for oid, record in list(_register.items()):
        if record.station.IsDying():
            del _register[oid]
            _counts.pop(oid, None)
