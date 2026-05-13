"""ShipClass exposes _power_subsystem and _repair_subsystem slots
with the same Get/Set + pre-allocation + Pass 3 scrub pattern as the
existing eight."""
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (
    PowerSubsystem, RepairSubsystem,
)


def test_ship_class_create_preallocates_power():
    ship = ShipClass_Create("blank")
    assert isinstance(ship.GetPowerSubsystem(), PowerSubsystem)
    assert ship.GetPowerSubsystem().GetName() == "Power Plant"


def test_ship_class_create_preallocates_repair():
    ship = ShipClass_Create("blank")
    assert isinstance(ship.GetRepairSubsystem(), RepairSubsystem)
    assert ship.GetRepairSubsystem().GetName() == "Engineering"


def test_set_get_power_round_trip():
    ship = ShipClass()
    p = PowerSubsystem("X")
    ship.SetPowerSubsystem(p)
    assert ship.GetPowerSubsystem() is p


def test_set_get_repair_round_trip():
    ship = ShipClass()
    r = RepairSubsystem("X")
    ship.SetRepairSubsystem(r)
    assert ship.GetRepairSubsystem() is r


def test_setup_properties_scrubs_power_when_no_property():
    """Pass 3 must clear _power_subsystem when no PowerProperty is in
    the property set (mirrors the existing scrub for sensor/impulse/etc)."""
    ship = ShipClass_Create("blank")
    ship.SetupProperties()  # empty property set
    assert ship.GetPowerSubsystem() is None
    assert ship.GetRepairSubsystem() is None
