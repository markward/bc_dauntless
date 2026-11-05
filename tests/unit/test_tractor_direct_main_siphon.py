"""Tractor beam is a DIRECT main-battery siphon (q10 ground truth).

Instrumented experiment q10 (tools/probes/results/q10_battery_drain.txt,
docs/reference/instrumented_experiments/2026-07-06-battery-drain-order.md) measured the
original BC engine draining a Galaxy at RED alert with all sliders 1.25 while a
tractor was held: main -800/s, backup -113.75/s, concurrently, sliders never
throttled.

Decomposition (see the keystone integration test for the full derivation):
the tractor's per-second draw comes DIRECTLY from the main battery, bypassing
the conduit budget and UNSCALED by the power-percentage slider (measured 600
flat with sliders at 1.25, NOT 600*1.25=750). This module pins the mechanism
in isolation, through the native power pump (the stage is native only);
test_power_reference_values.py pins the full split.
"""
from engine.appc.ships import ShipClass
from engine.appc.subsystems import PowerSubsystem
from engine.appc.weapon_subsystems import TractorBeam, TractorBeamSystem
from engine.appc.properties import PowerProperty
from tests.helpers.subsystem_stage import tick_subsystems


def _power():
    """A plant with no output, so a tick's interval recharges nothing and
    only the tractor moves the batteries."""
    ps = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(0.0)
    prop.SetMainBatteryLimit(250000.0)
    prop.SetBackupBatteryLimit(80000.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    ps.SetProperty(prop)
    return ps


def _tractor(firing, normal_power=600.0):
    """A TractorBeamSystem with one beam, held (`firing`) or not: the pump's
    _wants_power reads the beams' _firing."""
    t = TractorBeamSystem("Tractor Beam")
    t.SetNormalPowerPerSecond(normal_power)
    t.TurnOn()
    beam = TractorBeam("Tractor Beam 1")
    t.AddChildSubsystem(beam)
    beam._firing = firing
    return t


def _firing_tractor(normal_power=600.0):
    return _tractor(True, normal_power)


def _pump(ps, t, dt=1.0):
    """One stage of `dt` over a ship holding the plant and the tractor (its
    only consumer)."""
    ship = ShipClass()
    ship.SetName("Tug")
    ship.SetPowerSubsystem(ps)
    ship.SetTractorBeamSystem(t)
    tick_subsystems([ship], dt)


def test_tractor_draws_direct_from_main_battery_bypassing_conduit():
    """A held tractor drains the main battery straight past the conduit
    budget (direct StealPower path): the main conduit is capped far below
    the draw, yet the full 600 leaves main, the conduit budget is untouched
    and nothing is counted as dispensed through it."""
    ps = _power()
    ps.GetProperty().SetMainConduitCapacity(10.0)     # far below 600/s
    t = _firing_tractor()
    main_before = ps.GetMainBatteryPower()
    _pump(ps, t)
    assert ps.GetMainBatteryPower() == main_before - 600.0
    # The interval seeded the budget from the capped capacity; the steal
    # did not spend it.
    assert ps._main_conduit_current == 10.0
    assert ps.GetPowerDispensed() == 0.0


def test_tractor_draw_is_unscaled_by_power_percentage():
    """q10: sliders at 1.25 measured a flat 600/s tractor draw, NOT 750/s.
    The direct siphon uses normal_power*dt, unscaled by _power_percentage_wanted.
    """
    ps = _power()
    t = _firing_tractor()
    t.SetPowerPercentageWanted(1.25)
    main_before = ps.GetMainBatteryPower()
    _pump(ps, t)
    assert ps.GetMainBatteryPower() == main_before - 600.0  # flat, not 750


def test_tractor_never_touches_backup_battery():
    """The tractor binds to the main battery only (q10 power-source stack:
    tractor -> Main Battery, cannot reach reserve)."""
    ps = _power()
    t = _firing_tractor()
    backup_before = ps.GetBackupBatteryPower()
    # Drain main dry, then keep drawing: backup must never move.
    ps.SetMainBatteryPower(100.0)
    _pump(ps, t)   # wants 600, only 100 in main
    assert ps.GetMainBatteryPower() == 0.0
    assert ps.GetBackupBatteryPower() == backup_before


def test_tractor_efficiency_reports_starvation():
    """received/base drives GetPowerPercentage so the StopFiring starvation gate
    still engages: main dry -> efficiency 0 while power is still wanted."""
    ps = _power()
    t = _firing_tractor()
    ps.SetMainBatteryPower(0.0)
    _pump(ps, t)
    assert t.GetPowerPercentage() == 0.0        # received/wanted
    assert t.GetNormalPowerWanted() == 600.0    # still wants power (gate input)


def test_tractor_reports_full_demand_for_powerdisplay():
    """_power_wanted must still report the demand for PowerDisplay math even
    though the draw path is the direct steal."""
    ps = _power()
    t = _firing_tractor()
    _pump(ps, t)
    assert t.GetPowerWanted() == 600.0


def test_idle_tractor_draws_nothing():
    """A powered-but-not-firing tractor siphons nothing (siphon-while-held)."""
    ps = _power()
    t = _tractor(False)
    main_before = ps.GetMainBatteryPower()
    _pump(ps, t)
    assert ps.GetMainBatteryPower() == main_before
    assert t.GetPowerWanted() == 0.0
