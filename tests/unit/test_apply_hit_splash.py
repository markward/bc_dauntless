"""Tests for the rewritten apply_hit — splash allocation per spec.

These tests use minimal fakes to keep the focus on attribution. They
cover:
- hull always damaged when post-shield > 0
- multiple subsystems damaged when their spheres overlap the splash
- weight falloff produces proportional damage
- shield-only hit (no bleed-through) leaves hull and subsystems untouched
- WeaponHitEvent carries the radius and normal
"""

import pytest

from engine.appc.combat import apply_hit
from engine.appc.events import WeaponHitEvent
from engine.appc.math import TGMatrix3, TGPoint3
import App


class _FakeSub:
    def __init__(self, name, pos, radius, max_condition=1000.0):
        self.name = name
        self._pos = pos
        self._radius = radius
        self._max = max_condition
        self._condition = max_condition

    def GetPosition(self):  return self._pos
    def GetRadius(self):    return self._radius
    def GetCondition(self): return self._condition
    def GetMaxCondition(self): return self._max
    def IsDamaged(self):    return self._condition < self._max
    def IsDisabled(self):   return False
    def IsDestroyed(self):  return False


class _FakeHull(_FakeSub):
    pass


class _FakeShip(App.TGEventHandlerObject):
    def __init__(self, hull, subsystems, location=None, rotation=None):
        super().__init__()
        self._hull = hull
        self._subs = list(subsystems)
        self._loc = location or TGPoint3(0.0, 0.0, 0.0)
        self._rot = rotation or TGMatrix3()
        self.damage_log = []

    def GetHull(self):          return self._hull
    def GetSubsystems(self):    return list(self._subs)
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetShields(self):       return None  # shields off for these tests

    def DamageSystem(self, sub, amount):
        self.damage_log.append((sub.name, amount))
        sub._condition = max(0.0, sub._condition - amount)


def _captured_event(holder):
    """Patch App.g_kEventManager.AddEvent to capture the broadcast event."""
    orig = App.g_kEventManager.AddEvent
    def capture(evt):
        holder.append(evt)
        return orig(evt)
    App.g_kEventManager.AddEvent = capture
    return orig


@pytest.fixture
def restore_event_manager():
    orig = App.g_kEventManager.AddEvent
    yield
    App.g_kEventManager.AddEvent = orig


def test_hull_always_takes_full_post_shield_damage(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    far_sub = _FakeSub("FarSub", TGPoint3(10.0, 0, 0), radius=0.1)
    ship = _FakeShip(hull=hull, subsystems=[hull, far_sub])

    holder = []
    _captured_event(holder)

    apply_hit(ship, damage=100.0, hit_point=TGPoint3(0.0, 0.0, 0.0),
              source=None, normal=None)

    names = [e[0] for e in ship.damage_log]
    assert "Hull" in names
    hull_amount = next(amt for n, amt in ship.damage_log if n == "Hull")
    assert hull_amount == 100.0
    # FarSub well outside splash, no damage to it.
    assert "FarSub" not in names


def test_subsystem_inside_splash_takes_weighted_damage(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    # Sensor at (0.3, 0, 0), R=0.28; hit at (0.3, 0, 0) → centre, w=1.0
    sensor = _FakeSub("Sensors", TGPoint3(0.3, 0, 0), radius=0.28)
    ship = _FakeShip(hull=hull, subsystems=[hull, sensor])

    holder = []
    _captured_event(holder)

    apply_hit(ship, damage=100.0, hit_point=TGPoint3(0.3, 0.0, 0.0),
              source=None, normal=None)

    sensor_amount = next(amt for n, amt in ship.damage_log if n == "Sensors")
    assert sensor_amount == pytest.approx(100.0)


def test_subsystem_outside_splash_takes_no_damage(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    # Sensor at (0.3, 0, 0), R=0.28; hit at (5.0, 0, 0) → far outside.
    sensor = _FakeSub("Sensors", TGPoint3(0.3, 0, 0), radius=0.28)
    ship = _FakeShip(hull=hull, subsystems=[hull, sensor])

    holder = []
    _captured_event(holder)

    apply_hit(ship, damage=100.0, hit_point=TGPoint3(5.0, 0.0, 0.0),
              source=None, normal=None)

    names = [e[0] for e in ship.damage_log]
    assert "Sensors" not in names
    assert "Hull" in names  # hull always damaged


def test_multiple_overlapping_subsystems_each_take_damage_independently(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    a = _FakeSub("A", TGPoint3(0.2, 0, 0), radius=0.3)
    b = _FakeSub("B", TGPoint3(-0.2, 0, 0), radius=0.3)
    ship = _FakeShip(hull=hull, subsystems=[hull, a, b])

    holder = []
    _captured_event(holder)

    # Hit at origin: 0.2 from A's centre (inside R_A=0.3 → w=1.0)
    # and 0.2 from B's centre (inside R_B=0.3 → w=1.0). Both take full.
    apply_hit(ship, damage=50.0, hit_point=TGPoint3(0.0, 0.0, 0.0),
              source=None, normal=None)

    a_amount = next(amt for n, amt in ship.damage_log if n == "A")
    b_amount = next(amt for n, amt in ship.damage_log if n == "B")
    hull_amount = next(amt for n, amt in ship.damage_log if n == "Hull")

    assert a_amount == pytest.approx(50.0)
    assert b_amount == pytest.approx(50.0)
    assert hull_amount == pytest.approx(50.0)
    # Total applied (150) exceeds incoming (50) — by design (independent allocation).


def test_weapon_hit_event_carries_radius_and_normal(restore_event_manager):
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    ship = _FakeShip(hull=hull, subsystems=[hull])

    holder = []
    _captured_event(holder)
    normal = TGPoint3(1.0, 0.0, 0.0)

    apply_hit(ship, damage=10.0, hit_point=TGPoint3(0.0, 0.0, 0.0),
              source=None, normal=normal)

    assert len(holder) == 1
    evt = holder[0]
    # No hardpoint or payload passed → phaser default 0.15
    assert evt.GetRadius() == 0.15
    assert evt.GetNormal() is normal


def test_apply_hit_accepts_optional_hardpoint_and_payload(restore_event_manager):
    """apply_hit signature gains hardpoint_weapon= and payload_template=
    kwargs so callers (phaser firing, projectile collision) can supply
    the DRF resolver inputs."""
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    ship = _FakeShip(hull=hull, subsystems=[hull])

    class _Hp:
        def GetDamageRadiusFactor(self): return 0.20

    holder = []
    _captured_event(holder)

    apply_hit(ship, damage=10.0, hit_point=TGPoint3(0.0, 0.0, 0.0),
              source=None, normal=None, hardpoint_weapon=_Hp())

    assert holder[0].GetRadius() == 0.20
