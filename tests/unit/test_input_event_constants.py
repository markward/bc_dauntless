"""The ET_INPUT_ viewscreen/first-person/tab/pick-fire + ET_MOUSE constants
close the input-event dead-key class.

DefaultUKKeyboardBinding binds these 11 event types (BridgeHandlers registers
handlers for the viewscreen ones), but the shim App.py never defined them, so
each resolved to App._NamedStub and BindKey's `int(event_type)`
(engine/appc/input.py:214) collapsed all of them to event_type 0 — a bound key
that silently does nothing (and, worse, all 10 keyboard bindings sharing slot
0). These tests prove the names are real, distinct, collision-free ints and
that two different viewscreen keys no longer collapse to the same event.

NOTE this is the constant-hygiene half only — it stops the collapse. It does
NOT make the keys functional: no poller forwards the physical keys, and
pick-fire's flag has no consumer. See
memory project_input_event_dead_keys_and_pickfire.
"""
import App
from engine.appc.events import (
    TGEventManager, TGEventHandlerObject, TGKeyboardEvent,
)
from engine.appc.input import KeyboardBinding, KS_KEYDOWN


# The 11 previously-collapsing input-event constants.
_INPUT_EVENT_NAMES = (
    "ET_INPUT_VIEWSCREEN_TARGET",
    "ET_INPUT_VIEWSCREEN_FORWARD",
    "ET_INPUT_VIEWSCREEN_LEFT",
    "ET_INPUT_VIEWSCREEN_RIGHT",
    "ET_INPUT_VIEWSCREEN_BACKWARD",
    "ET_INPUT_VIEWSCREEN_UP",
    "ET_INPUT_VIEWSCREEN_DOWN",
    "ET_INPUT_FIRSTPERSON",
    "ET_INPUT_TAB_FOCUS_CHANGE",
    "ET_INPUT_TOGGLE_PICK_FIRE",
    "ET_MOUSE",
)


def test_input_event_constants_real_distinct():
    """Each name is a real nonzero int, and all 11 are distinct."""
    values = []
    for name in _INPUT_EVENT_NAMES:
        v = getattr(App, name)
        assert type(v) is int and v != 0, name
        values.append(v)
    assert len(set(values)) == len(values), (
        "duplicate input-event codes: %r"
        % sorted(v for v in set(values) if values.count(v) > 1))


def test_no_collision_with_existing_input_events():
    """The 11 new codes must not alias any existing keyboard-bound ET_ code."""
    new_values = {getattr(App, name) for name in _INPUT_EVENT_NAMES}
    existing = {
        getattr(App, n): n for n in dir(App)
        if n.startswith(("ET_INPUT_", "ET_OTHER_"))
        and n not in _INPUT_EVENT_NAMES
        and type(getattr(App, n)) is int
    }
    clash = new_values & set(existing)
    assert not clash, "input-event code collides with %r" % (
        {c: existing[c] for c in clash},)


class _Dest(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self.received = []

    def ProcessEvent(self, evt):
        self.received.append(evt)


def test_two_viewscreen_keys_dispatch_distinct_event_types():
    """Binding two different viewscreen keys must yield two DIFFERENT event
    types on dispatch. Before the constants were defined, both event types
    collapsed to 0 via int(_NamedStub), so both keys produced an identical,
    zero-typed event."""
    em = TGEventManager()
    kb = KeyboardBinding(em)
    dest = _Dest()
    kb.SetDefaultDestination(dest)

    kb.BindKey(App.WC_HOME, KS_KEYDOWN, App.ET_INPUT_VIEWSCREEN_FORWARD)
    kb.BindKey(App.WC_END, KS_KEYDOWN, App.ET_INPUT_VIEWSCREEN_BACKWARD)

    for wc in (App.WC_HOME, App.WC_END):
        evt = TGKeyboardEvent()
        evt.SetUnicodeKey(wc)
        evt.SetKeyState(KS_KEYDOWN)
        kb.OnKeyboardEvent(None, evt)

    got = [e.GetEventType() for e in dest.received]
    assert got == [App.ET_INPUT_VIEWSCREEN_FORWARD,
                   App.ET_INPUT_VIEWSCREEN_BACKWARD]
    assert got[0] != got[1] and 0 not in got
