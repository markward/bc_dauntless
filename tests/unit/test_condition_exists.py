"""End-to-end tests for SDK Conditions.ConditionExists running against
our engine. The condition class is loaded via _SDKFinder; the engine
surfaces it touches (ObjectGroup, g_kEventManager, TGPythonInstanceWrapper)
must all be in place for this to work."""
import pytest

import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.events import TGEvent_Create
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


def test_condition_exists_initial_status_when_object_present():
    """Object 'Bart' is already in a set when the condition is created →
    status should be 1 immediately."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["S"] = pSet

    cs = ConditionScript_Create("Conditions.ConditionExists",
                                "ConditionExists", "Bart")
    assert cs._instance is not None, (
        f"ConditionExists failed to instantiate: {cs._init_error}"
    )
    assert cs.GetStatus() == 1


def test_condition_exists_initial_status_when_object_absent():
    """Object 'Bart' is NOT in any set → status 0."""
    _reset_app_state()
    cs = ConditionScript_Create("Conditions.ConditionExists",
                                "ConditionExists", "Bart")
    assert cs._instance is not None, cs._init_error
    assert cs.GetStatus() == 0


def test_condition_exists_flips_to_zero_on_delete_event():
    """Object exists, condition is 1. Fire ET_DELETE_OBJECT_PUBLIC for it
    → condition flips to 0."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["S"] = pSet

    cs = ConditionScript_Create("Conditions.ConditionExists",
                                "ConditionExists", "Bart")
    assert cs.GetStatus() == 1

    # Simulate the delete event.
    evt = TGEvent_Create()
    evt.SetEventType(App.ET_DELETE_OBJECT_PUBLIC)
    evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)

    assert cs.GetStatus() == 0


def test_condition_exists_flips_to_one_on_entered_set_event():
    """Object isn't in any set yet → condition is 0. Add the object to a
    set → the real producer (ObjectGroup.broadcast_membership, spec #4)
    posts ET_OBJECT_GROUP_OBJECT_ENTERED_SET and the condition flips to 1."""
    _reset_app_state()
    cs = ConditionScript_Create("Conditions.ConditionExists",
                                "ConditionExists", "Bart")
    assert cs.GetStatus() == 0

    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["S"] = pSet

    assert cs.GetStatus() == 1
