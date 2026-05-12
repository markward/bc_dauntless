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


def test_face_constants_on_subsystem():
    """SDK reads App.ShieldClass.FRONT_SHIELDS / NUM_SHIELDS — the class
    itself must carry them, not just ShieldProperty."""
    assert ShieldSubsystem.NUM_SHIELDS == 6
    assert ShieldSubsystem.FRONT_SHIELDS == 0
    assert ShieldSubsystem.REAR_SHIELDS == 1
    assert ShieldSubsystem.TOP_SHIELDS == 2
    assert ShieldSubsystem.BOTTOM_SHIELDS == 3
    assert ShieldSubsystem.LEFT_SHIELDS == 4
    assert ShieldSubsystem.RIGHT_SHIELDS == 5


def test_set_cur_shields_aliases_set_current_shields():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 8000.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 3000.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 3000.0
