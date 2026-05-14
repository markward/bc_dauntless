"""TGInputManager.RegisterUnicodeKey + OnKeyDown/OnKeyUp emit
TGKeyboardEvent into g_kEventManager.
"""
import sys
import types
from engine.appc.events import TGEventManager, ET_KEYBOARD_EVENT
from engine.appc.input import (
    TGInputManager, WC_RBUTTON, KY_RBUTTON, KS_KEYDOWN, KS_KEYUP,
)


def _make_capture_mod():
    """Return (module, captured_list) registered in sys.modules."""
    captured = []
    mod = types.ModuleType("_test_tg_input_manager_helper")
    mod.captured = captured
    mod.capture = lambda _obj, evt: captured.append(evt)
    sys.modules["_test_tg_input_manager_helper"] = mod
    return mod, captured


def _fresh_manager():
    """Returns (TGInputManager, TGEventManager)."""
    em = TGEventManager()
    im = TGInputManager(em)
    return im, em


def test_register_unicode_key_records_mapping():
    im, _ = _fresh_manager()
    im.RegisterUnicodeKey(WC_RBUTTON, KY_RBUTTON, None, "RButton")
    assert WC_RBUTTON in im._registered


def test_on_key_down_emits_event_for_registered_key():
    mod, captured = _make_capture_mod()
    im, em = _fresh_manager()
    im.RegisterUnicodeKey(WC_RBUTTON, KY_RBUTTON, None, "RButton")
    em.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT, None, "_test_tg_input_manager_helper.capture",
    )
    im.OnKeyDown(WC_RBUTTON)
    assert len(captured) == 1
    evt = captured[0]
    assert evt.GetUnicodeKey() == WC_RBUTTON
    assert evt.GetKeyState() == KS_KEYDOWN


def test_on_key_down_no_op_for_unregistered():
    mod, captured = _make_capture_mod()
    im, em = _fresh_manager()
    em.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT, None, "_test_tg_input_manager_helper.capture",
    )
    im.OnKeyDown(WC_RBUTTON)  # not registered
    assert captured == []


def test_on_key_up_emits_keyup_event():
    mod, captured = _make_capture_mod()
    im, em = _fresh_manager()
    im.RegisterUnicodeKey(WC_RBUTTON, KY_RBUTTON, None, "RButton")
    em.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT, None, "_test_tg_input_manager_helper.capture",
    )
    im.OnKeyUp(WC_RBUTTON)
    assert captured[0].GetKeyState() == KS_KEYUP
