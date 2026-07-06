"""Tractor beam is a DIRECT main-battery siphon (q10 ground truth).

Instrumented experiment q10 (tools/probes/results/q10_battery_drain.txt,
docs/instrumented_experiments/2026-07-06-battery-drain-order.md) measured the
original BC engine draining a Galaxy at RED alert with all sliders 1.25 while a
tractor was held: main -800/s, backup -113.75/s, concurrently, sliders never
throttled.

Decomposition (see the keystone integration test for the full derivation):
the tractor's per-second draw comes DIRECTLY from the main battery, bypassing
the conduit budget and UNSCALED by the power-percentage slider (measured 600
flat with sliders at 1.25, NOT 600*1.25=750). This module pins the mechanism
in isolation; test_power_reference_values.py pins the full split.
"""
from engine.appc.subsystems import PowerSubsystem
from engine.appc.weapon_subsystems import TractorBeamSystem
from engine.appc.properties import PowerProperty


def _power():
    ps = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(250000.0)
    prop.SetBackupBatteryLimit(80000.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    ps.SetProperty(prop)
    return ps


def _firing_tractor(normal_power=600.0):
    """A TractorBeamSystem that reports a held beam (so _wants_power is True)
    without wiring a full emitter — patch _any_child_firing directly."""
    t = TractorBeamSystem("Tractor Beam")
    t.SetNormalPowerPerSecond(normal_power)
    t.TurnOn()
    t._any_child_firing = lambda: True
    return t


def test_tractor_draws_direct_from_main_battery_bypassing_conduit():
    """A held tractor drains the main battery even before the conduit budget is
    seeded (direct StealPower path, not the per-interval conduit budget)."""
    ps = _power()
    t = _firing_tractor()
    main_before = ps.GetMainBatteryPower()
    # dt of 1s: the conduit budget for this frame is still zero (Update hasn't
    # seeded it via the interval tick), yet the direct siphon still pulls.
    t._update_power(1.0, ps)
    assert ps.GetMainBatteryPower() == main_before - 600.0


def test_tractor_draw_is_unscaled_by_power_percentage():
    """q10: sliders at 1.25 measured a flat 600/s tractor draw, NOT 750/s.
    The direct siphon uses normal_power*dt, unscaled by _power_percentage_wanted.
    """
    ps = _power()
    t = _firing_tractor()
    t.SetPowerPercentageWanted(1.25)
    main_before = ps.GetMainBatteryPower()
    t._update_power(1.0, ps)
    assert ps.GetMainBatteryPower() == main_before - 600.0  # flat, not 750


def test_tractor_never_touches_backup_battery():
    """The tractor binds to the main battery only (q10 power-source stack:
    tractor -> Main Battery, cannot reach reserve)."""
    ps = _power()
    t = _firing_tractor()
    backup_before = ps.GetBackupBatteryPower()
    # Drain main dry, then keep drawing: backup must never move.
    ps.SetMainBatteryPower(100.0)
    t._update_power(1.0, ps)   # wants 600, only 100 in main
    assert ps.GetMainBatteryPower() == 0.0
    assert ps.GetBackupBatteryPower() == backup_before


def test_tractor_efficiency_reports_starvation():
    """received/base drives GetPowerPercentage so the StopFiring starvation gate
    still engages: main dry -> efficiency 0 while power is still wanted."""
    ps = _power()
    t = _firing_tractor()
    ps.SetMainBatteryPower(0.0)
    t._update_power(1.0, ps)
    assert t.GetPowerPercentage() == 0.0        # received/wanted
    assert t.GetNormalPowerWanted() == 600.0    # still wants power (gate input)


def test_tractor_reports_full_demand_for_powerdisplay():
    """_power_wanted must still report the demand for PowerDisplay math even
    though the draw path is the direct steal."""
    ps = _power()
    t = _firing_tractor()
    t._update_power(1.0, ps)
    assert t.GetPowerWanted() == 600.0


def test_idle_tractor_draws_nothing():
    """A powered-but-not-firing tractor siphons nothing (siphon-while-held)."""
    ps = _power()
    t = TractorBeamSystem("Tractor Beam")
    t.SetNormalPowerPerSecond(600.0)
    t.TurnOn()
    t._any_child_firing = lambda: False
    main_before = ps.GetMainBatteryPower()
    t._update_power(1.0, ps)
    assert ps.GetMainBatteryPower() == main_before
    assert t.GetPowerWanted() == 0.0
