"""Tau Ceti shuttle service: roster, lanes, staggered start, docking out of
the world (a docked shuttle is in no set), and the Starbase 12 legs (undock,
depart, warp out; approach, enter the bay, dock)."""
import math

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
    launched = [s.ship is not None for s in ss.roster()]
    assert launched == [True] * 3 + [False] * 7


def test_paused_outside_tau_ceti(world):
    _run(65.0)
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


def test_no_two_shuttles_ever_share_a_pose(world):
    seen = {}
    loop = GameLoop()
    for _ in range(int(600 / DT)):
        loop.tick()
        poses = []
        for pSet in App.g_kSetManager._sets.values():
            for n in _names():
                o = pSet.GetObject(n)
                if o is not None:
                    l = o.GetWorldLocation()
                    poses.append((round(l.x, 3), round(l.y, 3), round(l.z, 3)))
        assert len(poses) == len(set(poses))
        seen[len(poses)] = True
    assert 1 in seen


def test_a_failing_launch_parks_the_shuttle_and_never_raises(world, monkeypatch, capsys):
    real = ss._bay_pose
    calls = []

    def bad(station):
        calls.append(1)
        if len(calls) == 1:
            raise AttributeError("no bay")
        return real(station)
    monkeypatch.setattr(ss, "_bay_pose", bad)
    _run(125.0)
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
    """Put shuttle `s` at the Starbase 12 lane point the way a warp back
    from the Dry Docks leaves it (Task 3's hand-over): in Starbase12, at the
    lane, no AI, collisions on, phase APPROACHING."""
    if s.ship is None:
        ss._launch(s)
    ship = s.ship
    ss._release_bay(s)
    ship.ClearAI()
    home = _home()
    held = ship.GetContainingSet()
    if held is not home:
        held.RemoveObjectFromSet(s.name)
        home.AddObjectToSet(ship, s.name)
    lane = home.GetObject(ss.LANE_NAME)
    rot = lane.GetWorldRotation()
    ship.SetTranslate(lane.GetWorldLocation())
    ship.AlignToVectors(rot.GetCol(1), rot.GetCol(2))
    ship.SetVelocity(App.TGPoint3(0.0, 0.0, 0.0))
    ship.UpdateNodeOnly()
    ss._enter(s, ss.Phase.APPROACHING)


def test_a_shuttle_undocks_and_reaches_the_lane(world):
    s = ss.roster()[0]
    lane = _home().GetObject(ss.LANE_NAME)
    seen, closest = set(), [1e9]

    def watch(_hits):
        seen.add(s.phase)
        if s.ship is not None and s.ship.GetContainingSet() is _home():
            closest[0] = min(closest[0], _dist(s.ship, lane))
    took = _sim(120.0, until=lambda: s.phase is ss.Phase.WARPING_OUT,
                each=watch)
    assert took is not None, sorted(p.name for p in seen)
    assert {ss.Phase.UNDOCKING, ss.Phase.DEPARTING} <= seen
    assert closest[0] < 150.0


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
    assert _dist(s.ship, far.GetObject(ss.LANE_NAME)) < 300.0


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
    lane = _home().GetObject(ss.LANE_NAME)
    assert s.phase is ss.Phase.WAITING
    assert s.ship.GetContainingSet() is _home()
    assert _dist(s.ship, lane) < 150.0
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
    """At the outside clearance point, stopped, collisions with the station
    back on."""
    assert s.phase is ss.Phase.APPROACHING
    approach = _home().GetObject("TC Shuttle Approach")
    assert _dist(s.ship, approach) <= 110.0
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
