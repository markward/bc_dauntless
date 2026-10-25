"""Quick Battle keeps owned objects (home stations and the like) in their set.

BC's ChangeRegion moves every ship in the player's set into the new battle
region; a placed home station would follow the player. The region-change tests
set `QB.g_sSelectedRegion` directly, standing in for BC's Change Combat Region
menu (the setup panel leaves it "" so the battle happens where the player is).
No coordinate is typed here: the station's saved location is read off the
station itself before the battle starts.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.helpers.headless_mission import no_logged_failures  # noqa: E402,F401
from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402,F401
    _do, _go, world)


def _into_region(system, region):
    """Build `region` through BC's own module and move the player into it."""
    import App
    from tests.helpers.mapped_regions import load_region
    pSet = load_region(system, region)
    player = App.Game_GetCurrentGame().GetPlayer()
    name = player.GetName()
    old = player.GetContainingSet()
    if old is not None:
        old.RemoveObjectFromSet(name)
    pSet.AddObjectToSet(player, name)
    player.PlaceObjectByName("Player Start")
    player.UpdateNodeOnly()
    return pSet


def _player():
    import App
    return App.Game_GetCurrentGame().GetPlayer()


def _loc(obj):
    w = obj.GetWorldLocation()
    return (w.x, w.y, w.z)


def _rot(obj):
    return obj.GetWorldRotation().as_tuple()


def _proximity_holds(pSet, obj):
    """`obj` is in the set's proximity index: the set-member read-through or a
    registered (AddObject/UpdateObject) entry."""
    return any(o is obj for o in pSet.GetProximityManager()._candidates())


def _crowd_every_spot_once(monkeypatch):
    """Make BC's ChangeRegion find each ship's first spot occupied, so its
    ChooseNewLocation loop really moves every ship (our IsLocationEmptyTG is a
    stub that always answers 1). `seen` holds the points so an id is never
    reused for a new one."""
    from engine.appc.sets import SetClass
    seen = []

    def IsLocationEmptyTG(self, point, radius, flag=1):
        if any(p is point for p in seen):
            return 1
        seen.append(point)
        return 0

    monkeypatch.setattr(SetClass, "IsLocationEmptyTG", IsLocationEmptyTG)


def _start_region_change(hl, panel, QB, region):
    QB.g_sSelectedRegion = region
    _do(panel, "add:Warbird")
    _go(hl, panel)


def test_a_battle_at_starbase_12_includes_the_station(world):
    hl, _c, panel, QB = world
    from engine.systems import home_stations as hs
    _into_region("TauCeti", "Starbase12")
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert QB.g_pSet.GetName() == "Starbase12"
    station = QB.g_pSet.GetObject("Starbase 12")
    assert station is not None
    assert hs.home_station_of(station) is not None


def test_a_region_change_leaves_the_station_home(world, monkeypatch):
    hl, _c, panel, QB = world
    import App
    pSet = _into_region("TauCeti", "Starbase12")
    station = pSet.GetObject("Starbase 12")
    saved, saved_rot = _loc(station), _rot(station)
    _crowd_every_spot_once(monkeypatch)
    _start_region_change(hl, panel, QB, "Belaruz1")
    assert _player().GetContainingSet().GetName() == "Belaruz1"
    home = App.g_kSetManager.GetSet("Starbase12")
    battle = App.g_kSetManager.GetSet("Belaruz1")
    assert home.GetObject("Starbase 12") is station
    assert station.GetContainingSet() is home
    assert _loc(station) == pytest.approx(saved, abs=1e-6)
    assert _rot(station) == pytest.approx(saved_rot, abs=1e-6)
    assert battle.GetObject("Starbase 12") is None
    # BC's loop UpdateObject'ed the station into the battle set's proximity
    # manager; it must not linger there, and its home set's must know it.
    assert not _proximity_holds(battle, station)
    assert station not in battle.GetProximityManager()._objects
    assert _proximity_holds(home, station)


