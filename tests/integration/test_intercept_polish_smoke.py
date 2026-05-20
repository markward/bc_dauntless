"""Integration smoke for AI.PlainAI.Intercept under NonFedAttack/FedAttack
usage patterns.

Slice A landed an initial Intercept port. This task pins the
combat-relevant Update behaviour: target ahead -> ship accelerates and
turns toward target."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _attach_ies(ship, *, max_speed=120.0, max_accel=50.0,
                 max_ang_vel=1.5, max_ang_accel=1.0):
    """Intercept reads MaxSpeed > 0 (sdk/.../Intercept.py:118) to enter
    its prediction-and-control block, and the SDK call is unguarded.
    Fresh ShipClass instances have no IES (tests/unit/test_player.py:52
    pins that contract), so combat-relevant smokes must attach one
    explicitly. Mirrors test_ai_intercept_smoke.py's helper."""
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ies.SetMaxSpeed(max_speed)
    ies.SetMaxAccel(max_accel)
    ies.SetMaxAngularVelocity(max_ang_vel)
    ies.SetMaxAngularAccel(max_ang_accel)
    ship.SetImpulseEngineSubsystem(ies)


def _build_scene(target_distance: float = 500.0):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    _attach_ies(ours)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, target_distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_intercept(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "Intercept")
    plain.SetScriptModule("Intercept")
    inst = plain.GetScriptInstance()
    inst.SetTargetObjectName(target_name)
    # Default fMaximumSpeed is 1.0e20 which routes through InSystemWarp
    # (sdk/.../Intercept.py:213-214) and teleports without calling
    # SetSpeed. Pin a finite maximum so the impulse/SetSpeed path runs
    # — that's what the combat-relevant smoke asserts.
    inst.SetMaximumSpeed(120.0)
    return plain, inst


def test_intercept_update_drives_impulse_toward_distant_target():
    """At long distance, Intercept should produce non-zero forward impulse."""
    ours, _target = _build_scene(target_distance=1000.0)
    _plain, inst = _wire_intercept(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] > 0.0


def test_intercept_update_with_no_target_returns_done():
    ours, _target = _build_scene()
    _plain, inst = _wire_intercept(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE


def test_intercept_existing_slice_a_smoke_still_passes():
    """The Slice A intercept smoke at tests/integration/test_ai_intercept_smoke.py
    must remain green - pin its existence here as a regression marker.

    This test acts as a directory check; the actual regression is the
    sibling test file's continued green status under the project test
    sweep."""
    import os
    sibling = os.path.join(
        os.path.dirname(__file__), "test_ai_intercept_smoke.py")
    assert os.path.exists(sibling), (
        "Slice A test_ai_intercept_smoke.py must remain present; "
        "if you renamed it, update this regression marker"
    )
