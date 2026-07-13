"""ImpulseEngineSubsystem.GetCurMaxSpeed — the ship's *current* speed cap (GU/s).

Ground truth for the full-condition datapoints is the q16 live object-graph walk
of the real engine (`tools/probes/results/q16_object_graph_B.txt:43,106`):

    Galaxy  (undamaged): cond=2400/2400  curmaxspeed=6.3
    Shuttle (undamaged): cond=1000/1000  curmaxspeed=4.0

Both equal that ship's authored MaxSpeed (galaxy.py:785, shuttle.py:37), so at
full pods + full power GetCurMaxSpeed() == GetMaxSpeed().

Below full, the derating law is the one this engine already flies by
(`docs/superpowers/specs/2026-06-10-impulse-engine-degradation-design.md`):
online-pod fraction x normal-power fraction. GetCurMaxSpeed reports the cap the
ship can actually reach, so it must agree with ship_motion._effective_motion.
"""
from engine.appc.ship_motion import _effective_motion
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    ImpulseEngineSubsystem, ShipSubsystem, impulse_online_fraction,
)


def _assert_speed_gups(ies, expected: float) -> None:
    """Assert the reported cap, type-strictly.

    The `type(...) is float` check is load-bearing: a missing method returns a
    truthy `_Stub` whose operators silently collapse, so a bare
    `abs(ies.GetCurMaxSpeed() - expected) < 1e-6` passes VACUOUSLY against the
    very bug these tests exist to catch.
    """
    actual = ies.GetCurMaxSpeed()
    assert type(actual) is float
    assert abs(actual - expected) < 1e-6


def _ship_with_engines(max_speed_gups: float, n_pods: int) -> ShipClass:
    ship = ShipClass()
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ies.SetMaxSpeed(max_speed_gups)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    for i in range(n_pods):
        pod = ShipSubsystem("pod%d" % i)
        pod.SetMaxCondition(2600.0)
        pod.SetCondition(2600.0)
        ies.AddChildSubsystem(pod)
    ship.SetImpulseEngineSubsystem(ies)
    return ship


def test_undamaged_galaxy_reports_authored_max_speed():
    """q16: Galaxy at full condition -> curmaxspeed 6.3 GU/s."""
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    _assert_speed_gups(ies, 6.3)


def test_undamaged_shuttle_reports_authored_max_speed():
    """q16: Shuttle at full condition -> curmaxspeed 4.0 GU/s."""
    ies = _ship_with_engines(4.0, 2).GetImpulseEngineSubsystem()
    _assert_speed_gups(ies, 4.0)


def test_cur_max_speed_is_a_real_float_not_a_stub():
    """The bug this closes: the name fell through TGObject.__getattr__ to a
    truthy _Stub that collapses to 0 in arithmetic."""
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    speed_gups = ies.GetCurMaxSpeed()
    assert type(speed_gups) is float
    assert speed_gups * 2.0 == 12.6


def test_destroyed_pod_derates_the_cap_by_online_fraction():
    ship = _ship_with_engines(6.3, 3)
    ies = ship.GetImpulseEngineSubsystem()
    ies.GetChildSubsystem("pod0").SetCondition(0.0)
    _assert_speed_gups(ies, 6.3 * 2.0 / 3.0)


def test_all_pods_out_gives_zero_cap():
    ship = _ship_with_engines(6.3, 3)
    ies = ship.GetImpulseEngineSubsystem()
    for i in range(3):
        ies.GetChildSubsystem("pod%d" % i).SetCondition(0.0)
    _assert_speed_gups(ies, 0.0)


def test_power_starvation_derates_the_cap():
    """Half the wanted power reaching the engines -> half the speed cap,
    matching _effective_motion's power_factor term."""
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    ies._power_factor = 0.5
    _assert_speed_gups(ies, 3.15)


def test_cur_max_speed_agrees_with_the_flight_model_cap():
    """GetCurMaxSpeed is the speed the ship can actually reach: it must equal
    the cap the motion integrator enforces, damaged and power-starved alike."""
    ship = _ship_with_engines(6.3, 4)
    ies = ship.GetImpulseEngineSubsystem()
    ies.GetChildSubsystem("pod0").SetCondition(0.0)
    ies._power_factor = 0.8
    em = _effective_motion(ship, impulse_online_fraction(ies))
    _assert_speed_gups(ies, em.max_speed)


def test_no_pods_ship_keeps_full_cap():
    """Fallback ships (hardpoint declares no EP_IMPULSE pods) fly at full
    capability -- same rule as impulse_online_fraction."""
    ies = _ship_with_engines(6.3, 0).GetImpulseEngineSubsystem()
    _assert_speed_gups(ies, 6.3)
