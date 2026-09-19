"""ET_DELETE_OBJECT_PUBLIC — spec #5. Only constants_generated.py:345 and a
docstring mentioned it; 14 SDK files subscribe. ConditionExists never
returned to 0 after its target died."""
import pytest

import App
from engine.appc import ship_death
from engine.appc.ai import ConditionScript_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    ship_death.reset()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _scene():
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ship, "Bart")
    cond = ConditionScript_Create("Conditions.ConditionExists", "ConditionExists", "Bart")
    cond.SetActive()
    assert cond.GetStatus() == 1
    return pSet, ship, cond


def test_delete_object_from_set_drops_condition_exists():
    pSet, ship, cond = _scene()
    pSet.DeleteObjectFromSet("Bart")
    assert cond.GetStatus() == 0


def test_end_of_death_linger_drops_condition_exists():
    pSet, ship, cond = _scene()
    ship_death._remove(ship)
    assert cond.GetStatus() == 0


def test_delete_me_sweep_drops_condition_exists():
    from engine import host_loop
    pSet, ship, cond = _scene()
    ship.SetDeleteMe(1)
    host_loop._process_object_deletions()
    assert cond.GetStatus() == 0


def test_a_plain_set_move_is_not_a_delete():
    pSet, ship, cond = _scene()
    other = App.SetClass_Create(); other.SetName("T"); App.g_kSetManager._sets["T"] = other
    pSet.RemoveObjectFromSet("Bart"); other.AddObjectToSet(ship, "Bart")
    assert cond.GetStatus() == 1
