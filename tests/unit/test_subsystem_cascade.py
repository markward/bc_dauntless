"""Tests for the hull-death subsystem cascade (engine/appc/subsystem_cascade.py)."""
import pytest

from engine.appc import subsystem_cascade


class _Sub:
    def __init__(self, name, cond=100.0):
        self.name = name
        self._c = cond
        self._destroyed = False

    def GetCondition(self):   return self._c
    def SetCondition(self, v): self._c = v
    def SetDestroyed(self, v): self._destroyed = bool(v)
    def IsDestroyed(self):     return self._destroyed


class _Ship:
    """Fake ship exposing the surface the cascade walks."""
    def __init__(self, hull, power, others, destroy_broken=True):
        self._hull = hull
        self._power = power
        self._others = list(others)
        self._destroy_broken = destroy_broken
        self.destroyed = []  # subsystems passed to DestroySystem, in order

    def GetHull(self):            return self._hull
    def GetPowerSubsystem(self):  return self._power
    def GetSubsystems(self):      return [self._hull, self._power, *self._others]
    def IsDestroyBrokenSystems(self): return 1 if self._destroy_broken else 0

    def DestroySystem(self, sub):
        self.destroyed.append(sub)
        sub.SetCondition(0.0)
        sub.SetDestroyed(True)


@pytest.fixture(autouse=True)
def _clean():
    subsystem_cascade.reset()
    yield
    subsystem_cascade.reset()


def _make_ship(**kw):
    hull = _Sub("Hull", cond=0.0)   # hull already dead when cascade is scheduled
    power = _Sub("WarpCore", cond=100.0)
    sensors = _Sub("Sensors", cond=100.0)
    return _Ship(hull, power, [sensors], **kw), hull, power, sensors


def test_schedule_then_advance_past_delay_zeroes_all_subsystems():
    ship, hull, power, sensors = _make_ship()
    subsystem_cascade.schedule(ship)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    destroyed = set(ship.destroyed)
    assert power in destroyed and sensors in destroyed and hull in destroyed
    assert power.GetCondition() == 0.0


def test_does_not_fire_before_delay():
    ship, _, power, _ = _make_ship()
    subsystem_cascade.schedule(ship)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY / 2.0)
    assert ship.destroyed == []
    assert power.GetCondition() == 100.0


def test_destroy_broken_systems_flag_off_suppresses_cascade():
    ship, _, power, _ = _make_ship(destroy_broken=False)
    subsystem_cascade.schedule(ship)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY * 2)
    assert ship.destroyed == []
    assert power.GetCondition() == 100.0


def test_schedule_is_idempotent():
    ship, _, power, _ = _make_ship()
    subsystem_cascade.schedule(ship)
    subsystem_cascade.schedule(ship)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    # Warp core destroyed exactly once despite the double schedule.
    assert ship.destroyed.count(power) == 1


def test_reset_clears_pending():
    ship, _, power, _ = _make_ship()
    subsystem_cascade.schedule(ship)
    subsystem_cascade.reset()
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    assert ship.destroyed == []
