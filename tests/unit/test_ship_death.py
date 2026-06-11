# tests/unit/test_ship_death.py
"""Unit tests for the ship death sequence (engine/appc/ship_death.py)."""
import pytest

from engine.appc import ship_death


class FakeSet:
    """Minimal SetClass stand-in recording removals by name."""
    def __init__(self):
        self.removed = []
    def RemoveObjectFromSet(self, name):
        self.removed.append(name)


class FakeShip:
    """Minimal ship: lifecycle flags + name + containing set + radius."""
    def __init__(self, name="Enemy1", containing_set=None, radius=1.0):
        self._name = name
        self._set = containing_set if containing_set is not None else FakeSet()
        self._radius = radius
        self._dying = False
        self._dead = False
    def GetName(self):           return self._name
    def GetContainingSet(self):  return self._set
    def GetRadius(self):         return self._radius
    def IsDying(self):           return 1 if self._dying else 0
    def IsDead(self):            return 1 if self._dead else 0
    def SetDying(self, v):       self._dying = bool(v)
    def SetDead(self, v=True):   self._dead = bool(v) if v is not True else True


@pytest.fixture(autouse=True)
def _clean_registry():
    ship_death.reset()
    yield
    ship_death.reset()


def test_begin_marks_ship_dying():
    ship = FakeShip()
    ship_death.begin(ship)
    assert ship.IsDying() == 1
    assert ship.IsDead() == 0


def test_begin_is_idempotent():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.begin(ship)  # second call must not double-register
    # Advance just short of the throes window: still exactly one entry, alive.
    ship_death.advance(ship_death.THROES_DURATION - 0.01)
    assert ship.IsDead() == 0


def test_advance_transitions_to_dead_and_removes_after_throes():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)  # timer expires
    assert ship.IsDead() == 1
    assert s.removed == ["Doomed"]


def test_advance_does_not_kill_before_throes_elapse():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION / 2.0)
    assert ship.IsDead() == 0
    assert ship.IsDying() == 1


def test_entry_pruned_after_death():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)
    # A second advance after death must be a no-op (entry pruned, no re-removal).
    ship._set.removed.clear()
    ship_death.advance(1.0)
    assert ship._set.removed == []


def test_reset_clears_registry():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.reset()
    ship_death.advance(ship_death.THROES_DURATION)
    assert ship.IsDead() == 0  # nothing ticked


def test_out_of_action_predicate():
    ship = FakeShip()
    assert ship_death._out_of_action(ship) is False
    ship.SetDying(True)
    assert ship_death._out_of_action(ship) is True
    ship.SetDying(False)
    ship.SetDead(True)
    assert ship_death._out_of_action(ship) is True


def test_begin_ignores_none():
    ship_death.begin(None)  # must not raise
    ship_death.advance(ship_death.THROES_DURATION)  # registry stayed empty


def test_advance_prunes_ship_with_no_set():
    ship = FakeShip()
    ship._set = None  # GetContainingSet() -> None
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)  # must not raise
    assert ship.IsDead() == 1


# --- Task 2: critical-flag trigger via DamageSystem -------------------------
from engine.appc.objects import DamageableObject


class FakeSub:
    """Subsystem with condition + critical flag (mirrors ShipSubsystem)."""
    def __init__(self, max_condition=100.0, critical=0):
        self._cond = float(max_condition)
        self._max = float(max_condition)
        self._critical = int(critical)
        self._destroyed = False
    def GetCondition(self):      return self._cond
    def SetCondition(self, v):   self._cond = max(0.0, float(v))
    def GetMaxCondition(self):   return self._max
    def IsCritical(self):        return self._critical
    def SetDestroyed(self, v):   self._destroyed = bool(v)
    def IsDestroyed(self):       return 1 if self._destroyed else 0


class FakeDamageable(DamageableObject):
    """DamageableObject with a hull + lifecycle flags, for trigger tests."""
    def __init__(self):
        super().__init__()
        self._hull = FakeSub(critical=1)
        self._dying = False
        self._dead = False
        self._name = "Subject"
        self._set = FakeSet()
    def GetHull(self):           return self._hull
    def GetName(self):           return self._name
    def GetContainingSet(self):  return self._set
    def GetRadius(self):         return 1.0
    def IsDying(self):           return 1 if self._dying else 0
    def IsDead(self):            return 1 if self._dead else 0
    def SetDying(self, v):       self._dying = bool(v)
    def SetDead(self, v=True):   self._dead = bool(v) if v is not True else True


def test_damaging_critical_subsystem_to_zero_triggers_death():
    obj = FakeDamageable()
    obj.DamageSystem(obj.GetHull(), 100.0)  # hull is critical
    assert obj.IsDying() == 1


def test_damaging_noncritical_subsystem_to_zero_does_not_trigger_death():
    obj = FakeDamageable()
    sensors = FakeSub(critical=0)
    obj.DamageSystem(sensors, 100.0)
    assert sensors.GetCondition() == 0.0
    assert obj.IsDying() == 0


def test_warp_core_critical_triggers_death():
    obj = FakeDamageable()
    warp_core = FakeSub(critical=1)
    obj.DamageSystem(warp_core, 100.0)
    assert obj.IsDying() == 1


def test_partial_damage_does_not_trigger_death():
    obj = FakeDamageable()
    obj.DamageSystem(obj.GetHull(), 40.0)  # hull still at 60
    assert obj.IsDying() == 0


def test_killing_blow_on_dying_ship_is_no_op():
    """A second killing blow through DamageSystem on an already-dying ship
    must not re-trigger begin (the IsDying guard prevents double-register)."""
    obj = FakeDamageable()
    obj.DamageSystem(obj.GetHull(), 100.0)  # first kill -> dying
    assert obj.IsDying() == 1
    obj.DamageSystem(obj.GetHull(), 100.0)  # second blow -> still just dying
    assert obj.IsDying() == 1
    assert len(ship_death._active) == 1


# --- Task 3: DestroySystem --------------------------------------------------
def test_destroy_system_on_critical_kills():
    obj = FakeDamageable()
    obj.DestroySystem(obj.GetHull())
    assert obj.GetHull().GetCondition() == 0.0
    assert obj.IsDying() == 1


def test_destroy_system_on_noncritical_zeroes_but_no_death():
    obj = FakeDamageable()
    sensors = FakeSub(critical=0)
    obj.DestroySystem(sensors)
    assert sensors.GetCondition() == 0.0
    assert sensors.IsDestroyed() == 1
    assert obj.IsDying() == 0


def test_destroy_system_none_is_noop():
    obj = FakeDamageable()
    obj.DestroySystem(None)  # must not raise
    assert obj.IsDying() == 0
