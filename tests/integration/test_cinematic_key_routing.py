"""F1-F6 end-to-end in cinematic mode.

The camera keys do NOT go through g_kKeyboardBinding. BC routes the raw
keystroke to the focused window, whose ET_KEYBOARD handler is
CinematicInterfaceHandlers.HandleKeyboard (:96); that calls
InterfaceHandlers.TriggerKeyboardEvents(g_dKeyToEventMapping, ...) FIRST
(:114), and that table (:154-159) is the only thing mapping WC_F1..F6 to the
six ET_INPUT_CINEMATIC_* camera modes. g_kKeyboardBinding.LaunchEvent is
consulted only if that missed (:117-119).

So the whole chain under test is: OnKeyDown -> raw ET_KEYBOARD ->
_raw_keyboard_destination picks the FOCUSED cinematic window -> HandleKeyboard
-> TriggerKeyboardEvents -> ET_INPUT_CINEMATIC_* delivered back to that window,
where CinematicInterfaceHandlers.Initialize registered the camera handlers.
"""
import App
from engine.appc import top_window
from engine.appc.input import TGInputManager

_hits: list = []
_talk_hits: list = []


def _probe(obj, evt):
    """Records the delivery and STOPS the chain (no CallNextHandler), so the
    real CameraChase/CameraFreeOrbit handler underneath never runs — those
    need a live player camera, which is not what this test is about."""
    _hits.append((obj, evt.GetEventType()))


def _talk_probe(obj, _evt):
    _talk_hits.append(obj)


def _focused_cinematic_window():
    top_window.reset_for_tests()
    tw = App.TopWindow_GetTopWindow()
    tw.ToggleCinematicWindow()              # focuses it + lazily wires the SDK
    return tw, tw.FindMainWindow(App.MWT_CINEMATIC)


def _press(wc, ky, label):
    im = TGInputManager(App.g_kEventManager)
    im.RegisterUnicodeKey(wc, ky, None, label)
    im.OnKeyDown(wc)


def test_f2_in_cinematic_mode_fires_the_chase_camera_event():
    del _hits[:]
    _tw, cine = _focused_cinematic_window()
    cine.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CINEMATIC_CHASE, __name__ + "._probe")
    _press(App.WC_F2, App.KY_F2, "F2")
    assert _hits == [(cine, App.ET_INPUT_CINEMATIC_CHASE)]


def test_f6_in_cinematic_mode_fires_the_free_orbit_event():
    del _hits[:]
    _tw, cine = _focused_cinematic_window()
    cine.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CINEMATIC_FREEORBIT, __name__ + "._probe")
    _press(App.WC_F6, App.KY_F6, "F6")
    assert _hits == [(cine, App.ET_INPUT_CINEMATIC_FREEORBIT)]


def test_the_same_key_switches_behaviour_across_a_focus_change():
    """THE regression guard for the bridge crew menus. Drives F2 BOTH ways in
    one test so the negative half cannot pass merely because routing is broken
    everywhere: focused -> camera event; unfocused -> nothing, and F2 is left
    to the global binding (ET_INPUT_TALK_TO_TACTICAL)."""
    del _hits[:]
    tw, cine = _focused_cinematic_window()
    cine.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CINEMATIC_CHASE, __name__ + "._probe")

    _press(App.WC_F2, App.KY_F2, "F2")
    assert _hits == [(cine, App.ET_INPUT_CINEMATIC_CHASE)]

    tw.ToggleCinematicWindow()              # back out — handlers stay wired
    assert tw.is_cinematic_active() is False
    del _hits[:]
    _press(App.WC_F2, App.KY_F2, "F2")
    assert _hits == []


def test_only_the_six_mapped_keys_produce_a_camera_event():
    """HandleKeyboard must not invent an event for an unmapped key. Presses a
    mapped key too, so the negative half cannot pass on broken routing."""
    del _hits[:]
    _tw, cine = _focused_cinematic_window()
    for et in (App.ET_INPUT_CINEMATIC_CHASE, App.ET_INPUT_CINEMATIC_FREEORBIT,
               App.ET_INPUT_CINEMATIC_TARGET, App.ET_INPUT_CINEMATIC_TORPCAM,
               App.ET_INPUT_CINEMATIC_WIDETARGET,
               App.ET_INPUT_CINEMATIC_DROPANDWATCH):
        cine.AddPythonFuncHandlerForInstance(et, __name__ + "._probe")
    _press(App.WC_S, App.KY_S, "s")
    assert _hits == []
    _press(App.WC_F1, App.KY_F1, "F1")
    assert _hits == [(cine, App.ET_INPUT_CINEMATIC_DROPANDWATCH)]


