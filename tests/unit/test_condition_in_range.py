"""End-to-end tests for SDK Conditions.ConditionInRange.

Depends on ProximityCheck + the per-tick evaluator. The condition
watches sObject1's position; when any of lsObjectNames is within
fDistance, status flips to 1."""
import pytest

import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.planet import evaluate_proximity_checks
from engine.appc.ships import ShipClass


def _reset_app_state():
    """Clear ONLY the state these tests touch:
      - g_kSetManager._sets (re-populated per test)
      - g_kEventManager._method_handlers (Task 1 dict; conditions
        register here via AddBroadcastPythonMethodHandler)
    We deliberately do NOT clear _broadcast_handlers because that dict
    holds module-import-time registrations (e.g. KeyboardBinding._OnKeyboardEvent_Dispatch
    on event type 4096) that downstream weapon-hit / input-pipeline
    tests rely on. Conditions never write to _broadcast_handlers; they
    use _method_handlers."""
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate_app_state():
    """Reset condition-touched state BEFORE and AFTER each test so this
    file's tests are order-independent and don't leak into unrelated
    downstream tests."""
    _reset_app_state()
    yield
    _reset_app_state()


def _place_two_ships(d):
    """Anchor 'Anchor' at origin; target 'Target' at (d, 0, 0)."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(anchor, "Anchor")
    target = ShipClass(); target.SetTranslateXYZ(d, 0.0, 0.0)
    pSet.AddObjectToSet(target, "Target")
    App.g_kSetManager._sets["S"] = pSet
    return anchor, target


def test_initial_status_one_when_inside_radius():
    anchor, target = _place_two_ships(d=50.0)
    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", "Target")
    assert cs._instance is not None, cs._init_error
    # Initial state is 0; the proximity check fires on first evaluation.
    evaluate_proximity_checks()
    assert cs.GetStatus() == 1


def test_initial_status_zero_when_outside_radius():
    anchor, target = _place_two_ships(d=500.0)
    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", "Target")
    evaluate_proximity_checks()
    assert cs.GetStatus() == 0


def test_status_flips_when_target_moves_into_range():
    anchor, target = _place_two_ships(d=500.0)
    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", "Target")
    evaluate_proximity_checks()
    assert cs.GetStatus() == 0

    target.SetTranslateXYZ(50.0, 0.0, 0.0)
    evaluate_proximity_checks()
    assert cs.GetStatus() == 1


def test_status_zero_when_target_missing():
    """Anchor exists but Target doesn't → no proximity events → status 0."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    anchor = ShipClass(); pSet.AddObjectToSet(anchor, "Anchor")
    App.g_kSetManager._sets["S"] = pSet

    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", "Target")
    evaluate_proximity_checks()
    assert cs.GetStatus() == 0


def test_name_added_after_the_ship_entered_the_set_is_watched():
    """Quick Battle's order: CreateShip puts the enemy in the set, THEN its
    name joins the mission's enemy group. Only ET_OBJECT_GROUP_CHANGED
    (ConditionInRange.GroupChanged) can tell the condition. This is the
    shape of DynamicMusic's 'enemies within 400' check on a group."""
    anchor, target = _place_two_ships(d=50.0)
    enemies = App.ObjectGroup()
    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", enemies)
    evaluate_proximity_checks()
    assert cs.GetStatus() == 0
    enemies.AddName("Target")
    evaluate_proximity_checks()
    assert cs.GetStatus() == 1


def test_group_changes_do_not_multiply_the_conditions_handlers():
    """GroupChanged re-runs SetObjects, which re-registers GroupChanged."""
    _place_two_ships(d=500.0)
    enemies = App.ObjectGroup()
    ConditionScript_Create("Conditions.ConditionInRange",
                           "ConditionInRange", 100.0, "Anchor", enemies)
    for n in range(6):
        enemies.AddName("Ghost %d" % n)
    handlers = App.g_kEventManager._method_handlers[App.ET_OBJECT_GROUP_CHANGED]
    assert len(handlers) == 1
