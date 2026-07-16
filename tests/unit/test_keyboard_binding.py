"""KeyboardBinding.BindKey + OnKeyboardEvent — translate
(WC, KS) → (ET_*, value) and post the bound event via g_kEventManager.
"""
from engine.appc.events import TGEventManager, TGEventHandlerObject, TGKeyboardEvent
from engine.appc.input import (
    KeyboardBinding,
    WC_RBUTTON, KS_KEYDOWN, KS_KEYUP,
)


# Picked value (not the SDK's actual ET_INPUT_FIRE_SECONDARY int);
# the binding records and replays whatever event_type is provided.
_ET_INPUT_FIRE_SECONDARY = 2001


class _Dest(TGEventHandlerObject):
    def __init__(self):
        super().__init__()
        self.received = []

    def ProcessEvent(self, evt):
        self.received.append(evt)


def test_bind_key_records_mapping():
    kb = KeyboardBinding(TGEventManager())
    kb.BindKey(WC_RBUTTON, KS_KEYDOWN, _ET_INPUT_FIRE_SECONDARY,
               KeyboardBinding.GET_BOOL_EVENT, 1)
    assert (WC_RBUTTON, KS_KEYDOWN) in kb._bindings


def test_on_keyboard_event_dispatches_bound_event():
    em = TGEventManager()
    kb = KeyboardBinding(em)
    dest = _Dest()
    kb.SetDefaultDestination(dest)

    kb.BindKey(WC_RBUTTON, KS_KEYDOWN, _ET_INPUT_FIRE_SECONDARY,
               KeyboardBinding.GET_BOOL_EVENT, 1)

    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(WC_RBUTTON)
    evt.SetKeyState(KS_KEYDOWN)
    kb.OnKeyboardEvent(None, evt)

    assert len(dest.received) == 1
    out = dest.received[0]
    assert out.GetEventType() == _ET_INPUT_FIRE_SECONDARY
    assert out.GetBool() == 1


def test_keyup_routes_to_separate_binding():
    em = TGEventManager()
    kb = KeyboardBinding(em)
    dest = _Dest()
    kb.SetDefaultDestination(dest)

    # DefaultKeyboardBinding pattern: KEYDOWN bool=1, KEYUP bool=0
    kb.BindKey(WC_RBUTTON, KS_KEYDOWN, _ET_INPUT_FIRE_SECONDARY,
               KeyboardBinding.GET_BOOL_EVENT, 1)
    kb.BindKey(WC_RBUTTON, KS_KEYUP, _ET_INPUT_FIRE_SECONDARY,
               KeyboardBinding.GET_BOOL_EVENT, 0)

    e1 = TGKeyboardEvent(); e1.SetUnicodeKey(WC_RBUTTON); e1.SetKeyState(KS_KEYDOWN)
    kb.OnKeyboardEvent(None, e1)
    e2 = TGKeyboardEvent(); e2.SetUnicodeKey(WC_RBUTTON); e2.SetKeyState(KS_KEYUP)
    kb.OnKeyboardEvent(None, e2)

    assert len(dest.received) == 2
    assert dest.received[0].GetBool() == 1
    assert dest.received[1].GetBool() == 0


def test_unbound_key_state_no_op():
    em = TGEventManager()
    kb = KeyboardBinding(em)
    dest = _Dest()
    kb.SetDefaultDestination(dest)
    # No BindKey calls.
    evt = TGKeyboardEvent(); evt.SetUnicodeKey(WC_RBUTTON); evt.SetKeyState(KS_KEYDOWN)
    kb.OnKeyboardEvent(None, evt)
    assert dest.received == []


def test_int_event_binding_delivers_value():
    import App
    from engine.appc.input import KS_NORMAL

    em = TGEventManager()
    kb = KeyboardBinding(em)
    dest = _Dest()
    kb.SetDefaultDestination(dest)

    kb.BindKey(App.WC_ALT_3, KS_NORMAL, App.ET_MANAGE_POWER,
               KeyboardBinding.GET_INT_EVENT, 2,
               KeyboardBinding.KBT_SINGLE_KEY_TO_EVENT)

    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_ALT_3)
    evt.SetKeyState(KS_NORMAL)
    kb.OnKeyboardEvent(None, evt)

    assert len(dest.received) == 1
    out = dest.received[0]
    assert out.GetEventType() == App.ET_MANAGE_POWER
    assert out.GetInt() == 2


