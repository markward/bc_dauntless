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
