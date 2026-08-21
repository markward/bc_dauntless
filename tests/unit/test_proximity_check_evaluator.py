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


def test_evaluate_ignores_a_watched_object_in_a_different_set():
    """THE mission-load regression, fixed at its cause.

    E1M1.py:913-917 creates the Starbase 12 proximity pair during mission
    setup, anchored on the starbase (in the "Starbase12" set) and watching the
    player -- who at that moment is still in "DryDock". Comparing raw world
    positions, both sit near their own set's origin, so the player read as
    INSIDE the 690 GU sphere and Graff's greeting fired at mission load, over
    the opening Liu briefing.

    BC cannot have that bug: MissionLib.ProximityCheck:199 registers the check
    with `pSet.GetProximityManager()` -- the manager is PER SET, so an object
    in another set is simply not among the objects it considers. Set membership
    is the real gate; a first-eval baseline flag was standing in for it, and
    that flag also suppressed the repeat firing E1M1's dock gate depends on."""
    from engine.appc.sets import SetClass_Create

    dry_dock = SetClass_Create()
    starbase12 = SetClass_Create()

    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(690.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    starbase12.AddObjectToSet(anchor, "Starbase 12")
    # Well inside the radius by raw coordinates, but a set away.
    target = ShipClass(); target.SetTranslateXYZ(50.0, 0.0, 0.0)
    dry_dock.AddObjectToSet(target, "player")
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        for _ in range(10):
            pCheck.Evaluate(anchor)
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert fired == []


def test_evaluate_fires_once_the_object_joins_the_anchors_set():
    """The other half: the same object, once it warps into the anchor's set,
    is evaluated normally."""
    from engine.appc.sets import SetClass_Create

    dry_dock = SetClass_Create()
    starbase12 = SetClass_Create()

    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(690.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    starbase12.AddObjectToSet(anchor, "Starbase 12")
    target = ShipClass(); target.SetTranslateXYZ(50.0, 0.0, 0.0)
    dry_dock.AddObjectToSet(target, "player")
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    # Count ONLY our proximity event: moving the ship between sets posts
    # ET_ENTERED_SET/ET_EXITED_SET through this same manager.
    App.g_kEventManager.AddEvent = (
        lambda evt: fired.append(1) if evt.GetEventType() == 999 else None)
    try:
        pCheck.Evaluate(anchor)
        assert fired == []
        dry_dock.RemoveObjectFromSet("player")
        starbase12.AddObjectToSet(target, "player")
        pCheck.Evaluate(anchor)
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert fired == [1]


def test_check_proximity_force_still_fires_when_already_inside():
    """The explicit immediate-check path (force=True, used by CheckProximity)
    fires for an already-inside object. Under level triggering `force` no
    longer has to bypass anything — the object matches, so it fires — but the
    path stays pinned because CheckProximity is published SDK surface
    (sdk/.../App.py:6172) that callers use for an answer right now."""
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


def test_evaluate_keeps_firing_while_the_object_matches():
    """LEVEL-triggered, not edge-triggered: the check fires on every
    evaluation for as long as the object matches its trigger type.

    This is the contract E1M1's dock gate depends on. The Graff cutscene runs
    off the FIRST firing of StarbaseInnerProximity and only sets g_bGraffHailed
    at its very end (EnableDockButton, E1M1.py:2934). The line that actually
    clears g_bDockDisabled and enables the Helm > Dock button lives back in
    StarbaseInnerProximity (:1597) and needs a LATER firing to run -- while the
    player is parked inside the 690 GU sphere and never leaves it. Edge
    triggering made that second firing impossible, so Dock stayed greyed out
    forever.

    BC's own scripts prove the semantics: Conditions/ConditionInRange.
    ProximityEvent:296-297 re-arms the object to the OPPOSITE trigger type the
    instant it fires ("Trigger again if this goes outside") -- pointless under
    edge triggering -- and every one-shot handler in the SDK disarms itself
    with RemoveAndDelete()/RemoveObjectFromCheckList() as its first act."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(500.0, 0.0, 0.0)  # outside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        pCheck.Evaluate(anchor)             # outside: no match, no fire
        assert fired == []
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        for _ in range(5):
            pCheck.Evaluate(anchor)         # parked inside: fires every time
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert len(fired) == 5


def test_evaluate_stops_firing_when_the_object_stops_matching():
    """Level-triggered still means CONDITIONAL: leave the radius and a
    TT_INSIDE watch goes quiet again."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(50.0, 0.0, 0.0)   # inside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        pCheck.Evaluate(anchor)
        pCheck.Evaluate(anchor)
        target.SetTranslateXYZ(500.0, 0.0, 0.0)                    # left
        for _ in range(5):
            pCheck.Evaluate(anchor)
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert len(fired) == 2


def test_condition_in_range_rearm_idiom_stops_the_repeat():
    """The SDK's own way of turning the level-triggered stream into one event
    per crossing, and the reason we know the stream exists at all.

    Conditions/ConditionInRange.ProximityEvent flips the object to the
    opposite trigger type as soon as it fires. Replaying that here must yield
    exactly one event per direction change, not one per tick."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(500.0, 0.0, 0.0)  # outside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []

    def _rearm(evt):
        fired.append(pCheck.GetTriggerType(target))
        # Exactly ConditionInRange.py:296-297 / :306-307.
        flipped = (ProximityCheck.TT_OUTSIDE
                   if pCheck.GetTriggerType(target) == ProximityCheck.TT_INSIDE
                   else ProximityCheck.TT_INSIDE)
        pCheck.SetTriggerType(target, flipped)

    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = _rearm
    try:
        for _ in range(5):
            pCheck.Evaluate(anchor)         # outside, armed INSIDE: quiet
        assert fired == []
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        for _ in range(5):
            pCheck.Evaluate(anchor)         # enters: one event, then re-armed
        assert fired == [ProximityCheck.TT_INSIDE]
        target.SetTranslateXYZ(500.0, 0.0, 0.0)
        for _ in range(5):
            pCheck.Evaluate(anchor)         # leaves: one more, re-armed again
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert fired == [ProximityCheck.TT_INSIDE, ProximityCheck.TT_OUTSIDE]


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
