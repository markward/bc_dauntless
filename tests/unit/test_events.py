import sys
import types
import pytest
from engine.appc.events import (
    TGEvent, TGEvent_Create, TGEventHandlerObject, TGEventManager,
)

ET_TEST = 9001  # arbitrary type constant for tests


def test_event_type_roundtrip():
    event = TGEvent_Create()
    event.SetEventType(ET_TEST)
    assert event.GetEventType() == ET_TEST


def test_event_destination_roundtrip():
    handler = TGEventHandlerObject()
    event = TGEvent_Create()
    event.SetDestination(handler)
    assert event.GetDestination() is handler


def test_event_create_returns_tgevent():
    assert isinstance(TGEvent_Create(), TGEvent)


def test_dispatch_calls_registered_handler():
    called_with = []

    mod = types.ModuleType("_test_events_helper")
    def my_handler(pObject, pEvent):
        called_with.append((pObject, pEvent))
    mod.my_handler = my_handler
    sys.modules["_test_events_helper"] = mod

    handler_obj = TGEventHandlerObject()
    handler_obj.AddPythonFuncHandlerForInstance(ET_TEST, "_test_events_helper.my_handler")

    event = TGEvent_Create()
    event.SetEventType(ET_TEST)
    event.SetDestination(handler_obj)

    handler_obj.ProcessEvent(event)

    assert len(called_with) == 1
    assert called_with[0] == (handler_obj, event)


def test_dispatch_ignores_wrong_event_type():
    called = []
    mod = types.ModuleType("_test_events_helper2")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_test_events_helper2"] = mod

    handler_obj = TGEventHandlerObject()
    handler_obj.AddPythonFuncHandlerForInstance(ET_TEST, "_test_events_helper2.cb")

    event = TGEvent_Create()
    event.SetEventType(9002)  # different type
    handler_obj.ProcessEvent(event)

    assert called == []


def test_remove_handler():
    called = []
    mod = types.ModuleType("_test_events_helper3")
    mod.cb = lambda obj, ev: called.append(True)
    sys.modules["_test_events_helper3"] = mod

    handler_obj = TGEventHandlerObject()
    handler_obj.AddPythonFuncHandlerForInstance(ET_TEST, "_test_events_helper3.cb")
    handler_obj.RemoveHandlerForInstance(ET_TEST, "_test_events_helper3.cb")

    event = TGEvent_Create()
    event.SetEventType(ET_TEST)
    handler_obj.ProcessEvent(event)


def test_broadcast_handler_receives_all_events_of_type():
    called = []
    mod = types.ModuleType("_test_broadcast_1")
    mod.cb = lambda pObj, pEv: called.append(pObj)
    sys.modules["_test_broadcast_1"] = mod

    em = TGEventManager()
    dest1 = TGEventHandlerObject()
    dest2 = TGEventHandlerObject()
    listener = TGEventHandlerObject()
    em.AddBroadcastPythonFuncHandler(ET_TEST, listener, "_test_broadcast_1.cb")

    ev1 = TGEvent_Create()
    ev1.SetEventType(ET_TEST)
    ev1.SetDestination(dest1)
    em.AddEvent(ev1)
    assert called == [listener]

    called.clear()
    ev2 = TGEvent_Create()
    ev2.SetEventType(ET_TEST)
    ev2.SetDestination(dest2)
    em.AddEvent(ev2)
    assert called == [listener]

    del sys.modules["_test_broadcast_1"]


def test_broadcast_handler_does_not_fire_for_wrong_type():
    called = []
    mod = types.ModuleType("_test_broadcast_2")
    mod.cb = lambda pObj, pEv: called.append(True)
    sys.modules["_test_broadcast_2"] = mod

    em = TGEventManager()
    listener = TGEventHandlerObject()
    em.AddBroadcastPythonFuncHandler(ET_TEST, listener, "_test_broadcast_2.cb")

    ev = TGEvent_Create()
    ev.SetEventType(9002)
    ev.SetDestination(TGEventHandlerObject())
    em.AddEvent(ev)
    assert called == []

    del sys.modules["_test_broadcast_2"]


