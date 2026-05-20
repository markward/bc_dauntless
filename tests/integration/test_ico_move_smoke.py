"""Activation smoke for AI.Compound.Parts.ICOMove.

SDK Parts/ICOMove.py: CreateAI(pShip, sTarget, dKeywords, fForwardBias=0.0)
returns PriorityListAI("ICOMovePriorities") with 3 children:
ConditionalAI("UseShields") priority 1, ConditionalAI("UseSideWeapons_2")
priority 2, PlainAI("ICO_MoveNoWeaponsNoShields") priority 3.

Most elaborate Part — nested PriorityListAI/ConditionalAI structure
with 4 PlainAI(IntelligentCircleObject) leaf instances."""
import pytest

import App
from engine.appc.ai import PriorityListAI, ConditionalAI, PlainAI
from engine.appc.ai_driver import tick_ai
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


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); pSet.AddObjectToSet(target, "Target")
    return ours, target


def test_ico_move_create_ai_returns_priority_list_with_three_children():
    ours, _target = _build_scene()
    import AI.Compound.Parts.ICOMove as ico
    ai = ico.CreateAI(ours, "Target", {})
    assert isinstance(ai, PriorityListAI)
    assert ai.GetName() == "ICOMovePriorities"
    assert len(ai._ais) == 3
    children_by_name = {c.GetName(): c for _prio, c in ai._ais}
    assert "UseShields" in children_by_name
    assert isinstance(children_by_name["UseShields"], ConditionalAI)
    assert "UseSideWeapons_2" in children_by_name
    assert isinstance(children_by_name["UseSideWeapons_2"], ConditionalAI)
    assert "ICO_MoveNoWeaponsNoShields" in children_by_name
    assert isinstance(children_by_name["ICO_MoveNoWeaponsNoShields"], PlainAI)


def test_ico_move_tick_does_not_crash():
    ours, _target = _build_scene()
    import AI.Compound.Parts.ICOMove as ico
    ai = ico.CreateAI(ours, "Target", {})
    tick_ai(ai, game_time=0.01)
