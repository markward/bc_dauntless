"""Crew menu rendering is SUPPRESSED (not dropped) during cinematic mode.

Entering cinematic mode (F9) already drops any open crew menu
(_drop_open_crew_menu in _TopWindow.ToggleCinematicWindow), and F1-F5 are
vetoed inside it. The residual leak is a MISSION SCRIPT raising a menu while
cinematic mode is active (a scripted AT_MENU_UP -> CharacterClass.MenuUp ->
panel.show_menu): the menu must not render, but the script still owns it —
its view state must survive so it reappears when cinematic mode exits.
"""
import json

import App
from engine.appc import top_window
from engine.appc.characters import STTopLevelMenu
from engine.appc.windows import TacticalControlWindow
from engine.ui.crew_menu_panel import CrewMenuPanel


def setup_function(_):
    TacticalControlWindow._instance = None
    top_window.reset_for_tests()


def _build_helm():
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    helm.AddChild(App.STButton_CreateW("All Stop", None))
    tcw.AddMenuToList(helm)
    return helm


def _payload(panel):
    raw = panel.render_payload()
    assert raw is not None
    return json.loads(raw[len("setCrewMenus("):-2])


def _opens(data):
    return {m["label"]: m["open"] for m in data["menus"]}


def test_menu_raised_during_cinematic_mode_does_not_render():
    helm = _build_helm()
    panel = CrewMenuPanel()
    tw = App.TopWindow_GetTopWindow()
    tw.ToggleCinematicWindow()                  # enter cinematic mode
    assert tw.is_cinematic_active() is True

    panel.show_menu(helm)                       # scripted AT_MENU_UP path
    assert _opens(_payload(panel)) == {"Helm": False}


def test_suppression_keeps_view_state_intact():
    # SUPPRESS RENDERING ONLY: the script still owns the menu. The open-menu
    # bookkeeping (has_open_menu / get_open_menu, which backs BC's
    # STTopLevelMenu_GetOpenMenu) must be untouched by the render gate.
    helm = _build_helm()
    panel = CrewMenuPanel()
    App.TopWindow_GetTopWindow().ToggleCinematicWindow()

    panel.show_menu(helm)
    _payload(panel)                             # render while suppressed
    assert panel.has_open_menu() is True
    assert panel.get_open_menu() is helm


def test_menu_reappears_when_cinematic_mode_exits():
    # The failure mode a naive "set visible=False" fix would introduce: a
    # menu a script raised DURING cinematic mode must become visible again
    # after leaving it.
    helm = _build_helm()
    panel = CrewMenuPanel()
    tw = App.TopWindow_GetTopWindow()
    tw.ToggleCinematicWindow()                  # enter

    panel.show_menu(helm)
    assert _opens(_payload(panel)) == {"Helm": False}

    tw.ToggleCinematicWindow()                  # exit
    assert tw.is_cinematic_active() is False
    # The per-tick pump re-renders: the payload changes (diff gate re-emits)
    # and the menu is open again.
    assert _opens(_payload(panel)) == {"Helm": True}


def test_entering_cinematic_mode_hides_an_already_rendered_menu():
    # A menu rendered open before F9 must re-emit as closed on the next pump
    # after entry (this panel is not wired into crew_menu_hotkeys, so the
    # entry-time _drop_open_crew_menu cannot reach it — the render gate alone
    # must hide it).
    helm = _build_helm()
    panel = CrewMenuPanel()
    panel.show_menu(helm)
    assert _opens(_payload(panel)) == {"Helm": True}

    App.TopWindow_GetTopWindow().ToggleCinematicWindow()
    assert _opens(_payload(panel)) == {"Helm": False}


def test_outside_cinematic_mode_rendering_is_unchanged():
    helm = _build_helm()
    panel = CrewMenuPanel()
    panel.show_menu(helm)
    assert _opens(_payload(panel)) == {"Helm": True}
