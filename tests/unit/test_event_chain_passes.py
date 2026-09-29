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


def test_nested_repost_outer_stops_reports_false():
    """Regression: nested dispatch must not overwrite outer dispatch's result.

    Scenario: Destination D has handlers [A (oldest), B (newest)]. B re-posts
    the same event object and returns without CallNextHandler (stops the chain).
    The nested dispatch runs A and B again; B's second invocation calls
    CallNextHandler, chain reaches end, setting _chain_passed = True. The outer
    chain actually stopped (B never called CallNextHandler), yet dispatch_passes
    returned True (wrong). Fix: track result on the frame, not the event."""
    obj = TGEventHandlerObject()

    # Handler A (oldest): on second dispatch (nested), calls CallNextHandler
    repost_count = [0]  # use list to allow mutation in closure
    def a_handler(obj_inner, event):
        # A always calls next
        obj_inner.CallNextHandler(event)

    # Handler B (newest): on first dispatch (outer), re-posts and returns
    # without CallNextHandler (stops the chain); on second dispatch (nested),
    # calls CallNextHandler
    def b_handler(obj_inner, event):
        repost_count[0] += 1
        if repost_count[0] == 1:
            # Only repost on first invocation to avoid infinite recursion
            App.g_kEventManager.AddEvent(event)  # nested dispatch
            # return without CallNextHandler — stops the OUTER chain
        else:
            # On second invocation (nested), do call next
            obj_inner.CallNextHandler(event)

    # Register A first (will be oldest), then B (newest, runs first)
    obj.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, _install("_nested_a", a_handler))
    obj.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, _install("_nested_b", b_handler))

    # The outer dispatch should report False (B stopped it on first call),
    # even though the nested dispatch completed successfully
    assert dispatch_passes(_event(obj)) is False


def test_dispatched_events_do_not_accumulate_in_the_id_registry():
    # Final review #4: radiation fires ~270 events/s near Vesuvi; each one
    # stayed strongly held in ids._registry forever.
    from engine.core import ids
    dest = TGEventHandlerObject()
    dispatch_passes(_event(dest))                 # warm any lazy registrations
    before = len(ids._registry)
    for _ in range(200):
        dispatch_passes(_event(dest))
    assert len(ids._registry) == before


def test_dispatched_event_is_released_even_when_a_handler_raises():
    import pytest
    from engine.core import ids

    def boom(o, e):
        raise RuntimeError("handler failure")

    obj = TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, _install("_chain_boom", boom))
    evt = _event(obj)
    with pytest.raises(RuntimeError):
        dispatch_passes(evt)
    assert ids.get_object_by_id(evt.GetObjID()) is None
