"""Activation smoke for AI.Compound.Parts.WarpBeforeDeath.

SDK Parts/WarpBeforeDeath.py: CreateAI(pShip, dKeywords, fFraction=0.1)
returns a ConditionalAI named "WarpOutBeforeDeath" wrapping a PlainAI
named "WarpOut" (script module: "Warp"). Default flags → US_DONE."""
import pytest

import App
from engine.appc.ai import ConditionalAI, PlainAI
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
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    return ours


def test_warp_before_death_create_ai_returns_conditional_ai_wrapping_warp_plain_ai():
    ours = _build_scene()
    import AI.Compound.Parts.WarpBeforeDeath as wbd
    ai = wbd.CreateAI(ours, {})
    assert isinstance(ai, ConditionalAI)
    assert ai.GetName() == "WarpOutBeforeDeath"
    contained = ai._contained_ai
    assert isinstance(contained, PlainAI)
    assert contained.GetName() == "WarpOut"


def test_warp_before_death_tick_does_not_crash():
    ours = _build_scene()
    import AI.Compound.Parts.WarpBeforeDeath as wbd
    ai = wbd.CreateAI(ours, {})
    tick_ai(ai, game_time=0.01)
