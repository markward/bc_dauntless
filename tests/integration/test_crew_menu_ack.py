"""End-to-end: an F-key talk-to event opens a crew menu and the officer
acknowledges (subtitle reaches the snapshot)."""
import App
from engine.appc import top_window, crew_speech
from engine.appc.characters import STTopLevelMenu
from engine.appc.windows import TacticalControlWindow
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.ui import crew_menu_hotkeys


def _subtitle():
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def test_fkey_talk_to_opens_menu_and_acknowledges():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    tcw = TacticalControlWindow.GetInstance()
    # Tactical menu present under its label (headless TGL -> key fallback).
    tcw.AddMenuToList(STTopLevelMenu("Tactical"))

    panel = CrewMenuPanel()
    crew_menu_hotkeys.wire(tcw, panel)

    # Simulate the TALK_TO_TACTICAL event the host feeds from F2.
    evt = App.TGIntEvent_Create() if hasattr(App, "TGIntEvent_Create") else App.TGEvent_Create()
    evt.SetEventType(App.ET_INPUT_TALK_TO_TACTICAL)
    crew_menu_hotkeys._on_talk_to(tcw, evt)

    assert panel.has_open_menu() is True
    snap = _subtitle()._snapshot(now=0.0)
    assert snap is not None
    assert snap["speaker"] == "Tactical"


def test_owned_menu_click_goes_through_menu_up():
    """The real in-game chain: the SDK attaches a station menu to its officer
    (`pTactical.SetMenu(tcw.FindMenu("Tactical"))`), so a title click DELEGATES to
    BC's canonical primitive — CharacterClass.MenuUp() raises the menu (driving the
    wired panel's view), flags the officer as menu-up, and the click path acks."""
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    tcw = TacticalControlWindow.GetInstance()
    menu = STTopLevelMenu("Tactical")
    tcw.AddMenuToList(menu)

    panel = CrewMenuPanel()
    crew_menu_hotkeys.wire(tcw, panel)          # MenuUp reaches the view via this
    officer = crew_menu_hotkeys.resolve_character("Tactical")
    officer.SetMenu(menu)                       # SDK AttachMenuToTactical
    try:
        panel.toggle_menu(menu)                     # -> officer.MenuUp()

        assert panel.has_open_menu() is True        # the PRIMITIVE opened the view
        assert officer.IsMenuUp() == 1
        assert _subtitle()._snapshot(now=0.0)["speaker"] == "Tactical"   # ack (click path)

        panel.toggle_menu(menu)                     # -> officer.MenuDown()
        assert panel.has_open_menu() is False
        assert officer.IsMenuUp() == 0
    finally:
        officer.SetMenu(None)                       # don't leak the attachment


def test_reset_sdk_globals_clean_after_ack():
    from engine.host_loop import reset_sdk_globals
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    tcw = TacticalControlWindow.GetInstance()
    tcw.AddMenuToList(STTopLevelMenu("Tactical"))
    panel = CrewMenuPanel()
    panel.toggle_menu(tcw.FindMenu("Tactical"))   # acks
    reset_sdk_globals()
    assert crew_speech.bus().speak("Eng", "x", None, App.CSP_SPONTANEOUS) > 0.0
