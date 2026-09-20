"""SelectTarget's native-era event hooks (spec #14). BC's C++ CodeAISet
registered them; the Python copy is commented out (Preprocessors.py:1094-
1157). Without them a new target entering the set waited up to the 5 s
cadence before SelectTarget noticed."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.objects import ObjectGroup
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


def _ship(pSet, name, y=0.0):
    s = ShipClass(); s.SetTranslateXYZ(0, y, 0)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(s, name)
    return s


def _select_target_node(ours, group):
    import AI.Preprocessors
    node = PreprocessingAI_Create(ours, "Select")
    node.SetPreprocessingMethod(AI.Preprocessors.SelectTarget(group), "Update")
    stay = PlainAI_Create(ours, "Stay"); stay.SetScriptModule("Stay")
    node.SetContainedAI(stay)
    ours.SetAI(node)
    return node


def test_target_entering_the_set_forces_an_early_reselect():
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ours = _ship(pSet, "Ours")
    grp = ObjectGroup(); grp.AddName("Late")
    node = _select_target_node(ours, grp)
    tick_ai(node, 0.0); tick_ai(node, 1.0 / 60)        # cadence settles on tick 2
    assert node._next_update_time > 1.0, "precondition: SelectTarget is sleeping on its 5 s cadence"
    assert ours.GetTarget() is None

    _ship(pSet, "Late", y=600.0)                        # the target arrives
    assert node._next_update_time == 0.0, "TargetEnteredSet never called ForceUpdate"
    tick_ai(node, 2.0 / 60)
    assert ours.GetTarget() is not None and ours.GetTarget().GetName() == "Late"


def test_our_ship_entering_a_set_forces_an_early_reselect():
    a = App.SetClass_Create(); a.SetName("A"); App.g_kSetManager._sets["A"] = a
    b = App.SetClass_Create(); b.SetName("B"); App.g_kSetManager._sets["B"] = b
    ours = _ship(a, "Ours")
    grp = ObjectGroup(); grp.AddName("Enemy")
    node = _select_target_node(ours, grp)
    tick_ai(node, 0.0); tick_ai(node, 1.0 / 60)
    assert node._next_update_time > 1.0
    a.RemoveObjectFromSet("Ours"); b.AddObjectToSet(ours, "Ours")
    assert node._next_update_time == 0.0, "OurShipEnteredSet never called ForceUpdate"


def test_target_decloaking_forces_an_early_reselect():
    """A ship in our target group has a cloaking device; when it decloaks
    (StopCloaking fires ET_DECLOAK_BEGINNING with the ship as destination),
    ObjectDecloaked should ForceUpdate so SelectTarget re-rates it without
    waiting out the 5 s cadence."""
    from engine.appc.subsystems import CloakingSubsystem

    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ours = _ship(pSet, "Ours")
    cloaked = _ship(pSet, "Cloaked", y=600.0)
    cloaked.SetCloakingSubsystem(CloakingSubsystem("Cloak"))
    cloaked.GetCloakingSubsystem().InstantCloak()

    grp = ObjectGroup(); grp.AddName("Cloaked")
    node = _select_target_node(ours, grp)
    tick_ai(node, 0.0); tick_ai(node, 1.0 / 60)
    assert node._next_update_time > 1.0, "precondition: SelectTarget is sleeping on its 5 s cadence"

    cloaked.GetCloakingSubsystem().StopCloaking()       # fires ET_DECLOAK_BEGINNING, destination=cloaked ship
    assert node._next_update_time == 0.0, "ObjectDecloaked never called ForceUpdate"
