"""Torpedo reload must BANK progress across a mid-reload power change.

BC (weapon-firing-mechanics.md §2.6, the 2026-07-16 rewrite): TorpedoTube::Update
advances each cooling slot's timer by ``NormalPowerPercentage x dt`` every tick and
reloads when the timer exceeds ReloadDelay.  It is an INTEGRATOR: progress already
banked at one power level is never re-valued when the power level changes.

The pre-fix implementation stored a cooldown START stamp and compared
``now - start >= reload_delay / factor``.  That recomputes the WHOLE elapsed
interval against the CURRENT factor every call, so a power change mid-reload
retroactively rescales already-banked progress:

  * power DROP  -> the nearly-loaded tube snaps back toward empty (progress lost)
  * power RISE  -> slow early cooling is over-credited at the new higher factor
                   (tube finishes far too early)

These two tests pin both directions.  Reload runs on the GAME clock
(App.g_kTimerManager._time), driven directly here as in test_torpedo_tube_reload.py.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


@pytest.fixture
def clock():
    App.g_kTimerManager._time = 0.0

    def _set(t: float) -> None:
        App.g_kTimerManager._time = float(t)

    yield _set
    App.g_kTimerManager._time = 0.0


def _torpedo_fixture():
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    system._power_factor = 1.0

    tube = TorpedoTube("Tube1")
    tube._max_ready = 1
    tube._num_ready = 1
    tube._reload_delay = 40.0
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return system, tube


def test_power_drop_mid_reload_banks_prior_progress(clock):
    """39 s of FULL power then 10% power: the 39 s must be banked.

    BC banks 39 s of full-rate progress; at 10% it then needs only
    (40 - 39) / 0.1 = 10 more seconds, so the tube is loaded by t = 49.
    The buggy divisor formula recomputes delay = 40 / 0.1 = 400 s against the
    full elapsed time and does not reload until t = 400 -- it threw away the
    39 s of banked progress.
    """
    system, tube = _torpedo_fixture()

    clock(0.0)
    tube.Fire()
    assert tube.GetNumReady() == 0

    # Full-power cooling phase: bank ~39 s of progress at factor 1.0.
    system._power_factor = 1.0
    clock(39.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 0, "39 s < 40 s: not loaded yet"

    # Power collapses to 10%.  11 more seconds at 0.1 adds 1.1 -> 40.1 >= 40.
    system._power_factor = 0.1
    clock(50.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 1, (
        "banked 39 s of full-power reload progress must persist across the "
        "power drop -- the tube must not snap back toward empty"
    )


def test_power_rise_mid_reload_does_not_overcredit(clock):
    """39 s of 10% power then full power: the slow early time is NOT re-valued.

    BC banks 39 x 0.1 = 3.9 effective seconds; at full power it then needs
    40 - 3.9 = 36.1 more seconds.  At t = 40 only 3.9 + 1.0 = 4.9 is banked,
    nowhere near 40, so the tube must NOT be loaded.  The buggy divisor formula
    recomputes delay = 40 / 1.0 = 40 against the full 40 s elapsed and reloads
    immediately -- retroactively crediting the slow early cooling at full rate.
    """
    system, tube = _torpedo_fixture()

    clock(0.0)
    tube.Fire()
    assert tube.GetNumReady() == 0

    # Low-power cooling phase: bank only ~3.9 effective seconds.
    system._power_factor = 0.1
    clock(39.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 0

    # Power restored to full.  One more second adds 1.0 -> 4.9, far below 40.
    system._power_factor = 1.0
    clock(40.0)
    tube.UpdateReload(0.0)
    assert tube.GetNumReady() == 0, (
        "slow 10%-power early cooling must not be retroactively over-credited "
        "at the restored full rate"
    )
