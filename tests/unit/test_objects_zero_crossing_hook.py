"""DamageSystem/DestroySystem route warp-core / hull zero-crossings to the
breach + cascade (engine/appc/objects.py)."""
import pytest

from engine.appc.objects import DamageableObject
from engine.appc import warp_core_breach, subsystem_cascade


class _Sub:
    def __init__(self, name, cond=100.0, critical=False, targetable=True):
        self.name = name
        self._c = cond
        self._max = cond
        self._crit = critical
        self._targetable = targetable
        self._destroyed = False

    def GetCondition(self):    return self._c
    def SetCondition(self, v): self._c = v
    def GetMaxCondition(self): return self._max
    def IsCritical(self):      return 1 if self._crit else 0
    def IsTargetable(self):    return 1 if self._targetable else 0
    def SetDestroyed(self, v): self._destroyed = bool(v)
    def IsDestroyed(self):     return self._destroyed


class _Ship(DamageableObject):
    def __init__(self, hull, power):
        super().__init__()
        self._hull = hull
        self._power = power

    def GetHull(self):           return self._hull
    def GetPowerSubsystem(self): return self._power
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


def _spy(monkeypatch):
    armed, scheduled = [], []
    monkeypatch.setattr(warp_core_breach, "arm", lambda s: armed.append(s))
    monkeypatch.setattr(subsystem_cascade, "schedule", lambda s: scheduled.append(s))
    return armed, scheduled


def test_warp_core_to_zero_arms_breach(monkeypatch):
    armed, scheduled = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("WarpCore", cond=50.0, critical=False)
    ship = _Ship(hull, power)
    ship.DamageSystem(power, 50.0)   # 50 -> 0, crosses
    assert ship is armed[0]
    assert scheduled == []


def test_warp_core_already_zero_does_not_rearm(monkeypatch):
    armed, _ = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("WarpCore", cond=0.0)
    ship = _Ship(hull, power)
    ship.DamageSystem(power, 10.0)   # 0 -> 0, no crossing
    assert armed == []


def test_hull_to_zero_schedules_cascade(monkeypatch):
    armed, scheduled = _spy(monkeypatch)
    hull = _Sub("Hull", cond=30.0)
    power = _Sub("WarpCore", cond=100.0)
    ship = _Ship(hull, power)
    ship.DamageSystem(hull, 30.0)    # 30 -> 0, crosses
    assert ship is scheduled[0]
    assert armed == []


def test_non_core_non_hull_subsystem_routes_nothing(monkeypatch):
    armed, scheduled = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("WarpCore", cond=100.0)
    sensors = _Sub("Sensors", cond=40.0)
    ship = _Ship(hull, power)
    ship.DamageSystem(sensors, 40.0)  # sensors -> 0, but neither core nor hull
    assert armed == [] and scheduled == []


def test_destroy_system_on_warp_core_arms_breach(monkeypatch):
    armed, _ = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("WarpCore", cond=100.0)
    ship = _Ship(hull, power)
    ship.DestroySystem(power)         # forced 100 -> 0, crosses
    assert ship is armed[0]


def test_non_targetable_power_plant_does_not_breach(monkeypatch):
    """An asteroid's hidden Power Plant (SetTargetable(0)) must not throw a
    warp-core explosion when the death cascade zeroes it."""
    armed, scheduled = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("Power Plant", cond=50.0, targetable=False)
    ship = _Ship(hull, power)
    ship.DamageSystem(power, 50.0)    # 50 -> 0, crosses, but not targetable
    assert armed == []
    assert scheduled == []


def test_non_targetable_power_plant_via_destroy_does_not_breach(monkeypatch):
    armed, _ = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("Power Plant", cond=100.0, targetable=False)
    ship = _Ship(hull, power)
    ship.DestroySystem(power)         # forced kill (cascade path), still no breach
    assert armed == []


# ── Cloned-model warp radius (ConditionInRange consumer) ────────────────────

def test_has_cloned_model_returns_zero():
    """ConditionInRange's warp branch gates GetClonedModelRadius behind
    HasClonedModel(); Dauntless has no cloned-model override yet, so it
    returns 0 and callers fall back to GetRadius()."""
    obj = DamageableObject()
    assert obj.HasClonedModel() == 0


def test_get_cloned_model_radius_equals_get_radius():
    """The placeholder GetClonedModelRadius mirrors GetRadius so a direct
    caller (ConditionInRange) gets a sane radius rather than an error."""
    obj = DamageableObject()
    obj.SetRadius(42.5)
    assert obj.GetClonedModelRadius() == obj.GetRadius() == 42.5
