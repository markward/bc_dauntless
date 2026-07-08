"""Task 9: cloak power starvation — backup battery dry → forced decloak.

When the backup battery is fully depleted (PSM_BACKUP_ONLY cloak draws
nothing → efficiency 0.0 < AUTO_DECLOAK_EFFICIENCY threshold) the
CloakingSubsystem must force itself back to DECLOAKED.

Reference: docs/original_game_reference/gameplay/ship-subsystems.md:187-189.
"""
import App
import pytest

from engine.appc.subsystems import (
    CloakingSubsystem, PowerSubsystem, PoweredSubsystem, PSM_BACKUP_ONLY,
)
from engine.appc.properties import PowerProperty


def _powered_ship():
    """Minimal ship: power plant, cloak attached as a consumer.

    Mirrors the helper in test_power_consumer_draws.py — authored here so no
    cross-file import is needed.  The power property deliberately uses the
    Galaxy authored values (output 1000, main 250k, backup 80k,
    conduits 1200/200).
    """
    ship = App.ShipClass_Create("TestShip")
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(250000.0)
    prop.SetBackupBatteryLimit(80000.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)
    return ship, power


# ── Core starvation test ──────────────────────────────────────────────────────

def test_cloak_drops_when_backup_battery_empties():
    """A cloaked ship with an empty backup battery and no recharge is
    forced to decloak once the starvation check triggers (efficiency < 0.25
    for a non-zero-draw cloak).

    The test drives 10 s of ticks (600 × 1/60 s); the backup battery
    starts at 10 J and the reactor is disabled so there is no recharge.
    Within that window the backup battery drains to zero, efficiency drops
    to 0.0, and _force_decloak() must engage.
    """
    ship, power = _powered_ship()
    cloak = CloakingSubsystem("Cloaking Device")
    cloak.SetNormalPowerPerSecond(1000.0)
    ship.AddPoweredConsumer(cloak)
    # Nearly-dry backup; no recharge.
    power.SetBackupBatteryPower(10.0)
    power.GetProperty().SetPowerOutput(0.0)

    cloak.StartCloaking()
    assert cloak.IsTryingToCloak() == 1   # sanity: we are trying

    for _ in range(600):          # 10 s at 60 Hz
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)

    assert cloak.IsTryingToCloak() == 0, (
        "cloak must auto-decloak when backup battery is exhausted"
    )


def test_free_cloak_is_never_force_decloaked():
    """A cloak with CLOAK_RESERVE_DRAIN_PER_SECOND == 0.0 is 'free' — it makes
    no direct-from-reserve draw at all (see CloakingSubsystem._update_power).
    The starvation guard must NOT trigger for free cloaks even when the
    backup battery is completely empty, because a zero-drain cloak can never
    be supply-starved by definition.
    """
    ship, power = _powered_ship()
    cloak = CloakingSubsystem("Free Cloak")
    cloak.CLOAK_RESERVE_DRAIN_PER_SECOND = 0.0   # free (no direct-from-reserve draw)
    cloak.SetNormalPowerPerSecond(0.0)   # legacy field; no longer read by the B-path
    ship.AddPoweredConsumer(cloak)
    power.SetBackupBatteryPower(0.0)
    power.SetMainBatteryPower(0.0)
    power.GetProperty().SetPowerOutput(0.0)

    cloak.InstantCloak()

    for _ in range(600):
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)

    assert cloak.IsTryingToCloak() == 1, (
        "zero-draw (free) cloak must NOT be force-decloaked by the starvation guard"
    )


