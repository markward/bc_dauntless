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

        def event_type_for(self, evt):
            # Not a bridge crew-menu key -> honours the keyboard lockout.
            return None

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
    # MWT_MODAL_DIALOG is never seeded; only MWT_SUBTITLE, MWT_OPTIONS,
    # MWT_CINEMATIC, MWT_BRIDGE and MWT_TACTICAL are pre-seeded by
    # _TopWindow.__init__ (see the *_is_preseeded tests below for why).
    assert tw.FindMainWindow(top_window.MWT_MODAL_DIALOG) is None


def test_find_main_window_bridge_tactical_preseeded_support_addchild():
    """MWT_BRIDGE / MWT_TACTICAL must be pre-seeded and support AddChild: SDK UI
    (Tactical.Interface.TacticalControlWindow.Refresh, run at the end of the
    E6M2 dock via DockWithStarbase.FinishedUndocking) re-parents the TCW into the
    visible main window with no None guard —
    `pTop.FindMainWindow(MWT_TACTICAL).AddChild(pTacCtrlWindow, 0.0, 0.0, 0)`.
    Raw None there crashed 'NoneType has no attribute AddChild'."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    child = object()
    for mwt in (top_window.MWT_TACTICAL, top_window.MWT_BRIDGE):
        w = tw.FindMainWindow(mwt)
        assert w is not None
        w.AddChild(child, 0.0, 0.0, 0)          # the exact Refresh() call — no crash
        w.RemoveChild(child, 0)
        assert w.GetObjID() is not None         # SDK also reads GetObjID on these


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


def test_cinematic_window_reports_normal_non_cutscene_state():
    """Real BC's Cinematic main window, in the normal (non-cutscene) state,
    reports NOT active and interactive. _CinematicWindow previously only
    inherited TGEventHandlerObject, so IsWindowActive()/IsInteractive()
    fell through to a truthy _Stub, which flipped OR-guards at two
    confirmed SDK sites (Bridge/TacticalInterfaceHandlers.GotFocus and
    MissionLib.ExitGame) the wrong way.

    A `_Stub` compares `== 0` as False (so `IsInteractive() == 1` fails)
    and is truthy under `bool()` (so `bool(IsWindowActive()) is False`
    fails) — this pins the RED reason before the explicit methods exist.
    """
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    pCinematic = top_window._the_top_window.FindMainWindow(App.MWT_CINEMATIC)
    assert bool(pCinematic.IsWindowActive()) is False
    assert pCinematic.IsInteractive() == 1


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


# ── Cinematic mode ──────────────────────────────────────────────────────────
# BC enters cinematic mode by focusing the MWT_CINEMATIC main window
# (Actions/CameraScriptActions.py:StartCinematicMode compares GetFocus()
# against it). Focus is the single source of truth — there is no second flag.

def test_toggle_cinematic_window_focuses_and_unfocuses():
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)

    assert tw.GetFocus() is None
    assert tw.is_cinematic_active() is False

    tw.ToggleCinematicWindow()
    assert tw.GetFocus() is cine
    assert tw.is_cinematic_active() is True
    assert cine.IsWindowActive() == 1

    tw.ToggleCinematicWindow()
    assert tw.GetFocus() is None
    assert tw.is_cinematic_active() is False
    assert cine.IsWindowActive() == 0


def test_cinematic_window_interactive_state_round_trips():
    from engine.appc import top_window
    top_window.reset_for_tests()
    cine = top_window.TopWindow_GetTopWindow().FindMainWindow(
        top_window.MWT_CINEMATIC)
    assert cine.IsInteractive() == 1        # BC normal-state default, unchanged
    cine.SetInteractive(0)
    assert cine.IsInteractive() == 0
    cine.SetInteractive(1)
    assert cine.IsInteractive() == 1


def test_is_cinematic_active_false_when_another_child_holds_focus():
    """QuickBattle's OpenConfigDialog focuses a config pane. That must not read
    as cinematic mode."""
    from engine.appc import top_window
    from engine.appc.events import TGEventHandlerObject
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.SetFocus(TGEventHandlerObject())
    assert tw.is_cinematic_active() is False


# ── Entering cinematic mode drops an open crew menu ─────────────────────────
# Live bug: F9 hides the tactical HUD but leaves an already-open crew/officer
# menu on screen. Cinematic mode should be a clean camera view. The fix reuses
# the exact primitive StartCutscene already calls at its own entry
# (_drop_open_crew_menu, :103/:369) -- must fire on ENTER only, never on exit.

def _wired_officer_for_menu_drop_test(name="Helm", label="Helm"):
    """A bridge officer with a menu attached and registered on the TCW's menu
    list, with a CrewMenuPanel wired -- mirrors
    tests/unit/test_cutscene_menu_drop.py's _wired_officer, which exercises
    the same App.STTopLevelMenu_GetOpenMenu()/GetOwner()/MenuDown() primitive
    _drop_open_crew_menu uses."""
    import App
    from engine.appc.characters import STTopLevelMenu_CreateW
    from engine.appc.windows import TacticalControlWindow
    from engine.ui import crew_menu_hotkeys
    from engine.ui.crew_menu_panel import CrewMenuPanel

    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    tac_menu = STTopLevelMenu_CreateW(db.GetString("Tactical"))
    tac_menu.AddChild(App.STButton_CreateW(db.GetString("Manual Aim")))
    tcw.SetTacticalMenu(tac_menu)
    App.g_kLocalizationManager.Unload(db)

    menu = STTopLevelMenu_CreateW(label)
    tcw.AddMenuToList(menu)
    panel = CrewMenuPanel()
    crew_menu_hotkeys.wire(tcw, panel)
    officer = App.CharacterClass_Create("b.nif", "h.nif")
    officer.SetCharacterName(name)
    officer.SetMenu(menu)
    return officer, menu, panel


def test_entering_cinematic_mode_drops_an_open_crew_menu():
    """The bug: F9 (ToggleCinematicWindow, entering) must close whatever crew
    menu is currently up, exactly as StartCutscene already does."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    officer, _menu, panel = _wired_officer_for_menu_drop_test()
    officer.MenuUp()
    assert panel.has_open_menu() is True

    tw = top_window.TopWindow_GetTopWindow()
    tw.ToggleCinematicWindow()          # ENTER cinematic mode

    assert tw.is_cinematic_active() is True
    assert panel.has_open_menu() is False
    assert officer.IsMenuUp() == 0


