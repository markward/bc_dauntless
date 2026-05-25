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
        self._affiliation: str = "UNKNOWN"

    def GetShip(self):
        return self._ship

    def GetAffiliation(self) -> str:
        return self._affiliation

    def SetAffiliation(self, token: str) -> None:
        self._affiliation = token

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

    # ── Mutators SDK scripts actually call ──

    def ClearTargetList(self) -> None:
        """SDK: Multiplayer/MissionShared.py:353."""
        self.KillChildren()

    def ClearPersistentTarget(self) -> None:
        """SDK: TacticalInterfaceHandlers.py:656, HelmMenuHandlers.py:947,
        MissionShared.py:354."""
        self._persistent_target_name = None

    def SetPersistentTarget(self, name) -> None:
        """Engine-internal — NOT in the SDK SWIG surface.

        The original BC engine sets the persistent-target hint
        automatically when the player manually selects a target.
        We expose it as a Python method so our engine layer (which
        also handles click events) can drive it the same way. SDK
        scripts only ever call ClearPersistentTarget.
        """
        self._persistent_target_name = str(name) if name else None

    def GetPersistentTarget(self) -> "str | None":
        """Engine-internal — NOT in the SDK SWIG surface.

        Read by the save/load path so a reloaded game can re-fire
        ET_RESTORE_PERSISTENT_TARGET and SetTarget on the same ship.
        """
        return self._persistent_target_name

    def RebuildShipMenu(self, ship) -> None:
        """Add or refresh the row for ``ship``. SDK callsites:
        MissionLib.py:2200, MissionLib.py:2225.

        Phase 1 deferral: the call ``ship.StartGetSubsystemMatch()``
        with no match-type argument returns an empty iterator from the
        current `engine/appc/ships.py` shim, so this method creates the
        STSubsystemMenu row but leaves its subsystem children empty.
        That matches the Phase 1 deliverable — the visible target list
        only shows ship rows, not subsystem children. A future plan
        will pass App.CT_SHIP_SUBSYSTEM and populate per-subsystem
        rows; the iteration loop below is kept as scaffolding for
        that integration.
        """
        if ship is None:
            return
        row = self.GetObjectEntry(ship)
        if row is None:
            row = STSubsystemMenu(ship, ship.GetName())
            self.AddChild(row)
        row.KillChildren()
        kIter = ship.StartGetSubsystemMatch()
        sub = ship.GetNextSubsystemMatch(kIter)
        while sub is not None:
            label = sub.GetName() if hasattr(sub, "GetName") else ""
            row.AddChild(STMenu(label))
            sub = ship.GetNextSubsystemMatch(kIter)
        ship.EndGetSubsystemMatch(kIter)

    def RebuildShipMenus(self) -> None:
        """Bulk rebuild. Never called from SDK Python; included so the
        engine auto-population hook has a single entry point."""
        import App as _App
        bridge = _App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            return
        for obj in bridge.GetObjectList():
            if hasattr(obj, "StartGetSubsystemMatch"):
                self.RebuildShipMenu(obj)

    def ResetAffiliationColors(self) -> None:
        """Recompute every row's affiliation token. SDK callsites:
        Maelstrom/Episode2/E2M2.py:789, E2M6.py:1066 — invoked after
        a mission reassigns ships between groups."""
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        mission = None
        if game is not None:
            ep = game.GetCurrentEpisode()
            if ep is not None:
                mission = ep.GetCurrentMission()
        for child in self._children:
            if isinstance(child, STSubsystemMenu):
                child.SetAffiliation(resolve_affiliation(child.GetShip(), mission))


# ── Module-level singleton + factory ─────────────────────────────────────────

_target_menu_singleton: STTargetMenu | None = None


def STTargetMenu_CreateW(label: str = "") -> STTargetMenu:
    """SDK factory — Bridge/TacticalMenuHandlers.py:492."""
    global _target_menu_singleton
    _target_menu_singleton = STTargetMenu(str(label))
    return _target_menu_singleton


def STTargetMenu_GetTargetMenu() -> "STTargetMenu | None":
    """SDK accessor — TacticalInterfaceHandlers + MissionLib + others."""
    return _target_menu_singleton


def _reset_target_menu_singleton() -> None:
    """Test-only — clear singleton between tests."""
    global _target_menu_singleton
    _target_menu_singleton = None


# ── Lenient cast helpers ─────────────────────────────────────────────────────

def STSubsystemMenu_Cast(obj):
    """Mirrors STMenu_Cast lenient pass-through in characters.py."""
    if isinstance(obj, STSubsystemMenu):
        return obj
    if obj is None:
        return None
    return obj


def STComponentMenu_Cast(obj):
    """Mirrors STMenu_Cast lenient pass-through in characters.py.

    Although STComponentMenu is never invoked from SDK Python
    scripts (engine-internal in original BC), the cast helper is
    exported by App.py and may be hit by tooling that catches
    every public symbol. Same three-branch semantics as
    STSubsystemMenu_Cast.
    """
    if isinstance(obj, STComponentMenu):
        return obj
    if obj is None:
        return None
    return obj


def resolve_affiliation(ship, mission) -> str:
    """Mission groups override static ship-property affiliation.

    Returns one of "FRIENDLY", "ENEMY", "NEUTRAL", "UNKNOWN" — the
    engine layer maps these to the radar colour palette from
    docs/ui_designs/SDK_UI_API.md §1.4.
    """
    if mission is None or ship is None:
        return "UNKNOWN"
    name = ship.GetName()
    if mission.GetFriendlyGroup().IsNameInGroup(name):
        return "FRIENDLY"
    if mission.GetEnemyGroup().IsNameInGroup(name):
        return "ENEMY"
    if mission.GetNeutralGroup().IsNameInGroup(name):
        return "NEUTRAL"
    return "UNKNOWN"
