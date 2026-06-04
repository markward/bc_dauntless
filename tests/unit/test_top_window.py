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


def test_fade_default_off():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsFading() is False


def test_fade_out_sets_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.FadeOut(1.5)
    assert tw.IsFading() is True


def test_fade_in_clears_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.FadeOut(1.5)
    tw.FadeIn(1.5)
    assert tw.IsFading() is False


def test_abort_fade_clears_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.FadeOut(1.5)
    tw.AbortFade()
    assert tw.IsFading() is False


def test_view_state_defaults():
    """Dauntless has no bridge view and renders the tactical scene by default."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True


def test_force_bridge_visible_swaps_state():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ForceBridgeVisible()
    assert tw.IsBridgeVisible() is True
    assert tw.IsTacticalVisible() is False


def test_force_tactical_visible_swaps_state():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ForceBridgeVisible()
    tw.ForceTacticalVisible()
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True


def test_toggle_bridge_and_tactical_swaps_both():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # Default: bridge=False, tactical=True
    tw.ToggleBridgeAndTactical()
    assert tw.IsBridgeVisible() is True
    assert tw.IsTacticalVisible() is False
    tw.ToggleBridgeAndTactical()
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True


def test_mwt_enums_are_distinct_integers():
    """The constants previously fell through to _NamedStub, whose __eq__
    returned isinstance(o, _Stub) — making MWT_CINEMATIC == MWT_BRIDGE
    nondeterministically truthy. Real ints fix that."""
    from engine.appc import top_window
    enums = [
        top_window.MWT_BRIDGE,
        top_window.MWT_TACTICAL,
        top_window.MWT_CONSOLE,
        top_window.MWT_EDITOR,
        top_window.MWT_OPTIONS,
        top_window.MWT_SUBTITLE,
        top_window.MWT_TACTICAL_MAP,
        top_window.MWT_CINEMATIC,
        top_window.MWT_MULTIPLAYER,
        top_window.MWT_CD_CHECK,
        top_window.MWT_MODAL_DIALOG,
    ]
    assert all(isinstance(v, int) for v in enums)
    assert len(set(enums)) == len(enums)   # all distinct


def test_find_main_window_returns_none_when_unregistered():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # MWT_CINEMATIC and MWT_MODAL_DIALOG are never seeded; only MWT_SUBTITLE
    # is pre-seeded by _TopWindow.__init__ (Task 5).
    assert tw.FindMainWindow(top_window.MWT_CINEMATIC) is None
    assert tw.FindMainWindow(top_window.MWT_MODAL_DIALOG) is None


def test_find_main_window_returns_registered_window():
    """Verify the lookup path — a future spec will land real backing
    windows; today no one registers, but the path must work."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    sentinel = object()
    tw._main_windows[top_window.MWT_CINEMATIC] = sentinel
    assert tw.FindMainWindow(top_window.MWT_CINEMATIC) is sentinel


def test_children_empty_by_default():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.GetNumChildren() == 0
    assert tw.GetChildren() == []


def test_add_child_records_tuple():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    label = object()
    tw.AddChild(label, 100, 200)
    assert tw.GetNumChildren() == 1
    assert tw.GetChildren() == [label]
    # Internal storage retains the position for the future CEF mirror.
    assert tw._children == [(label, 100.0, 200.0)]


def test_add_child_accepts_no_position():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddChild(object())
    assert tw.GetNumChildren() == 1


def test_add_child_accepts_extra_args():
    """Some SDK callers pass extra trailing args (e.g. z-order).
    The shim must accept them without raising."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddChild(object(), 1.0, 2.0, 0)   # 4th arg used by MissionMenusShared.py
    assert tw.GetNumChildren() == 1


def test_remove_child_drops_matching_entries():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    a, b = object(), object()
    tw.AddChild(a, 0, 0)
    tw.AddChild(b, 0, 0)
    tw.RemoveChild(a)
    assert tw.GetChildren() == [b]


def test_window_size_falls_back_when_host_not_initialised():
    """In pytest contexts _dauntless_host either isn't importable or
    raises RuntimeError because init() hasn't been called. The shim
    must fall back to a sensible default."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # Default fallback per spec: 1920x1080
    assert tw.GetWidth() == 1920
    assert tw.GetHeight() == 1080


def test_window_size_uses_host_when_available(monkeypatch):
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()

    class FakeHost:
        @staticmethod
        def window_size():
            return (800, 600)

    import sys
    monkeypatch.setitem(sys.modules, "_dauntless_host", FakeHost)
    assert tw.GetWidth() == 800
    assert tw.GetHeight() == 600


def test_initialize_and_update_are_callable():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # Must not raise; have no observable side-effects yet.
    tw.Initialize()
    tw.Update()


