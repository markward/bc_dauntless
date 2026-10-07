"""Helm -> Set Course as a drop-down, against real SDK missions, headless.

The unit tests (tests/unit/test_crew_menu_set_course_override.py) pin the
projection on hand-built menus. These load the missions that offer the
largest Set Course lists and snapshot the LIVE menu the SDK built through
Systems/Utils.CreateSystemMenuInternal, so the drop-down is checked against
what the campaign actually produces — and a region row is clicked through
to the warp button.
"""
import pytest

import App
from engine.appc import warp
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui.crew_menu_panel import CARTOGRAPHY_LABEL, CrewMenuPanel
from tests.helpers import headless_mission as hm


def _set_course_node(panel):
    menu = warp.find_set_course_menu()
    assert menu is not None, "no live Set Course menu"
    return menu, panel._snapshot_node(menu)


def _shape(node):
    """{system label: [region labels]} plus the rows in order."""
    out = {}
    for child in node["children"]:
        out[child["label"]] = [c["label"] for c in child.get("children", [])]
    return out


def test_e3m4_offers_four_systems_from_the_start():
    hm.load("Maelstrom.Episode3.E3M4.E3M4")
    _menu, node = _set_course_node(CrewMenuPanel())

    assert node["type"] == "menu"
    labels = [c["label"] for c in node["children"]]
    assert labels[-1] == CARTOGRAPHY_LABEL
    shape = _shape(node)
    # Itari lists all eight regions though the mission loads only 8 and 5:
    # CreateMenus() registers every region of the system.
    itari = next(v for k, v in shape.items() if "Itari" in k)
    assert len(itari) == 8, shape
    xi = next(v for k, v in shape.items() if "Xi" in k)
    assert len(xi) == 5, shape
    voltair = next(v for k, v in shape.items() if "Voltair" in k)
    assert len(voltair) == 2, shape
    assert any("Starbase" in k for k in shape), shape


def test_a_region_row_click_sets_the_warp_button_course():
    hm.load("Maelstrom.Episode3.E3M4.E3M4")
    from engine.host_loop import record_course_selection

    panel = CrewMenuPanel(on_course_set=record_course_selection)
    menu, node = _set_course_node(panel)
    itari = next(c for c in node["children"] if "Itari" in c["label"])
    region = itari["children"][0]
    assert region["type"] == "button" and region["chosen"] is False

    assert panel.dispatch_event("click:%d" % region["id"]) is True

    widget = panel._widgets_by_id[region["id"]]
    assert hm.the_warp_button().GetDestination() == widget.GetRegionModule()
    # ...and the next snapshot ticks that row and no other.
    _menu, node = _set_course_node(panel)
    ticked = [r["label"] for s in node["children"]
              for r in ([s] + s.get("children", [])) if r.get("chosen")]
    assert ticked == [region["label"]]


def test_e7m3_grows_to_six_systems_after_its_briefing():
    hm.load("Maelstrom.Episode7.E7M3.E7M3")
    hm.tick_until(lambda: len(_shape(_set_course_node(CrewMenuPanel())[1])) >= 6,
                  bound_s=hm.MASTER_DIALOGUE_BOUND_S)
    shape = _shape(_set_course_node(CrewMenuPanel())[1])
    for system, regions in (("Poseidon", 2), ("Geble", 4), ("Serris", 3),
                            ("Artrus", 3), ("Ascella", 5)):
        got = next(v for k, v in shape.items() if system in k)
        assert len(got) == regions, (system, shape)


def test_cartography_opens_the_map_on_the_live_menu():
    hm.load("Maelstrom.Episode5.E5M4.E5M4")
    opened = []
    panel = CrewMenuPanel(on_set_course=opened.append)
    menu, node = _set_course_node(panel)
    alioth = next(v for k, v in _shape(node).items() if "Alioth" in k)
    assert len(alioth) == 8
    cart = node["children"][-1]
    assert cart["label"] == CARTOGRAPHY_LABEL
    assert panel.dispatch_event("click:" + cart["id"]) is True
    assert opened == [menu]


def _star_map_rows(set_name):
    import json
    from engine.ui.star_map_panel import StarMapPanel
    p = StarMapPanel()
    p.open(course_menu=warp.find_set_course_menu(), set_name=set_name)
    d = json.loads(p.render_payload()[len("setStarMapPanel("):-2])
    return {r["label"]: r for r in d["warp_points"]}


def test_e1m1_marks_starbase_12_as_the_objective_from_the_dry_dock():
    """E1M1 offers only Tau Ceti and names no row until later in the
    tutorial. Inferred: the one destination that is not the Dry Dock the
    player is in."""
    hm.load("Maelstrom.Episode1.E1M1.E1M1")
    rows = _star_map_rows("DryDock")
    assert rows["Starbase 12"]["objective"] is True
    assert rows["Dry Dock"]["objective"] is False
    # ...and it is an inference, not a mission signal: not blue.
    assert rows["Starbase 12"]["mission"] is False


def test_no_inference_with_several_candidates():
    """E3M4 names Itari as a mission system but no region in it. The player
    is not in Itari, so all eight regions are candidates — too many to infer
    from, so only rows the mission itself names are marked."""
    hm.load("Maelstrom.Episode3.E3M4.E3M4")
    from engine.ui.star_map_panel import StarMapPanel
    import json
    p = StarMapPanel()
    p.open(course_menu=warp.find_set_course_menu(), set_name="Starbase12")
    p.dispatch_event("select-system:itari")
    d = json.loads(p.render_payload()[len("setStarMapPanel("):-2])
    marked = [r["label"] for r in d["warp_points"] if r["objective"]]
    named = [r["label"] for r in d["warp_points"] if r["mission"]]
    assert marked == named
