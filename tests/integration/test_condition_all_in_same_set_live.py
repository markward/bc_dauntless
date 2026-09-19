"""ConditionAllInSameSet must follow ships between sets with NO hand-posted
events — the engine's own set add/remove must drive it. Before spec #4 it
froze at its construction value."""
import pytest

import App
from engine.appc.ai import ConditionScript_Create
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


def _set(name):
    s = App.SetClass_Create(); s.SetName(name); App.g_kSetManager._sets[name] = s
    return s


def _ship():
    s = ShipClass(); s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    return s


def test_all_in_same_set_tracks_a_ship_leaving_and_returning():
    a, b = _set("A"), _set("B")
    s1, s2 = _ship(), _ship()
    a.AddObjectToSet(s1, "One"); a.AddObjectToSet(s2, "Two")

    cond = ConditionScript_Create("Conditions.ConditionAllInSameSet",
                                  "ConditionAllInSameSet", "One", "Two")
    cond.SetActive()
    assert cond._instance is not None, cond._init_error
    assert cond.GetStatus() == 1

    a.RemoveObjectFromSet("Two"); b.AddObjectToSet(s2, "Two")
    assert cond.GetStatus() == 0, "ship moved to another set but the condition never heard"

    b.RemoveObjectFromSet("Two"); a.AddObjectToSet(s2, "Two")
    assert cond.GetStatus() == 1, "ship came back but the condition never re-evaluated"
