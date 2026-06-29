"""Subsystem FloatRangeWatcher getters + per-tick drive (W1.T2).

Three SDK conditions obtain a FloatRangeWatcher from a subsystem getter and
register a threshold check on it:

* Conditions/ConditionPowerBelow.py     -> pPower.GetMainBatteryWatcher() /
                                           pPower.GetBackupBatteryWatcher()
                                           (watched var = battery FRACTION)
* Conditions/ConditionSingleShieldBelow.py -> pShields.GetShieldWatcher(side)
                                           (watched var = single-face FRACTION)
* Conditions/ConditionPulseReady.py     -> pWeapon.GetChargeWatcher()
                                           (watched var = charge FRACTION =
                                            charge / max_charge)

These tests pin (a) stable-identity getters and (b) that the owning subsystem
actually pushes the right quantity into its watcher each tick / on value
change, so the registered crossing event fires.
"""
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.subsystems import PowerSubsystem, ShieldSubsystem
from engine.appc.weapon_subsystems import PulseWeapon
from engine.appc.properties import PowerProperty
from engine.appc.ships import ShipClass_Create


class _RecordingEvent:
    """Minimal pEvent: records SetFloat values and that AddEvent was called.

    Registered with a watcher; we use a per-watcher event_manager that simply
    appends fired events so we can assert the crossing path ran."""
    def __init__(self):
        self.floats = []

    def SetFloat(self, v):
        self.floats.append(float(v))


class _FiringManager:
    def __init__(self):
        self.fired = []

    def AddEvent(self, pEvent):
        self.fired.append(pEvent)


def _bind_power_property(ps, *, output, main_cap, backup_cap=0.0):
    prop = PowerProperty("WarpCore")
    prop.SetPowerOutput(output)
    prop.SetMainBatteryLimit(main_cap)
    prop.SetBackupBatteryLimit(backup_cap)
    ps.SetProperty(prop)
    return prop


# ── Getter identity ──────────────────────────────────────────────────────────

def test_power_watcher_getters_return_stable_watchers():
    ps = PowerSubsystem("WarpCore")
    main = ps.GetMainBatteryWatcher()
    backup = ps.GetBackupBatteryWatcher()
    assert isinstance(main, FloatRangeWatcher)
    assert isinstance(backup, FloatRangeWatcher)
    assert main is not backup
    assert ps.GetMainBatteryWatcher() is main
    assert ps.GetBackupBatteryWatcher() is backup


def test_shield_watcher_getter_returns_stable_watcher_per_face():
    sh = ShieldSubsystem("Shields")
    front = sh.GetShieldWatcher(ShieldSubsystem.FRONT_SHIELDS)
    rear = sh.GetShieldWatcher(ShieldSubsystem.REAR_SHIELDS)
    assert isinstance(front, FloatRangeWatcher)
    assert front is not rear
    assert sh.GetShieldWatcher(ShieldSubsystem.FRONT_SHIELDS) is front


def test_charge_watcher_getter_returns_stable_watcher():
    pw = PulseWeapon("Pulse")
    w = pw.GetChargeWatcher()
    assert isinstance(w, FloatRangeWatcher)
    assert pw.GetChargeWatcher() is w


# ── Power: Update pushes the battery FRACTION ────────────────────────────────

def test_power_update_drives_main_battery_fraction_into_watcher():
    """Draining the main battery below a registered fraction fires the
    crossing event with the fraction (matches ConditionPowerBelow)."""
    ship = ShipClass_Create("Test")
    ps = ship.GetPowerSubsystem()
    _bind_power_property(ps, output=0.0, main_cap=1000.0)
    ps.SetMainBatteryPower(1000.0)
    # Seed the watcher's prior value at the full fraction (1.0).
    ps.Update(1.0)
    assert ps.GetMainBatteryWatcher().GetWatchedVariable() == 1.0

    mgr = _FiringManager()
    w = ps.GetMainBatteryWatcher()
    w._event_manager = mgr
    ev = _RecordingEvent()
    w.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BELOW, ev)

    # Drain a big idle load so the next tick takes the fraction below 0.5.
    sensor = ship.GetSensorSubsystem()
    sensor.SetNormalPowerPerSecond(800.0)
    sensor.TurnOn()
    ps.Update(1.0)  # 1000 - 800 = 200 -> fraction 0.2 < 0.5

    assert ps.GetMainBatteryWatcher().GetWatchedVariable() == 0.2
    assert mgr.fired, "main battery watcher did not fire on downward crossing"
    assert ev.floats[-1] == 0.2


