"""PowerSubsystem.Update — interval-tick semantics (generation + caps).

Rewritten in Task 3 to match BC's 1-second interval model.  Drain was part
of the old per-dt net-energy model; Task 4 introduces the consumer pump that
replaces it.  These tests cover generation, battery caps, conduit budgets,
and the no-property guard.

Note: `Update(1.0)` passes dt=1.0 which is ≥ POWER_INTERVAL (1.0 s), so the
interval fires in a single call.  elapsed = 1.0.
"""
from engine.appc.subsystems import (
    PowerSubsystem, PoweredSubsystem, SensorSubsystem,
)
from engine.appc.properties import PowerProperty
from engine.appc.ships import ShipClass_Create


def _bind_property(ps, *, output, main_cap, backup_cap=0.0, main_conduit=1200.0,
                   backup_conduit=0.0):
    prop = PowerProperty("WarpCore")
    prop.SetPowerOutput(output)
    prop.SetMainBatteryLimit(main_cap)
    prop.SetBackupBatteryLimit(backup_cap)
    prop.SetMainConduitCapacity(main_conduit)
    prop.SetBackupConduitCapacity(backup_conduit)
    ps.SetProperty(prop)
    return prop


def test_update_with_no_parent_ship_grows_battery_by_generation():
    """No consumers.  One 1-second interval deposits full output into battery."""
    ps = PowerSubsystem("WarpCore")
    _bind_property(ps, output=1000.0, main_cap=10000.0)
    ps.SetMainBatteryPower(0.0)
    ps.Update(1.0)
    assert ps.GetMainBatteryPower() == 1000.0
    # Available = conduit budget: min(1000, 1200 * 1.0) = 1000
    assert ps.GetAvailablePower() == 1000.0


def test_update_caps_main_battery_at_limit():
    """Generation that would exceed main-battery cap is stopped at the cap."""
    ps = PowerSubsystem("WarpCore")
    _bind_property(ps, output=1000.0, main_cap=500.0)
    ps.SetMainBatteryPower(400.0)
    ps.Update(1.0)
    # 1000 generated → room=100 → main capped at 500
    assert ps.GetMainBatteryPower() == 500.0


def test_update_generation_spills_to_backup():
    """Surplus beyond main cap spills to backup battery (BC fill order)."""
    ps = PowerSubsystem("WarpCore")
    _bind_property(ps, output=1500.0, main_cap=500.0, backup_cap=5000.0,
                   main_conduit=9999.0, backup_conduit=9999.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)
    ps.Update(1.0)
    # 1500 generated → 500 fills main, 1000 spills to backup
    assert ps.GetMainBatteryPower() == 500.0
    assert ps.GetBackupBatteryPower() == 1000.0


def test_update_generation_overflow_discarded():
    """Generation that fills both batteries leaves the rest discarded."""
    ps = PowerSubsystem("WarpCore")
    _bind_property(ps, output=2000.0, main_cap=500.0, backup_cap=300.0,
                   main_conduit=9999.0, backup_conduit=9999.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)
    ps.Update(1.0)
    # 2000 → main capped at 500, backup capped at 300, 1200 discarded
    assert ps.GetMainBatteryPower() == 500.0
    assert ps.GetBackupBatteryPower() == 300.0


def test_update_conduit_budget_limits_available():
    """Available power is bounded by conduit capacity * elapsed, not raw battery."""
    ps = PowerSubsystem("WarpCore")
    _bind_property(ps, output=5000.0, main_cap=50000.0, main_conduit=300.0)
    ps.SetMainBatteryPower(0.0)
    ps.Update(1.0)
    # Battery = 5000; conduit can only pass 300/s; available = 300
    assert ps.GetAvailablePower() == 300.0


def test_update_no_recharge_when_destroyed():
    """Destroyed reactor (condition=0) produces no power."""
    ps = PowerSubsystem("WarpCore")
    _bind_property(ps, output=1000.0, main_cap=10000.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetCondition(0.0)   # triggers IsDestroyed() == 1
    ps.Update(1.0)
    assert ps.GetMainBatteryPower() == 0.0


def test_update_no_property_is_a_noop():
    """A ship without a wired PowerProperty gracefully skips Update."""
    ps = PowerSubsystem("WarpCore")
    ps.SetMainBatteryPower(500.0)
    ps.Update(1.0)
    assert ps.GetMainBatteryPower() == 500.0
