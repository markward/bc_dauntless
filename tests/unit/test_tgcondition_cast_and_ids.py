"""App.TGCondition_Cast — heatmap 122/130.

MissionLib.ConditionChangedRedirect:2536 does
    pCondition = App.TGCondition_Cast(pEvent.GetSource())
    bStatus = pCondition.GetStatus()
and forwards bStatus to the mission's handler. Undefined, bStatus was a
truthy stub on BOTH the 0->1 and 1->0 edges, so E7M6's g_bInOrbit never
cleared. E2M0.py:156 goes further and looks the condition up by id via
TGObject_GetTGObjectPtr, which needs conditions in the id registry."""
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
    c.SetStatus(1)
    c.SetStatus(0)

    assert seen[-2:] == [1, 0]
