"""CEF view for the target list panel.

Reads the STTargetMenu singleton each tick, builds a state dict, and
emits a `setTargetList({...})` JS call. Idempotent — only re-emits
when the state snapshot changes from the previous call.

Click events from JS (action = ship name) translate to
``pPlayer.SetTarget(name)``, which fires ET_SET_TARGET and
ET_TARGET_WAS_CHANGED via the engine's existing event machinery.

Plan: docs/superpowers/plans/2026-05-25-target-list-shim.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel


class TargetListView(Panel):
    @property
    def name(self) -> str:
        return "target"

    def __init__(self):
        super().__init__()
        self._last_snapshot: Optional[tuple] = None

    def _snapshot(self):
        """Build a hashable snapshot of the rendered state."""
        import App
        target_menu = App.STTargetMenu_GetTargetMenu()
        if target_menu is None:
            return (self._visible, None, ())
        from engine.appc.target_menu import STSubsystemMenu
        rows = []
        for child in target_menu._children:
            if isinstance(child, STSubsystemMenu):
                ship = child.GetShip()
                rows.append((ship.GetName(), child.GetAffiliation(), child.IsVisible()))
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        selected = None
        if game is not None:
            player = game.GetPlayer()
            if player is not None and player.GetTarget() is not None:
                selected = player.GetTarget().GetName()
        return (self._visible, selected, tuple(rows))

    def render_payload(self) -> Optional[str]:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, selected, rows = snapshot
        payload = {
            "visible": visible,
            "selected": selected,
            "rows": [
                {"name": name, "affiliation": aff}
                for (name, aff, is_vis) in rows
                if is_vis
            ],
        }
        return "setTargetList(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        """Action is the ship name (verbatim from the JS row data attr)."""
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        if game is None:
            return False
        player = game.GetPlayer()
        if player is None:
            return False
        player.SetTarget(action)
        return True

    def invalidate(self) -> None:
        """Force the next render_payload to re-emit."""
        self._last_snapshot = None
