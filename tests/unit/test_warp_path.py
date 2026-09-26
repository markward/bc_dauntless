# tests/unit/test_warp_path.py
"""The in-system warp planner (spec §1: Path, Speed policy, Body drop-out)."""
import math
import pytest
from engine.systems import warp_path as wp


def _dist(a, b):
    return math.dist(a, b)


def _min_clearance(path, obstacles, n=4000):
    worst = math.inf
    for i in range(n + 1):
        p = path.point_at(path.length_gu * i / n)
        for o in obstacles:
            worst = min(worst, _dist(p, o.center) - o.radius_gu - wp.clearance_gu(o.radius_gu))
    return worst


def test_clear_line_is_straight():
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [])
    assert p.length_gu == pytest.approx(100000.0)
    assert p.point_at(50000.0) == pytest.approx((50000.0, 0.0, 0.0))


def test_a_body_in_the_way_is_routed_around_with_clearance():
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun])
    assert _min_clearance(p, [sun]) >= -1e-6
    assert p.point_at(0.0) == pytest.approx((0.0, 0.0, 0.0))
    assert p.point_at(p.length_gu) == pytest.approx((100000.0, 0.0, 0.0))
    assert p.length_gu > 100000.0


def test_the_path_is_tangent_continuous():
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun], end_dir=(0.0, 1.0, 0.0))
    prev = p.tangent_at(0.0)
    steps = 20000
    for i in range(1, steps + 1):
        t = p.tangent_at(p.length_gu * i / steps)
        cos = sum(a * b for a, b in zip(prev, t))
        assert cos > math.cos(math.radians(2.0)), f"kink at step {i}"
        prev = t


def test_the_path_arrives_along_the_placement_forward():
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [], end_dir=(0.0, 1.0, 0.0))
    assert p.tangent_at(p.length_gu) == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)
    assert p.point_at(p.length_gu) == pytest.approx((100000.0, 0.0, 0.0))


def test_ona1_to_ona3_routes_around_the_sun():
    """Review Focus 1, on the real regenerated map."""
    from engine.systems import resolve
    m = resolve.map_of("Ona")
    a1 = resolve.anchor_of("Ona1"); a3 = resolve.anchor_of("Ona3")
    obstacles = [wp.Obstacle(b.name, tuple(b.position_gu), b.radius_gu) for b in m.bodies]
    p = wp.plan_path(a1, a3, [o for o in obstacles if o.name == "Ona"])
    assert _min_clearance(p, [o for o in obstacles if o.name == "Ona"]) >= -1e-6


@pytest.mark.parametrize("length,expected", [
    (100000.0, 10000.0), (5000.0, 2000.0), (2_000_000.0, 100000.0)])
def test_set_course_speed(length, expected):
    assert wp.set_course_speed(length) == pytest.approx(expected)


def test_drop_out_stops_at_the_standoff_on_the_line():
    # 15,000 GU/s x 2 s = 30,000 GU of lookahead reaches the surface at 28,200.
    planet = wp.Obstacle("P", (30000.0, 0.0, 0.0), 1800.0)
    d = wp.drop_out((0, 0, 0), (1, 0, 0), 15000.0, [planet], lambda o: 4000.0)
    assert d == pytest.approx((26000.0, 0.0, 0.0))


def test_drop_out_ignores_bodies_beyond_the_lookahead_and_off_the_line():
    far = wp.Obstacle("Far", (50000.0, 0.0, 0.0), 1800.0)     # surface 48,200 > 20,000
    side = wp.Obstacle("Side", (10000.0, 9000.0, 0.0), 1800.0)
    assert wp.drop_out((0, 0, 0), (1, 0, 0), 10000.0, [far, side], lambda o: 4000.0) is None


def test_drop_out_never_goes_backwards():
    planet = wp.Obstacle("P", (3000.0, 0.0, 0.0), 1800.0)     # already inside the standoff
    d = wp.drop_out((0, 0, 0), (1, 0, 0), 10000.0, [planet], lambda o: 4000.0)
    assert d == pytest.approx((0.0, 0.0, 0.0))


def test_drop_out_lookahead_is_measured_to_the_drop_point():
    # 10,000 GU/s x 2 s = 20,000 GU: the drop point at 26,000 is not yet in
    # range. (Was "..._to_the_surface": the lookahead counted a body once its
    # surface was in reach, and with a standoff more than the reach above the
    # surface the dash dropped short of it -- fix round 1 of Task 5.)
    planet = wp.Obstacle("P", (30000.0, 0.0, 0.0), 1800.0)
    assert wp.drop_out((0, 0, 0), (1, 0, 0), 10000.0, [planet], lambda o: 4000.0) is None


