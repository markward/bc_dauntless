"""ImpulseEngineSubsystem speed limits — BC's real derating law.

Decompiled from stbc.exe (clean-room, 2026-07-13). The naming is
counter-intuitive:

  * `GetMaxSpeed` (FUN_00561230) is the LIVE, damage-and-power-adjusted value.
  * `GetCurMaxSpeed` (wrapper 0x0061B640) is a plain read of a cached float at
    ImpulseEngineSubsystem+0xAC, whose per-tick writer is presumed to be
    Update() (address range absent from the Ghidra dump). We model the cache as
    equal to the live value; if BC in fact lerps/spools it, the two diverge only
    during the ramp, and SSDiag.py:114 printing both ("Maximum/current max")
    would be the tell.

FUN_00561230, in full:

    if IsDisabled() or not on: return 0
    base = property->maxSpeed                      # prop+0x4C (the hardpoint)
    cur  = base
    for each child pod:
        share = base / childCount
        if pod not disabled: share *= (1 - pod->conditionRatio)   # pod+0x34
        cur -= share                   # a disabled pod costs its ENTIRE share
    if tractorBeam: cur *= (1 - dragFraction)
    clamp cur to [0, base]
    return cur * powerSetting                      # +0x90 — the SLIDER

Two consequences that contradict what we shipped before:
  * pods are condition-WEIGHTED, not binary online/offline;
  * the power term is the requested SLIDER fraction (GetPowerPercentageWanted),
    NOT received/normal power — a ship whose reactor is starving it still
    reports full speed for its requested setting.

The tractor-drag term is NOT modelled: we have no IES->tractor link and no
drag-fraction field (our tractor drag is positional, engine/appc/tractor.py).

Full-condition ground truth is the q16 live object-graph walk
(`tools/probes/results/q16_object_graph_B.txt:43,106`): undamaged Galaxy 6.3,
undamaged Shuttle 4.0 GU/s — both equal the authored MaxSpeed
(galaxy.py:785, shuttle.py:37).
"""
from engine.appc.ship_motion import _effective_motion
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem, ShipSubsystem

POD_MAX_CONDITION = 2600.0


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
        pod.SetMaxCondition(POD_MAX_CONDITION)   # also seeds condition to max
        ies.AddChildSubsystem(pod)
    ship.SetImpulseEngineSubsystem(ies)
    return ship


def _pod(ies, i: int):
    return ies.GetChildSubsystem("pod%d" % i)


# ── q16 datapoints: full pods, full power ────────────────────────────────────

def test_undamaged_galaxy_reports_authored_max_speed():
    """q16: Galaxy at full condition -> curmaxspeed 6.3 GU/s."""
    _assert_speed_gups(_ship_with_engines(6.3, 3).GetImpulseEngineSubsystem(), 6.3)


def test_undamaged_shuttle_reports_authored_max_speed():
    """q16: Shuttle at full condition -> curmaxspeed 4.0 GU/s."""
    _assert_speed_gups(_ship_with_engines(4.0, 2).GetImpulseEngineSubsystem(), 4.0)


def test_cur_max_speed_is_a_real_float_not_a_stub():
    """The bug this closes: the name fell through TGObject.__getattr__ to a
    truthy _Stub that collapses to 0 in arithmetic."""
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    speed_gups = ies.GetCurMaxSpeed()
    assert type(speed_gups) is float
    assert speed_gups * 2.0 == 12.6


def test_cur_max_speed_is_a_cached_copy_of_the_live_value():
    """+0xAC mirrors FUN_00561230's result; we model the cache as exact."""
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    _pod(ies, 0).SetCondition(POD_MAX_CONDITION * 0.5)
    assert ies.GetCurMaxSpeed() == ies.GetMaxSpeed()


# ── the pod term: condition-weighted, not binary ─────────────────────────────

def test_half_health_pod_costs_half_its_share():
    """BC: share = base/n, scaled by (1 - conditionRatio). One of three pods at
    50% costs 1/3 x 50% = 1/6 of the base speed. The old binary law wrongly
    reported this ship at FULL speed."""
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    _pod(ies, 0).SetCondition(POD_MAX_CONDITION * 0.5)
    _assert_speed_gups(ies, 6.3 * (1.0 - (1.0 / 3.0) * 0.5))


def test_disabled_pod_costs_its_entire_share():
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    _pod(ies, 0).SetCondition(0.0)
    _assert_speed_gups(ies, 6.3 * 2.0 / 3.0)


def test_all_pods_disabled_gives_zero_speed():
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    for i in range(3):
        _pod(ies, i).SetCondition(0.0)
    _assert_speed_gups(ies, 0.0)


def test_no_pods_ship_keeps_full_speed():
    """Fallback ships (hardpoint declares no EP_IMPULSE pods): nothing to
    subtract, so cur stays at base."""
    _assert_speed_gups(_ship_with_engines(6.3, 0).GetImpulseEngineSubsystem(), 6.3)


# ── the power term: the requested slider, not the received power ─────────────

def test_power_slider_scales_the_speed():
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    ies.SetPowerPercentageWanted(0.5)
    _assert_speed_gups(ies, 3.15)


def test_power_slider_above_one_overdrives_past_base_speed():
    """The [0, base] clamp happens BEFORE the power multiply, so BC's 1.25 slider
    ceiling really does buy 125% of the authored max speed."""
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    ies.SetPowerPercentageWanted(1.25)
    _assert_speed_gups(ies, 6.3 * 1.25)


def test_starved_reactor_does_not_reduce_reported_speed():
    """BC multiplies by the REQUESTED setting (+0x90), not received/normal power
    (+0x94/+0x98). A ship whose reactor cannot feed the engines still reports
    full speed for its requested setting."""
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    ies._power_factor = 0.25      # received/normal — deliberately ignored
    ies._efficiency = 0.25
    _assert_speed_gups(ies, 6.3)


# ── master gates ─────────────────────────────────────────────────────────────

def test_engines_off_gives_zero_speed():
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    ies.TurnOff()
    _assert_speed_gups(ies, 0.0)


def test_disabled_master_gives_zero_speed():
    ies = _ship_with_engines(6.3, 3).GetImpulseEngineSubsystem()
    ies.SetCondition(0.0)
    _assert_speed_gups(ies, 0.0)


# ── the flight model flies by exactly this number ────────────────────────────

def test_cur_max_speed_agrees_with_the_flight_model_cap():
    """GetCurMaxSpeed is the speed the ship can actually reach: it must equal
    the cap the motion integrator enforces."""
    ship = _ship_with_engines(6.3, 4)
    ies = ship.GetImpulseEngineSubsystem()
    _pod(ies, 0).SetCondition(0.0)
    _pod(ies, 1).SetCondition(POD_MAX_CONDITION * 0.5)
    ies.SetPowerPercentageWanted(0.8)
    _assert_speed_gups(ies, _effective_motion(ship).max_speed)


def test_the_other_three_limits_derate_by_the_same_scalar():
    """BC caches four floats side by side (+0xAC..+0xB8). We derate accel and
    the angular pair by the same scalar as speed."""
    ies = _ship_with_engines(6.3, 4).GetImpulseEngineSubsystem()
    _pod(ies, 0).SetCondition(0.0)          # one of four out -> 0.75
    assert abs(ies.GetMaxAccel() - 1.5 * 0.75) < 1e-6
    assert abs(ies.GetCurMaxAccel() - 1.5 * 0.75) < 1e-6
    assert abs(ies.GetCurMaxAngularVelocity() - 0.28 * 0.75) < 1e-6
    assert abs(ies.GetCurMaxAngularAccel() - 0.12 * 0.75) < 1e-6