def test_a_non_interactive_cinematic_window_ignores_the_camera_keys():
    """StartCinematicMode(bInteractive=0) is how scripted cinematics lock the
    player out of the camera, and it is only real now that
    CinematicWindow_Cast/SetInteractive are.

    TWO layers agree here, and it matters which one acts first: the raw
    keystroke never even reaches this window, because
    _raw_keyboard_destination declines a non-interactive window (see
    test_a_non_interactive_focused_window_never_takes_the_raw_stream — the key
    must keep flowing to the root window during every warp). HandleKeyboard's
    own gate (:99) is the second line of defence. Interactivity is flipped back
    on inside the test so the suppression is shown to be the flag and not
    simply a dead route."""
    del _hits[:]
    _tw, cine = _focused_cinematic_window()
    cine.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CINEMATIC_CHASE, __name__ + "._probe")

    App.CinematicWindow_Cast(cine).SetInteractive(0)
    _press(App.WC_F2, App.KY_F2, "F2")
    assert _hits == []

    App.CinematicWindow_Cast(cine).SetInteractive(1)
    _press(App.WC_F2, App.KY_F2, "F2")
    assert _hits == [(cine, App.ET_INPUT_CINEMATIC_CHASE)]


# ── The double-fire, closed ─────────────────────────────────────────────────
# In BC, g_kKeyboardBinding.LaunchEvent is called ONLY from inside
# HandleKeyboard, gated on pEvent.EventHandled() == 0 (:117-119) — so a key the
# cinematic table consumed never reaches the global binding. Our shim did the
# binding translation on the independent ET_KEYBOARD_EVENT broadcast in
# TGInputManager._emit, which ran BEFORE and REGARDLESS of the raw dispatch,
# and DefaultKeyboardBinding.py:121-126 binds WC_F1..F6 -> ET_INPUT_TALK_TO_*
# under the same KS_KEYDOWN. So every one of F1-F6 in cinematic mode fired the
# camera event AND opened a crew menu — reported live as "f9 followed by f3
# just seems to be activating the xo menu now".
#
# These two tests were an xfail(strict) pinning that defect. _emit now
# dispatches the raw window event first and skips the broadcast when
# TGEvent.EventHandled() comes back set, so they are real assertions.

def _arm_binding(wc, event_type):
    """Bind `wc` KEYDOWN -> event_type with a probe on the default
    destination, mirroring DefaultKeyboardBinding + the TCW wiring. Returns a
    teardown callable."""
    from engine.appc.events import ET_KEYBOARD_EVENT, TGEventHandlerObject
    from engine.appc.input import KS_KEYDOWN, register_input_handlers

    # The App-module-load registration can have been cleared by an earlier
    # test's world reset; re-arm it only if it is actually missing, because
    # registering twice would double-deliver every bound key.
    live = App.g_kEventManager._broadcast_handlers.get(ET_KEYBOARD_EVENT, [])
    if not any(n.endswith("_OnKeyboardEvent_Dispatch") for _d, n in live):
        register_input_handlers(App.g_kEventManager)

    kb = App.g_kKeyboardBinding
    previous_destination = kb._default_destination
    tcw = TGEventHandlerObject()
    tcw.AddPythonFuncHandlerForInstance(event_type, __name__ + "._talk_probe")
    kb.SetDefaultDestination(tcw)
    kb.BindKey(wc, KS_KEYDOWN, event_type)

    def _undo():
        kb.SetDefaultDestination(previous_destination)
        kb._bindings.pop((wc, KS_KEYDOWN), None)
    return tcw, _undo


