"""Tests for the warp-core breach hull carve (engine/appc/core_breach_carve.py)."""
import pytest

from engine.appc import core_breach_carve
from engine.appc.math import TGMatrix3, TGPoint3


class _Core:
    def __init__(self, pos=None):
        self._pos = pos or TGPoint3(0.5, 0.0, 0.0)  # body offset from ship centre

    def GetPosition(self):
        return self._pos


class _Ship:
    def __init__(self, loc=None, radius=2.0, core="default"):
        self._loc = loc or TGPoint3(0.0, 0.0, 0.0)
        self._radius = radius
        self._core = _Core() if core == "default" else core
        self._rot = TGMatrix3()  # identity

    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return self._rot
    def GetRadius(self):         return self._radius
    def GetPowerSubsystem(self): return self._core


class _Host:
    def __init__(self):
        self.carves = []  # (iid, point, normal, radius, time)

    def hull_carve_add(self, iid, point, normal, radius, time):
        self.carves.append((iid, point, normal, radius, time))


@pytest.fixture(autouse=True)
def _clean():
    core_breach_carve.reset()
    yield
    core_breach_carve.reset()


def test_advance_emits_carve_at_core_with_growing_radius():
    ship = _Ship(radius=2.0)
    host = _Host()
    si = {ship: 7}
    core_breach_carve.schedule(ship)

    core_breach_carve.advance(0.15, host, si)
    core_breach_carve.advance(0.45, host, si)   # age now 0.6

    assert len(host.carves) == 2
    # Same instance id, centered at the core world position (ship at origin,
    # identity rotation, core body offset (0.5,0,0) -> world (0.5,0,0)).
    assert host.carves[0][0] == 7
    assert host.carves[0][1] == pytest.approx((0.5, 0.0, 0.0))
    # Radius strictly grows as it ages.
    assert host.carves[1][3] > host.carves[0][3]


def test_carve_normal_points_from_centre_through_core():
    ship = _Ship(radius=2.0)
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(0.1, host, {ship: 1})
    nx, ny, nz = host.carves[0][2]
    assert (round(nx, 5), round(ny, 5), round(nz, 5)) == (1.0, 0.0, 0.0)


def test_reaches_full_radius_then_drops():
    ship = _Ship(radius=2.0)
    host = _Host()
    si = {ship: 1}
    core_breach_carve.schedule(ship)

    core_breach_carve.advance(core_breach_carve.GROW_DURATION, host, si)  # t=1
    # Full radius = min(MAX_RADIUS_GU, 0.25 * 2.0) * easeOut(1.0) = 0.5
    assert host.carves[-1][3] == pytest.approx(0.5)

    n = len(host.carves)
    core_breach_carve.advance(1.0, host, si)   # entry dropped -> no new carve
    assert len(host.carves) == n


def test_radius_stays_within_safe_cap_for_a_capital_ship():
    # A Galaxy's bounding-sphere GetRadius() is ~4 GU; the carve must NOT scale
    # to several GU (the breach renderer degenerates into a flat patch when a
    # carve approaches the hull's smallest dimension). It must stay <= the cap.
    ship = _Ship(radius=4.0)
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(core_breach_carve.GROW_DURATION, host, {ship: 1})
    radius = host.carves[-1][3]
    assert radius <= core_breach_carve.MAX_RADIUS_GU
    # 0.25 * 4.0 = 1.0, under the 1.2 cap.
    assert radius == pytest.approx(1.0)


def test_radius_hard_capped_for_an_oversized_ship():
    ship = _Ship(radius=20.0)
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(core_breach_carve.GROW_DURATION, host, {ship: 1})
    # 0.25 * 20 = 5.0, clamped to MAX_RADIUS_GU.
    assert host.carves[-1][3] == pytest.approx(core_breach_carve.MAX_RADIUS_GU)


def test_no_instance_emits_nothing_and_drops():
    ship = _Ship()
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(0.1, host, {})   # ship not in ship_instances
    assert host.carves == []
    core_breach_carve.advance(0.1, host, {ship: 1})  # already dropped
    assert host.carves == []


def test_ship_without_core_is_not_scheduled():
    ship = _Ship(core=None)
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(0.1, host, {ship: 1})
    assert host.carves == []


def test_schedule_is_idempotent():
    ship = _Ship()
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(0.1, host, {ship: 1})
    assert len(host.carves) == 1   # one entry, one carve this tick


def test_reset_clears_registry():
    ship = _Ship()
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.reset()
    core_breach_carve.advance(0.1, host, {ship: 1})
    assert host.carves == []
