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


# --- the whole-trip smooth curve (Mark, live 2026-09-28) --------------------
# "very tight around the body and plays out like the planetary body has
# repelled us magnetically" -> set out on a heading that avoids the body and
# turn over the course of the entire warp.

def _comfort_reach(o):
    return o.radius_gu + wp.comfort_gu(o.radius_gu)


def _assert_smooth_safe(path, start, end, obstacles):
    """No body entered; when the smooth curve was used, every obstacle whose
    comfort sphere holds neither endpoint keeps the full comfort margin."""
    assert path.point_at(0.0) == pytest.approx(tuple(map(float, start)), abs=1e-6)
    assert path.point_at(path.length_gu) == pytest.approx(tuple(map(float, end)), abs=1e-6)
    assert not path.enters_body
    worst = _sample_dists(path, obstacles, n=4000)
    for o in obstacles:
        near = min(_dist(start, o.center), _dist(end, o.center))
        if near <= o.radius_gu:
            continue
        assert worst[o.name] >= o.radius_gu - 1e-6, f"entered {o.name}"
        if path.smooth:
            assert path.comfort_kept
            if near >= _comfort_reach(o):
                assert worst[o.name] >= _comfort_reach(o) - 1.0, f"comfort of {o.name}"


def _headings(path, n=10):
    """Signed heading (radians, in the x-y map plane) at n+1 even stations."""
    out = []
    for i in range(n + 1):
        t = path.tangent_at(path.length_gu * i / n)
        out.append(math.atan2(t[1], t[0]))
    return out


def test_comfort_margin_is_the_radius_but_at_least_4000_gu():
    assert wp.COMFORT_MARGIN_MIN_GU == 4000.0
    assert wp.comfort_gu(1800.0) == 4000.0
    assert wp.comfort_gu(12000.0) == 12000.0


def test_one_body_in_the_way_gets_one_gentle_whole_trip_bow():
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun])
    assert p.smooth and p.comfort_kept and p.clearance_kept
    _assert_smooth_safe(p, (0, 0, 0), (100000, 0, 0), [sun])
    # Sets off angled AWAY from the body (it sits at +y, so heading -y).
    t0 = p.tangent_at(0.0)
    assert t0[1] < -math.sin(math.radians(5.0))
    # The turn is spread over the whole trip: every tenth turns the same
    # way, and no tenth holds more than a third of the total turn.
    h = _headings(p)
    steps = [b - a for a, b in zip(h, h[1:])]
    total = sum(steps)
    assert total > 0.0
    assert all(s > 0.02 * total for s in steps)
    assert max(steps) < total / 3.0
    # Far gentler than hugging the keep-out circle (curvature 1 / reach):
    # no tenth turns tighter than twice that radius.
    assert max(abs(s) for s in steps) / (p.length_gu / 10) < 0.5 / _comfort_reach(sun)


def test_smooth_path_is_arc_length_parameterised_and_tangent_continuous():
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun])
    assert p.smooth
    n = 2000
    ds = p.length_gu / n
    prev_p, prev_t = p.point_at(0.0), p.tangent_at(0.0)
    for i in range(1, n + 1):
        q, t = p.point_at(ds * i), p.tangent_at(ds * i)
        assert _dist(prev_p, q) == pytest.approx(ds, rel=2e-3)
        assert sum(a * b for a, b in zip(prev_t, t)) > math.cos(math.radians(0.5))
        # The tangent is the direction of travel.
        chord = tuple((b - a) / _dist(prev_p, q) for a, b in zip(prev_p, q))
        assert sum(a * b for a, b in zip(chord, t)) > math.cos(math.radians(0.5))
        prev_p, prev_t = q, t
    assert abs(sum(v * v for v in p.tangent_at(p.length_gu)) - 1.0) < 1e-9


