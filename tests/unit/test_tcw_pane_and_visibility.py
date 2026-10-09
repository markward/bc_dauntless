"""TacticalControlWindow is a TGPane, and its visibility follows BC's Refresh rule.

BC: `class TacticalControlWindow(TGPane)` (App.py:7428; the clean-room
reference's type graph gives TGPane -> TacticalControlWindow). Ours derived
from TGEventHandlerObject and re-implemented a slice of the pane surface, so
every other pane call fell through to a TRUTHY _Stub: IgnoreNextMouseKeyEvent()
read as "ignore every click", GetOpenMenu() as "a menu is always open",
GetNextChild() as a non-window, and SetVisible/SetNotVisible did nothing.

Visibility. In BC the TCW is shown or hidden by
Tactical.Interface.TacticalControlWindow.Refresh (:298-365): on the bridge it
is visible only while a top-level menu is open; on tactical it is visible.
MissionLib.StartCutscene hides it (:754); EndCutscene re-shows it only on
tactical (:795). Info boxes are its children, so they draw only while it is
visible.

Every E1M1 bridge tutorial box is shown inside a cutscene, in this order:
StartCutscene -> ChangeToBridge -> AT_MENU_UP -> ShowInfoBox (E1M1.py:3516-3537
and four more). The boxes are visible in BC, so a menu opening must re-run
Refresh's rule -- that is why the rule is re-evaluated in MenuUp/MenuDown as
well as at the bridge/tactical focus changes.
"""
import json

import App
import MissionLib
from engine.appc.characters import STTopLevelMenu_CreateW
from engine.appc.top_window import TopWindow_GetTopWindow
from engine.appc.tg_ui.widgets import TGPane
from engine.appc.windows import TacticalControlWindow, _STStylizedWindow
from engine.ui import crew_menu_hotkeys
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.ui.info_box_panel import InfoBoxPanel


def setup_function(_):
    TacticalControlWindow._instance = None


def _tcw():
    return App.TacticalControlWindow_GetTacticalControlWindow()


def _wired_officer(label="Helm"):
    """An officer whose menu is registered on the TCW, with a CrewMenuPanel
    wired so MenuUp/MenuDown drive the real open-menu state."""
    tcw = _tcw()
    menu = STTopLevelMenu_CreateW(label)
    tcw.AddMenuToList(menu)
    panel = CrewMenuPanel()
    crew_menu_hotkeys.wire(tcw, panel)
    officer = App.CharacterClass_Create("b.nif", "h.nif")
    officer.SetCharacterName(label)
    officer.SetMenu(menu)
    return officer, menu


def _info_box():
    """A real MissionLib info box parented to the TCW, shown."""
    player = App.TGEventHandlerObject()
    box = MissionLib.SetupInfoBox("Title", "body", 300, 200,
                                  None, None, App.ET_CHARACTER_MENU, player, 0)
    _tcw().AddChild(box, 0, 0)
    MissionLib.ShowInfoBox(None, box.GetObjID())
    return box


def _drawn_box_ids():
    js = InfoBoxPanel().render_payload()
    return [e["id"] for e in json.loads(js[len("setInfoBoxes("):-2])["entries"]]


# ── The pane surface ─────────────────────────────────────────────────────────

def test_tcw_is_a_tgpane():
    tcw = _tcw()
    assert isinstance(tcw, TGPane)
    assert App.TGPane_Cast(tcw) is tcw


def test_child_iteration_walks_added_children():
    tcw = _tcw()
    a, b = _STStylizedWindow("A"), _STStylizedWindow("B")
    tcw.AddChild(a, 0, 0)
    tcw.AddChild(b, 0, 0)
    assert tcw.GetNumChildren() == 2
    assert tcw.GetFirstChild() is a
    assert tcw.GetNextChild(a) is b
    assert tcw.GetNextChild(b) is None


def test_sdk_next_window_lookup_finds_the_sibling():
    # TacticalControlWindow.py:775 / :1222 -- the Engineer window finds the
    # Power window as its next sibling to give both the focus glass.
    tcw = _tcw()
    engineer, power = _STStylizedWindow("Engineer"), _STStylizedWindow("Power")
    tcw.AddChild(engineer, 0, 0)
    tcw.AddChild(power, 0, 0)
    found = App.STStylizedWindow_Cast(engineer.GetParent().GetNextChild(engineer))
    assert found is power


