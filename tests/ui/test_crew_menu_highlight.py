"""CrewMenuPanel snapshot carries ui_attention's pointer-arrow flag.

Covers the identifier-centric UI attention design's Task 3: every node that
gets a widget id (STMenu/submenu rows AND STButton leaves) must carry
"attention" (and "attentionColor" when set), and the mission's
RefreshArrows hide->show cycle (both inside one Python tick, 8x/second) must
never make the CEF-facing payload flicker.

BC's OTHER attention verb — TGUIObject.SetHighlighted, node["highlighted"] —
is a separate flag with a separate look; see tests/ui/test_sdk_widget_highlight.py.

See docs/superpowers/specs/2026-07-12-identifier-centric-ui-attention-design.md
and engine/ui/ui_attention.py's module docstring.
"""
import json

import App
from engine.appc.characters import STButton, STMenu, STTopLevelMenu
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.appc.windows import TacticalControlWindow
from engine.ui import ui_attention
from engine.ui.crew_menu_panel import CrewMenuPanel

import pytest


@pytest.fixture
def crew_panel_with_helm_menu():
    """Helm top-level menu with a 'Set Course' STMenu submenu (mirrors the
    real E1M1 target: pKiskaMenu.GetSubmenuW("Set Course") — a submenu row,
    not a leaf button)."""
    TacticalControlWindow._instance = None
    ui_attention.hide_pointer_arrows()
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    setcourse = STMenu("Set Course")
    setcourse.AddChild(STButton("Sol System"))
    helm.AddChild(setcourse)
    tcw.AddMenuToList(helm)
    panel = CrewMenuPanel()
    panel.render_payload()          # populate _widgets_by_id / prime _last_pushed
    yield panel, setcourse
    ui_attention.hide_pointer_arrows()


def _find(payload, widget):
    wid = ensure_widget_id(widget)

    def walk(nodes):
        for n in nodes:
            if n.get("id") == wid:
                return n
            found = walk(n.get("children", []))
            if found is not None:
                return found
        return None

    return walk(payload["menus"])


def test_snapshot_marks_highlighted_node(crew_panel_with_helm_menu):
    panel, set_course_submenu = crew_panel_with_helm_menu
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, set_course_submenu, 0, 0.0, None)
    payload = panel.snapshot()
    node = _find(payload, set_course_submenu)
    assert node["attention"] is True


def test_snapshot_unhighlighted_by_default(crew_panel_with_helm_menu):
    panel, set_course_submenu = crew_panel_with_helm_menu
    ui_attention.hide_pointer_arrows()
    node = _find(panel.snapshot(), set_course_submenu)
    assert node["attention"] is False


def test_snapshot_carries_highlight_color_when_set(crew_panel_with_helm_menu):
    panel, set_course_submenu = crew_panel_with_helm_menu
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, set_course_submenu, 0, 0.0, "gold")
    node = _find(panel.snapshot(), set_course_submenu)
    assert node["attentionColor"] == "gold"


def test_render_payload_json_safe_with_tgcolora_kcolor(crew_panel_with_helm_menu):
    """kColor is DEAD in every live SDK ShowArrow call site today, but the
    signature accepts a raw TGColorA/NiColorA. If a mission ever did pass
    one, render_payload's json.dumps() must not blow up -- ui_attention
    coerces kColor to a CSS string at capture time rather than storing the
    object as-is."""
    panel, set_course_submenu = crew_panel_with_helm_menu
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, set_course_submenu, 0, 0.0, App.NiColorA_WHITE)
    payload_json = panel.render_payload()  # calls json.dumps() internally -- must not raise
    assert payload_json is not None
    json.dumps(panel.snapshot())  # same proof, directly against the raw payload dict
    node = _find(panel.snapshot(), set_course_submenu)
    assert isinstance(node["attentionColor"], str)


def test_snapshot_omits_highlight_color_when_unset(crew_panel_with_helm_menu):
    panel, set_course_submenu = crew_panel_with_helm_menu
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, set_course_submenu, 0, 0.0, None)
    node = _find(panel.snapshot(), set_course_submenu)
    assert "attentionColor" not in node


def test_highlight_flag_reaches_button_leaves_too(crew_panel_with_helm_menu):
    # The flag must not be submenu-only -- every id-bearing node gets it.
    panel, set_course_submenu = crew_panel_with_helm_menu
    leaf = set_course_submenu._children[0]      # the "Sol System" STButton
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, leaf, 0, 0.0, None)
    node = _find(panel.snapshot(), leaf)
    assert node["attention"] is True


def test_refresh_cycle_leaves_payload_identical(crew_panel_with_helm_menu):
    """THE FLICKER TRAP. The mission's RefreshArrows timer calls HidePointerArrows()
    then re-issues ShowPointerArrow 8x/sec. Both happen inside ONE tick, so the next
    snapshot must be byte-identical to the previous one — otherwise CEF re-renders and
    restarts the CSS pulse animation 8x/sec, which looks broken."""
    panel, target = crew_panel_with_helm_menu
    ui_attention.show_pointer_arrow(None, target, 0, 0.0, None)
    before = panel.snapshot()
    ui_attention.hide_pointer_arrows()                       # what RefreshArrows does...
    ui_attention.show_pointer_arrow(None, target, 0, 0.0, None)  # ...then re-shows
    after = panel.snapshot()
    assert after == before


def test_render_payload_not_repushed_across_refresh_cycle(crew_panel_with_helm_menu):
    """Same trap, at the level that actually matters: the CEF-facing push
    (render_payload/PanelRegistry.render_all) must not re-fire across the
    hide->show cycle, since CrewMenuPanel.render_payload gates on payload
    string-equality against self._last_pushed."""
    panel, target = crew_panel_with_helm_menu
    ui_attention.show_pointer_arrow(None, target, 0, 0.0, None)
    assert panel.render_payload() is not None    # highlight turning on IS a change
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, target, 0, 0.0, None)
    assert panel.render_payload() is None         # net-unchanged -> gated, no re-push
