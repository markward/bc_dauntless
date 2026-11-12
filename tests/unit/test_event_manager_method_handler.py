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


def test_reset_clears_broadcast_handlers():
    """After reset_sdk_globals (called on mission swap), broadcast handlers
    from the prior mission must NOT fire. Conditions register handlers on
    g_kEventManager during mission init; without clearing, stale handlers
    leak across missions and fire against wrong objects."""
    import sys, types
    # engine.host_loop imports engine.renderer → _dauntless_host (C++ ext).
    # In test environments without a matching-Python-ABI build, install a
    # benign stub so the import succeeds. The reset path itself doesn't
    # call any renderer entrypoint.
    if "_dauntless_host" not in sys.modules:
        sys.modules["_dauntless_host"] = types.ModuleType("_dauntless_host")
        sys.modules["_dauntless_host"].InstanceId = int  # type: ignore[attr-defined]
    import App
    from engine.host_loop import reset_sdk_globals

    fired = []

    class Spy:
        def Hit(self, evt):
            fired.append(1)

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(50, wrapper, "Hit")

    reset_sdk_globals()

    evt = TGEvent_Create(); evt.SetEventType(50)
    App.g_kEventManager.AddEvent(evt)

    assert fired == [], "stale handler from prior mission fired after reset"


# ── Owner lifetime: a discarded SDK object stops listening ──────────────────
#
# The SDK idiom makes a cycle: the owner keeps the wrapper
# (self.pEventHandler) and the wrapper points back at the owner. BC's Python
# 1.5 has no cyclic collector, and SDK classes rely on __del__ running when
# the last outside reference goes (Conditions/ConditionIncomingTorps.py), so
# BC's wrapper cannot own its instance. Ours held it strongly, and the event
# manager holds the wrapper, so every condition the SDK discarded on a
# retarget kept receiving broadcasts for the rest of the mission.

class _Owner:
    """The SDK shape: wrapper stored on the owner BEFORE SetPyWrapper(self)."""
    def __init__(self, mgr, calls):
        self.calls = calls
        self.pEventHandler = TGPythonInstanceWrapper()
        self.pEventHandler.SetPyWrapper(self)
        mgr.AddBroadcastPythonMethodHandler(42, self.pEventHandler, "Hit")

    def Hit(self, evt):
        self.calls.append(evt.GetEventType())


def _post(mgr, event_type=42):
    evt = TGEvent_Create()
    evt.SetEventType(event_type)
    mgr.AddEvent(evt)


def test_discarded_owner_stops_receiving_and_its_handler_is_dropped():
    import gc
    gc.disable()                       # refcount alone must do it, as in BC
    try:
        mgr = _fresh_manager()
        calls = []
        owner = _Owner(mgr, calls)
        _post(mgr)
        assert calls == [42]
        del owner
        _post(mgr)
        assert calls == [42]
        assert mgr._method_handlers[42] == []
    finally:
        gc.enable()


def test_dead_owners_never_pile_up_as_new_handlers_register():
    """Registration prunes dead entries only once the list has doubled
    (constant time per add), so they stay bounded rather than gone at once;
    the next dispatch drops the rest."""
    import gc
    from engine.appc import events
    gc.disable()
    try:
        mgr = _fresh_manager()
        calls = []
        for _ in range(500):
            _Owner(mgr, calls)         # each discarded at once
        keeper = _Owner(mgr, calls)
        assert len(mgr._method_handlers[42]) <= events._PRUNE_FLOOR
        _post(mgr)
        assert calls == [42]
        assert len(mgr._method_handlers[42]) == 1
        del keeper
    finally:
        gc.enable()


def test_instance_that_does_not_hold_its_wrapper_is_kept_alive():
    """A wrapper given an instance nobody else holds (engine and test code
    do this) must keep it: only the owner idiom is held weakly."""
    calls = []

    class Spy:
        def Hit(self, evt):
            calls.append(evt.GetEventType())

    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(Spy())
    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(42, wrapper, "Hit")
    import gc
    gc.collect()
    _post(mgr)
    assert calls == [42]
    assert wrapper.GetPyWrapper() is not None


def test_wrapper_with_no_instance_yet_keeps_its_registration():
    """Registered before SetPyWrapper: not a dead owner, must not be pruned."""
    calls = []

    class Spy:
        def Hit(self, evt):
            calls.append(1)

    wrapper = TGPythonInstanceWrapper()
    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(42, wrapper, "Hit")
    _post(mgr)
    spy = Spy()
    wrapper.SetPyWrapper(spy)
    _post(mgr)
    assert calls == [1]


# ── Target-filter lifetime ───────────────────────────────────────────────────
#
# A handler filtered on a destination can only ever fire for that one object.
# SDK ConditionInRange.SetObjects builds a fresh ObjectGroup on every retarget,
# registers handlers filtered on it and drops the old group; BC's handlers go
# with the destination object. Ours kept the old group alive in the handler
# list, so the list grew by two entries per retarget for the whole mission.

class _Dest:
    pass


class _Listener:
    def __init__(self):
        self.calls = 0
        self.pEventHandler = TGPythonInstanceWrapper()
        self.pEventHandler.SetPyWrapper(self)

    def Hit(self, evt):
        self.calls += 1


def test_handler_whose_target_was_freed_is_dropped():
    import gc
    gc.disable()
    try:
        mgr = _fresh_manager()
        listener = _Listener()
        for _ in range(5):
            mgr.AddBroadcastPythonMethodHandler(
                42, listener.pEventHandler, "Hit", _Dest())   # freed at once
        live = _Dest()
        mgr.AddBroadcastPythonMethodHandler(42, listener.pEventHandler, "Hit", live)
        assert len(mgr._method_handlers[42]) == 1
        evt = TGEvent_Create()
        evt.SetEventType(42)
        evt.SetDestination(live)
        mgr.AddEvent(evt)
        assert listener.calls == 1
    finally:
        gc.enable()


def test_target_filter_does_not_keep_the_target_alive():
    import gc
    import weakref
    gc.disable()
    try:
        mgr = _fresh_manager()
        listener = _Listener()
        dest = _Dest()
        ref = weakref.ref(dest)
        mgr.AddBroadcastPythonMethodHandler(42, listener.pEventHandler, "Hit", dest)
        del dest
        assert ref() is None
        _post(mgr)                      # an untargeted event never matched it
        assert listener.calls == 0
        assert mgr._method_handlers[42] == []
    finally:
        gc.enable()


def test_remove_matches_a_live_target():
    mgr = _fresh_manager()
    listener = _Listener()
    a, b = _Dest(), _Dest()
    mgr.AddBroadcastPythonMethodHandler(42, listener.pEventHandler, "Hit", a)
    mgr.AddBroadcastPythonMethodHandler(42, listener.pEventHandler, "Hit", b)
    mgr.AddBroadcastPythonMethodHandler(42, listener.pEventHandler, "Hit", a)
    assert len(mgr._method_handlers[42]) == 2
    mgr.RemoveBroadcastHandler(42, listener.pEventHandler, "Hit", a)
    assert len(mgr._method_handlers[42]) == 1
    for dest in (a, b):
        evt = TGEvent_Create()
        evt.SetEventType(42)
        evt.SetDestination(dest)
        mgr.AddEvent(evt)
    assert listener.calls == 1
