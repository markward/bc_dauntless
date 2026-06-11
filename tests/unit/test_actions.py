"""Unit tests for TGAction, TGSequence, TGScriptAction."""
import sys
import types
import pytest
import App
from engine.appc.actions import (
    TGAction, TGSequence, TGSequence_Create,
    TGScriptAction, TGScriptAction_Create,
    TGNullAction, TGAction_CreateNull,
    TGTimedAction, TGSoundAction, TGSoundAction_Create,
    TGActionManager, TGObjPtrEvent, TGObjPtrEvent_Create,
    TGAction_Cast,
)


# ── TGAction base ──────────────────────────────────────────────────────────────

def test_action_initially_not_playing():
    a = TGAction()
    assert not a.IsPlaying()


def test_action_play_marks_not_playing_after_completion():
    a = TGAction()
    a.Play()
    assert not a.IsPlaying()


def test_action_completed_fires_registered_events():
    fired = []
    mod = types.ModuleType("_test_action_cb")
    mod.on_done = lambda obj, ev: fired.append(ev.GetEventType())
    sys.modules["_test_action_cb"] = mod

    a = TGAction()
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_ACTION_COMPLETED)
    ev.SetDestination(App.g_kTGActionManager)
    a.AddCompletedEvent(ev)
    App.g_kTGActionManager.AddPythonFuncHandlerForInstance(
        App.ET_ACTION_COMPLETED, "_test_action_cb.on_done"
    )
    a.Completed()

    assert App.ET_ACTION_COMPLETED in fired
    del sys.modules["_test_action_cb"]
    App.g_kTGActionManager.RemoveHandlerForInstance(
        App.ET_ACTION_COMPLETED, "_test_action_cb.on_done"
    )


def test_action_completed_clears_events():
    a = TGAction()
    ev = App.TGEvent_Create()
    a.AddCompletedEvent(ev)
    a.Completed()
    # Second call should not fire again (list is cleared)
    a.Completed()  # must not raise


def test_null_action_play_does_nothing():
    null = TGAction_CreateNull()
    null.Play()  # must not raise
    assert not null.IsPlaying()


# ── TGSequence ─────────────────────────────────────────────────────────────────

def test_sequence_create_returns_sequence():
    s = TGSequence_Create()
    assert isinstance(s, TGSequence)


def test_sequence_add_action_increments_count():
    s = TGSequence_Create()
    s.AddAction(TGAction_CreateNull())
    assert s.GetNumActions() == 1


def test_sequence_play_runs_all_actions():
    played = []
    mod = types.ModuleType("_test_seq_cb")
    mod.cb = lambda pAction: played.append(True)
    sys.modules["_test_seq_cb"] = mod

    s = TGSequence_Create()
    s.AddAction(TGScriptAction_Create("_test_seq_cb", "cb"))
    s.AddAction(TGScriptAction_Create("_test_seq_cb", "cb"))
    s.Play()

    assert len(played) == 2
    del sys.modules["_test_seq_cb"]


def test_sequence_add_action_with_dependency_args():
    s = TGSequence_Create()
    dep = TGAction_CreateNull()
    a = TGScriptAction_Create("_test_seq_cb", "cb")
    s.AddAction(a, dep, 1.0)  # must not raise; dependency/delay ignored in Phase 1
    assert s.GetNumActions() == 1


def test_sequence_append_action():
    s = TGSequence_Create()
    s.AppendAction(TGAction_CreateNull())
    assert s.GetNumActions() == 1


def test_sequence_play_completes_self():
    s = TGSequence_Create()
    s.Play()
    assert not s.IsPlaying()


# ── TGScriptAction ─────────────────────────────────────────────────────────────

def test_script_action_create():
    a = TGScriptAction_Create("os.path", "join", "a", "b")
    assert isinstance(a, TGScriptAction)


def test_script_action_play_calls_function():
    called = []
    mod = types.ModuleType("_test_script_action")
    mod.handler = lambda pAction, x: called.append(x)
    sys.modules["_test_script_action"] = mod

    a = TGScriptAction_Create("_test_script_action", "handler", 42)
    a.Play()

    assert called == [42]
    del sys.modules["_test_script_action"]


def test_script_action_play_passes_self_as_first_arg():
    received = []
    mod = types.ModuleType("_test_script_action2")
    mod.handler = lambda pAction: received.append(pAction)
    sys.modules["_test_script_action2"] = mod

    a = TGScriptAction_Create("_test_script_action2", "handler")
    a.Play()

    assert received[0] is a
    del sys.modules["_test_script_action2"]


def test_script_action_missing_module_does_not_raise():
    a = TGScriptAction_Create("no.such.module", "func")
    a.Play()  # must not raise


