"""Tau Ceti shuttle service: roster, lanes, staggered start, docking out of
the world (a docked shuttle is in no set), and the Starbase 12 legs (undock,
depart, warp out; approach, enter the bay, dock) and the Dry Docks legs
(to a random dock, two circles, out to the lane, warp back)."""
import math
import random

import pytest

import App
from engine.appc import collisions, warp_state
from engine.core.loop import GameLoop
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
    # Where a free-roam player starts (~225 GU from the bay mouth), not the
    # origin, which is next to Starbase 12's bay.
    start = pSet.GetObject("Player Start")
    if start is not None:
        player.SetTranslate(start.GetWorldLocation())
        player.UpdateNodeOnly()
    return player


@pytest.fixture
def world():
    _build_world()
    # The dock choice is random: a fixed seed keeps every run the same.
    ss.set_rng(random.Random(1701))
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


def _gap(p, q):
    return math.sqrt((p.x - q.x) ** 2 + (p.y - q.y) ** 2 + (p.z - q.z) ** 2)


def test_each_shuttle_has_its_own_lane_point_in_both_regions(world):
    """R6: a shuttle arrives at, departs from and holds at its own point
    round the region's lane point, at least 30 GU from every other one."""
    for set_name in ("Starbase12", "DryDock"):
        pSet = App.g_kSetManager.GetSet(set_name)
        centre = pSet.GetObject(ss.LANE_NAME).GetWorldLocation()
        start = pSet.GetObject("Player Start").GetWorldLocation()
        points = []
        for s in ss.roster():
            wp = pSet.GetObject(ss._lane_name(s))
            assert wp is not None, (set_name, s.name)
            p = wp.GetWorldLocation()
            assert _gap(p, centre) < 100.0
            assert _gap(p, start) > 1000.0
            points.append(p)
        assert min(_gap(p, q) for i, p in enumerate(points)
                   for q in points[i + 1:]) >= 30.0


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
    # The real loop: a launch waits for the shuttle before it to be out of
    # the bay (~55 s of undocking), so the ships have to move.
    _sim(125.0)
    launched = [s.ship is not None for s in ss.roster()]
    assert launched == [True] * 3 + [False] * 7


def test_paused_outside_tau_ceti(world):
    _sim(65.0)
    assert ss.roster()[1].ship is not None
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


def test_a_launched_shuttle_is_given_the_undock_leg(world):
    ss.tick(DT)
    s = ss.roster()[0]
    assert s.phase is ss.Phase.UNDOCKING
    assert s.ship.GetAI() is not None
    sb = _home().GetObject("Starbase 12")
    assert sb.GetObjID() in collisions._collision_disabled_ids(s.ship)


# Two shuttles in one set never come closer than this (a shuttle's hull
# radius is 0.12 GU, ships/Hardpoints/shuttle.py).
MIN_SEPARATION_GU = 2.0


def test_no_two_shuttles_ever_share_a_pose(world):
    """Over 2,400 s -- past the first cycle, where the one-a-minute stagger
    has drifted, several shuttles are at the Dry Docks together and more of
    them want the bay than it holds -- no two shuttles in one set are ever
    within MIN_SEPARATION_GU of each other, and at most one is ever on a bay
    leg (ENTERING or UNDOCKING)."""
    seen = {}
    closest = (1e9, None)
    shared = 0
    in_bay = 0
    by_phase = {s.index: s for s in ss.roster()}
    loop = GameLoop()
    for i in range(int(2400 / DT)):
        loop.tick()
        poses = []
        for pSet in App.g_kSetManager._sets.values():
            here = []
            for n in _names():
                o = pSet.GetObject(n)
                if o is not None:
                    here.append(o)
                    l = o.GetWorldLocation()
                    poses.append((round(l.x, 3), round(l.y, 3), round(l.z, 3)))
            for a in range(len(here)):
                for b in range(a + 1, len(here)):
                    d = _dist(here[a], here[b])
                    if d < closest[0]:
                        sa = by_phase[int(here[a].GetName().split()[-1])]
                        sb = by_phase[int(here[b].GetName().split()[-1])]
                        closest = (d, (i * DT, sa.name, sa.phase.name,
                                       sb.name, sb.phase.name))
        assert len(poses) == len(set(poses))
        seen[len(poses)] = True
        circling = [s.dock_name for s in ss.roster()
                    if s.phase is ss.Phase.CIRCLING]
        shared = max([shared] + [circling.count(n) for n in circling])
        bay = sum(s.phase in (ss.Phase.ENTERING, ss.Phase.UNDOCKING)
                  for s in ss.roster())
        in_bay = max(in_bay, bay)
    assert 1 in seen
    assert shared >= 2           # docks were shared: the case is exercised
    assert in_bay == 1
    assert closest[0] >= MIN_SEPARATION_GU, closest


def test_a_failing_launch_parks_the_shuttle_and_never_raises(world, monkeypatch, capsys):
    real = ss._bay_pose
    calls = []

    def bad(station):
        calls.append(1)
        if len(calls) == 1:
            raise AttributeError("no bay")
        return real(station)
    monkeypatch.setattr(ss, "_bay_pose", bad)
    _sim(125.0)                 # the real loop: launches wait for the bay
    out = capsys.readouterr().out
    assert out.count("[shuttles]") == 1
    r = ss.roster()
    assert r[0].ship is None and r[0].phase is ss.Phase.DOCKED
    assert r[0].timer == pytest.approx(ss.DOCK_S - (125.0 - 1 * DT), abs=1.0)
    assert r[1].ship is not None and r[2].ship is not None


def test_a_create_ship_that_returns_none_is_parked(world, monkeypatch, capsys):
    import loadspacehelper
    monkeypatch.setattr(loadspacehelper, "CreateShip",
                        lambda *a, **k: None)
    _run(70.0)
    assert capsys.readouterr().out.count("[shuttles]") == 2
    assert all(s.phase is ss.Phase.DOCKED for s in ss.roster())


def _move_player_to(world, set_name):
    world.GetContainingSet().RemoveObjectFromSet("player")
    App.g_kSetManager.GetSet(set_name).AddObjectToSet(world, "player")


def test_the_warp_transit_set_neither_pauses_nor_restarts(world):
    from engine.appc import warp
    _run(65.0)
    before = [(s.phase, s.timer, s.ship) for s in ss.roster()]
    transit = warp.WarpSequence_GetWarpSet()
    world.GetContainingSet().RemoveObjectFromSet("player")
    transit.AddObjectToSet(world, "player")
    ss.tick(DT)
    after = [(s.phase, s.ship) for s in ss.roster()]
    assert after == [(p, sh) for p, _t, sh in before]