def test_ignore_next_mouse_key_event_defaults_off():
    # BridgeHandlers.HandleKeyboard:519 swallows the click when this is set.
    tcw = _tcw()
    assert tcw.IgnoreNextMouseKeyEvent() == 0
    tcw.SetIgnoreNextMouseKeyEvent(1)
    assert tcw.IgnoreNextMouseKeyEvent() == 1
    tcw.SetIgnoreNextMouseKeyEvent(0)
    assert tcw.IgnoreNextMouseKeyEvent() == 0


def test_get_open_menu_is_none_when_nothing_is_open():
    _wired_officer()
    assert _tcw().GetOpenMenu() is None


def test_get_open_menu_returns_the_open_menu():
    officer, menu = _wired_officer()
    officer.MenuUp()
    assert _tcw().GetOpenMenu() is menu


# ── Visibility ───────────────────────────────────────────────────────────────

def test_set_not_visible_hides_the_tcw():
    tcw = _tcw()
    tcw.SetNotVisible(0)
    assert tcw.IsVisible() == 0
    tcw.SetVisible(0)
    assert tcw.IsVisible() == 1


def test_info_boxes_are_not_drawn_while_the_tcw_is_hidden():
    box = _info_box()
    assert _drawn_box_ids() == [box._id]
    _tcw().SetNotVisible(0)
    assert _drawn_box_ids() == []
    _tcw().SetVisible(0)
    assert _drawn_box_ids() == [box._id]


def test_bridge_with_no_open_menu_hides_the_tcw():
    _wired_officer()
    TopWindow_GetTopWindow().ForceBridgeVisible()
    assert _tcw().IsVisible() == 0


def test_bridge_menu_up_shows_and_menu_down_hides_the_tcw():
    officer, _menu = _wired_officer()
    TopWindow_GetTopWindow().ForceBridgeVisible()
    officer.MenuUp()
    assert _tcw().IsVisible() == 1
    officer.MenuDown()
    assert _tcw().IsVisible() == 0


def test_tactical_shows_the_tcw():
    _wired_officer()
    top = TopWindow_GetTopWindow()
    top.ForceBridgeVisible()
    assert _tcw().IsVisible() == 0
    top.ToggleBridgeAndTactical()
    assert top.IsTacticalVisible()
    assert _tcw().IsVisible() == 1


def test_tactical_focus_during_a_cutscene_keeps_the_tcw_hidden():
    # TacticalInterfaceHandlers.GotFocus:139-142.
    _wired_officer()
    top = TopWindow_GetTopWindow()
    MissionLib.StartCutscene(None)
    top.ForceTacticalVisible()
    assert _tcw().IsVisible() == 0


def test_e1m1_tutorial_box_is_drawn_after_cutscene_bridge_menu_up():
    """E1M1.py:3516-3537: StartCutscene, ChangeToBridge, Kiska AT_MENU_UP,
    ShowInfoBox. The box must be on screen."""
    officer, _menu = _wired_officer()
    MissionLib.StartCutscene(None)
    assert _tcw().IsVisible() == 0
    TopWindow_GetTopWindow().ForceBridgeVisible()   # ChangeToBridge
    officer.MenuUp()                                # AT_MENU_UP
    box = _info_box()                               # ShowInfoBox
    assert _drawn_box_ids() == [box._id]


def test_end_cutscene_on_tactical_reshows_the_tcw():
    # EndCutscene takes its tactical branch (:793-795) when the rendered set
    # is not the bridge -- i.e. a space set is being drawn.
    _wired_officer()
    space = App.SetClass_Create()
    App.g_kSetManager.AddSet(space, "TcwVisibilitySpace")
    App.g_kSetManager.MakeRenderedSet("TcwVisibilitySpace")
    top = TopWindow_GetTopWindow()
    top.ForceTacticalVisible()
    MissionLib.StartCutscene(None)
    assert _tcw().IsVisible() == 0
    MissionLib.EndCutscene(None)
    assert _tcw().IsVisible() == 1
