"""A major-rock fixture for the occlusion tests
(tests/unit/test_sensor_occlusion.py).

Builds a genus-asteroid ship the way tests/unit/test_rock_class.py::_make
does -- a ShipProperty carrying App.GENUS_ASTEROID plus a HullProperty
carrying the radius, run through SetupProperties, which (via
engine.appc.ships.ShipClass.SetupProperties ->
engine.rocks.rock.maybe_become_rock) switches the ship's __class__ to
RockClass. Sized so its SCALED radius (engine.rocks.rock.effective_radius,
never the raw GetRadius() a caller might reach for instead -- that ignores
SetScale) comes out to exactly radius_gu: effective_radius reads
rock.GetRadius() first, which SetupProperties never touches at ship
(ObjectClass) level, so it falls through to the Hull subsystem's radius --
the one the HullProperty below actually sets -- times GetScale() (left at
its 1.0 default here).
"""
import pytest

import App
from engine.appc import sensor_occlusion
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ShipProperty, HullProperty
from engine.rocks.rock import effective_radius


def make_major_rock(pSet, name, *, at=(0.0, 0.0, 0.0), radius_gu=3.0):
    """Build a RockClass in *pSet*, positioned at *at*, whose
    effective_radius is exactly *radius_gu*. Returns the rock."""
    ship = ShipClass_Create(name)
    ps = ship.GetPropertySet()
    sp = ShipProperty("Mass")
    sp.SetGenus(App.GENUS_ASTEROID)
    sp.SetMass(400.0)
    ps.AddToSet("Scene Root", sp)
    hp = HullProperty("Hull")
    hp.SetMaxCondition(2500.0)
    hp.SetCritical(1)
    hp.SetPrimary(1)
    hp.SetRadius(float(radius_gu))
    ps.AddToSet("Scene Root", hp)
    ship.SetupProperties()
    got = effective_radius(ship)
    assert got == float(radius_gu), (
        "make_major_rock(%r, radius_gu=%r) produced effective_radius %r -- "
        "construction is wrong, fix the helper, not the caller"
        % (name, radius_gu, got))
    ship.SetTranslateXYZ(*at)
    pSet.AddObjectToSet(ship, name)
    return ship


@pytest.fixture
def occlusion_enabled():
    """Occlusion ships default OFF (sensor_occlusion.DEFAULT_ENABLED) -- off
    until the sensor-model project finishes. Any test that uses
    make_major_rock to assert blocking must enable it explicitly, here or via
    an autouse wrapper in the test module; restores on exit (not reset_enabled
    directly -- tests/conftest.py's autouse reset already does that between
    tests, this fixture is for the body of a single test)."""
    sensor_occlusion.set_enabled(True)
    try:
        yield
    finally:
        sensor_occlusion.reset_enabled()