def test_a_dupe_region_change_keeps_the_station_in_its_set(
        world, no_logged_failures):  # noqa: F811
    hl, _c, panel, QB = world
    import App
    old = _into_region("TauCeti", "Starbase12")
    station = old.GetObject("Starbase 12")
    saved = _loc(station)
    _start_region_change(hl, panel, QB, "Belaruz4")
    assert _player().GetContainingSet().GetName() == "Belaruz4"
    assert station.GetContainingSet() is old
    assert old.GetObject("Starbase 12") is station
    assert _loc(station) == pytest.approx(saved, abs=1e-6)
    assert App.g_kSetManager.GetSet("Belaruz4").GetObject("Starbase 12") is None


def test_a_failing_region_change_still_returns_the_station(world, monkeypatch):
    """The original moves and turns the station into the battle set, then
    raises: the station still goes home at its pose, and the exception still
    reaches the caller."""
    _hl, _c, _panel, QB = world
    import App
    from engine.appc.math import TGMatrix3, TGPoint3
    from engine.quickbattle import sim_restore
    from tests.helpers.mapped_regions import load_region
    home = _into_region("TauCeti", "Starbase12")
    station = home.GetObject("Starbase 12")
    saved, saved_rot = _loc(station), _rot(station)
    turned = TGMatrix3().MakeZRotation(1.0)
    assert turned.as_tuple() != pytest.approx(saved_rot, abs=1e-3)
    battle = load_region("Belaruz", "Belaruz1")

    def failing_change_region():
        home.RemoveObjectFromSet("Starbase 12")
        battle.AddObjectToSet(station, "Starbase 12")
        station.SetTranslate(TGPoint3(saved[0] + 50.0, saved[1], saved[2]))
        station.SetMatrixRotation(turned)
        station.UpdateNodeOnly()
        battle.GetProximityManager().UpdateObject(station)
        raise RuntimeError("region module blew up")

    monkeypatch.setattr(QB, "ChangeRegion", failing_change_region)
    assert sim_restore.install(QB) is True
    with pytest.raises(RuntimeError, match="region module blew up"):
        QB.ChangeRegion()
    assert station.GetContainingSet() is home
    assert home.GetObject("Starbase 12") is station
    assert battle.GetObject("Starbase 12") is None
    assert _loc(station) == pytest.approx(saved, abs=1e-6)
    assert _rot(station) == pytest.approx(saved_rot, abs=1e-6)
    assert station not in battle.GetProximityManager()._objects
    assert App.g_kSetManager.GetSet("Starbase12") is home


class _TestPatrolOwner:
    name = "test_patrol"

    def rebuild(self, old, record):
        return None

    def after_rebuild(self, new, record) -> None:
        pass


def test_any_owned_object_stays_home(world):
    hl, _c, panel, QB = world
    import App
    import loadspacehelper
    from engine.systems import owners
    owners.register(_TestPatrolOwner())
    try:
        pSet = _into_region("TauCeti", "Starbase12")
        patrol = loadspacehelper.CreateShip("Galor", pSet, "Patrol 1", "")
        owners.tag(patrol, "test_patrol", "Patrol 1")
        _start_region_change(hl, panel, QB, "Belaruz1")
        assert _player().GetContainingSet().GetName() == "Belaruz1"
        assert App.g_kSetManager.GetSet("Starbase12").GetObject("Patrol 1") is patrol
        assert App.g_kSetManager.GetSet("Belaruz1").GetObject("Patrol 1") is None
    finally:
        owners._owners.pop("test_patrol", None)


# ── A battle ends with every real object as it began (spec §7) ──────────────

def _all_objects():
    import App
    for pSet in list(App.g_kSetManager._sets.values()):
        for obj in list(pSet._objects.values()):
            yield obj


def _scripted(leaf):
    return [o for o in _all_objects()
            if getattr(type(o), "GetScript", None) is not None
            and str(o.GetScript()).rsplit(".", 1)[-1] == leaf]


def _named_in(pSet, name):
    return [o for o in pSet.GetObjectList() if o.GetName() == name]


def _flat(cond):
    return [(-1.0 if v is None else float(v))
            for key in ("subsystems", "shields", "ammo") for v in cond[key]]


def _same_condition(obj, before):
    from engine.quickbattle.sim_restore import condition_of
    now = condition_of(obj)
    assert [len(now[k]) for k in now] == [len(before[k]) for k in before]
    assert _flat(now) == pytest.approx(_flat(before), abs=1e-6)


