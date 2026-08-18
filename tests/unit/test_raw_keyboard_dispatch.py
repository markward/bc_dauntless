"""TGInputManager posts BC's raw ET_KEYBOARD event down the window chain.

BC delivers every keystroke to the window chain as ET_KEYBOARD; SDK scripts
hook it with g_kRootWindow.AddPythonFuncHandlerForInstance(App.ET_KEYBOARD,
...)  (E1M1.CrewIntros:1971). Our pipeline previously produced only the
internal ET_KEYBOARD_EVENT broadcast consumed by KeyboardBinding, so every
such handler was dead.
"""
import sys
import types

import App
from engine.appc.events import TGEventManager, TGEventHandlerObject
from engine.appc.input import (
    TGInputManager, _raw_keyboard_destination,
    WC_S, KY_S, KS_KEYDOWN, KS_KEYUP,
)

_HELPER = "_test_raw_keyboard_dispatch_helper"


def _capture_module():
    """Register a module exposing capture(obj, evt) -> appends to .captured."""
    mod = types.ModuleType(_HELPER)
    mod.captured = []
    mod.capture = lambda _obj, evt: mod.captured.append(evt)
    sys.modules[_HELPER] = mod
    return mod


def _root_with_handler(mod):
    """Register the capture handler on the real g_kRootWindow, return it."""
    App.g_kRootWindow.AddPythonFuncHandlerForInstance(
        App.ET_KEYBOARD, _HELPER + ".capture")
    return App.g_kRootWindow


def _remove(root):
    root.RemoveHandlerForInstance(App.ET_KEYBOARD, _HELPER + ".capture")


def test_et_keyboard_is_a_real_int():
    # A _NamedStub here makes every registration unreachable: _Stub.__hash__
    # is id(self) and ET_* names are not memoized, so each access is a new key.
    assert isinstance(App.ET_KEYBOARD, int)
    assert App.ET_KEYBOARD != App.ET_KEYBOARD_EVENT


def test_et_keyboard_is_the_measured_bc_value():
    """Not an invented id: 196610 was read out of the original game.

    tools/probes/results/q13_constants_battle.txt:459 and
    tools/probes/results/ghidra_export/stbc_constants.csv:449 both record
    `App.ET_KEYBOARD = 196610 (0x30002)`.
    """
    assert App.ET_KEYBOARD == 0x30002


def test_et_keyboard_collides_with_no_other_app_event_constant():
    others = {
        n: getattr(App, n) for n in dir(App)
        if n.startswith("ET_") and n != "ET_KEYBOARD"
        and type(getattr(App, n)) is int
    }
    clash = [n for n, v in others.items() if v == App.ET_KEYBOARD]
    assert not clash, "ET_KEYBOARD aliases %r" % (clash,)


def test_keydown_reaches_a_root_window_et_keyboard_handler():
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        em = TGEventManager()
        im = TGInputManager(em)
        im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
        im.OnKeyDown(WC_S)
        assert len(mod.captured) == 1
        evt = mod.captured[0]
        assert evt.GetUnicode() == WC_S
        assert evt.GetKeyState() == KS_KEYDOWN
        assert evt.GetEventType() == App.ET_KEYBOARD
    finally:
        _remove(root)


def test_keyup_also_reaches_the_handler():
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        em = TGEventManager()
        im = TGInputManager(em)
        im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
        im.OnKeyUp(WC_S)
        assert [e.GetKeyState() for e in mod.captured] == [KS_KEYUP]
    finally:
        _remove(root)


def test_unregistered_key_does_not_dispatch():
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        em = TGEventManager()
        im = TGInputManager(em)
        # WC_S deliberately NOT registered on this manager.
        im.OnKeyDown(WC_S)
        assert mod.captured == []
    finally:
        _remove(root)


def test_no_destination_when_nothing_registered_a_handler(monkeypatch):
    # With no ET_KEYBOARD handler anywhere, the helper returns None and _emit
    # must not post a raw event (and must not raise). Isolated from the real
    # App.g_kRootWindow (which other tests in the suite may have left a
    # handler registered on) by installing a fresh TGEventHandlerObject and
    # making TopWindow_GetTopWindow() return None for the duration of this
    # test — this test's own intent is "nothing registered anywhere", not
    # "the real root window happens to be clean right now".
    monkeypatch.setattr(App, "g_kRootWindow", TGEventHandlerObject())
    monkeypatch.setattr(App, "TopWindow_GetTopWindow", lambda: None)
    assert _raw_keyboard_destination() is None
    em = TGEventManager()
    im = TGInputManager(em)
    im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
    im.OnKeyDown(WC_S)  # no exception