def test_remove_broadcast_handler():
    called = []
    mod = types.ModuleType("_test_broadcast_3")
    mod.cb = lambda pObj, pEv: called.append(True)
    sys.modules["_test_broadcast_3"] = mod

    em = TGEventManager()
    listener = TGEventHandlerObject()
    em.AddBroadcastPythonFuncHandler(ET_TEST, listener, "_test_broadcast_3.cb")
    em.RemoveBroadcastHandler(ET_TEST, listener, "_test_broadcast_3.cb")

    ev = TGEvent_Create()
    ev.SetEventType(ET_TEST)
    ev.SetDestination(TGEventHandlerObject())
    em.AddEvent(ev)
    assert called == []

    del sys.modules["_test_broadcast_3"]

    assert called == []


def test_raising_func_broadcast_handler_logs_and_continues(capsys):
    """BC is log-and-continue: one raising broadcast handler must not
    unwind the tick. The traceback goes to stderr (with a line naming
    the handler + event type) and the remaining handlers still run."""
    called = []
    mod = types.ModuleType("_test_broadcast_raise")
    def bad(pObj, pEv):
        raise RuntimeError("boom in func handler")
    mod.bad = bad
    mod.good = lambda pObj, pEv: called.append(True)
    sys.modules["_test_broadcast_raise"] = mod

    em = TGEventManager()
    listener = TGEventHandlerObject()
    em.AddBroadcastPythonFuncHandler(ET_TEST, listener, "_test_broadcast_raise.bad")
    em.AddBroadcastPythonFuncHandler(ET_TEST, listener, "_test_broadcast_raise.good")

    ev = TGEvent_Create()
    ev.SetEventType(ET_TEST)
    em.AddEvent(ev)  # must NOT raise

    assert called == [True], "handler after the raising one did not run"
    err = capsys.readouterr().err
    assert "_test_broadcast_raise.bad" in err
    assert str(ET_TEST) in err
    assert "RuntimeError" in err
    assert "boom in func handler" in err
    assert "Traceback" in err

    del sys.modules["_test_broadcast_raise"]


def test_raising_method_broadcast_handler_logs_and_continues(capsys):
    """Same log-and-continue guarantee for the method-broadcast path."""
    from engine.appc.events import TGPythonInstanceWrapper

    called = []

    class BadSpy:
        def Hit(self, evt):
            raise RuntimeError("boom in method handler")

    class GoodSpy:
        def Hit(self, evt):
            called.append(True)

    bad_wrapper = TGPythonInstanceWrapper()
    bad_wrapper.SetPyWrapper(BadSpy())
    good_wrapper = TGPythonInstanceWrapper()
    good_wrapper.SetPyWrapper(GoodSpy())

    em = TGEventManager()
    em.AddBroadcastPythonMethodHandler(ET_TEST, bad_wrapper, "Hit")
    em.AddBroadcastPythonMethodHandler(ET_TEST, good_wrapper, "Hit")

    ev = TGEvent_Create()
    ev.SetEventType(ET_TEST)
    em.AddEvent(ev)  # must NOT raise

    assert called == [True], "handler after the raising one did not run"
    err = capsys.readouterr().err
    assert "Hit" in err
    assert "BadSpy" in err
    assert str(ET_TEST) in err
    assert "RuntimeError" in err
    assert "boom in method handler" in err
    assert "Traceback" in err


def test_destination_process_event_exception_still_propagates():
    """The destination ProcessEvent dispatch at the top of AddEvent is NOT
    guarded — engine-internal actions rely on exceptions propagating."""
    class ExplodingDest(TGEventHandlerObject):
        def ProcessEvent(self, event):
            raise RuntimeError("destination boom")

    em = TGEventManager()
    ev = TGEvent_Create()
    ev.SetEventType(ET_TEST)
    ev.SetDestination(ExplodingDest())

    with pytest.raises(RuntimeError, match="destination boom"):
        em.AddEvent(ev)
