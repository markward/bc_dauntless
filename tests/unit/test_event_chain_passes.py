import sys
import types

import App
from engine.appc.events import TGEventHandlerObject, dispatch_passes


def _event(dest):
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_ENVIRONMENT_DAMAGE)
    evt.SetDestination(dest)
    return evt


def _install(name, fn):
    mod = types.ModuleType(name)
    mod.h = fn
    sys.modules[name] = mod
    return name + ".h"


def test_no_handlers_passes():
    assert dispatch_passes(_event(TGEventHandlerObject())) is True


def test_handler_that_calls_next_passes():
    obj = TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, _install("_chain_next", lambda o, e: o.CallNextHandler(e)))
    assert dispatch_passes(_event(obj)) is True


def test_handler_that_returns_swallows():
    obj = TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, _install("_chain_stop", lambda o, e: None))
    assert dispatch_passes(_event(obj)) is False


def test_ignore_event_swallows():
    obj = TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(App.ET_ENVIRONMENT_DAMAGE, "MissionLib.IgnoreEvent")
    assert dispatch_passes(_event(obj)) is False


def test_destination_without_process_event_passes():
    class Plain:
        pass
    assert dispatch_passes(_event(Plain())) is True
