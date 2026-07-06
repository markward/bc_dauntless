"""PowerSubsystem.Update — BC interval-tick semantics (Task 3).

BC's power plant accumulates elapsed game time and fires a 1-second
interval tick: generate output*elapsed into batteries (main first, spill
to backup, discard overflow), then compute conduit budgets from battery
levels and capacity.  No drain in this task; Task 4 adds the consumer pump.

Floating-point note: due to IEEE-754 arithmetic, 60 additions of (1/60)
overflow to just above 1.0, so the first interval fires after EXACTLY 60
ticks (not 61).  Subsequent intervals fire after every 59 ticks because the
remainder (elapsed - POWER_INTERVAL) carries forward as the starting value.
All expected values in these tests are derived from the same accumulated-sum
arithmetic that the implementation uses, not from multiplication.
"""
from engine.appc.subsystems import PowerSubsystem
from engine.appc.properties import PowerProperty

# 1/60 s tick (BC fixed at 60 Hz)
_DT = 1.0 / 60.0


def _accum_elapsed(n: int, dt: float = _DT) -> float:
    """Sum n additions of dt — same floating-point path as Update's +=."""
    t = 0.0
    for _ in range(n):
        t += dt
    return t


# The first interval fires after 60 ticks: accumulated sum = 1.0 + epsilon.
_ELAPSED_FIRST = _accum_elapsed(60)


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


def _run_ticks(ps, n, dt=_DT):
    """Run exactly n ticks of dt."""
    for _ in range(n):
        ps.Update(dt)


def _run_seconds(ps, seconds, dt=_DT):
    for _ in range(int(seconds / dt)):
        ps.Update(dt)


# ── Recharge / spill / discard ────────────────────────────────────────────────

def test_recharge_fills_main_then_spills_to_backup_then_discards():
    """output=1000, main_cap=500, backup_cap=300.

    After one interval (≈ 1.0 + eps s): generation ≈ 1000 → 500 fills main,
    spill to backup (capped at 300).  After two more intervals caps hold;
    overflow discarded.
    """
    ps = PowerSubsystem("Warp Core")
    _bind(ps, output=1000.0, main=500.0, backup=300.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)

    _run_ticks(ps, 60)   # first interval fires at tick 60

    assert ps.GetMainBatteryPower() == 500.0    # capped at limit
    # Spill to backup = generated - main_fill = (1000 * _ELAPSED_FIRST) - 500.0,
    # then capped at backup limit of 300.0.
    expected_spill = (1000.0 * _ELAPSED_FIRST) - 500.0
    expected_in_backup = min(expected_spill, 300.0)
    assert abs(ps.GetBackupBatteryPower() - expected_in_backup) < 0.001

    # Run two more seconds — caps hold, overflow discarded
    _run_seconds(ps, 2.0)
    assert ps.GetMainBatteryPower() == 500.0
    assert ps.GetBackupBatteryPower() == 300.0


def test_recharge_partial_main_battery():
    """Main battery has room for less than one interval's output.

    output=200, main_cap=100, backup_cap=10000.  After first interval:
    generated = 200 * _ELAPSED_FIRST; main fills to 100, spill to backup.
    """
    ps = PowerSubsystem("Warp Core")
    _bind(ps, output=200.0, main=100.0, backup=10000.0,
          main_conduit=9999.0, backup_conduit=9999.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)

    _run_ticks(ps, 60)   # first interval

    expected_gen = 200.0 * _ELAPSED_FIRST
    assert ps.GetMainBatteryPower() == 100.0
    assert abs(ps.GetBackupBatteryPower() - (expected_gen - 100.0)) < 0.001


def test_no_recharge_while_reactor_offline():
    """IsDestroyed() == 1 blocks recharge; batteries stay at 0."""
    ps = PowerSubsystem("Warp Core")
    _bind(ps, main=1000.0, backup=5000.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)
    # Drive condition to zero so IsDestroyed() returns 1
    ps.SetCondition(0.0)
    _run_seconds(ps, 2.0)
    assert ps.GetMainBatteryPower() == 0.0


def test_no_recharge_while_reactor_disabled():
    """IsDisabled() == 1 (condition at/below DisabledPercentage threshold)."""
    ps = PowerSubsystem("Warp Core")
    _bind(ps, main=1000.0, backup=5000.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)
    # Use a high disabled threshold: disabled when condition <= 50% of max
    ps.SetMaxCondition(100.0)
    ps.SetDisabledPercentage(0.5)   # disabled when condition <= 50
    ps.SetCondition(30.0)           # 30 <= 50 → IsDisabled() == 1
    _run_seconds(ps, 2.0)
    assert ps.GetMainBatteryPower() == 0.0


