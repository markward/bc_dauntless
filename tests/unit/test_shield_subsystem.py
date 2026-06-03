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


def test_single_shield_percentage_full():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    # SetMaxShields seeds current to max when current was 0
    assert s.GetSingleShieldPercentage(ShieldProperty.FRONT_SHIELDS) == 1.0


def test_single_shield_percentage_half():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    assert s.GetSingleShieldPercentage(ShieldProperty.FRONT_SHIELDS) == 0.5


def test_single_shield_percentage_zero_max_returns_zero():
    """A face with max=0 (unshielded ship) reports 0% without raising."""
    s = ShieldSubsystem("Shield Generator")
    assert s.GetSingleShieldPercentage(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_single_shield_percentage_zero_current():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 0.0)
    assert s.GetSingleShieldPercentage(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_update_regenerates_face():
    s = ShieldSubsystem("Shield Generator")
    s.TurnOn()  # Regen requires the generator to be powered (alert-level gate).
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 10.0)
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 60.0


def test_update_clamps_at_max():
    s = ShieldSubsystem("Shield Generator")
    s.TurnOn()
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 95.0)
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 100.0


def test_update_zero_charge_rate_noop():
    s = ShieldSubsystem("Shield Generator")
    s.TurnOn()
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    # charge_per_second defaults to 0
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 50.0


def test_update_skips_unshielded_face():
    """A face with max=0 (e.g. asteroid-like object) stays at 0 even if
    something erroneously set its charge_per_second."""
    s = ShieldSubsystem("Shield Generator")
    s.TurnOn()
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_update_powered_down_skips_regen():
    """Generator IsOn=False (default; ship at GREEN_ALERT) → no regen."""
    s = ShieldSubsystem("Shield Generator")
    assert s.IsOn() == 0
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 10.0)
    s.Update(1.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 50.0


def test_update_independent_per_face():
    s = ShieldSubsystem("Shield Generator")
    s.TurnOn()
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetMaxShields(ShieldProperty.REAR_SHIELDS, 200.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 0.0)
    s.SetCurShields(ShieldProperty.REAR_SHIELDS, 0.0)
    s.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 10.0)
    s.SetShieldChargePerSecond(ShieldProperty.REAR_SHIELDS, 20.0)
    s.Update(2.0)
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 20.0
    assert s.GetCurrentShields(ShieldProperty.REAR_SHIELDS) == 40.0


def test_apply_damage_partial():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    overflow = s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 30.0)
    assert overflow == 0.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 70.0


def test_apply_damage_exact():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 50.0)
    overflow = s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 50.0)
    assert overflow == 0.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_apply_damage_overflow():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 20.0)
    overflow = s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 50.0)
    assert overflow == 30.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 0.0


def test_apply_damage_other_faces_untouched():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetMaxShields(ShieldProperty.REAR_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.REAR_SHIELDS, 100.0)
    s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 40.0)
    assert s.GetCurrentShields(ShieldProperty.REAR_SHIELDS) == 100.0


def test_apply_damage_zero_amount_noop():
    s = ShieldSubsystem("Shield Generator")
    s.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    s.SetCurShields(ShieldProperty.FRONT_SHIELDS, 75.0)
    overflow = s.ApplyDamage(ShieldProperty.FRONT_SHIELDS, 0.0)
    assert overflow == 0.0
    assert s.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 75.0
