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


# ── TGSequence synchronous launch engine ─────────────────────────────────────

class _RecordingAction(TGAction):
    """Test action that records the order in which it was played."""
    def __init__(self, log, tag):
        super().__init__()
        self._log = log
        self._tag = tag

    def _do_play(self):
        self._log.append(self._tag)


def test_add_action_roots_fire_in_parallel_on_play():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "a"))
    s.AddAction(_RecordingAction(log, "b"))
    s.Play()
    assert log == ["a", "b"]          # both roots fired


def test_append_action_zero_delay_chains_inline():
    log = []
    s = App.TGSequence_Create()
    s.AppendAction(_RecordingAction(log, "a"))
    s.AppendAction(_RecordingAction(log, "b"))   # depends on a, delay 0
    s.Play()
    assert log == ["a", "b"]          # b fired inline after a completed


def test_explicit_dependency_zero_delay_fires_inline():
    log = []
    s = App.TGSequence_Create()
    dep = _RecordingAction(log, "dep")
    s.AddAction(dep)
    s.AddAction(_RecordingAction(log, "next"), dep)
    s.Play()
    assert log == ["dep", "next"]


def test_sequence_not_playing_after_synchronous_completion():
    s = App.TGSequence_Create()
    s.AddAction(App.TGAction_CreateNull())
    s.Play()
    assert not s.IsPlaying()


def test_sequence_fires_own_completed_event_when_all_done():
    import sys, types
    fired = []
    mod = types.ModuleType("_test_seq_done")
    mod.on_done = lambda obj, ev: fired.append(True)
    sys.modules["_test_seq_done"] = mod
    App.g_kTGActionManager.AddPythonFuncHandlerForInstance(
        App.ET_ACTION_COMPLETED, "_test_seq_done.on_done")

    s = App.TGSequence_Create()
    s.AddAction(App.TGAction_CreateNull())
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_ACTION_COMPLETED)
    ev.SetDestination(App.g_kTGActionManager)
    s.AddCompletedEvent(ev)
    s.Play()

    assert fired == [True]
    App.g_kTGActionManager.RemoveHandlerForInstance(
        App.ET_ACTION_COMPLETED, "_test_seq_done.on_done")
    del sys.modules["_test_seq_done"]


def test_dependent_waits_for_dependency_listed_later():
    # 'b' is listed BEFORE its dependency 'a' in insertion order, so a pure
    # insertion-order engine would fire b first. The dependency engine must
    # fire a (the dependency) and only then b.
    log = []
    s = App.TGSequence_Create()
    a = _RecordingAction(log, "a")
    s.AddAction(_RecordingAction(log, "b"), a)   # b depends on a (listed first)
    s.AddAction(a)                                # a is a root (listed second)
    s.Play()
    assert log == ["a", "b"]


def test_replay_runs_steps_again():
    # A second Play() must re-run the sequence, not hang (step.started reset).
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "x"))
    s.Play()
    s.Play()
    assert log == ["x", "x"]


# ── TGSequence delay scheduling ──────────────────────────────────────────────

def _advance_game_time(seconds, step=1.0 / 60.0):
    """Advance g_kTimerManager in 60 Hz ticks for `seconds` of game time."""
    n = int(round(seconds / step))
    for _ in range(n):
        App.g_kTimerManager.tick(step)


def test_delayed_step_does_not_fire_before_delay():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "now"))
    s.AddAction(_RecordingAction(log, "later"),
                App.TGAction_CreateNull(), 0.5)
    s.Play()
    assert log == ["now"]                 # delayed step not fired yet
    _advance_game_time(0.25)
    assert log == ["now"]                 # still waiting at t=0.25


def test_delayed_step_fires_after_delay():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "now"))
    s.AddAction(_RecordingAction(log, "later"),
                App.TGAction_CreateNull(), 0.5)
    s.Play()
    _advance_game_time(0.6)               # past the 0.5s delay
    assert log == ["now", "later"]


def test_two_delayed_steps_fire_in_time_order():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "t0"))
    s.AddAction(_RecordingAction(log, "t05"), App.TGAction_CreateNull(), 0.5)
    s.AddAction(_RecordingAction(log, "t15"), App.TGAction_CreateNull(), 1.5)
    s.Play()
    _advance_game_time(0.6)
    assert log == ["t0", "t05"]
    _advance_game_time(1.0)               # total ~1.6s
    assert log == ["t0", "t05", "t15"]


# ── TGConditionAction deferred completion ────────────────────────────────────

