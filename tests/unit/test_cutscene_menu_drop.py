"""E1M1 ExplainWarp bug: Kiska's Helm menu opened then instantly closed.

Root cause: two separate mechanisms tried to drop crew menus at cutscene
start, and BOTH were wrong.

(a) The SDK's own drop, BridgeHandlers.DropMenusTurnBack() (called by
MissionLib.StartCutscene), reads App.STTopLevelMenu_GetOpenMenu() -- which
was an unimplemented App.__getattr__ catch-all (_NamedStub). A _NamedStub is
TRUTHY, so `if (pOpenMenu):` passed, but `pOpenMenu.GetOwner()` was itself
another _NamedStub, so the drop silently did nothing.

(b) Because (a) never worked, a host-loop clamp
(engine/host_loop.py:_close_crew_menu_during_cutscene, now DELETED) papered
over it by closing any open menu on the cutscene-start edge. But
ExplainWarp's sequence (E1M1.py:3513-3534) runs StartCutscene AND Kiska's
AT_MENU_UP in the SAME TICK -- so the end-of-tick clamp saw the freshly
opened menu and slammed it shut before the player ever saw it.

Fix: implement App.STTopLevelMenu_GetOpenMenu() (backed by the wired
CrewMenuPanel) and STTopLevelMenu.GetOwner()/SetOwner() (backed by
CharacterClass.SetMenu) so DropMenusTurnBack() -- called once, at the
correct moment, INSIDE StartCutscene -- actually closes whatever was open
BEFORE the cutscene's own script raises a new menu. The host-loop clamp is
then redundant and actively wrong (its end-of-tick timing raced the
same-tick MenuUp), so it is deleted outright.
"""
import App
from engine.appc.characters import STTopLevelMenu_CreateW
from engine.appc.windows import TacticalControlWindow
from engine.ui import crew_menu_hotkeys
from engine.ui.crew_menu_panel import CrewMenuPanel


def setup_function(_):
    TacticalControlWindow._instance = None


def _wired_officer(name="Helm", label="Helm"):
    """A bridge officer with a menu ATTACHED and REGISTERED on the TCW's menu
    list, with a CrewMenuPanel wired -- the full SDK attach path
    (`pHelm.SetMenu(tcw.FindMenu("Helm"))`, HelmCharacterHandlers:50) plus
    the view-layer wiring MenuUp/MenuDown need to actually show/hide.

    Also stands up a minimal Tactical menu with a "Manual Aim" button and
    registers it via SetTacticalMenu -- BridgeHandlers.DropMenusTurnBack
    unconditionally calls DropOutOfManualFireMode -> Bridge.TacticalMenu
    Handlers.ResetPickFireButton, which dereferences
    TacticalControlWindow.GetTacticalMenu() with no null-guard. In the real
    game this is always populated by the time any cutscene runs (Bridge.
    TacticalMenuHandlers.CreateMenus() -> SetTacticalMenu runs during
    mission boot, see engine/host_loop.py:resolve_officer_menu_layout); a
    bare test TCW needs the same minimal setup to exercise the real
    BridgeHandlers module end-to-end."""
    tcw = TacticalControlWindow.GetInstance()
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    tac_menu = STTopLevelMenu_CreateW(db.GetString("Tactical"))
    tac_menu.AddChild(App.STButton_CreateW(db.GetString("Manual Aim")))
    tcw.SetTacticalMenu(tac_menu)
    App.g_kLocalizationManager.Unload(db)

    menu = STTopLevelMenu_CreateW(label)
    tcw.AddMenuToList(menu)
    panel = CrewMenuPanel()
    crew_menu_hotkeys.wire(tcw, panel)
    officer = App.CharacterClass_Create("b.nif", "h.nif")
    officer.SetCharacterName(name)
    officer.SetMenu(menu)
    return officer, menu, panel


def test_get_open_menu_returns_none_when_no_menu_open():
    _wired_officer()   # a panel is wired, but nothing has been raised
    val = App.STTopLevelMenu_GetOpenMenu()
    assert val is None


def test_get_open_menu_returns_the_actual_open_menu_not_a_stub():
    officer, menu, panel = _wired_officer()
    officer.MenuUp()
    assert panel.has_open_menu()
    val = App.STTopLevelMenu_GetOpenMenu()
    assert val is menu
    assert type(val).__name__ != "_NamedStub"


def test_drop_menus_turn_back_closes_the_open_menu():
    """The regression test that matters: with an officer's menu open,
    BridgeHandlers.DropMenusTurnBack() -- the exact call MissionLib's
    StartCutscene makes -- actually closes it. This proves the SDK's own
    mechanism works, once App.STTopLevelMenu_GetOpenMenu() and
    STTopLevelMenu.GetOwner() are real."""
    import BridgeHandlers
    officer, menu, panel = _wired_officer()
    officer.MenuUp()
    assert panel.has_open_menu() is True

    BridgeHandlers.DropMenusTurnBack()

    assert panel.has_open_menu() is False
    assert officer.IsMenuUp() == 0


def test_menu_raised_after_startcutscene_drop_survives_the_tick():
    """The bug test: the ExplainWarp ordering. A cutscene starts (which
    calls DropMenusTurnBack once, at the correct moment -- nothing is open
    yet, so it's a no-op), and THEN, later in the SAME tick, a script raises
    an officer's menu (Kiska's AT_MENU_UP in the real mission). The menu
    must still be open afterwards -- it must NOT be slammed shut by
    anything running later in the tick (there is no longer an end-of-tick
    clamp to do that)."""
    import BridgeHandlers
    officer, menu, panel = _wired_officer(name="Helm", label="Helm")

    BridgeHandlers.DropMenusTurnBack()   # StartCutscene's drop; nothing open
    assert panel.has_open_menu() is False

    officer.MenuUp()                     # scripted AT_MENU_UP, same tick

    assert panel.has_open_menu() is True
    assert App.STTopLevelMenu_GetOpenMenu() is menu
