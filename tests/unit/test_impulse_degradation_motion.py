"""Effective-limit + keep-rule helpers for impulse degradation."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ship_motion import (
    _effective_motion, _cap_keep, _asymptote_step, _step_ship_motion,
)
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import ShipSubsystem


def _galaxy():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    for i in range(3):
        ies.AddChildSubsystem(ShipSubsystem("pod%d" % i))
    return ship


def test_effective_motion_scales_all_four_limits():
    ship = _galaxy()
    em = _effective_motion(ship, 0.5)
    assert em.has_linear is True
    assert abs(em.max_speed - 3.15) < 1e-9
    assert abs(em.max_accel - 0.75) < 1e-9
    assert em.has_angular is True
    assert abs(em.max_ang_vel - 0.14) < 1e-9
    assert abs(em.max_ang_accel - 0.06) < 1e-9


def test_effective_motion_full_fraction_is_base():
    ship = _galaxy()
    em = _effective_motion(ship, 1.0)
    assert abs(em.max_speed - 6.3) < 1e-9
    assert abs(em.max_accel - 1.5) < 1e-9


def test_effective_motion_fallback_ship_has_no_real_limits():
    # bare ship: no ImpulseEngineSubsystem at all (GetImpulseEngineSubsystem
    # → None), so neither axis group has real limits.
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    em = _effective_motion(ship, 1.0)
    assert em.has_linear is False
    assert em.has_angular is False


def test_effective_motion_zero_fraction_zeros_all_limits():
    # f == 0 is the total-loss / drift trigger: every scaled limit is zero.
    ship = _galaxy()
    em = _effective_motion(ship, 0.0)
    assert em.has_linear is True and em.has_angular is True
    assert em.max_speed == 0.0 and em.max_accel == 0.0
    assert em.max_ang_vel == 0.0 and em.max_ang_accel == 0.0


def test_cap_keep_caps_acceleration_below_cap():
    # current under cap → commanded clamped to cap
    assert _cap_keep(10.0, 1.0, 3.0) == 3.0


def test_cap_keep_does_not_brake_above_cap():
    # already above cap → keep current, never dragged down by the cap
    assert _cap_keep(10.0, 5.0, 3.0) == 5.0


def test_cap_keep_allows_commanded_slowdown_above_cap():
    # pilot eases off below current (but still above cap) → allowed
    assert _cap_keep(4.0, 5.0, 3.0) == 4.0


def test_cap_keep_preserves_reverse_sign():
    assert _cap_keep(-10.0, 0.0, 3.0) == -3.0


def test_asymptote_step_rate_limited():
    # large gap → limited by accel
    assert abs(_asymptote_step(1.5, 100.0, 1.0 / 60) - 1.5 / 60) < 1e-9


def test_asymptote_step_closes_small_gap():
    # small gap (|gap|/tau < accel) → limited by gap/tau (tau == 1.0)
    assert abs(_asymptote_step(1.5, 0.3, 1.0 / 60) - 0.3 / 60) < 1e-9


def _disable_pods(ship, count):
    ies = ship.GetImpulseEngineSubsystem()
    for i in range(count):
        ies.GetChildSubsystem(i).SetCondition(0.0)


def _fwd_setpoint(ship, speed):
    ship._speed_setpoint = (
        speed, TGPoint3(0.0, 1.0, 0.0), PhysicsObjectClass.DIRECTION_MODEL_SPACE,
    )


def test_partial_loss_caps_top_speed_proportionally():
    # Galaxy has 3 pods. Disable 1 -> f = 2/3 -> top speed ~= 6.3 * 2/3.
    ship = _galaxy()
    _disable_pods(ship, 1)
    _fwd_setpoint(ship, 6.3)
    for _ in range(60 * 20):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3 * (2.0 / 3.0)) < 1e-2


def test_partial_loss_does_not_brake_ship_already_above_cap():
    # Reach full speed healthy, then lose a pod. Keep-rule: speed is held,
    # not dragged down to the new lower cap.
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    # 20 s, not 10: the ramp is a rate-limited asymptote (BC_IMPULSE_TAU), so
    # the last sliver of the gap closes slowly (10 s still leaves 1.6e-3).
    for _ in range(60 * 20):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - 6.3) < 1e-3
    v_at_cap = ship._current_speed
    _disable_pods(ship, 1)          # cap drops to 4.2, ship is at 6.3
    for _ in range(60 * 5):
        _step_ship_motion(ship, 1.0 / 60)
    assert abs(ship._current_speed - v_at_cap) < 1e-6  # unchanged, not braked


def test_first_frame_accelerates_it_does_not_teleport_to_commanded_speed():
    """Regression: the powered branch reads its drift snapshot with
    getattr(ship, "_drift_velocity", None). While TGObject.__getattr__ stubbed
    private names that default never fired -- it got a truthy _Stub, assigned
    _current_speed = _Stub.Length(), and _ramp_toward's `abs(delta) <= step`
    then evaluated 0 <= 0 and returned the TARGET. Every ship snapped to its
    commanded speed on its first motion frame instead of accelerating."""
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    _step_ship_motion(ship, 1.0 / 60)
    assert 0.0 < ship._current_speed < 0.1     # one tick of accel, not 6.3
    assert isinstance(ship._current_speed, float)


def test_total_loss_drifts_at_constant_velocity():
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    for _ in range(60 * 10):
        _step_ship_motion(ship, 1.0 / 60)
    speed_before = ship._current_speed
    pos_a = ship.GetTranslate()
    _disable_pods(ship, 3)          # all pods offline -> drift
    for _ in range(60 * 10):
        _step_ship_motion(ship, 1.0 / 60)
    # velocity magnitude unchanged across 10 s of drift (no decay)
    v = ship.GetVelocityTG()
    assert abs(v.Length() - speed_before) < 1e-6
    pos_b = ship.GetTranslate()
    travelled = ((pos_b.x - pos_a.x) ** 2 + (pos_b.y - pos_a.y) ** 2
                 + (pos_b.z - pos_a.z) ** 2) ** 0.5
    assert travelled > 0.0


def test_drift_velocity_decoupled_from_facing_while_tumbling():
    # Ship drifting along +Y, with residual yaw. Path must stay straight in
    # world space even though the nose rotates.
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    ship._target_angular_velocity_setpoint = TGPoint3(0.0, 0.0, 0.2)  # yaw
    for _ in range(60 * 5):
        _step_ship_motion(ship, 1.0 / 60)
    _disable_pods(ship, 3)          # drift with residual yaw
    p0 = ship.GetTranslate()
    _step_ship_motion(ship, 1.0 / 60)
    p1 = ship.GetTranslate()
    dir0 = (p1.x - p0.x, p1.y - p0.y, p1.z - p0.z)
    for _ in range(60 * 3):
        _step_ship_motion(ship, 1.0 / 60)
    p2 = ship.GetTranslate()
    _step_ship_motion(ship, 1.0 / 60)
    p3 = ship.GetTranslate()
    dirN = (p3.x - p2.x, p3.y - p2.y, p3.z - p2.z)
    import math
    def _unit(d):
        m = math.sqrt(sum(c * c for c in d))
        return tuple(c / m for c in d)
    u0, uN = _unit(dir0), _unit(dirN)
    dot = sum(a * b for a, b in zip(u0, uN))
    assert dot > 0.999   # travel direction unchanged despite the ship yawing


def test_repair_one_pod_resumes_powered_flight():
    ship = _galaxy()
    _fwd_setpoint(ship, 6.3)
    for _ in range(60 * 10):
        _step_ship_motion(ship, 1.0 / 60)
    _disable_pods(ship, 3)
    for _ in range(60 * 2):
        _step_ship_motion(ship, 1.0 / 60)
    assert getattr(ship, "_drift_velocity", None) is not None
    ies = ship.GetImpulseEngineSubsystem()
    pod = ies.GetChildSubsystem(0)
    pod.SetCondition(pod.GetMaxCondition())
    _step_ship_motion(ship, 1.0 / 60)
    assert ship._drift_velocity is None
    assert ship._current_speed > 0.0   # re-seeded from drift speed
