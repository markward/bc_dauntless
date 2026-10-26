"""Tau Ceti shuttle service, task 1: roster, lanes, staggered start, and
docking out of the world (a docked shuttle is in no set)."""
import math

import pytest

import App
from engine.systems import owners, shuttle_service as ss
from tests.helpers.fresh_world import _fresh_world

DT = 1.0 / 60.0


def _build_world():
    _fresh_world()
    ss.reset()
    import Systems.Starbase12.Starbase12 as sb
    import Systems.DryDock.DryDock as dd
    sb.Initialize()
    dd.Initialize()


def _place_player(set_name):
    pSet = App.g_kSetManager.GetSet(set_name)
    player = App.ShipClass_Create()
    pSet.AddObjectToSet(player, "player")
    App.Game_GetCurrentGame().SetPlayer(player)
    return player


@pytest.fixture
def world():
    _build_world()
    player = _place_player("Starbase12")
    yield player
    ss.reset()


def _run(seconds):
    for _ in range(int(round(seconds / DT))):
        ss.tick(DT)


def _names():
    return ["TC Shuttle %d" % i for i in range(1, 11)]


def _sets_holding_shuttles():
    found = []
    for pSet in App.g_kSetManager._sets.values():
        for n in _names():
            if pSet.GetObject(n) is not None:
                found.append((pSet.GetName(), n))
    return found


def test_both_regions_get_a_lane_point(world):
    for set_name, station in (("Starbase12", "Starbase 12"),
                              ("DryDock", "Dry Dock")):
        pSet = App.g_kSetManager.GetSet(set_name)
        lane = pSet.GetObject(ss.LANE_NAME)
        st = pSet.GetObject(station)
        assert lane is not None and st is not None
        a, b = lane.GetWorldLocation(), st.GetWorldLocation()
        d = math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)
        assert d == pytest.approx(2000.0, abs=1e-3)
        fwd = st.GetWorldRotation().GetCol(1)
        lf = lane.GetWorldRotation().GetCol(1)
        assert (a.x - b.x) * fwd.x + (a.y - b.y) * fwd.y + (a.z - b.z) * fwd.z \
            == pytest.approx(2000.0, abs=1e-3)
        assert lf.x * fwd.x + lf.y * fwd.y + lf.z * fwd.z == pytest.approx(1.0, abs=1e-4)


def test_ten_shuttles_start_docked_and_staggered(world):
    r = ss.roster()
    assert [s.name for s in r] == _names()
    assert [s.index for s in r] == list(range(1, 11))
    assert all(s.phase is ss.Phase.DOCKED for s in r)
    assert [s.timer for s in r] == [i * 60.0 for i in range(10)]


def test_docked_shuttles_are_in_no_set(world):
    assert _sets_holding_shuttles() == []


def test_the_first_launches_on_the_first_tick(world):
    ss.tick(DT)
    r = ss.roster()
    assert r[0].phase is ss.Phase.UNDOCKING
    assert all(s.phase is ss.Phase.DOCKED for s in r[1:])
    ship = App.g_kSetManager.GetSet("Starbase12").GetObject("TC Shuttle 1")
    assert ship is not None and ship is r[0].ship
    owner, key = owners.owner_of(ship)
    assert (owner.name, key) == ("tau_ceti_shuttles", 1)


def test_the_shuttle_starts_at_the_exit_start_point(world):
    ss.tick(DT)
    sb = App.g_kSetManager.GetSet("Starbase12").GetObject("Starbase 12")
    import MissionLib
    pos, fwd, _up = MissionLib.GetPositionOrientationFromProperty(
        sb, "Docking Exit Start")
    pos.MultMatrixLeft(sb.GetWorldRotation())
    pos.Add(sb.GetWorldLocation())
    fwd.MultMatrixLeft(sb.GetWorldRotation())
    ship = ss.roster()[0].ship
    loc, f = ship.GetWorldLocation(), ship.GetWorldRotation().GetCol(1)
    assert (loc.x, loc.y, loc.z) == pytest.approx((pos.x, pos.y, pos.z), abs=1e-3)
    assert (f.x, f.y, f.z) == pytest.approx((fwd.x, fwd.y, fwd.z), abs=1e-3)


def test_one_launch_a_minute(world):
    _run(125.0)
    phases = [s.phase for s in ss.roster()]
    assert all(p is ss.Phase.UNDOCKING for p in phases[:3])
    assert all(p is ss.Phase.DOCKED for p in phases[3:])


def test_paused_outside_tau_ceti(world):
    _run(65.0)
    assert ss.roster()[0].phase is ss.Phase.UNDOCKING
    other = App.SetClass_Create()
    App.g_kSetManager.AddSet(other, "Vesuvi6")
    world.GetContainingSet().RemoveObjectFromSet("player")
    other.AddObjectToSet(world, "player")
    ss.tick(DT)
    assert all(s.phase is ss.Phase.DOCKED for s in ss.roster())
    assert _sets_holding_shuttles() == []
    frozen = [s.timer for s in ss.roster()]
    _run(30.0)
    assert [s.timer for s in ss.roster()] == frozen
    assert _sets_holding_shuttles() == []
    other.RemoveObjectFromSet("player")
    App.g_kSetManager.GetSet("Starbase12").AddObjectToSet(world, "player")
    ss.tick(DT)
    r = ss.roster()
    assert r[0].phase is ss.Phase.UNDOCKING
    assert all(s.phase is ss.Phase.DOCKED for s in r[1:])
    assert r[1].timer == pytest.approx(60.0 - DT, abs=1e-6)


def test_region_built_twice_keeps_one_roster(world):
    import Systems.Starbase12.Starbase12 as sb
    sb.Initialize()
    assert len(ss.roster()) == 10
    assert App.g_kSetManager.GetSet("Starbase12").GetObject(ss.LANE_NAME) is not None


def test_a_replaced_set_docks_the_shuttles_that_were_in_it(world):
    ss.tick(DT)
    assert ss.roster()[0].phase is ss.Phase.UNDOCKING
    import Systems.Starbase12.Starbase12 as sb
    sb.Initialize()
    assert ss.roster()[0].phase is ss.Phase.DOCKED


def test_reset_forgets_everything(world):
    ss.tick(DT)
    ss.reset()
    assert ss.roster() == []


def test_in_no_mission_group(world):
    ss.tick(DT)
    import MissionLib
    m = MissionLib.GetMission()
    for g in (m.GetFriendlyGroup(), m.GetEnemyGroup(), m.GetNeutralGroup()):
        assert not g.IsNameInGroup("TC Shuttle 1")