def test_script_action_missing_func_does_not_raise():
    mod = types.ModuleType("_test_script_action3")
    sys.modules["_test_script_action3"] = mod

    a = TGScriptAction_Create("_test_script_action3", "no_such_func")
    a.Play()  # must not raise

    del sys.modules["_test_script_action3"]


def test_script_action_has_obj_id():
    a = TGScriptAction_Create("m", "f")
    assert isinstance(a.GetObjID(), int)


# ── TGObjPtrEvent ──────────────────────────────────────────────────────────────

def test_obj_ptr_event_roundtrip():
    ev = TGObjPtrEvent_Create()
    action = TGAction()
    ev.SetObjPtr(action)
    assert ev.GetObjPtr() is action


def test_obj_ptr_event_is_tgevent():
    from engine.appc.events import TGEvent
    ev = TGObjPtrEvent_Create()
    assert isinstance(ev, TGEvent)


# ── TGAction_Cast ──────────────────────────────────────────────────────────────

def test_tgaction_cast_returns_action():
    a = TGScriptAction_Create("m", "f")
    assert TGAction_Cast(a) is a


def test_tgaction_cast_non_action_returns_none():
    assert TGAction_Cast(object()) is None


# ── App-level wiring ───────────────────────────────────────────────────────────

def test_app_tgsequence_create():
    assert isinstance(App.TGSequence_Create(), TGSequence)


def test_app_tgscript_action_create():
    a = App.TGScriptAction_Create("os", "getcwd")
    assert isinstance(a, TGScriptAction)


def test_app_tgaction_create_null():
    assert isinstance(App.TGAction_CreateNull(), TGNullAction)


def test_app_g_ktg_action_manager_exists():
    assert isinstance(App.g_kTGActionManager, TGActionManager)


def test_app_tgobjptr_event_create():
    assert isinstance(App.TGObjPtrEvent_Create(), TGObjPtrEvent)


def test_tgobject_get_tgobject_ptr_roundtrip():
    a = TGScriptAction_Create("m", "f")
    obj_id = a.GetObjID()
    result = App.TGObject_GetTGObjectPtr(obj_id)
    assert result is a


# ── TGSequence_Cast ──────────────────────────────────────────────────────────

def test_tgsequence_cast_returns_sequence():
    from engine.appc.actions import TGSequence_Cast
    seq = App.TGSequence_Create()
    assert TGSequence_Cast(seq) is seq


def test_tgsequence_cast_returns_none_for_non_sequence():
    from engine.appc.actions import TGSequence_Cast
    assert TGSequence_Cast(App.TGAction_CreateNull()) is None
    assert TGSequence_Cast(None) is None


# ── TGActionManager named registry ───────────────────────────────────────────

def test_tg_action_manager_register_and_find():
    mgr = TGActionManager()
    a = App.TGAction_CreateNull()
    mgr.RegisterAction(a, "FriendlyFireWarning")
    assert mgr.FindAction("FriendlyFireWarning") is a
    assert mgr.IsRegistered("FriendlyFireWarning") == 1


def test_tg_action_manager_register_replaces_prior():
    """SDK pattern: re-registering under the same name replaces the prior."""
    mgr = TGActionManager()
    a = App.TGAction_CreateNull()
    b = App.TGAction_CreateNull()
    mgr.RegisterAction(a, "X")
    mgr.RegisterAction(b, "X")
    assert mgr.FindAction("X") is b


def test_tg_action_manager_unregister():
    mgr = TGActionManager()
    a = App.TGAction_CreateNull()
    mgr.RegisterAction(a, "X")
    mgr.UnregisterAction("X")
    assert mgr.IsRegistered("X") == 0
    assert mgr.FindAction("X") is None


def test_module_level_register_action_uses_singleton():
    """SDK call: ``App.TGActionManager_RegisterAction(pAction, "name")``
    routes to the global g_kTGActionManager."""
    a = App.TGAction_CreateNull()
    App.TGActionManager_RegisterAction(a, "TestAction")
    assert App.TGActionManager_FindAction("TestAction") is a
    App.TGActionManager_UnregisterAction("TestAction")


# ── TGCreditAction ───────────────────────────────────────────────────────────

def test_tg_credit_action_factory_records_args():
    ca = App.TGCreditAction_Create("Hello", None, 0.5, 0.025, 5, 0.25, 0.5, 12)
    assert isinstance(ca, App.TGCreditAction)
    assert ca._text == "Hello"


def test_tg_credit_action_set_color():
    ca = App.TGCreditAction_Create("X", None)
    ca.SetColor(0.1, 0.2, 0.3, 0.4)
    assert ca._color == (0.1, 0.2, 0.3, 0.4)


