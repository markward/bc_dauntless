"""B: a cloaked ship draws its full CLOAK_RESERVE_DRAIN_PER_SECOND straight from
the backup reserve (bypassing the conduit throttle), so sustained cloak depletes
the reserve unless the reactor keeps up. Healthy reactor sustains; damaged one is
flushed out by Step 0's reserve guard. See
docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md."""
import App
from engine.appc.subsystems import CloakingSubsystem, PowerSubsystem
from engine.appc.properties import PowerProperty


def _powered_ship(output=1500.0):
    ship = App.ShipClass_Create("TestShip")
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(output)
    prop.SetMainBatteryLimit(100000.0)
    prop.SetBackupBatteryLimit(200000.0)
    prop.SetMainConduitCapacity(1700.0)
    prop.SetBackupConduitCapacity(300.0)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)
    return ship, power


def _cloak_on(ship, drain=1000.0):
    cloak = CloakingSubsystem("Cloaking Device")
    cloak.CLOAK_RESERVE_DRAIN_PER_SECOND = drain
    ship.AddPoweredConsumer(cloak)
    return cloak


def test_cloak_drains_reserve_at_full_rate_not_conduit_throttled():
    # Backup conduit is 300/s; the direct-from-reserve draw must ignore it and
    # pull the full 1000/s. Reactor off so we measure pure draw.
    ship, power = _powered_ship(output=0.0)
    cloak = _cloak_on(ship, drain=1000.0)
    power.SetBackupBatteryPower(50000.0)
    cloak.InstantCloak()
    for _ in range(60):                       # 1 s at 60 Hz
        power.Update(1.0 / 60.0)
    drained = 50000.0 - power.GetBackupBatteryPower()
    assert 950.0 <= drained <= 1050.0         # ~1000/s, not ~300/s


def test_healthy_reactor_sustains_cloak():
    # Reactor 1500/s > drain 1000/s: refill exceeds drain, so a reserve that
    # would otherwise empty within the run must instead hold (and even climb).
    # Main battery is seeded FULL so every watt of reactor output spills
    # straight into the backup reserve (_add_power_to_batteries fills main
    # first) -- otherwise "reactor health" would be inert to the reserve.
    ship, power = _powered_ship(output=1500.0)
    cloak = _cloak_on(ship, drain=1000.0)
    power.SetMainBatteryPower(power.GetMainBatteryLimit())   # main full -> spill to backup
    power.SetBackupBatteryPower(3000.0)   # low reserve: would drain dry in 3s without refill
    cloak.StartCloaking()
    for _ in range(600):                      # 10 s
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)
    assert cloak.IsTryingToCloak() == 1, (
        "healthy reactor (1500/s) out-refills the 1000/s drain and must sustain cloak"
    )
    assert power.GetBackupBatteryPower() > 3000.0, (
        "reserve should have net-gained over the run, proving refill (not just non-depletion)"
    )


def test_damaged_reactor_depletes_reserve_and_forces_decloak():
    # Reactor 1500 * 30% condition = 450/s < drain 1000/s: refill is active
    # but falls behind the drain, so the reserve empties EVEN WITH the reactor
    # feeding it, and Step 0's guard force-decloaks. Main battery seeded FULL
    # so the (reduced) reactor output still spills straight into backup.
    ship, power = _powered_ship(output=1500.0)
    power.SetCondition(power.GetMaxCondition() * 0.30)   # damaged reactor -> ~450/s output
    cloak = _cloak_on(ship, drain=1000.0)
    power.SetMainBatteryPower(power.GetMainBatteryLimit())   # main full -> spill to backup
    power.SetBackupBatteryPower(2000.0)                  # small reserve
    cloak.StartCloaking()
    for _ in range(600):                                # up to 10 s
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)
    assert cloak.IsTryingToCloak() == 0, (
        "damaged reactor's refill (~450/s) falls behind the 1000/s drain, "
        "so the reserve must still empty and force a decloak"
    )
