"""Pass 4 instantiates one live child subsystem per child WeaponProperty,
attaching it under the matching parent slot via AddChildSubsystem.

Property type -> child slot mapping:
    PhaserProperty       -> _phaser_system._children   (PhaserBank)
    PulseWeaponProperty  -> _pulse_weapon_system       (PulseWeapon)
    TractorBeamProperty  -> _tractor_beam_system       (TractorBeam)
    TorpedoTubeProperty  -> _torpedo_system            (TorpedoTube)
"""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import (
    WeaponSystemProperty, PhaserProperty, PulseWeaponProperty,
    TractorBeamProperty, TorpedoTubeProperty,
)
from engine.appc.subsystems import (
    PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
)


def _tractor_parent():
    p = WeaponSystemProperty("Tractors")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TRACTOR)
    return p


def _phaser_parent():
    p = WeaponSystemProperty("Phasers")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    return p


def _pulse_parent():
    p = WeaponSystemProperty("Pulse")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PULSE)
    return p


def _torpedo_parent():
    p = WeaponSystemProperty("Torpedoes")
    p.SetWeaponSystemType(WeaponSystemProperty.WST_TORPEDO)
    return p


def test_tractor_children_attached_to_parent():
    ship = ShipClass_Create("DryDock")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _tractor_parent())
    for n in ("Aft Tractor 1", "Aft Tractor 2",
              "Forward Tractor 1", "Forward Tractor 2"):
        ps.AddToSet("Scene Root", TractorBeamProperty(n))
    ship.SetupProperties()

    parent = ship.GetTractorBeamSystem()
    assert parent is not None
    assert parent.GetNumChildSubsystems() == 4
    for i, expected in enumerate([
        "Aft Tractor 1", "Aft Tractor 2",
        "Forward Tractor 1", "Forward Tractor 2",
    ]):
        c = parent.GetChildSubsystem(i)
        assert isinstance(c, TractorBeam)
        assert c.GetName() == expected
        assert c.GetParentSubsystem() is parent


def test_phaser_children_attached_to_parent():
    ship = ShipClass_Create("Galaxy")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _phaser_parent())
    ps.AddToSet("Scene Root", PhaserProperty("Fore Phaser"))
    ps.AddToSet("Scene Root", PhaserProperty("Aft Phaser"))
    ship.SetupProperties()

    parent = ship.GetPhaserSystem()
    assert parent.GetNumChildSubsystems() == 2
    assert all(isinstance(parent.GetChildSubsystem(i), PhaserBank) for i in range(2))


def test_pulse_children_attached_to_parent():
    ship = ShipClass_Create("X")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _pulse_parent())
    ps.AddToSet("Scene Root", PulseWeaponProperty("Forward Pulse"))
    ship.SetupProperties()

    parent = ship.GetPulseWeaponSystem()
    assert parent.GetNumChildSubsystems() == 1
    assert isinstance(parent.GetChildSubsystem(0), PulseWeapon)


def test_torpedo_tubes_attached_as_children():
    ship = ShipClass_Create("Galaxy")
    ps = ship.GetPropertySet()
    ps.AddToSet("Scene Root", _torpedo_parent())
    ps.AddToSet("Scene Root", TorpedoTubeProperty("Forward Torpedo 1"))
    ps.AddToSet("Scene Root", TorpedoTubeProperty("Forward Torpedo 2"))
    ship.SetupProperties()

    parent = ship.GetTorpedoSystem()
    assert parent.GetNumChildSubsystems() == 2
    assert all(isinstance(parent.GetChildSubsystem(i), TorpedoTube) for i in range(2))


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
