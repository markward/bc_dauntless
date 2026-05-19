"""Unit tests for engine.appc.ship_motion.tick_all_ship_motion.

Each test constructs a ship in its own SetClass so iter_ships() picks
it up, then calls tick_all_ship_motion(dt) directly. Conftest's
reset_app_state fixture clears g_kSetManager between tests.
"""
import math

import pytest

import App
from engine.appc.math import (
    TGPoint3, TGMatrix3,
    TGPoint3_GetModelForward, TGPoint3_GetModelUp,
)
from engine.appc.ship_motion import tick_all_ship_motion
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def fresh_set_manager():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()


def _place(ship, name="t"):
    """Drop a ship into a fresh SetClass so iter_ships sees it."""
    pSet = App.SetClass_Create()
    pSet.SetName(name)
    pSet.AddObjectToSet(ship, name + "_obj")
    App.g_kSetManager._sets[name] = pSet


def test_no_setpoints_is_noop():
    """Ship with no setpoints written must be left strictly alone."""
    ship = ShipClass()
    _place(ship)
    ship.SetTranslateXYZ(10.0, 20.0, 30.0)
    tick_all_ship_motion(1.0)
    p = ship.GetTranslate()
    assert (p.x, p.y, p.z) == (10.0, 20.0, 30.0)


