"""Task 9: pins the whole pipeline to BC's deficit table
(docs/gameplay/ship-subsystems.md:370-386).

Galaxy authored values
  output 1000 / main 250,000 / backup 80,000 / conduits 1200+200

Consumer draws (from sdk/Build/scripts/ships/Hardpoints/galaxy.py):
  impulse 150, sensors 100, shields 400, phasers 300, torpedoes 100,
  warp 0, engineering 1, tractor 600

For the drain-time simulation we enable only the PSM_MAIN_FIRST consumers
(impulse + sensors + shields + phasers + torps + warp + engineering),
whose total draw 1051 < conduit cap 1200 so deficit = draw - output exactly:

  deficit = 1051 - 1000 = 51 pw/s
  drain_time = 250000 / 51 ≈ 4902.0 s

The second assertion checks the fully-loaded deficit (all 7 consumers
including tractor firing at 600 pw/s):

  total_draw = 150 + 100 + 400 + 300 + 100 + 0 + 1 + 600 = 1651
  deficit = 1651 - 1000 = 651  (matches BC reference table row "Galaxy")
"""
import importlib
import sys

import App
import pytest

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (
    PowerSubsystem, PoweredSubsystem, ImpulseEngineSubsystem,
    WarpEngineSubsystem, ShieldSubsystem, RepairSubsystem,
    PSM_BACKUP_FIRST,
)
from engine.appc.properties import (
    PowerProperty, ImpulseEngineProperty, ShieldProperty,
)

# Galaxy authored power values (galaxy.py:763-767)
_OUTPUT          = 1000.0
_MAIN_BATTERY    = 250_000.0
_BACKUP_BATTERY  = 80_000.0
_MAIN_CONDUIT    = 1200.0
_BACKUP_CONDUIT  = 200.0

# Consumer draws (galaxy.py:717-1002)
_DRAW_IMPULSE    = 150.0
_DRAW_SENSORS    = 100.0
_DRAW_SHIELDS    = 400.0
_DRAW_PHASERS    = 300.0
_DRAW_TORPS      = 100.0
_DRAW_WARP       = 0.0
_DRAW_ENGINEERING = 1.0
_DRAW_TRACTOR    = 600.0


def _galaxy_with_authored_power():
    """Build a Galaxy ship with the exact authored power values and all seven
    subsystem consumers registered, using plain PoweredSubsystem instances
    rather than loading the full hardpoint module (which would pull in weapon
    systems and complicate teardown).

    Consumers are registered in BC attachment order (matches the hardpoint
    script order): impulse, sensors, shields, phasers, torps, warp, engineering.
    Tractor is attached last (PSM_MAIN_FIRST, the default) so tests can enable it
    selectively.
    """
    ship = ShipClass_Create("Galaxy")

    # Power plant
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(_OUTPUT)
    prop.SetMainBatteryLimit(_MAIN_BATTERY)
    prop.SetBackupBatteryLimit(_BACKUP_BATTERY)
    prop.SetMainConduitCapacity(_MAIN_CONDUIT)
    prop.SetBackupConduitCapacity(_BACKUP_CONDUIT)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)

    def _consumer(name, draw, mode=None, is_on=True):
        c = PoweredSubsystem(name)
        c.SetNormalPowerPerSecond(draw)
        if mode is not None:
            c.POWER_MODE = mode
        if is_on:
            c.TurnOn()
        ship.AddPoweredConsumer(c)
        return c

    _consumer("Impulse Engines",  _DRAW_IMPULSE)
    _consumer("Sensor Array",     _DRAW_SENSORS)
    _consumer("Shield Generator", _DRAW_SHIELDS)
    _consumer("Phasers",          _DRAW_PHASERS)
    _consumer("Torpedo Tubes",    _DRAW_TORPS)
    _consumer("Warp Engines",     _DRAW_WARP)       # authored 0 pw/s — free
    _consumer("Engineering",      _DRAW_ENGINEERING)
    # Tractor uses default PSM_MAIN_FIRST (spec decision §2); is_on=False in these tests
    tractor = _consumer("Tractor Beam", _DRAW_TRACTOR, is_on=False)

    return ship, tractor