def test_no_player_neither_pauses_nor_restarts(world):
    _run(65.0)
    before = [(s.phase, s.ship) for s in ss.roster()]
    timers = [s.timer for s in ss.roster()]
    App.Game_GetCurrentGame().SetPlayer(None)
    ss.tick(DT)
    assert [(s.phase, s.ship) for s in ss.roster()] == before
    assert [s.timer for s in ss.roster()] == timers


# ── The Starbase 12 legs ─────────────────────────────────────────────────────
# Time runs through the real GameLoop.tick (AI, warp states, the service,
# motion) plus collisions.tick_collisions, which the host runs per frame.

# Headless ships load with GetRadius() == 0, so nothing could ever collide.
# The collision test gives Starbase 12 its model-wide bound (~150 GU,
# tests/unit/test_hull_bounds.py) and the shuttle a small one; the bay points
# (68-108 GU from the centre) then sit inside the station's sphere.
SB_RADIUS = 150.0
SHUTTLE_RADIUS = 0.5


def _home():
    return App.g_kSetManager.GetSet("Starbase12")


def _starbase():
    return _home().GetObject("Starbase 12")


def _dist(a, b):
    a, b = a.GetWorldLocation(), b.GetWorldLocation()
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _sim(seconds, until=None, each=None):
    """Tick the real loop; returns the game seconds `until` took, or None."""
    loop = GameLoop()
    for i in range(int(round(seconds / DT))):
        loop.tick()
        hits = collisions.tick_collisions(DT)
        if each is not None:
            each(hits)
        if until is not None and until():
            return (i + 1) * DT
    return None


def _arrive_home(s):
    """Put shuttle `s` at its own Starbase 12 lane point the way a warp back
    from the Dry Docks leaves it: in Starbase12, at the lane, no AI,
    collisions on, phase APPROACHING."""
    if s.ship is None:
        ss._launch(s)
    ship = s.ship
    ss._release_bay(s)
    ship.ClearAI()
    home = _home()
    held = ship.GetContainingSet()
    if held is not home:
        if held is not None:
            held.RemoveObjectFromSet(s.name)
        home.AddObjectToSet(ship, s.name)
    lane = home.GetObject(ss._lane_name(s))
    rot = lane.GetWorldRotation()
    ship.SetTranslate(lane.GetWorldLocation())
    ship.AlignToVectors(rot.GetCol(1), rot.GetCol(2))
    ship.SetVelocity(App.TGPoint3(0.0, 0.0, 0.0))
    ship.UpdateNodeOnly()
    ss._enter(s, ss.Phase.APPROACHING)


def test_a_shuttle_undocks_and_reaches_the_lane(world):
    s = ss.roster()[0]
    lane = _home().GetObject(ss._lane_name(s))
    seen, closest = set(), [1e9]

    def watch(_hits):
        seen.add(s.phase)
        if s.ship is not None and s.ship.GetContainingSet() is _home():
            closest[0] = min(closest[0], _dist(s.ship, lane))
    took = _sim(120.0, until=lambda: s.phase is ss.Phase.WARPING_OUT,
                each=watch)
    assert took is not None, sorted(p.name for p in seen)
    assert {ss.Phase.UNDOCKING, ss.Phase.DEPARTING} <= seen
    assert closest[0] < 15.0           # its own lane point, not the centre


def test_the_bay_legs_never_collide_with_the_starbase(world, monkeypatch):
    sb = _starbase()
    sb.SetRadius(SB_RADIUS)
    real_launch = ss._launch

    def sized_launch(shuttle):
        real_launch(shuttle)
        if shuttle.ship is not None:
            shuttle.ship.SetRadius(SHUTTLE_RADIUS)
    monkeypatch.setattr(ss, "_launch", sized_launch)
    s = ss.roster()[0]
    sb_hull = sb.GetHull().GetCondition()
    bad, mask = [], []

    def watch(hits):
        ship = s.ship
        if ship is None:
            return
        for a, b, *_rest in hits:
            if {a, b} == {ship, sb}:
                bad.append((s.phase.name, a.GetName(), b.GetName()))
        off = sb.GetObjID() in collisions._collision_disabled_ids(ship)
        mask.append((s.phase, off))
    # Leaving: launch -> undock -> depart, up to the warp.
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.WARPING_OUT,
                each=watch) is not None
    shuttle_hull = s.ship.GetHull().GetCondition()
    # Entering: back at the lane, approach -> enter -> docked.
    _arrive_home(s)
    assert _sim(300.0, until=lambda: s.phase is ss.Phase.DOCKED,
                each=watch) is not None
    assert bad == []
    assert sb.GetHull().GetCondition() == sb_hull
    assert s.ship.GetHull().GetCondition() == shuttle_hull
    # Off on the bay legs, on everywhere else.
    assert {off for p, off in mask if p in (ss.Phase.UNDOCKING,
                                             ss.Phase.ENTERING)} == {True}
    assert {off for p, off in mask if p in (ss.Phase.DEPARTING,
                                             ss.Phase.APPROACHING)} == {False}
    assert sb.GetObjID() not in collisions._collision_disabled_ids(s.ship)


def test_a_shuttle_warps_to_the_dry_docks_lane(world):
    s = ss.roster()[0]
    assert _sim(180.0, until=lambda: s.phase is ss.Phase.TO_DOCK) is not None
    far = App.g_kSetManager.GetSet("DryDock")
    assert s.ship.GetContainingSet() is far
    assert not warp_state.is_ship_warping(s.ship)
    assert _dist(s.ship, far.GetObject(ss._lane_name(s))) < 15.0


def test_an_arriving_shuttle_enters_the_bay_and_docks(world):
    s = ss.roster()[0]
    _arrive_home(s)
    seen = set()
    took = _sim(300.0, until=lambda: s.phase is ss.Phase.DOCKED,
                each=lambda _h: seen.add(s.phase))
    assert took is not None, sorted(p.name for p in seen)
    assert ss.Phase.ENTERING in seen
    assert s.ship.GetContainingSet() is None
    assert all(n != s.name for _set, n in _sets_holding_shuttles())
    assert s.timer == ss.DOCK_S