def test_power_update_zero_main_cap_pushes_zero_fraction():
    """No divide-by-zero: a zero main-battery cap yields fraction 0.0."""
    ship = ShipClass_Create("Test")
    ps = ship.GetPowerSubsystem()
    _bind_power_property(ps, output=0.0, main_cap=0.0)
    ps.Update(1.0)
    assert ps.GetMainBatteryWatcher().GetWatchedVariable() == 0.0


def test_power_update_drives_backup_battery_fraction_into_watcher():
    ship = ShipClass_Create("Test")
    ps = ship.GetPowerSubsystem()
    _bind_power_property(ps, output=0.0, main_cap=1000.0, backup_cap=2000.0)
    ps.SetBackupBatteryPower(2000.0)
    ps.Update(1.0)
    assert ps.GetBackupBatteryWatcher().GetWatchedVariable() == 1.0


# ── Shield: drive single-face fraction ───────────────────────────────────────

def test_shield_update_drives_face_fraction_into_watcher():
    sh = ShieldSubsystem("Shields")
    sh.SetMaxShields(ShieldSubsystem.FRONT_SHIELDS, 100.0)
    sh.SetCurrentShields(ShieldSubsystem.FRONT_SHIELDS, 100.0)
    sh.TurnOn()
    # Seed prior value (fraction 1.0).
    sh.Update(0.0)
    w = sh.GetShieldWatcher(ShieldSubsystem.FRONT_SHIELDS)
    assert w.GetWatchedVariable() == 1.0

    mgr = _FiringManager()
    w._event_manager = mgr
    ev = _RecordingEvent()
    w.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BELOW, ev)

    sh.SetCurrentShields(ShieldSubsystem.FRONT_SHIELDS, 30.0)
    sh.Update(0.0)  # fraction 0.3 < 0.5

    assert w.GetWatchedVariable() == 0.3
    assert mgr.fired, "shield watcher did not fire on downward crossing"


# ── Pulse: drive charge fraction ─────────────────────────────────────────────

def test_pulse_update_drives_charge_fraction_into_watcher():
    pw = PulseWeapon("Pulse")
    pw._max_charge = 10.0
    pw._recharge_rate = 0.0
    pw.SetChargeLevel(10.0)
    pw.UpdateCharge(0.0)
    w = pw.GetChargeWatcher()
    assert w.GetWatchedVariable() == 1.0

    mgr = _FiringManager()
    w._event_manager = mgr
    ev = _RecordingEvent()
    w.AddRangeCheck(0.5, FloatRangeWatcher.FRW_BELOW, ev)

    pw.SetChargeLevel(2.0)
    pw.UpdateCharge(0.0)  # fraction 0.2 < 0.5

    assert w.GetWatchedVariable() == 0.2
    assert mgr.fired, "charge watcher did not fire on downward crossing"


# ── Integration: ConditionPowerBelow flips on a real drain ───────────────────

def test_condition_power_below_flips_status_on_drain():
    """End-to-end: a real ConditionPowerBelow against a ship's PowerSubsystem
    starts at status 0 (full battery) and flips to 1 once Update drains the
    main battery below the fraction."""
    from engine.appc.ai import ConditionScript_Create

    ship = ShipClass_Create("PowerTarget")
    ps = ship.GetPowerSubsystem()
    _bind_power_property(ps, output=0.0, main_cap=1000.0)
    ps.SetMainBatteryPower(1000.0)
    ps.Update(1.0)  # seed watcher at fraction 1.0

    # ConditionPowerBelow(pCodeCondition, pObject, bReserveOnly, fPowerFraction)
    cs = ConditionScript_Create(
        "Conditions.ConditionPowerBelow", "ConditionPowerBelow",
        ship, 0, 0.5,
    )
    assert cs._instance is not None, cs._init_error
    assert cs.GetStatus() == 0  # battery full, above fraction

    sensor = ship.GetSensorSubsystem()
    sensor.SetNormalPowerPerSecond(800.0)
    sensor.TurnOn()
    ps.Update(1.0)  # fraction -> 0.2, crosses below 0.5

    assert cs.GetStatus() == 1
