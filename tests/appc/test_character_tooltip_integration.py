"""End-to-end: the real BridgeHandlers.XOUpdateToolTip writes an alert into the
XO's StatusMap key 1, and the tooltip panel renders it. Runs the actual SDK
handler (BridgeHandlers.py:1432, not a reimplementation), proving the
dispatcher chain + StatusMap + panel agree.

XOUpdateToolTip resolves the player via MissionLib.GetPlayer() (->
App.Game_GetCurrentPlayer()) and the XO via
App.CharacterClass_GetObject(App.g_kSetManager.GetSet("bridge"), "XO"), then
loads "data/TGL/Bridge Menus.TGL" and calls pXO.SetStatus(db.GetString(
"Red Alert"), 1) when the player is at RED_ALERT. "BridgeHandlers" is kept
whole-module-stubbed in tools/mission_harness.py and tests/conftest.py (see
engine/ui/tooltip_dispatch._bridge_handlers docstring) so every other SDK
caller's ``import BridgeHandlers`` stays inert; this test reaches the real
module the same way the dispatcher does, via ``_bridge_handlers()``, which
pops the shared stub, imports fresh, and restores the stub -- leaving the
shared name untouched.
"""
import App
from engine.appc.characters import (
    CharacterClass, CharacterClass_SetCurrentToolTipOwner,
)
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.core.game import Game, _set_current_game
from engine.ui import tooltip_dispatch
from engine.ui.character_tooltip_panel import CharacterTooltipPanel


def test_xo_update_tooltip_writes_alert_key1():
    xo = CharacterClass()
    xo.SetCharacterName("XO")

    bridge = SetClass()
    bridge.SetName("bridge")
    bridge.AddObjectToSet(xo, "XO")
    App.g_kSetManager._sets["bridge"] = bridge

    # A player at red alert so XOUpdateToolTip picks the "Red Alert" branch
    # (BridgeHandlers.py:1442-1447 -- RED/YELLOW/GREEN branch on GetAlertLevel).
    player = ShipClass_Create("Galaxy")
    player.SetAlertLevel(player.RED_ALERT)
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)

    try:
        # Reach the REAL BridgeHandlers module the same way the dispatcher
        # does -- NOT a bare `import BridgeHandlers` (that resolves to the
        # shared stub kept inert for DropMenusTurnBack's sake).
        real_handlers = tooltip_dispatch._bridge_handlers()
        assert type(real_handlers.XOUpdateToolTip).__name__ == "function"

        real_handlers.XOUpdateToolTip(xo)
        # "Red Alert" specifically (not just "Alert") proves the RED_ALERT
        # branch fired -- the real "data/TGL/Bridge Menus.TGL" resolves
        # Red/Yellow/Green Alert to three distinct strings (verified against
        # game/data/TGL/Bridge Menus.TGL), so a wrong-branch or stale-default
        # alert level would show up as a mismatch here, not a false pass.
        assert str(xo.GetStatus(1)) == "Red Alert"

        CharacterClass_SetCurrentToolTipOwner(xo)
        snap = CharacterTooltipPanel().snapshot()
        assert snap["visible"] is True
        assert any("Red Alert" in row for row in snap["rows"])
    finally:
        CharacterClass_SetCurrentToolTipOwner(None)
        App.g_kSetManager._sets.pop("bridge", None)
        _set_current_game(None)
