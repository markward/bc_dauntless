"""CEF view for the SDK ShipDisplay widget.

The SDK creates two ShipDisplay widgets per game (player + target).
Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md
"""
from __future__ import annotations

from typing import Optional

from engine.ui.panel import Panel


ROLE_PLAYER = "player"
ROLE_TARGET = "target"
_VALID_ROLES = (ROLE_PLAYER, ROLE_TARGET)


class ShipDisplayPanel(Panel):
    def __init__(self, role: str):
        super().__init__()
        assert role in _VALID_ROLES, "role must be 'player' or 'target'"
        self._role: str = role
        self._ship_id: int = 0  # App.NULL_ID — bound in Task 4
        self._last_snapshot: Optional[tuple] = None
        self._minimizable: bool = (role == ROLE_TARGET)
        self._minimized: bool = False

    @property
    def name(self) -> str:
        return "ship-" + self._role

    # SDK widget API ----------------------------------------------------
    def SetShipID(self, ship_id) -> None:
        self._ship_id = int(ship_id)
        self._last_snapshot = None  # force re-emit on next tick

    def SetShipIDVar(self, ship_id) -> None:
        """SDK alias used by ShipDisplay.SetShipID at line 148."""
        self._ship_id = int(ship_id)
        self._last_snapshot = None

    def GetShipID(self) -> int:
        return self._ship_id

    def SetMinimizable(self, value) -> None:
        if self._role == ROLE_TARGET:
            self._minimizable = bool(value)
            self._last_snapshot = None

    def SetMinimized(self, value) -> None:
        if self._role == ROLE_TARGET:
            self._minimized = bool(value)
            self._last_snapshot = None

    def IsMinimized(self) -> int:
        return 1 if self._minimized else 0

    def IsMinimizable(self) -> int:
        return 1 if self._minimizable else 0

    # Panel framework ---------------------------------------------------
    def render_payload(self) -> Optional[str]:
        return None  # filled in Task 5

    def dispatch_event(self, action: str) -> bool:
        return False  # filled in Task 6

    def invalidate(self) -> None:
        self._last_snapshot = None