def test_drop_out_with_a_large_standoff_stops_exactly_at_it():
    """A region-arrival standoff far above the surface (Prendel's Moon 2:
    43,249 GU for a 1,800 GU moon): the drop is counted once the DROP POINT
    is in reach, so the dash stops at the standoff, not ~reach above the
    surface."""
    moon = wp.Obstacle("M", (100000.0, 0.0, 0.0), 1800.0)
    sd = lambda o: 40000.0
    reach = 10000.0 * wp.DROP_LOOKAHEAD_S
    # Stepping along the ray: nothing until the drop point is in reach...
    assert wp.drop_out((39000.0 - reach, 0, 0), (1, 0, 0), 10000.0, [moon], sd) is None
    # ...then exactly the standoff, from every point up to it.
    for x in (60000.0 - reach, 50000.0, 59999.0, 60000.0):
        d = wp.drop_out((x, 0, 0), (1, 0, 0), 10000.0, [moon], sd)
        assert d == pytest.approx((60000.0, 0.0, 0.0)), x


def test_drop_out_never_enters_the_body_even_with_a_small_standoff():
    planet = wp.Obstacle("P", (30000.0, 0.0, 0.0), 1800.0)
    d = wp.drop_out((0, 0, 0), (1, 0, 0), 20000.0, [planet], lambda o: 500.0)
    assert d == pytest.approx((28200.0, 0.0, 0.0))


def _joins(path):
    return path._starts[1:]


def _assert_smooth_joins(path):
    for s in _joins(path):
        before = path.tangent_at(s - 1e-7)
        after = path.tangent_at(s)
        assert max(abs(a - b) for a, b in zip(before, after)) < 1e-6
        assert path.point_at(s - 1e-7) == pytest.approx(path.point_at(s), abs=1e-5)


def test_joins_are_tangent_continuous_to_1e_6():
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun], end_dir=(0.0, 1.0, 0.0))
    assert len(_joins(p)) >= 3
    _assert_smooth_joins(p)


def test_several_obstacles_are_all_cleared_and_the_arrival_holds():
    obs = [wp.Obstacle("A", (30000.0, -2000.0, 0.0), 5000.0),
           wp.Obstacle("B", (70000.0, 3000.0, 0.0), 8000.0)]
    p = wp.plan_path((0, 0, 0), (110000, 0, 0), obs, end_dir=(-1.0, 0.0, 0.0))
    assert _min_clearance(p, obs) >= -1e-6
    assert p.point_at(p.length_gu) == pytest.approx((110000.0, 0.0, 0.0))
    assert p.tangent_at(p.length_gu) == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)
    _assert_smooth_joins(p)


def test_a_3d_route_clears_and_arrives_along_end_dir():
    body = wp.Obstacle("Body", (40000.0, 20000.0, 15000.0), 9000.0)
    end_dir = (0.0, 0.6, 0.8)
    p = wp.plan_path((0, 0, 0), (80000, 40000, 30000), [body], end_dir=end_dir)
    assert _min_clearance(p, [body]) >= -1e-6
    assert p.point_at(p.length_gu) == pytest.approx((80000.0, 40000.0, 30000.0))
    assert p.tangent_at(p.length_gu) == pytest.approx(end_dir, abs=1e-6)
    _assert_smooth_joins(p)


def test_planning_is_deterministic():
    # Two identical bodies mirrored across the chord, their clearance spheres
    # overlapping: passing above A or below B is an exact tie, so without a
    # canonical obstacle order the choice would follow the caller's list order.
    obs = [wp.Obstacle("B", (50000.0, -6000.0, 0.0), 8000.0),
           wp.Obstacle("A", (50000.0, 6000.0, 0.0), 8000.0)]
    a = wp.plan_path((0, 0, 0), (100000, 0, 0), obs)
    b = wp.plan_path((0, 0, 0), (100000, 0, 0), list(reversed(obs)))
    assert a.length_gu == b.length_gu
    for i in range(101):
        s = a.length_gu * i / 100
        assert a.point_at(s) == b.point_at(s)


# --- R6: the planner never enters a body ------------------------------------

def _sample_dists(path, obstacles, n=6000):
    worst = {o.name: math.inf for o in obstacles}
    for i in range(n + 1):
        p = path.point_at(path.length_gu * i / n)
        for o in obstacles:
            worst[o.name] = min(worst[o.name], _dist(p, o.center))
    return worst


def _assert_safe(path, start, end, obstacles, end_dir=None):
    """No body entered; every obstacle whose clearance sphere holds neither
    endpoint keeps its full clearance (R5/R6 exemptions)."""
    assert path.point_at(0.0) == pytest.approx(tuple(map(float, start)), abs=1e-6)
    assert path.point_at(path.length_gu) == pytest.approx(tuple(map(float, end)), abs=1e-6)
    assert not path.enters_body
    assert path.clearance_kept
    worst = _sample_dists(path, obstacles)
    for o in obstacles:
        ds, de = _dist(start, o.center), _dist(end, o.center)
        if min(ds, de) <= o.radius_gu:
            continue                                   # endpoint inside the body
        assert worst[o.name] >= o.radius_gu - 1e-6, f"entered {o.name}"
        reach = o.radius_gu + wp.clearance_gu(o.radius_gu)
        if min(ds, de) < reach:
            continue                                   # R5 exemption
        assert worst[o.name] >= reach - 1e-6, f"clearance of {o.name}"
    if end_dir is not None and path.end_dir_honoured:
        n = math.sqrt(sum(v * v for v in end_dir))
        assert path.tangent_at(path.length_gu) == pytest.approx(
            tuple(v / n for v in end_dir), abs=1e-6)


