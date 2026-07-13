"""Stub-typed event keys are recorded, not silently dead. And removal is by identity.

An ET_* name absent from our App.py resolves through App's module __getattr__
(App.py:1935) to a _NamedStub. events.py keys handlers on the raw object;
_Stub.__hash__ is id(self) and __getattr__ does not memoize, so EVERY access
mints a fresh key -- the handler is unreachable forever. 89 distinct stub ET_
names across ~270 SDK registration sites are dead this way.

We RECORD (so it surfaces in docs/stub_heatmap.md) and WARN. We must NOT refuse:
Tactical/Interface/CinematicInterfaceHandlers.py:15 keeps a module-level stub as
a LIVE same-object dispatch key (registered :229, fired :275 through that same
global), and refusing would break it.
"""
import App
from engine.appc import events as events_mod
from engine.appc.events import TGEventManager, TGEventHandlerObject, TGPythonInstanceWrapper
from engine.core import stub_telemetry
from engine.core.ids import _Stub as CoreIdsStub


def test_stub_event_type_is_recorded_to_telemetry(monkeypatch):
    recorded = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: recorded.append((owner, attr)))

    mgr = TGEventManager()
    mgr.AddBroadcastPythonFuncHandler(
        App.ET_SOME_UNDEFINED_EVENT, object(), "mod.Func")

    assert recorded, "a stub-typed event key must be recorded, not silently dead"
    # Pin the owner to "EventType" (our own record_attr call in
    # events.py:_validate_event_type), NOT a loose substring match.
    # App.py's own module-level __getattr__ (App.py:2006-2007) ALSO calls
    # stub_telemetry.record_attr("App", name) for every undefined attribute
    # -- merely EVALUATING `App.ET_SOME_UNDEFINED_EVENT` as an argument
    # records ("App", "ET_SOME_UNDEFINED_EVENT") regardless of whether
    # events.py's validator ever runs. A loose `any(... in str(attr) ...)`
    # check is satisfied by that row alone and proves nothing about OUR
    # code -- it would still pass with _validate_event_type deleted. Pinning
    # owner == "EventType" is the only assertion that actually discriminates.
    assert any(o == "EventType" and a == "ET_SOME_UNDEFINED_EVENT" for o, a in recorded)


def test_stub_event_type_is_recorded_for_instance_level_registrar(monkeypatch):
    """AddPythonFuncHandlerForInstance / AddPythonMethodHandlerForInstance are
    where the bulk of SDK handler registrations actually land (per-object
    handlers, not broadcast) -- exercise those registrars too, not just the
    broadcast one."""
    recorded = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: recorded.append((owner, attr)))

    handler_obj = TGEventHandlerObject()
    handler_obj.AddPythonFuncHandlerForInstance(
        App.ET_YET_ANOTHER_INSTANCE_UNDEFINED_EVENT, "mod.Func")

    assert any(
        o == "EventType" and a == "ET_YET_ANOTHER_INSTANCE_UNDEFINED_EVENT"
        for o, a in recorded
    )

    recorded.clear()
    wrapper = TGPythonInstanceWrapper()
    wrapper.AddPythonMethodHandlerForInstance(
        App.ET_STILL_ANOTHER_INSTANCE_UNDEFINED_EVENT, "Method")

    assert any(
        o == "EventType" and a == "ET_STILL_ANOTHER_INSTANCE_UNDEFINED_EVENT"
        for o, a in recorded
    )


def test_stub_event_type_guard_holds_for_core_ids_stub(monkeypatch):
    """engine.core.ids._Stub is the OTHER stub hierarchy (vended by
    TGObject.__getattr__ for any unimplemented Appc method, e.g. an event
    type read off a real engine object rather than an App.ET_* constant). It
    has NO `_name` attribute -- it stores its name at `_stub_name` -- so
    `getattr(event_type, "_name", None)` triggers `_Stub.__getattr__`, which
    vends ANOTHER truthy _Stub rather than raising AttributeError. The `or
    repr(event_type)` fallback therefore never runs, and the old code became
    `str(<a fresh _Stub>)` -- the default object.__repr__, unique by id() on
    every single access. That defeated the once-per-name warn/telemetry
    guard: the SAME stub-typed event_type, registered repeatedly, produced a
    new "name" (and a new warning line + telemetry row) every time.

    Prove the guard now holds: register the SAME _Stub-typed event_type N
    times and assert only ONE distinct name is ever recorded/warned.
    """
    recorded = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: recorded.append((owner, attr)))
    monkeypatch.setattr(events_mod, "_warned_event_types", set())

    stub_event_type = CoreIdsStub("ET_FROM_UNIMPLEMENTED_APPC_METHOD", "SomeEngineClass")

    mgr = TGEventManager()
    for _ in range(4):
        mgr.AddBroadcastPythonFuncHandler(stub_event_type, object(), "mod.Func")

    distinct_names = {a for o, a in recorded if o == "EventType"}
    assert distinct_names == {"ET_FROM_UNIMPLEMENTED_APPC_METHOD"}, (
        "guard must key on the real stub name, not an id-unique repr: got %r" % distinct_names
    )
    assert len(events_mod._warned_event_types) == 1, (
        "once-per-name warn guard did not collapse to one entry: %r"
        % events_mod._warned_event_types
    )


def test_stub_event_type_registration_is_not_refused(monkeypatch):
    """CinematicInterfaceHandlers.py:15 relies on a live stub key. Refusing would
    break it -- we record and warn, then register anyway."""
    monkeypatch.setattr(stub_telemetry, "ENABLED", False)
    mgr = TGEventManager()
    key = App.ET_ANOTHER_UNDEFINED_EVENT      # capture ONE stub object

    mgr.AddBroadcastPythonFuncHandler(key, object(), "mod.Func")

    # Same-object lookup must still find it (that is the Cinematic pattern).
    assert mgr._broadcast_handlers.get(key), "registration must not be refused"


def test_remove_broadcast_handler_removes_the_correct_handler():
    """_Stub.__eq__ is TYPE-based, so any all-stub tuple == any other. With
    list.remove(), removing B's handler would delete A's."""
    mgr = TGEventManager()
    key = App.ET_YET_ANOTHER_UNDEFINED       # one stub, reused as the key
    dest_a = App.ET_STUB_A                   # two DIFFERENT stub "objects"
    dest_b = App.ET_STUB_B

    mgr.AddBroadcastPythonFuncHandler(key, dest_a, "Handler")
    mgr.AddBroadcastPythonFuncHandler(key, dest_b, "Handler")
    assert len(mgr._broadcast_handlers[key]) == 2

    mgr.RemoveBroadcastHandler(key, dest_b, "Handler")

    remaining = mgr._broadcast_handlers[key]
    assert len(remaining) == 1
    assert remaining[0][0] is dest_a, "removed the WRONG handler"
