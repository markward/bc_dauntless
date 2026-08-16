"""TGInputManager.RegisterUnicodeKey + OnKeyDown/OnKeyUp emit
TGKeyboardEvent into g_kEventManager.
"""
import sys
import types
from engine.appc.events import TGEventManager, ET_KEYBOARD_EVENT
from engine.appc.input import (
    TGInputManager, WC_RBUTTON, KY_RBUTTON, KS_KEYDOWN, KS_KEYUP, KS_NORMAL,
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


def test_modifier_registered_chord_emits_keydown_and_normal():
    import App
    mod, captured = _make_capture_mod()
    im, em = _fresh_manager()
    im.RegisterUnicodeKey(App.WC_ALT_1, App.KY_1, None, "ALT-1", App.KY_ALT)
    em.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT, None, "_test_tg_input_manager_helper.capture",
    )
    im.OnChordDown(App.WC_ALT_1)
    seen = [(evt.GetUnicodeKey(), evt.GetKeyState()) for evt in captured]
    assert (App.WC_ALT_1, KS_KEYDOWN) in seen
    assert (App.WC_ALT_1, KS_NORMAL) in seen


def test_unregistered_chord_is_dropped():
    import App
    mod, captured = _make_capture_mod()
    im, em = _fresh_manager()
    em.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT, None, "_test_tg_input_manager_helper.capture",
    )
    im.OnChordDown(App.WC_CTRL_Z)  # never registered
    assert captured == []


def test_keyup_works_for_modifier_registered_code():
    import App
    mod, captured = _make_capture_mod()
    im, em = _fresh_manager()
    im.RegisterUnicodeKey(App.WC_CAPS_K, App.KY_K, None, "K", App.KY_SHIFT)
    em.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT, None, "_test_tg_input_manager_helper.capture",
    )
    im.OnKeyUp(App.WC_CAPS_K)
    assert [evt.GetKeyState() for evt in captured] == [KS_KEYUP]


# ── GetDisplayStringFromUnicode ────────────────────────────────────────────
#
# BC returns the printable label for a key so scripts can build help text
# ("Press 's' to skip introduction", E1M1's W/S/A/D tactical help). The label
# comes from the 4th RegisterUnicodeKey argument, localized through the 3rd
# (a TGL database). Rank 57 in docs/stub_heatmap.md, 342 live hits.

class _FakeDatabase:
    """Minimal TGL database stand-in: GetString(key) -> localized text."""
    def __init__(self, mapping):
        self._mapping = mapping

    def GetString(self, key):
        from engine.appc.localization import _TGString
        return _TGString(self._mapping.get(str(key), str(key)))


def test_display_string_uses_the_registered_name():
    from engine.appc.input import WC_S, KY_S
    im, _ = _fresh_manager()
    im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
    assert im.GetDisplayStringFromUnicode(WC_S).GetCString() == "s"


def test_display_string_is_localized_through_the_database():
    from engine.appc.input import WC_ESCAPE, KY_ESCAPE
    im, _ = _fresh_manager()
    db = _FakeDatabase({"ESC": "Esc"})
    im.RegisterUnicodeKey(WC_ESCAPE, KY_ESCAPE, db, "ESC")
    assert im.GetDisplayStringFromUnicode(WC_ESCAPE).GetCString() == "Esc"


def test_display_string_falls_back_to_the_name_when_db_lacks_the_key():
    from engine.appc.input import WC_S, KY_S
    im, _ = _fresh_manager()
    im.RegisterUnicodeKey(WC_S, KY_S, _FakeDatabase({}), "s")
    assert im.GetDisplayStringFromUnicode(WC_S).GetCString() == "s"


def test_display_string_for_unregistered_key_is_empty_not_a_stub():
    from engine.appc.input import WC_S
    im, _ = _fresh_manager()
    result = im.GetDisplayStringFromUnicode(WC_S)
    assert result.GetCString() == ""


def test_display_string_result_compares_equal_to_a_plain_str():
    # E1M1.SkipOpeningSequence compares
    #   kDisplayString.GetCString() == kSkipKey.GetCString()
    # where the right side comes from a TGL lookup. Both must be str-comparable.
    from engine.appc.input import WC_S, KY_S
    im, _ = _fresh_manager()
    im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
    lhs = im.GetDisplayStringFromUnicode(WC_S).GetCString()
    assert lhs == "s"
