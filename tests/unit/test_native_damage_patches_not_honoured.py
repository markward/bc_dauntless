"""The native damage path has no module- or class-patch guard (spec Part A,
phase 6 A3): a function or stock-class method the native hit and condition
chain stand in for, patched after a class was first seen, is NOT obeyed --
the native chain keeps doing the write. What stays is representability: the
class mirror flags taken at a class's first sight (a class defined with a
foreign override is DMG_PYTHON and handed back), an instance attribute
shadowing a stood-in method, and the kernels' observation seam: a spy on
combat.apply_hit (the golden fights' and dispatch tests' hit log) hands the
kernels' hits back.

Replaces test_native_damage_guard_cache.py (the cached guard is deleted);
the module-function, stock-method and patched-after-first-sight cases are in
test_native_damage_dispatch.py.
"""
import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import combat
from engine.appc import effect_queue as eq
from engine.appc import native_combat as nc
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.projectiles import Torpedo
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


def _sensor(cls=SensorSubsystem, name="NotHonoured"):
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(500.0)
    ship.SetHull(hull)
    sensor = cls("Sensors")
    sensor.SetMaxCondition(100.0)
    ship.SetSensorSubsystem(sensor)
    nc.configure(ON)
    return ship, sensor


def _native_write(sensor, value) -> bool:
    """SetCondition(value): True when the native chain did it."""
    before = nc.damage_counts()
    sensor.SetCondition(value)
    after = nc.damage_counts()
    return after["conditions"] == before["conditions"] + 1


def test_a_patched_watcher_method_is_not_honoured(monkeypatch):
    _ship, sensor = _sensor()
    sensor.GetConditionWatcher()
    assert _native_write(sensor, 90.0)
    monkeypatch.setattr(FloatRangeWatcher, "_update_queued",
                        lambda self, *a, **k: None)
    assert _native_write(sensor, 80.0)


def test_a_class_defined_with_a_foreign_override_is_handed_back():
    """Representability, kept: a class whose rules are not the stock ones
    at its first sight is flagged DMG_PYTHON, and its writes are Python's."""

    class OddSensor(SensorSubsystem):
        def IsDisabled(self):
            return SensorSubsystem.IsDisabled(self)
    _ship, odd = _sensor(OddSensor, "NotHonouredOdd")
    assert not _native_write(odd, 90.0)
    assert odd.GetCondition() == 90.0               # the reference did it


def test_the_kernels_context_ignores_patched_arithmetic(monkeypatch):
    _sensor()
    assert nc._kdmg_ctx("phaser", None, [])["ok"]
    monkeypatch.setattr(host_loop, "_phaser_damage_for_tick",
                        lambda *a: 0.0)
    assert nc._kdmg_ctx("phaser", None, [])["ok"]
    monkeypatch.setattr(Torpedo, "GetDamageRadiusFactor",
                        lambda self: 1.0)
    assert nc._kdmg_ctx("torpedo", None, [])["ok"]


def test_a_spy_on_apply_hit_hands_the_kernels_hits_back(monkeypatch):
    """The observation seam: a spy on combat.apply_hit makes the kernels'
    context not ok, so every pulse and hit goes through it."""
    _sensor()
    assert nc._kdmg_ctx("torpedo", None, [])["ok"]
    real = combat.apply_hit
    monkeypatch.setattr(combat, "apply_hit",
                        lambda *a, **k: real(*a, **k))
    assert not nc._kdmg_ctx("torpedo", None, [])["ok"]
    assert not nc._kdmg_ctx("phaser", None, [])["ok"]
    monkeypatch.undo()
    assert nc._kdmg_ctx("phaser", None, [])["ok"]