def test_condition_action_play_stays_pending_when_unsatisfied():
    from engine.appc.ai import TGCondition
    ca = App.TGConditionAction_Create()
    cond = TGCondition()
    ca.AddCondition(cond)
    ca.Play()
    assert ca.GetState() == App.TGConditionAction.TGCA_WAIT
    assert ca.IsPlaying()                 # still pending, not completed


def test_sequence_step_waits_for_condition_flip():
    from engine.appc.ai import TGCondition
    log = []
    s = App.TGSequence_Create()
    cond = TGCondition()
    gate = App.TGConditionAction_Create()
    gate.AddCondition(cond)
    s.AddAction(gate)
    s.AddAction(_RecordingAction(log, "after"), gate)
    s.Play()
    assert log == []                      # gate pending -> dependent waits
    cond.SetActive()
    cond.SetStatus(1)                     # condition flips
    assert log == ["after"]              # dependent fires on completion


# ── TGSequence teardown ──────────────────────────────────────────────────────

def test_abort_cancels_pending_delay_timers():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "later"),
                App.TGAction_CreateNull(), 0.5)
    s.Play()
    assert len(s._pending_timers) == 1
    s.Abort()
    assert s._pending_timers == []
    _advance_game_time(1.0)
    assert log == []                      # timer was cancelled; never fired
    assert not s.IsPlaying()


def test_stop_cancels_pending_delay_timers():
    log = []
    s = App.TGSequence_Create()
    s.AddAction(_RecordingAction(log, "later"),
                App.TGAction_CreateNull(), 0.5)
    s.Play()
    s.Stop()
    assert s._pending_timers == []
    _advance_game_time(1.0)
    assert log == []


# ── TGSoundAction / TGCreditAction inline completion ─────────────────────────

def test_sound_action_completes_inline_so_chain_advances():
    # Regression: a step chained after a TGSoundAction must fire. The sound
    # action must complete inline (it previously never called Completed(),
    # hanging every dependent step — e.g. the probe-launch chain in
    # ScienceMenuHandlers).
    import sys, types
    log = []
    mod = types.ModuleType("_test_sound_chain")
    mod.after = lambda pAction: log.append("after")
    sys.modules["_test_sound_chain"] = mod

    s = App.TGSequence_Create()
    s.AppendAction(App.TGSoundAction_Create("ProbeLaunchTestSfx"))
    s.AppendAction(App.TGScriptAction_Create("_test_sound_chain", "after"))
    s.Play()

    assert log == ["after"]
    assert not s.IsPlaying()          # sequence self-completed
    del sys.modules["_test_sound_chain"]


def test_credit_action_completes_inline_so_chain_advances():
    import sys, types
    log = []
    mod = types.ModuleType("_test_credit_chain")
    mod.after = lambda pAction: log.append("after")
    sys.modules["_test_credit_chain"] = mod

    s = App.TGSequence_Create()
    s.AppendAction(App.TGCreditAction_Create("Hello", None))
    s.AppendAction(App.TGScriptAction_Create("_test_credit_chain", "after"))
    s.Play()

    assert log == ["after"]
    del sys.modules["_test_credit_chain"]


# ── TGAction._complete_after deferred completion ────────────────────────────

def _advance_real_time(seconds, step=1.0 / 60.0):
    """Advance g_kRealtimeTimerManager in 60 Hz ticks for `seconds`."""
    n = int(round(seconds / step))
    for _ in range(n):
        App.g_kRealtimeTimerManager.tick(step)


def test_complete_after_zero_completes_inline():
    a = TGAction()
    done = []
    a.Completed = lambda: done.append(True)  # type: ignore
    a._playing = True
    a._complete_after(0.0)
    assert done == [True]                      # inline, no timer


def test_complete_after_duration_defers_until_timer():
    a = TGAction()
    done = []
    real_completed = a.Completed
    a.Completed = lambda: (done.append(True), real_completed())  # type: ignore
    a._playing = True
    a._complete_after(0.5)
    assert done == []                          # not yet
    _advance_real_time(0.25)
    assert done == []                          # still waiting at t=0.25
    _advance_real_time(0.4)                    # past 0.5s total
    assert done == [True]                      # completed exactly once
    _advance_real_time(1.0)
    assert done == [True]                      # one-shot: no re-fire


def test_cancel_deferred_timer_prevents_completion():
    a = TGAction()
    done = []
    a.Completed = lambda: done.append(True)    # type: ignore
    a._playing = True
    a._complete_after(0.5)
    a._cancel_deferred_timer()
    _advance_real_time(1.0)
    assert done == []                          # cancelled before firing


