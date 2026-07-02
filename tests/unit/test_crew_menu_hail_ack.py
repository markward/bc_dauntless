"""Clicking a bridge-menu button fires NO generic crew acknowledgement.

BC-faithful: the SDK's Bridge.BridgeMenus.ButtonClicked (the ET_ST_BUTTON_CLICKED
handler on every officer menu) only turns the officer back to face front — its
per-officer SayLine acks are commented out in stock BC (BridgeMenus.py:84).
Officers greet only when a menu is *opened* (CharacterInteraction). Buttons that
should speak do so through their own SDK handlers (Hail -> Kiska's "Hailing
frequencies open" + the mission comm; alert -> XO; Scan Area -> Miguel's
ScanComplete). A generic per-click ack used to double up with — and, being
single-channel, preempt — that real dialogue.
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


def test_hail_button_click_fires_no_ack():
    panel, wid, acks = _panel_with_button(App.ET_HAIL)
    panel.dispatch_event("click:" + str(wid))
    assert acks == []


def test_communicate_button_click_fires_no_ack():
    panel, wid, acks = _panel_with_button(App.ET_COMMUNICATE)
    panel.dispatch_event("click:" + str(wid))
    assert acks == []


def test_ordinary_command_button_click_fires_no_ack():
    # An ordinary command button (e.g. ET_ALL_STOP) also speaks nothing on
    # click — matching BC's silent ButtonClicked.
    panel, wid, acks = _panel_with_button(App.ET_ALL_STOP)
    panel.dispatch_event("click:" + str(wid))
    assert acks == []
