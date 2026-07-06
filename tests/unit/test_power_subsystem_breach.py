"""Task 5: destroyed warp core triggers ship death (warp-core breach).

PowerSubsystem.Update must arm a warp-core breach for the parent ship on the
first Update() tick after the subsystem becomes Destroyed (condition == 0),
and must do so at most once (_breach_fired guard).
"""
import pytest

from engine.appc.subsystems import PowerSubsystem, PoweredSubsystem
from engine.appc.properties import PowerProperty
from engine.appc import warp_core_breach


@pytest.fixture(autouse=True)
def _clean():
    warp_core_breach.reset()
    yield
    warp_core_breach.reset()


def _powered_ship():
    """Minimal ship: power plant + one consumer — reuses the helper shape from
    test_power_consumer_draws.py without importing across test files."""
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


def test_destroyed_reactor_arms_breach():
    """Destroying the warp core arms it in warp_core_breach._armed."""
    ship, power, _ = _powered_ship()
    power.SetCondition(0.0)          # makes IsDestroyed() == 1
    power.Update(1.0 / 60.0)
    # The ship must appear in _armed (not yet detonated — just queued).
    assert ship in warp_core_breach._armed or ship in warp_core_breach._breached, (
        "destroyed warp core must arm the ship in warp_core_breach"
    )


def test_destroyed_reactor_arms_only_once():
    """_breach_fired guard: repeated Update() calls arm the ship at most once."""
    ship, power, _ = _powered_ship()
    power.SetCondition(0.0)
    for _ in range(120):
        power.Update(1.0 / 60.0)
    # After draining _armed via advance the ship must be in _breached exactly once.
    # Here we just check it was not queued more than once.
    total = (warp_core_breach._armed.count(ship)
             + (1 if ship in warp_core_breach._breached else 0))
    assert total <= 1, "_breach_fired guard must prevent double-arming"


def test_healthy_reactor_does_not_arm_breach():
    """A healthy (non-destroyed) power subsystem must never arm a breach."""
    ship, power, _ = _powered_ship()
    for _ in range(120):
        power.Update(1.0 / 60.0)
    assert ship not in warp_core_breach._armed
    assert ship not in warp_core_breach._breached


def test_no_parent_ship_does_not_raise():
    """PowerSubsystem with no parent ship must not raise on Update."""
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(1000.0)
    prop.SetMainConduitCapacity(1200.0)
    power.SetProperty(prop)
    power.SetCondition(0.0)
    power.Update(1.0 / 60.0)  # must not raise
