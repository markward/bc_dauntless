"""engine/appc/warp_flight.py — one in-system warp flight for every ship.

ShipClass.InSystemWarp (SDK AI/PlainAI/Intercept.py) keeps its contract; the
per-tick motion underneath is a WarpFlight: planned in system coordinates,
routed around bodies, facing its path, ending by an exit policy. Spec:
docs/superpowers/specs/2026-09-25-in-system-warp-design.md section 1.

Ships here are built bare (no SDK ship script), as test_in_system_warp.py
does; the ones placed in a set use a plain set or a region created through
BC's own region module (tests/helpers/mapped_regions.load_region).
"""
import math

import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.planet import Planet_Create
from engine.appc.sets import SetClass_Create
from engine.appc.ship_motion import _step_ship_motion
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem
from engine.appc import warp_flight
from engine.appc.warp_flight import WarpFlight
from engine.systems import resolve
from engine.systems.warp_path import HEADING_DASH_GUPS, Obstacle, clearance_gu
from tests.helpers.mapped_regions import load_region

_DT = 1.0 / 60.0


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


@pytest.fixture
def posted(monkeypatch):
    """Every event the engine posts during the test, in order."""
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    return events


def _of_type(posted, event_type):
    return [e for e in posted if e.GetEventType() == event_type]


def _make_ship(xyz=(0.0, 0.0, 0.0), pSet=None, name="ship") -> ShipClass:
    s = ShipClass()
    s.SetName(name)
    if pSet is not None:
        pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    s._impulse_engine_subsystem = ies
    return s


def _plain_set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def _xyz(p):
    return (p.x, p.y, p.z)


def _fly(ship, max_ticks=200_000, each=None):
    """Advance the integrator until the flight ends; `each(ship)` per tick."""
    for _ in range(max_ticks):
        if ship._insystem_warp_transit is None:
            return
        _step_ship_motion(ship, _DT)
        if each is not None:
            each(ship)
    raise AssertionError("warp flight never ended")


def _old_straight_line(ship_xyz, target_xyz, drop, warp_speed, current_speed):
    """The pre-WarpFlight integrator (ship_motion._step_in_system_warp before
    this change), recorded verbatim: per tick, straight at the live target,
    landing exactly on the drop edge. Returns (positions, final velocity)."""
    px, py, pz = ship_xyz
    tx, ty, tz = target_xyz
    positions = []
    for _ in range(200_000):
        dx, dy, dz = tx - px, ty - py, tz - pz
        d = (dx * dx + dy * dy + dz * dz) ** 0.5
        ux, uy, uz = dx / d, dy / d, dz / d
        remaining = d - float(drop)
        step = warp_speed * _DT
        if step >= remaining:
            px, py, pz = tx - ux * drop, ty - uy * drop, tz - uz * drop
            positions.append((px, py, pz))
            s = current_speed
            return positions, (ux * s, uy * s, uz * s)
        px, py, pz = px + ux * step, py + uy * step, pz + uz * step
        positions.append((px, py, pz))
    raise AssertionError("old integrator never arrived")


# ── 1. The existing contract, pinned again through the flight ──────────────

def test_setless_ship_keeps_todays_arrival_speed_and_exit():
    ship = _make_ship()
    ship._current_speed = 3.0
    target = _make_ship((0.0, 1000.0, 0.0), name="target")

    assert ship.InSystemWarp(target, 295.0) == 1
    assert isinstance(ship._insystem_warp_transit, WarpFlight)
    _step_ship_motion(ship, _DT)
    # BC's fixed in-system warp speed, whatever the ship's impulse.
    assert ship.GetVelocity().y == pytest.approx(75.0)
    _fly(ship)

    assert _xyz(ship.GetTranslate()) == pytest.approx((0.0, 705.0, 0.0))
    v = ship.GetVelocity()
    assert v.y == pytest.approx(ship._current_speed)
    assert ship._current_speed == 3.0
    assert ship.IsDoingInSystemWarp() == 0


