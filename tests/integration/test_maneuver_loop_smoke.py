"""Activation smoke for AI.PlainAI.ManeuverLoop.

SDK has no required setters. Drives random drift maneuvers — used by
the NoSensorsEvasive sub-Compound, and by AI/Player/Defense,
AI/Player/DefenseNoTarget, QuickBattle/QuickBattleAI and E3M1/
KlingonManeuverAI.

ManeuverLoop is the sole caller of ShipClass.TurnTowardDifference. Note that
test_maneuver_loop_update_returns_valid_status below CANNOT see that method
being a no-op — a stubbed turn still lets Update return US_ACTIVE, which is a
valid status. The two tests after it close that hole by asserting the ship
actually rotates and the maneuver actually finishes."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem
from engine.core.loop import GameLoop, TICK_RATE


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_maneuver_loop_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("ManeuverLoop")
    inst = plain.GetScriptInstance()
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS


def _setup_maneuver(loop_fraction):
    """A Galaxy-enveloped ship running a real ManeuverLoop under the gameloop."""
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ship.SetImpulseEngineSubsystem(ies)
    pSet.AddObjectToSet(ship, "Ours")

    plain = PlainAI_Create(ship, "TestAI")
    plain.SetScriptModule("ManeuverLoop")
    inst = plain.GetScriptInstance()
    inst.SetLoopFraction(loop_fraction)
    inst.SetTurnAxis(App.TGPoint3_GetModelLeft())
    inst.SetSpeeds(0.0, 0.0)          # rotation only — keep translation out of it
    ship.SetAI(plain)
    return ship, plain


def _world_forward(ship):
    v = TGPoint3(0.0, 1.0, 0.0)
    v.MultMatrixLeft(ship.GetWorldRotation())
    return v


def test_quarter_loop_actually_rotates_the_ship():
    """A quarter loop about model-left must swing the nose ~90° off its start
    heading, and must stay in its own turn plane while doing it.

    Model-left is -X, and a +90° rotation about -X carries forward (0,1,0) onto
    (0,0,-1) — so the nose ends pointing "down" in world terms with no sideways
    component. The fwd.x bound is the one that matters: a spurious roll term in
    TurnDirectionsToDirections used to yaw the ship out of the turn plane
    entirely, landing it at (-0.64, +0.41, +0.65)."""
    ship, plain = _setup_maneuver(0.25)
    GameLoop().advance(TICK_RATE * 30)

    fwd = _world_forward(ship)
    # Swept at least the commanded 90° (dot with the start heading <= cos 85°).
    assert fwd.y < 0.09, f"nose did not swing through ~90°; fwd={fwd}"
    # Stayed in the turn plane. This is the assertion that guards the bug: the
    # spurious roll term used to yaw the ship clean out of the plane, landing it
    # at (-0.64, +0.41, +0.65). Measured fwd.x is now exactly 0.0.
    assert abs(fwd.x) < 0.1, f"nose drifted out of the turn plane; fwd={fwd}"


@pytest.mark.xfail(strict=True, reason=(
    "Pre-existing, separate from TurnTowardDifference: nothing zeroes an AI's "
    "angular-velocity setpoint when the AI completes, so a finished turn keeps "
    "creeping. Measured with a 0.25 loop: 98.9 deg swept at t=10s (a fair ~9 deg "
    "of overshoot), still creeping to 117.8 deg by t=30s with no AI updates at "
    "all. The rate IS decaying (19 deg over 20s vs the 16 deg/s setpoint), so "
    "something damps it, just not to rest. Systemic — it applies to every AI "
    "that commands a turn and then finishes (TurnToOrientation with "
    "bDoneOnLineup, FollowWaypoints, ...), so the fix belongs in the AI "
    "driver/ship_motion seam, not here. Remove this marker when fixed."))
def test_maneuver_stops_turning_once_it_reports_done():
    """The commanded rotation must not run on past US_DONE.

    ManeuverLoop stops updating once it reports DONE, so whatever angular
    velocity setpoint was last written is simply left standing — nothing in the
    script zeroes it. If nothing else does either, a completed maneuver leaves
    the ship rotating forever."""
    ship, plain = _setup_maneuver(0.25)
    loop = GameLoop()
    loop.advance(TICK_RATE * 10)          # well past completion (~5.6 s)
    assert plain.IsActive() == 0, "precondition: maneuver should be done by 10 s"
    settled = _world_forward(ship)

    loop.advance(TICK_RATE * 20)          # 20 s more with no AI updates
    after = _world_forward(ship)

    drift = max(abs(after.x - settled.x), abs(after.y - settled.y),
                abs(after.z - settled.z))
    assert drift < 0.01, (
        f"ship kept rotating after the maneuver finished: {settled} -> {after}")


def test_quarter_loop_reports_done():
    """Once the commanded angle is traversed the AI must go inactive.

    This is the jam a stubbed TurnTowardDifference caused: ManeuverLoop only
    reports US_DONE when its *observed* rotation reaches fDestinationAngle
    (ManeuverLoop.py:110-113), so a maneuver that cannot turn stays US_ACTIVE
    forever and never yields its container."""
    ship, plain = _setup_maneuver(0.25)
    GameLoop().advance(TICK_RATE * 30)

    assert plain.IsActive() == 0, "ManeuverLoop never completed — still US_ACTIVE"
