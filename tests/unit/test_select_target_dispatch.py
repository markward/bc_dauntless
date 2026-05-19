"""Unit tests for SelectTarget.Update + external-SetTarget-dispatch
chain. Verifies the chosen target gets propagated to the ship and to
every leaf AI registered via RegisterExternalFunction."""
import pytest

import App
from engine.appc.ai import (
    PreprocessingAI_Create, PlainAI_Create, PriorityListAI_Create,
)
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _kitted_ship(x, y, z):
    """ShipClass at (x,y,z) with hull + empty 6-face shield subsystem so
    SelectTarget.GetTargetRating (which unconditionally pulls hull +
    shield percentages off every ShipClass target) doesn't NPE. Mirrors
    the rating-test pattern in test_select_target_rating._make_target_ship_at."""
    s = ShipClass(); s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    s._shield_subsystem = ShieldSubsystem("Shd")
    return s


def _setup_scene_with_three_targets():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")

    # 3 targets in front, at distances 50, 200, 500.
    t1 = _kitted_ship(0, 50, 0);  pSet.AddObjectToSet(t1, "Close")
    t2 = _kitted_ship(0, 200, 0); pSet.AddObjectToSet(t2, "Mid")
    t3 = _kitted_ship(0, 500, 0); pSet.AddObjectToSet(t3, "Far")
    return ours, t1, t2, t3


def _wire_select_target(ours, *target_names):
    from AI.Preprocessors import SelectTarget
    pp = PreprocessingAI_Create(ours, "SelectPP")
    # SDK's Update gates pShip.SetTarget on pCodeAI.HasFocus(); ai_driver
    # owns focus in normal play. In a headless unit test we grant focus
    # directly so the SetTarget dispatch path runs.
    pp._has_focus = True
    grp = ObjectGroup()
    for n in target_names:
        grp.AddName(n)
    inst = SelectTarget(grp); inst.pCodeAI = pp
    # SDK seeds dDamageReceived inside CodeAISet/DamageEvent, both wired
    # by the optimized C++ Update path we don't run. Init directly so
    # GetTargetRating's `has_key` lookup has a dict to query.
    inst.dDamageReceived = {}
    # __init__ leaves the event-handler setup commented out ("commented out
    # because this is work that would need to be undone by the optimized
    # version"). Provide a real TGPythonInstanceWrapper so UpdateTargetInfo's
    # AddBroadcastPythonMethodHandler calls don't trip on the missing attr.
    inst.pEventHandler = App.TGPythonInstanceWrapper()
    inst.pEventHandler.SetPyWrapper(inst)
    pp.SetPreprocessingMethod(inst, "Update")
    return inst, pp


def test_update_picks_closest_target_under_default_weights():
    """Default weights → distance dominates; closest target wins."""
    ours, close, mid, far = _setup_scene_with_three_targets()
    inst, pp = _wire_select_target(ours, "Close", "Mid", "Far")
    inst.Update(dEndTime=999.0)
    assert inst.sCurrentTarget == "Close"


def test_update_calls_set_target_on_ship_when_bSetShipTarget_is_one():
    """bSetShipTarget=1 (default) → pShip.SetTarget(pChosen) fires."""
    ours, close, _mid, _far = _setup_scene_with_three_targets()
    inst, _pp = _wire_select_target(ours, "Close")
    assert inst.bSetShipTarget == 1
    inst.Update(dEndTime=999.0)
    assert ours.GetTarget() is close


def test_update_does_not_set_ship_target_when_disabled():
    """DontSetShipTarget() → pShip.SetTarget is NOT called."""
    ours, _close, _mid, _far = _setup_scene_with_three_targets()
    inst, _pp = _wire_select_target(ours, "Close")
    inst.DontSetShipTarget()
    ours.SetTarget(None)  # baseline
    inst.Update(dEndTime=999.0)
    assert ours.GetTarget() is None


def test_update_dispatches_set_target_to_contained_leaf_with_registered_function():
    """A PlainAI inside the contained tree, registered with
    RegisterExternalFunction("SetTarget", {"FunctionName": "SetObj"}),
    has its `SetObj(target_name)` method called when SelectTarget picks."""
    ours, _close, _mid, _far = _setup_scene_with_three_targets()
    inst, pp = _wire_select_target(ours, "Close", "Mid", "Far")

    # Build a leaf that registers a SetTarget hook + records calls.
    leaf = PlainAI_Create(ours, "Leaf")
    received = []

    class _Inst:
        def SetObj(self, name):
            received.append(name)

    leaf._script_instance = _Inst()
    leaf.RegisterExternalFunction("SetTarget", {"FunctionName": "SetObj"})
    pp.SetContainedAI(leaf)

    inst.Update(dEndTime=999.0)
    assert received == ["Close"]


def test_update_with_no_targets_returns_skip_dormant():
    """SDK contract: bCallSetTargetFuncsWithNoTarget=0 (default) +
    no targets in group → return PS_SKIP_DORMANT."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _kitted_ship(0, 0, 0)
    pSet.AddObjectToSet(ours, "Ours")

    inst, _pp = _wire_select_target(ours)  # empty target group
    result = inst.Update(dEndTime=999.0)
    assert result == App.PreprocessingAI.PS_SKIP_DORMANT
