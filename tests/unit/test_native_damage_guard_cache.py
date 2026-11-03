"""The native damage path's cached override guards (native damage perf fix;
spec 2026-11-02-native-damage §4.2, Task 3's report concern 4, Task 4's
concern 1).

The guards the native hit and condition chain run at every call -- every
function and stock-class method they stand in for is the one snapshotted
(_dmg_unchanged), and the kernels' own (_kdmg_unchanged) -- are answered
from the binding's cache while nothing they read has changed: each watched
module's dict at the same ma_version_tag (or, when it moved, every watched
name still bound to the same object) and each watched class at the same
tp_version_tag. A patch made AFTER the cache was filled must still be
obeyed at the next call: each test here fills the cache with a first call,
patches, and checks the next call hands back to the reference.
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
from engine.appc.subsystems import HullSubsystem, SensorSubsystem, ShipSubsystem

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


def _sensor():
    ship = ShipClass_Create("GuardCache")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(500.0)
    ship.SetHull(hull)
    sensor = SensorSubsystem("Sensors")
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


def test_the_guard_is_computed_once_while_nothing_changes():
    _ship, sensor = _sensor()
    for v in (90.0, 80.0, 70.0):
        assert _native_write(sensor, v)
    assert nc.damage_guard_counts()["dmg"] == 1


def test_an_unrelated_global_rebound_keeps_the_cache():
    """A watched module's dict moves (its version changes) when any global
    in it is rebound: the names the guard reads are still the same objects,
    so the answer stands and nothing is recomputed."""
    _ship, sensor = _sensor()
    assert _native_write(sensor, 90.0)
    combat._guard_cache_probe = object()
    try:
        assert _native_write(sensor, 80.0)
    finally:
        del combat._guard_cache_probe
    assert _native_write(sensor, 70.0)
    assert nc.damage_guard_counts()["dmg"] == 1


def test_a_module_function_patched_after_the_first_call_is_obeyed(
        monkeypatch):
    _ship, sensor = _sensor()
    assert _native_write(sensor, 90.0)
    monkeypatch.setattr(combat, "_splash_weight",
                        lambda *a: combat._splash_weight(*a))
    assert not _native_write(sensor, 80.0)
    assert sensor.GetCondition() == 80.0            # the reference did it
    monkeypatch.undo()
    assert _native_write(sensor, 70.0)              # restored: native again


def test_a_stock_method_patched_after_the_first_call_is_obeyed(monkeypatch):
    _ship, sensor = _sensor()
    assert _native_write(sensor, 90.0)
    calls = []
    orig = ShipSubsystem.GetMaxCondition

    def spy(self):
        calls.append(self)
        return orig(self)
    monkeypatch.setattr(ShipSubsystem, "GetMaxCondition", spy)
    assert not _native_write(sensor, 80.0)
    assert calls
    monkeypatch.undo()
    assert _native_write(sensor, 70.0)


def test_a_watcher_method_patched_after_the_first_call_is_obeyed(
        monkeypatch):
    _ship, sensor = _sensor()
    sensor.GetConditionWatcher()
    assert _native_write(sensor, 90.0)
    monkeypatch.setattr(FloatRangeWatcher, "_update_queued",
                        lambda self, *a, **k: None)
    assert not _native_write(sensor, 80.0)


def test_the_kernels_guard_is_cached_and_obeys_a_later_patch(monkeypatch):
    _sensor()
    assert nc._kdmg_ctx("phaser", None, [])["ok"]
    assert nc._kdmg_ctx("phaser", None, [])["ok"]
    assert nc.damage_guard_counts()["kdmg"] == 1
    monkeypatch.setattr(host_loop, "_phaser_damage_for_tick",
                        lambda *a: 0.0)
    assert not nc._kdmg_ctx("phaser", None, [])["ok"]
    monkeypatch.undo()
    assert nc._kdmg_ctx("phaser", None, [])["ok"]


def test_the_kernels_class_guard_obeys_a_later_patch(monkeypatch):
    _sensor()
    assert nc._kdmg_ctx("torpedo", None, [])["ok"]
    monkeypatch.setattr(Torpedo, "GetDamageRadiusFactor",
                        lambda self: 1.0)
    assert not nc._kdmg_ctx("torpedo", None, [])["ok"]


def test_a_class_first_flagged_after_the_fill_is_watched(monkeypatch):
    """The guard watches every class rows have been flagged with (final
    review I-1), including one first flagged after the cache was filled."""
    _ship, sensor = _sensor()
    assert _native_write(sensor, 90.0)              # fills the cache

    class LateSensor(SensorSubsystem):
        pass
    other = ShipClass_Create("GuardCacheLate")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(500.0)
    other.SetHull(hull)
    late = LateSensor("Sensors")
    late.SetMaxCondition(100.0)
    other.SetSensorSubsystem(late)
    assert _native_write(late, 90.0)
    monkeypatch.setattr(LateSensor, "IsDisabled", lambda self: 1)
    assert not _native_write(late, 80.0)
    assert _native_write(sensor, 70.0) is False     # one guard for all
    monkeypatch.undo()
    assert _native_write(late, 70.0)