def test_starbase_destroyed_shuttles_wait(world, capsys):
    s = ss.roster()[0]
    _arrive_home(s)
    assert _sim(300.0, until=lambda: s.phase is ss.Phase.ENTERING) is not None
    _sim(5.0)
    _starbase().SetDead(1)
    _sim(120.0)
    lane = _home().GetObject(ss._lane_name(s))
    assert s.phase is ss.Phase.WAITING
    assert s.ship.GetContainingSet() is _home()
    assert _dist(s.ship, lane) < 20.0
    assert ss.roster()[1].timer <= 0.0     # due, but nowhere to launch from
    assert all(o.phase is ss.Phase.DOCKED for o in ss.roster()[1:])
    assert [n for _set, n in _sets_holding_shuttles()] == [s.name]
    # Gone outright (removed from the set) is the same: still waiting.
    _home().RemoveObjectFromSet("Starbase 12")
    _sim(10.0)
    assert s.phase is ss.Phase.WAITING
    assert "[shuttles]" not in capsys.readouterr().out


def test_player_docking_pushes_a_shuttle_and_it_recovers(world, capsys):
    s = ss.roster()[0]
    _arrive_home(s)

    def near_the_bay():
        wp = _home().GetObject("Docking Entry")
        return (s.phase is ss.Phase.ENTERING and wp is not None
                and _dist(s.ship, wp) < 60.0)
    assert _sim(300.0, until=near_the_bay) is not None
    # BC's player docking (DockWithStarbase.SetupDockPositions) clears
    # everything within 300 GU of "Docking Entry" -- run the real thing.
    import AI.Compound.DockWithStarbase as dock
    dock.SetupDockPositions(world, "Starbase 12")
    assert _dist(s.ship, _home().GetObject("Docking Entry")) >= 299.0
    # The player now sits at the bay mouth: the bay is the player's, so the
    # pushed shuttle goes back out to its clearance point and holds there.
    assert ss._player_owns_bay()
    seen = []
    _sim(90.0, each=lambda _h: seen.append(s.phase))
    assert ss.Phase.APPROACHING in seen
    assert ss.Phase.ENTERING not in seen
    _assert_holding(s)
    # The player leaves: the shuttle enters and docks.
    _to_player_start(world)
    seen.clear()
    took = _sim(300.0, until=lambda: s.phase is ss.Phase.DOCKED,
                each=lambda _h: seen.append(s.phase))
    assert took is not None, sorted({p.name for p in seen})
    assert ss.Phase.ENTERING in seen
    assert "[shuttles]" not in capsys.readouterr().out


def test_a_persistent_tick_failure_prints_once(world, monkeypatch, capsys):
    def boom():
        raise RuntimeError("no presence")
    monkeypatch.setattr(ss, "_player_presence", boom)
    _run(1.0)
    assert capsys.readouterr().out.count("[shuttles] tick failed") == 1


def test_varying_tick_failures_are_bounded(world, monkeypatch, capsys):
    n = [0]

    def boom():
        n[0] += 1
        raise RuntimeError("failure %d" % n[0])
    monkeypatch.setattr(ss, "_player_presence", boom)
    _run(10.0)
    printed = capsys.readouterr().out.count("[shuttles] tick failed")
    assert n[0] == 600
    assert 1 <= printed <= ss._TICK_ERRORS_MAX
    assert len(ss._tick_errors) <= ss._TICK_ERRORS_MAX


# ── The bay is the player's while the player docks, is docked or undocks ────

def _to_player_start(player):
    player.SetTranslate(_home().GetObject("Player Start").GetWorldLocation())
    player.UpdateNodeOnly()


def _assert_holding(s):
    """At its own point round the outside clearance point, stopped,
    collisions with the station back on."""
    assert s.phase is ss.Phase.APPROACHING
    approach = _home().GetObject(ss._approach_name(s))
    assert _dist(s.ship, approach) <= 15.0
    assert s.ship.GetVelocityTG().Length() < 0.5
    assert _starbase().GetObjID() not in \
        collisions._collision_disabled_ids(s.ship)


@pytest.fixture
def bay_flag(monkeypatch):
    flag = [False]
    monkeypatch.setattr(ss, "_player_owns_bay", lambda: flag[0])
    return flag


def test_the_bay_is_the_players_while_docking_docked_or_undocking(
        world, monkeypatch):
    assert not ss._player_owns_bay()          # free roam at Player Start
    sb = _starbase()
    import AI.Compound.UndockFromStarbase as undock
    world.SetAI(undock.CreateAI(world, sb))
    assert ss._player_owns_bay()
    import AI.Compound.DockWithStarbase as dock
    # Graff's docked scene needs the bridge set, which a headless world lacks;
    # the rest of the tree is BC's own.
    monkeypatch.setattr(dock, "CreatePlayerDockAction", lambda *_a:
                        App.TGScriptAction_Create("MissionLib", "FadeIn"))
    world.SetAI(dock.CreateAI(world, sb))
    assert ss._player_owns_bay()
    intercept = App.PlainAI_Create(world, "Elsewhere")
    intercept.SetScriptModule("Intercept")
    intercept.GetScriptInstance().SetTargetObjectName(ss.LANE_NAME)
    world.SetAI(intercept)
    assert not ss._player_owns_bay()
    world.ClearAI()
    # At the bay mouth with no docking AI (just undocked and coasting out,
    # or parked there): still the player's.
    import MissionLib
    pos = MissionLib.GetPositionOrientationFromProperty(
        sb, "Docking Entry Start")[0]
    pos.MultMatrixLeft(sb.GetWorldRotation())
    pos.Add(sb.GetWorldLocation())
    world.SetTranslate(pos)
    world.UpdateNodeOnly()
    assert ss._player_owns_bay()
    _to_player_start(world)
    assert not ss._player_owns_bay()


def test_a_due_shuttle_waits_docked_while_the_player_owns_the_bay(
        world, bay_flag):
    bay_flag[0] = True
    _run(5.0)
    s = ss.roster()[0]
    assert s.phase is ss.Phase.DOCKED and s.ship is None
    assert s.timer <= 0.0
    bay_flag[0] = False
    ss.tick(DT)
    assert s.phase is ss.Phase.UNDOCKING
    assert s.ship.GetContainingSet() is _home()


def test_an_approaching_shuttle_holds_until_the_bay_is_free(world, bay_flag):
    bay_flag[0] = True
    s = ss.roster()[0]
    _arrive_home(s)
    seen = set()
    _sim(120.0, each=lambda _h: seen.add(s.phase))
    assert ss.Phase.ENTERING not in seen
    _assert_holding(s)
    bay_flag[0] = False
    took = _sim(300.0, until=lambda: s.phase is ss.Phase.DOCKED,
                each=lambda _h: seen.add(s.phase))
    assert took is not None
    assert ss.Phase.ENTERING in seen


def test_an_entering_shuttle_backs_out_when_the_player_takes_the_bay(
        world, bay_flag):
    s = ss.roster()[0]
    _arrive_home(s)
    assert _sim(300.0, until=lambda: s.phase is ss.Phase.ENTERING) is not None
    _sim(5.0)
    bay_flag[0] = True
    _sim(150.0)
    _assert_holding(s)
    bay_flag[0] = False
    assert _sim(300.0, until=lambda: s.phase is ss.Phase.DOCKED) is not None