def test_a_line_that_keeps_the_comfort_margin_stays_exactly_straight():
    body = wp.Obstacle("B", (50000.0, 20000.0, 0.0), 3000.0)   # 17,000 off, needs 7,000
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [body])
    assert not p.smooth and p.comfort_kept
    assert p.length_gu == pytest.approx(100000.0)
    assert p.point_at(37000.0) == pytest.approx((37000.0, 0.0, 0.0))


def test_a_line_inside_the_comfort_margin_but_outside_clearance_now_bends():
    # 6,000 off the line: clears radius + clearance (5,000), not + comfort (7,000).
    body = wp.Obstacle("B", (50000.0, 6000.0, 0.0), 3000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [body])
    assert p.smooth and p.comfort_kept
    _assert_smooth_safe(p, (0, 0, 0), (100000, 0, 0), [body])


def test_two_bodies_on_the_same_side_share_one_bow():
    obs = [wp.Obstacle("A", (35000.0, 3000.0, 0.0), 6000.0),
           wp.Obstacle("B", (65000.0, 5000.0, 0.0), 7000.0)]
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), obs)
    assert p.smooth
    _assert_smooth_safe(p, (0, 0, 0), (100000, 0, 0), obs)
    # One bow on the far side: never crosses back over the line mid-trip.
    ys = [p.point_at(p.length_gu * i / 50)[1] for i in range(1, 50)]
    assert all(y < 0.0 for y in ys)


def test_bodies_on_opposite_sides_get_an_s_bend():
    # Each body pokes into the line from its own side: bowing round either
    # one's far side is a big swing, slipping between them a small S.
    obs = [wp.Obstacle("A", (25000.0, 9000.0, 0.0), 5000.0),
           wp.Obstacle("B", (75000.0, -9000.0, 0.0), 5000.0)]
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), obs)
    assert p.smooth
    _assert_smooth_safe(p, (0, 0, 0), (100000, 0, 0), obs)
    # Passes A on its -y side and B on its +y side: the curve crosses the line.
    assert p.point_at(p.length_gu * 0.3)[1] < 0.0
    assert p.point_at(p.length_gu * 0.7)[1] > 0.0
    # And it stays in the map plane (the S does not dodge over a pole).
    assert all(abs(p.point_at(p.length_gu * i / 20)[2]) < 1e-6 for i in range(21))


def test_three_bodies_are_all_cleared_by_the_comfort_margin():
    obs = [wp.Obstacle("A", (25000.0, 2000.0, 0.0), 4000.0),
           wp.Obstacle("B", (50000.0, -1500.0, 500.0), 8000.0),
           wp.Obstacle("C", (80000.0, 6000.0, 0.0), 3000.0)]
    p = wp.plan_path((0, 0, 0), (120000, 0, 0), obs)
    assert p.smooth
    _assert_smooth_safe(p, (0, 0, 0), (120000, 0, 0), obs)


def test_ona1_to_ona3_sets_off_away_from_the_sun_on_a_smooth_curve():
    from engine.systems import resolve
    m = resolve.map_of("Ona")
    a1 = resolve.anchor_of("Ona1"); a3 = resolve.anchor_of("Ona3")
    obstacles = [wp.Obstacle(b.name, tuple(b.position_gu), b.radius_gu) for b in m.bodies]
    p = wp.plan_path(a1, a3, obstacles)
    assert p.smooth
    _assert_smooth_safe(p, a1, a3, obstacles)
    sun = next(o for o in obstacles if o.name == "Ona")
    chord = [b - a for a, b in zip(a1, a3)]
    n = math.sqrt(sum(v * v for v in chord))
    ex = [v / n for v in chord]
    to_sun = [c - a for c, a in zip(sun.center, a1)]
    lat_sun = [v - sum(x * y for x, y in zip(to_sun, ex)) * e for v, e in zip(to_sun, ex)]
    t0 = p.tangent_at(0.0)
    # Angled away from the sun from the first moment.
    assert sum(x * y for x, y in zip(t0, lat_sun)) < 0.0
    assert sum(x * y for x, y in zip(t0, ex)) < math.cos(math.radians(5.0))


