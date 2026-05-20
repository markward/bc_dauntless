"""Activation smoke for AI.PlainAI.FollowWaypoints.

SDK requires SetTargetWaypointName(s). The script flies a waypoint
path."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


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


def test_follow_waypoints_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    # FollowWaypoints reads a Waypoint placeable by name. The minimal
    # stand-in is to point at an Object (any non-None resolution) in the
    # set — the Update body is defensive against not-yet-arrived
    # waypoints. If a real Waypoint instance is required, the engine
    # gap surfaces here and lands as a separate feat() commit.
    other = ShipClass(); other.SetTranslateXYZ(0, 100, 0)
    other._hull = HullSubsystem("H"); other._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(other, "WP1")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("FollowWaypoints")
    inst = plain.GetScriptInstance()
    inst.SetTargetWaypointName("WP1")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