def test_each_shuttle_holds_at_its_own_point_outside_the_bay(world):
    """R6: the hold points round the bay's outside clearance point are one
    per shuttle, at least 30 GU apart, all well clear of Starbase 12."""
    ss._entry_points(_starbase())
    centre = _home().GetObject("TC Shuttle Approach").GetWorldLocation()
    sb = _starbase().GetWorldLocation()
    points = [_home().GetObject(ss._approach_name(s)).GetWorldLocation()
              for s in ss.roster()]
    assert min(_gap(p, q) for i, p in enumerate(points)
               for q in points[i + 1:]) >= 30.0
    assert all(_gap(p, centre) < 100.0 for p in points)
    assert all(_gap(p, sb) > SB_RADIUS + 50.0 for p in points)


def test_one_shuttle_in_the_bay_at_a_time(world):
    """R6: a shuttle due to launch stays docked while another is ENTERING; an
    arriving one holds at its own point while another is UNDOCKING."""
    a, b = ss.roster()[0], ss.roster()[1]
    for o in ss.roster()[2:]:
        o.timer = 1e9
    b.timer = 1e9
    _arrive_home(a)
    assert _sim(300.0, until=lambda: a.phase is ss.Phase.ENTERING) is not None
    b.timer = 0.0                       # due while `a` enters
    pairs = []
    assert _sim(300.0, until=lambda: b.phase is ss.Phase.UNDOCKING,
                each=lambda _h: pairs.append((a.phase, b.phase))) is not None
    # `b` stayed docked all the time `a` was entering, and launched only
    # once `a` had docked (on that very tick).
    assert ss.Phase.ENTERING in {pa for pa, _pb in pairs}
    assert all(pb is ss.Phase.DOCKED for pa, pb in pairs
               if pa is ss.Phase.ENTERING)
    assert a.phase is ss.Phase.DOCKED
    # `a` comes back while `b` undocks: it holds outside until `b` is out.
    a.timer = 1e9
    _arrive_home(a)
    both = []

    def watch(_h):
        both.append((a.phase, b.phase))
    assert _sim(300.0, until=lambda: b.phase is not ss.Phase.UNDOCKING,
                each=watch) is not None
    assert all(pa is not ss.Phase.ENTERING for pa, _pb in both)
    _assert_holding(a)
    assert _sim(300.0, until=lambda: a.phase is ss.Phase.DOCKED) is not None


def test_an_undocking_shuttle_carries_on_out(world, bay_flag):
    s = ss.roster()[0]
    ss.tick(DT)
    assert s.phase is ss.Phase.UNDOCKING
    bay_flag[0] = True
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.WARPING_OUT) \
        is not None


def test_a_refused_warp_departs_again(world):
    s = ss.roster()[0]
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.WARPING_OUT) \
        is not None
    s.ship.ClearAI()                  # the Warp AI dropped, still at home
    _sim(DT)
    assert s.phase is ss.Phase.DEPARTING
    assert s.ship.GetAI() is not None
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.TO_DOCK) is not None


# ── The Dry Docks legs ───────────────────────────────────────────────────────

DOCKS = ("Dry Dock", "Dry Dock2", "Dry Dock3")
# Headless ships load with GetRadius() == 0. The collision checks give each
# dock its hardpoint hull radius (8 GU, ships/Hardpoints/drydock.py), the
# Station its own (11 GU, spacefacility.py) and the shuttle a small sphere.
DOCK_RADIUS = 8.0
STATION_RADIUS = 11.0
# CircleObject dips this far inside a band's near edge while it settles
# (measured up to 1.63 GU) and goes this far outside the far edge at most.
BAND_SLACK_IN, BAND_SLACK_OUT = 2.0, 0.5


def _size_the_dry_docks():
    for name in DOCKS:
        _far().GetObject(name).SetRadius(DOCK_RADIUS)
    _far().GetObject("Station").SetRadius(STATION_RADIUS)


def _far():
    return App.g_kSetManager.GetSet("DryDock")


def _only_the_first():
    """Keep every shuttle but the first docked for the whole test."""
    for o in ss.roster()[1:]:
        o.timer = 1e9
    return ss.roster()[0]


def _arrive_far(s):
    """Put shuttle `s` at its own Dry Docks lane point the way the warp out
    leaves it: in DryDock, at the lane, no AI, collisions on, phase
    TO_DOCK."""
    if s.ship is None:
        ss._launch(s)
    ship = s.ship
    ss._release_bay(s)
    ship.ClearAI()
    far = _far()
    held = ship.GetContainingSet()
    if held is not far:
        if held is not None:
            held.RemoveObjectFromSet(s.name)
        far.AddObjectToSet(ship, s.name)
    lane = far.GetObject(ss._lane_name(s))
    rot = lane.GetWorldRotation()
    ship.SetTranslate(lane.GetWorldLocation())
    ship.AlignToVectors(rot.GetCol(1), rot.GetCol(2))
    ship.SetVelocity(App.TGPoint3(0.0, 0.0, 0.0))
    ship.UpdateNodeOnly()
    ss._enter(s, ss.Phase.TO_DOCK)


def _swept(prev, ship, dock):
    """The angle (radians) the dock->ship direction turned since `prev`,
    measured independently of the service; returns (angle, new direction)."""
    a, b = ship.GetWorldLocation(), dock.GetWorldLocation()
    v = (a.x - b.x, a.y - b.y, a.z - b.z)
    if prev is None:
        return 0.0, v
    cross = (prev[1] * v[2] - prev[2] * v[1], prev[2] * v[0] - prev[0] * v[2],
             prev[0] * v[1] - prev[1] * v[0])
    dot = sum(x * y for x, y in zip(prev, v))
    return math.atan2(math.sqrt(sum(c * c for c in cross)), dot), v


def test_the_dock_is_chosen_at_random(world):
    s = _only_the_first()
    chosen = []
    for _ in range(30):
        _arrive_far(s)
        assert s.phase is ss.Phase.TO_DOCK
        chosen.append(s.dock_name)
    assert set(chosen) == set(DOCKS)
    _far().GetObject("Dry Dock2").SetDead(1)
    chosen.clear()
    for _ in range(30):
        _arrive_far(s)
        chosen.append(s.dock_name)
    assert set(chosen) == {"Dry Dock", "Dry Dock3"}
    # The service's own Random: the same seed, the same choices.
    ss.set_rng(random.Random(7))
    first = []
    for _ in range(10):
        _arrive_far(s)
        first.append(s.dock_name)
    ss.set_rng(random.Random(7))
    again = []
    for _ in range(10):
        _arrive_far(s)
        again.append(s.dock_name)
    assert first == again