def test_overlapping_inflated_pair_is_never_crossed():
    obs = [wp.Obstacle("A", (40000.0, 5000.0, 0.0), 8000.0),
           wp.Obstacle("B", (55000.0, -5000.0, 0.0), 8000.0)]
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), obs)
    _assert_safe(p, (0, 0, 0), (100000, 0, 0), obs)


def test_vesuvi_haven_moon1_crossings_clear_every_body():
    """Real map: Haven and Moon 1 are 7,200 GU apart, inflated radii 7,400."""
    import random
    from engine.systems import resolve
    m = resolve.map_of("Vesuvi")
    obstacles = [wp.Obstacle(b.name, tuple(b.position_gu), b.radius_gu) for b in m.bodies]
    haven = next(o for o in obstacles if o.name == "Haven")
    moon = next(o for o in obstacles if o.name == "Moon 1")
    mid = tuple((a + b) / 2 for a, b in zip(haven.center, moon.center))
    rng = random.Random(1701)
    honoured = 0
    for _ in range(200):
        th = rng.uniform(0, 2 * math.pi)
        off = (rng.uniform(-6000, 6000), rng.uniform(-6000, 6000), rng.uniform(-3000, 3000))
        d = (math.cos(th), math.sin(th), rng.uniform(-0.2, 0.2))
        start = tuple(m_ + o_ - 40000 * v for m_, o_, v in zip(mid, off, d))
        end = tuple(m_ + o_ + 40000 * v for m_, o_, v in zip(mid, off, d))
        end_dir = None if rng.random() < 0.3 else (
            rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.3, 0.3))
        p = wp.plan_path(start, end, obstacles, end_dir=end_dir)
        _assert_safe(p, start, end, obstacles, end_dir)
        honoured += bool(end_dir is not None and p.end_dir_honoured)
    assert honoured > 100


@pytest.mark.parametrize("bearing", range(0, 360, 10))
def test_placement_tangential_to_its_planet_is_approached_safely(bearing):
    planet = [wp.Obstacle("P", (0.0, 0.0, 0.0), 1800.0)]
    th = math.radians(bearing)
    start = (150000 * math.cos(th), 150000 * math.sin(th), 0.0)
    p = wp.plan_path(start, (5000, 0, 0), planet, end_dir=(0.0, 1.0, 0.0))
    _assert_safe(p, start, (5000, 0, 0), planet, (0.0, 1.0, 0.0))
    assert p.end_dir_honoured


@pytest.mark.parametrize("bearing", range(0, 360, 10))
def test_placement_facing_away_from_its_planet_is_approached_safely(bearing):
    planet = [wp.Obstacle("P", (0.0, 0.0, 0.0), 1800.0)]
    th = math.radians(bearing)
    start = (150000 * math.cos(th), 150000 * math.sin(th), 0.0)
    p = wp.plan_path(start, (5000, 0, 0), planet, end_dir=(1.0, 0.0, 0.0))
    _assert_safe(p, start, (5000, 0, 0), planet, (1.0, 0.0, 0.0))
    assert p.end_dir_honoured


def test_seeded_fuzz_never_enters_a_body():
    import random
    rng = random.Random(4077)
    for _case in range(300):
        obs = []
        for k in range(rng.randint(1, 5)):
            r = rng.uniform(800, 12000)
            c = (rng.uniform(20000, 180000), rng.uniform(-30000, 30000), rng.uniform(-8000, 8000))
            obs.append(wp.Obstacle(f"O{k}", c, r))
            if rng.random() < 0.4:   # an overlapping companion
                r2 = rng.uniform(800, 4000)
                gap = r + r2 + rng.uniform(0.0, 0.5) * (wp.clearance_gu(r) + wp.clearance_gu(r2))
                u = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.3, 0.3))
                n = math.sqrt(sum(v * v for v in u))
                obs.append(wp.Obstacle(f"O{k}m", tuple(ci + gap * ui / n for ci, ui in zip(c, u)), r2))
        start = (0.0, rng.uniform(-5000, 5000), rng.uniform(-2000, 2000))
        end = (200000.0, rng.uniform(-20000, 20000), rng.uniform(-5000, 5000))
        end_dir = None if rng.random() < 0.25 else (
            rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.5, 0.5))
        p = wp.plan_path(start, end, obs, end_dir=end_dir)
        _assert_safe(p, start, end, obs, end_dir)
