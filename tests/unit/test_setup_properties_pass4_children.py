"""Pass 4 instantiates one live child subsystem per child WeaponProperty,
attaching it under the matching parent slot via AddChildSubsystem.

Property type -> child slot mapping (full coverage in
tests/integration/test_galaxy_hardpoint_emitters.py; this file covers
the edge cases and the pulse path since Galaxy has no pulse cannons):

    PulseWeaponProperty  -> _pulse_weapon_system       (PulseWeapon)
    TractorBeamProperty  -> _tractor_beam_system       (TractorBeam)
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    WeaponSystemProperty, PulseWeaponProperty,
    TractorBeamProperty,
)
from engine.appc.subsystems import (
    PulseWeapon, TractorBeam,
)


def _tractor_parent():
    p = WeaponSystemProperty("Tractors")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    return p


def _pulse_parent():
    p = WeaponSystemProperty("Pulse")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PULSE)
    return p


def test_pulse_children_attached_to_parent():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _pulse_parent())
    ps.AddToSet("Scene Root", PulseWeaponProperty("Forward Pulse"))
    ship.SetupProperties()

    parent = ship.GetPulseWeaponSystem()
    assert parent.GetNumChildSubsystems() == 1
    assert isinstance(parent.GetChildSubsystem(0), PulseWeapon)


def test_pass4_skips_children_when_parent_scrubbed():
    """A TractorBeamProperty without a parent WST_TRACTOR -> Pass 3
    scrubs the parent slot, Pass 4 finds no parent to attach to and
    silently skips."""
    ship = ShipClass_Create("X")
    ship.GetPropertySet().AddToSet("Scene Root", TractorBeamProperty("Orphan"))
    ship.SetupProperties()  # must not raise

    assert ship.GetTractorBeamSystem() is None
    # No exception, no half-attached state.


def test_pass4_idempotent_against_re_run():
    """Re-running SetupProperties must not double-attach children."""
    ship = ShipClass_Create("DryDock")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _tractor_parent())
    ps.AddToSet("Scene Root", TractorBeamProperty("Aft Tractor 1"))

    ship.SetupProperties()
    ship.SetupProperties()  # second call should detect existing children
    assert ship.GetTractorBeamSystem().GetNumChildSubsystems() == 1


def test_pass4_copies_child_property_back_reference():
    ship = ShipClass_Create("DryDock")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _tractor_parent())
    tbp = TractorBeamProperty("Aft Tractor 1")
    ps.AddToSet("Scene Root", tbp)
    ship.SetupProperties()

    child = ship.GetTractorBeamSystem().GetChildSubsystem(0)
    assert child.GetProperty() is tbp