def _loc(name):
    return _far().GetObject(name).GetWorldLocation()


def test_orbit_bands_come_from_the_dock_layout(world):
    """R7: each dock's bands are disjoint, ~8 GU wide, start outside
    max(2 x its hull radius, 20 GU) and end inside half the distance to the
    nearest other standing station minus 5 GU -- so bands round two docks
    never meet either."""
    others = DOCKS + ("Station",)
    outer = {}
    for name in DOCKS:
        bands = ss._bands(name)
        assert bands, name
        floor = max(2.0 * _far().GetObject(name).GetHull().GetRadius(), 20.0)
        cap = min(_gap(_loc(name), _loc(o)) for o in others if o != name) \
            / 2.0 - 5.0
        assert bands[0][0] - BAND_SLACK_IN >= floor
        assert bands[-1][1] + BAND_SLACK_OUT <= cap + 0.5
        for near, far in bands:
            assert 6.0 <= far - near <= 9.0
        for (_n0, f0), (n1, _f1) in zip(bands, bands[1:]):
            assert f0 + BAND_SLACK_OUT < n1 - BAND_SLACK_IN   # never overlap
        outer[name] = bands[-1][1]
    for i, a in enumerate(DOCKS):
        for b in DOCKS[i + 1:]:
            assert outer[a] + outer[b] + 10.0 <= _gap(_loc(a), _loc(b))
    # The two docks 89 GU apart have room for two orbits each.
    assert len(ss._bands("Dry Dock")) == len(ss._bands("Dry Dock3")) == 2
    # A dock destroyed frees its neighbours' room.
    _far().GetObject("Dry Dock3").SetDead(1)
    assert len(ss._bands("Dry Dock")) > 2


def _occupy(s, dock, slot):
    """`s` circling `dock` on orbit `slot` (set up by hand)."""
    _arrive_far(s)
    s.dock_name, s.orbit_slot = dock, slot
    s.bearing_accum, s.bearing_prev = 0.0, None
    s.leave_at = ss.CIRCLES * 2.0 * math.pi
    ss._enter(s, ss.Phase.CIRCLING)


def test_a_full_house_holds_at_the_lane(world):
    """R7: a dock with no free orbit is not eligible; with none eligible the
    shuttle holds at its own Dry Docks lane point until one frees."""
    for o in ss.roster():
        o.timer = 1e9
    shuttles = iter(ss.roster())
    for name in DOCKS:
        for slot in range(len(ss._bands(name))):
            _occupy(next(shuttles), name, slot)
    waiting = next(shuttles)
    _arrive_far(waiting)
    assert waiting.phase is ss.Phase.TO_DOCK and waiting.dock_name is None
    _sim(10.0)
    assert waiting.phase is ss.Phase.TO_DOCK and waiting.dock_name is None
    assert _dist(waiting.ship, _far().GetObject(ss._lane_name(waiting))) < 15.0
    assert waiting.ship.GetVelocityTG().Length() < 0.5
    # The outermost orbit on Dry Dock2 frees: it goes there.
    leaver = next(o for o in ss.roster() if o.dock_name == "Dry Dock2"
                  and o.orbit_slot == len(ss._bands("Dry Dock2")) - 1)
    ss._dock(leaver)
    _sim(DT)
    assert waiting.dock_name == "Dry Dock2"
    assert waiting.orbit_slot == len(ss._bands("Dry Dock2")) - 1


def test_orbits_fill_outward_and_empty_inward(world):
    """No shuttle ever crosses another's orbit: a newcomer takes the orbit
    outside every occupied one (one flying in at a time per dock), and a
    shuttle only leaves when no shuttle at its dock is outside it -- until
    then it circles on, a whole turn at a time."""
    for o in ss.roster():
        o.timer = 1e9
    a, b, c = ss.roster()[:3]
    _occupy(a, "Dry Dock", 1)
    _arrive_far(b)
    # Dry Dock's outer orbit is taken: not eligible, even with orbit 0 free.
    assert b.dock_name in ("Dry Dock2", "Dry Dock3")
    # One flying in per dock: `c` goes to the remaining dock.
    _arrive_far(c)
    assert {b.dock_name, c.dock_name} == {"Dry Dock2", "Dry Dock3"}
    # `a` inside `b`: `a` may not leave until `b` has gone.
    ss._dock(c)
    _occupy(b, "Dry Dock", 1)
    _occupy(a, "Dry Dock", 0)
    a.bearing_accum = a.leave_at
    a.bearing_prev = ss._radial(a.ship, _far().GetObject("Dry Dock"))
    _sim(DT)
    assert a.phase is ss.Phase.CIRCLING
    assert a.leave_at == pytest.approx((ss.CIRCLES + 1) * 2.0 * math.pi)
    ss._dock(b)
    a.bearing_accum = a.leave_at
    _sim(DT)
    assert a.phase is ss.Phase.LEAVING_DOCKS


def test_neighbouring_docks_keep_their_shuttles_apart(world):
    """R7: four shuttles circling Dry Dock and Dry Dock3 (89 GU apart) at
    once, two orbits each, never come within 2 x the shuttle radius + 5 GU
    of a shuttle at the other dock, never within MIN_SEPARATION_GU of any
    shuttle, never touch a station, and stay in their own bands."""
    _size_the_dry_docks()
    _far().GetObject("Dry Dock2").SetDead(1)
    for o in ss.roster():
        o.timer = 1e9
    four = ss.roster()[:4]
    state = {"cross": 1e9, "any": 1e9, "hits": [], "out_of_band": []}

    def watch(hits):
        for x, y, *_rest in hits:
            if x.GetName() in _names() or y.GetName() in _names():
                state["hits"].append((x.GetName(), y.GetName()))
        live = [s for s in four if s.ship is not None
                and s.ship.GetContainingSet() is _far()]
        for i, s in enumerate(live):
            if s.phase is ss.Phase.CIRCLING:
                near, far = ss._bands(s.dock_name)[s.orbit_slot]
                d = _dist(s.ship, _far().GetObject(s.dock_name))
                if not near - BAND_SLACK_IN <= d <= far + BAND_SLACK_OUT:
                    state["out_of_band"].append((s.name, s.orbit_slot, d))
            for t in live[i + 1:]:
                d = _dist(s.ship, t.ship)
                state["any"] = min(state["any"], d)
                if (s.phase is t.phase is ss.Phase.CIRCLING
                        and s.dock_name != t.dock_name):
                    state["cross"] = min(state["cross"], d)
    for pair in (four[:2], four[2:]):
        for s in pair:
            _arrive_far(s)
            s.ship.SetRadius(SHUTTLE_RADIUS)
        assert _sim(120.0, each=watch, until=lambda: all(
            s.phase is ss.Phase.CIRCLING for s in pair)) is not None
    assert sorted((s.dock_name, s.orbit_slot) for s in four) == [
        ("Dry Dock", 0), ("Dry Dock", 1), ("Dry Dock3", 0), ("Dry Dock3", 1)]
    assert _sim(900.0, each=watch, until=lambda: all(
        s.phase is not ss.Phase.CIRCLING for s in four)) is not None
    assert state["cross"] >= 2 * SHUTTLE_RADIUS + 5.0, state["cross"]
    assert state["any"] >= MIN_SEPARATION_GU, state["any"]
    assert state["hits"] == []
    assert state["out_of_band"] == []


