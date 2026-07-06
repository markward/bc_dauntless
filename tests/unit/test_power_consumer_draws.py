"""Per-frame consumer draws — three modes, efficiency, registration (Task 4).

PowerSubsystem._pump_consumers walks the ship's registered powered consumers
(attach order = BC draw priority), each drawing its per-tick demand from the
conduit budget + battery via PowerSubsystem._draw(amount, mode).  Efficiency
(received/wanted) and power-factor (received/normal) are written back onto
each PoweredSubsystem so GetPowerPercentage / GetNormalPowerPercentage report
the real fed state.
"""
from engine.appc.subsystems import (
    PowerSubsystem, PoweredSubsystem, PSM_BACKUP_ONLY, CloakingSubsystem,
)
from engine.appc.properties import PowerProperty


def _powered_ship():
    """Minimal ship: power plant + one 100 pw/s consumer."""
    import App
    ship = App.ShipClass_Create("TestShip")
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(1000.0)
    prop.SetBackupBatteryLimit(500.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)
    consumer = PoweredSubsystem("Sensor Array")
    consumer.SetNormalPowerPerSecond(100.0)
    consumer.TurnOn()
    ship.AddPoweredConsumer(consumer)
    return ship, power, consumer


def _tick(power, seconds, dt=1.0 / 60.0):
    for _ in range(int(seconds / dt)):
        power.Update(dt)


def test_full_power_consumer_gets_factor_one():
    ship, power, consumer = _powered_ship()
    _tick(power, 2.0)
    assert abs(consumer.GetPowerPercentage() - 1.0) < 1e-6
    assert abs(consumer.GetNormalPowerPercentage() - 1.0) < 1e-6


def test_boost_raises_factor_above_one():
    ship, power, consumer = _powered_ship()
    consumer.SetPowerPercentageWanted(1.25)
    _tick(power, 2.0)
    assert abs(consumer.GetNormalPowerPercentage() - 1.25) < 1e-3
    assert abs(consumer.GetPowerPercentage() - 1.0) < 1e-6   # fully fed


def test_starved_consumer_efficiency_drops():
    ship, power, consumer = _powered_ship()
    # Zero the reservoirs and the generator: nothing to draw.
    power.SetMainBatteryPower(0.0)
    power.SetBackupBatteryPower(0.0)
    power.GetProperty().SetPowerOutput(0.0)
    _tick(power, 2.0)
    assert consumer.GetPowerPercentage() == 0.0
    assert consumer.GetNormalPowerPercentage() == 0.0


def test_zero_normal_power_consumer_is_free_and_full():
    ship, power, consumer = _powered_ship()
    consumer.SetNormalPowerPerSecond(0.0)     # e.g. authored warp engines
    _tick(power, 2.0)
    assert consumer.GetNormalPowerPercentage() == 1.0


def test_backup_only_mode_never_touches_main():
    ship, power, consumer = _powered_ship()
    consumer.POWER_MODE = PSM_BACKUP_ONLY     # instance override fine for test
    _tick(power, 1.05)                        # budgets seeded
    main_before = power.GetMainBatteryPower()
    _tick(power, 1.0)
    # Consumer drew only from backup; main moved only by recharge (capped: 0 delta)
    assert power.GetMainBatteryPower() >= main_before


def test_draws_deplete_battery_and_dispensed_counter():
    ship, power, consumer = _powered_ship()
    power.GetProperty().SetPowerOutput(0.0)   # no recharge: watch pure drain
    _tick(power, 3.0)
    assert power.GetMainBatteryPower() < 1000.0
    assert power.GetPowerDispensed() > 0.0


def test_cloak_wants_power_only_while_trying_to_cloak():
    """CloakingSubsystem draws only while trying to cloak, via _wants_power
    (replaces the deleted PowerSubsystem._compute_idle_drain cloak branch)."""
    cloak = CloakingSubsystem("Cloak")
    assert cloak.POWER_MODE == PSM_BACKUP_ONLY
    assert cloak._wants_power() is False       # DECLOAKED
    cloak.StartCloaking()
    assert cloak._wants_power() is True         # CLOAKING
    cloak.InstantCloak()
    assert cloak._wants_power() is True         # CLOAKED
    cloak.StopCloaking()
    assert cloak._wants_power() is False        # DECLOAKING
