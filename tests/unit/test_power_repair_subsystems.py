"""PowerSubsystem + RepairSubsystem — top-level subsystems missing from
the panel today because SetupProperties had no handler for their property
templates.  Inheritance matches SDK App.py:5710 (PowerSubsystem :
ShipSubsystem — not powered) and SDK App.py:6639 (RepairSubsystem :
PoweredSubsystem)."""
from engine.appc.subsystems import (
    ShipSubsystem, PoweredSubsystem, PowerSubsystem, RepairSubsystem,
)


def test_power_subsystem_inherits_ship_subsystem():
    p = PowerSubsystem("Power Plant")
    assert isinstance(p, ShipSubsystem)
    # NOT a PoweredSubsystem — it generates power rather than consuming it.
    assert not isinstance(p, PoweredSubsystem)
    assert p.GetName() == "Power Plant"


def test_repair_subsystem_inherits_powered_subsystem():
    r = RepairSubsystem("Engineering")
    assert isinstance(r, PoweredSubsystem)
    assert r.GetName() == "Engineering"


def test_power_subsystem_property_back_reference():
    from engine.appc.properties import PowerProperty
    p = PowerSubsystem("Power Plant")
    pp = PowerProperty("Power Plant")
    p.SetProperty(pp)
    assert p.GetProperty() is pp


def test_repair_subsystem_property_back_reference():
    from engine.appc.properties import RepairSubsystemProperty
    r = RepairSubsystem("Engineering")
    rp = RepairSubsystemProperty("Engineering")
    r.SetProperty(rp)
    assert r.GetProperty() is rp
