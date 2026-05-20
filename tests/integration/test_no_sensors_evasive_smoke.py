"""Activation smoke for AI.Compound.Parts.NoSensorsEvasive.

SDK Parts/NoSensorsEvasive.py: CreateAI(pShip) returns
ConditionalAI("SensorsDisabled") wrapping SequenceAI("LoopForever")
wrapping RandomAI("Random") with 4 PlainAI(ManeuverLoop) children."""
import pytest

import App
from engine.appc.ai import (
    ConditionalAI, SequenceAI, RandomAI, PlainAI,
)
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
    ours = ShipClass(); ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    return ours


def test_no_sensors_evasive_create_ai_returns_expected_tree():
    ours = _build_scene()
    import AI.Compound.Parts.NoSensorsEvasive as nse
    ai = nse.CreateAI(ours)
    assert isinstance(ai, ConditionalAI)
    assert ai.GetName() == "SensorsDisabled"
    loop = ai._contained_ai
    assert isinstance(loop, SequenceAI)
    assert loop.GetName() == "LoopForever"
    random_ai = loop._ais[0]
    assert isinstance(random_ai, RandomAI)
    assert random_ai.GetName() == "Random"
    assert len(random_ai._ais) == 4
    leaf_names = [c.GetName() for c in random_ai._ais]
    assert set(leaf_names) == {"DriftUp", "DriftDown", "DriftRight", "DriftLeft"}
    for c in random_ai._ais:
        assert isinstance(c, PlainAI)


def test_no_sensors_evasive_tick_does_not_crash():
    ours = _build_scene()
    import AI.Compound.Parts.NoSensorsEvasive as nse
    ai = nse.CreateAI(ours)
    tick_ai(ai, game_time=0.01)
