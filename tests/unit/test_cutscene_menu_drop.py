"""E1M1 ExplainWarp bug: Kiska's Helm menu opened then instantly closed.

Root cause, ROUND 1: two separate mechanisms tried to drop crew menus at
cutscene start, and BOTH were wrong.

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

ROUND 1 fix (commit cc218371) implemented App.STTopLevelMenu_GetOpenMenu()
and STTopLevelMenu.GetOwner()/SetOwner(), then UNSTUBBED the whole
BridgeHandlers SDK module so DropMenusTurnBack() would actually run. That
was WRONG: DropMenusTurnBack()'s body walks into
DropOutOfManualFireMode() -> Bridge.TacticalMenuHandlers.
ResetPickFireButton(), which dereferences TacticalControlWindow.
GetTacticalMenu() with no None-guard -- a path our engine cannot satisfy in
general, and it RAISES (AttributeError: 'NoneType' object has no attribute
'GetButtonW'). The exception unwound out of MissionLib.StartCutscene, through
the mission sequence, into CharacterClass.SendActivationEvent, where it was
silently swallowed -- so ExplainWarp never reached Kiska's AT_MENU_UP at all.

ROUND 2 fix (this file): BridgeHandlers is RE-STUBBED (its body is not safe
to run). Instead, the drop is done directly by our engine, at the same
moment BC does it -- inside _TopWindow.StartCutscene
(engine/appc/top_window.py), which MissionLib.StartCutscene calls right
after (the now no-op) BridgeHandlers.DropMenusTurnBack(). That is still
BEFORE the cutscene sequence's own later AT_MENU_UP, so a scripted menu
raised later in the same cutscene survives by construction. The drop logic
itself (STTopLevelMenu_GetOpenMenu -> GetOwner -> MenuDown) is unchanged and
still exercises the real primitives from ROUND 1.
"""
import App
from engine.appc.characters import STTopLevelMenu_CreateW
from engine.appc.top_window import TopWindow_GetTopWindow
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


def test_bridgehandlers_drop_menus_turn_back_is_a_stubbed_noop():
    """BridgeHandlers is RE-STUBBED (ROUND 2) -- its real body is not safe to
    run: DropMenusTurnBack() -> DropOutOfManualFireMode() ->
    Bridge.TacticalMenuHandlers.ResetPickFireButton() dereferences
    TacticalControlWindow.GetTacticalMenu() with no None-guard and RAISES
    when no Tactical menu has been registered. As a _StubModule,
    DropMenusTurnBack() is a harmless no-op -- it does NOT close an open
    menu. The real drop now happens in _TopWindow.StartCutscene instead (see
    the tests below), which is where MissionLib.StartCutscene calls it
    (immediately after this now-inert BridgeHandlers.DropMenusTurnBack()) --
    so the net behaviour the player sees is unchanged, it just no longer
    routes through SDK code that can crash."""
    import BridgeHandlers
    officer, menu, panel = _wired_officer()
    officer.MenuUp()
    assert panel.has_open_menu() is True

    BridgeHandlers.DropMenusTurnBack()   # stub: no-op, does not raise

    assert panel.has_open_menu() is True   # unchanged -- stub did nothing
    assert officer.IsMenuUp() == 1


def test_missionlib_start_cutscene_does_not_raise():
    """The regression test that matters. Before this fix,
    MissionLib.StartCutscene(None) raised AttributeError:
    BridgeHandlers.DropMenusTurnBack() -> DropOutOfManualFireMode() ->
    Bridge.TacticalMenuHandlers.ResetPickFireButton() -> pMenu.GetButtonW(...)
    with pMenu None, because BridgeHandlers had been unstubbed (ROUND 1) so
    its real, crash-prone body ran. Re-stubbing BridgeHandlers makes that
    call a no-op, so StartCutscene must complete cleanly."""
    import MissionLib
    MissionLib.StartCutscene(None)   # must not raise


def test_missionlib_start_cutscene_closes_an_open_officer_menu():
    """With BridgeHandlers re-stubbed, the drop itself is performed by
    _TopWindow.StartCutscene (engine/appc/top_window.py), which
    MissionLib.StartCutscene calls right after the now-inert
    BridgeHandlers.DropMenusTurnBack(). An officer's open menu must still be
    closed by the end of MissionLib.StartCutscene -- the SDK-visible
    behaviour is unchanged even though the mechanism moved into our
    engine."""
    import MissionLib
    officer, menu, panel = _wired_officer()
    officer.MenuUp()
    assert panel.has_open_menu() is True

    MissionLib.StartCutscene(None)

    assert panel.has_open_menu() is False
    assert officer.IsMenuUp() == 0


def test_explainwarp_ordering_menu_raised_after_startcutscene_survives():
    """The bug test: the ExplainWarp ordering (E1M1.py:3513-3534). A
    cutscene starts (MissionLib.StartCutscene -- nothing is open yet, so the
    drop is a no-op), and THEN, later in the SAME tick, a script raises an
    officer's menu (Kiska's AT_MENU_UP in the real mission). The menu must
    still be open afterwards -- it must NOT be slammed shut by anything
    running later in the tick (there is no end-of-tick clamp; the drop only
    ever fires once, at StartCutscene, inside _TopWindow.StartCutscene)."""
    import MissionLib
    officer, menu, panel = _wired_officer(name="Helm", label="Helm")

    MissionLib.StartCutscene(None)       # cutscene start; nothing open
    assert panel.has_open_menu() is False

    officer.MenuUp()                     # scripted AT_MENU_UP, same tick

    assert panel.has_open_menu() is True
    assert App.STTopLevelMenu_GetOpenMenu() is menu


def test_top_window_start_cutscene_closes_an_open_officer_menu():
    """Unit-level check on the hook itself, bypassing MissionLib/
    BridgeHandlers entirely: _TopWindow.StartCutscene must perform the drop
    (STTopLevelMenu_GetOpenMenu -> GetOwner -> MenuDown), mirroring BC's own
    BridgeHandlers.DropMenusTurnBack (BridgeHandlers.py:1019-1031) at the
    moment MissionLib.StartCutscene calls pTop.StartCutscene(...)
    (MissionLib.py:751), i.e. before any later same-tick AT_MENU_UP."""
    officer, menu, panel = _wired_officer()
    officer.MenuUp()
    assert panel.has_open_menu() is True

    TopWindow_GetTopWindow().StartCutscene(1.0, 0.125, 1)

    assert panel.has_open_menu() is False
    assert officer.IsMenuUp() == 0


def test_top_window_start_cutscene_is_safe_with_no_menu_open():
    """No open menu -> the drop must be a harmless no-op, not raise."""
    TopWindow_GetTopWindow().StartCutscene(1.0, 0.125, 1)   # must not raise
