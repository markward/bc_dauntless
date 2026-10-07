"""Drift and spin for rocks: the only motion a rock has.

Ships move through ship_motion's setpoint integrator, which a rock skips
(it has no AI and no engines). Missions give rocks motion with SetVelocity /
SetAngularVelocity (E1M2 CreateMovingAsteroids), which the shim only STORES,
so without this step a scripted rock never moves.

The actual integration is shared with any other setpoint-less ship (see
engine.appc.drift -- same gap, same fix, one implementation).
"""
from engine.appc import drift


def step(rock, dt: float) -> None:
    drift.step(rock, dt)


def tick_all(dt: float) -> None:
    from engine.appc.ship_iter import iter_rocks
    for rock in iter_rocks():
        step(rock, dt)