def _end(hl, QB):
    QB.EndSimulation()
    hl._process_object_deletions()


def test_end_combat_and_restart_keep_the_station(world):
    hl, _c, panel, QB = world
    import App
    pSet = _into_region("TauCeti", "Starbase12")
    _do(panel, "add:Warbird")
    _go(hl, panel)
    assert _scripted("Warbird")
    _end(hl, QB)
    assert pSet.GetObject("Starbase 12") is not None
    assert _scripted("Warbird") == []
    _go(hl, panel)
    QB.RestartSimulation(QB.g_pXO, App.TGEvent_Create())
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    hl._process_object_deletions()
    assert pSet.GetObject("Starbase 12") is not None


def test_damage_from_the_battle_is_undone(world):
    hl, _c, panel, QB = world
    import loadspacehelper
    from engine.appc import combat
    from engine.appc.math import TGPoint3
    from engine.quickbattle.sim_restore import condition_of
    pSet = _into_region("TauCeti", "Starbase12")
    p = _player().GetWorldLocation()
    rock = loadspacehelper.CreateShip("Asteroidh1", pSet, "Test Rock", "")
    rock.SetTranslate(TGPoint3(p.x + 100.0, p.y, p.z))
    rock.UpdateNodeOnly()
    station = pSet.GetObject("Starbase 12")
    before_station, before_rock = condition_of(station), condition_of(rock)
    _do(panel, "add:Warbird")
    _go(hl, panel)
    warbird = QB.g_pSet.GetObject("Warbird-1")
    combat.apply_hit(station, 20000.0, station.GetWorldLocation(), warbird,
                     weapon_type="phaser")
    combat.apply_hit(rock, 50.0, rock.GetWorldLocation(), _player(),
                     weapon_type="phaser")
    assert condition_of(station)["subsystems"][0] < before_station["subsystems"][0]
    assert condition_of(rock)["subsystems"][0] < before_rock["subsystems"][0]
    _end(hl, QB)
    _same_condition(pSet.GetObject("Starbase 12"), before_station)
    _same_condition(pSet.GetObject("Test Rock"), before_rock)


def test_a_station_destroyed_in_battle_comes_back(world):
    hl, _c, panel, QB = world
    import loadspacehelper
    from engine.appc import ship_death
    from engine.systems import home_stations as hs
    pSet = _into_region("TauCeti", "Starbase12")
    station = pSet.GetObject("Starbase 12")
    row = hs.home_station_of(station)
    saved, saved_rot = _loc(station), _rot(station)
    _do(panel, "add:Warbird")
    _go(hl, panel)
    ship_death.begin(station)
    ship_death.advance(ship_death.MAX_THROES_DURATION + 0.1)
    assert station.IsDead()
    assert not hs.is_standing(row)
    _end(hl, QB)
    found = _named_in(pSet, "Starbase 12")
    assert len(found) == 1
    new = found[0]
    assert new is not station
    assert not ship_death._out_of_action(new)
    assert hs.home_station_of(new) == row
    assert _loc(new) == pytest.approx(saved, abs=1e-6)
    assert _rot(new) == pytest.approx(saved_rot, abs=1e-6)
    assert hs.is_standing(row)
    for i in range(ship_death.MAX_HULKS + 1):
        hulk = loadspacehelper.CreateShip("Galor", pSet, "Hulk %d" % i, "")
        ship_death.begin(hulk)
        ship_death.advance(ship_death.MAX_THROES_DURATION + 0.1)
    assert pSet.GetObject("Starbase 12") is new


class _RecordingOwner:
    name = "test_patrol"

    def __init__(self):
        self.rebuilt = []
        self.built = []
        self.after = []

    def rebuild(self, old, record):
        import loadspacehelper
        self.rebuilt.append(record)
        new = loadspacehelper.CreateShip(record.script, record.pset,
                                         record.name, "", 0, 0)
        self.built.append(new)
        return new

    def after_rebuild(self, new, record) -> None:
        self.after.append((new, record))


