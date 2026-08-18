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


def _probe(obj, evt):
    """Records the delivery and STOPS the chain (no CallNextHandler), so the
    real CameraChase/CameraFreeOrbit handler underneath never runs — those
    need a live player camera, which is not what this test is about."""
    _hits.append((obj, evt.GetEventType()))


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
    """HandleKeyboard's first gate (:99) — StartCinematicMode(bInteractive=0)
    is how scripted cinematics lock the player out of the camera. That gate is
    only reachable now that CinematicWindow_Cast/SetInteractive are real; it is
    flipped back on inside the test so the suppression is shown to be the gate
    and not simply a dead route."""
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