def test_cinematic_camera_key_does_not_also_open_the_crew_menu():
    del _hits[:]
    del _talk_hits[:]
    _tcw, undo = _arm_binding(App.WC_F2, App.ET_INPUT_TALK_TO_TACTICAL)
    try:
        _tw, cine = _focused_cinematic_window()
        cine.AddPythonFuncHandlerForInstance(
            App.ET_INPUT_CINEMATIC_CHASE, __name__ + "._probe")
        _press(App.WC_F2, App.KY_F2, "F2")
        # BOTH halves: the camera event must still fire, so a routing
        # regression (which would also empty _talk_hits) cannot pass this.
        assert _hits == [(cine, App.ET_INPUT_CINEMATIC_CHASE)]
        assert _talk_hits == []
    finally:
        undo()


def test_f3_in_cinematic_mode_is_the_target_camera_and_not_the_xo_menu():
    """The exact live report: F9 (cinematic mode) then F3. F3 is
    ET_INPUT_CINEMATIC_TARGET in the window's table
    (CinematicInterfaceHandlers.py:156) and ET_INPUT_TALK_TO_XO in the global
    binding (DefaultKeyboardBinding.py:123)."""
    del _hits[:]
    del _talk_hits[:]
    _tcw, undo = _arm_binding(App.WC_F3, App.ET_INPUT_TALK_TO_XO)
    try:
        _tw, cine = _focused_cinematic_window()
        cine.AddPythonFuncHandlerForInstance(
            App.ET_INPUT_CINEMATIC_TARGET, __name__ + "._probe")
        _press(App.WC_F3, App.KY_F3, "F3")
        assert _hits == [(cine, App.ET_INPUT_CINEMATIC_TARGET)]
        assert _talk_hits == []
    finally:
        undo()


def test_f3_outside_cinematic_mode_still_opens_the_xo_menu():
    """THE regression guard for the live-verified bridge crew menus. The
    suppression must bite only when a window genuinely consumed the key; with
    no cinematic window focused nothing does, so F3 must reach
    ET_INPUT_TALK_TO_XO exactly as it did before the reorder."""
    del _hits[:]
    del _talk_hits[:]
    tcw, undo = _arm_binding(App.WC_F3, App.ET_INPUT_TALK_TO_XO)
    try:
        top_window.reset_for_tests()            # nothing focused
        assert App.TopWindow_GetTopWindow().GetFocus() is None
        _press(App.WC_F3, App.KY_F3, "F3")
        assert _talk_hits == [tcw]
    finally:
        undo()


def test_f3_reverts_to_the_xo_menu_when_cinematic_mode_is_left():
    """Drives the SAME key both ways in one test, so neither half can pass on
    routing that is simply broken everywhere."""
    del _hits[:]
    del _talk_hits[:]
    tcw, undo = _arm_binding(App.WC_F3, App.ET_INPUT_TALK_TO_XO)
    try:
        tw, cine = _focused_cinematic_window()
        cine.AddPythonFuncHandlerForInstance(
            App.ET_INPUT_CINEMATIC_TARGET, __name__ + "._probe")
        _press(App.WC_F3, App.KY_F3, "F3")
        assert _hits == [(cine, App.ET_INPUT_CINEMATIC_TARGET)]
        assert _talk_hits == []

        tw.ToggleCinematicWindow()              # F9 again — leave the mode
        assert tw.is_cinematic_active() is False
        del _hits[:]
        _press(App.WC_F3, App.KY_F3, "F3")
        assert _hits == []
        assert _talk_hits == [tcw]
    finally:
        undo()


def test_a_key_the_cinematic_table_misses_still_gets_its_binding():
    """The cinematic window's handler runs for EVERY key while it is focused,
    but only the six table entries call SetHandled (InterfaceHandlers.py:58).
    A key it looked at and passed on must still be translated — otherwise
    focusing any window with a raw handler would deafen the whole binding
    table."""
    del _hits[:]
    del _talk_hits[:]
    tcw, undo = _arm_binding(App.WC_S, App.ET_INPUT_TALK_TO_XO)
    try:
        _tw, cine = _focused_cinematic_window()
        cine.AddPythonFuncHandlerForInstance(
            App.ET_INPUT_CINEMATIC_TARGET, __name__ + "._probe")
        _press(App.WC_S, App.KY_S, "s")
        assert _hits == []                      # not in g_dKeyToEventMapping
        assert _talk_hits == [tcw]
    finally:
        undo()
