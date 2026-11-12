"""App.TGCondition_Cast — heatmap 122/130.

MissionLib.ConditionChangedRedirect:2536 does
    pCondition = App.TGCondition_Cast(pEvent.GetSource())
    bStatus = pCondition.GetStatus()
and forwards bStatus to the mission's handler. Undefined, bStatus was a
truthy stub on BOTH the 0->1 and 1->0 edges, so E7M6's g_bInOrbit never
cleared. E2M0.py:156 goes further and looks the condition up by id via
TGObject_GetTGObjectPtr, which needs conditions in the id registry."""
import gc
import weakref

import pytest

import App
from engine.appc.ai import TGCondition, ConditionScript_Create


def test_cast_is_real_and_type_checks():
    assert not isinstance(App.TGCondition_Cast, App._NamedStub)
    c = TGCondition()
    assert App.TGCondition_Cast(c) is c
    assert App.TGCondition_Cast(object()) is None
    assert App.TGCondition_Cast(None) is None


def test_condition_script_is_a_tgcondition_for_the_cast():
    cs = ConditionScript_Create("Conditions.ConditionFlagSet", "ConditionFlagSet", {}, "x")
    assert App.TGCondition_Cast(cs) is cs


def test_condition_is_reachable_by_object_id():
    c = TGCondition()
    assert App.TGObject_GetTGObjectPtr(c.GetObjID()) is c
    cs = ConditionScript_Create("Conditions.ConditionFlagSet", "ConditionFlagSet", {}, "x")
    assert App.TGObject_GetTGObjectPtr(cs.GetObjID()) is cs


def test_condition_script_get_by_id_still_resolves():
    from engine.appc.ai import ConditionScript_GetByID
    cs = ConditionScript_Create("Conditions.ConditionFlagSet", "ConditionFlagSet", {}, "x")
    assert ConditionScript_GetByID(cs.GetObjID()) is cs


def test_condition_changed_redirect_passes_the_real_status():
    """The MissionLib path end to end: a condition flipping 1 -> 0 must hand
    the handler 0, not a truthy stub.

    MissionLib.CallFunctionWhenConditionChanges(pMission, sModule, sFunction,
    pCondition) (MissionLib.py:2462) wires a ConditionEventCreator + a
    TGStringEvent whose source is the condition and destination is the
    mission, then registers pMission.AddPythonFuncHandlerForInstance(...,
    "MissionLib.ConditionChangedRedirect"). ConditionChangedRedirect
    (:2531) does App.TGCondition_Cast(pEvent.GetSource()).GetStatus() and
    forwards it to __import__(sModule) + getattr(sModule, sFunction).
    __import__ is top-level only, so the probe handler has to live on the
    MissionLib module itself.
    """
    import MissionLib
    from engine.core.game import Mission

    seen = []

    def handler(status):
        seen.append(status)

    MissionLib._probe_handler = handler

    mission = Mission()
    c = TGCondition()
    MissionLib.CallFunctionWhenConditionChanges(mission, "MissionLib", "_probe_handler", c)
    from engine.appc.ai import deliver_condition_events
    c.SetStatus(1)
    deliver_condition_events()      # a tick boundary between the two flips
    c.SetStatus(0)
    deliver_condition_events()

    assert seen[-2:] == [1, 0]


def test_condition_registry_entry_does_not_keep_it_alive():
    """The id-registry entry must be weak. A strong entry would make every
    TGCondition immortal for the life of the process -- see
    test_tgcondition_del_runs_when_last_reference_dropped for why that
    matters."""
    c = TGCondition()
    cid = c.GetObjID()
    del c
    gc.collect()
    assert App.TGObject_GetTGObjectPtr(cid) is None


def test_tgcondition_del_runs_when_last_reference_dropped():
    """Direct proof of the mechanism engine.core.ids.register_weak exists
    for: a TGCondition with real teardown in __del__ (mirroring SDK
    condition scripts -- ConditionInRange, ConditionSingleShieldBelow and
    ConditionPulseReady all define one) is reachable by id while it is
    alive, and its __del__ actually runs once the last Python reference is
    dropped and collected -- a strong id-registry entry would keep it (and
    every condition ever constructed) alive for the rest of the process,
    and that teardown would never fire."""
    events = []

    class _TeardownCondition(TGCondition):
        def __del__(self):
            events.append("torn down")

    c = _TeardownCondition()
    cid = c.GetObjID()
    assert App.TGObject_GetTGObjectPtr(cid) is c

    del c
    gc.collect()

    assert events == ["torn down"]
    assert App.TGObject_GetTGObjectPtr(cid) is None


def test_condition_script_del_still_runs():
    """ConditionInRange.__del__ (Conditions/ConditionInRange.py) removes its
    ProximityCheck: `if self.pProx: self.pProx.RemoveAndDelete()`. Constructor
    args + set fixture mirror tests/unit/test_condition_in_range.py.
    The wrapper holds its owner weakly (TGPythonInstanceWrapper.SetPyWrapper),
    so the instance goes with its last outside reference even though the
    wrapper itself stays in the id registry."""
    from engine.appc.ships import ShipClass

    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()

    pSet = App.SetClass_Create()
    pSet.SetName("S")
    anchor = ShipClass()
    anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(anchor, "Anchor")
    target = ShipClass()
    target.SetTranslateXYZ(50.0, 0.0, 0.0)
    pSet.AddObjectToSet(target, "Target")
    App.g_kSetManager._sets["S"] = pSet

    cs = ConditionScript_Create(
        "Conditions.ConditionInRange", "ConditionInRange", 100.0, "Anchor", "Target"
    )
    assert cs._instance is not None, cs._init_error
    instance_ref = weakref.ref(cs._instance)

    del cs, anchor, target, pSet
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    gc.collect()

    assert instance_ref() is None
