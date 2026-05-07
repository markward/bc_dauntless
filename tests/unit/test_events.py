import sys
import types
import pytest
from engine.appc.events import (
    TGEvent, TGEvent_Create, TGEventHandlerObject,
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

    assert called == []
