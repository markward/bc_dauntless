"""Effective-limit + keep-rule helpers for impulse degradation."""
from engine.appc.ship_motion import (
    _effective_motion, _cap_keep, _asymptote_step,
)
from engine.appc.ships import ShipClass_Create


def _galaxy():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
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
    # bare ship: no IES populated → has_linear and has_angular are False
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    em = _effective_motion(ship, 1.0)
    assert em.has_linear is False
    assert em.has_angular is False


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
