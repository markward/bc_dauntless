"""SDK target-list shim — STTargetMenu / STSubsystemMenu / STComponentMenu.

Mirrors the SDK surface at sdk/Build/scripts/App.py:8051-8201 with only
the calls SDK Python scripts actually make. Engine-internal methods
(ShowUnknownName / ShowRealName) are no-ops; the engine layer drives
sensor identification state directly in a later phase.

Plan: docs/superpowers/plans/2026-05-25-target-list-shim.md
"""
from __future__ import annotations

from engine.appc.characters import STMenu, STTopLevelMenu


class STSubsystemMenu(STMenu):
    """One row in the target list — represents a single ship.

    SDK pattern: target_menu's children are STSubsystemMenu siblings,
    each subsystem-menu's children are per-subsystem rows. CycleTarget
    reads GetShip() and IsVisible() on each STSubsystemMenu sibling.
    """

    def __init__(self, ship, label: str = ""):
        super().__init__(label or (ship.GetName() if ship else ""))
        self._ship = ship

    def GetShip(self):
        return self._ship

    def IsVisible(self) -> int:
        return 1 if self._visible else 0

    def ShowUnknownName(self, *args) -> None:
        """Engine-internal — sensor ID state. SDK never calls."""
        pass

    def ShowRealName(self, *args) -> None:
        """Engine-internal — sensor ID state. SDK never calls."""
        pass


class STComponentMenu(STMenu):
    """Per-component sub-row inside STSubsystemMenu.

    Never invoked from SDK Python; empty subclass satisfies isinstance
    checks if they ever appear in code we load.
    """
    pass


class STTargetMenu(STTopLevelMenu):
    """The whole target list — children are STSubsystemMenu rows."""

    def __init__(self, label: str = ""):
        super().__init__(label)
        # The last ship the player manually selected. Survives across
        # mission saves so a reload restores the selection. SDK callers
        # mutate via ClearPersistentTarget; engine sets it on real clicks.
        self._persistent_target_name: str | None = None

    # ── Sibling traversal required by CycleTarget ──
    def GetFirstChild(self):
        return self._children[0] if self._children else None

    def GetLastChild(self):
        return self._children[-1] if self._children else None

    def GetNextChild(self, child):
        try:
            i = self._children.index(child)
        except ValueError:
            return None
        return self._children[i + 1] if i + 1 < len(self._children) else None

    def GetPrevChild(self, child):
        try:
            i = self._children.index(child)
        except ValueError:
            return None
        return self._children[i - 1] if i > 0 else None

    def GetObjectEntry(self, ship):
        """Return the STSubsystemMenu whose GetShip() is ``ship``.

        SDK: TacticalInterfaceHandlers.py:711 (CycleTarget). Identity
        comparison — the SDK passes the actual ShipClass object.
        """
        for child in self._children:
            if isinstance(child, STSubsystemMenu) and child.GetShip() is ship:
                return child
        return None
