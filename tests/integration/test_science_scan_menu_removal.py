"""The Science -> "Scan Object" submenu must drop a departed object's row.

Bridge/ScienceMenuHandlers registers ExitedSet on BOTH ET_TARGET_LIST_OBJECT_
REMOVED (:93, an undefined constant here, so dead) and ET_EXITED_SET (:92,
which our shim defines) -- so the handler really does run at set exit. It calls
``pScanMenu.RemoveItemW(pObject.GetDisplayName())``.

STMenu had no RemoveItemW, so the call hit TGObject.__getattr__'s truthy _Stub
and the row survived. Two visible consequences, both through
engine/ui/crew_menu_panel.py:150, which renders ``widget._children``:

  1. a destroyed or departed object keeps its Scan Object row forever;
  2. PropertyChange:277 uses ExitedSet as the remove half of a remove-then-
     re-add refresh, so every name/scannability change appends a DUPLICATE row
     (AddChild dedupes the _buttons dict but appends to the _children list).

Drives the real SDK handler rather than reimplementing its logic.
"""
import sys

import pytest

import App
import LoadBridge
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.tg_ui import st_widgets
from engine.core.game import Game, Episode, Mission, _set_current_game


SCAN_MENU = "Scan Object"


@pytest.fixture
def scan_menu():
    """The live Science -> Scan Object submenu, built by the real
    Bridge.ScienceMenuHandlers.CreateMenus via LoadBridge.Load."""
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)
    for name in list(sys.modules):
        if name.startswith("Bridge.") and "StubModule" in type(sys.modules[name]).__name__:
            sys.modules.pop(name)
    try:
        LoadBridge.Load("GalaxyBridge")
        # A player DISTINCT from the exiting object is required, or ExitedSet
        # takes its `(not pPlayer) or player is the object` branch and calls
        # KillChildren() -- which empties the menu and would make these tests
        # pass without RemoveItemW ever running. Caught exactly that way.
        from engine.appc.ships import ShipClass
        player = ShipClass()
        player.SetName("Dauntless")
        game.SetPlayer(player)
        db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
        science = TacticalControlWindow.GetInstance().FindMenu(db.GetString("Science"))
        menu = science.GetSubmenuW(db.GetString(SCAN_MENU))
        App.g_kLocalizationManager.Unload(db)
        assert menu is not None, "Science -> Scan Object submenu was not built"
        yield menu
    finally:
        _set_current_game(None)


def _labels(menu):
    return [c.GetLabel() for c in menu._children]


def _scannable(name):
    """A named, scannable, uncloaked object — the three things CreateScanButton
    requires before it will build a row (ScienceMenuHandlers.py:152-170)."""
    from engine.appc.objects import ObjectClass

    obj = ObjectClass()
    obj.SetName(name)
    return obj


def test_exited_set_removes_the_objects_scan_row(scan_menu):
    import Bridge.ScienceMenuHandlers as smh
    from engine.appc.characters import STButton_CreateW

    obj = _scannable("Vagabond")
    scan_menu.AddChild(STButton_CreateW(obj.GetDisplayName()))
    assert _labels(scan_menu) == ["Vagabond"]

    smh.ExitedSet(obj)
    assert _labels(scan_menu) == []


def test_exited_set_leaves_other_rows_alone(scan_menu):
    import Bridge.ScienceMenuHandlers as smh
    from engine.appc.characters import STButton_CreateW

    for name in ("Vagabond", "Kessok Cruiser"):
        scan_menu.AddChild(STButton_CreateW(name))

    smh.ExitedSet(_scannable("Vagabond"))
    assert _labels(scan_menu) == ["Kessok Cruiser"]


def test_remove_then_re_add_refresh_does_not_duplicate(scan_menu):
    # PropertyChange's shape: ExitedSet, then re-add. The row the player sees
    # must not double up on every rename.
    import Bridge.ScienceMenuHandlers as smh
    from engine.appc.characters import STButton_CreateW

    obj = _scannable("Vagabond")
    scan_menu.AddChild(STButton_CreateW(obj.GetDisplayName()))
    smh.ExitedSet(obj)
    scan_menu.AddChild(STButton_CreateW(obj.GetDisplayName()))
    assert _labels(scan_menu) == ["Vagabond"]
