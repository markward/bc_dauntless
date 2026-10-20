"""SPIKE (damage redesign): a destroyed subsystem blows out from inside, but
only where its blast reaches the hull."""
import math

from engine.appc import internal_blast as ib


class _Ship:
    def __init__(self):
        self.hull = object()
        self.dying = 0

    def GetHull(self):
        return self.hull

    def IsDying(self):
        return self.dying


class _Sub:
    def __init__(self, ship, radius=0.25, name="Port Impulse"):
        self.ship, self.radius, self.name = ship, radius, name

    def _climb_to_ship(self):
        return self.ship

    def GetRadius(self):
        return self.radius

    def GetName(self):
        return self.name


def test_queue_takes_a_destroyed_subsystem_scaled_by_its_radius():
    ib.reset()
    ship = _Ship()
    ib.queue(_Sub(ship, radius=0.25))
    assert len(ib._pending) == 1
    assert ib._pending[0]["radius"] == 0.25 * ib.RADIUS_SCALE


def test_queue_ignores_the_hull_a_dying_ship_and_zero_radius():
    ib.reset()
    ship = _Ship()
    hull = _Sub(ship)
    ship.hull = hull
    ib.queue(hull)
    ib.queue(_Sub(ship, radius=0.0))
    dying = _Ship()
    dying.dying = 1
    ib.queue(_Sub(dying))
    assert ib._pending == []


def test_unrealized_ship_waits_then_ages_out():
    ib.reset()
    ib.queue(_Sub(_Ship()))
    ib.advance(1.0, ship_instances={})
    assert len(ib._pending) == 1
    ib.advance(ib.MAX_PENDING_AGE, ship_instances={})
    assert ib._pending == []


def test_find_exits_keeps_hull_inside_the_sphere_nearest_first(monkeypatch):
    # A flat hull at z = 0.2: rays from above hit it at distance 0.2 from the
    # centre; rays from below or sideways miss.
    def trace(iid, origin, direction, max_dist):
        if direction[2] >= -1e-6:
            return None
        t = (origin[2] - 0.2) / -direction[2]
        if t < 0 or t > max_dist:
            return None
        p = tuple(origin[i] + direction[i] * t for i in range(3))
        return p, (0.0, 0.0, 1.0), t
    monkeypatch.setattr(ib.host_io, "ray_trace_mesh", trace)
    exits = ib.find_exits(1, (0.0, 0.0, 0.0), 0.35, ib.EXIT_DIRS)
    assert exits, "the hull 0.2 above the centre is inside a 0.35 sphere"
    assert math.isclose(exits[0][2], 0.2, abs_tol=1e-6)
    assert all(e[2] <= 0.35 for e in exits)
    assert len(exits) <= ib.MAX_EXITS


def test_find_exits_is_empty_when_the_hull_is_out_of_reach(monkeypatch):
    def trace(iid, origin, direction, max_dist):
        if direction[2] >= -1e-6:
            return None
        t = (origin[2] - 1.0) / -direction[2]
        p = tuple(origin[i] + direction[i] * t for i in range(3))
        return p, (0.0, 0.0, 1.0), t
    monkeypatch.setattr(ib.host_io, "ray_trace_mesh", trace)
    assert ib.find_exits(1, (0.0, 0.0, 0.0), 0.35, ib.EXIT_DIRS) == []
