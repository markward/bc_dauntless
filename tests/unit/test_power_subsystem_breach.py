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


def test_destroyed_reactor_breaches_ship():
    """Manual p.16: reaching 0% warp core destroys the SHIP — even with no
    hull cascade in play (direct core destruction in isolation).  detonate()
    skips the source ship, so PowerSubsystem must start the death sequence
    itself via ship_death.begin()."""
    from engine.appc import ship_death
    ship, power, _ = _powered_ship()
    ship_death.reset()
    try:
        power.SetCondition(0.0)
        for _ in range(120):
            power.Update(1.0 / 60.0)
        assert ship.IsDying() or ship.IsDead(), (
            "a destroyed warp core must destroy the ship itself"
        )
    finally:
        ship_death.reset()


def test_destroyed_reactor_arms_only_once():
    """_breach_fired guard: repeated Update() calls arm the ship exactly once."""
    ship, power, _ = _powered_ship()
    power.SetCondition(0.0)
    for _ in range(120):
        power.Update(1.0 / 60.0)
    assert warp_core_breach._armed.count(ship) == 1, (
        "_breach_fired guard must prevent double-arming"
    )


def test_breach_does_not_restart_death_of_dying_ship():
    """A ship already dying (e.g. hull-zero cascade already ran
    ship_death.begin) must not have its death sequence restarted by the
    reactor guard — begin() is idempotent, and the guard must not enqueue a
    second sequence."""
    from engine.appc import ship_death
    ship, power, _ = _powered_ship()
    ship_death.reset()
    try:
        ship_death.begin(ship)
        assert ship.IsDying()
        entries_before = len(ship_death._active)
        power.SetCondition(0.0)
        power.Update(1.0 / 60.0)
        assert len(ship_death._active) == entries_before, (
            "breach trigger must not enqueue a second death sequence"
        )
    finally:
        ship_death.reset()


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


def test_non_targetable_power_plant_does_not_arm_breach():
    """An asteroid carries a hidden Power Plant with SetTargetable(0). When
    the death cascade zeroes it, PowerSubsystem.Update must NOT arm a
    warp-core breach (and must NOT start ship death).  This mirrors the
    identical gate in objects.py:_route_zero_crossing.

    The _breach_fired flag is still set (so we do not re-evaluate every
    tick), but the arm + ship_death paths must be skipped.
    """
    from engine.appc import ship_death
    ship, power, _ = _powered_ship()
    ship_death.reset()
    try:
        # Mark the power plant as non-targetable — exactly what asteroid
        # hardpoints do (SetTargetable(0)).
        power.SetTargetable(0)
        power.SetCondition(0.0)   # IsDestroyed() == 1
        for _ in range(120):
            power.Update(1.0 / 60.0)
        # No breach must be armed or detonated.
        assert ship not in warp_core_breach._armed, (
            "non-targetable power plant must not arm warp_core_breach"
        )
        assert ship not in warp_core_breach._breached, (
            "non-targetable power plant must not detonate warp_core_breach"
        )
        # Ship must NOT be dying or dead (no ship_death.begin called).
        assert not (ship.IsDying() or ship.IsDead()), (
            "non-targetable power plant must not trigger ship death"
        )
    finally:
        ship_death.reset()
