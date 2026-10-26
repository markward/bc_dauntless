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


def hit(w, station, t, source=None, weapon="phaser", aim=True):
    """One hit through combat.apply_hit. `aim` makes the current player target
    the station first (a hit only counts on the player's current target)."""
    w.clock.t = t
    current = App.Game_GetCurrentGame().GetPlayer()
    if aim and current is not None:
        current.SetTarget(station)
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


# ── ending hostility ─────────────────────────────────────────────────────────

def go_to(w, set_name, t=None):
    """Move the player into a (new or existing) set, as BC's AddObjectToSet."""
    if t is not None:
        w.clock.t = t
    target = App.g_kSetManager.GetSet(set_name)
    if target is None:
        target = App.SetClass_Create()
        App.g_kSetManager.AddSet(target, set_name)
    w.player.GetContainingSet().RemoveObjectFromSet(w.player.GetName())
    target.AddObjectToSet(w.player, w.player.GetName())
    return target


def turn(w, station, t=0.0):
    hit(w, station, t)
    hit(w, station, t + 5.0)
    assert sh.is_hostile(station)


def test_entering_a_set_in_another_system_restores(world):
    world.mission.GetFriendlyGroup().AddName("Starbase 12")
    turn(world, world.starbase)
    go_to(world, "Savoy1")
    assert not sh.is_hostile(world.starbase)
    assert not enemies(world).IsNameInGroup("Starbase 12")
    assert world.mission.GetFriendlyGroup().IsNameInGroup("Starbase 12")
    assert world.starbase.GetAI() is None


def test_entering_another_region_of_the_system_keeps_it(world):
    turn(world, world.starbase)
    go_to(world, "DryDock")
    assert sh.is_hostile(world.starbase)
    assert enemies(world).IsNameInGroup("Starbase 12")


def test_entering_the_warp_set_keeps_it(world):
    turn(world, world.starbase)
    go_to(world, "warp")
    assert sh.is_hostile(world.starbase)


def qb_level():
    import QuickBattle.QuickBattle as qb
    return qb.g_iCurrentAILevel


def test_restoring_brings_back_a_quick_battle_ai(world):
    import QuickBattle.QuickBattle as qb
    qb.g_kShips[world.starbase.GetObjID()] = (
        "StarbaseFriendlyAI", "gs", "Friendly", 2)
    try:
        turn(world, world.starbase)
        hostile_ai = world.starbase.GetAI()
        assert "StarbaseAttack" in ai_modules(hostile_ai)
        go_to(world, "Savoy1")
    finally:
        qb.g_kShips.pop(world.starbase.GetObjID(), None)
    restored = world.starbase.GetAI()
    # StarbaseFriendlyAI builds its own StarbaseAttack (aimed at pEnemies):
    # what proves it is the QB one is a fresh tree, built at the recorded level.
    assert restored is not None and restored is not hostile_ai
    assert restored.GetName() == "Wait"   # StarbaseFriendlyAI root, not StarbaseAttack
    assert qb_level() == 2


def test_a_destroyed_hostile_station_is_dropped(world):
    turn(world, world.starbase)
    world.starbase._dead = True
    go_to(world, "Savoy1")
    assert sh.hostile_stations() == []


def test_a_dead_station_is_pruned_on_read(world):
    turn(world, world.starbase)
    world.starbase._dead = True
    assert sh.hostile_stations() == []


def test_reset_forgets_without_restoring(world):
    turn(world, world.starbase)
    sh.reset()
    assert enemies(world).IsNameInGroup("Starbase 12")
    assert sh.hostile_stations() == []
    assert sh._active is False


def test_leaving_clears_part_counts(world):
    hit(world, world.starbase, 0.0)
    go_to(world, "Savoy1")
    go_to(world, "Starbase12")
    hit(world, world.starbase, 6.0)
    assert not sh.is_hostile(world.starbase)


def test_counts_are_trimmed_to_the_window(world):
    for i in range(4):
        hit(world, world.starbase, 100.0 * i)
    assert len(next(iter(sh._counts.values()))) <= 2


def test_an_old_ship_hit_after_a_rebuild_still_counts(world):
    import loadspacehelper
    old = world.player
    hit(world, world.starbase, 0.0)
    new = loadspacehelper.CreateShip("Galaxy", world.sb_set, "Player2", "")
    # Both ships end up named "Player": rename around the name clash, so the
    # OLD ship (not the current player object) is matched by name alone.
    new.SetName("Other")
    old.SetName("Other2")
    new.SetName("Player")
    old.SetName("Player")
    world.game.SetPlayer(new)
    hit(world, world.starbase, 6.0, source=old)
    assert sh.is_hostile(world.starbase)