def test_set_impulse_aliases_set_speed():
    """SetImpulse(s, dir, frame) records the same _speed_setpoint as
    SetSpeed — GoForward.Update calls SetImpulse, not SetSpeed."""
    ship = ShipClass()
    fwd = TGPoint3_GetModelForward()
    ship.SetImpulse(42.0, fwd, App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    sp = ship.GetSpeedSetpoint()
    assert sp[0] == 42.0
    assert sp[2] == App.PhysicsObjectClass.DIRECTION_MODEL_SPACE


def test_set_speed_defensively_copies_direction():
    """If a caller mutates the direction vec after SetSpeed returns,
    the recorded setpoint must NOT change. Prevents the Risk #2
    aliasing bug from the design spec."""
    ship = ShipClass()
    fwd = TGPoint3(0.0, 1.0, 0.0)
    ship.SetSpeed(10.0, fwd, App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    fwd.SetXYZ(99.0, 99.0, 99.0)
    sp = ship.GetSpeedSetpoint()
    recorded_dir = sp[1]
    assert (recorded_dir.x, recorded_dir.y, recorded_dir.z) == (0.0, 1.0, 0.0)


def test_linear_ramp_snaps_with_fallback_accel():
    """Test ship has no IES populated; FALLBACK_MAX_ACCEL=1e9 makes
    the ramp snap to target on the first tick. After one tick with
    SetImpulse(50, fwd, MODEL_SPACE), _current_speed should equal
    50.0 and the position should advance by ~50 * dt along +Y."""
    ship = ShipClass()
    _place(ship)
    ship.SetImpulse(50.0, TGPoint3_GetModelForward(),
                    App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    # Zero out the angular setpoint explicitly so the integrator picks
    # up motion (avoids the no-setpoint early-out path).
    v0 = TGPoint3(0.0, 0.0, 0.0)
    ship.SetTargetAngularVelocityDirect(v0)

    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)

    assert ship._current_speed == pytest.approx(50.0)
    p = ship.GetTranslate()
    assert p.y == pytest.approx(50.0 * dt)
    assert p.x == pytest.approx(0.0)
    assert p.z == pytest.approx(0.0)


def test_linear_speed_zero_setpoint_stops_ship():
    """A ship moving at _current_speed > 0 ramps to zero when speed
    setpoint is zero. Fallback accel snaps in one tick."""
    ship = ShipClass()
    _place(ship)
    ship._current_speed = 100.0
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_speed == pytest.approx(0.0)


def test_direction_model_space_follows_rotation():
    """When direction frame is MODEL_SPACE, the velocity vector is
    rotated by the ship's world rotation each tick. Yaw the ship 90°
    around +Z so its model-forward (+Y) now points along world +X;
    moving forward should advance along +X, not +Y."""
    ship = ShipClass()
    _place(ship)
    # Yaw 90° around Z: model +Y -> world +X.
    R = TGMatrix3()
    R.MakeZRotation(-math.pi / 2.0)  # row-vector convention: +Z rotation
                                     # tilts forward toward +X (see
                                     # host_loop.py:721 sign comment).
    ship.SetMatrixRotation(R)

    ship.SetImpulse(10.0, TGPoint3_GetModelForward(),
                    App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)

    p = ship.GetTranslate()
    # World-forward after MakeZRotation(-π/2) applied via MultMatrixLeft
    # to model (+Y) is world (+X). See ship_motion._step_ship_motion:
    # world_dir = TGPoint3(direction) then MultMatrixLeft(GetWorldRotation()).
    assert p.x == pytest.approx(10.0 * dt, abs=1e-9)
    assert p.y == pytest.approx(0.0, abs=1e-9)
    assert p.z == pytest.approx(0.0, abs=1e-9)


def test_direction_world_space_ignores_rotation():
    """When direction frame is WORLD_SPACE, the direction vec is used
    as-is, independent of ship rotation."""
    ship = ShipClass()
    _place(ship)
    R = TGMatrix3(); R.MakeZRotation(math.pi / 2.0)  # arbitrary rotation
    ship.SetMatrixRotation(R)

    world_dir = TGPoint3(0.0, 1.0, 0.0)  # world +Y
    ship.SetSpeed(20.0, world_dir,
                  App.PhysicsObjectClass.DIRECTION_WORLD_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)

    p = ship.GetTranslate()
    assert p.y == pytest.approx(20.0 * dt)
    assert p.x == pytest.approx(0.0, abs=1e-9)


def test_angular_ramp_snaps_with_fallback_accel():
    """Test ship has no IES populated; the angular ramp snaps to
    target in one tick under FALLBACK_MAX_ACCEL."""
    ship = ShipClass()
    _place(ship)
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    target_av = TGPoint3(0.0, 0.0, 1.0)  # yaw at 1 rad/s
    ship.SetTargetAngularVelocityDirect(target_av)

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_angular_velocity.x == pytest.approx(0.0)
    assert ship._current_angular_velocity.y == pytest.approx(0.0)
    assert ship._current_angular_velocity.z == pytest.approx(1.0)


def test_angular_zero_setpoint_stops_rotation():
    """A ship rotating at _current_angular_velocity != 0 ramps to
    zero when the target is zero."""
    ship = ShipClass()
    _place(ship)
    ship._current_angular_velocity = TGPoint3(0.5, 0.5, 0.5)
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_angular_velocity.x == pytest.approx(0.0)
    assert ship._current_angular_velocity.y == pytest.approx(0.0)
    assert ship._current_angular_velocity.z == pytest.approx(0.0)


def test_angular_rotation_advances_world_rotation():
    """After one tick at yaw=1 rad/s for dt=1/60, the ship's world
    rotation has advanced by ~1/60 rad around Z (model-up axis).
    Easiest check: model-forward (+Y) now has a small +X (or -X)
    component, no longer pure +Y."""
    ship = ShipClass()
    _place(ship)
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 1.0))

    dt = 1.0 / 60.0
    tick_all_ship_motion(dt)

    R = ship.GetWorldRotation()
    fwd_world = R.GetRow(1)  # model-Y mapped into world
    # After yaw of ~dt rad, |x| ≈ sin(dt), |y| ≈ cos(dt).
    assert abs(fwd_world.x) == pytest.approx(math.sin(dt), abs=1e-6)
    assert fwd_world.y == pytest.approx(math.cos(dt), abs=1e-6)
    assert fwd_world.z == pytest.approx(0.0, abs=1e-9)


def test_angular_per_axis_ramp_is_independent():
    """When the target has nonzero pitch but zero yaw, only pitch
    rate ramps up — yaw and roll stay at zero."""
    ship = ShipClass()
    _place(ship)
    ship._current_angular_velocity = TGPoint3(0.0, 0.0, 0.0)
    ship.SetSpeed(0.0, TGPoint3_GetModelForward(),
                  App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.7, 0.0, 0.0))

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_angular_velocity.x == pytest.approx(0.7)
    assert ship._current_angular_velocity.y == pytest.approx(0.0)
    assert ship._current_angular_velocity.z == pytest.approx(0.0)


def test_motion_integrator_runs_after_ai_setpoints():
    """Sanity: when the integrator runs, GetSpeedSetpoint must already
    reflect the AI's intent — order-of-ops is locked by the GameLoop
    test in Task 6. This duplicates that contract at the integrator
    boundary so a bug in either side fails locally."""
    ship = ShipClass()
    _place(ship)
    ship.SetImpulse(7.0, TGPoint3_GetModelForward(),
                    App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))

    tick_all_ship_motion(1.0 / 60.0)
    assert ship._current_speed == pytest.approx(7.0)