# ── 2. Mapped region: routed around Ona 1, across two regions ──────────────

def test_mapped_intercept_routes_around_ona_1_and_arrives():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    planet = resolve.map_of("Ona").body("Ona 1")
    centre = tuple(planet.position_gu)
    keep_out = planet.radius_gu + clearance_gu(planet.radius_gu)

    # Ship 20,000 GU "south" of the planet in Ona1; target 20,000 GU "north"
    # of it, held in Ona2's coordinates (a cross-region target).
    ship_sys = (centre[0], centre[1] - 20000.0, centre[2])
    target_sys = (centre[0], centre[1] + 20000.0, centre[2])
    ship = _make_ship(tuple(s - a for s, a in zip(ship_sys, a1)), ona1, "ship")
    target = _make_ship(tuple(s - a for s, a in zip(target_sys, a2)), ona2,
                        "target")

    assert ship.InSystemWarp(target, 500.0) == 1
    gaps = []

    def record(s):
        p = warp_flight.to_system(s, _xyz(s.GetTranslate()))
        gaps.append(math.dist(p, centre))

    _fly(ship, each=record)

    assert len(gaps) > 10
    assert min(gaps) >= keep_out - 1e-3
    end = warp_flight.to_system(ship, _xyz(ship.GetTranslate()))
    assert math.dist(end, target_sys) <= 500.0 + 1e-6
    assert ship.IsDoingInSystemWarp() == 0


# ── 3. Unmapped set: routed around the set's own Planet ────────────────────

def test_unmapped_set_routes_around_its_own_planet():
    pSet = _plain_set("Arena")
    planet = Planet_Create(1000.0, "")
    planet.SetName("Rock")
    pSet.AddObjectToSet(planet, "Rock")
    planet.SetTranslateXYZ(0.0, 10000.0, 0.0)
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")
    target = _make_ship((0.0, 20000.0, 0.0), pSet, "target")

    assert warp_flight.obstacles_for(ship) == [
        Obstacle("Rock", (0.0, 10000.0, 0.0), 1000.0)]

    assert ship.InSystemWarp(target, 300.0) == 1
    gaps = []
    _fly(ship, each=lambda s: gaps.append(
        math.dist(_xyz(s.GetTranslate()), (0.0, 10000.0, 0.0))))

    assert min(gaps) >= 1000.0 + clearance_gu(1000.0) - 1e-3
    assert math.dist(_xyz(ship.GetTranslate()), (0.0, 20000.0, 0.0)) <= 300.0 + 1e-6


# ── 4. Facing the path ─────────────────────────────────────────────────────

def test_ship_faces_the_path_tangent_every_tick_of_a_curved_flight():
    pSet = _plain_set("Arena")
    planet = Planet_Create(1000.0, "")
    planet.SetName("Rock")
    pSet.AddObjectToSet(planet, "Rock")
    planet.SetTranslateXYZ(0.0, 10000.0, 0.0)
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")
    target = _make_ship((0.0, 20000.0, 0.0), pSet, "target")
    ship.InSystemWarp(target, 300.0)

    cosines, headings = [], []

    def check(s):
        if s._insystem_warp_transit is None:
            return                       # the exit tick carries impulse speed
        v = s.GetVelocity()
        n = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        f = s.GetWorldRotation().GetCol(1)
        u = s.GetWorldRotation().GetCol(2)
        cosines.append((f.x * v.x + f.y * v.y + f.z * v.z) / n)
        headings.append(math.atan2(v.x, v.y))
        # Up stays perpendicular to forward and close to the ship's up (+Z).
        assert abs(f.x * u.x + f.y * u.y + f.z * u.z) < 1e-9
        assert u.z > 0.999

    _fly(ship, each=check)

    assert cosines and min(cosines) > 0.999
    assert max(headings) - min(headings) > 0.3, "flight was not curved"


