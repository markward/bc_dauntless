"""ray_sphere_entry + _resolve_hit_point fallback chain."""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.combat import ray_sphere_entry, _resolve_hit_point


# ── ray_sphere_entry ────────────────────────────────────────────────────────

def test_ray_sphere_entry_hits_front_of_sphere():
    origin = TGPoint3(0, 0, -10)
    direction = TGPoint3(0, 0, 1)
    center = TGPoint3(0, 0, 0)
    p = ray_sphere_entry(origin, direction, max_dist=20.0,
                          center=center, radius=2.0)
    assert p is not None
    assert p.x == pytest.approx(0.0)
    assert p.y == pytest.approx(0.0)
    assert p.z == pytest.approx(-2.0)


def test_ray_sphere_entry_origin_inside_returns_origin():
    origin = TGPoint3(0, 0, 0)
    direction = TGPoint3(0, 0, 1)
    center = TGPoint3(0, 0, 0)
    p = ray_sphere_entry(origin, direction, max_dist=10.0,
                          center=center, radius=2.0)
    assert p is not None
    # Inside the sphere: the "entry" is the origin itself.
    assert p.x == pytest.approx(0.0)
    assert p.y == pytest.approx(0.0)
    assert p.z == pytest.approx(0.0)


def test_ray_sphere_entry_miss_returns_none():
    origin = TGPoint3(10, 10, -10)
    direction = TGPoint3(0, 0, 1)
    center = TGPoint3(0, 0, 0)
    p = ray_sphere_entry(origin, direction, max_dist=20.0,
                          center=center, radius=2.0)
    assert p is None


def test_ray_sphere_entry_past_max_dist_returns_none():
    origin = TGPoint3(0, 0, -100)
    direction = TGPoint3(0, 0, 1)
    center = TGPoint3(0, 0, 0)
    p = ray_sphere_entry(origin, direction, max_dist=10.0,
                          center=center, radius=2.0)
    assert p is None


# ── _resolve_hit_point ──────────────────────────────────────────────────────

class _FakeShip:
    def __init__(self, x, y, z, r=10.0):
        self._loc = TGPoint3(x, y, z)
        self._r = r
    def GetWorldLocation(self): return self._loc
    def GetRadius(self): return self._r


class _FakeHost:
    """Minimal host stub: ray_trace_mesh returns a preconfigured value."""
    def __init__(self, result):
        self._result = result
        self.calls = []
    def ray_trace_mesh(self, instance_id, origin, direction, max_dist):
        self.calls.append((instance_id, origin, direction, max_dist))
        return self._result


def test_resolve_returns_mesh_hit_when_trace_succeeds():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=((1.0, 2.0, 3.0), (0.0, 0.0, -1.0), 5.0))
    p = _resolve_hit_point(
        host=host, ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p.x == pytest.approx(1.0)
    assert p.y == pytest.approx(2.0)
    assert p.z == pytest.approx(3.0)


def test_resolve_falls_back_to_sphere_entry_when_trace_misses():
    ship = _FakeShip(0, 0, 0, r=2.0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=None)
    p = _resolve_hit_point(
        host=host, ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    # Sphere of radius 2 at origin; ray enters at z=-2.
    assert p.z == pytest.approx(-2.0)


def test_resolve_returns_fallback_when_host_is_none():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    p = _resolve_hit_point(
        host=None, ship_instances=None, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p is fallback


def test_resolve_returns_fallback_when_ship_instances_missing():
    ship = _FakeShip(0, 0, 0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=((1.0, 2.0, 3.0), (0.0, 0.0, -1.0), 5.0))
    p = _resolve_hit_point(
        host=host, ship_instances={}, ship=ship,  # ship not in map
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p is fallback
    assert host.calls == []  # binding must not be called without an iid


def test_resolve_returns_fallback_when_binding_missing():
    """If host exists but lacks ray_trace_mesh (older build), fall through."""
    class HostWithoutTrace:
        pass
    ship = _FakeShip(0, 0, 0, r=2.0)
    fallback = TGPoint3(99, 99, 99)
    p = _resolve_hit_point(
        host=HostWithoutTrace(), ship_instances={ship: object()}, ship=ship,
        ray_origin=TGPoint3(0, 0, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    # Sphere entry preferred when ray clearly intersects sphere; otherwise
    # fallback.
    assert p.z == pytest.approx(-2.0)


def test_resolve_falls_back_to_caller_point_when_sphere_also_misses():
    ship = _FakeShip(0, 0, 0, r=2.0)
    fallback = TGPoint3(99, 99, 99)
    host = _FakeHost(result=None)
    p = _resolve_hit_point(
        host=host, ship_instances={ship: object()}, ship=ship,
        # Ray that misses the bounding sphere entirely.
        ray_origin=TGPoint3(100, 100, -10),
        ray_direction=TGPoint3(0, 0, 1),
        max_dist=20.0,
        fallback_point=fallback,
    )
    assert p is fallback
