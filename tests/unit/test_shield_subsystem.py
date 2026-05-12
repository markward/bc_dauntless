"""ShieldSubsystem: six-face shield slots with seed-on-max behavior."""
from engine.appc.subsystems import ShieldSubsystem, PoweredSubsystem
from engine.appc.properties import ShieldProperty


def test_is_powered_subsystem():
    assert issubclass(ShieldSubsystem, PoweredSubsystem)


def test_defaults_zero_per_face():
    s = ShieldSubsystem("Shield Generator")
    for face in range(ShieldProperty.NUM_SHIELDS):
        assert s.GetMaxShields(face) == 0.0
        assert s.GetCurrentShields(face) == 0.0
        assert s.GetShieldChargePerSecond(face) == 0.0


def test_set_max_seeds_current_when_current_zero():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    assert s.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 8000.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 8000.0


def test_set_max_does_not_overwrite_nonzero_current():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    s.SetCurrentShields(ShieldProperty.FRONT_SHIELDS, 3000.0)  # take damage
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 10000.0)     # repair upgrade
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 3000.0  # unchanged


def test_charge_per_second():
    s = ShieldSubsystem("Shield Generator")
    s.SetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS, 11.0)
    assert s.GetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS) == 11.0


def test_faces_are_independent():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    s.SetMaxShields(ShieldProperty.REAR_SHIELDS, 4000.0)
    assert s.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 8000.0
    assert s.GetMaxShields(ShieldProperty.REAR_SHIELDS) == 4000.0
    assert s.GetMaxShields(ShieldProperty.TOP_SHIELDS) == 0.0