# ── Destination resolution — window-chain bubbling for keyboard-bound events ──
#
# TGEventManager.AddEvent delivers a destination event straight to
# dest.ProcessEvent with no parent-window bubbling, but the SDK registers
# ManagePower on TopWindow (EngineerMenuHandlers.py:145) and Maneuver on the
# tactical menu (TacticalMenuHandlers.py:397), while the binding's default
# destination is the TCW (host_loop.py:169,2771).  _resolve_destination scans
# [default destination, its tactical menu, TopWindow] for the first object
# with a registered instance handler for the event type.

_resolver_hits = []


def _resolver_probe(pObject, pEvent):
    _resolver_hits.append(pObject)


def test_keyboard_event_routes_to_object_with_handler(monkeypatch):
    import App
    from engine.appc.input import KS_NORMAL

    del _resolver_hits[:]
    em = TGEventManager()
    kb = KeyboardBinding(em)

    tcw = TGEventHandlerObject()          # no handler for ET_MANAGE_POWER
    top = TGEventHandlerObject()
    top.AddPythonFuncHandlerForInstance(
        App.ET_MANAGE_POWER, __name__ + "._resolver_probe")
    kb.SetDefaultDestination(tcw)
    monkeypatch.setattr(App, "TopWindow_GetTopWindow", lambda: top)

    kb.BindKey(App.WC_ALT_1, KS_NORMAL, App.ET_MANAGE_POWER,
               KeyboardBinding.GET_INT_EVENT, 0,
               KeyboardBinding.KBT_SINGLE_KEY_TO_EVENT)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_ALT_1)
    evt.SetKeyState(KS_NORMAL)
    kb.OnKeyboardEvent(None, evt)

    assert _resolver_hits == [top], \
        "ET_MANAGE_POWER must route to the object that registered the handler"


def test_keyboard_event_prefers_default_destination_when_it_handles(monkeypatch):
    import App

    del _resolver_hits[:]
    em = TGEventManager()
    kb = KeyboardBinding(em)

    tcw = TGEventHandlerObject()
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CLEAR_TARGET, __name__ + "._resolver_probe")
    top = TGEventHandlerObject()
    top.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CLEAR_TARGET, __name__ + "._resolver_probe")
    kb.SetDefaultDestination(tcw)
    monkeypatch.setattr(App, "TopWindow_GetTopWindow", lambda: top)

    kb.BindKey(App.WC_CTRL_T, KS_KEYDOWN, App.ET_INPUT_CLEAR_TARGET)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_CTRL_T)
    evt.SetKeyState(KS_KEYDOWN)
    kb.OnKeyboardEvent(None, evt)

    assert _resolver_hits == [tcw], \
        "default destination wins when it has a handler"


_manage_power_hits = []


def _manage_power_probe(pObject, pEvent):
    _manage_power_hits.append(pEvent)


def test_alt_1_chord_reaches_real_top_window_manage_power_handler():
    """ALT+1..8 route to ET_MANAGE_POWER, handled by the SDK's
    EngineerMenuHandlers registered on the REAL TopWindow singleton
    (not a monkeypatched plain TGEventHandlerObject).  _resolve_destination
    must find the handler through _TopWindow's composed `_events` object —
    the real singleton has no `_handlers` attribute of its own and is
    rejected by TGEventManager.AddEvent's isinstance(TGEventHandlerObject)
    check, so appending `top` itself (rather than `top._events`) as a
    destination candidate silently drops the event."""
    import App

    del _manage_power_hits[:]
    top = App.TopWindow_GetTopWindow()
    top.AddPythonFuncHandlerForInstance(
        App.ET_MANAGE_POWER, __name__ + "._manage_power_probe")
    try:
        em = TGEventManager()
        kb = KeyboardBinding(em)
        kb.SetDefaultDestination(TGEventHandlerObject())  # TCW stand-in, no handler

        from engine.appc.input import KS_NORMAL
        kb.BindKey(App.WC_ALT_1, KS_NORMAL, App.ET_MANAGE_POWER,
                   KeyboardBinding.GET_INT_EVENT, 0,
                   KeyboardBinding.KBT_SINGLE_KEY_TO_EVENT)
        evt = TGKeyboardEvent()
        evt.SetUnicodeKey(App.WC_ALT_1)
        evt.SetKeyState(KS_NORMAL)
        kb.OnKeyboardEvent(None, evt)

        assert len(_manage_power_hits) == 1, \
            "ET_MANAGE_POWER must reach the real TopWindow's instance handler"
        assert _manage_power_hits[0].GetInt() == 0
    finally:
        top.RemoveHandlerForInstance(
            App.ET_MANAGE_POWER, __name__ + "._manage_power_probe")
