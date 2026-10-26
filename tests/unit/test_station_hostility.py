"""A station the player attacks twice within a minute turns hostile.

Hits go through the real combat.apply_hit; stations are the real home stations
BC's own region scripts place, in a real mapped set.
"""
import pytest

import App
from engine.appc import combat
from engine.appc.events import WeaponHitEvent
from engine.systems import home_stations as hs
from engine.systems import station_hostility as sh
from tests.helpers.fresh_world import _fresh_world
from tests.helpers.mapped_regions import load_region

HANDLER = "engine.systems.station_hostility.on_weapon_hit"


class Clock:
    t = 0.0


@pytest.fixture
def world(monkeypatch):
    game = _fresh_world()
    hs.reset()
    sh.reset()
    import loadspacehelper
    sb_set = load_region("TauCeti", "Starbase12")
    dd_set = load_region("TauCeti", "DryDock")
    player = loadspacehelper.CreateShip("Galaxy", sb_set, "Player", "")
    game.SetPlayer(player)
    clock = Clock()
    clock.t = 0.0
    monkeypatch.setattr(sh, "_game_time", lambda: clock.t)
    mission = game.GetCurrentEpisode().GetCurrentMission()
    for g in (mission.GetFriendlyGroup(), mission.GetEnemyGroup(),
              mission.GetNeutralGroup()):
        g.RemoveAllNames()
    sh.activate()

    class W:
        pass
    w = W()
    w.game, w.player, w.clock, w.mission = game, player, clock, mission
    w.sb_set, w.dd_set = sb_set, dd_set
    w.starbase = App.ShipClass_GetObject(sb_set, "Starbase 12")
    w.drydock = App.ShipClass_GetObject(dd_set, "Dry Dock")
    w.facility = App.ShipClass_GetObject(dd_set, "Station")
    yield w
    sh.reset()
    hs.reset()


def hit(w, station, t, source=None, weapon="phaser"):
    w.clock.t = t
    combat.apply_hit(station, 50.0, station.GetWorldLocation(),
                     source if source is not None else w.player,
                     weapon_type=weapon)


def enemies(w):
    return w.mission.GetEnemyGroup()


def ai_modules(ai, out=None):
    out = [] if out is None else out
    if ai is None:
        return out
    if hasattr(ai, "GetScriptModule"):
        out.append(ai.GetScriptModule())
    for child in getattr(ai, "GetAIs", lambda: [])():
        ai_modules(child, out)
    if hasattr(ai, "GetContainedAI"):
        ai_modules(ai.GetContainedAI(), out)
    return out


def test_fixture_stations_are_what_we_think(world):
    assert world.starbase is not None and world.drydock is not None
    assert world.facility is not None
    assert world.facility.IsStationary() == 0
    assert hs.home_station_of(world.facility) is not None


def test_one_sweep_never_turns_a_station(world):
    for i in range(10):
        hit(world, world.starbase, i * 0.5)
    assert not sh.is_hostile(world.starbase)
    assert not enemies(world).IsNameInGroup("Starbase 12")


def test_two_hits_five_seconds_apart_turn_it(world):
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 5.0)
    assert sh.is_hostile(world.starbase)
    assert enemies(world).IsNameInGroup("Starbase 12")
    rec, = sh.hostile_stations()
    assert rec.name == "Starbase 12" and rec.system == "tauceti"
    assert rec.since == 5.0


def test_hits_more_than_a_minute_apart_do_not(world):
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 61.0)
    assert not sh.is_hostile(world.starbase)
    hit(world, world.starbase, 66.0)
    assert sh.is_hostile(world.starbase)


def test_shield_only_hits_count(world):
    seen = []
    orig = sh.on_weapon_hit
    # Record the hull flag the real events carry, then let the real handler run.
    def wrapped(pObject, pEvent):
        seen.append(pEvent.IsHullHit())
        return orig(pObject, pEvent)
    sh.on_weapon_hit = wrapped
    try:
        hit(world, world.starbase, 0.0)
        hit(world, world.starbase, 5.0)
    finally:
        sh.on_weapon_hit = orig
    assert seen == [0, 0]
    assert sh.is_hostile(world.starbase)


@pytest.mark.parametrize("weapon", ["tractor", "collision"])
def test_tractor_and_collision_never_count(world, weapon):
    for i in range(3):
        hit(world, world.starbase, i * 10.0, weapon=weapon)
    assert not sh.is_hostile(world.starbase)
    hit(world, world.starbase, 40.0)
    assert not sh.is_hostile(world.starbase)


