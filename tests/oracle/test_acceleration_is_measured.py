"""PhysicsObjectClass.GetAccelerationTG is the ship's real world-space acceleration.

FireScript.PredictTargetLocation fires a torpedo only when the target's position
predicted by GetPredictedPosition(p, v, GetAccelerationTG(), flight time) is
within 10 deg of a tube, and the pulse-weapon lead solver uses the same term.
Measured on stbc.exe (stbc-oracle results_mac/probe_accel_gk.json, xac rows):
the original returns the ship's actual acceleration -- it matches dv/dt between
samples, sideways components included while turning, up to ~1.9 GU/s^2, nonzero
in 342 of 363 samples of a Galaxy-Keldon fight. Dauntless returned zero, so its
prediction was a straight line that sat on the target whenever the nose did:
Galaxy-Keldon AI duels launched 21-32% more torpedoes than the original and
ended 25-30% sooner.
"""
import math


def test_acceleration_is_the_velocity_change_over_the_tick(oracle):
    s = oracle(attacker="Galaxy", target="Keldon", range_gu=100.0)
    s.attach_basic_attack(1.0)
    App = s.App
    prev = None
    worst, moving = 0.0, 0
    for t, _ in s.sample_until(40.0, every_ticks=1):
        v = s.atk.GetVelocityTG()
        a = s.atk.GetAccelerationTG()
        now = App.g_kUtopiaModule.GetGameTime()
        if prev is not None and now > prev[0]:
            dt = now - prev[0]
            fd = [(v.x - prev[1][0]) / dt, (v.y - prev[1][1]) / dt, (v.z - prev[1][2]) / dt]
            worst = max(worst, math.dist(fd, [a.x, a.y, a.z]))
            if math.hypot(a.x, a.y, a.z) > 0.2:
                moving += 1
        prev = (now, (v.x, v.y, v.z))
    assert moving > 100, "an attacking ship accelerates for most of a fight"
    assert worst < 1e-3, worst


def test_a_ship_at_rest_reports_zero(oracle):
    s = oracle(attacker="Galaxy", target="Keldon", range_gu=3000.0)
    for _ in s.sample_until(2.0, every_ticks=10):
        pass
    a = s.tgt.GetAccelerationTG()
    assert (a.x, a.y, a.z) == (0.0, 0.0, 0.0)