def test_edit_mode_toggles():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsEditModeEnabled() is False
    tw.SetEditMode(1)
    assert tw.IsEditModeEnabled() is True
    tw.ToggleEditMode()
    assert tw.IsEditModeEnabled() is False
    tw.ToggleEditMode()
    assert tw.IsEditModeEnabled() is True


def test_disable_options_menu_sets_flag():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw._options_disabled is False
    tw.DisableOptionsMenu()
    assert tw._options_disabled is True


def test_toggle_methods_are_callable():
    """Every Toggle*() method must accept zero args and not raise."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ToggleOptionsMenu()
    tw.ToggleConsole()
    tw.ToggleMapWindow()
    tw.ToggleCinematicWindow()
    tw.ToggleWireframe()


def test_show_bad_connection_text_callable():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ShowBadConnectionText(1)
    tw.ShowBadConnectionText(0)


def test_last_rendered_set_round_trips():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.GetLastRenderedSet() is None
    sentinel = object()
    tw.SetLastRenderedSet(sentinel)
    assert tw.GetLastRenderedSet() is sentinel


def test_app_top_window_get_top_window_returns_real_singleton():
    """SDK code calls App.TopWindow_GetTopWindow() — that path must
    reach the real _TopWindow, not fall through to _NamedStub."""
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = App.TopWindow_GetTopWindow()
    assert tw is top_window._the_top_window


def test_app_mwt_enums_are_real_ints():
    """Previously these fell through to _NamedStub and compared
    equal to each other via _Stub.__eq__. Real ints fix that."""
    import App
    from engine.appc import top_window
    assert App.MWT_BRIDGE == top_window.MWT_BRIDGE
    assert App.MWT_CINEMATIC == top_window.MWT_CINEMATIC
    assert isinstance(App.MWT_BRIDGE, int)
    assert App.MWT_BRIDGE != App.MWT_CINEMATIC


def test_reset_sdk_globals_resets_top_window_state():
    """A previous mission's cutscene/view/input flags must not bleed
    into the next mission. reset_sdk_globals() owns that contract."""
    from engine.host_loop import reset_sdk_globals
    from engine.appc import top_window

    # Dirty the state as if a prior mission had run.
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    tw.AllowKeyboardInput(0)
    tw.ForceBridgeVisible()

    reset_sdk_globals()

    fresh = top_window.TopWindow_GetTopWindow()
    assert fresh.IsCutsceneMode() is False
    assert fresh.IsKeyboardInputAllowed() is True
    assert fresh.IsBridgeVisible() is False
    assert fresh.IsTacticalVisible() is True


def test_start_cutscene_accepts_positional_args():
    """SDK code calls StartCutscene(fTimeToComeIn, fCoveredArea, bHideReticle)
    via MissionLib.StartCutscene (sdk/Build/scripts/MissionLib.py:751).
    We accept and ignore the args — we don't render fade-ins or reticles."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(2.0, 0.5, 1)
    assert tw.IsCutsceneMode() is True


def test_add_python_func_handler_for_instance_records_registration():
    """SDK Initialize() routines call pTop.AddPythonFuncHandlerForInstance(...)
    to register per-instance event handlers. We record the registrations
    but don't dispatch through them today — when an SDK event flow needs
    these handlers, a follow-up will wire them into g_kEventManager."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddPythonFuncHandlerForInstance(1001, "some.module.handler")
    tw.AddPythonFuncHandlerForInstance(1002, "another.handler")
    assert tw._handler_registrations == [
        (1001, "some.module.handler"),
        (1002, "another.handler"),
    ]


def test_add_python_func_handler_accepts_extra_args():
    """The underlying TGEventManager.AddBroadcastPythonFuncHandler has a
    *extra trailing varargs; mirror that on the shim so any SDK caller
    passing trailing args doesn't TypeError."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # Should not raise even with extra trailing args
    tw.AddPythonFuncHandlerForInstance(1001, "x.y", "extra", 42)
    assert len(tw._handler_registrations) == 1


def test_subtitle_window_seeded_after_init():
    from engine.appc import top_window
    from engine.appc.windows import _SubtitleWindow
    top_window.reset_for_tests()
    sub = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    assert isinstance(sub, _SubtitleWindow)


def test_reset_for_tests_replaces_subtitle_singleton():
    from engine.appc import top_window
    sub_before = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    top_window.reset_for_tests()
    sub_after = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    assert sub_after is not sub_before


def test_reset_for_tests_resets_stylized_counter():
    from engine.appc import top_window
    from engine.appc.windows import _STStylizedWindow, STStylizedWindow_CreateW
    STStylizedWindow_CreateW("A")
    STStylizedWindow_CreateW("B")
    assert _STStylizedWindow._counter == 2
    top_window.reset_for_tests()
    assert _STStylizedWindow._counter == 0
