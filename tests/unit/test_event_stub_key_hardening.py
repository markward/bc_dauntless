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
from engine.appc.events import TGEventManager
from engine.core import stub_telemetry


def test_stub_event_type_is_recorded_to_telemetry(monkeypatch):
    recorded = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: recorded.append((owner, attr)))

    mgr = TGEventManager()
    mgr.AddBroadcastPythonFuncHandler(
        App.ET_SOME_UNDEFINED_EVENT, object(), "mod.Func")

    assert recorded, "a stub-typed event key must be recorded, not silently dead"
    assert any("ET_SOME_UNDEFINED_EVENT" in str(attr) for _owner, attr in recorded)


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
