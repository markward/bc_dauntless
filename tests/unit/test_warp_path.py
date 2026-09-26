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


def test_drop_out_lookahead_is_measured_to_the_surface():
    # 10,000 GU/s x 2 s = 20,000 GU: a surface at 28,200 is not yet in range.
    planet = wp.Obstacle("P", (30000.0, 0.0, 0.0), 1800.0)
    assert wp.drop_out((0, 0, 0), (1, 0, 0), 10000.0, [planet], lambda o: 4000.0) is None


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
    obs = [wp.Obstacle("B", (70000.0, 3000.0, 0.0), 8000.0),
           wp.Obstacle("A", (30000.0, -2000.0, 0.0), 5000.0)]
    a = wp.plan_path((0, 0, 0), (110000, 0, 0), obs, end_dir=(0.0, 1.0, 0.0))
    b = wp.plan_path((0, 0, 0), (110000, 0, 0), list(reversed(obs)), end_dir=(0.0, 1.0, 0.0))
    assert a.length_gu == b.length_gu
    for i in range(101):
        s = a.length_gu * i / 100
        assert a.point_at(s) == b.point_at(s)
