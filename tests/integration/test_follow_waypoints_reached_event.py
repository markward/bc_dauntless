"""FollowWaypoints must broadcast a real ET_AI_REACHED_WAYPOINT event.

Gap C1 (docs/engine/aieditor-ai-surface-and-gaps.md §4). BC's arrival
notification is emitted by SDK script, not by the engine:
``AI/PlainAI/FollowWaypoints.py:278-284`` builds an ``App.WaypointEvent_Create()``,
sets destination/type/placement on it, and hands it to
``App.g_kEventManager.AddEvent``.

Neither ``WaypointEvent`` nor ``ET_AI_REACHED_WAYPOINT`` existed in our tree, so
the event object was a ``_NamedStub`` and the type constant collapsed to
``int() == 0`` — the broadcast went nowhere and every consumer was dead
(``Conditions/ConditionReachedWaypoint``, registered by ``AI/Setup.py:125``, and
``Maelstrom/Episode8/E8M2/E8M2.py:514``). Live-confirmed by
``docs/stub_heatmap.md`` ranks 76/108/109/113.

These tests drive the REAL SDK producer to a real ``App.Waypoint`` and assert a
subscriber actually receives it, carrying the placement and destination the SDK
consumers read back.
"""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.ship_motion import _step_ship_motion
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


def _ship_at_origin(pSet):
    ship = ShipClass()
    ship._hull = HullSubsystem("H")
    ship._hull.SetMaxCondition(1000.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(120.0)
    ies.SetMaxAccel(50.0)
    ies.SetMaxAngularVelocity(0.5)
    ies.SetMaxAngularAccel(0.3)
    ship._impulse_engine_subsystem = ies
    pSet.AddObjectToSet(ship, "Ours")
    return ship


def _fly_to_waypoint():
    """Drive the real FollowWaypoints script until it reaches WP1.

    Returns (ship, waypoint). WP1 sits dead ahead and close, so the ship
    crosses fCloseEnough (8.0 GU) quickly and ReachedWaypoint() fires.
    """
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = _ship_at_origin(pSet)

    wp = App.Waypoint_Create("WP1", "S", None)
    wp.SetTranslateXYZ(0.0, 30.0, 0.0)
    wp.SetSpeed(10.0)

    plain = PlainAI_Create(ship, "TestAI")
    plain.SetScriptModule("FollowWaypoints")
    inst = plain.GetScriptInstance()
    inst.SetTargetWaypointName("WP1")

    for _ in range(600):            # 10 s at 60 Hz
        inst.Update()
        _step_ship_motion(ship, 1.0 / 60.0)

    return ship, wp


def test_reaching_a_waypoint_broadcasts_the_arrival_event():
    """A broadcast subscriber on ET_AI_REACHED_WAYPOINT must actually be called.

    Fails before the fix because App.ET_AI_REACHED_WAYPOINT is undefined: the
    constant collapses to int() == 0, so the registration key and the event's
    type never match (and WaypointEvent_Create returns a stub that cannot carry
    a type at all).
    """
    received = []

    class _Listener:
        def Arrived(self, pEvent):
            received.append(pEvent)

    listener = _Listener()
    handler = App.TGPythonInstanceWrapper()
    handler.SetPyWrapper(listener)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_AI_REACHED_WAYPOINT, handler, "Arrived")

    _fly_to_waypoint()

    assert received, (
        "no ET_AI_REACHED_WAYPOINT reached the subscriber -- "
        "FollowWaypoints.ReachedWaypoint() broadcast went nowhere")


def test_arrival_event_carries_the_placement_and_ship():
    """The payload must survive the round trip.

    ConditionReachedWaypoint.EventTriggered reads BOTH
    ``pEvent.GetDestination()`` (to match the ship) and
    ``pEvent.GetPlacement().GetName()`` (to match the waypoint)
    -- Conditions/ConditionReachedWaypoint.py:47-56. An event that arrives
    without those is still useless, so assert them rather than mere delivery.
    """
    received = []

    class _Listener:
        def Arrived(self, pEvent):
            received.append(pEvent)

    listener = _Listener()
    handler = App.TGPythonInstanceWrapper()
    handler.SetPyWrapper(listener)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_AI_REACHED_WAYPOINT, handler, "Arrived")

    ship, wp = _fly_to_waypoint()
    assert received, "precondition: the arrival event must be delivered"

    event = received[0]
    assert event.GetDestination() is ship
    assert event.GetPlacement() is wp
    assert event.GetPlacement().GetName() == "WP1"
    assert event.GetEventType() == App.ET_AI_REACHED_WAYPOINT


def test_sdk_condition_reached_waypoint_goes_true_end_to_end():
    """The real SDK consumer must flip 0 -> 1. This is the dead behaviour.

    Conditions/ConditionReachedWaypoint subscribes in its own __init__ and is
    registered by AI/Setup.py:125. Nothing about it was broken -- it simply
    never received an event. Drives the real producer and the real consumer
    with no test double between them.
    """
    from engine.appc.ai import ConditionScript_Create

    cond = ConditionScript_Create(
        "Conditions.ConditionReachedWaypoint", "ConditionReachedWaypoint",
        "Ours", "WP1")
    assert cond.GetStatus() == 0, "condition must start false"

    _fly_to_waypoint()

    assert cond.GetStatus() == 1, (
        "ConditionReachedWaypoint never went true after the ship reached WP1")


def test_reached_waypoint_condition_ignores_a_different_waypoint():
    """It must match on the waypoint NAME, not fire on any arrival.

    Guards the obvious wrong fix -- broadcasting an event whose placement is
    ignored would pass the test above while making the condition fire for
    every waypoint in the mission.
    """
    from engine.appc.ai import ConditionScript_Create

    cond = ConditionScript_Create(
        "Conditions.ConditionReachedWaypoint", "ConditionReachedWaypoint",
        "Ours", "SOME_OTHER_WAYPOINT")

    _fly_to_waypoint()

    assert cond.GetStatus() == 0, (
        "condition fired for WP1 while watching SOME_OTHER_WAYPOINT -- "
        "the placement name is not being checked")


def test_arrival_event_type_is_distinct_from_other_event_types():
    """A constant that collapses to 0 would alias every other event type.

    This is the failure mode CLAUDE.md flags as a live bug rather than noise:
    an undefined App.<CONST> becomes a _NamedStub whose int() is 0, so
    unrelated broadcasts would cross-fire into waypoint handlers.
    """
    assert isinstance(App.ET_AI_REACHED_WAYPOINT, int)
    assert int(App.ET_AI_REACHED_WAYPOINT) != 0

    others = [
        App.ET_AI_TIMER, App.ET_AI_DONE, App.ET_AI_ORBITTING,
        App.ET_ENTERED_SET, App.ET_OBJECT_DESTROYED,
        App.ET_AI_INTERNAL_PROX_EVENT, App.ET_OBJECT_GROUP_CHANGED,
    ]
    assert App.ET_AI_REACHED_WAYPOINT not in others
