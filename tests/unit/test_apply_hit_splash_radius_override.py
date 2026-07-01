"""apply_hit(splash_radius=...) overrides the resolved R_hit.

A subsystem placed beyond the default phaser radius (0.15 GU) but inside an
explicit 1.3 GU override must be damaged only when the override is supplied.
"""
from engine.appc.combat import apply_hit
from engine.appc.math import TGMatrix3, TGPoint3
import App


class _FakeSub:
    def __init__(self, name, pos, radius, max_condition=1000.0):
        self.name = name
        self._pos = pos
        self._radius = radius
        self._max = max_condition
        self._condition = max_condition

    def GetPosition(self):     return self._pos
    def GetRadius(self):       return self._radius
    def GetCondition(self):    return self._condition
    def GetMaxCondition(self): return self._max
    def IsDamaged(self):       return self._condition < self._max
    def IsDisabled(self):      return False
    def IsDestroyed(self):     return False


class _FakeHull(_FakeSub):
    pass


class _FakeShip(App.TGEventHandlerObject):
    def __init__(self, hull, subsystems):
        super().__init__()
        self._hull = hull
        self._subs = list(subsystems)
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()
        self.damage_log = []

    def GetHull(self):          return self._hull
    def GetSubsystems(self):    return list(self._subs)
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetShields(self):       return None

    def DamageSystem(self, sub, amount, source=None):
        self.damage_log.append((sub.name, amount))
        sub._condition = max(0.0, sub._condition - amount)


def _names(ship):
    return [n for n, _ in ship.damage_log]


def test_default_radius_does_not_reach_distant_subsystem():
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    far = _FakeSub("Far", TGPoint3(0.5, 0, 0), radius=0.1)
    ship = _FakeShip(hull=hull, subsystems=[hull, far])
    apply_hit(ship, 100.0, TGPoint3(0, 0, 0), source=None, normal=None)
    assert "Far" not in _names(ship)


def test_override_radius_reaches_distant_subsystem():
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    far = _FakeSub("Far", TGPoint3(0.5, 0, 0), radius=0.1)
    ship = _FakeShip(hull=hull, subsystems=[hull, far])
    apply_hit(ship, 100.0, TGPoint3(0, 0, 0), source=None, normal=None,
              splash_radius=1.3)
    assert "Far" in _names(ship)
    # weight = (0.1 + 1.3 - 0.5) / 1.3 = 0.9/1.3 ≈ 0.6923
    far_amount = next(a for n, a in ship.damage_log if n == "Far")
    assert abs(far_amount - 100.0 * (0.9 / 1.3)) < 1e-6
