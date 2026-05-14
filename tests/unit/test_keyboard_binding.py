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