def test_leaving_cinematic_mode_does_not_drop_a_crew_menu():
    """The other half: leaving cinematic mode must NOT run the drop. A menu
    opened only after entering (there is nothing before entry to leave open
    in real play -- F1-F5 are vetoed while focused on the cinematic window --
    but the shim-level primitive itself must not fire on exit either way)
    must still be open once the player toggles back out."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    officer, _menu, panel = _wired_officer_for_menu_drop_test()

    tw = top_window.TopWindow_GetTopWindow()
    tw.ToggleCinematicWindow()          # enter -- nothing open yet
    assert tw.is_cinematic_active() is True

    officer.MenuUp()                    # opened while already in cinematic mode
    assert panel.has_open_menu() is True

    tw.ToggleCinematicWindow()          # LEAVE cinematic mode
    assert tw.is_cinematic_active() is False
    assert panel.has_open_menu() is True    # unchanged -- exit must not drop
    assert officer.IsMenuUp() == 1


def test_entering_cinematic_mode_is_safe_with_no_menu_open():
    """No open menu -> the drop must be a harmless no-op, not raise."""
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    tw.ToggleCinematicWindow()          # must not raise
    assert tw.is_cinematic_active() is True


# ── Lazy SDK handler registration ───────────────────────────────────────────
# CinematicInterfaceHandlers.Initialize(pWindow) is what binds the six
# ET_INPUT_CINEMATIC_* events to camera modes. No SDK script calls it — BC's
# engine ran it at window construction — so we run it lazily on first toggle,
# because the module imports Camera and must not be pulled into App bootstrap.

def test_first_toggle_registers_the_sdk_cinematic_handlers():
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)

    assert cine._handlers == {}
    tw.ToggleCinematicWindow()
    assert cine._handlers.get(App.ET_INPUT_CINEMATIC_CHASE)
    assert cine._handlers.get(App.ET_INPUT_CINEMATIC_FREEORBIT)


def test_first_toggle_registers_the_windows_raw_keyboard_handler():
    """Initialize()'s loop (CinematicInterfaceHandlers.py:54-56) registers ONLY
    the ET_INPUT_* handlers; it never registers HandleKeyboard. In real BC the
    engine wires the window's keyboard handler at construction. Without it the
    F1-F6 camera keys have no path at all: the g_dKeyToEventMapping table is
    consulted from inside HandleKeyboard (:114) and nowhere else."""
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)

    tw.ToggleCinematicWindow()
    assert cine._handlers.get(App.ET_KEYBOARD) == [
        "CinematicInterfaceHandlers.HandleKeyboard"]


def test_handlers_are_registered_once_not_per_toggle():
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)
    for _ in range(4):
        tw.ToggleCinematicWindow()
    assert len(cine._handlers[App.ET_INPUT_CINEMATIC_CHASE]) == 1
    assert len(cine._handlers[App.ET_KEYBOARD]) == 1


def test_a_failing_initialize_neither_wedges_the_toggle_nor_stays_silent(capsys):
    """Cinematic mode without its F-key handlers is degraded, not broken — so
    a failure must not block the focus flip. But it must not be silent either,
    or a missing-surface gap looks like a working feature."""
    import CinematicInterfaceHandlers
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()

    def _boom(_pWindow):
        raise RuntimeError("missing engine surface")

    real = CinematicInterfaceHandlers.Initialize
    CinematicInterfaceHandlers.Initialize = _boom
    try:
        tw.ToggleCinematicWindow()
    finally:
        CinematicInterfaceHandlers.Initialize = real

    assert tw.is_cinematic_active() is True
    assert "missing engine surface" in capsys.readouterr().out


def test_a_failing_keyboard_registration_names_that_step_not_initialize(capsys):
    """The two wiring steps are independent and fail independently. Blaming
    Initialize for a HandleKeyboard registration failure would send whoever
    reads the log to the wrong module."""
    import CinematicInterfaceHandlers
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)

    def _raise(*_a, **_k):
        raise RuntimeError("registration blew up")

    real = CinematicInterfaceHandlers.Initialize
    CinematicInterfaceHandlers.Initialize = lambda _w: None   # step 1 succeeds
    cine.AddPythonFuncHandlerForInstance = _raise             # step 2 fails
    try:
        tw.ToggleCinematicWindow()
    finally:
        CinematicInterfaceHandlers.Initialize = real

    out = capsys.readouterr().out
    assert "registration blew up" in out
    assert "HandleKeyboard" in out
    assert "Initialize failed" not in out
    assert tw.is_cinematic_active() is True


def test_a_failing_initialize_still_wires_the_keyboard_handler(capsys):
    """Independent steps: losing the camera-mode handlers must not also cost
    the raw keyboard route (and vice versa)."""
    import App
    import CinematicInterfaceHandlers
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    cine = tw.FindMainWindow(top_window.MWT_CINEMATIC)

    def _boom(_pWindow):
        raise RuntimeError("missing engine surface")

    real = CinematicInterfaceHandlers.Initialize
    CinematicInterfaceHandlers.Initialize = _boom
    try:
        tw.ToggleCinematicWindow()
    finally:
        CinematicInterfaceHandlers.Initialize = real

    assert capsys.readouterr().out.count("missing engine surface") == 1
    assert cine._handlers.get(App.ET_KEYBOARD) == [
        "CinematicInterfaceHandlers.HandleKeyboard"]


def test_a_failing_initialize_is_not_retried_every_toggle(capsys):
    """The once-only latch is set BEFORE the attempt, so a broken Initialize
    cannot spam the log (or half-register) on every subsequent toggle."""
    import CinematicInterfaceHandlers
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()

    def _boom(_pWindow):
        raise RuntimeError("missing engine surface")

    real = CinematicInterfaceHandlers.Initialize
    CinematicInterfaceHandlers.Initialize = _boom
    try:
        for _ in range(4):
            tw.ToggleCinematicWindow()
    finally:
        CinematicInterfaceHandlers.Initialize = real

    assert capsys.readouterr().out.count("missing engine surface") == 1


# ── CinematicWindow_Cast ────────────────────────────────────────────────────
# Seven SDK sites do
#     pCinematic = App.CinematicWindow_Cast(pTop.FindMainWindow(MWT_CINEMATIC))
#     if pCinematic: pCinematic.SetInteractive(...) / .IsInteractive()
# (MissionLib:784, TacticalInterfaceHandlers:1038, WarpSequence:504,
# CinematicInterfaceHandlers:316, CameraScriptActions:396+413,
# QuickBattle:3324).  Undefined, the name resolved to a truthy _NamedStub —
# rank 64 in docs/stub_heatmap.md, 246 live hits — so every one of them called
# SetInteractive/IsInteractive on a stub and the real window state was
# unreachable from SDK code.  Same shape as the armed MapWindow_Cast trap
# documented at top_window.py:269.

def test_cinematic_window_cast_returns_the_real_window():
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    cine = top_window.TopWindow_GetTopWindow().FindMainWindow(
        top_window.MWT_CINEMATIC)
    assert App.CinematicWindow_Cast(cine) is cine


def test_cinematic_window_cast_rejects_a_non_cinematic_window():
    """A REAL cast, not an identity function: anything that is not a
    _CinematicWindow must come back None so `if pCinematic:` skips."""
    import App
    from engine.appc import top_window
    from engine.appc.events import TGEventHandlerObject
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    assert App.CinematicWindow_Cast(None) is None
    assert App.CinematicWindow_Cast(tw.FindMainWindow(
        top_window.MWT_TACTICAL)) is None
    assert App.CinematicWindow_Cast(TGEventHandlerObject()) is None


def test_cinematic_window_cast_survives_the_real_sdk_call_shape():
    """CinematicInterfaceHandlers.ToggleCinematicMode:316-318 reads
    IsInteractive() off the cast result — that must be Task 2's real state,
    not a stub's truthy answer."""
    import App
    from engine.appc import top_window
    top_window.reset_for_tests()
    tw = top_window.TopWindow_GetTopWindow()
    pCinematic = App.CinematicWindow_Cast(tw.FindMainWindow(App.MWT_CINEMATIC))
    assert pCinematic is not None
    pCinematic.SetInteractive(0)
    assert pCinematic.IsInteractive() == 0
    assert tw.FindMainWindow(App.MWT_CINEMATIC).IsInteractive() == 0


