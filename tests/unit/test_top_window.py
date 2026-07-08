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


# ── Cutscene overlay state (letterbox + reticle hide) ────────────────────────

def test_start_cutscene_captures_covered_and_reticle_args():
    """MissionLib.StartCutscene passes (fTimeToComeIn, fCoveredArea,
    bHideReticle); the overlay snapshot must reflect them for the CEF
    letterbox and the reticle gate."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(1.0, 0.125, 1)
    snap = tw.letterbox_snapshot()
    assert snap["visible"] is True
    assert snap["covered"] == 0.125
    assert snap["transition_s"] == 1.0
    assert tw.reticle_hidden() is True


def test_letterbox_snapshot_default_before_cutscene():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    snap = tw.letterbox_snapshot()
    assert snap["type"] == "letterbox"
    assert snap["visible"] is False
    assert tw.reticle_hidden() is False


def test_end_cutscene_hides_letterbox_and_reticle():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(1.0, 0.125, 1)
    tw.EndCutscene(2.5)
    snap = tw.letterbox_snapshot()
    assert snap["visible"] is False
    assert snap["transition_s"] == 2.5   # bars animate out over fTimeToLeave
    assert tw.reticle_hidden() is False


def test_start_cutscene_reticle_kept_when_flag_zero():
    """E1M2's later cutscenes pass bHideReticle=FALSE — reticle stays."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(1.0, 0.125, 0)
    assert tw.IsCutsceneMode() is True
    assert tw.reticle_hidden() is False


def test_start_cutscene_defaults_when_no_args():
    """Direct pTop.StartCutscene() (no args) uses BC defaults."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene()
    snap = tw.letterbox_snapshot()
    assert snap["visible"] is True
    assert snap["covered"] == 0.125       # BC default fCoveredArea
    assert tw.reticle_hidden() is True     # BC default bHideReticle=1


def test_abort_cutscene_hides_letterbox():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(1.0, 0.125, 1)
    tw.AbortCutscene()
    assert tw.letterbox_snapshot()["visible"] is False
    assert tw.reticle_hidden() is False
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
    """TopWindow's bridge/tactical view defaults to bridge-visible."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsBridgeVisible() is True
    assert tw.IsTacticalVisible() is False


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
    # Default: bridge=True, tactical=False
    tw.ToggleBridgeAndTactical()
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True
    tw.ToggleBridgeAndTactical()
    assert tw.IsBridgeVisible() is True
    assert tw.IsTacticalVisible() is False


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
    # MWT_MODAL_DIALOG is never seeded; only MWT_SUBTITLE, MWT_OPTIONS, and
    # MWT_CINEMATIC are pre-seeded by _TopWindow.__init__ (see
    # test_find_main_window_cinematic_is_preseeded below for why).
    assert tw.FindMainWindow(top_window.MWT_MODAL_DIALOG) is None


def test_find_main_window_returns_registered_window():
    """Verify the lookup path works for an arbitrary registration, on top
    of whatever _TopWindow.__init__ pre-seeds."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    sentinel = object()
    tw._main_windows[top_window.MWT_MODAL_DIALOG] = sentinel
    assert tw.FindMainWindow(top_window.MWT_MODAL_DIALOG) is sentinel


def test_find_main_window_cinematic_is_preseeded():
    """Real BC's Cinematic main window always exists, and
    AI/Compound/DockWithStarbase.SetupCutscene dereferences
    FindMainWindow(MWT_CINEMATIC).GetObjID() with no None-guard (unlike
    Actions.CameraScriptActions.Start/StopCinematicMode, which checks
    `if pCinematic:` first). Returning raw None here — as an earlier,
    documented-intentional simplification did — is a live AttributeError
    crash risk the moment anything calls TopWindow.SetFocus() with a
    non-None value before the player docks (e.g. Bridge/XOMenuHandlers.
    ShowLog's "Show Mission Log" button, which sets focus and never clears
    it). MWT_CINEMATIC must resolve to a real object with a stable
    GetObjID(), mirroring the MWT_OPTIONS / _OptionsWindow precedent."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    pCinematic = tw.FindMainWindow(top_window.MWT_CINEMATIC)
    assert pCinematic is not None
    assert isinstance(pCinematic.GetObjID(), int)


def test_dock_cutscene_focus_check_does_not_crash_when_focus_is_set():
    """Reproduces AI/Compound/DockWithStarbase.SetupCutscene's exact
    unguarded pattern:

        pFocus = pTopWindow.GetFocus()
        pCinematic = pTopWindow.FindMainWindow(App.MWT_CINEMATIC)
        if (not pFocus) or (pFocus.GetObjID() != pCinematic.GetObjID()):
            pTopWindow.ToggleCinematicWindow()

    Before the MWT_CINEMATIC pre-seed fix, this raised AttributeError on
    'NoneType' object has no attribute 'GetObjID' whenever pFocus was
    truthy (e.g. after the XO menu's mission-log button ran SetFocus)."""
    from engine.appc import top_window
    from engine.core.ids import TGObject
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.SetFocus(TGObject())  # simulate a non-None focus, e.g. the mission log
    pFocus = tw.GetFocus()
    pCinematic = tw.FindMainWindow(top_window.MWT_CINEMATIC)
    if (not pFocus) or (pFocus.GetObjID() != pCinematic.GetObjID()):
        tw.ToggleCinematicWindow()


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
    tw.ForceTacticalVisible()

    reset_sdk_globals()

    fresh = top_window.TopWindow_GetTopWindow()
    assert fresh.IsCutsceneMode() is False
    assert fresh.IsKeyboardInputAllowed() is True
    assert fresh.IsBridgeVisible() is True
    assert fresh.IsTacticalVisible() is False