# ── Arithmetic sanity: designed deficit = 651 ────────────────────────────────

def test_galaxy_full_load_deficit_is_651():
    """The BC reference table (ship-subsystems.md:378) quotes Galaxy deficit as
    651 when all seven consumers are at authored draw.  Verify this is
    consistent with the authored numbers baked into this module.

    This is a pure arithmetic assertion — it does not run the simulation.
    """
    total_draw = (_DRAW_IMPULSE + _DRAW_SENSORS + _DRAW_SHIELDS +
                  _DRAW_PHASERS + _DRAW_TORPS + _DRAW_WARP +
                  _DRAW_ENGINEERING + _DRAW_TRACTOR)
    assert total_draw == 1651.0
    deficit = total_draw - _OUTPUT
    assert abs(deficit - 651.0) <= 1.0, (
        f"Galaxy full-load deficit must be 651 ± 1; got {deficit}"
    )


# ── Drain-time simulation ────────────────────────────────────────────────────

def test_galaxy_drain_time_matches_bc():
    """Galaxy with PSM_MAIN_FIRST consumers only (total draw 1051 pw/s,
    deficit 51 pw/s) drains the main battery in 250000/51 ≈ 4902 s.

    The test runs at dt=1.0 (one simulation second per tick) so each Update()
    fires exactly one power interval.  This keeps the iteration count to ~4902
    (< 5000) and eliminates floating-point accumulation skew from sub-second
    ticks.

    Consumers enabled:
        impulse 150 + sensors 100 + shields 400 + phasers 300 + torps 100
        + warp 0 + engineering 1 = 1051 pw/s (all PSM_MAIN_FIRST)

    Total 1051 < main conduit cap 1200 → all demand is met every tick.
    Net battery change per tick = output - draw = 1000 - 1051 = -51 (drain).
    Tractor is left OFF so conduit complexity is avoided.
    """
    ship, _tractor = _galaxy_with_authored_power()
    power = ship.GetPowerSubsystem()

    # PSM_MAIN_FIRST consumers total draw
    active_draw = (_DRAW_IMPULSE + _DRAW_SENSORS + _DRAW_SHIELDS +
                   _DRAW_PHASERS + _DRAW_TORPS + _DRAW_WARP + _DRAW_ENGINEERING)
    assert active_draw == 1051.0

    deficit = active_draw - _OUTPUT   # = 51.0
    assert deficit > 0.0, "test requires a genuine power deficit"

    expected_drain_time = _MAIN_BATTERY / deficit   # = 250000 / 51 ≈ 4902.0 s

    # Precondition: SetProperty fills batteries (BC spawn)
    assert power.GetMainBatteryPower() == 250000.0, (
        "main battery must start at 250000.0 (BC spawn default)"
    )

    dt = 1.0   # one tick = one second; interval fires on every Update call
    seconds = 0.0
    max_seconds = expected_drain_time * 2.0   # safety cap (never reached)

    while power.GetMainBatteryPower() > 0.0 and seconds < max_seconds:
        power.Update(dt)
        seconds += dt

    assert seconds < max_seconds, (
        "simulation ran past the safety cap — something is wrong with the drain loop"
    )
    assert abs(seconds - expected_drain_time) / expected_drain_time < 0.05, (
        f"drain time {seconds:.1f} s must be within 5% of expected "
        f"{expected_drain_time:.1f} s (deficit={deficit} pw/s)"
    )


# ── q10 instrumented-ground-truth replication ────────────────────────────────

