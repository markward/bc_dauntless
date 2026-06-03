"""Engines disabled / destroyed → ship_motion._step_ship_motion clamps
linear and angular targets to zero and applies a drag-fraction-scaled
ramp so current velocities decay slowly. Repair lifts the gate at use-
time (no cached flag)."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass_Create
from engine.appc.ship_motion import (
    _step_ship_motion, DISABLED_ENGINE_DRAG_FRACTION,
)


def _galaxy_like_ship():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ies._max_condition = 100.0
    ies._condition = 100.0
    ies._disabled_percentage = 0.5
    return ship


def _set_forward_setpoint(ship, speed):
    ship._speed_setpoint = (
        speed, TGPoint3(0.0, 1.0, 0.0),
        PhysicsObjectClass.DIRECTION_MODEL_SPACE,
    )


def _set_angular_setpoint(ship, x, y, z):
    ship._target_angular_velocity_setpoint = TGPoint3(x, y, z)


def test_drag_fraction_is_one_tenth():
    """Locked tuning constant from the spec (§2)."""
    assert DISABLED_ENGINE_DRAG_FRACTION == 0.1


def test_healthy_ies_ramps_to_setpoint_at_max_accel():
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 6.3)
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    # After ~1 s at MaxAccel 1.5: current_speed = 1.5.
    assert abs(ship._current_speed - 1.5) < 1e-3


def test_disabled_ies_clamps_target_and_decays_at_drag_fraction():
    """Disable IES with high current_speed; target clamps to 0, decay is
    MaxAccel * drag_fraction per second (not full MaxAccel)."""
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 6.3)
    ship._current_speed = 6.3
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)  # below 0.5 * 100 = 50 -> disabled
    assert ies.IsDisabled() == 1

    for _ in range(60):  # 1 second
        _step_ship_motion(ship, 1.0 / 60)
    # Drag-fraction decel: 1.5 * 0.1 = 0.15 GU/s²; after 1s: 6.3 - 0.15 = 6.15.
    expected = 6.3 - 1.5 * DISABLED_ENGINE_DRAG_FRACTION
    assert abs(ship._current_speed - expected) < 1e-3


def test_destroyed_ies_behaves_identically_to_disabled():
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 6.3)
    ship._current_speed = 6.3
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(0.0)  # destroyed
    assert ies.IsDestroyed() == 1

    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    expected = 6.3 - 1.5 * DISABLED_ENGINE_DRAG_FRACTION
    assert abs(ship._current_speed - expected) < 1e-3


def test_disabled_ies_clamps_angular_target_and_decays():
    """Angular setpoint also clamps to zero; ramp uses drag fraction."""
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 0.0)
    _set_angular_setpoint(ship, 0.0, 0.0, 0.28)  # yawing at MaxAngularVelocity
    ship._current_angular_velocity.z = 0.28
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    # MaxAngularAccel 0.12 * drag_fraction 0.1 = 0.012 rad/s^2; 1s: 0.28-0.012=0.268.
    expected = 0.28 - 0.12 * DISABLED_ENGINE_DRAG_FRACTION
    assert abs(ship._current_angular_velocity.z - expected) < 1e-3


def test_repair_restores_full_ramp_rate():
    ship = _galaxy_like_ship()
    _set_forward_setpoint(ship, 6.3)
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)  # disabled
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    speed_disabled = ship._current_speed

    ies.SetCondition(100.0)  # repaired
    for _ in range(60):
        _step_ship_motion(ship, 1.0 / 60)
    # 1 s of healthy ramp at MaxAccel 1.5: gain ~1.5 (capped at MaxSpeed 6.3).
    assert ship._current_speed > speed_disabled + 1.0


# ── Player-side gate (host_loop._PlayerControl) ───────────────────────────────

from engine.host_loop import _PlayerControl


class _Keys:
    KEY_W = 1; KEY_S = 2; KEY_A = 3; KEY_D = 4; KEY_Q = 5; KEY_E = 6
    KEY_R = 7; KEY_I = 8
    KEY_0 = 10; KEY_1 = 11; KEY_2 = 12; KEY_3 = 13; KEY_4 = 14
    KEY_5 = 15; KEY_6 = 16; KEY_7 = 17; KEY_8 = 18; KEY_9 = 19
    KEY_LEFT_SHIFT = 20; KEY_LEFT_CONTROL = 21; KEY_LEFT_SUPER = 22


class _Reader:
    keys = _Keys()
    def __init__(self):
        self.held = set(); self.pressed_once = set()
    def key_state(self, key): return key in self.held
    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key); return True
        return False


def test_player_throttle_clamped_when_ies_disabled():
    pc = _PlayerControl()
    pc.impulse_level = 9
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)  # disabled
    assert pc.GetTargetSpeed(ship) == 0.0


def test_player_throttle_clamped_when_ies_destroyed():
    pc = _PlayerControl()
    pc.impulse_level = 9
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(0.0)
    assert pc.GetTargetSpeed(ship) == 0.0


def test_player_throttle_restored_after_repair():
    pc = _PlayerControl()
    pc.impulse_level = 9
    ship = _galaxy_like_ship()
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)
    assert pc.GetTargetSpeed(ship) == 0.0
    ies.SetCondition(100.0)
    assert abs(pc.GetTargetSpeed(ship) - 6.3) < 1e-6


def test_player_angular_clamped_when_ies_disabled():
    """Holding D (yaw right) with disabled engines: angular target
    forced to 0 and current rate decays at drag fraction × MaxAngularAccel.
    """
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    pc._current_yaw_rate = 0.28  # already yawing at full rate
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)

    reader = _Reader()
    reader.held.add(reader.keys.KEY_D)  # request yaw right (which sets a nonzero target)
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    # MaxAngularAccel 0.12 * 0.1 drag = 0.012 rad/s² decay; after 1 s: 0.28 - 0.012 ≈ 0.268.
    expected = 0.28 - 0.12 * DISABLED_ENGINE_DRAG_FRACTION
    assert abs(pc._current_yaw_rate - expected) < 1e-3


def test_player_angular_recovers_after_repair():
    pc = _PlayerControl()
    ship = _galaxy_like_ship()
    pc._current_yaw_rate = 0.28
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetCondition(10.0)
    reader = _Reader()
    for _ in range(60):
        pc.apply(ship, dt=1.0/60, h=reader)
    rate_disabled = pc._current_yaw_rate

    ies.SetCondition(100.0)  # repaired
    for _ in range(60):  # no keys held -> target is 0, full-rate decay back to 0
        pc.apply(ship, dt=1.0/60, h=reader)
    assert pc._current_yaw_rate < rate_disabled - 0.05