def test_full_backup_battery_does_not_decloak():
    """A cloaked ship with a full backup battery and output >= draw must
    remain cloaked: the reserve never runs dry.

    The power subsystem is pre-seeded for 2 seconds before the cloak starts
    so the conduit budgets are non-zero when the starvation check first runs.
    This mirrors real gameplay: a ship's EPS conduits are seeded from the
    moment it spawns, long before the cloak engages.
    """
    ship, power = _powered_ship()
    cloak = CloakingSubsystem("Cloaking Device")
    cloak.SetNormalPowerPerSecond(100.0)    # draw 100, backup cap 200 → fully fed
    ship.AddPoweredConsumer(cloak)
    # Full batteries, normal output
    power.SetBackupBatteryPower(80000.0)

    # Pre-seed the power conduits (2 intervals) before engaging the cloak,
    # so the first starvation check sees a real conduit budget rather than
    # the zero-budget warm-up window.
    for _ in range(120):
        power.Update(1.0 / 60.0)

    cloak.StartCloaking()

    for _ in range(600):
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)

    assert cloak.IsTryingToCloak() == 1, (
        "well-fed cloak (full backup battery) must NOT be force-decloaked"
    )


def test_high_draw_cloak_with_full_reserve_stays_cloaked():
    """Regression (2026-07-07 'cloak then immediately decloak'): a Warbird-style
    cloak draws 1000 pw/s but the backup conduit only supplies ~200 pw/s, so the
    per-frame power *efficiency* oscillates to 0 as the per-second conduit budget
    is spent and refills — and is 0 for the whole first-second warm-up. The old
    guard keyed on that instantaneous efficiency and force-decloaked on frame 1
    even though the reserve BATTERY was full. The starvation guard must key on
    the reserve level, not conduit efficiency, so a full-reserve ship stays
    cloaked despite a heavily throttled conduit.

    No conduit pre-seed and no InstantCloak here — the ship must survive the
    warm-up window from a cold StartCloaking, exactly as it does in game.
    """
    ship, power = _powered_ship()
    cloak = CloakingSubsystem("Cloaking Device")
    cloak.SetNormalPowerPerSecond(1000.0)   # >> backup conduit 200 → eff oscillates to 0
    ship.AddPoweredConsumer(cloak)
    power.SetBackupBatteryPower(80000.0)     # full reserve, reactor refills it

    cloak.StartCloaking()

    for _ in range(600):                     # 10 s from a cold start
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)

    assert cloak.IsTryingToCloak() == 1, (
        "full-reserve cloak must stay cloaked despite conduit-throttled efficiency"
    )
    assert power.GetBackupBatteryPower() > 0.0, "reserve should not have emptied"


class _DeclOakCapture:
    """Module-level handler class so _resolve_handler can find it.

    The AddBroadcastPythonFuncHandler API resolves handlers by
    'module.func_name', so the function must be importable from this module's
    namespace — inner functions inside a test don't qualify.  The pattern
    mirrors test_cloaking_subsystem.py."""

    def __init__(self):
        self.decloaks = []


def _capture_decloak(handler, event):
    handler.decloaks.append(event.GetSource())


def test_force_decloak_fires_decloak_completed_event():
    """When the starvation guard fires for a CLOAKED ship, it must broadcast
    ET_DECLOAK_COMPLETED (same as the existing offline path) so mission scripts
    that listen for the event know the ship is visible again.
    """
    cap = _DeclOakCapture()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_DECLOAK_COMPLETED, cap,
        __name__ + "._capture_decloak",
    )

    ship, power = _powered_ship()
    cloak = CloakingSubsystem("Cloaking Device")
    cloak.SetNormalPowerPerSecond(500.0)
    ship.AddPoweredConsumer(cloak)
    power.SetBackupBatteryPower(5.0)
    power.GetProperty().SetPowerOutput(0.0)

    cloak.InstantCloak()   # jump straight to CLOAKED (was_cloaked=True path)

    for _ in range(600):
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)

    assert cloak.IsCloaked() == 0, "starvation must drop out of CLOAKED"
    # The event should have fired at least once.
    assert len(cap.decloaks) >= 1, (
        "ET_DECLOAK_COMPLETED must fire when the starvation guard decloaks a CLOAKED ship"
    )
