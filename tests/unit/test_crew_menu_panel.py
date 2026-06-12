"""CrewMenuPanel snapshot/diff/dispatch. Pattern: engine/appc/sdk_mirror_panel.py."""
import json

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.characters import STButton, STTopLevelMenu
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui.crew_menu_panel import CrewMenuPanel


def setup_function(_):
    TacticalControlWindow._instance = None


def _build_helm_with_button(event_type=None):
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    evt = App.TGIntEvent_Create()
    evt.SetEventType(event_type if event_type is not None else App.ET_ALL_STOP)
    evt.SetDestination(helm)
    btn = App.STButton_CreateW("All Stop", evt)
    helm.AddChild(btn)
    tcw.AddMenuToList(helm)
    return helm, btn


def test_payload_shape_and_ids():
    helm, btn = _build_helm_with_button()
    panel = CrewMenuPanel()
    payload = panel.render_payload()
    assert payload.startswith("setCrewMenus(")
    data = json.loads(payload[len("setCrewMenus("):-2])  # strip call + ");"
    assert len(data["menus"]) == 1
    root = data["menus"][0]
    assert root["label"] == "Helm"
    assert root["type"] == "menu"
    assert root["children"][0]["label"] == "All Stop"
    assert root["children"][0]["type"] == "button"
    assert isinstance(root["children"][0]["id"], int)
    assert root["children"][0]["enabled"] is True


def test_payload_dedups_until_state_changes():
    helm, btn = _build_helm_with_button()
    panel = CrewMenuPanel()
    assert panel.render_payload() is not None
    assert panel.render_payload() is None          # unchanged → no re-emit
    btn.SetDisabled()
    assert panel.render_payload() is not None      # change → re-emit


def test_invalidate_forces_reemission():
    _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    panel.invalidate()
    assert panel.render_payload() is not None


def test_panel_name():
    assert CrewMenuPanel().name == "crew-menu"


_clicks = []


def _record_all_stop(dest, event):
    _clicks.append((dest, event.GetEventType()))


def test_click_fires_buttons_stored_event_into_sdk_handler():
    _clicks.clear()
    helm, btn = _build_helm_with_button()
    helm.AddPythonFuncHandlerForInstance(
        App.ET_ALL_STOP, __name__ + "._record_all_stop")
    panel = CrewMenuPanel()
    panel.render_payload()                      # builds the id map
    wid = ensure_widget_id(btn)
    assert panel.dispatch_event(f"click:{wid}") is True
    assert _clicks == [(helm, App.ET_ALL_STOP)]


def test_click_also_fires_st_button_clicked_at_root_menu():
    _clicks.clear()
    helm, btn = _build_helm_with_button()
    helm.AddPythonFuncHandlerForInstance(
        App.ET_ST_BUTTON_CLICKED, __name__ + "._record_all_stop")
    panel = CrewMenuPanel()
    panel.render_payload()
    panel.dispatch_event(f"click:{ensure_widget_id(btn)}")
    assert (helm, App.ET_ST_BUTTON_CLICKED) in _clicks


def test_stale_click_id_is_dropped_not_raised():
    _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    assert panel.dispatch_event("click:999999") is True   # handled: dropped


def test_click_on_disabled_button_is_ignored():
    _clicks.clear()
    helm, btn = _build_helm_with_button()
    helm.AddPythonFuncHandlerForInstance(
        App.ET_ALL_STOP, __name__ + "._record_all_stop")
    btn.SetDisabled()
    panel = CrewMenuPanel()
    panel.render_payload()
    panel.dispatch_event(f"click:{ensure_widget_id(btn)}")
    assert _clicks == []
