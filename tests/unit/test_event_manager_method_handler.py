"""Unit tests for TGEventManager.AddBroadcastPythonMethodHandler +
TGPythonInstanceWrapper — instance-method dispatch from the event bus.

The SDK conditions (Conditions/Condition*.py) use this pattern:
    self.pEventHandler = App.TGPythonInstanceWrapper()
    self.pEventHandler.SetPyWrapper(self)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_DELETE_OBJECT_PUBLIC, self.pEventHandler, "Deleted", target_obj)
The wrapper holds the Python instance; the event manager dispatches
`getattr(instance, "Deleted")(evt)` when matching events fire.
"""
import App
from engine.appc.events import (
    TGEvent, TGEvent_Create, TGEventManager, TGPythonInstanceWrapper,
)


def _fresh_manager():
    return TGEventManager()


def test_method_handler_dispatches_named_method_on_wrapper():
    class Spy:
        def __init__(self):
            self.calls = []
        def Hit(self, evt):
            self.calls.append(evt.GetEventType())

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(42, wrapper, "Hit")

    evt = TGEvent_Create()
    evt.SetEventType(42)
    mgr.AddEvent(evt)

    assert spy.calls == [42]


def test_method_handler_filters_by_target():
    """When a target object is passed, the handler fires ONLY for events
    whose destination matches that target. None target → matches all."""
    fired_with = []

    class Spy:
        def Hit(self, evt):
            fired_with.append(evt.GetDestination())

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    target_obj = object()  # arbitrary identity-comparable target
    other_obj = object()

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(7, wrapper, "Hit", target_obj)

    e_match = TGEvent_Create(); e_match.SetEventType(7)
    e_match.SetDestination(target_obj)
    mgr.AddEvent(e_match)

    e_other = TGEvent_Create(); e_other.SetEventType(7)
    e_other.SetDestination(other_obj)
    mgr.AddEvent(e_other)

    assert fired_with == [target_obj]


def test_method_handler_no_target_matches_all():
    fired = []

    class Spy:
        def Hit(self, evt):
            fired.append(1)

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(5, wrapper, "Hit")  # no target

    e1 = TGEvent_Create(); e1.SetEventType(5); e1.SetDestination(object())
    mgr.AddEvent(e1)
    e2 = TGEvent_Create(); e2.SetEventType(5)  # no destination
    mgr.AddEvent(e2)

    assert len(fired) == 2


def test_remove_broadcast_handler_unregisters():
    fired = []

    class Spy:
        def Hit(self, evt):
            fired.append(1)

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(9, wrapper, "Hit")
    mgr.RemoveBroadcastHandler(9, wrapper, "Hit")

    evt = TGEvent_Create(); evt.SetEventType(9)
    mgr.AddEvent(evt)

    assert fired == []


def test_unrelated_event_does_not_fire():
    fired = []

    class Spy:
        def Hit(self, evt):
            fired.append(1)

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(1, wrapper, "Hit")

    evt = TGEvent_Create(); evt.SetEventType(2)  # different type
    mgr.AddEvent(evt)

    assert fired == []
