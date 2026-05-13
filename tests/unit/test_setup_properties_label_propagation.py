"""SetupProperties copies the hardpoint name onto the live subsystem.

ShipClass_Create pre-allocates with canonical fallback names
('Tractor Beam System', 'Sensor Subsystem').  When the hardpoint
registers a WeaponSystemProperty('Tractors'), the targets panel must
show 'Tractors' not the fallback.
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    SensorProperty, ImpulseEngineProperty, WarpEngineProperty,
    HullProperty, ShieldProperty, WeaponSystemProperty,
    PowerProperty, RepairSubsystemProperty,
)


def test_sensor_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", SensorProperty("Sensor Array"))
    ship.SetupProperties()
    assert ship.GetSensorSubsystem().GetName() == "Sensor Array"


def test_impulse_label_copied_from_hardpoint():
    ship = ShipClass_Create("Galaxy")
    ship.GetPropertySet().AddToSet("Scene Root", ImpulseEngineProperty("Impulse Drive"))
    ship.SetupProperties()
    assert ship.GetImpulseEngineSubsystem().GetName() == "Impulse Drive"


def test_warp_label_copied_from_hardpoint():
    ship = ShipClass_Create("Galaxy")
    ship.GetPropertySet().AddToSet("Scene Root", WarpEngineProperty("Warp Nacelles"))
    ship.SetupProperties()
    assert ship.GetWarpEngineSubsystem().GetName() == "Warp Nacelles"


def test_shield_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", ShieldProperty("Shield Generator"))
    ship.SetupProperties()
    assert ship.GetShieldSubsystem().GetName() == "Shield Generator"


def test_tractor_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    p = WeaponSystemProperty("Tractors")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    assert ship.GetTractorBeamSystem().GetName() == "Tractors"


def test_phaser_label_copied_from_hardpoint():
    ship = ShipClass_Create("Galaxy")
    p = WeaponSystemProperty("Phasers")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    assert ship.GetPhaserSystem().GetName() == "Phasers"


def test_power_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", PowerProperty("Power Plant"))
    ship.SetupProperties()
    assert ship.GetPowerSubsystem().GetName() == "Power Plant"


def test_repair_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", RepairSubsystemProperty("Engineering"))
    ship.SetupProperties()
    assert ship.GetRepairSubsystem().GetName() == "Engineering"


def test_hull_label_copied_from_hardpoint():
    ship = ShipClass_Create("DryDock")
    ship.GetPropertySet().AddToSet("Scene Root", HullProperty("Primary Hull"))
    ship.SetupProperties()
    assert ship.GetHull().GetName() == "Primary Hull"


def test_empty_hardpoint_name_keeps_canonical_fallback():
    """A property with an empty name leaves the receiver's canonical
    fallback name alone (Phase 1 hardpoints always name; defensive)."""
    ship = ShipClass_Create("Galaxy")
    p = SensorProperty("")  # explicitly empty
    ship.GetPropertySet().AddToSet("Scene Root", p)
    ship.SetupProperties()
    # The canonical fallback 'Sensor Subsystem' from ShipClass_Create persists.
    assert ship.GetSensorSubsystem().GetName() == "Sensor Subsystem"
