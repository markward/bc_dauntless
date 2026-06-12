"""CrewMenuPanel snapshot/diff/dispatch. Pattern: engine/appc/sdk_mirror_panel.py."""
import json

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.characters import STButton, STTopLevelMenu
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