def test_vesuvi_haven_moon1_smooth_crossings_keep_the_comfort_margin():
    import random
    from engine.systems import resolve
    m = resolve.map_of("Vesuvi")
    obstacles = [wp.Obstacle(b.name, tuple(b.position_gu), b.radius_gu) for b in m.bodies]
    haven = next(o for o in obstacles if o.name == "Haven")
    moon = next(o for o in obstacles if o.name == "Moon 1")
    mid = tuple((a + b) / 2 for a, b in zip(haven.center, moon.center))
    rng = random.Random(1864)
    smooth = 0
    for _ in range(120):
        th = rng.uniform(0, 2 * math.pi)
        off = (rng.uniform(-6000, 6000), rng.uniform(-6000, 6000), rng.uniform(-3000, 3000))
        d = (math.cos(th), math.sin(th), rng.uniform(-0.2, 0.2))
        start = tuple(m_ + o_ - 40000 * v for m_, o_, v in zip(mid, off, d))
        end = tuple(m_ + o_ + 40000 * v for m_, o_, v in zip(mid, off, d))
        p = wp.plan_path(start, end, obstacles)
        _assert_smooth_safe(p, start, end, obstacles)
        assert p.clearance_kept
        smooth += p.smooth
    assert smooth > 100


def test_seeded_3d_fuzz_smooth_curves_never_enter_and_keep_comfort():
    import random
    rng = random.Random(1966)
    smooth = 0
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
        p = wp.plan_path(start, end, obs)
        _assert_smooth_safe(p, start, end, obs)
        assert p.clearance_kept
        smooth += p.smooth
    assert smooth > 150


def test_no_comfortable_curve_falls_back_to_a_curve_at_the_hard_clearance(monkeypatch):
    real = wp._smooth_curve
    monkeypatch.setattr(wp, "_smooth_curve", lambda s, e, spheres, comfort, **kw: (
        None if comfort else real(s, e, spheres, comfort, **kw)))
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun])
    assert p.smooth and not p.comfort_kept and p.clearance_kept
    _assert_safe(p, (0, 0, 0), (100000, 0, 0), [sun])


def test_no_smooth_curve_at_all_falls_back_to_the_routed_path(monkeypatch):
    monkeypatch.setattr(wp, "_smooth_curve", lambda s, e, spheres, comfort, **kw: None)
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun])
    assert not p.smooth and not p.comfort_kept and p.clearance_kept
    _assert_safe(p, (0, 0, 0), (100000, 0, 0), [sun])


# --- start_dir: a re-plan continues the heading already flown ----------------

def _unit3(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


@pytest.mark.parametrize("obstacles", [
    [], [wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)],
    [wp.Obstacle("A", (30000.0, 9000.0, 0.0), 4000.0),
     wp.Obstacle("B", (70000.0, -3000.0, 2000.0), 6000.0)]])
@pytest.mark.parametrize("start_dir", [(1.0, 0.5, 0.0), (1.0, -0.3, 0.1), (0.6, 1.0, 0.0)])
def test_start_dir_curve_sets_off_along_the_heading_already_flown(obstacles, start_dir):
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), obstacles, start_dir=start_dir)
    assert p.tangent_at(0.0) == pytest.approx(_unit3(start_dir), abs=1e-9)
    assert p.smooth
    _assert_smooth_safe(p, (0, 0, 0), (100000, 0, 0), obstacles)
    assert p.clearance_kept


def test_start_dir_along_a_clear_chord_stays_exactly_straight():
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [], start_dir=(2.0, 0.0, 0.0))
    assert not p.smooth
    assert p.point_at(40000.0) == pytest.approx((40000.0, 0.0, 0.0))


def test_start_dir_facing_away_falls_back_to_a_fresh_plan():
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun], start_dir=(-1.0, 0.2, 0.0))
    fresh = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun])
    assert p.length_gu == fresh.length_gu
    assert p.tangent_at(0.0) == fresh.tangent_at(0.0)