def test_script_action_truthy_return_defers_completion():
    import sys, types
    mod = types.ModuleType("_test_script_defer")
    mod.deferred = lambda pAction: 1          # truthy => "I'll complete later"
    sys.modules["_test_script_defer"] = mod

    a = App.TGScriptAction_Create("_test_script_defer", "deferred")
    a.Play()
    assert a.IsPlaying()                       # deferred: NOT auto-completed
    del sys.modules["_test_script_defer"]


def test_script_action_falsy_return_auto_completes():
    import sys, types
    mod = types.ModuleType("_test_script_instant")
    mod.instant = lambda pAction: 0           # falsy => auto-complete
    sys.modules["_test_script_instant"] = mod

    a = App.TGScriptAction_Create("_test_script_instant", "instant")
    a.Play()
    assert not a.IsPlaying()                   # completed inline
    del sys.modules["_test_script_instant"]


def test_script_action_none_return_auto_completes():
    import sys, types
    mod = types.ModuleType("_test_script_none")
    mod.noret = lambda pAction: None
    sys.modules["_test_script_none"] = mod

    a = App.TGScriptAction_Create("_test_script_none", "noret")
    a.Play()
    assert not a.IsPlaying()
    del sys.modules["_test_script_none"]


def test_action_manager_completes_objptr_on_action_completed():
    owner = TGAction()
    done = []
    owner.Completed = lambda: done.append(True)   # type: ignore

    ev = App.TGObjPtrEvent_Create()
    ev.SetEventType(App.ET_ACTION_COMPLETED)
    ev.SetObjPtr(owner)
    App.g_kTGActionManager.ProcessEvent(ev)

    assert done == [True]


# ── TGSoundAction deferred completion ────────────────────────────────────────

def test_sound_action_defers_by_real_duration(monkeypatch):
    from engine.audio.tg_sound import TGSoundManager
    monkeypatch.setattr(TGSoundManager, "duration_for",
                        lambda self, name: 0.5, raising=True)
    a = App.TGSoundAction_Create("AnySfx")
    a.Play()
    assert a.IsPlaying()                       # gated on the 0.5s duration
    _advance_real_time(0.6)
    assert not a.IsPlaying()                    # completed after duration


def test_sound_action_zero_duration_completes_inline(monkeypatch):
    from engine.audio.tg_sound import TGSoundManager
    monkeypatch.setattr(TGSoundManager, "duration_for",
                        lambda self, name: 0.0, raising=True)
    a = App.TGSoundAction_Create("AnySfx")
    a.Play()
    assert not a.IsPlaying()                    # inline (synchronous preserved)


# ── CharacterAction speak-type deferral ──────────────────────────────────────

def test_character_speak_action_defers_by_duration(monkeypatch):
    import engine.appc.crew_speech as crew_speech
    monkeypatch.setattr(crew_speech, "emit",
                        lambda *a, **k: 0.5, raising=True)
    from engine.appc.ai import CharacterAction
    a = CharacterAction(None, CharacterAction.AT_SAY_LINE, "AnyLine")
    a.Play()
    assert a.IsPlaying()                       # gated on 0.5s line duration
    _advance_real_time(0.6)
    assert not a.IsPlaying()


def test_character_speak_zero_duration_inline(monkeypatch):
    import engine.appc.crew_speech as crew_speech
    monkeypatch.setattr(crew_speech, "emit",
                        lambda *a, **k: 0.0, raising=True)
    from engine.appc.ai import CharacterAction
    a = CharacterAction(None, CharacterAction.AT_SAY_LINE, "AnyLine")
    a.Play()
    assert not a.IsPlaying()                    # inline


def test_character_nonspeak_action_completes_inline():
    from engine.appc.ai import CharacterAction
    a = CharacterAction(None, CharacterAction.AT_TURN, None)
    a.Play()
    assert not a.IsPlaying()                    # non-speak: unchanged, inline


# ── Completed TGSequence id invalidation (MissionLib master-sequence contract) ──
#
# The original engine destroys a finished TGSequence, so its object id stops
# resolving. MissionLib.QueueActionToPlay relies on this: it stores the master
# sequence's id and appends every subsequent queued action onto it *until* the
# id goes invalid, at which point the next call starts a fresh, playing master.
# If a completed sequence's id kept resolving, every action queued after the
# first master completed would be appended onto a dead sequence and never fire
# (E1M2: Director Soams's viewscreen hail was silently dropped).

def test_completed_sequence_id_no_longer_resolves():
    s = App.TGSequence_Create()
    s.AddAction(App.TGAction_CreateNull())     # instantaneous -> completes inline
    sid = s.GetObjID()
    assert App.TGObject_GetTGObjectPtr(sid) is s   # resolvable while alive
    s.Play()
    assert not s.IsPlaying()                        # drained + completed
    assert App.TGObject_GetTGObjectPtr(sid) is None # id invalidated on completion


