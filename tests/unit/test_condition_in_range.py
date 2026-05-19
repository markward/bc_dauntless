"""End-to-end tests for SDK Conditions.ConditionInRange.

Depends on ProximityCheck + the per-tick evaluator (Task 4). The
condition watches sObject1's position; when any of lsObjectNames is
within fDistance, status flips to 1."""
import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.planet import evaluate_proximity_checks
from engine.appc.ships import ShipClass


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


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