# ── 5. ET_IN_SYSTEM_WARP once each way ─────────────────────────────────────

def test_routed_flight_posts_true_once_and_false_once(posted):
    pSet = _plain_set("Arena")
    planet = Planet_Create(1000.0, "")
    planet.SetName("Rock")
    pSet.AddObjectToSet(planet, "Rock")
    planet.SetTranslateXYZ(0.0, 10000.0, 0.0)
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")
    target = _make_ship((0.0, 20000.0, 0.0), pSet, "target")
    posted.clear()

    ship.InSystemWarp(target, 300.0)
    _fly(ship)

    evts = _of_type(posted, App.ET_IN_SYSTEM_WARP)
    assert [e.GetBool() for e in evts] == [1, 0]
    assert all(e.GetDestination() is ship for e in evts)
    assert ship._insystem_warp_transit is None


# ── 6. Review Focus 5: an unobstructed same-set warp is today's trajectory ─

def test_unobstructed_same_set_warp_is_byte_for_byte_the_old_trajectory():
    pSet = _plain_set("Arena")
    start = (12.5, -40.25, 3.0)
    goal = (310.0, 3000.0, -77.0)
    ship = _make_ship(start, pSet, "ship")
    ship._current_speed = 4.2
    target = _make_ship(goal, pSet, "target")
    # Face the target exactly so the facing gate passes.
    d = TGPoint3(*(g - s for g, s in zip(goal, start)))
    ship.AlignToVectors(d, TGPoint3(0.0, 0.0, 1.0))

    expected, v_end = _old_straight_line(start, goal, 295.0, 75.0, 4.2)
    assert ship.InSystemWarp(target, 295.0) == 1
    got = []
    _fly(ship, each=lambda s: got.append(_xyz(s.GetTranslate())))

    assert got == expected
    assert _xyz(ship.GetVelocity()) == v_end


# ── Heading flights: body drop-out ─────────────────────────────────────────

def test_heading_flight_drops_out_at_the_standoff_with_engaged_impulse():
    pSet = _plain_set("Arena")
    planet = Planet_Create(1000.0, "")
    planet.SetName("Rock")
    pSet.AddObjectToSet(planet, "Rock")
    planet.SetTranslateXYZ(0.0, 50000.0, 0.0)
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")

    flight = WarpFlight(heading=(0.0, 1.0, 0.0), speed_policy="heading",
                        exit_policy="engaged_impulse", engaged_speed=5.0)
    ship.begin_warp_flight(flight)
    assert ship.IsDoingInSystemWarp() == 1
    _step_ship_motion(ship, _DT)
    assert ship.GetVelocity().y == pytest.approx(HEADING_DASH_GUPS)
    _fly(ship)

    # Default standoff (R1): one radius above the surface, 2 x radius.
    assert _xyz(ship.GetTranslate()) == pytest.approx((0.0, 48000.0, 0.0))
    assert flight.ended_reason == "body"
    assert flight.drop_point == pytest.approx((0.0, 48000.0, 0.0))
    assert _xyz(ship.GetVelocity()) == pytest.approx((0.0, 5.0, 0.0))
    assert ship._current_speed == 5.0


def test_heading_flight_uses_the_callers_standoff():
    pSet = _plain_set("Arena")
    planet = Planet_Create(1000.0, "")
    planet.SetName("Rock")
    pSet.AddObjectToSet(planet, "Rock")
    planet.SetTranslateXYZ(0.0, 50000.0, 0.0)
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")

    flight = WarpFlight(heading=(0.0, 1.0, 0.0), speed_policy="heading",
                        exit_policy="rest", standoff_of=lambda o: 7000.0)
    ship.begin_warp_flight(flight)
    _fly(ship)

    assert _xyz(ship.GetTranslate()) == pytest.approx((0.0, 43000.0, 0.0))
    assert _xyz(ship.GetVelocity()) == pytest.approx((0.0, 0.0, 0.0))


