"""Activation smoke for AI.Compound.Parts.EvadeTorps.

SDK Parts/EvadeTorps.py: CreateAI(pShip, sTorpSource=None, dKeywords={})
returns a ConditionalAI named "IncomingTorps" wrapping a PlainAI named
"EvadeTorps". Default flags → EvalFunc returns US_DONE.

This is an activation smoke per Slice D1 spec — we don't exercise the
PlainAI Update body (D2 scope)."""
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


def test_evade_torps_create_ai_returns_conditional_ai_wrapping_plain_ai():
    ours = _build_scene()
    import AI.Compound.Parts.EvadeTorps as evade_torps
    ai = evade_torps.CreateAI(ours)
    assert isinstance(ai, ConditionalAI), f"expected ConditionalAI, got {type(ai).__name__}"
    assert ai.GetName() == "IncomingTorps"
    contained = ai._contained_ai
    assert isinstance(contained, PlainAI), f"expected PlainAI contained, got {type(contained).__name__}"
    assert contained.GetName() == "EvadeTorps"


def test_evade_torps_tick_does_not_crash():
    ours = _build_scene()
    import AI.Compound.Parts.EvadeTorps as evade_torps
    ai = evade_torps.CreateAI(ours)
    # Default: AvoidTorps flag unset → EvalFunc returns DONE → no crash.
    tick_ai(ai, game_time=0.01)
