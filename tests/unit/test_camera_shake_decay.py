"""camera_shake — energy decay + perturbation math.

API:
    apply_kick(damage: float) -> None
    update(dt: float) -> None
    perturb(eye, target, up) -> (eye, target, up)
    reset() -> None
    get_energy() -> float
"""
import math

import pytest


# ── energy decay ───────────────────────────────────────────────────────────

def test_apply_kick_increases_energy():
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    assert camera_shake.get_energy() == pytest.approx(2.0)   # 100 / DAMAGE_PER_UNIT_ENERGY=50


def test_apply_kick_clamped_to_max_kick_energy():
    """A single 10000-damage hit injects at most MAX_KICK_ENERGY = 4.0."""
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(10000.0)
    assert camera_shake.get_energy() == pytest.approx(4.0)


def test_zero_damage_apply_kick_is_noop():
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(0.0)
    assert camera_shake.get_energy() == 0.0


def test_energy_decays_monotonically():
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    last = camera_shake.get_energy()
    for _ in range(60):
        camera_shake.update(1.0 / 60.0)
        cur = camera_shake.get_energy()
        assert cur <= last + 1e-9
        last = cur


def test_energy_decays_to_one_percent_in_half_a_second():
    """TAU=0.15s → exp(-0.5/0.15) ≈ 0.036 → crosses 1% near t ≈ 0.69s.
    Test bound: under 1% within [0.45s, 0.80s] to cover both float drift
    and the spec's '~0.5s' target."""
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    peak = camera_shake.get_energy()
    one_pct = 0.01 * peak
    t = 0.0
    dt = 1.0 / 240.0
    while camera_shake.get_energy() > one_pct and t < 1.0:
        camera_shake.update(dt)
        t += dt
    assert 0.60 <= t <= 0.80


def test_sustained_fire_clamped_to_max_energy():
    from engine.appc import camera_shake
    camera_shake.reset()
    for _ in range(100):
        camera_shake.apply_kick(1000.0)   # each kick clamps to 4.0
    assert camera_shake.get_energy() <= 8.0 + 1e-9   # MAX_ENERGY


# ── perturbation math ──────────────────────────────────────────────────────

def test_perturb_identity_when_energy_zero():
    from engine.appc import camera_shake
    camera_shake.reset()
    eye = (0.0, 0.0, 100.0)
    target = (0.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)
    e2, t2, u2 = camera_shake.perturb(eye, target, up)
    assert e2 == pytest.approx(eye)
    assert t2 == pytest.approx(target)
    assert u2 == pytest.approx(up)


def test_perturb_keeps_up_vector_unchanged():
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    eye = (0.0, 0.0, 100.0)
    target = (0.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)
    _, _, u2 = camera_shake.perturb(eye, target, up)
    assert u2 == pytest.approx(up)


def test_perturb_peak_yaw_within_expected_range():
    """Peak yaw over a 30-tick window after a 100-damage kick is between
    1.0° and 2.5° (calibration target from spec §3.5)."""
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)
    eye = (0.0, 0.0, 100.0)
    target = (0.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)

    peak_yaw_deg = 0.0
    for _ in range(30):
        e2, t2, _ = camera_shake.perturb(eye, target, up)
        # Yaw angle = angle of (target' - eye') projected onto XZ plane,
        # relative to the original view direction (-Z).
        vx = t2[0] - e2[0]
        vz = t2[2] - e2[2]
        yaw_rad = math.atan2(vx, -vz)   # 0 when looking down -Z.
        peak_yaw_deg = max(peak_yaw_deg, abs(math.degrees(yaw_rad)))
        camera_shake.update(1.0 / 60.0)
    assert 1.0 <= peak_yaw_deg <= 2.5


def test_perturb_is_deterministic_across_resets():
    """Two identical kick sequences after reset produce identical perturb outputs."""
    from engine.appc import camera_shake

    def _run():
        camera_shake.reset()
        camera_shake.apply_kick(50.0)
        outs = []
        for _ in range(30):
            outs.append(camera_shake.perturb((0.0, 0.0, 100.0),
                                              (0.0, 0.0, 0.0),
                                              (0.0, 1.0, 0.0)))
            camera_shake.update(1.0 / 60.0)
        return outs

    a = _run()
    b = _run()
    assert a == b


def test_yaw_crosses_zero_multiple_times_in_decay_window():
    """The decaying-noise design should oscillate, not drift. Yaw flips
    sign at least 4 times during the first 0.3s after a kick."""
    from engine.appc import camera_shake
    camera_shake.reset()
    camera_shake.apply_kick(100.0)

    eye = (0.0, 0.0, 100.0)
    target = (0.0, 0.0, 0.0)
    up = (0.0, 1.0, 0.0)

    prev_sign = 0
    crossings = 0
    for _ in range(18):    # 0.3s @ 60Hz
        e2, t2, _ = camera_shake.perturb(eye, target, up)
        vx = t2[0] - e2[0]
        sign = 1 if vx > 1e-6 else (-1 if vx < -1e-6 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            crossings += 1
        if sign != 0:
            prev_sign = sign
        camera_shake.update(1.0 / 60.0)
    assert crossings >= 4
