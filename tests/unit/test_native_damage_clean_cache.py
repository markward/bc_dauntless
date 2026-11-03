"""combat_dmg_clean's object cache (native damage perf fix; Task 4's report
concern 1: the K2 pulse context scanned every target's subsystems' dicts
every step).

A target is clean when neither the ship nor any subsystem its hit can reach
(its mount order, hull and shield generator) has an instance attribute
shadowing a method the hit stands in for (override-guard gap 1). The scan
keeps each object's answer with what it was computed on -- its type, its
dict and the dict's ma_version_tag -- so an unchanged object is never
probed again, and any change to its dict (a write, a patch, a delete) makes
it probed at the next scan. Each test scans once to fill the cache, then
patches, and checks the next scan obeys.
"""
import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import effect_queue as eq
from engine.appc import native_combat as nc
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (HullSubsystem, SensorSubsystem,
                                    ShieldSubsystem)

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_dmg_clean"),
    reason="native damage bindings not built")

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture(autouse=True)
def _clean():
    nc.reset()
    eq.reset()
    yield
    nc.reset()
    eq.reset()


def _ship(name="CleanCache"):
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(500.0)
    ship.SetHull(hull)
    sensor = SensorSubsystem("Sensors")
    sensor.SetMaxCondition(100.0)
    ship.SetSensorSubsystem(sensor)
    shields = ShieldSubsystem("Shield Generator")
    shields.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetMaxShields(f, 100.0)
    ship.SetShieldSubsystem(shields)
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    nc.configure(ON)
    return ship


def _probed(fn):
    _h.combat_dmg_clean_reset_counts()
    out = fn()
    return out, _h.combat_dmg_clean_counts()["probed"]


def test_an_unchanged_ship_is_answered_from_the_cache():
    ship = _ship()
    assert nc._kdmg_clean([ship]) == [True]
    out, probed = _probed(lambda: nc._kdmg_clean([ship]))
    assert out == [True]
    assert probed == 0


def test_only_an_object_written_since_is_probed_again():
    ship = _ship()
    assert nc._kdmg_clean([ship]) == [True]
    ship.GetSensorSubsystem().SetCondition(50.0)   # its dict moves
    out, probed = _probed(lambda: nc._kdmg_clean([ship]))
    assert out == [True]
    assert probed == 1


@pytest.mark.parametrize("where", ("sensors", "hull", "shields"))
def test_a_subsystem_patch_made_after_the_scan_is_seen(where):
    ship = _ship()
    sub = {"sensors": ship.GetSensorSubsystem(), "hull": ship.GetHull(),
           "shields": ship.GetShields()}[where]
    assert nc._kdmg_clean([ship]) == [True]
    sub.IsDestroyed = lambda: False
    assert nc._kdmg_clean([ship]) == [False]
    del sub.IsDestroyed
    assert nc._kdmg_clean([ship]) == [True]


def test_a_ship_patch_made_after_the_scan_is_seen():
    ship = _ship()
    assert nc._kdmg_clean([ship]) == [True]
    ship.GetHull = lambda: None
    assert nc._kdmg_clean([ship]) == [False]
    del ship.GetHull
    assert nc._kdmg_clean([ship]) == [True]


def test_a_subsystem_unregistered_since_the_scan_is_not_clean():
    ship = _ship()
    assert nc._kdmg_clean([ship]) == [True]
    nc._drop(ship.GetSensorSubsystem())
    assert nc._kdmg_clean([ship]) == [False]


def test_by_handle_the_same_answers():
    """K2's pulse context scans its targets by handle
    (combat_dmg_clean_handles): the clean ones come back, in order."""
    a, b = _ship("A"), _ship("B")
    ha, hb = a.__dict__["_nslot"], b.__dict__["_nslot"]
    assert nc._kdmg_clean_handles([ha, hb]) == [ha, hb]
    b.GetShields().IsOn = lambda: True
    assert nc._kdmg_clean_handles([ha, hb]) == [ha]
    _h.combat_dmg_clean_reset_counts()
    assert nc._kdmg_clean_handles([ha]) == [ha]
    assert _h.combat_dmg_clean_counts()["probed"] == 0
    del b.GetShields().IsOn
    assert nc._kdmg_clean_handles([hb, ha]) == [hb, ha]
    assert nc._kdmg_clean_handles([]) == []
