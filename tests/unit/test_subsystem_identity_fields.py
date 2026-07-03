"""ShipSubsystem base identity fields: critical/targetable/primary/disabled."""
from engine.appc.subsystems import ShipSubsystem


def test_defaults():
    s = ShipSubsystem("Test")
    assert s.GetCritical() == 0
    # Targetable defaults to 1 (matches SubsystemProperty's default and the
    # prior IsTargetable()==1 behavior). SetupProperties copies the hardpoint's
    # value on top; only an explicit SetTargetable(0) hides a subsystem.
    assert s.GetTargetable() == 1
    assert s.IsTargetable() == 1
    assert s.GetPrimary() == 0
    assert s.GetDisabledPercentage() == 0.25


def test_setters_persist():
    s = ShipSubsystem("Test")
    s.SetCritical(1)
    s.SetTargetable(1)
    s.SetPrimary(1)
    s.SetDisabledPercentage(0.5)
    assert s.GetCritical() == 1
    assert s.GetTargetable() == 1
    assert s.GetPrimary() == 1
    assert s.GetDisabledPercentage() == 0.5


def test_disabled_percentage_is_field_not_constant():
    """Two instances should hold independent values."""
    a = ShipSubsystem("A")
    b = ShipSubsystem("B")
    a.SetDisabledPercentage(0.75)
    assert b.GetDisabledPercentage() == 0.25  # untouched