# ── Toggle drives the real SDK camera switch ────────────────────────────────
# BC's C++ engine calls Camera.PlayerCameraAsCinematic/AsSpace on window
# switch; our toggle (ToggleCinematicWindow) is that seam. NewMode runs
# against the seeded player camera (bReplace=1), so the raw current mode
# (arg 0, unresolved) must be the Invalid* marker and the stack must not grow
# across repeated toggles.

def test_toggle_switches_the_player_camera_to_cinematic_and_back():
    """BC's engine calls Camera.PlayerCameraAsCinematic/AsSpace on window
    switch; our toggle is that seam. Raw mode (arg 0) is the marker; NewMode
    replaces (bReplace=1) so the stack must not grow with repeated toggles."""
    import App
    from engine.appc import top_window
    from engine.core.game import Game, _set_current_game

    top_window.reset_for_tests()
    _set_current_game(Game())
    tw = top_window.TopWindow_GetTopWindow()
    cam = App.Game_GetCurrentGame().GetPlayerCamera()

    tw.ToggleCinematicWindow()               # enter
    raw = cam.GetCurrentCameraMode(0)
    assert getattr(raw, "_named", None) == "InvalidCinematic"

    tw.ToggleCinematicWindow()               # exit
    raw = cam.GetCurrentCameraMode(0)
    assert getattr(raw, "_named", None) == "InvalidSpace"

    depth_before = len(cam._mode_stack)
    for _ in range(4):
        tw.ToggleCinematicWindow()
    assert len(cam._mode_stack) == depth_before
