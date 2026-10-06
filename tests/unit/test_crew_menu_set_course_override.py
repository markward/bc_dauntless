"""Helm -> Set Course is BC's drop-down: the root (a SortedRegionMenu with no
region module) expands to its systems, a system to its regions, and a region
row sets the course. A permanent "Stellar Cartography" row at the foot of the
root opens the star map. The Helm "Warp" button keeps its own path."""
import pytest

from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui import st_widgets
from engine.appc.tg_ui.st_widgets import SortedRegionMenu, STWarpButton
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui.crew_menu_panel import CARTOGRAPHY_LABEL, CrewMenuPanel


@pytest.fixture(autouse=True)
def _clean_warp_button_registry():
    st_widgets._reset_module_state()
    yield
    st_widgets._reset_module_state()


def _course_tree():
    """Set Course -> Vesuvi (4, 6) + Riha (single region), as
    Systems/Utils.CreateSystemMenuInternal builds it."""
    root = SortedRegionMenu("Set Course")
    vesuvi = SortedRegionMenu("Vesuvi", "Systems.Vesuvi.Vesuvi6")
    v4 = SortedRegionMenu("Vesuvi 4", "Systems.Vesuvi.Vesuvi4")
    v6 = SortedRegionMenu("Vesuvi 6", "Systems.Vesuvi.Vesuvi6")
    vesuvi.AddChild(v4, 0, 0, 0)
    vesuvi.AddChild(v6, 0, 0, 0)
    riha = SortedRegionMenu("Riha", "Systems.Riha.Riha1")
    root.AddChild(vesuvi, 0, 0, 0)
    root.AddChild(riha, 0, 0, 0)
    return root, vesuvi, v4, v6, riha


def _registered(panel, root):
    panel._snapshot_node(root)        # populates _widgets_by_id
    return panel


def _labels(node):
    return [c["label"] for c in node["children"]]


def test_set_course_snapshots_as_a_menu_of_systems_then_cartography():
    root, *_ = _course_tree()
    node = CrewMenuPanel()._snapshot_node(root)
    assert node["type"] == "menu"
    assert node["openable"] is True
    assert _labels(node) == ["Vesuvi", "Riha", CARTOGRAPHY_LABEL]


def test_set_course_with_no_systems_collapses_to_one_button():
    """Stellar Cartography would be the only row, so the drop-down collapses
    into a single "Set Course" button — the shape it had before."""
    node = CrewMenuPanel()._snapshot_node(SortedRegionMenu("Set Course"))
    assert node["type"] == "button"
    assert node["label"] == "Set Course"
    assert "children" not in node


def test_the_collapsed_button_opens_the_map(monkeypatch):
    import App
    root = SortedRegionMenu("Set Course")
    opened, courses = [], []
    panel = _registered(CrewMenuPanel(on_set_course=opened.append,
                                      on_course_set=courses.append), root)
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)
    assert panel.dispatch_event("click:%d" % ensure_widget_id(root)) is True
    assert opened == [root]
    assert courses == [] and events == []


def test_the_collapsed_button_follows_set_course_being_disabled():
    root = SortedRegionMenu("Set Course")
    root.SetDisabled()
    opened = []
    panel = _registered(CrewMenuPanel(on_set_course=opened.append), root)
    panel.dispatch_event("click:%d" % ensure_widget_id(root))
    assert opened == []


def test_a_system_with_regions_expands_and_its_regions_are_course_rows():
    root, *_ = _course_tree()
    vesuvi = CrewMenuPanel()._snapshot_node(root)["children"][0]
    assert vesuvi["type"] == "menu"
    assert _labels(vesuvi) == ["Vesuvi 4", "Vesuvi 6"]
    assert {c["type"] for c in vesuvi["children"]} == {"button"}


def test_a_single_region_system_is_itself_a_course_row():
    root, *_ = _course_tree()
    riha = CrewMenuPanel()._snapshot_node(root)["children"][1]
    assert riha["type"] == "button"
    assert "children" not in riha


def test_a_not_openable_system_acts_on_its_default_region():
    """Systems/Utils.py:93 makes a system SetNotOpenable in multiplayer;
    such a system is a course row for its own module, not a submenu."""
    root, vesuvi, *_ = _course_tree()
    vesuvi.SetNotOpenable()
    node = CrewMenuPanel()._snapshot_node(vesuvi)
    assert node["type"] == "button"


def test_the_row_on_the_warp_button_is_ticked():
    root, *_ = _course_tree()
    btn = STWarpButton("Warp")
    st_widgets.SortedRegionMenu_SetWarpButton(btn)
    btn.SetDestination("Systems.Vesuvi.Vesuvi4")
    node = CrewMenuPanel()._snapshot_node(root)
    vesuvi, riha = node["children"][0], node["children"][1]
    assert [c["chosen"] for c in vesuvi["children"]] == [True, False]
    assert riha["chosen"] is False