def test_tg_credit_action_set_default_color_round_trip():
    App.TGCreditAction_SetDefaultColor(0.65, 0.65, 1.0, 1.0)
    assert App.TGCreditAction_GetDefaultColor() == (0.65, 0.65, 1.0, 1.0)
    # New banner inherits the default at construction.
    ca = App.TGCreditAction_Create("X", None)
    assert ca._color == (0.65, 0.65, 1.0, 1.0)
    # Reset for subsequent tests.
    App.TGCreditAction_SetDefaultColor(1.0, 1.0, 1.0, 1.0)


def test_tg_credit_action_play_completes():
    ca = App.TGCreditAction_Create("X", None)
    ca.Play()
    assert ca.IsPlaying() is False


def test_tg_credit_action_justify_constants_distinct():
    cs = {
        App.TGCreditAction.JUSTIFY_LEFT,
        App.TGCreditAction.JUSTIFY_RIGHT,
        App.TGCreditAction.JUSTIFY_TOP,
        App.TGCreditAction.JUSTIFY_BOTTOM,
        App.TGCreditAction.JUSTIFY_CENTER,
    }
    assert len(cs) == 5


# ── TGConditionAction ────────────────────────────────────────────────────────

def test_tg_condition_action_starts_in_wait_state():
    ca = App.TGConditionAction_Create()
    assert ca.GetState() == App.TGConditionAction.TGCA_WAIT


def test_tg_condition_action_add_condition_subscribes():
    from engine.appc.ai import TGCondition
    ca = App.TGConditionAction_Create()
    cond = TGCondition()
    ca.AddCondition(cond)
    # Underlying TGCondition wired up to invoke ConditionChanged.
    assert ca in cond._handlers


def test_tg_condition_action_completes_on_condition_change():
    from engine.appc.ai import TGCondition
    ca = App.TGConditionAction_Create()
    cond = TGCondition()
    ca.AddCondition(cond)
    cond.SetActive()
    cond.SetStatus(1)
    assert ca.GetState() == App.TGConditionAction.TGCA_COMPLETED


def test_tg_condition_action_play_evaluates_existing_truthy_status():
    """If a condition is already truthy when Play() runs, complete immediately."""
    from engine.appc.ai import TGCondition
    ca = App.TGConditionAction_Create()
    cond = TGCondition()
    cond._status = 1   # bypass handler firing for setup
    ca.AddCondition(cond)
    ca.Play()
    assert ca.GetState() == App.TGConditionAction.TGCA_COMPLETED


def test_tg_condition_action_in_sequence():
    """SDK pattern: pSequence.AppendAction(pConditionAction); pSequence.AddAction(pNext, pConditionAction)."""
    seq = App.TGSequence_Create()
    ca = App.TGConditionAction_Create()
    seq.AppendAction(ca)
    next_action = App.TGAction_CreateNull()
    seq.AddAction(next_action, ca)
    assert seq.GetNumActions() == 2


# ── TGSequence step model ────────────────────────────────────────────────────

def test_add_action_stores_step_with_no_dependency():
    from engine.appc.actions import TGSequence_Create
    s = TGSequence_Create()
    a = App.TGAction_CreateNull()
    s.AddAction(a)
    assert s.GetNumActions() == 1
    assert s.GetAction(0) is a
    assert s._steps[0].dependency is None
    assert s._steps[0].delay == 0.0


def test_add_action_parses_dependency_and_delay_by_type():
    from engine.appc.actions import TGSequence_Create
    s = TGSequence_Create()
    dep = App.TGAction_CreateNull()
    a = App.TGAction_CreateNull()
    s.AddAction(a, dep, 1.5)
    step = s._steps[0]
    assert step.dependency is dep
    assert step.delay == 1.5


def test_add_action_delay_only_arg_is_delay_not_dependency():
    from engine.appc.actions import TGSequence_Create
    s = TGSequence_Create()
    a = App.TGAction_CreateNull()
    s.AddAction(a, 2.0)
    assert s._steps[0].dependency is None
    assert s._steps[0].delay == 2.0


def test_append_action_chains_to_previous_action():
    from engine.appc.actions import TGSequence_Create
    s = TGSequence_Create()
    first = App.TGAction_CreateNull()
    second = App.TGAction_CreateNull()
    s.AppendAction(first)
    s.AppendAction(second, 0.25)
    assert s._steps[0].dependency is None           # first chains to start
    assert s._steps[1].dependency is first          # second chains to first
    assert s._steps[1].delay == 0.25


def test_parse_extra_helper():
    from engine.appc.actions import _parse_extra
    dep = App.TGAction_CreateNull()
    assert _parse_extra(()) == (None, 0.0)
    assert _parse_extra((dep,)) == (dep, 0.0)
    assert _parse_extra((3,)) == (None, 3.0)
    assert _parse_extra((dep, 0.5)) == (dep, 0.5)
