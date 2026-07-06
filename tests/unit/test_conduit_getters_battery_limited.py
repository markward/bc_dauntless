"""SDK-facing conduit-capacity getters are battery-limited (q10 ground truth).

q10 (tools/probes/results/q10_battery_drain.txt) showed the original engine's
SDK AdjustPower throttling impulse/warp/sensors once the MAIN battery ran dry
(s38->s39: sliders drop to 0.40/0.40/0.45 as main hit ~1%). For AdjustPower /
IsPowerDraining / PowerDisplay.Update to see the capacity shrink as a battery
empties, GetMainConduitCapacity() / GetBackupConduitCapacity() must clamp the
rated capacity by the remaining battery charge:

    GetMainConduitCapacity()   = min(main_battery,   rated_main * conditionPct)
    GetBackupConduitCapacity() = min(backup_battery, rated_backup)

The per-interval budget tick keeps its OWN internal view (rated capacity, not
the battery-clamped getter) so the min-with-battery is not double-applied — see
test_interval_budget_still_uses_raw_capacity.
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


def test_main_conduit_capacity_full_battery_returns_rated():
    """Full battery > rated capacity -> getter reports the rated (health-scaled)
    capacity unchanged (existing drain-law behaviour is preserved)."""
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    assert ps.GetMainConduitCapacity() == 1200.0
    assert ps.GetBackupConduitCapacity() == 200.0


def test_main_conduit_capacity_clamped_by_near_empty_battery():
    """When the main battery holds less than the rated capacity, the getter
    reports the battery charge (AdjustPower sees the shrink)."""
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    ps.SetMainBatteryPower(400.0)          # < 1200 rated
    assert ps.GetMainConduitCapacity() == 400.0


def test_backup_conduit_capacity_clamped_by_near_empty_battery():
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    ps.SetBackupBatteryPower(50.0)         # < 200 rated
    assert ps.GetBackupConduitCapacity() == 50.0


def test_main_conduit_capacity_clamp_composes_with_health_scaling():
    """condition scaling AND battery clamp both apply: rated*condPct then min
    with battery. Health 50% -> 600 rated; battery 300 -> reports 300."""
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    ps.SetMaxCondition(7000.0)
    ps.SetCondition(3500.0)                # 50% health -> rated 600
    ps.SetMainBatteryPower(300.0)
    assert ps.GetMainConduitCapacity() == 300.0
    # backup is not health-scaled but IS battery-clamped
    ps.SetBackupBatteryPower(120.0)
    assert ps.GetBackupConduitCapacity() == 120.0


def test_raw_max_main_conduit_capacity_unaffected_by_battery():
    """GetMaxMainConduitCapacity is the raw authored number — no health scale,
    no battery clamp (used for AdjustPower's ceiling reference)."""
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    ps.SetMainBatteryPower(1.0)
    assert ps.GetMaxMainConduitCapacity() == 1200.0


def test_interval_budget_still_uses_raw_capacity():
    """The per-interval budget = min(battery, rated*condPct*elapsed). The tick
    must NOT double-apply the getter's battery clamp: with a full battery the
    seeded conduit budget is the full rated capacity for a 1s interval."""
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    ps.Update(1.0)                          # one interval fires
    # Full battery -> conduit budget = rated capacity * 1s (no shrink).
    assert ps._main_conduit_current == 1200.0
    assert ps._backup_conduit_current == 200.0


def test_no_property_getters_return_zero():
    ps = PowerSubsystem("Warp Core")
    assert ps.GetMainConduitCapacity() == 0.0
    assert ps.GetBackupConduitCapacity() == 0.0
