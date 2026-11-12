"""AddBroadcastPythonMethodHandler does not walk the handler list.

SDK Conditions/ConditionInRange.SetTarget registers its handler set on every
AI retarget. With a walk per registration (and a dead-entry check per entry),
a large Quick Battle spent ~1.2 ms per registration once a type held
thousands of handlers, and a few retargets on one tick were a 25-30 ms
gl.ai hitch. The duplicate check now reads an index kept on the list.
"""
import gc

from engine.appc import events
from engine.appc.events import (
    TGEvent_Create, TGEventManager, TGPythonInstanceWrapper,
)


class _Target:
    """A weakly referenceable filter target."""


class _Rec:
    def __init__(self):
        self.hits = []

    def Hit(self, evt):
        self.hits.append(evt.GetDestination())


def _wrapper(rec):
    w = TGPythonInstanceWrapper()
    w.SetPyWrapper(rec)
    return w


def _post(mgr, dest=None, event_type=42):
    evt = TGEvent_Create()
    evt.SetEventType(event_type)
    if dest is not None:
        evt.SetDestination(dest)
    mgr.AddEvent(evt)


def test_registration_cost_does_not_grow_with_the_list(monkeypatch):
    calls = [0]
    real = events._handler_dead

    def counting(entry):
        calls[0] += 1
        return real(entry)

    monkeypatch.setattr(events, "_handler_dead", counting)
    mgr = TGEventManager()
    rec = _Rec()
    w = _wrapper(rec)
    targets = [_Target() for _ in range(2000)]
    for t in targets:
        mgr.AddBroadcastPythonMethodHandler(42, w, "Hit", t)
    # A walk per add was ~n^2/2 = 2,000,000 checks; the doubling prune is
    # under 2 per handler in total.
    assert calls[0] < 4 * len(targets)
    assert len(mgr._method_handlers[42]) == len(targets)


def test_duplicates_are_still_kept_once():
    mgr = TGEventManager()
    rec = _Rec()
    w = _wrapper(rec)
    t = _Target()
    for _ in range(5):
        mgr.AddBroadcastPythonMethodHandler(42, w, "Hit", t)
        mgr.AddBroadcastPythonMethodHandler(42, w, "Hit")
    assert len(mgr._method_handlers[42]) == 2
    _post(mgr, t)
    assert rec.hits == [t, t]          # the filtered one and the open one


def test_delivery_order_is_registration_order():
    mgr = TGEventManager()
    order = []

    class R:
        def __init__(self, n):
            self.n = n

        def Hit(self, evt):
            order.append(self.n)

    keep = [R(i) for i in range(50)]
    for r in keep:
        mgr.AddBroadcastPythonMethodHandler(42, _wrapper(r), "Hit")
    _post(mgr)
    assert order == list(range(50))


def test_dedupe_survives_an_in_place_filter_from_outside():
    """mission_change._drop_event_handlers filters the lists in place."""
    mgr = TGEventManager()
    a, b = _Rec(), _Rec()
    wa, wb = _wrapper(a), _wrapper(b)
    mgr.AddBroadcastPythonMethodHandler(42, wa, "Hit")
    mgr.AddBroadcastPythonMethodHandler(42, wb, "Hit")
    handlers = mgr._method_handlers[42]
    handlers[:] = [h for h in handlers if h[0] is wb]
    mgr.AddBroadcastPythonMethodHandler(42, wa, "Hit")   # gone: added again
    mgr.AddBroadcastPythonMethodHandler(42, wb, "Hit")   # still there: kept
    assert [h[0] for h in mgr._method_handlers[42]] == [wb, wa]


def test_dedupe_survives_the_handler_dict_being_cleared():
    mgr = TGEventManager()
    rec = _Rec()
    w = _wrapper(rec)
    mgr.AddBroadcastPythonMethodHandler(42, w, "Hit")
    mgr._method_handlers.clear()                         # the resets do this
    mgr.AddBroadcastPythonMethodHandler(42, w, "Hit")
    mgr.AddBroadcastPythonMethodHandler(42, w, "Hit")
    assert len(mgr._method_handlers[42]) == 1


def test_remove_then_add_registers_again():
    mgr = TGEventManager()
    rec = _Rec()
    w = _wrapper(rec)
    t = _Target()
    mgr.AddBroadcastPythonMethodHandler(42, w, "Hit", t)
    mgr.RemoveBroadcastHandler(42, w, "Hit", t)
    assert len(mgr._method_handlers[42]) == 0
    mgr.AddBroadcastPythonMethodHandler(42, w, "Hit", t)
    assert len(mgr._method_handlers[42]) == 1
    _post(mgr, t)
    assert rec.hits == [t]


def test_a_freed_filter_never_blocks_a_new_registration():
    """The index keys on id(); a new target may reuse a freed one's id."""
    gc.disable()
    try:
        mgr = TGEventManager()
        rec = _Rec()
        w = _wrapper(rec)
        for _ in range(200):
            t = _Target()
            mgr.AddBroadcastPythonMethodHandler(42, w, "Hit", t)
            del t                       # freed: likely id reused next pass
        live = _Target()
        mgr.AddBroadcastPythonMethodHandler(42, w, "Hit", live)
        _post(mgr, live)
        assert rec.hits == [live]
        assert len(mgr._method_handlers[42]) == 1      # dispatch pruned
    finally:
        gc.enable()


def test_clearing_the_handlers_frees_the_index_with_them():
    """The index lives on the list: once the resets clear the dict, nothing
    of the event manager's still holds an entry."""
    mgr = TGEventManager()
    mgr.AddBroadcastPythonMethodHandler(42, _wrapper(_Rec()), "Hit")
    entry = mgr._method_handlers[42][0]
    mgr._method_handlers.clear()
    gc.collect()
    holders = [r for r in gc.get_referrers(entry)
               if isinstance(r, (list, dict))]
    assert holders == []