def test_a_hit_with_no_damage_does_not_count(world):
    world.clock.t = 0.0
    from engine.appc.events import WeaponHitEvent
    for t in (0.0, 6.0):
        world.clock.t = t
        ev = WeaponHitEvent()
        ev.SetEventType(App.ET_WEAPON_HIT)
        ev.SetTarget(world.starbase)
        ev.SetSource(world.player)
        ev.SetWeaponType(WeaponHitEvent.PHASER)
        ev.SetDamage(0.0)
        sh.on_weapon_hit(None, ev)
    assert not sh.is_hostile(world.starbase)


def test_neutral_membership_is_restored(world):
    world.mission.GetNeutralGroup().AddName("Starbase 12")
    turn(world, world.starbase)
    rec, = sh.hostile_stations()
    assert rec.prior_groups == ("neutral",)
    go_to(world, "Savoy1")
    assert world.mission.GetNeutralGroup().IsNameInGroup("Starbase 12")
    assert not enemies(world).IsNameInGroup("Starbase 12")


def test_no_mission_does_not_raise(world, monkeypatch):
    monkeypatch.setattr(sh, "_mission", lambda: None)
    sh._turn_hostile(world.starbase, 1.0)
    assert sh.hostile_stations() == []


def test_install_wraps_once_and_clears_on_end_and_start(world):
    import types
    calls = []
    qb = types.ModuleType("fakeqb")
    qb.StartSimulation2 = lambda *a: calls.append("start")
    qb.EndSimulation = lambda *a: calls.append("end")
    sh.reset()
    assert sh.install(qb) is True
    assert sh._active is True
    assert sh.install(qb) is False
    for name in ("StartSimulation2", "EndSimulation"):
        assert hasattr(getattr(qb, name), "_dauntless_station_hostility_orig")
    turn(world, world.starbase)
    qb.EndSimulation()
    assert calls == ["end"]
    assert not sh.is_hostile(world.starbase)
    assert not enemies(world).IsNameInGroup("Starbase 12")
    turn(world, world.starbase, 100.0)
    qb.StartSimulation2()
    assert calls == ["end", "start"]
    assert not sh.is_hostile(world.starbase)


# ── final-review fixes ───────────────────────────────────────────────────────

def test_a_hit_counts_only_on_the_players_target(world):
    hit(world, world.starbase, 0.0, aim=False)
    hit(world, world.starbase, 6.0, aim=False)
    assert not sh.is_hostile(world.starbase)
    world.player.SetTarget(world.drydock)
    hit(world, world.starbase, 12.0, aim=False)
    hit(world, world.starbase, 20.0, aim=False)
    assert not sh.is_hostile(world.starbase)
    assert sh._counts == {}
    hit(world, world.starbase, 30.0)
    hit(world, world.starbase, 40.0)
    assert sh.is_hostile(world.starbase)


def test_a_dead_hostile_station_leaves_the_enemy_group_on_end(world):
    world.mission.GetFriendlyGroup().AddName("Starbase 12")
    turn(world, world.starbase)
    world.starbase._dead = True
    sh.end_all()
    assert not enemies(world).IsNameInGroup("Starbase 12")
    assert world.mission.GetFriendlyGroup().IsNameInGroup("Starbase 12")


def test_a_dying_hostile_station_leaves_the_enemy_group_on_end(world):
    world.mission.GetNeutralGroup().AddName("Starbase 12")
    turn(world, world.starbase)
    world.starbase._dying = True
    sh.end_all()
    assert not enemies(world).IsNameInGroup("Starbase 12")
    assert world.mission.GetNeutralGroup().IsNameInGroup("Starbase 12")


def test_a_dead_hostile_station_leaves_the_enemy_group_on_prune(world):
    world.mission.GetFriendlyGroup().AddName("Starbase 12")
    turn(world, world.starbase)
    world.starbase._dead = True
    assert sh.hostile_stations() == []
    assert not enemies(world).IsNameInGroup("Starbase 12")
    assert world.mission.GetFriendlyGroup().IsNameInGroup("Starbase 12")


def test_end_all_clears_every_hit_count(world):
    hit(world, world.starbase, 0.0)
    assert sh._counts and sh._count_system
    sh.end_all()
    assert sh._counts == {} and sh._count_system == {}
    hit(world, world.starbase, 6.0)
    assert not sh.is_hostile(world.starbase)


def test_count_system_goes_with_counts(world):
    turn(world, world.starbase)
    sh.end_in_system("tauceti")
    assert sh._count_system == {}
    turn(world, world.starbase, 100.0)
    world.starbase._dead = True
    sh.hostile_stations()
    assert sh._counts == {} and sh._count_system == {}