def test_playing_sequence_id_still_resolves():
    s = App.TGSequence_Create()
    cond = App.TGConditionAction_Create()          # stays pending (no condition)
    s.AddAction(cond)
    sid = s.GetObjID()
    s.Play()
    assert s.IsPlaying()                            # still waiting on cond
    assert App.TGObject_GetTGObjectPtr(sid) is s    # resolvable while playing


def test_replayed_sequence_id_resolves_again_then_reinvalidates():
    s = App.TGSequence_Create()
    s.AddAction(App.TGAction_CreateNull())
    sid = s.GetObjID()
    s.Play()
    assert App.TGObject_GetTGObjectPtr(sid) is None  # invalid after first run
    s.Restart()                                      # re-launch (Play again)
    # Restart runs an instantaneous member and completes again, re-invalidating.
    assert App.TGObject_GetTGObjectPtr(sid) is None


def test_aborted_sequence_id_no_longer_resolves():
    s = App.TGSequence_Create()
    cond = App.TGConditionAction_Create()          # keeps the sequence playing
    s.AddAction(cond)
    sid = s.GetObjID()
    s.Play()
    assert App.TGObject_GetTGObjectPtr(sid) is s
    s.Abort()
    assert App.TGObject_GetTGObjectPtr(sid) is None


def test_queueactiontoplay_starts_fresh_master_after_previous_completes(monkeypatch):
    """MissionLib.QueueActionToPlay must open a NEW playing master once the
    previous master has completed (its id gone invalid) — not append onto the
    dead one. This is the exact contract E1M2's Soams hail depends on."""
    import MissionLib
    from engine.core.game import Game, _set_current_game
    from engine.appc.ships import ShipClass_Create

    # A live, non-dying player so QueueActionToPlay does not take its skip path.
    game = Game()
    player = ShipClass_Create("Galaxy")
    player.SetName("player")
    game.SetPlayer(player)
    _set_current_game(game)
    monkeypatch.setattr(MissionLib, "g_idMasterSequenceObj", App.NULL_ID,
                        raising=False)
    try:
        # First queued action -> creates master A, plays it. A's sole member is
        # instantaneous, so A completes and its id is invalidated.
        MissionLib.QueueActionToPlay(App.TGAction_CreateNull())
        master_a = MissionLib.g_idMasterSequenceObj
        assert App.TGObject_GetTGObjectPtr(master_a) is None  # A completed+gone

        # Second queued action must NOT append onto the dead A: it starts a
        # fresh master B and plays it.
        MissionLib.QueueActionToPlay(App.TGAction_CreateNull())
        master_b = MissionLib.g_idMasterSequenceObj
        assert master_b != master_a          # a genuinely new master was created
    finally:
        _set_current_game(None)


# ── Skip (Backspace → TGActionManager_SkipEvents) ────────────────────────────

class _FakeVoiceHandle:
    def __init__(self):
        self.stopped = False

    def Stop(self):
        self.stopped = True


def test_skippable_flag_roundtrip():
    a = TGAction()
    assert not a.IsSkippable()               # SDK default: not skippable
    a.SetSkippable(1)
    assert a.IsSkippable()
    a.SetSkippable(0)
    assert not a.IsSkippable()


def test_skip_cancels_deferred_timer_and_completes_once():
    a = TGAction()
    done = []
    real_completed = a.Completed
    a.Completed = lambda: (done.append(True), real_completed())  # type: ignore
    a._playing = True
    a._complete_after(0.5)
    a.Skip()
    assert done == [True]                    # completed immediately
    _advance_real_time(1.0)
    assert done == [True]                    # timer cancelled: no re-fire


def test_skip_events_stops_audio_and_advances_sequence(monkeypatch):
    from engine.audio.tg_sound import TGSoundManager
    handle = _FakeVoiceHandle()
    monkeypatch.setattr(TGSoundManager, "duration_for",
                        lambda self, name: 5.0, raising=True)
    monkeypatch.setattr(TGSoundManager, "PlaySound",
                        lambda self, name: handle, raising=True)

    sound = App.TGSoundAction_Create("VoiceLine")
    sound.SetSkippable(1)                    # MissionLib.py:699 pattern
    follower = TGAction()
    played = []
    real_play = follower.Play
    follower.Play = lambda: (played.append(True), real_play())  # type: ignore

    seq = TGSequence_Create()
    seq.AddAction(sound)
    seq.AddAction(follower, sound)
    seq.Play()
    assert sound.IsPlaying()
    assert played == []                      # gated on the 5s line

    App.TGActionManager_SkipEvents()

    assert handle.stopped                    # audio cut mid-line
    assert not sound.IsPlaying()
    assert played == [True]                  # chained step advanced immediately


