"""Unit tests for ShieldSubsystem.GetShieldPercentage — aggregate
ratio across 6 faces. Used by SelectTarget rating."""
from engine.appc.subsystems import ShieldSubsystem
from engine.appc.properties import ShieldProperty


def test_unshielded_ship_returns_one():
    """No max set on any face → defaults to 1.0 so the rating
    doesn't unduly penalize ships that just don't have shields."""
    ss = ShieldSubsystem("X")
    assert ss.GetShieldPercentage() == 1.0


def test_full_shields_returns_one():
    ss = ShieldSubsystem("X")
    for f in range(ShieldProperty.NUM_SHIELDS):
        ss.SetMaxShields(f, 100.0)
    assert ss.GetShieldPercentage() == 1.0


def test_half_shields_returns_half():
    ss = ShieldSubsystem("X")
    for f in range(ShieldProperty.NUM_SHIELDS):
        ss.SetMaxShields(f, 100.0)
        ss.SetCurrentShields(f, 50.0)
    assert ss.GetShieldPercentage() == 0.5


def test_zero_shields_returns_zero():
    ss = ShieldSubsystem("X")
    for f in range(ShieldProperty.NUM_SHIELDS):
        ss.SetMaxShields(f, 100.0)
        ss.SetCurrentShields(f, 0.0)
    assert ss.GetShieldPercentage() == 0.0


def test_mixed_face_strengths_weighted_by_max():
    """Front + Rear at full, rest at zero max → percentage is the
    average of the two faces with max, not 2/6."""
    ss = ShieldSubsystem("X")
    ss.SetMaxShields(0, 100.0); ss.SetCurrentShields(0, 100.0)
    ss.SetMaxShields(1, 100.0); ss.SetCurrentShields(1, 50.0)
    # Total max = 200; total current = 150; ratio = 0.75
    assert ss.GetShieldPercentage() == 0.75
