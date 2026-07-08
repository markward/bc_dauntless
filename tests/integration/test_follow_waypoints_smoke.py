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


def test_follow_waypoints_turns_to_offset_waypoint():
    """With TurnTowardOrientation wired, a ship facing +Y must turn toward a
    waypoint that is NOT dead ahead and close the bearing. Before the fix the
    ship flew straight along +Y forever (TurnTowardOrientation was a no-op).

    FollowWaypoints.Update() resolves its target via
    ``App.PhysicsObjectClass_GetObject(pSet, name)`` first, falling back to
    ``App.PlacementObject_GetObject`` only when that returns None
    (sdk/.../AI/PlainAI/FollowWaypoints.py:132-137). "WP1" is a ShipClass
    (a PhysicsObjectClass), so it resolves directly through the real
    resolver, exercising a genuine off-axis approach."""
    from engine.appc.math import TGPoint3
    from engine.appc.ship_motion import _step_ship_motion

    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(120.0); ies.SetMaxAccel(50.0)
    ies.SetMaxAngularVelocity(0.5); ies.SetMaxAngularAccel(0.3)
    ours._impulse_engine_subsystem = ies
    pSet.AddObjectToSet(ours, "Ours")

    # Waypoint 90° off the +Y nose (dead abeam to starboard).
    other = ShipClass(); other.SetTranslateXYZ(4000.0, 0.0, 0.0)
    other._hull = HullSubsystem("H"); other._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(other, "WP1")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("FollowWaypoints")
    inst = plain.GetScriptInstance()
    inst.SetTargetWaypointName("WP1")

    def bearing_dot():
        fwd = ours.GetWorldRotation().GetCol(1)
        d = TGPoint3(4000.0 - ours.GetTranslate().x,
                     0.0 - ours.GetTranslate().y,
                     0.0 - ours.GetTranslate().z)
        d.Unitize()
        return fwd.x * d.x + fwd.y * d.y + fwd.z * d.z

    start_dot = bearing_dot()
    # Re-command on the AI cadence, integrate at 60 Hz between commands.
    for _ in range(600):            # 10 s
        inst.Update()
        _step_ship_motion(ours, 1.0 / 60.0)
    end_dot = bearing_dot()

    assert end_dot > start_dot + 0.2, (
        f"nose did not turn toward the offset waypoint: {start_dot:.3f} -> {end_dot:.3f}")