def test_npc_fire_never_counts(world):
    import loadspacehelper
    npc = loadspacehelper.CreateShip("Galor", world.sb_set, "Raider", "")
    hit(world, world.starbase, 0.0, source=npc)
    hit(world, world.starbase, 10.0, source=npc)
    assert not sh.is_hostile(world.starbase)


def test_spacefacility_counts_as_a_station(world):
    hit(world, world.facility, 0.0)
    hit(world, world.facility, 6.0)
    assert sh.is_hostile(world.facility)


def test_a_non_station_never_counts(world):
    import loadspacehelper
    other = loadspacehelper.CreateShip("Galor", world.sb_set, "Raider", "")
    assert not sh.is_station(other)
    hit(world, other, 0.0)
    hit(world, other, 10.0)
    assert not sh.is_hostile(other)


def test_an_enemy_station_is_untouched(world):
    enemies(world).AddName("Starbase 12")
    before = world.starbase.GetAI()
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 10.0)
    assert not sh.is_hostile(world.starbase)
    assert sh.hostile_stations() == []
    assert world.starbase.GetAI() is before


def test_armed_station_gets_starbase_attack(world):
    assert world.starbase.GetAI() is None
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 5.0)
    assert world.starbase.GetAI() is not None
    assert "StarbaseAttack" in ai_modules(world.starbase.GetAI())
    rec, = sh.hostile_stations()
    assert rec.replaced_ai is True and rec.prior_ai is None


def test_unarmed_station_gets_no_ai(world):
    hit(world, world.drydock, 0.0)
    hit(world, world.drydock, 5.0)
    assert sh.is_hostile(world.drydock)
    assert world.drydock.GetAI() is None
    rec, = sh.hostile_stations()
    assert rec.replaced_ai is False and rec.prior_ai is None


def test_armed_station_with_a_quick_battle_ai_records_it(world):
    import QuickBattle.QuickBattle as qb
    qb.g_kShips[world.starbase.GetObjID()] = (
        "StarbaseFriendlyAI", "gs", "Friendly", 2)
    try:
        hit(world, world.starbase, 0.0)
        hit(world, world.starbase, 5.0)
    finally:
        qb.g_kShips.pop(world.starbase.GetObjID(), None)
    rec, = sh.hostile_stations()
    assert rec.prior_ai == ("StarbaseFriendlyAI", 2)
    assert rec.replaced_ai is True


def test_prior_groups_are_recorded(world):
    world.mission.GetFriendlyGroup().AddName("Starbase 12")
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 5.0)
    rec, = sh.hostile_stations()
    assert rec.prior_groups == ("friendly",)
    assert not world.mission.GetFriendlyGroup().IsNameInGroup("Starbase 12")
    assert enemies(world).IsNameInGroup("Starbase 12")


def test_inactive_does_nothing(world):
    sh.deactivate()
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 10.0)
    assert not sh.is_hostile(world.starbase)
    sh.activate()
    hit(world, world.starbase, 20.0)
    assert not sh.is_hostile(world.starbase)   # the earlier hits never counted


def test_activate_twice_registers_once(world):
    sh.activate()
    names = [n for _d, n, _t in
             App.g_kEventManager._broadcast_handlers[App.ET_WEAPON_HIT]]
    assert names.count(HANDLER) == 1


def test_hits_from_a_rebuilt_player_count(world):
    import loadspacehelper
    hit(world, world.starbase, 0.0)
    world.player.SetName("Old")
    new = loadspacehelper.CreateShip("Galaxy", world.sb_set, "Player2", "")
    new.SetName("Player")
    world.game.SetPlayer(new)
    hit(world, world.starbase, 6.0, source=new)
    assert sh.is_hostile(world.starbase)


def test_no_player_is_harmless(world):
    world.game.SetPlayer(None)
    world.clock.t = 0.0
    hit(world, world.starbase, 0.0, source=world.player)
    hit(world, world.starbase, 10.0, source=world.player)
    assert not sh.is_hostile(world.starbase)


def test_destroyed_stations_are_pruned_on_read(world):
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 5.0)
    world.starbase._dying = True
    assert sh.hostile_stations() == []
    assert not sh.is_hostile(world.starbase)


def test_hostile_stations_filters_by_system(world):
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 5.0)
    assert len(sh.hostile_stations("tauceti")) == 1
    assert sh.hostile_stations("vesuvi") == []


def test_reset_forgets_and_deactivates(world):
    hit(world, world.starbase, 0.0)
    hit(world, world.starbase, 5.0)
    sh.reset()
    assert sh.hostile_stations() == []
    assert enemies(world).IsNameInGroup("Starbase 12")
