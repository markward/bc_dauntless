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
import pytest

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


# ── KNOWN DEFECT, pinned ────────────────────────────────────────────────────
# In BC, g_kKeyboardBinding.LaunchEvent is called ONLY from inside
# HandleKeyboard, gated on pEvent.EventHandled() == 0 (:117-119) — so a key the
# cinematic table consumed never reaches the global binding. Our shim does the
# binding translation on the independent ET_KEYBOARD_EVENT broadcast in
# TGInputManager._emit, which runs before and regardless of the raw dispatch,
# and DefaultKeyboardBinding.py:121-126 binds WC_F1..F6 -> ET_INPUT_TALK_TO_*
# under the same KS_KEYDOWN. So F2 in cinematic mode fires the camera event AND
# still opens the Tactical crew menu.
#
# Closing it means dispatching raw BEFORE the broadcast and skipping the
# broadcast when the raw event was handled, which needs real
# TGEvent.SetHandled/EventHandled (both are _Stubs today) and reorders a
# live-verified path — out of scope here.
#
# strict=True is the point: when someone fixes this, the XPASS FAILS the suite
# and forces them to delete the marker, so the defect cannot silently outlive
# its fix.

@pytest.mark.xfail(strict=True, reason=(
    "known divergence: our ET_KEYBOARD_EVENT broadcast translates the binding "
    "unconditionally, so a cinematic camera key ALSO fires its "
    "ET_INPUT_TALK_TO_* binding. BC gates LaunchEvent on EventHandled()."))
def test_cinematic_camera_key_does_not_also_open_the_crew_menu():
    from engine.appc.events import ET_KEYBOARD_EVENT, TGEventHandlerObject
    from engine.appc.input import KS_KEYDOWN, register_input_handlers

    del _hits[:]
    del _talk_hits[:]

    # The App-module-load registration can have been cleared by an earlier
    # test's world reset; re-arm it only if it is actually missing, because
    # registering twice would double-deliver every bound key.
    live = App.g_kEventManager._broadcast_handlers.get(ET_KEYBOARD_EVENT, [])
    if not any(n.endswith("_OnKeyboardEvent_Dispatch") for _d, n in live):
        register_input_handlers(App.g_kEventManager)

    kb = App.g_kKeyboardBinding
    previous_destination = kb._default_destination
    tcw = TGEventHandlerObject()
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TALK_TO_TACTICAL, __name__ + "._talk_probe")
    kb.SetDefaultDestination(tcw)
    kb.BindKey(App.WC_F2, KS_KEYDOWN, App.ET_INPUT_TALK_TO_TACTICAL)
    try:
        _tw, cine = _focused_cinematic_window()
        cine.AddPythonFuncHandlerForInstance(
            App.ET_INPUT_CINEMATIC_CHASE, __name__ + "._probe")
        _press(App.WC_F2, App.KY_F2, "F2")
        # The camera half is asserted by
        # test_f2_in_cinematic_mode_fires_the_chase_camera_event; asserting it
        # here too would let a routing regression masquerade as this xfail.
        assert _talk_hits == []
    finally:
        kb.SetDefaultDestination(previous_destination)
        kb._bindings.pop((App.WC_F2, KS_KEYDOWN), None)
