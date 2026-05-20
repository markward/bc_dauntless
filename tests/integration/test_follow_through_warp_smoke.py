"""Activation smoke for AI.Compound.FollowThroughWarp.

SDK FollowThroughWarp.py: CreateAI(pShip, sTarget, bWarpBlindly=0,
**dKeywords) returns SequenceAI("FollowThroughWarpSequence") wrapping
3 nested ConditionalAIs (outermost "TargetExistsInWrongSet", middle
"CheckStarbase12", innermost "CheckMissionWarping") around PlainAI
("WarpFollow", script module "FollowThroughWarp")."""
import pytest

import App
from engine.appc.ai import SequenceAI, ConditionalAI, PlainAI
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


def test_follow_through_warp_create_ai_returns_expected_tree():
    ours, _target = _build_scene()
    import AI.Compound.FollowThroughWarp as ftw
    ai = ftw.CreateAI(ours, "Target")
    assert isinstance(ai, SequenceAI)
    assert ai.GetName() == "FollowThroughWarpSequence"
    # Outermost ConditionalAI inside the sequence.
    outer = ai._ais[0]
    assert isinstance(outer, ConditionalAI)
    assert outer.GetName() == "TargetExistsInWrongSet"
    # Walk to the innermost PlainAI.
    middle = outer._contained_ai
    assert isinstance(middle, ConditionalAI)
    assert middle.GetName() == "CheckStarbase12"
    inner = middle._contained_ai
    assert isinstance(inner, ConditionalAI)
    assert inner.GetName() == "CheckMissionWarping"
    leaf = inner._contained_ai
    assert isinstance(leaf, PlainAI)
    assert leaf.GetName() == "WarpFollow"


def test_follow_through_warp_tick_does_not_crash():
    ours, _target = _build_scene()
    import AI.Compound.FollowThroughWarp as ftw
    ai = ftw.CreateAI(ours, "Target")
    tick_ai(ai, game_time=0.01)