def test_circles_twice_then_leaves(world):
    _size_the_dry_docks()
    s = _only_the_first()
    _arrive_far(s)
    s.ship.SetRadius(SHUTTLE_RADIUS)
    dock = _far().GetObject(s.dock_name)
    took_to = _sim(120.0, until=lambda: s.phase is ss.Phase.CIRCLING)
    assert took_to is not None
    assert s.bearing_accum == 0.0
    assert s.ship.GetAI() is not None
    state = {"prev": None, "swept": 0.0, "dmin": 1e9, "dmax": 0.0,
             "at_leave": None, "hits": []}

    def watch(hits):
        for a, b, *_rest in hits:
            if s.ship in (a, b):
                state["hits"].append((s.phase.name, a.GetName(), b.GetName()))
        if state["at_leave"] is not None:
            return
        ang, state["prev"] = _swept(state["prev"], s.ship, dock)
        state["swept"] += ang
        if s.phase is ss.Phase.CIRCLING:
            d = _dist(s.ship, dock)
            state["dmin"] = min(state["dmin"], d)
            state["dmax"] = max(state["dmax"], d)
            # Never leaves early: below two turns of real motion it circles.
            assert s.bearing_accum < 4 * math.pi
            assert s.bearing_accum == pytest.approx(state["swept"], abs=0.05)
        else:
            state["at_leave"] = state["swept"]
    took = _sim(600.0, until=lambda: s.phase is ss.Phase.LEAVING_DOCKS,
                each=watch)
    assert took is not None, (s.phase, s.bearing_accum)
    # It left on the tick its real motion completed two turns.
    assert 4 * math.pi <= state["at_leave"] < 4 * math.pi + 0.1
    near, far = ss._bands(s.dock_name)[s.orbit_slot]
    assert near - BAND_SLACK_IN <= state["dmin"]
    assert state["dmax"] <= far + BAND_SLACK_OUT
    assert state["hits"] == []
    assert s.ship.GetAI() is not None          # flying out to the lane


def test_a_shuttle_held_still_counts_no_turns(world):
    s = _only_the_first()
    _arrive_far(s)
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.CIRCLING) is not None
    _sim(10.0)
    turned = s.bearing_accum
    assert turned > 0.0
    # Held still (an AI that keeps it in place, at rest): no motion, no turns.
    s.ship.SetVelocity(App.TGPoint3(0.0, 0.0, 0.0))
    s.ai = ss._plain(s.ship, "Hold", "Stay")
    s.ship.SetAI(s.ai)
    dock = _far().GetObject(s.dock_name)
    state = {"prev": None, "swept": 0.0}

    def watch(_h):
        ang, state["prev"] = _swept(state["prev"], s.ship, dock)
        state["swept"] += ang
    _sim(30.0, each=watch)
    assert s.phase is ss.Phase.CIRCLING
    # It coasts to a stop (~0.05 rad); 30 s of circling would be ~1.5 rad.
    assert s.bearing_accum - turned < 0.1
    assert s.bearing_accum - turned == pytest.approx(state["swept"], abs=0.01)


def test_warps_back_to_starbase_12(world):
    s = _only_the_first()
    _arrive_far(s)
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.CIRCLING) is not None
    ss._enter(s, ss.Phase.LEAVING_DOCKS)
    far_lane = _far().GetObject(ss._lane_name(s))
    seen, closest = set(), [1e9]

    def watch(_h):
        seen.add(s.phase)
        if s.ship.GetContainingSet() is _far():
            closest[0] = min(closest[0], _dist(s.ship, far_lane))
    took = _sim(180.0, until=lambda: s.phase is ss.Phase.APPROACHING,
                each=watch)
    assert took is not None, sorted(p.name for p in seen)
    assert ss.Phase.WARPING_BACK in seen
    assert closest[0] < 15.0           # left from its own lane point
    assert s.ship.GetContainingSet() is _home()
    assert not warp_state.is_ship_warping(s.ship)
    assert _dist(s.ship, _home().GetObject(ss._lane_name(s))) < 15.0
    # Then Task 2's legs take it into the bay.
    assert _sim(300.0, until=lambda: s.phase is ss.Phase.DOCKED) is not None


def test_a_refused_warp_back_leaves_the_docks_again(world):
    s = _only_the_first()
    _arrive_far(s)
    ss._enter(s, ss.Phase.LEAVING_DOCKS)
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.WARPING_BACK) \
        is not None
    s.ship.ClearAI()                  # the Warp AI dropped, still in DryDock
    _sim(DT)
    assert s.phase is ss.Phase.LEAVING_DOCKS
    assert s.ship.GetAI() is not None
    assert _sim(180.0, until=lambda: s.phase is ss.Phase.APPROACHING) \
        is not None


def test_a_destroyed_dock_mid_circle(world, capsys):
    s = _only_the_first()
    _arrive_far(s)
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.CIRCLING) is not None
    _sim(10.0)
    first = s.dock_name
    _far().GetObject(first).SetDead(1)
    _sim(DT)
    # Another standing dock, flown to afresh.
    assert s.phase is ss.Phase.TO_DOCK
    assert s.dock_name in DOCKS and s.dock_name != first
    second = s.dock_name
    assert _sim(120.0, until=lambda: s.phase is ss.Phase.CIRCLING) is not None
    assert s.dock_name == second
    assert s.bearing_accum < 0.5
    # On the way to `second` again (re-entered until the RNG picks it), it is
    # removed from the set outright: the last one is chosen.
    third = next(n for n in DOCKS if n not in (first, second))
    for _ in range(50):
        ss._enter(s, ss.Phase.TO_DOCK)
        if s.dock_name == second:
            break
    assert s.dock_name == second
    _far().RemoveObjectFromSet(second)
    _sim(DT)
    assert s.phase is ss.Phase.TO_DOCK and s.dock_name == third
    # None left: out to the lane and home.
    _far().GetObject(third).SetDead(1)
    _sim(DT)
    assert s.phase is ss.Phase.LEAVING_DOCKS
    assert s.dock_name is None
    assert _sim(180.0, until=lambda: s.phase is ss.Phase.APPROACHING) \
        is not None
    # An arrival with no dock standing goes straight back out.
    _arrive_far(s)
    assert s.phase is ss.Phase.LEAVING_DOCKS
    assert "[shuttles]" not in capsys.readouterr().out


