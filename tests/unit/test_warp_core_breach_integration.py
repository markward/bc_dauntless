"""End-to-end: hull death -> 1.5s cascade -> warp core crosses 0 -> breach
damages a neighbour. Exercises objects.py routing + subsystem_cascade +
warp_core_breach together (Case B), with combat.apply_hit captured."""
import pytest

from engine.appc.objects import DamageableObject
from engine.appc import warp_core_breach, subsystem_cascade
from engine.appc.math import TGMatrix3, TGPoint3


class _Sub:
    def __init__(self, name, cond=100.0, critical=False, pos=None,
                 max_condition=None):
        self.name = name
        self._c = cond
        self._max = max_condition if max_condition is not None else cond
        self._crit = critical
        self._pos = pos or TGPoint3(0.0, 0.0, 0.0)
        self._destroyed = False

    def GetCondition(self):    return self._c
    def SetCondition(self, v): self._c = v
    def GetMaxCondition(self): return self._max
    def IsCritical(self):      return 1 if self._crit else 0
    def GetPosition(self):     return self._pos
    def SetDestroyed(self, v): self._destroyed = bool(v)
    def IsDestroyed(self):     return self._destroyed


class _Ship(DamageableObject):
    def __init__(self, name, loc, hull, power, others, radius=1.0):
        super().__init__()
        self._name = name
        self._loc = loc
        self._radius = radius
        self._hull = hull
        self._power = power
        self._others = list(others)

    def GetName(self):           return self._name
    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return TGMatrix3()
    def GetRadius(self):         return self._radius
    def GetHull(self):           return self._hull
    def GetPowerSubsystem(self): return self._power
    def GetSubsystems(self):     return [self._hull, self._power, *self._others]
    def IsDestroyBrokenSystems(self): return 1
    def IsDying(self):           return 0
    def IsDead(self):            return 0
    def SetDying(self, v):       pass


@pytest.fixture(autouse=True)
def _clean():
    warp_core_breach.reset()
    subsystem_cascade.reset()
    yield
    warp_core_breach.reset()
    subsystem_cascade.reset()


def test_hull_death_cascade_breach_damages_neighbour(monkeypatch):
    # Source ship at origin with a 5000-condition warp core; neighbour 0.5 away.
    src = _Ship("A", TGPoint3(0, 0, 0),
                hull=_Sub("Hull", cond=20.0, critical=True),
                power=_Sub("WarpCore", cond=100.0, critical=True,
                           max_condition=5000.0),
                others=[_Sub("Sensors", cond=100.0)])
    nbr = _Ship("B", TGPoint3(0.5, 0, 0),
                hull=_Sub("Hull", cond=9999.0, critical=True),
                power=_Sub("WarpCore", cond=9999.0, critical=True,
                           max_condition=5000.0),
                others=[], radius=0.5)

    import engine.appc.ship_iter as ship_iter
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: [src, nbr])

    import engine.appc.combat as combat
    hits = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, damage, hp, source, **kw: hits.append((ship, damage)))

    # Hull dies -> schedules the cascade (no breach yet).
    src.DamageSystem(src.GetHull(), 20.0)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY / 2.0)
    warp_core_breach.advance(0.0)
    assert hits == []   # cascade not yet fired

    # Past the 1.5s delay: cascade zeroes the warp core -> arms breach.
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    warp_core_breach.advance(0.0)

    targets = [h[0] for h in hits]
    assert nbr in targets and src not in targets
