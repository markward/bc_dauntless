"""End-to-end: a phaser hit on the Galaxy applies damage to the hull and
to any subsystem whose hardpoint position is within the splash sphere of
the impact point.

This is the production-fidelity proof of the splash attribution model.
Loads the real Galaxy ship via loadspacehelper, fires a synthesized
phaser hit at the world-space position of the Sensors subsystem, and
asserts both hull and sensors took damage.

No ``headless_app`` fixture exists in this project; tests own their
own App state via the standard ``_isolate`` pattern (App.SetClass_Create
+ explicit teardown).
"""
import sys

import pytest

import App
from engine.appc.combat import _subsystem_world_position, apply_hit
from engine.appc.math import TGPoint3


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()
    # Flush ships.Hardpoints.galaxy so the next test reloads cleanly.
    for k in list(sys.modules):
        if k == "ships" or k.startswith("ships."):
            del sys.modules[k]


@pytest.fixture
def galaxy_ship():
    """Construct a Galaxy via the real SDK helper, headless.

    Ship starts at GREEN alert with shields off (``_is_on = False``),
    so ``apply_hit`` delivers the full damage directly to hull and
    subsystems without any shield absorption.
    """
    import loadspacehelper
    pSet = App.SetClass_Create()
    pSet.SetName("splash_test")
    App.g_kSetManager._sets["splash_test"] = pSet
    ship = loadspacehelper.CreateShip("Galaxy", pSet, "Galaxy", None, 0, 0)
    assert ship is not None, "loadspacehelper.CreateShip returned None for Galaxy"
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    return ship


def _subsystem_named(ship, name):
    """Return the first subsystem whose GetName() == ``name``, or None."""
    for s in ship.GetSubsystems():
        if s is None:
            continue
        if hasattr(s, "GetName") and s.GetName() == name:
            return s
        for child in getattr(s, "_children", []) or []:
            if child is not None and hasattr(child, "GetName") and child.GetName() == name:
                return child
    return None


def test_phaser_at_sensor_array_damages_hull_and_sensors(galaxy_ship):
    """Impact at the Sensor Array world position damages hull AND sensors."""
    sensors = _subsystem_named(galaxy_ship, "Sensor Array")
    assert sensors is not None, (
        "Galaxy SDK should declare a Sensor Array subsystem; "
        "check sdk/Build/scripts/ships/Hardpoints/galaxy.py for the exact name"
    )

    hull = galaxy_ship.GetHull()
    hull_before = hull.GetCondition()
    sensors_before = sensors.GetCondition()

    # Fire at the sensors' world-space position; weight should be 1.0
    # (impact distance = 0 → _splash_weight clamps to 1.0).
    hit_point = _subsystem_world_position(galaxy_ship, sensors)

    apply_hit(galaxy_ship, damage=100.0, hit_point=hit_point,
              source=None, normal=TGPoint3(0.0, 1.0, 0.0))

    hull_after = hull.GetCondition()
    sensors_after = sensors.GetCondition()

    assert hull_after < hull_before, (
        "hull should always take damage on a bleed-through hit "
        f"(before={hull_before}, after={hull_after})"
    )
    assert sensors_after < sensors_before, (
        "sensors should take damage when impact is at its centre "
        f"(before={sensors_before}, after={sensors_after})"
    )
    # Hull takes the full 100 damage; sensors takes 100 * weight=1.0 = 100.
    assert pytest.approx(hull_before - hull_after, rel=0.01) == 100.0
    assert pytest.approx(sensors_before - sensors_after, rel=0.01) == 100.0


def test_phaser_far_from_any_subsystem_only_damages_hull(galaxy_ship):
    """Impact 1000 GU from ship origin misses all subsystems — only hull damaged."""
    hull = galaxy_ship.GetHull()
    hull_before = hull.GetCondition()

    # 1000 GU offset along world-X — far outside every subsystem catchment.
    # apply_hit doesn't validate that the point is on the hull; it trusts
    # the caller's impact point.
    hit_point = TGPoint3(1000.0, 0.0, 0.0)

    subsystem_conditions_before = {}
    for s in galaxy_ship.GetSubsystems():
        if s is None or s is hull:
            continue
        if hasattr(s, "GetCondition"):
            subsystem_conditions_before[id(s)] = s.GetCondition()

    apply_hit(galaxy_ship, damage=50.0, hit_point=hit_point,
              source=None, normal=None)

    assert hull.GetCondition() < hull_before, (
        "hull should take damage even on a far hit "
        f"(before={hull_before}, after={hull.GetCondition()})"
    )
    # No non-hull subsystem should have taken damage.
    for s in galaxy_ship.GetSubsystems():
        if s is None or s is hull:
            continue
        if hasattr(s, "GetCondition") and id(s) in subsystem_conditions_before:
            assert s.GetCondition() == subsystem_conditions_before[id(s)], (
                f"{getattr(s, 'GetName', lambda: '?')()} should not be damaged "
                "by a hit 1000 GU from the ship"
            )