def test_clicking_a_region_sets_the_course_and_fires_no_button_event(monkeypatch):
    import App
    root, _vesuvi, v4, _v6, riha = _course_tree()
    seen = []
    panel = _registered(CrewMenuPanel(on_course_set=seen.append), root)
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", events.append)

    assert panel.dispatch_event("click:%d" % ensure_widget_id(v4)) is True
    assert panel.dispatch_event("click:%d" % ensure_widget_id(riha)) is True

    assert seen == ["Systems.Vesuvi.Vesuvi4", "Systems.Riha.Riha1"]
    # record_course_selection (the injected callback) owns the crew ack; the
    # panel must not also fire ET_ST_BUTTON_CLICKED.
    assert events == []


def test_clicking_a_system_with_regions_does_not_set_a_course():
    root, vesuvi, *_ = _course_tree()
    seen = []
    panel = _registered(CrewMenuPanel(on_course_set=seen.append), root)
    panel.dispatch_event("expand:%d" % ensure_widget_id(vesuvi))
    assert seen == []
    assert ensure_widget_id(vesuvi) in panel._expanded_ids


def test_stellar_cartography_opens_the_map_on_the_set_course_menu():
    root, *_ = _course_tree()
    opened = []
    panel = _registered(CrewMenuPanel(on_set_course=opened.append), root)
    cart_id = panel._snapshot_node(root)["children"][-1]["id"]
    assert panel.dispatch_event("click:" + cart_id) is True
    assert opened == [root]


def test_stellar_cartography_follows_set_course_being_disabled():
    root, *_ = _course_tree()
    root.SetDisabled()
    opened = []
    panel = _registered(CrewMenuPanel(on_set_course=opened.append), root)
    cart = panel._snapshot_node(root)["children"][-1]
    assert cart["enabled"] is False
    panel.dispatch_event("click:" + cart["id"])
    assert opened == []


def test_stale_or_malformed_cartography_clicks_are_dropped():
    panel = CrewMenuPanel(on_set_course=lambda w: pytest.fail("opened"))
    assert panel.dispatch_event("click:cartography:999999") is True
    assert panel.dispatch_event("click:cartography:nope") is True


def test_none_callbacks_are_silent_noops():
    root, _vesuvi, v4, *_ = _course_tree()
    panel = _registered(CrewMenuPanel(), root)
    cart_id = panel._snapshot_node(root)["children"][-1]["id"]
    assert panel.dispatch_event("click:%d" % ensure_widget_id(v4)) is True
    assert panel.dispatch_event("click:" + cart_id) is True


def test_plain_menu_still_snapshots_as_menu_with_children():
    panel = CrewMenuPanel()
    m = STMenu("Hail")
    m.AddChild(STButton("Enterprise"))
    node = panel._snapshot_node(m)
    assert node["type"] == "menu"
    assert len(node["children"]) == 1


def test_click_on_warp_button_engages_warp_with_widget(monkeypatch):
    import App
    seen = []
    panel = CrewMenuPanel(on_warp_engage=lambda w: seen.append(w))
    btn = STWarpButton("Warp")
    # A course MUST be set: STWarpButton.IsEnabled() is false without a
    # destination (BC's "enable warp button if it has a destination"), and
    # dispatch_event refuses disabled widgets — so a course-less button here
    # would test the refusal path, not the warp path.
    btn.SetDestination("Systems.Vesuvi.Vesuvi4")
    wid = ensure_widget_id(btn)
    panel._widgets_by_id[wid] = btn
    # The warp button must NOT take the generic STButton path (no SDK event).
    events = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                        lambda e: events.append(e))
    handled = panel.dispatch_event("click:" + str(wid))
    assert handled is True
    assert seen == [btn]           # engaged the warp spine directly
    assert events == []            # no ET_ST_BUTTON_CLICKED / warp event fired


def test_warp_button_none_callback_is_silent_noop():
    panel = CrewMenuPanel()  # on_warp_engage defaults to None
    btn = STWarpButton("Warp")
    wid = ensure_widget_id(btn)
    panel._widgets_by_id[wid] = btn
    assert panel.dispatch_event("click:" + str(wid)) is True


def test_a_course_less_warp_button_does_not_engage():
    """The user-facing half of the lockout fix.

    Clicking Warp with no course greyed the Helm menu (engage_warp does that
    before execute_warp) while the warp itself no-opped for want of a
    destination — and the re-enable lives inside the warp sequence, so the
    menu never came back. BC kept the button disabled until a course was set;
    dispatch_event already refuses disabled widgets, so the click must never
    reach the callback at all.
    """
    seen = []
    panel = CrewMenuPanel(on_warp_engage=lambda w: seen.append(w))
    btn = STWarpButton("Warp")                 # no destination
    wid = ensure_widget_id(btn)
    panel._widgets_by_id[wid] = btn

    assert not btn.IsEnabled()
    handled = panel.dispatch_event("click:" + str(wid))

    assert handled is True                     # consumed, not passed onward
    assert seen == [], "a course-less Warp click must not engage the spine"
