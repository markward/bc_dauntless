"""SetupProperties copies a powered subsystem's hardpoint radius onto the
subsystem.

Regression: the sensor/shield radius was left at the 0.0 default (the shared
_copy_powered_subsystem_fields copied condition/power/targetable but not
radius), so `GetRadius()` returned 0 and the SPV drew no volume sphere for them
even though the hardpoint sets one (Galaxy Sensor Array = 0.28).
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import SensorProperty, ShieldProperty


def test_sensor_radius_copied_from_property():
    ship = ShipClass_Create("Galaxy")
    sp = SensorProperty("Sensor Array")
    sp.SetRadius(0.28)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()
    sens = ship.GetSensorSubsystem()
    assert sens is not None
    assert sens.GetRadius() == 0.28


def test_shield_radius_copied_from_property():
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    sp.SetRadius(0.6)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()
    sh = ship.GetShieldSubsystem()
    assert sh is not None
    assert sh.GetRadius() == 0.6