def test_skip_events_leaves_unskippable_actions_playing(monkeypatch):
    from engine.audio.tg_sound import TGSoundManager
    handle = _FakeVoiceHandle()
    monkeypatch.setattr(TGSoundManager, "duration_for",
                        lambda self, name: 5.0, raising=True)
    monkeypatch.setattr(TGSoundManager, "PlaySound",
                        lambda self, name: handle, raising=True)

    sound = App.TGSoundAction_Create("Ambience")   # never SetSkippable(1)
    sound.Play()
    assert sound.IsPlaying()

    App.TGActionManager_SkipEvents()

    assert sound.IsPlaying()                 # untouched
    assert not handle.stopped
    sound.Abort()                            # cleanup (also stops audio)
    assert handle.stopped


def test_skip_events_noop_when_nothing_playing():
    from engine.appc.actions import reset_deferred_playing
    reset_deferred_playing()
    App.TGActionManager_SkipEvents()         # must not raise


def test_action_manager_skips_objptr_on_action_skip():
    target = TGAction()
    skipped = []
    target.Skip = lambda: skipped.append(True)   # type: ignore

    ev = App.TGObjPtrEvent_Create()
    ev.SetEventType(App.ET_ACTION_SKIP)
    ev.SetObjPtr(target)
    App.g_kTGActionManager.ProcessEvent(ev)

    assert skipped == [True]


def test_sequence_skip_stops_inflight_children_without_launching_rest(monkeypatch):
    from engine.audio.tg_sound import TGSoundManager
    handle = _FakeVoiceHandle()
    monkeypatch.setattr(TGSoundManager, "duration_for",
                        lambda self, name: 5.0, raising=True)
    monkeypatch.setattr(TGSoundManager, "PlaySound",
                        lambda self, name: handle, raising=True)

    sound = App.TGSoundAction_Create("WinMovieLine")
    follower = TGAction()
    played = []
    real_play = follower.Play
    follower.Play = lambda: (played.append(True), real_play())  # type: ignore

    seq = TGSequence_Create()
    seq.AddAction(sound)
    seq.AddAction(follower, sound)
    seq.Play()

    seq.Skip()                               # E8M2 win-movie pattern

    assert handle.stopped                    # in-flight child silenced
    assert not seq.IsPlaying()               # sequence over now
    assert played == []                      # later steps NOT launched by skip


def test_skip_events_does_not_silence_the_follow_on_line(monkeypatch):
    """Regression: Backspace on a chained dialogue sequence.

    Skipping line A's action completes it inline, which starts line B during
    TGActionManager_SkipEvents. The bus skip must run BEFORE the action loop
    — issued after, it silenced the freshly-started B while B's action still
    ran its full duration (skip muted the dialogue without shortening the
    wait)."""
    from engine.appc import crew_speech
    from engine.appc.localization import TGLocalizationDatabase
    from engine.appc import top_window

    top_window.reset_for_tests()
    crew_speech.bus().reset()
    b = crew_speech.bus()
    handles = []

    def fake_play(self, wav):
        h = _FakeVoiceHandle()
        handles.append(h)
        return (5.0, h)

    monkeypatch.setattr(type(b), "_play_voice", fake_play, raising=True)
    db = TGLocalizationDatabase(
        "x.tgl",
        strings={"L1": "line one", "L2": "line two"},
        sounds={"L1": "l1.wav", "L2": "l2.wav"},
    )
    line_a = App.CharacterAction_Create(
        None, App.CharacterAction.AT_SAY_LINE, "L1", None, 0, db)
    line_b = App.CharacterAction_Create(
        None, App.CharacterAction.AT_SAY_LINE, "L2", None, 0, db)
    seq = TGSequence_Create()
    seq.AddAction(line_a)
    seq.AppendAction(line_b, line_a)
    seq.Play()
    assert len(handles) == 1                 # only A's voice started

    App.TGActionManager_SkipEvents()

    assert not line_a.IsPlaying()
    assert line_b.IsPlaying()                # B advanced immediately...
    assert len(handles) == 2
    assert handles[0].stopped                # ...A's voice was cut
    assert not handles[1].stopped            # ...and B's voice keeps playing
    import App as _App
    sub = _App.TopWindow_GetTopWindow().FindMainWindow(_App.MWT_SUBTITLE)
    snap = sub._snapshot(now=0.0)
    assert snap is not None and snap["speech"] == "line two"