# ── Set Course destination: a point with an arrival direction ──────────────

def test_point_destination_arrives_along_end_dir_at_rest():
    pSet = _plain_set("Arena")
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")
    ship._current_speed = 9.0
    end, end_dir = (30000.0, 30000.0, 0.0), (1.0, 0.0, 0.0)

    flight = WarpFlight(target=(end, end_dir), speed_policy="set_course",
                        exit_policy="rest")
    ship.begin_warp_flight(flight)
    ticks = [0]
    _fly(ship, each=lambda s: ticks.__setitem__(0, ticks[0] + 1))

    # Set Course: ~10 s flash to flash (DASH_TRIP_S) at 60 Hz.
    assert ticks[0] == pytest.approx(600, abs=2)
    assert _xyz(ship.GetTranslate()) == pytest.approx(end)
    f = ship.GetWorldRotation().GetCol(1)
    assert _xyz(f) == pytest.approx(end_dir, abs=1e-6)
    assert _xyz(ship.GetVelocity()) == pytest.approx((0.0, 0.0, 0.0))
    assert ship._current_speed == 0.0
    assert flight.ended_reason == "arrived"


# ── Frame helpers ──────────────────────────────────────────────────────────

def test_setless_ship_frame_helpers_are_identity_and_have_no_obstacles():
    ship = _make_ship((1.0, 2.0, 3.0))
    assert warp_flight.obstacles_for(ship) == []
    assert warp_flight.to_system(ship, (1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)
    assert warp_flight.to_local(ship, (1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0)


def test_mapped_region_obstacles_are_the_system_maps_bodies():
    ona1 = load_region("Ona", "Ona1")
    ship = _make_ship((0.0, 0.0, 0.0), ona1, "ship")
    m = resolve.map_of("Ona")
    assert warp_flight.obstacles_for(ship) == [
        Obstacle(b.name, tuple(b.position_gu), b.radius_gu) for b in m.bodies]
    a1 = resolve.anchor_of("Ona1")
    assert warp_flight.to_system(ship, (1.0, 2.0, 3.0)) == pytest.approx(
        (a1[0] + 1.0, a1[1] + 2.0, a1[2] + 3.0))
    assert warp_flight.to_local(ship, warp_flight.to_system(
        ship, (1.0, 2.0, 3.0))) == pytest.approx((1.0, 2.0, 3.0))


def test_stop_in_system_warp_marks_the_flight_aborted():
    ship = _make_ship()
    target = _make_ship((0.0, 1000.0, 0.0), name="target")
    ship.InSystemWarp(target, 295.0)
    flight = ship._insystem_warp_transit
    ship.StopInSystemWarp()
    assert flight.ended_reason == "aborted"
    assert ship.IsDoingInSystemWarp() == 0


# ── 11. R8 with the smooth curve: no flip-flop, no kink ────────────────────

# The drifting-target scenarios below were drawn for a 630 GU/s warp. At BC's
# fixed 75 GU/s the same geometry needs the target's per-tick drift scaled
# down, and the tick budgets up, by this ratio -- otherwise a target drifting
# faster than the warp can never be caught (20 GU a tick = 1,200 GU/s; real
# targets move at impulse, <= ~20 GU/s).
_SCALE = ShipClass.IN_SYSTEM_WARP_SPEED_GUPS / 630.0

@pytest.mark.parametrize("drift", [0.0, 1.5, -1.5, 4.0])
def test_ai_flight_round_a_body_turns_smoothly_as_its_target_drifts(drift, monkeypatch):
    """An AI Intercept whose line to its target is blocked flies the planner's
    whole-trip curve (Mark, 2026-09-28) and keeps flying it while the target
    drifts: no flip-flop onto the straight chord mid-curve, every R8 re-plan
    sets off along the heading already flown, and the body keeps the comfort
    margin."""
    from engine.systems import warp_path
    from engine.systems.warp_path import comfort_gu
    plans = []

    def spy(*args, **kwargs):
        path = warp_path.plan_path(*args, **kwargs)
        plans.append((len(headings), path.tangent_at(0.0)))
        return path

    monkeypatch.setattr(warp_flight, "plan_path", spy)
    pSet = _plain_set("Arena")
    planet = Planet_Create(1000.0, "")
    planet.SetName("Rock")
    pSet.AddObjectToSet(planet, "Rock")
    planet.SetTranslateXYZ(0.0, 10000.0, 0.0)
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")
    target = _make_ship((600.0, 20000.0, 0.0), pSet, "target")
    assert ship.InSystemWarp(target, 300.0) == 1

    headings, dirs, gaps, modes = [], [], [], []

    def each(s):
        p = target.GetTranslate()
        target.SetTranslateXYZ(p.x + drift * _SCALE, p.y, p.z)
        gaps.append(math.dist(_xyz(s.GetTranslate()), (0.0, 10000.0, 0.0)))
        if s._insystem_warp_transit is None:
            return
        v = s.GetVelocity()
        n = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        headings.append(math.atan2(v.x, v.y))
        dirs.append((v.x / n, v.y / n, v.z / n))
        modes.append(s._insystem_warp_transit._path is None)

    _fly(ship, each=each)

    assert max(headings) - min(headings) > 0.3, "flight was not curved"
    # Curved, then (once the live drop point is in clear view) straight at
    # the live target -- never back and forth.
    assert modes[0] is False
    assert sum(a != b for a, b in zip(modes, modes[1:])) <= 1
    if drift:
        assert len(plans) >= 2, "the target never moved past the R8 threshold"
    for tick, first in plans[1:]:
        assert first == pytest.approx(dirs[tick - 1], abs=1e-9)
    jumps = [abs(b - a) for a, b in zip(headings, headings[1:])]
    assert max(jumps) <= warp_flight.AI_WARP_TURN_RATE_RAD_S * _DT + 1e-9
    # The curve keeps the comfort margin; the straight line it hands over to
    # holds while it keeps the hard clearance (the hysteresis).
    curved = [g for g, m in zip(gaps, modes) if m is False]
    assert min(curved) >= 1000.0 + comfort_gu(1000.0) - 1.0
    assert min(gaps) >= 1000.0 + clearance_gu(1000.0) - 1.0


# ── 12. The drop edge is measured from the LIVE target (review of b80085ba) ─

_AI_STEP_GU = ShipClass.IN_SYSTEM_WARP_SPEED_GUPS * _DT   # one tick of AI warp travel


def _heading_change(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return math.acos(max(-1.0, min(1.0, dot)))


@pytest.mark.parametrize("drift", [
    (0.5, 0.0), (1.5, 0.0), (4.0, 0.0), (0.0, 3.0), (2.0, 2.0),
    (0.0, -10.0), (0.0, -20.0), (-1.0, -5.0), (3.0, -8.0)])
def test_ai_flight_round_a_body_ends_on_the_live_drop_edge(drift):
    """Intercept relies on the drop edge (SetInSystemWarpDistance): however
    the target moves, the flight ends within one tick's travel of ``drop``
    from where the target IS, in bounded time, with the nose turning at most
    AI_WARP_TURN_RATE_RAD_S (3 deg a tick at 60 Hz), keeping the hard
    clearance throughout. Measured before the fix: 325..1163 GU for the
    drifts, never ending for a closing target."""
    pSet = _plain_set("Arena")
    planet = Planet_Create(1000.0, "")
    planet.SetName("Rock")
    pSet.AddObjectToSet(planet, "Rock")
    planet.SetTranslateXYZ(0.0, 10000.0, 0.0)
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")
    target = _make_ship((600.0, 20000.0, 0.0), pSet, "target")
    drop = 295.0
    assert ship.InSystemWarp(target, drop) == 1

    flown, gaps, used = [], [], []

    def each(s):
        p = target.GetTranslate()
        used.append(_xyz(p))                  # where this tick's step aimed
        target.SetTranslateXYZ(p.x + drift[0] * _SCALE,
                               p.y + drift[1] * _SCALE, p.z)
        gaps.append(math.dist(_xyz(s.GetTranslate()), (0.0, 10000.0, 0.0)))
        f = s.GetWorldRotation().GetCol(1)
        flown.append((f.x, f.y, f.z))

    budget = int(4000 / _SCALE)
    _fly(ship, max_ticks=budget, each=each)

    assert len(used) < budget
    end = _xyz(ship.GetTranslate())
    assert abs(math.dist(end, used[-1]) - drop) <= _AI_STEP_GU + 1e-6
    # A target whose line runs through the body (|x| < 1,000 on the way
    # down) brings its own drop point inside the clearance: R5 then only
    # promises the body is never entered.
    through = drift[1] < 0.0 and any(abs(u[0]) < 1000.0 + clearance_gu(1000.0)
                                      and abs(u[1] - 10000.0) < 3000.0 for u in used)
    floor = 1000.0 if through else 1000.0 + clearance_gu(1000.0)
    assert min(gaps) >= floor - 1.0
    cap = warp_flight.AI_WARP_TURN_RATE_RAD_S * _DT
    turns = [_heading_change(a, b) for a, b in zip(flown, flown[1:])]
    assert max(turns) <= cap + 1e-9


def test_a_target_crossing_the_ship_turns_the_nose_instead_of_snapping():
    """The target sweeps past behind the ship mid-curve: the pin to the
    heading flown is dropped (it faces away from the new chord) and the nose
    turns at the cap rather than snapping (77-124 deg in one tick before)."""
    pSet = _plain_set("Arena")
    planet = Planet_Create(1000.0, "")
    planet.SetName("Rock")
    pSet.AddObjectToSet(planet, "Rock")
    planet.SetTranslateXYZ(0.0, 10000.0, 0.0)
    ship = _make_ship((0.0, 0.0, 0.0), pSet, "ship")
    target = _make_ship((600.0, 20000.0, 0.0), pSet, "target")
    assert ship.InSystemWarp(target, 295.0) == 1
    flown, gaps = [], []
    ticks = [0]

    def each(s):
        ticks[0] += 1
        if ticks[0] == int(400 / _SCALE):     # jump the target behind the ship
            p = _xyz(s.GetTranslate())
            target.SetTranslateXYZ(p[0] - 3000.0, p[1] - 12000.0, 0.0)
        gaps.append(math.dist(_xyz(s.GetTranslate()), (0.0, 10000.0, 0.0)))
        f = s.GetWorldRotation().GetCol(1)
        flown.append((f.x, f.y, f.z))

    _fly(ship, max_ticks=int(4000 / _SCALE), each=each)
    cap = warp_flight.AI_WARP_TURN_RATE_RAD_S * _DT
    turns = [_heading_change(a, b) for a, b in zip(flown, flown[1:])]
    assert max(turns) <= cap + 1e-9
    assert min(gaps) >= 1000.0 + clearance_gu(1000.0) - 1.0


@pytest.mark.parametrize("offset", [6999.0, 7000.0 - 1e-6, 7000.0, 7000.0 + 1e-6, 7001.0])
def test_the_flight_and_the_planner_agree_on_a_clear_line_at_the_boundary(offset):
    """One keep-out test for both: a line the planner draws straight is one
    the flight flies straight, to the last tolerance."""
    from engine.systems import warp_path
    body = [Obstacle("B", (50000.0, offset, 0.0), 3000.0)]   # comfort reach 7,000
    planned = warp_path.plan_path((0.0, 0.0, 0.0), (100000.0, 0.0, 0.0), body)
    straight = not planned.smooth and planned.length_gu == pytest.approx(100000.0)
    assert warp_flight._chord_clear((0.0, 0.0, 0.0), (100000.0, 0.0, 0.0), body) == straight
