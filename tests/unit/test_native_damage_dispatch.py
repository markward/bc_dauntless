"""Which caller the native hit and condition chain stand in for, and when
they hand back to the Python reference (native damage Task 3; spec
2026-11-02-native-damage §3 goal 4).

With the switch on, combat.apply_hit, DamageableObject.DamageSystem and
ShipSubsystem._set_condition run the native chain (damage.h) unless a
function or class it stands in for was replaced, an instance attribute
shadows one, or an input cannot be named natively; then the reference runs,
and a fallback leaves nothing changed. With the switch off nothing native
runs. The bit-exact comparison is
tests/integration/test_native_damage_differential.py.
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import combat
from engine.appc import effect_queue as eq
from engine.appc import native_combat as nc
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (HullSubsystem, SensorSubsystem,
                                    ShieldSubsystem, ShipSubsystem)

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_apply_hit"),
    reason="native damage bindings not built")

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture(autouse=True)
def _clean():
    nc.reset()
    eq.reset()
    yield
    nc.reset()
    eq.reset()


def _ship():
    ship = ShipClass_Create("Dispatch")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(500.0)
    ship.SetHull(hull)
    sensor = SensorSubsystem("Sensors")
    sensor.SetMaxCondition(100.0)
    sensor.SetRadius(0.5)
    sensor._position = TGPoint3(0.0, 1.0, 0.0)
    ship.SetSensorSubsystem(sensor)
    shields = ShieldSubsystem("Shield Generator")
    shields.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetMaxShields(f, 100.0)
    ship.SetShieldSubsystem(shields)
    ship._radius = 3.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


def _hit(ship, damage=50.0):
    combat.apply_hit(ship, damage, TGPoint3(0.0, 1.0, 0.0), None,
                     bypass_shields=True)


def test_off_nothing_native_runs():
    ship = _ship()
    _hit(ship)
    ship.GetSensorSubsystem().SetCondition(10.0)
    ship.DamageSystem(ship.GetHull(), 5.0)
    assert nc.damage_counts() == dict.fromkeys(nc.damage_counts(), 0)
    assert ship.GetHull().GetCondition() == 445.0


def test_on_every_entry_point_runs_native():
    ship = _ship()
    nc.configure(ON)
    _hit(ship)
    ship.GetSensorSubsystem().SetCondition(10.0)
    ship.DamageSystem(ship.GetHull(), 5.0)
    ship.GetSensorSubsystem().SetConditionPercentage(0.5)
    assert nc.damage_counts() == {"hits": 1, "conditions": 2,
                                  "damage_systems": 1, "fallbacks": 0}
    assert ship.GetHull().GetCondition() == 445.0
    assert ship.GetSensorSubsystem().GetCondition() == 50.0


def test_a_patched_function_runs_the_reference(monkeypatch):
    ship = _ship()
    nc.configure(ON)
    seen = []
    weight = combat._splash_weight

    def spy(*a):
        seen.append(a)
        return weight(*a)
    monkeypatch.setattr(combat, "_splash_weight", spy)
    _hit(ship)
    assert seen and nc.damage_counts()["hits"] == 0
    assert nc.damage_counts()["fallbacks"] >= 1


def test_a_patched_stock_method_runs_the_reference(monkeypatch):
    sensor = _ship().GetSensorSubsystem()
    nc.configure(ON)
    calls = []
    orig = ShipSubsystem.GetMaxCondition

    def spy(self):
        calls.append(self)
        return orig(self)
    monkeypatch.setattr(ShipSubsystem, "GetMaxCondition", spy)
    sensor.SetCondition(20.0)
    assert calls and nc.damage_counts()["conditions"] == 0


def test_an_instance_patch_runs_the_reference():
    ship = _ship()
    nc.configure(ON)
    got = []
    ship.DamageSystem = lambda sub, amt, src=None: got.append(amt)
    _hit(ship, 40.0)
    assert got == [40.0, 40.0]          # the hull, then the sensors
    assert nc.damage_counts()["hits"] == 0


@pytest.mark.parametrize("where", ("sensors", "hull", "shields"))
def test_an_instance_patch_on_a_reachable_subsystem_runs_the_reference(
        where):
    """Override-guard gap 1 (native damage Task 4): an instance attribute
    shadowing a method the hit stands in for, on a subsystem the hit can
    reach -- an overlapped one, the hull, the shield generator -- is obeyed:
    the hit is the reference's, which calls it."""
    ship = _ship()
    nc.configure(ON)
    sub = {"sensors": ship.GetSensorSubsystem(), "hull": ship.GetHull(),
           "shields": ship.GetShields()}[where]
    got = []
    stock = type(sub).IsDestroyed

    def patched(_s=sub):
        got.append(_s.GetName())
        return stock(_s)
    sub.IsDestroyed = patched
    # Through the shields for their generator; past them for the others.
    bypass = where != "shields"
    combat.apply_hit(ship, 50.0, TGPoint3(0.0, 1.0, 0.0), None,
                     bypass_shields=bypass)
    # (The reference's own DamageSystem / SetCondition calls on the
    # patched subsystem hand back too: more than one fallback.)
    assert nc.damage_counts()["hits"] == 0
    assert nc.damage_counts()["fallbacks"] >= 1
    assert got, where
    del sub.IsDestroyed
    combat.apply_hit(ship, 50.0, TGPoint3(0.0, 1.0, 0.0), None,
                     bypass_shields=bypass)
    assert nc.damage_counts()["hits"] == 1


