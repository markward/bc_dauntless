"""SetupProperties copies ShieldProperty fields onto the ShieldSubsystem."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ShieldProperty


def test_shield_property_propagation():
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxCondition(12000.0)
    sp.SetNormalPowerPerSecond(400.0)
    sp.SetMaxShields(ShieldProperty.FRONT_SHIELDS,  8000.0)
    sp.SetMaxShields(ShieldProperty.REAR_SHIELDS,   4000.0)
    sp.SetMaxShields(ShieldProperty.TOP_SHIELDS,    4000.0)
    sp.SetMaxShields(ShieldProperty.BOTTOM_SHIELDS, 4000.0)
    sp.SetMaxShields(ShieldProperty.LEFT_SHIELDS,   4000.0)
    sp.SetMaxShields(ShieldProperty.RIGHT_SHIELDS,  4000.0)
    for face in range(ShieldProperty.NUM_SHIELDS):
        sp.SetShieldChargePerSecond(face, 11.0)

    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    shield = ship.GetShieldSubsystem()
    assert shield is not None
    assert shield.GetMaxCondition() == 12000.0
    assert shield.GetNormalPowerPerSecond() == 400.0
    assert shield.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 8000.0
    assert shield.GetMaxShields(ShieldProperty.REAR_SHIELDS) == 4000.0
    # Current seeded equal to max:
    for face in range(ShieldProperty.NUM_SHIELDS):
        assert shield.GetCurrentShields(face) == shield.GetMaxShields(face)
        assert shield.GetShieldChargePerSecond(face) == 11.0


def test_get_shields_aliases_get_shield_subsystem():
    """SDK uses pShip.GetShields(); engine has GetShieldSubsystem.
    Both names must return the same object."""
    ship = ShipClass_Create("Galaxy")
    assert ship.GetShields() is ship.GetShieldSubsystem()


def test_setup_properties_sets_shield_property_back_ref():
    """After SetupProperties copies a ShieldProperty onto the subsystem,
    the subsystem's GetProperty() returns the source property.
    loadspacehelper.py:246 reads pShields.GetProperty()."""
    ship = ShipClass_Create("Galaxy")
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    assert ship.GetShields().GetProperty() is sp
