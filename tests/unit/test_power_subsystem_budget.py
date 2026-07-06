"""PowerSubsystem runtime budget — available + main + backup pools and
the arithmetic ops weapons / subsystems use to drain them.

Mirrors the SDK Appc surface (App.py:5739-5754):
    GetAvailablePower / SetAvailablePower
    GetMainBatteryPower / SetMainBatteryPower
    GetBackupBatteryPower / SetBackupBatteryPower
    AddPower / DeductPower / StealPower / StealPowerFromReserve

Task 2 updated StealPower / StealPowerFromReserve to be reservoir-specific
and return float (amount actually taken) instead of int 0/1.  Tests below
reflect the new semantics; the per-tick flow and conduit surface are
covered in test_power_subsystem_conduits.py.
"""
from engine.appc.subsystems import PowerSubsystem


def test_available_power_round_trip():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(50.0)
    assert p.GetAvailablePower() == 50.0


def test_main_and_backup_battery_round_trip():
    p = PowerSubsystem("WarpCore")
    p.SetMainBatteryPower(1234.5)
    p.SetBackupBatteryPower(67.0)
    assert p.GetMainBatteryPower() == 1234.5
    assert p.GetBackupBatteryPower() == 67.0


def test_pools_default_to_zero():
    p = PowerSubsystem("WarpCore")
    assert p.GetAvailablePower() == 0.0
    assert p.GetMainBatteryPower() == 0.0
    assert p.GetBackupBatteryPower() == 0.0


def test_add_power_increases_available():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(10.0)
    p.AddPower(15.0)
    assert p.GetAvailablePower() == 25.0


def test_deduct_power_succeeds_when_enough_available():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(50.0)
    ok = p.DeductPower(20.0)
    assert ok == 1
    assert p.GetAvailablePower() == 30.0


def test_deduct_power_fails_when_insufficient_no_partial_drain():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(10.0)
    ok = p.DeductPower(20.0)
    assert ok == 0
    # No partial drain — pool unchanged so callers can fall back cleanly.
    assert p.GetAvailablePower() == 10.0


def test_steal_power_drains_main_battery_only():
    """StealPower is main-battery-only; available pool is untouched (Task 2).

    Returns the float amount taken.  0.0 is falsy; positive is truthy —
    weapon_subsystems.py tractor/phaser call sites still work correctly in
    boolean context."""
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(50.0)
    p.SetMainBatteryPower(1000.0)
    taken = p.StealPower(30.0)
    assert taken == 30.0                     # float return
    assert p.GetAvailablePower() == 50.0     # available NOT drained
    assert p.GetMainBatteryPower() == 970.0  # main drained


def test_steal_power_partial_drain_when_main_low():
    """StealPower takes whatever main has (partial drain); does not touch backup."""
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(50.0)
    p.SetMainBatteryPower(10.0)
    p.SetBackupBatteryPower(500.0)
    taken = p.StealPower(30.0)
    assert taken == 10.0                     # only what main had
    assert p.GetMainBatteryPower() == 0.0
    assert p.GetBackupBatteryPower() == 500.0  # backup untouched
    assert p.GetAvailablePower() == 50.0     # available untouched


def test_steal_power_returns_zero_when_main_empty():
    """0.0 return is falsy — boolean callers treat this as 'no power'."""
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(50.0)
    p.SetMainBatteryPower(0.0)
    taken = p.StealPower(30.0)
    assert taken == 0.0
    assert not taken                         # falsy semantics preserved


def test_steal_power_from_reserve_drains_backup_only():
    """StealPowerFromReserve is backup-battery-only (Task 2)."""
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(100.0)
    p.SetMainBatteryPower(50.0)
    p.SetBackupBatteryPower(40.0)
    taken = p.StealPowerFromReserve(30.0)
    assert taken == 30.0
    assert p.GetBackupBatteryPower() == 10.0
    assert p.GetMainBatteryPower() == 50.0   # main untouched
    assert p.GetAvailablePower() == 100.0    # available untouched


def test_steal_power_from_reserve_partial_when_backup_low():
    """Partial drain when backup has less than requested."""
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(100.0)
    p.SetMainBatteryPower(200.0)
    p.SetBackupBatteryPower(20.0)
    taken = p.StealPowerFromReserve(50.0)
    assert taken == 20.0
    assert p.GetBackupBatteryPower() == 0.0
    assert p.GetMainBatteryPower() == 200.0  # main untouched


def test_steal_power_from_reserve_returns_zero_when_backup_empty():
    p = PowerSubsystem("WarpCore")
    p.SetMainBatteryPower(100.0)
    p.SetBackupBatteryPower(0.0)
    taken = p.StealPowerFromReserve(30.0)
    assert taken == 0.0
    assert not taken                         # falsy semantics preserved
