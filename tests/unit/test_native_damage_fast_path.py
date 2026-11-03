"""The native condition write and DamageSystem's one-call path (native
damage perf fix; host_bindings THE FAST DAMAGE ENTRIES).

set_condition and damage_system run their whole common case in one raw
binding call, under ONE reused applier context (native_combat._dmg_context)
instead of a fresh _K1Walk's per call. These pin what that must keep: the
caller's own applier context is back in place after the call, the reused
context holds nothing alive between calls (its pins are emptied), and a
call made while the reused context is already installed (an enclosing
native call) runs with a context of its own, leaving the enclosing one's
pins as they were.
"""
import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import effect_queue as eq
from engine.appc import native_combat as nc
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, SensorSubsystem

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


def _ship(name="FastPath"):
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(500.0)
    ship.SetHull(hull)
    sensor = SensorSubsystem("Sensors")
    sensor.SetMaxCondition(100.0)
    ship.SetSensorSubsystem(sensor)
    return ship, sensor


def test_a_native_write_restores_the_callers_applier_context():
    ship, sensor = _ship()
    nc.configure(ON)
    outer = nc._applier_context(nc._K1Walk())
    prev = _h.combat_set_applier(outer)
    try:
        sensor.SetCondition(40.0)
        ship.DamageSystem(sensor, 5.0)
    finally:
        back = _h.combat_set_applier(prev)
    assert back is outer
    assert nc.damage_counts() == {"hits": 0, "conditions": 1,
                                  "damage_systems": 1, "fallbacks": 0}
    assert sensor.GetCondition() == 35.0


def test_a_native_write_keeps_nothing_alive():
    """The applier pins every object it resolves for the call's writes;
    the reused context's pins are emptied after each call, as a fresh
    walk's were dropped."""
    ship, sensor = _ship()
    nc.configure(ON)
    sensor.SetCondition(40.0)
    ship.DamageSystem(ship.GetHull(), 5.0)
    assert nc.damage_counts() == {"hits": 0, "conditions": 1,
                                  "damage_systems": 1, "fallbacks": 0}
    assert nc._dmg_context()[0] == {}


def test_a_call_inside_the_reused_context_runs_with_its_own():
    ship, sensor = _ship()
    nc.configure(ON)
    ctx = nc._dmg_context()
    ctx[0][12345] = ship                 # an enclosing call's pin
    prev = _h.combat_set_applier(ctx)
    try:
        sensor.SetCondition(30.0)
        ship.DamageSystem(sensor, 5.0)
    finally:
        back = _h.combat_set_applier(prev)
    assert back is ctx
    assert ctx[0] == {12345: ship}
    ctx[0].clear()
    assert nc.damage_counts() == {"hits": 0, "conditions": 1,
                                  "damage_systems": 1, "fallbacks": 0}
    assert sensor.GetCondition() == 25.0


def test_the_reused_context_follows_a_replaced_quiet_setter(monkeypatch):
    """_applier_context's kinds follow `_quiet_setter` (a test's tracing
    wrapper replaces it); the reused context is rebuilt when it does, so
    the next native write's apply asks the new one, as a fresh context
    per call did."""
    ship, sensor = _ship()
    nc.configure(ON)
    sensor.SetCondition(40.0)                 # the context is made
    asked = []
    quiet = nc._quiet_setter

    def tracing(cls, name):
        asked.append(name)
        return quiet(cls, name)
    monkeypatch.setattr(nc, "_quiet_setter", tracing)
    sensor.SetCondition(30.0)
    assert "_condition" in asked
    assert nc.damage_counts()["conditions"] == 2
    assert sensor.GetCondition() == 30.0
