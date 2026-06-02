"""Engines-disabled gate end-to-end: ship at full impulse, damage IES to
disable, observe velocity decay, repair, observe recovery. Exercises the
shared _is_offline predicate through ship_motion._step_ship_motion."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.ship_motion import (
    _step_ship_motion, DISABLED_ENGINE_DRAG_FRACTION,
)


def test_disabled_engines_decay_velocity_then_repair_recovers():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ies._max_condition = 100.0
    ies._condition = 100.0
    ies._disabled_percentage = 0.5

    ship._speed_setpoint = (
        6.3, TGPoint3(0.0, 1.0, 0.0),
        PhysicsObjectClass.DIRECTION_MODEL_SPACE,
    )

    # ── 1. Healthy: ramp to full impulse over a few seconds.
    for _ in range(60 * 5):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3) < 1e-3

    # ── 2. Disable IES; verify gate engaged.
    ies.SetCondition(10.0)
    assert ies.IsDisabled() == 1

    # ── 3. Tick 1 second; current_speed decays at drag-fraction rate.
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    decay = 6.3 - ship._current_speed
    expected_decay = 1.5 * DISABLED_ENGINE_DRAG_FRACTION  # 0.15 m/s
    assert abs(decay - expected_decay) < 1e-3, \
        f"expected ~{expected_decay} decay, got {decay}"

    # ── 4. Repair; verify gate releases.
    ies.SetCondition(100.0)
    assert ies.IsDisabled() == 0
    speed_at_repair = ship._current_speed

    # ── 5. Tick 1 second; ramp resumes at MaxAccel rate toward target.
    # Since ship is at 6.15 and target is 6.3, it will ramp to target (limited by target).
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    # Ship should reach target speed (6.3) since ramp step (1.5/60) is large
    # enough to cover the 0.15 gap in one 60-frame tick.
    assert abs(ship._current_speed - 6.3) < 1e-3, \
        f"expected recovery to target 6.3, got {ship._current_speed}"