# ── Conduit budgets ───────────────────────────────────────────────────────────

def test_conduit_budgets_computed_per_interval():
    """Full batteries, full health: budgets = capacity * elapsed.

    After first interval (60 ticks, elapsed = _ELAPSED_FIRST ≈ 1.0 s):
    main_budget = min(battery, 1200 * elapsed);
    backup_budget = min(battery, 200 * elapsed).
    GetAvailablePower() = main_budget + backup_budget.
    """
    ps = PowerSubsystem("Warp Core")
    _bind(ps)  # defaults: main=250000, backup=80000, main_cond=1200, bkup_cond=200
    _run_ticks(ps, 60)   # first interval

    elapsed = _ELAPSED_FIRST
    expected_main_budget = min(ps.GetMainBatteryPower(), 1200.0 * elapsed)
    expected_backup_budget = min(ps.GetBackupBatteryPower(), 200.0 * elapsed)
    expected_total = expected_main_budget + expected_backup_budget

    assert abs(ps.GetAvailablePower() - expected_total) < 0.001


def test_conduit_budget_capped_by_battery_level():
    """Conduit budget is capped to the available battery when battery < capacity*elapsed."""
    ps = PowerSubsystem("Warp Core")
    # Main battery only has 50 units; conduit capacity is 1200/s — far larger
    _bind(ps, output=0.0, main=50.0, backup=10000.0,
          main_conduit=1200.0, backup_conduit=200.0)
    ps.SetMainBatteryPower(50.0)
    ps.SetBackupBatteryPower(10000.0)

    _run_ticks(ps, 60)   # first interval

    elapsed = _ELAPSED_FIRST
    # main_conduit_current = min(50, 1200 * elapsed) = 50
    # backup_conduit_current = min(10000, 200 * elapsed) = 200 * _ELAPSED_FIRST ≈ 200.017
    expected_backup = min(10000.0, 200.0 * elapsed)
    assert abs(ps.GetAvailablePower() - (50.0 + expected_backup)) < 0.001


# ── Interval boundary ────────────────────────────────────────────────────────

def test_interval_does_not_fire_before_1_second():
    """After 59 ticks (< 1 s), interval hasn't fired; batteries stay at 0."""
    ps = PowerSubsystem("Warp Core")
    _bind(ps, output=1000.0, main=50000.0, backup=50000.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)

    _run_ticks(ps, 59)   # 59/60 s < 1.0 s

    assert ps.GetMainBatteryPower() == 0.0


def test_interval_fires_at_60_ticks():
    """After exactly 60 ticks (≈ 1.0 + eps s), interval fires once.

    Battery is non-zero, indicating recharge occurred.
    """
    ps = PowerSubsystem("Warp Core")
    _bind(ps, output=1000.0, main=50000.0, backup=50000.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)

    _run_ticks(ps, 60)

    expected = 1000.0 * _ELAPSED_FIRST
    assert abs(ps.GetMainBatteryPower() - expected) < 0.001


def test_multiple_intervals_each_add_correctly():
    """3 full intervals each contribute one generation burst.

    Each interval fires after 60 ticks (accumulated sum crosses 1.0 due
    to IEEE-754: 60 × (1/60) = 1.0 + epsilon).  3 intervals = 180 ticks.
    Total battery = 3 * 100 * _ELAPSED_FIRST.
    """
    ps = PowerSubsystem("Warp Core")
    _bind(ps, output=100.0, main=50000.0, backup=50000.0,
          main_conduit=9999.0, backup_conduit=9999.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)

    _run_ticks(ps, 180)   # 3 intervals × 60 ticks

    expected = 3 * 100.0 * _ELAPSED_FIRST
    assert abs(ps.GetMainBatteryPower() - expected) < 0.001


# ── No-property guard ─────────────────────────────────────────────────────────

def test_update_no_property_is_noop():
    """No property bound — Update should return silently, battery unchanged."""
    ps = PowerSubsystem("Warp Core")
    ps.SetMainBatteryPower(500.0)
    ps.Update(_DT)
    assert ps.GetMainBatteryPower() == 500.0
