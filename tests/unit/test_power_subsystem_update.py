"""PowerSubsystem.Update — per-tick generation + idle-drain pass.

Each tick the PowerSubsystem:

* Generates `PowerOutput * dt` worth of power.
* Sums `NormalPowerPerSecond * dt` across every PoweredSubsystem on the
  parent ship that is currently on, and treats that as the idle drain.
* Net surplus tops up the main battery (capped at MainBatteryLimit) and
  also seeds `available_power` so weapons / ad-hoc consumers can spend
  it within the same tick.
* Net deficit drains main battery (then backup); `available_power`
  bottoms out at zero.

This is the per-tick flow consumers (TorpedoTube.Fire in slice 5) sit on
top of; the per-fire gate uses StealPower against available + main.
"""
from engine.appc.subsystems import (
    PowerSubsystem, PoweredSubsystem, SensorSubsystem,
)
from engine.appc.properties import PowerProperty
from engine.appc.ships import ShipClass_Create


def _bind_property(ps, *, output, main_cap, backup_cap=0.0, main_conduit=1200.0):
    prop = PowerProperty("WarpCore")
    prop.SetPowerOutput(output)
    prop.SetMainBatteryLimit(main_cap)
    prop.SetBackupBatteryLimit(backup_cap)
    prop.SetMainConduitCapacity(main_conduit)
    ps.SetProperty(prop)
    return prop


def test_update_with_no_parent_ship_grows_battery_by_generation():
    """No parent ship = zero idle drain.  One second of generation
    deposits full output into main battery and into the available
    pool."""
    ps = PowerSubsystem("WarpCore")
    _bind_property(ps, output=1000.0, main_cap=10000.0)
    ps.SetMainBatteryPower(0.0)
    ps.Update(1.0)
    assert ps.GetMainBatteryPower() == 1000.0
    assert ps.GetAvailablePower() == 1000.0


def test_update_caps_main_battery_at_limit():
    ps = PowerSubsystem("WarpCore")
    _bind_property(ps, output=1000.0, main_cap=500.0)
    ps.SetMainBatteryPower(400.0)
    ps.Update(1.0)
    # Net surplus 1000 would push to 1400 but cap is 500.
    assert ps.GetMainBatteryPower() == 500.0


def test_update_subtracts_idle_drain_from_powered_subsystems():
    """A PoweredSubsystem that's on with NormalPowerPerSecond=200
    drains the generation by 200/s.  Net 1000-200=800 banked + made
    available."""
    ship = ShipClass_Create("Test")
    ps = ship.GetPowerSubsystem()
    _bind_property(ps, output=1000.0, main_cap=10000.0)
    ps.SetMainBatteryPower(0.0)

    sensor = ship.GetSensorSubsystem()
    sensor.SetNormalPowerPerSecond(200.0)
    sensor.TurnOn()

    ps.Update(1.0)
    assert ps.GetAvailablePower() == 800.0
    assert ps.GetMainBatteryPower() == 800.0


def test_update_ignores_subsystems_that_are_off():
    """An off subsystem contributes zero to idle drain — full output
    flows to battery."""
    ship = ShipClass_Create("Test")
    ps = ship.GetPowerSubsystem()
    _bind_property(ps, output=1000.0, main_cap=10000.0)
    ps.SetMainBatteryPower(0.0)

    sensor = ship.GetSensorSubsystem()
    sensor.SetNormalPowerPerSecond(200.0)
    sensor.TurnOff()   # sensors default ON; force off to exercise the skip path

    ps.Update(1.0)
    assert ps.GetAvailablePower() == 1000.0


def test_update_with_deficit_drains_main_battery():
    """Idle drain 1500/s vs output 1000/s → 500/s deficit, taken from
    main battery; available bottoms at zero."""
    ship = ShipClass_Create("Test")
    ps = ship.GetPowerSubsystem()
    _bind_property(ps, output=1000.0, main_cap=10000.0)
    ps.SetMainBatteryPower(5000.0)

    sensor = ship.GetSensorSubsystem()
    sensor.SetNormalPowerPerSecond(1500.0)
    sensor.TurnOn()

    ps.Update(1.0)
    assert ps.GetMainBatteryPower() == 4500.0
    assert ps.GetAvailablePower() == 0.0


def test_update_deficit_falls_back_to_backup_when_main_empty():
    ship = ShipClass_Create("Test")
    ps = ship.GetPowerSubsystem()
    _bind_property(ps, output=0.0, main_cap=10000.0, backup_cap=80000.0)
    ps.SetMainBatteryPower(100.0)
    ps.SetBackupBatteryPower(80000.0)

    sensor = ship.GetSensorSubsystem()
    sensor.SetNormalPowerPerSecond(500.0)
    sensor.TurnOn()

    ps.Update(1.0)
    # 500 deficit: 100 from main, 400 from backup.
    assert ps.GetMainBatteryPower() == 0.0
    assert ps.GetBackupBatteryPower() == 79600.0


def test_update_no_property_is_a_noop():
    """A ship without a wired PowerProperty (test stub) gracefully skips
    Update — nothing to read generation from."""
    ps = PowerSubsystem("WarpCore")
    ps.SetMainBatteryPower(500.0)
    ps.Update(1.0)
    assert ps.GetMainBatteryPower() == 500.0