def test_owned_objects_follow_their_owner(world):
    hl, _c, panel, QB = world
    import loadspacehelper
    from engine.quickbattle.sim_restore import condition_of
    from engine.systems import owners
    owner = _RecordingOwner()
    owners.register(owner)
    try:
        pSet = _into_region("TauCeti", "Starbase12")
        patrol = loadspacehelper.CreateShip("Galor", pSet, "Patrol 1", "")
        owners.tag(patrol, "test_patrol", "Patrol 1")
        before = condition_of(patrol)
        _do(panel, "add:Warbird")
        _go(hl, panel)
        late = loadspacehelper.CreateShip("Galor", pSet, "Late Patrol", "")
        owners.tag(late, "test_patrol", "Late Patrol")
        hull = patrol.GetHull()
        hull.SetCondition(hull.GetCondition() * 0.5)
        _end(hl, QB)
        # (a) owned, though it appeared mid-battle: untouched
        assert pSet.GetObject("Late Patrol") is late
        assert [r.name for r in owner.rebuilt] == ["Patrol 1"]
        # (b) owned and damaged: rebuilt by its owner, condition put back
        assert len(owner.after) == 1
        assert owner.after[0][0] is owner.built[0]
        assert owner.after[0][1] is owner.rebuilt[0]
        assert pSet.GetObject("Patrol 1") is owner.built[0]
        _same_condition(owner.built[0], before)
        # (c) the battle's own ship is gone
        assert _scripted("Warbird") == []
    finally:
        owners._owners.pop("test_patrol", None)


def test_a_second_load_wraps_once(world, monkeypatch):
    """Quick Battle loaded twice on the cached module: EndSimulation's restore
    runs once, and each function carries one sim_restore wrapper."""
    hl, controller, panel, QB = world
    from engine.quickbattle import sim_restore
    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as again
    assert again is QB
    for name in ("StartSimulation2", "ChangeRegion", "EndSimulation"):
        assert sim_restore._wrapper_count(getattr(QB, name)) == 1, name
    calls = []
    real = sim_restore._restore_after_end
    monkeypatch.setattr(sim_restore, "_restore_after_end",
                        lambda *a: (calls.append(1), real(*a))[1])
    QB.EndSimulation()
    assert calls == [1]


class _BrokenOwner:
    name = "test_broken"

    def rebuild(self, old, record):
        raise RuntimeError("owner blew up")

    def after_rebuild(self, new, record) -> None:
        pass


def test_one_failing_rebuild_never_stops_the_rest(world, caplog):
    """R4: an owner's rebuild raising is logged with its traceback, and the
    other records are still restored."""
    hl, _c, panel, QB = world
    import logging
    import loadspacehelper
    from engine.quickbattle.sim_restore import condition_of
    from engine.systems import owners
    owners.register(_BrokenOwner())
    recording = _RecordingOwner()
    owners.register(recording)
    try:
        pSet = _into_region("TauCeti", "Starbase12")
        broken = loadspacehelper.CreateShip("Galor", pSet, "Broken 1", "")
        owners.tag(broken, "test_broken", "Broken 1")
        # Recorded AFTER the broken one, so only a per-record catch reaches it.
        later = loadspacehelper.CreateShip("Galor", pSet, "Patrol 9", "")
        owners.tag(later, "test_patrol", "Patrol 9")
        station = pSet.GetObject("Starbase 12")
        before = condition_of(station)
        _do(panel, "add:Warbird")
        _go(hl, panel)
        for obj in (broken, later, station):
            hull = obj.GetHull()
            hull.SetCondition(hull.GetCondition() * 0.5)
        with caplog.at_level(logging.ERROR, logger="engine.quickbattle.sim_restore"):
            _end(hl, QB)
        _same_condition(pSet.GetObject("Starbase 12"), before)
        assert [r.name for r in recording.rebuilt] == ["Patrol 9"]
        assert pSet.GetObject("Patrol 9") is recording.built[0]
        failed = [r for r in caplog.records if "Broken 1" in r.getMessage()]
        assert failed and failed[0].exc_info is not None
    finally:
        owners._owners.pop("test_broken", None)
        owners._owners.pop("test_patrol", None)