# ── Focus-aware routing ─────────────────────────────────────────────────────
# BC delivers the raw keystroke to the FOCUSED window first. That is the seam
# the cinematic camera keys live on: CinematicInterfaceHandlers.HandleKeyboard
# (:96) is the cinematic window's ET_KEYBOARD handler, and its
# g_dKeyToEventMapping table (:154-159) — consulted at :114 and NOWHERE else —
# is what maps WC_F1..F6 to the camera modes. Same prepend
# KeyboardBinding._resolve_destination already makes for bound ET_INPUT_*
# events; only a MAIN window counts, so QuickBattle's config-pane SetFocus()
# cannot start swallowing raw keystrokes.

def _cine_with_handler():
    """Focus the cinematic main window and give it an ET_KEYBOARD handler."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)
    cine.AddPythonFuncHandlerForInstance(App.ET_KEYBOARD, _HELPER + ".capture")
    tw.SetFocus(cine)
    return tw, cine


def test_focused_main_window_outranks_the_root_window():
    mod = _capture_module()
    root = _root_with_handler(mod)          # root has one too — real contest
    try:
        _tw, cine = _cine_with_handler()
        assert _raw_keyboard_destination() is cine
    finally:
        _remove(root)


def test_keystroke_actually_reaches_the_focused_window():
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        _tw, cine = _cine_with_handler()
        em = TGEventManager()
        im = TGInputManager(em)
        im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
        im.OnKeyDown(WC_S)
        assert len(mod.captured) == 1
        assert mod.captured[0].GetEventType() == App.ET_KEYBOARD
        # Identity, not just arrival: the same probe is registered on the root
        # window, so a count alone cannot tell the two destinations apart.
        assert mod.captured[0].GetDestination() is cine
    finally:
        _remove(root)


def test_focused_window_without_a_keyboard_handler_falls_through_to_root():
    """The existing root-window-before-TopWindow ordering is preserved for
    every window that did not register ET_KEYBOARD — E1M1's skip-intro handler
    lives on the root window and must keep its keystrokes."""
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        from engine.appc import top_window
        top_window.reset_for_tests()
        tw = top_window.TopWindow_GetTopWindow()
        tw.SetFocus(tw.FindMainWindow(top_window.MWT_CINEMATIC))  # no handlers
        assert _raw_keyboard_destination() is root
    finally:
        _remove(root)


def test_focused_non_main_window_is_not_a_candidate():
    """QuickBattle's OpenConfigDialog focuses config panes. A focused pane
    that happens to carry an ET_KEYBOARD handler must not hijack the raw
    stream — only main windows are focus candidates."""
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        from engine.appc import top_window
        top_window.reset_for_tests()
        tw = top_window.TopWindow_GetTopWindow()
        pane = TGEventHandlerObject()
        pane.AddPythonFuncHandlerForInstance(
            App.ET_KEYBOARD, _HELPER + ".capture")
        tw.SetFocus(pane)
        assert _raw_keyboard_destination() is root
    finally:
        _remove(root)


def test_nothing_focused_still_resolves_the_root_window():
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        from engine.appc import top_window
        top_window.reset_for_tests()
        assert top_window.TopWindow_GetTopWindow().GetFocus() is None
        assert _raw_keyboard_destination() is root
    finally:
        _remove(root)


def test_a_plain_top_window_double_does_not_raise(monkeypatch):
    """The focus probe must be as defensive as the _events probe beside it:
    tests monkeypatch TopWindow_GetTopWindow with doubles that have neither
    GetFocus nor _main_windows."""
    class _Bare:
        pass

    monkeypatch.setattr(App, "TopWindow_GetTopWindow", lambda: _Bare())
    mod = _capture_module()
    root = _root_with_handler(mod)
    try:
        assert _raw_keyboard_destination() is root
    finally:
        _remove(root)


def test_internal_keyboard_event_broadcast_still_fires():
    # Regression guard: the raw path is additive, not a replacement.
    from engine.appc.events import ET_KEYBOARD_EVENT
    mod = types.ModuleType(_HELPER + "_bcast")
    mod.captured = []
    mod.capture = lambda _obj, evt: mod.captured.append(evt)
    sys.modules[_HELPER + "_bcast"] = mod
    em = TGEventManager()
    im = TGInputManager(em)
    im.RegisterUnicodeKey(WC_S, KY_S, None, "s")
    em.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT, None, _HELPER + "_bcast.capture")
    im.OnKeyDown(WC_S)
    assert len(mod.captured) == 1