def test_q10_red_alert_sliders_125_tractor_held_split():
    """Reproduce the q10 instrumented measurement (Galaxy, RED alert, all seven
    sliders at 1.25, tractor held) and pin the concurrent drain split:

        main    ~= -800/s
        backup  ~= -113.75/s

    (tools/probes/results/q10_battery_drain.txt; the adjudicated s10->s20 window
    measured main ~= -789/s, backup ~= -110/s; the exact model-derived figures
    below are -800 / -113.75 within 2%.)

    Full decomposition (Galaxy authored: output 1000/s, main conduit cap 1200/s,
    backup conduit cap 200/s; conduit consumer draws sum to 1051/s):

      1. Conduit slider demand at 1.25:
             1051 * 1.25                       = 1313.75 /s
      2. Main conduit caps at its rated 1200/s; the overflow spills to backup:
             main conduit draw                 = 1200.00 /s
             backup conduit draw (overflow)    = 1313.75 - 1200 = 113.75 /s
      3. The warp core outputs 1000/s, refilling the MAIN battery first:
             net main from conduits            = 1000 (in) - 1200 (out) = -200 /s
             net backup from conduits          =            - 113.75    /s
      4. The TRACTOR draws its 600/s DIRECTLY from the main battery, bypassing
         the conduits and UNSCALED by the 1.25 slider (q10: measured 600 flat,
         not 600*1.25 = 750):
             net main total                    = -200 - 600  = -800.00 /s
             net backup total                  =              -113.75 /s

    The batteries start full (250k / 80k) so no clamp fires during the window;
    this is the pure sub-ceiling regime the getter change does not perturb.
    """
    from engine.appc.subsystems import (
        TractorBeamSystem, PowerSubsystem, PoweredSubsystem,
    )
    from engine.appc.properties import PowerProperty

    ship = ShipClass_Create("Galaxy")

    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(_OUTPUT)
    prop.SetMainBatteryLimit(_MAIN_BATTERY)
    prop.SetBackupBatteryLimit(_BACKUP_BATTERY)
    prop.SetMainConduitCapacity(_MAIN_CONDUIT)
    prop.SetBackupConduitCapacity(_BACKUP_CONDUIT)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)

    # Seven conduit consumers, all sliders at 1.25 (PSM_MAIN_FIRST default).
    for name, draw in (
        ("Impulse Engines",  _DRAW_IMPULSE),
        ("Sensor Array",     _DRAW_SENSORS),
        ("Shield Generator", _DRAW_SHIELDS),
        ("Phasers",          _DRAW_PHASERS),
        ("Torpedo Tubes",    _DRAW_TORPS),
        ("Warp Engines",     _DRAW_WARP),
        ("Engineering",      _DRAW_ENGINEERING),
    ):
        c = PoweredSubsystem(name)
        c.SetNormalPowerPerSecond(draw)
        c.SetPowerPercentageWanted(1.25)     # red-alert slider boost
        c.TurnOn()
        ship.AddPoweredConsumer(c)

    # Tractor: direct main-battery siphon, held (DRAWS_DIRECT_FROM_MAIN).
    tractor = TractorBeamSystem("Tractor Beam")
    tractor.SetNormalPowerPerSecond(_DRAW_TRACTOR)
    tractor.SetPowerPercentageWanted(1.25)   # slider does NOT scale the siphon
    tractor.TurnOn()
    tractor._any_child_firing = lambda: True  # beam held
    ship.AddPoweredConsumer(tractor)

    # Seed the first interval budget, then measure a clean window well before any
    # battery empties.  dt=1.0 -> one interval per Update.
    power.Update(1.0)
    main0 = power.GetMainBatteryPower()
    backup0 = power.GetBackupBatteryPower()
    window = 10
    for _ in range(window):
        power.Update(1.0)
    main_rate = (power.GetMainBatteryPower() - main0) / window
    backup_rate = (power.GetBackupBatteryPower() - backup0) / window

    assert abs(main_rate - (-800.0)) <= 0.02 * 800.0, (
        f"main drain must be ~-800/s (q10); got {main_rate:.2f}/s"
    )
    assert abs(backup_rate - (-113.75)) <= 0.02 * 113.75, (
        f"backup drain must be ~-113.75/s (q10 overflow); got {backup_rate:.2f}/s"
    )

    # q10 Q1: backup drains CONCURRENTLY with main (overflow model), not last.
    assert backup_rate < 0.0
    assert power.GetMainBatteryPower() > 0.0   # main still holds charge
