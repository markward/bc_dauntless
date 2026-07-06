"""PowerSubsystem battery/conduit surface with health-scaling asymmetry.

Pins the new interface added in Task 2 of the power-management plan:
- SetProperty fills batteries to their limits (BC FUN_005636D0)
- GetPowerOutput and GetMainConduitCapacity scale by GetConditionPercentage()
- GetBackupConduitCapacity does NOT scale with health (BC asymmetry)
- StealPower drains main battery only, returns float amount taken
- StealPowerFromReserve drains backup battery only, returns float amount taken
"""
from engine.appc.subsystems import PowerSubsystem
from engine.appc.properties import PowerProperty


def _bind(ps, output=1000.0, main=250000.0, backup=80000.0,
          main_conduit=1200.0, backup_conduit=200.0):
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(output)
    prop.SetMainBatteryLimit(main)
    prop.SetBackupBatteryLimit(backup)
    prop.SetMainConduitCapacity(main_conduit)
    prop.SetBackupConduitCapacity(backup_conduit)
    ps.SetProperty(prop)
    return prop


def test_set_property_fills_batteries():
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    assert ps.GetMainBatteryPower() == 250000.0
    assert ps.GetBackupBatteryPower() == 80000.0
    assert ps.GetMainBatteryLimit() == 250000.0
    assert ps.GetBackupBatteryLimit() == 80000.0


def test_output_and_main_conduit_scale_with_health_backup_does_not():
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    ps.SetMaxCondition(7000.0)
    ps.SetCondition(3500.0)          # 50% health
    assert abs(ps.GetPowerOutput() - 500.0) < 1e-6
    assert abs(ps.GetMainConduitCapacity() - 600.0) < 1e-6
    assert ps.GetMaxMainConduitCapacity() == 1200.0
    assert ps.GetBackupConduitCapacity() == 200.0    # NOT health-scaled


def test_steal_power_is_reservoir_specific():
    ps = PowerSubsystem("Warp Core")
    _bind(ps, main=100.0, backup=50.0)
    got = ps.StealPower(80.0)
    assert got == 80.0 and ps.GetMainBatteryPower() == 20.0
    got = ps.StealPower(50.0)                       # only 20 left in main
    assert got == 20.0 and ps.GetBackupBatteryPower() == 50.0  # backup untouched
    got = ps.StealPowerFromReserve(60.0)
    assert got == 50.0 and ps.GetBackupBatteryPower() == 0.0


def test_conduit_fields_exist_on_fresh_instance():
    """Task 2 internal fields must be present after __init__."""
    ps = PowerSubsystem("Warp Core")
    assert ps._main_conduit_current == 0.0
    assert ps._backup_conduit_current == 0.0
    assert ps._interval_elapsed == 0.0
    assert ps._power_dispensed == 0.0
    assert ps._power_wanted_total == 0.0


def test_get_power_dispensed_and_wanted_accessors():
    ps = PowerSubsystem("Warp Core")
    assert ps.GetPowerDispensed() == 0.0
    assert ps.GetPowerWanted() == 0.0


def test_get_power_output_no_property_returns_zero():
    ps = PowerSubsystem("Warp Core")
    assert ps.GetPowerOutput() == 0.0


def test_conduit_capacities_no_property_return_zero():
    ps = PowerSubsystem("Warp Core")
    assert ps.GetMaxMainConduitCapacity() == 0.0
    assert ps.GetMainConduitCapacity() == 0.0
    assert ps.GetBackupConduitCapacity() == 0.0