def test_start_cutscene_accepts_positional_args():
    """SDK code calls StartCutscene(fTimeToComeIn, fCoveredArea, bHideReticle)
    via MissionLib.StartCutscene (sdk/Build/scripts/MissionLib.py:751).
    We accept and ignore the args — we don't render fade-ins or reticles."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(2.0, 0.5, 1)
    assert tw.IsCutsceneMode() is True


def test_add_python_func_handler_accepts_extra_args():
    """The underlying TGEventManager.AddBroadcastPythonFuncHandler has a
    *extra trailing varargs; mirror that on the shim so any SDK caller
    passing trailing args doesn't TypeError."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    # Should not raise even with extra trailing args
    tw.AddPythonFuncHandlerForInstance(1001, "x.y", "extra", 42)


_chain_log = []


def _swallowing_handler(dispatcher, event):
    _chain_log.append("swallow")
    # returns WITHOUT CallNextHandler -> chain stops (E1M1 tutorial shape)


def _passthrough_handler(dispatcher, event):
    _chain_log.append("pass")
    dispatcher.CallNextHandler(event)


def test_default_view_is_bridge():
    from engine.appc.top_window import _TopWindow
    tw = _TopWindow()
    assert tw.IsBridgeVisible() is True
    assert tw.IsTacticalVisible() is False


def test_reset_restores_bridge_default():
    import engine.appc.top_window as top_window
    top_window.TopWindow_GetTopWindow().ForceTacticalVisible()
    top_window.reset_for_tests()
    assert top_window.TopWindow_GetTopWindow().IsBridgeVisible() is True


def test_toggle_event_default_handler_flips_view():
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsBridgeVisible() is True
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert tw.IsBridgeVisible() is False
    assert tw.IsTacticalVisible() is True


def test_mission_handler_swallows_toggle():
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    _chain_log.clear()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddPythonFuncHandlerForInstance(
        ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL, __name__ + "._swallowing_handler")
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert _chain_log == ["swallow"]
    assert tw.IsBridgeVisible() is True      # default never ran — view held


def test_mission_handler_passthrough_reaches_default():
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    _chain_log.clear()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddPythonFuncHandlerForInstance(
        ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL, __name__ + "._passthrough_handler")
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert _chain_log == ["pass"]
    assert tw.IsBridgeVisible() is False     # default ran via CallNextHandler


def test_remove_handler_for_instance():
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    _chain_log.clear()
    tw = top_window.TopWindow_GetTopWindow()
    name = __name__ + "._swallowing_handler"
    tw.AddPythonFuncHandlerForInstance(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL, name)
    tw.RemoveHandlerForInstance(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL, name)
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert _chain_log == []                  # removed handler never fired
    assert tw.IsBridgeVisible() is False     # default still ran


def test_reset_rebuilds_default_handler():
    # The lifecycle rule: the default lives in __init__, so a singleton
    # rebuild (mission swap) must re-arm it with no external wiring.
    import engine.appc.top_window as top_window
    from engine.appc.events import TGEvent, ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL
    top_window.reset_for_tests()
    top_window.reset_for_tests()             # twice — idempotent
    tw = top_window.TopWindow_GetTopWindow()
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    tw.ProcessEvent(ev)
    assert tw.IsBridgeVisible() is False


def test_subtitle_window_seeded_after_init():
    from engine.appc import top_window
    from engine.appc.windows import _SubtitleWindow
    top_window.reset_for_tests()
    sub = top_window._the_top_window.FindMainWindow(top_window.MWT_SUBTITLE)
    assert isinstance(sub, _SubtitleWindow)


def test_options_window_seeded_after_init():
    """Real BC always has an Options main window in the Appc UI hierarchy, so
    SDK code dereferences FindMainWindow(MWT_OPTIONS) without a None check
    (Bridge/HelmMenuHandlers.ObjectEnteredSet:407 crashed on warp set-entry).
    We render no SDK Options window, so it reports never-visible."""
    from engine.appc import top_window
    from engine.appc.windows import _OptionsWindow
    top_window.reset_for_tests()
    opts = top_window._the_top_window.FindMainWindow(top_window.MWT_OPTIONS)
    assert isinstance(opts, _OptionsWindow)
    assert opts.IsCompletelyVisible() == 0
    assert opts.IsVisible() == 0


def test_app_find_main_window_options_is_not_none():
    """The SDK path: App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_OPTIONS)
    must never return None — HelmMenuHandlers calls IsCompletelyVisible() on it
    unconditionally."""
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    opts = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_OPTIONS)
    assert opts is not None
    assert opts.IsCompletelyVisible() == 0


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


def test_dispatch_toggle_helper_round_trip():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert tw.IsBridgeVisible() is True
    top_window.dispatch_toggle_bridge_and_tactical()
    assert tw.IsBridgeVisible() is False
    top_window.dispatch_toggle_bridge_and_tactical()
    assert tw.IsBridgeVisible() is True


def test_dispatch_toggle_helper_respects_mission_swallow():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    _chain_log.clear()
    tw = top_window.TopWindow_GetTopWindow()
    tw.AddPythonFuncHandlerForInstance(
        top_window.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
        __name__ + "._swallowing_handler")
    top_window.dispatch_toggle_bridge_and_tactical()
    assert tw.IsBridgeVisible() is True      # held on bridge
