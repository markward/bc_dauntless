"""Regression: projectiles.update_all unpacks _resolve_hit_point's
(point, normal) return shape — previously it stored the whole tuple
as hit_point and crashed downstream in pick_target_subsystem.
"""
import pytest
from engine.appc.math import TGPoint3
from engine.appc.projectiles import Torpedo, register, update_all, _active


@pytest.fixture(autouse=True)
def clear_registry():
    _active.clear()
    yield
    _active.clear()


def _torp_at(x, y, z, vx, vy, vz, ttl=30.0, age=0.0, src=None):
    t = Torpedo()
    t._position = TGPoint3(x, y, z)
    t._velocity = TGPoint3(vx, vy, vz)
    t._ttl = ttl
    t._age = age
    t._source_ship = src
    t._damage = 100.0
    register(t)
    return t


class _FakeShip:
    def __init__(self, x, y, z, radius=10.0, dead=False):
        self._loc = TGPoint3(x, y, z)
        self._r = radius
        self._dead = dead
        self._hull = None
        self._children = []
        self._shields = None

    def GetWorldLocation(self): return self._loc
    def GetRadius(self): return self._r
    def IsDead(self): return 1 if self._dead else 0
    def GetHull(self): return self._hull
    def GetShields(self): return self._shields
    def GetNumChildSubsystems(self): return len(self._children)
    def GetChildSubsystem(self, i): return self._children[i]


def test_update_all_hit_point_is_tgpoint_not_tuple():
    """Regression for Task 2's missed projectiles.py call site.

    When _resolve_hit_point changed to return (point, normal), the
    projectiles.update_all call at line 154 was not updated to unpack.
    This caused pick_target_subsystem to receive a tuple instead of
    TGPoint3, crashing on ".x" attribute access.
    """
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    t = _torp_at(0, 0, 0, 10, 0, 0, src=src)

    hits = update_all(dt=0.1, all_ships=[src, target])

    assert len(hits) == 1
    _torpedo, ship, _subsystem, hit_point = hits[0]
    assert ship is target
    assert hasattr(hit_point, "x"), \
        f"hit_point must be a TGPoint3, got {type(hit_point).__name__}"
    assert isinstance(hit_point.x, float), \
        f"hit_point.x must be float, got {type(hit_point.x).__name__}"
