"""Unit tests for the TopWindow shim (engine/appc/top_window.py)."""


def test_singleton_exists():
    from engine.appc import top_window
    assert top_window._the_top_window is not None


def test_factory_returns_singleton():
    from engine.appc import top_window
    a = top_window.TopWindow_GetTopWindow()
    b = top_window.TopWindow_GetTopWindow()
    assert a is b
    assert a is top_window._the_top_window


def test_reset_for_tests_replaces_singleton_with_default_state():
    from engine.appc import top_window
    tw = top_window._the_top_window
    tw._cutscene_active = True
    top_window.reset_for_tests()
    new_tw = top_window._the_top_window
    assert new_tw is not tw
    assert new_tw._cutscene_active is False


def test_keyboard_input_default_enabled():
    from engine.appc import top_window
    top_window.reset_for_tests()
    assert top_window.keyboard_input_enabled() is True


def test_allow_keyboard_input_flips_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AllowKeyboardInput(0)
    assert top_window.keyboard_input_enabled() is False
    assert tw.IsKeyboardInputAllowed() is False
    tw.AllowKeyboardInput(1)
    assert top_window.keyboard_input_enabled() is True
    assert tw.IsKeyboardInputAllowed() is True


def test_allow_mouse_input_flips_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AllowMouseInput(0)
    assert top_window.mouse_input_enabled() is False
    assert tw.IsMouseInputAllowed() is False
    tw.AllowMouseInput(1)
    assert top_window.mouse_input_enabled() is True
    assert tw.IsMouseInputAllowed() is True
