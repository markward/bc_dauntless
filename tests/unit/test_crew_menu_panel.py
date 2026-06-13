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


def test_quiescent_panel_emits_nothing_on_first_tick():
    panel = CrewMenuPanel()        # no menus registered
    assert panel.render_payload() is None
    panel.invalidate()             # CEF reload: empty state must fire once
    assert panel.render_payload() == 'setCrewMenus({"menus": []});'


def test_nested_submenu_snapshot_depth():
    from engine.appc.characters import STMenu
    helm, btn = _build_helm_with_button()
    warp = STMenu("Warp")
    warp.AddChild(App.STButton_CreateW("Engage", None))
    helm.AddChild(warp)
    panel = CrewMenuPanel()
    payload = panel.render_payload()
    import json as _json
    data = _json.loads(payload[len("setCrewMenus("):-2])
    nodes = data["menus"][0]["children"]
    warp_node = [n for n in nodes if n["label"] == "Warp"][0]
    assert warp_node["type"] == "menu"
    assert warp_node["children"][0]["label"] == "Engage"
    assert warp_node["children"][0]["type"] == "button"


def test_menu_click_is_clean_noop():
    _clicks.clear()
    helm, btn = _build_helm_with_button()
    helm.AddPythonFuncHandlerForInstance(
        App.ET_ALL_STOP, __name__ + "._record_all_stop")
    helm.AddPythonFuncHandlerForInstance(
        App.ET_ST_BUTTON_CLICKED, __name__ + "._record_all_stop")
    panel = CrewMenuPanel()
    panel.render_payload()
    assert panel.dispatch_event(f"click:{ensure_widget_id(helm)}") is True
    assert _clicks == []           # no SDK event fired for a menu node


def test_toggle_menu_open_switch_close():
    helm, _ = _build_helm_with_button()
    from engine.appc.characters import STTopLevelMenu
    tactical = STTopLevelMenu("Tactical")
    TacticalControlWindow.GetInstance().AddMenuToList(tactical)
    panel = CrewMenuPanel()
    panel.render_payload()

    panel.toggle_menu(helm)
    assert panel.has_open_menu()
    payload = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    opens = {m["label"]: m["open"] for m in payload["menus"]}
    assert opens == {"Helm": True, "Tactical": False}

    panel.toggle_menu(tactical)            # switch: single-open invariant
    payload = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    opens = {m["label"]: m["open"] for m in payload["menus"]}
    assert opens == {"Helm": False, "Tactical": True}

    panel.toggle_menu(tactical)            # same again: close
    assert not panel.has_open_menu()


def test_close_open_menu_returns_whether_closed():
    helm, _ = _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    assert panel.close_open_menu() is False
    panel.toggle_menu(helm)
    assert panel.close_open_menu() is True
    assert panel.close_open_menu() is False


def test_dispatch_toggle_action():
    helm, _ = _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    wid = ensure_widget_id(helm)
    assert panel.dispatch_event(f"toggle:{wid}") is True
    assert panel.has_open_menu()
    assert panel.dispatch_event(f"toggle:{wid}") is True
    assert not panel.has_open_menu()
    assert panel.dispatch_event("toggle:999999") is True   # stale: dropped
    assert panel.dispatch_event("toggle:zap") is True      # malformed: dropped


def test_open_state_changes_force_reemit():
    helm, _ = _build_helm_with_button()
    panel = CrewMenuPanel()
    assert panel.render_payload() is not None
    assert panel.render_payload() is None
    panel.toggle_menu(helm)
    assert panel.render_payload() is not None   # open flag changed payload


def test_invalidate_clears_open_state():
    helm, _ = _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    panel.toggle_menu(helm)
    panel.invalidate()                      # CEF reload / mission swap
    assert not panel.has_open_menu()


def test_toggle_ignores_disabled_menu_and_buttons():
    helm, btn = _build_helm_with_button()
    panel = CrewMenuPanel()
    panel.render_payload()
    helm.SetDisabled()
    panel.toggle_menu(helm)
    assert not panel.has_open_menu()        # disabled menus stay closed
    helm.SetEnabled()
    panel.toggle_menu(btn)
    assert not panel.has_open_menu()        # buttons are not togglable


def _build_helm_with_submenu():
    """Helm top-level menu with a 'Set Course' submenu that has one child."""
    from engine.appc.characters import STTopLevelMenu, STMenu, STButton
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    setcourse = STMenu("Set Course")
    setcourse.AddChild(STButton("Sol System"))
    helm.AddChild(setcourse)
    tcw.AddMenuToList(helm)
    return helm, setcourse


def test_expand_toggles_node_and_flag():
    helm, setcourse = _build_helm_with_submenu()
    panel = CrewMenuPanel()
    panel.toggle_menu(helm)               # open Helm
    panel.render_payload()                # build _widgets_by_id
    sc_id = ensure_widget_id(setcourse)

    assert panel.dispatch_event(f"expand:{sc_id}") is True
    data = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    setcourse_node = data["menus"][0]["children"][0]
    assert setcourse_node["expanded"] is True
    assert setcourse_node["children"][0]["label"] == "Sol System"

    assert panel.dispatch_event(f"expand:{sc_id}") is True   # collapse
    data = json.loads(panel.render_payload()[len("setCrewMenus("):-2])
    assert data["menus"][0]["children"][0]["expanded"] is False


def test_expand_stale_and_malformed_dropped():
    helm, _ = _build_helm_with_submenu()
    panel = CrewMenuPanel()
    panel.toggle_menu(helm)
    panel.render_payload()
    assert panel.dispatch_event("expand:999999") is True   # stale
    assert panel.dispatch_event("expand:nope") is True      # malformed


def test_closing_menu_clears_expanded():
    helm, setcourse = _build_helm_with_submenu()
    panel = CrewMenuPanel()
    panel.toggle_menu(helm)
    panel.render_payload()
    panel.dispatch_event(f"expand:{ensure_widget_id(setcourse)}")
    assert panel._expanded_ids
    panel.toggle_menu(helm)               # close → expansion resets
    assert not panel._expanded_ids


def test_invalidate_clears_expanded():
    helm, setcourse = _build_helm_with_submenu()
    panel = CrewMenuPanel()
    panel.toggle_menu(helm)
    panel.render_payload()
    panel.dispatch_event(f"expand:{ensure_widget_id(setcourse)}")
    panel.invalidate()
    assert not panel._expanded_ids
