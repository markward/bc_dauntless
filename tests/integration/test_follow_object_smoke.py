"""Integration smoke for AI.PlainAI.FollowObject.

SDK PlainAI/FollowObject.py: follow another ship using FuzzyLogic
class form (SDK FollowObject.py:54-62, 110, 116-118) to compute
speed from distance + facing.

D2 smoke: after one Update call, ship's _speed_setpoint shows
positive impulse (follow); TurnTowardDirection was called."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene_with_target(target_distance: float):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, target_distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_follow_object(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "Follow")
    plain.SetScriptModule("FollowObject")
    inst = plain.GetScriptInstance()
    inst.SetFollowObjectName(target_name)
    return plain, inst


def test_follow_object_update_drives_impulse_when_far():
    """At a distance well beyond fFarDistance, FollowObject should
    produce a non-zero impulse setpoint (chase the target)."""
    ours, _target = _build_scene_with_target(target_distance=1000.0)
    _plain, inst = _wire_follow_object(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] > 0.0


def test_follow_object_update_turns_toward_target():
    """TurnTowardDirection called toward the target."""
    ours, _target = _build_scene_with_target(target_distance=500.0)
    _plain, inst = _wire_follow_object(ours)
    calls = []
    ours.TurnTowardDirection = lambda *args, **kwargs: calls.append(args)
    inst.Update()
    assert len(calls) >= 1, "expected TurnTowardDirection to be called"


def test_follow_object_update_with_no_target_returns_done():
    ours, _target = _build_scene_with_target(target_distance=500.0)
    _plain, inst = _wire_follow_object(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE
