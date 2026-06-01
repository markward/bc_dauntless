"""Torpedo impact point is the mesh-trace return value when a host is
wired, not the torpedo's post-advance position."""
import pytest
from unittest.mock import patch

from engine.appc.events import WeaponHitEvent
from engine.appc.math import TGPoint3
from engine.appc import projectiles
from engine.appc.projectiles import Torpedo, register
from engine.host_loop import _advance_combat


class _CapturingHost:
    """Stub host: ray_trace_mesh returns a fixed surface point so the
    test can prove it propagated through to apply_hit's hit_point."""
    SURFACE_POINT = (12.5, -3.0, 7.25)

    def __init__(self):
        self.shield_hits = []
    def ray_trace_mesh(self, iid, origin, direction, max_dist):
        return (self.SURFACE_POINT, (0.0, 0.0, -1.0), 1.0)
    def shield_hit(self, instance_id, point, rgba, intensity):
        self.shield_hits.append(point)
    def __getattr__(self, name):
        # set_torpedoes / set_hit_vfx / set_phaser_beams are touched by
        # _advance_combat; provide silent no-op accessors so the call
        # doesn't raise.
        return lambda *a, **kw: None


@pytest.fixture(autouse=True)
def clear_torpedo_registry():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


def test_torpedo_hit_uses_mesh_trace_point():
    from tests.unit.test_torpedo_advance import _FakeShip

    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    t = Torpedo()
    t._position = TGPoint3(0, 0, 0)
    t._velocity = TGPoint3(10, 0, 0)
    t._ttl = 30.0
    t._age = 0.0
    t._source_ship = src
    t._damage = 100.0
    register(t)

    host = _CapturingHost()
    captured = {}
    sentinel = object()

    # Patch apply_hit to capture the hit_point it receives.
    import engine.appc.combat as combat

    def spy(ship, damage, hit_point, source, subsystem=None):
        captured["hit_point"] = hit_point

    with patch.object(combat, "apply_hit", spy):
        _advance_combat([src, target], dt=0.1,
                        host=host,
                        ship_instances={target: sentinel})

    assert "hit_point" in captured, "apply_hit was never called"
    p = captured["hit_point"]
    assert p.x == pytest.approx(_CapturingHost.SURFACE_POINT[0])
    assert p.y == pytest.approx(_CapturingHost.SURFACE_POINT[1])
    assert p.z == pytest.approx(_CapturingHost.SURFACE_POINT[2])
