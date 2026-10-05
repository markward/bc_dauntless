"""Occlusion overhead benchmark (sensor continuity/occlusion spec, task 2).

can_detect has a dozen callers, some per frame and per torpedo
(sensor_detection.py's module docstring), so adding a major-rock occlusion
test must not make it pathologically slower. This asserts the measured
overhead stays within budget rather than reasoning about it -- see
task-2-brief.md step 4: if the ratio ever exceeds 3.0, that is a STOP
condition for raising the budget, not a license to.
"""
import random
import time

from engine.appc import sensor_detection as sd
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from tests.helpers.rocks import make_major_rock

N_SHIPS = 30
N_ROCKS = 54
SPAN = 800.0
RATIO_BUDGET = 3.0


def _ship(s, rng, name):
    ship = ShipClass_Create("Galaxy")
    ship.SetTranslateXYZ(rng.uniform(-SPAN, SPAN), rng.uniform(-SPAN, SPAN),
                          rng.uniform(-SPAN, SPAN))
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    ship.SetSensorSubsystem(sensors)
    s.AddObjectToSet(ship, name)
    return ship


def _build(seed, with_rocks):
    """A fresh set + N_SHIPS ships, identically positioned for the same seed
    whether or not rocks follow -- the ship-building calls on *rng* run in
    the same order either way, so with/without comparisons share ship
    layout and differ only in the rocks."""
    rng = random.Random(seed)
    s = SetClass()
    ships = [_ship(s, rng, "Ship%d" % i) for i in range(N_SHIPS)]
    if with_rocks:
        for i in range(N_ROCKS):
            at = (rng.uniform(-SPAN, SPAN), rng.uniform(-SPAN, SPAN),
                  rng.uniform(-SPAN, SPAN))
            make_major_rock(s, "Rock%d" % i, at=at, radius_gu=3.0)
    return ships


def _frame(ships) -> None:
    for a in ships:
        for b in ships:
            if a is not b:
                sd.can_detect(a, b)


def _time_one_run(seed, with_rocks) -> float:
    """CPU time (``time.process_time``), not wall clock: this machine runs
    concurrent Claude sessions that compete for the CPU, and wall-clock
    timing picked up that contention as several-fold swings between
    otherwise-identical runs. Process CPU time is what the algorithmic
    overhead this benchmark targets actually costs."""
    from engine.appc import sensor_occlusion
    ships = _build(seed, with_rocks)
    sensor_occlusion.reset()
    sd.reset_concealment_state()
    start = time.process_time()
    _frame(ships)   # cold: builds the rock list + pair cache
    _frame(ships)   # cached
    _frame(ships)   # cached
    return time.process_time() - start


def test_occlusion_overhead_within_budget():
    best_with = min(_time_one_run(1000 + i, True) for i in range(5))
    best_without = min(_time_one_run(1000 + i, False) for i in range(5))
    ratio = (best_with / best_without) if best_without > 0 else float("inf")
    print(
        "\nocclusion bench: with_rocks=%.5fs without_rocks=%.5fs ratio=%.3f"
        % (best_with, best_without, ratio))
    assert ratio <= RATIO_BUDGET, (
        "occlusion overhead ratio %.3f exceeds the %.1f budget "
        "(with_rocks=%.5fs without_rocks=%.5fs) -- STOP, do not raise the budget"
        % (ratio, RATIO_BUDGET, best_with, best_without))