# ── Losses ───────────────────────────────────────────────────────────────────

def _kill(s, killer=None):
    """`s` takes a fatal hit through the real combat path (from `killer`, if
    any) and its death throes run out: ShipClass.SetDead fires ship_lifecycle
    "destroyed"."""
    from engine.appc import combat, ship_death
    ship = s.ship
    if killer is not None:
        combat.apply_hit(ship, 1.0e6, ship.GetWorldLocation(), killer,
                         weapon_type="phaser")
    else:
        ship_death.begin(ship)
    assert ship.IsDying() or ship.IsDead()
    ship_death.advance(ship_death.MAX_THROES_DURATION + 0.1)
    assert ship.IsDead()
    return ship


def test_a_destroyed_shuttle_is_lost_and_recorded(world):
    _sim(5.0)
    s = ss.roster()[0]
    assert s.phase is ss.Phase.UNDOCKING
    when = App.g_kUtopiaModule.GetGameTime()
    assert when > 0.0
    _kill(s, killer=world)
    assert s.phase is ss.Phase.LOST
    assert s.ship is None
    assert ss.losses() == [ss.Loss(index=1, name="TC Shuttle 1",
                                   set_name="Starbase12",
                                   game_time=pytest.approx(when),
                                   killer="player")]
    # An unattributed death records no killer.
    _sim(70.0, until=lambda: ss.roster()[1].ship is not None)
    _kill(ss.roster()[1])
    assert [(x.index, x.killer) for x in ss.losses()] == [(1, "player"),
                                                         (2, None)]


def test_a_lost_shuttle_never_relaunches(world):
    _sim(DT)
    s = ss.roster()[0]
    _kill(s)
    s.timer = 0.0
    _run(1.0)
    assert s.phase is ss.Phase.LOST and s.ship is None
    # Away and back (the restart), and its region built again: still lost.
    App.g_kSetManager.AddSet(App.SetClass_Create(), "Vesuvi6")
    _move_player_to(world, "Vesuvi6")
    ss.tick(DT)
    _move_player_to(world, "Starbase12")
    ss.tick(DT)
    import Systems.Starbase12.Starbase12 as sb
    sb.Initialize()
    _run(1.0)
    assert s.phase is ss.Phase.LOST and s.ship is None
    assert all(o.phase is not ss.Phase.LOST for o in ss.roster()[1:])


def test_reset_on_mission_change_brings_all_ten_back(world):
    _sim(DT)
    _kill(ss.roster()[0])
    assert ss.losses()
    # A mission change: reset, then the regions are built again.
    ss.reset()
    assert ss.losses() == []
    import Systems.Starbase12.Starbase12 as sb
    import Systems.DryDock.DryDock as dd
    sb.Initialize()
    dd.Initialize()
    r = ss.roster()
    assert [s.name for s in r] == _names()
    assert all(s.phase is ss.Phase.DOCKED and s.ship is None for s in r)
    assert [s.timer for s in r] == [i * 60.0 for i in range(10)]


# ── Quick Battle: a battle is a simulation ───────────────────────────────────

def _fake_qb():
    """A stand-in for the QuickBattle module: the two functions install()
    wraps, recording their calls."""
    import types
    qb = types.ModuleType("FakeQuickBattle")
    calls = []
    qb.StartSimulation2 = lambda *a: calls.append("start")
    qb.EndSimulation = lambda *a: calls.append("end")
    return qb, calls


def _halve_hull(ship):
    hull = ship.GetHull()
    hull.SetCondition(hull.GetCondition() * 0.5)


def test_install_wraps_start_and_end_once(world):
    qb, calls = _fake_qb()
    assert ss.install(qb) is True
    assert ss.install(qb) is False
    for name in ("StartSimulation2", "EndSimulation"):
        assert "_dauntless_shuttle_service_orig" in qb.__dict__[name].__dict__
    qb.StartSimulation2()
    qb.EndSimulation()
    assert calls == ["start", "end"]
    # Under another module's wrapper (spawn's): still found, never twice.
    inner = qb.EndSimulation

    def outer(*a):
        return inner(*a)
    outer._dauntless_spawn_orig = inner
    qb.EndSimulation = outer
    assert ss.install(qb) is False


def test_a_battle_docks_what_it_damaged_or_destroyed_and_records_nothing(world):
    qb, _calls = _fake_qb()
    ss.install(qb)
    _sim(130.0)
    a, b, c, d = ss.roster()[:4]
    assert all(x.ship is not None and x.phase is not ss.Phase.DOCKED
               for x in (a, b, c))
    # Damaged before the battle and not touched in it: carries on.
    _halve_hull(c.ship)
    c_ship = c.ship
    qb.StartSimulation2()
    old_a = a.ship
    _halve_hull(old_a)
    old_b = _kill(b, killer=world)
    assert b.phase is ss.Phase.LOST
    assert ss.losses() == []                  # never during a battle
    # Launched during the battle, then damaged: docked too.
    ss._launch(d)
    old_d = d.ship
    _halve_hull(old_d)
    qb.EndSimulation()
    for x, old in ((a, old_a), (b, old_b), (d, old_d)):
        assert x.phase is ss.Phase.DOCKED and x.ship is None, x.name
        assert x.timer == ss.DOCK_S
        assert old.GetContainingSet() is None, x.name
    assert c.ship is c_ship and c.phase is not ss.Phase.DOCKED
    assert ss.losses() == []
    flying = sorted(x.name for x in ss.roster() if x.ship is not None
                    and x.ship.GetContainingSet() is not None)
    assert sorted(n for _set, n in _sets_holding_shuttles()) == flying
    # The battle is over: a loss is recorded again.
    _kill(c)
    assert [x.index for x in ss.losses()] == [3]


def test_an_end_with_no_battle_docks_nothing(world):
    qb, _calls = _fake_qb()
    ss.install(qb)
    _sim(DT)
    s = ss.roster()[0]
    ship = s.ship
    _halve_hull(ship)
    qb.EndSimulation()
    assert s.ship is ship and s.phase is ss.Phase.UNDOCKING


