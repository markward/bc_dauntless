"""Clicking a Hail (or Communicate) button must NOT fire the generic crew
acknowledgement — those buttons produce their own single-channel crew dialogue
(Kiska "Hailing frequencies open" + the mission's comm), and the ack would
preempt it so the player hears only "aye sir".
"""
import App
from engine.appc.characters import STButton, STTopLevelMenu
from engine.appc.windows import TacticalControlWindow
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui.crew_menu_panel import CrewMenuPanel


def _panel_with_button(event_type):
    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    menu = STTopLevelMenu("Helm")
    evt = App.TGObjPtrEvent_Create()
    evt.SetEventType(event_type)
    btn = STButton("Target", evt)
    menu.AddChild(btn)
    tcw.AddMenuToList(menu)

    panel = CrewMenuPanel()
    wid = ensure_widget_id(btn)
    panel._snapshot_node(menu)          # populates _widgets_by_id
    acks = []
    panel._acknowledge = lambda root: acks.append(root)
    return panel, wid, acks


def test_hail_button_click_suppresses_ack():
    panel, wid, acks = _panel_with_button(App.ET_HAIL)
    panel.dispatch_event("click:" + str(wid))
    assert acks == []


def test_communicate_button_click_suppresses_ack():
    panel, wid, acks = _panel_with_button(App.ET_COMMUNICATE)
    panel.dispatch_event("click:" + str(wid))
    assert acks == []


def test_ordinary_command_button_click_still_acks():
    # A non-dialogue command button (e.g. ET_ALL_STOP) keeps the "aye sir" ack.
    panel, wid, acks = _panel_with_button(App.ET_ALL_STOP)
    panel.dispatch_event("click:" + str(wid))
    assert len(acks) == 1
