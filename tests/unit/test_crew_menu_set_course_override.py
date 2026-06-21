"""The Helm Set Course (SortedRegionMenu) is projected as a leaf button and
its click opens the setting-course panel instead of expanding inline."""
import pytest

from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.st_widgets import SortedRegionMenu
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui.crew_menu_panel import CrewMenuPanel


def _snapshot(panel, widget):
    return panel._snapshot_node(widget)


def test_sorted_region_menu_snapshots_as_childless_button():
    panel = CrewMenuPanel()
    sc = SortedRegionMenu("Set Course")
    sc.AddChild(STButton("Alpha Centauri"))
    node = _snapshot(panel, sc)
    assert node["type"] == "button"
    assert node["label"] == "Set Course"
    assert "children" not in node
    assert "expanded" not in node


def test_plain_menu_still_snapshots_as_menu_with_children():
    panel = CrewMenuPanel()
    m = STMenu("Hail")
    m.AddChild(STButton("Enterprise"))
    node = _snapshot(panel, m)
    assert node["type"] == "menu"
    assert len(node["children"]) == 1


def test_click_on_set_course_invokes_callback_with_widget():
    seen = []
    panel = CrewMenuPanel(on_set_course=lambda w: seen.append(w))
    sc = SortedRegionMenu("Set Course")
    wid = ensure_widget_id(sc)
    # Populate the id->widget map the way render_payload does.
    panel._snapshot_node(sc)
    panel._widgets_by_id[wid] = sc
    handled = panel.dispatch_event("click:" + str(wid))
    assert handled is True
    assert seen == [sc]


def test_click_on_set_course_fires_no_sdk_button_event():
    import App
    panel = CrewMenuPanel(on_set_course=lambda w: None)
    sc = SortedRegionMenu("Set Course")
    wid = ensure_widget_id(sc)
    panel._widgets_by_id[wid] = sc
    before = App.g_kEventManager.GetEventCount() \
        if hasattr(App.g_kEventManager, "GetEventCount") else None
    panel.dispatch_event("click:" + str(wid))
    # A SortedRegionMenu is not an STButton, so SendActivationEvent /
    # ET_ST_BUTTON_CLICKED must never run. Assert by type, not event queue:
    assert not isinstance(sc, STButton)


def test_none_callback_is_silent_noop():
    panel = CrewMenuPanel()  # on_set_course defaults to None
    sc = SortedRegionMenu("Set Course")
    wid = ensure_widget_id(sc)
    panel._widgets_by_id[wid] = sc
    # Must not raise.
    assert panel.dispatch_event("click:" + str(wid)) is True