# ── Rebuilt and deleted regions, stations coming back ────────────────────────

def test_shrunk_orbit_bands_choose_again_instead_of_raising(world, capsys):
    """A neighbour coming back to standing (a battle rebuild) shrinks a
    dock's bands under a circling shuttle: its orbit no longer exists, so it
    chooses again rather than fail."""
    from engine.systems import home_stations as hs
    s = _only_the_first()
    _far().GetObject("Dry Dock3").SetDead(1)
    wide = len(ss._bands("Dry Dock"))
    assert wide > 2
    _occupy(s, "Dry Dock", wide - 1)
    assert s.phase is ss.Phase.CIRCLING
    # Dry Dock3 rebuilt, as the battle restore rebuilds a home station.
    row = next(r for r in hs.stations_for_set("DryDock")
               if r.name == "Dry Dock3")
    _far().RemoveObjectFromSet("Dry Dock3")
    hs.forget_destroyed(row)
    hs.place_for_set(_far(), "DryDock")
    assert len(ss._bands("Dry Dock")) == 2
    _sim(DT)
    assert s.phase is ss.Phase.TO_DOCK
    assert s.dock_name is None or s.orbit_slot < len(ss._bands(s.dock_name))
    # Started on a slot that no longer exists (a hand-over): the same.
    s.dock_name, s.orbit_slot = "Dry Dock", wide - 1
    ss._enter(s, ss.Phase.CIRCLING)
    assert s.phase is ss.Phase.TO_DOCK
    assert s.ship.GetContainingSet() is _far()
    assert "[shuttles]" not in capsys.readouterr().out


def test_lane_points_without_the_anchor_station():
    """A region built while its anchor station is not standing (destroyed
    earlier this mission) still gets its lane points, from the station's own
    placement point: the pose a rebuilt station gets."""
    from engine.systems import home_stations as hs
    _fresh_world()
    ss.reset()
    hs._destroyed.add(("Starbase12", "Starbase 12"))
    try:
        import Systems.Starbase12.Starbase12 as sb
        sb.Initialize()
        pSet = _home()
        assert pSet.GetObject("Starbase 12") is None
        row = next(r for r in hs.stations_for_set("Starbase12")
                   if r.name == "Starbase 12")
        loc, rot = hs.read_point(row, pSet)
        fwd = rot.GetCol(1)
        lane = pSet.GetObject(ss.LANE_NAME)
        assert lane is not None
        a = lane.GetWorldLocation()
        assert (a.x, a.y, a.z) == pytest.approx(
            (loc.x + 2000.0 * fwd.x, loc.y + 2000.0 * fwd.y,
             loc.z + 2000.0 * fwd.z), abs=1e-3)
        for i in range(1, 11):
            assert pSet.GetObject("%s %d" % (ss.LANE_NAME, i)) is not None
    finally:
        hs.reset()
        ss.reset()


def _entering(s):
    _arrive_home(s)
    assert _sim(300.0, until=lambda: s.phase is ss.Phase.ENTERING) \
        is not None
    station = _starbase()
    assert station.GetObjID() in collisions._collision_disabled_ids(s.ship)
    return station


def test_a_region_rebuilt_mid_entering_docks_and_releases_the_mask(world):
    s = _only_the_first()
    old = _entering(s)
    import Systems.Starbase12.Starbase12 as sb
    sb.Initialize()
    assert _starbase() is not old
    assert s.phase is ss.Phase.DOCKED
    assert s.bay_station is None
    assert old.GetObjID() not in collisions._collision_disabled_ids(s.ship)


def test_a_station_rebuilt_mid_entering_moves_the_mask(world):
    """The battle restore rebuilds Starbase 12 in its set (a new object, a
    new ObjID): the entering shuttle's collisions go off with the new one and
    back on with the old."""
    from engine.systems import home_stations as hs
    s = _only_the_first()
    old = _entering(s)
    row = hs.home_station_of(old)
    _home().RemoveObjectFromSet("Starbase 12")
    new = hs._build(row, _home(), *hs.read_point(row, _home()))
    assert new.GetObjID() != old.GetObjID()
    _sim(DT)
    assert s.phase is ss.Phase.ENTERING
    mask = collisions._collision_disabled_ids(s.ship)
    assert new.GetObjID() in mask and old.GetObjID() not in mask
    assert s.bay_station is new


def test_a_deleted_set_docks_its_shuttles(world):
    """E8M2 deletes Starbase12 outright: the shuttles in it are docked."""
    _sim(DT)
    s = ss.roster()[0]
    pSet = _home()
    assert s.ship.GetContainingSet() is pSet
    App.g_kSetManager.DeleteSet("Starbase12")
    ss.tick(DT)
    assert s.phase is ss.Phase.DOCKED
    assert pSet.GetObject(s.name) is None


def test_a_stale_killer_never_carries_into_the_next_life(world):
    """A shuttle hit fatally in a battle that ends mid-throes comes back
    docked with a fresh ship: its next, unattributed death names no killer."""
    qb, _calls = _fake_qb()
    ss.install(qb)
    _sim(DT)
    s = ss.roster()[0]
    qb.StartSimulation2()
    from engine.appc import combat
    combat.apply_hit(s.ship, 1.0e6, s.ship.GetWorldLocation(), world,
                     weapon_type="phaser")
    assert s.ship.IsDying() and s.killer == "player"
    qb.EndSimulation()
    assert s.phase is ss.Phase.DOCKED and s.ship is None
    assert s.killer is None
    ss._launch(s)
    _kill(s)
    assert [(x.index, x.killer) for x in ss.losses()] == [(1, None)]


def test_the_owner_rebuild_docks_the_record_and_never_re_adds_old(world):
    """Insurance: should any restore path call the owner's rebuild, the
    roster record goes DOCKED and drops the old ship; nothing is built."""
    import types
    _sim(DT)
    s = ss.roster()[0]
    old = s.ship
    owner = owners.get(ss.OWNER_NAME)
    # Not this shuttle's current ship: nothing happens.
    assert owner.rebuild(App.ShipClass_Create("Other"),
                         types.SimpleNamespace(key=1)) is None
    assert s.ship is old and s.phase is ss.Phase.UNDOCKING
    old.GetContainingSet().RemoveObjectFromSet(s.name)   # as sim_restore does
    assert owner.rebuild(old, types.SimpleNamespace(key=1)) is None
    assert s.phase is ss.Phase.DOCKED and s.ship is None
    assert s.name not in [n for _set, n in _sets_holding_shuttles()]
    owner.after_rebuild(None, types.SimpleNamespace(key=1))
