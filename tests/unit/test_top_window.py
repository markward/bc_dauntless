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


def test_input_dispatch_drops_event_when_gated_off():
    """The trampoline must consult keyboard_input_enabled() and skip
    KeyboardBinding.OnKeyboardEvent when gated off."""
    from engine.appc import top_window
    from engine.appc import input as appc_input
    from engine.appc.events import TGKeyboardEvent

    top_window.reset_for_tests()

    # Stand up a recording binding in place of the singleton so we can
    # observe whether the trampoline forwarded the event.
    received = []

    class RecordingBinding:
        def OnKeyboardEvent(self, obj, evt):
            received.append(evt)

    saved = appc_input.g_kKeyboardBinding
    appc_input.g_kKeyboardBinding = RecordingBinding()
    try:
        evt = TGKeyboardEvent()
        # Gate ON (default) — event should reach the binding.
        appc_input._OnKeyboardEvent_Dispatch(None, evt)
        assert len(received) == 1

        # Gate OFF — event should be dropped.
        top_window.TopWindow_GetTopWindow().AllowKeyboardInput(0)
        appc_input._OnKeyboardEvent_Dispatch(None, evt)
        assert len(received) == 1  # unchanged

        # Gate back ON — event flows again.
        top_window.TopWindow_GetTopWindow().AllowKeyboardInput(1)
        appc_input._OnKeyboardEvent_Dispatch(None, evt)
        assert len(received) == 2
    finally:
        appc_input.g_kKeyboardBinding = saved


def test_cutscene_default_off():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsCutsceneMode() is False


def test_start_cutscene_flips_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    assert tw.IsCutsceneMode() is True


def test_end_cutscene_clears_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    tw.EndCutscene()
    assert tw.IsCutsceneMode() is False


def test_end_cutscene_accepts_fade_time():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    tw.EndCutscene(2.5)   # SDK passes a fade-out duration
    assert tw.IsCutsceneMode() is False


def test_abort_cutscene_clears_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    tw.AbortCutscene()
    assert tw.IsCutsceneMode() is False


def test_cutscene_does_not_touch_input_flags():
    """MissionLib calls AllowKeyboardInput(0) explicitly around
    StartCutscene/EndCutscene; the cutscene methods must NOT
    auto-toggle the input gate or we'd double-gate."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsKeyboardInputAllowed() is True
    tw.StartCutscene()
    assert tw.IsKeyboardInputAllowed() is True   # unchanged
    tw.EndCutscene()
    assert tw.IsKeyboardInputAllowed() is True   # unchanged
