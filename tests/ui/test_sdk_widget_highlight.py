"""BC's own widget-highlight flag reaches CEF.

E1M1 drives it as a script action -- SetUIObjectHighlighted (E1M1.py:4911):

    pSubMenu.SetHighlighted()
    pMenu.SetFocus(pSubMenu)

...to light up the button an officer has just asked the player to press
(Brex's "Report", Miguel's "Scan Area", Saffi's "Green Alert"). STButton
already recorded the flag; nothing ever read it, so the button never lit.

This is a DIFFERENT SDK verb from MissionLib.ShowPointerArrow, and stays a
distinct snapshot key with a distinct look:

  node["attention"]   <- ShowPointerArrow  (pulsing ring; "look here")
  node["highlighted"] <- SetHighlighted    (steady lit; BC's selected state)

Keeping them separate matters because SetHighlighted is a general widget
state, not only a tutorial cue -- Multiplayer/MissionMenusShared.py:352 uses
it as plain list selection, which must not pulse like a tutorial arrow.
"""
import App
import pytest

from engine.appc.characters import STButton, STMenu, STTopLevelMenu
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.appc.windows import TacticalControlWindow
from engine.ui import ui_attention
from engine.ui.crew_menu_panel import CrewMenuPanel


@pytest.fixture
def panel_with_brex_menu():
    """Brex's top-level menu holding a "Report" button — the E1M1 target
    (E1M1.py:2110, pBrexMenu.GetButtonW("Report"))."""
    TacticalControlWindow._instance = None
    ui_attention.hide_pointer_arrows()
    tcw = TacticalControlWindow.GetInstance()
    brex = STTopLevelMenu("Tactical")
    report = STButton("Report")
    brex.AddChild(report)
    tcw.AddMenuToList(brex)
    panel = CrewMenuPanel()
    yield panel, brex, report
    ui_attention.hide_pointer_arrows()


def _find(snapshot, widget):
    wid = ensure_widget_id(widget)

    def walk(nodes):
        for n in nodes:
            if n.get("id") == wid:
                return n
            found = walk(n.get("children", []))
            if found is not None:
                return found
        return None

    return walk(snapshot["menus"])


# ── the SDK widget flag ────────────────────────────────────────────────────

def test_button_highlight_reaches_the_snapshot(panel_with_brex_menu):
    panel, _brex, report = panel_with_brex_menu
    report.SetHighlighted()
    assert _find(panel.snapshot(), report)["highlighted"] is True


def test_button_unhighlighted_by_default(panel_with_brex_menu):
    panel, _brex, report = panel_with_brex_menu
    assert _find(panel.snapshot(), report)["highlighted"] is False


def test_set_not_highlighted_clears_it(panel_with_brex_menu):
    panel, _brex, report = panel_with_brex_menu
    report.SetHighlighted()
    report.SetNotHighlighted()
    assert _find(panel.snapshot(), report)["highlighted"] is False


def test_submenu_rows_are_highlightable_too():
    """STMenu had no SetHighlighted at all, so TGObject.__getattr__ handed
    back a silent _Stub and a submenu target could never light up. BC puts
    SetHighlighted on the TGUIObject base (App.py:1293) — every widget has it.
    """
    TacticalControlWindow._instance = None
    ui_attention.hide_pointer_arrows()
    tcw = TacticalControlWindow.GetInstance()
    helm = STTopLevelMenu("Helm")
    setcourse = STMenu("Set Course")
    helm.AddChild(setcourse)
    tcw.AddMenuToList(helm)
    panel = CrewMenuPanel()

    setcourse.SetHighlighted()
    assert _find(panel.snapshot(), setcourse)["highlighted"] is True
    setcourse.SetNotHighlighted()
    assert _find(panel.snapshot(), setcourse)["highlighted"] is False


# ── the two mechanisms are independent ─────────────────────────────────────

def test_attention_and_highlight_are_separate_flags(panel_with_brex_menu):
    """A tutorial arrow must not imply the lit state, or vice versa — they
    are different SDK verbs and render differently."""
    panel, _brex, report = panel_with_brex_menu
    ui_attention.show_pointer_arrow(None, report, 0, 0.0, None)
    node = _find(panel.snapshot(), report)
    assert node["attention"] is True
    assert node["highlighted"] is False

    ui_attention.hide_pointer_arrows()
    report.SetHighlighted()
    node = _find(panel.snapshot(), report)
    assert node["attention"] is False
    assert node["highlighted"] is True


# ── the stub trap ──────────────────────────────────────────────────────────

def test_non_widget_rows_are_not_silently_highlighted():
    """The repair pane's rows are ShipSubsystems, NOT TG widgets — they have
    no _highlighted attribute. Reading the flag with getattr() would hand back
    a truthy TGObject.__getattr__ _Stub and light every repair row forever.
    apply() must read __dict__ directly. (See docs/stub_heatmap.md.)"""
    from engine.ui.eng_repair_pane import repair_pane_snapshot
    from tests.unit.test_eng_repair_pane import _ship_with_queue   # shared fixture builder

    ship = _ship_with_queue()
    snap = repair_pane_snapshot(ship, lambda wid, sub: None)
    for area in ("repair", "waiting", "destroyed"):
        for row in snap[area]:
            assert row["highlighted"] is False
