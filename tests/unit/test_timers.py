import sys
import types
import pytest
from engine.appc.events import TGEvent_Create, TGEventHandlerObject, TGEventManager
from engine.appc.timers import TGTimer, TGTimer_Create, TGTimerManager

TICK = 1.0 / 60.0  # 60 Hz game tick
ET_TEST = 8001


def _make_stack():
    """Return (event_manager, timer_manager, destination, event)."""
    em = TGEventManager()
    tm = TGTimerManager(em)
    dest = TGEventHandlerObject()
    ev = TGEvent_Create()
    ev.SetEventType(ET_TEST)
    ev.SetDestination(dest)
    return em, tm, dest, ev


def test_one_shot_fires_after_start():
    called = []
    mod = types.ModuleType("_tt1")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt1"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt1.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(3 * TICK)
    timer.SetDelay(0.0)
    timer.SetDuration(-1.0)
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    # Tick twice — not yet
    tm.tick(TICK)
    tm.tick(TICK)
    assert called == []

    # Third tick crosses the 3-tick threshold
    tm.tick(TICK)
    assert called == [True]

    # One-shot: does not fire again
    tm.tick(TICK)
    tm.tick(TICK)
    assert len(called) == 1


def test_repeat_fires_multiple_times():
    called = []
    mod = types.ModuleType("_tt2")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt2"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt2.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(TICK)
    timer.SetDelay(TICK)
    timer.SetDuration(-1.0)
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    for _ in range(5):
        tm.tick(TICK)

    assert len(called) == 5


def test_duration_stops_timer():
    called = []
    mod = types.ModuleType("_tt3")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt3"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt3.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(TICK)
    timer.SetDelay(TICK)
    timer.SetDuration(3 * TICK)  # stop after 3 ticks total elapsed
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    for _ in range(10):
        tm.tick(TICK)

    assert len(called) == 3


def test_timer_manager_tracks_absolute_time():
    em = TGEventManager()
    tm = TGTimerManager(em)
    assert tm.get_time() == 0.0
    tm.tick(TICK)
    assert abs(tm.get_time() - TICK) < 1e-9
    tm.tick(TICK)
    assert abs(tm.get_time() - 2 * TICK) < 1e-9


def test_remove_timer_accepts_an_obj_id_int():
    """Real Appc's TGTimerManager::RemoveTimer takes the timer's object ID.
    Conditions/ConditionTimer.py:73 -- the only SDK call site -- calls
    App.g_kTimerManager.RemoveTimer(self.pTimer.GetObjID()), an int, not a
    TGTimer instance."""
    called = []
    mod = types.ModuleType("_tt5")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt5"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt5.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(TICK)
    timer.SetDelay(TICK)
    timer.SetDuration(-1.0)
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    tm.RemoveTimer(timer.GetObjID())  # int, not the TGTimer object

    tm.tick(TICK)
    tm.tick(TICK)
    assert called == []  # removed before it ever fired


def test_delete_timer_stops_firing():
    called = []
    mod = types.ModuleType("_tt4")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_tt4"] = mod

    em, tm, dest, ev = _make_stack()
    dest.AddPythonFuncHandlerForInstance(ET_TEST, "_tt4.cb")

    timer = TGTimer_Create()
    timer.SetTimerStart(TICK)
    timer.SetDelay(TICK)
    timer.SetDuration(-1.0)
    timer.SetEvent(ev)
    tm.AddTimer(timer)

    tm.tick(TICK)  # fires once
    tm.tick(TICK)  # fires twice
    assert len(called) == 2

    tm.DeleteTimer(timer.GetObjID())

    tm.tick(TICK)
    tm.tick(TICK)
    assert len(called) == 2  # no more fires