def test_a_foreign_subsystem_class_runs_the_reference():
    class Odd(ShipSubsystem):
        def GetConditionPercentage(self):
            return 0.25
    odd = Odd("odd")
    odd.SetMaxCondition(100.0)
    nc.configure(ON)
    odd.GetConditionWatcher()
    odd.SetCondition(80.0)
    assert odd.GetConditionWatcher()._value == 0.25     # Odd's own reading
    assert nc.damage_counts()["conditions"] == 0
    assert nc.damage_counts()["fallbacks"] == 1


def test_a_foreign_watcher_runs_the_reference():
    class Loud(FloatRangeWatcher):
        pass
    sensor = _ship().GetSensorSubsystem()
    nc.configure(ON)
    sensor._condition_watcher = Loud(1.0)
    sensor.SetCondition(30.0)
    assert sensor._condition_watcher._value == 0.3
    assert nc.damage_counts()["conditions"] == 0


def test_a_fallback_changes_nothing_natively(monkeypatch):
    """A native call that hands back part-way (here the hull is written,
    then the walk meets a subsystem the mirror cannot name) leaves the
    mirror and the queue as they were: the reference then does the hit
    once, and the audit agrees."""
    ship = _ship()
    nc.configure(ON)
    _h.combat_set_mount_order(ship.__dict__["_nslot"],
                              [nc.REF_UNREPRESENTABLE])
    _hit(ship, 30.0)
    # The reference's own DamageSystem calls (hull, sensors) run natively.
    assert nc.damage_counts() == {"hits": 0, "conditions": 0,
                                  "damage_systems": 2, "fallbacks": 1}
    assert ship.GetHull().GetCondition() == 470.0       # once, by Python
    eq.boundary()
    nc.push_mount_order(ship)
    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_no_hit_point_runs_the_reference():
    ship = _ship()
    nc.configure(ON)
    with pytest.raises(AttributeError):     # the reference's own error
        combat.apply_hit(ship, 10.0, None, None, bypass_shields=True)
    assert nc.damage_counts()["hits"] == 0


def test_the_instances_map_is_set_for_the_delivery(monkeypatch):
    """Ruling R13: the native caller sets the map HIT_PRESENT's delivery
    presents with."""
    from engine.appc import hit_feedback
    ship = _ship()
    nc.configure(ON)
    instances = {ship: 7}
    got = []
    monkeypatch.setattr(hit_feedback, "present",
                        lambda **kw: got.append(kw["ship_instances"]))
    combat.apply_hit(ship, 10.0, TGPoint3(0.0, 1.0, 0.0), None,
                     ship_instances=instances, bypass_shields=True)
    hit_feedback.use_instances(None)
    eq.boundary()
    assert nc.damage_counts()["hits"] == 1
    assert got == [None]                # the map in force AT delivery...
    combat.apply_hit(ship, 10.0, TGPoint3(0.0, 1.0, 0.0), None,
                     ship_instances=instances, bypass_shields=True)
    eq.boundary()
    assert got[-1] is instances         # ...which the native hit set
