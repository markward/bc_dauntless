"""Activation smoke for AI.Compound.Parts.SweepPhasers.

SDK Parts/SweepPhasers.py: CreateAI(pShip, sTarget, fSpeed, dKeywords)
returns a PriorityListAI named "PriorityList" with 2 children:
ConditionalAI("UseSideArcs", priority 1) and PlainAI("PhaserSweep",
priority 2)."""
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


def test_sweep_phasers_create_ai_returns_priority_list_with_two_children():
    ours, _target = _build_scene()
    import AI.Compound.Parts.SweepPhasers as sweep
    ai = sweep.CreateAI(ours, "Target", 0.75, {})
    assert isinstance(ai, PriorityListAI)
    assert ai.GetName() == "PriorityList"
    # _ais is a list of (priority, ai) tuples for PriorityListAI.
    assert len(ai._ais) == 2
    names = [child.GetName() for _prio, child in ai._ais]
    assert "UseSideArcs" in names
    assert "PhaserSweep" in names


def test_sweep_phasers_tick_does_not_crash():
    ours, _target = _build_scene()
    import AI.Compound.Parts.SweepPhasers as sweep
    ai = sweep.CreateAI(ours, "Target", 0.75, {})
    tick_ai(ai, game_time=0.01)
