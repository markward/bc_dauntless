"""PowerSubsystem runtime budget — available + main + backup pools and
the arithmetic ops weapons / subsystems use to drain them.

Mirrors the SDK Appc surface (App.py:5739-5754):
    GetAvailablePower / SetAvailablePower
    GetMainBatteryPower / SetMainBatteryPower
    GetBackupBatteryPower / SetBackupBatteryPower
    AddPower / DeductPower / StealPower / StealPowerFromReserve

These are the hooks WeaponSystem.Fire and the per-tick power flow will
sit on top of in later slices.  This slice only pins the storage and
arithmetic — no per-tick refill yet, no per-fire gate yet.
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


def test_steal_power_uses_available_first():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(50.0)
    p.SetMainBatteryPower(1000.0)
    ok = p.StealPower(30.0)
    assert ok == 1
    assert p.GetAvailablePower() == 20.0
    assert p.GetMainBatteryPower() == 1000.0


def test_steal_power_falls_back_to_main_battery():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(10.0)
    p.SetMainBatteryPower(1000.0)
    ok = p.StealPower(30.0)
    assert ok == 1
    assert p.GetAvailablePower() == 0.0
    assert p.GetMainBatteryPower() == 980.0


def test_steal_power_fails_when_combined_pools_insufficient():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(5.0)
    p.SetMainBatteryPower(10.0)
    ok = p.StealPower(30.0)
    assert ok == 0
    # No partial drain — both pools unchanged.
    assert p.GetAvailablePower() == 5.0
    assert p.GetMainBatteryPower() == 10.0


def test_steal_power_from_reserve_drains_main_battery_first():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(100.0)
    p.SetMainBatteryPower(50.0)
    ok = p.StealPowerFromReserve(30.0)
    assert ok == 1
    assert p.GetMainBatteryPower() == 20.0
    assert p.GetAvailablePower() == 100.0


def test_steal_power_from_reserve_falls_back_to_available():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(100.0)
    p.SetMainBatteryPower(20.0)
    ok = p.StealPowerFromReserve(50.0)
    assert ok == 1
    assert p.GetMainBatteryPower() == 0.0
    assert p.GetAvailablePower() == 70.0


def test_steal_power_from_reserve_fails_when_combined_insufficient():
    p = PowerSubsystem("WarpCore")
    p.SetAvailablePower(5.0)
    p.SetMainBatteryPower(10.0)
    ok = p.StealPowerFromReserve(30.0)
    assert ok == 0
    assert p.GetMainBatteryPower() == 10.0
    assert p.GetAvailablePower() == 5.0
