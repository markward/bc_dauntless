"""Unit tests for ProximityCheck per-tick evaluation.

The SDK conditions (ConditionInRange) create a ProximityCheck via
App.ProximityCheck_Create(eEventType), add watched objects with
AddObjectToCheckList, and rely on the engine to fire `eEventType` events
when objects cross the radius boundary. This per-tick evaluator runs from
GameLoop.tick between tick_all_ai and tick_all_ship_motion.
"""
import App
from engine.appc.events import TGEvent_Create, TGEventManager
from engine.appc.ai import ProximityCheck
from engine.appc.ships import ShipClass


def test_evaluate_fires_event_when_object_enters_radius():
    """Watched object initially outside radius. After moving it inside
    and calling Evaluate, an event of the configured type is emitted to
    the watched object's destination."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)

    anchor = ShipClass()
    anchor.SetTranslateXYZ(0.0, 0.0, 0.0)

    target = ShipClass()
    target.SetTranslateXYZ(500.0, 0.0, 0.0)  # outside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(evt.GetEventType())
    try:
        # Evaluate before move — no fire (still outside).
        pCheck.Evaluate(anchor)
        # Move inside.
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)
    finally:
        App.g_kEventManager.AddEvent = saved_add

    assert 999 in fired


def test_evaluate_does_not_fire_when_object_already_inside_at_first_eval():
    """An object already inside its trigger radius when the check begins
    evaluating (e.g. the player docked inside the starbase's 690 GU
    proximity at mission load) establishes the baseline and does NOT fire.
    Only a genuine outside->inside transition fires. Regression: E1M1
    StarbaseInnerProximity firing Graff's greeting at mission load,
    concurrent with the opening Liu briefing."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(50.0, 0.0, 0.0)  # already inside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        pCheck.Evaluate(anchor)   # first eval: baseline (inside), no fire
        pCheck.Evaluate(anchor)   # still inside, no transition, no fire
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert fired == []


def test_check_proximity_force_still_fires_when_already_inside():
    """The explicit immediate-check path (force=True, used by CheckProximity)
    still fires for an already-inside object — only the per-tick Evaluate path
    is baseline-gated."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(50.0, 0.0, 0.0)  # inside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        pCheck._anchor = anchor
        pCheck._evaluate_one(target, force=True)
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert fired == [1]


def test_evaluate_does_not_re_fire_while_object_stays_inside():
    """Once an object has crossed inside, repeated Evaluate calls while it
    stays inside don't re-fire the event. Only transitions fire."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(500.0, 0.0, 0.0)  # outside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        pCheck.Evaluate(anchor)  # baseline (outside); no fire
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)  # transition outside→inside; fire
        pCheck.Evaluate(anchor)  # no transition; should not fire
        pCheck.Evaluate(anchor)  # no transition; should not fire
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert len(fired) == 1


def test_evaluate_fires_again_on_exit_then_re_enter():
    """Object enters → fire. Exits → no fire (we only watch INSIDE
    transitions here). Re-enters → fire again."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(500.0, 0.0, 0.0)  # outside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        pCheck.Evaluate(anchor)             # baseline (outside); no fire
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)             # entered; fire
        target.SetTranslateXYZ(500.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)             # outside; no fire
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)             # re-entered; fire
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert len(fired) == 2


def test_evaluate_skips_objects_with_no_location():
    """Defensive: watched object whose GetWorldLocation is missing or
    returns None is silently skipped, not crashed on."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)

    class Stripped:
        pass

    pCheck.AddObjectToCheckList(Stripped(), ProximityCheck.TT_INSIDE)
    # Must not raise.
    pCheck.Evaluate(anchor)


def test_evaluate_event_destination_is_the_watched_object():
    """The fired event's destination is the watched object so SDK handlers
    that filter by target (ET_DELETE_OBJECT_PUBLIC pattern) match
    correctly."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(500.0, 0.0, 0.0)  # outside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    captured = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: captured.append(evt.GetDestination())
    try:
        pCheck.Evaluate(anchor)             # baseline (outside); no fire
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)             # entered; fire
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert captured == [target]
