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

        Passes ``App.CT_SHIP_SUBSYSTEM`` to ``StartGetSubsystemMatch`` so
        all subsystems (sensor, impulse, warp, weapons, shields, hull, etc.)
        are iterated and each gets a child STMenu row under the ship row.

        Silently no-ops when ``ship`` is not a ``ShipClass`` instance.
        Reason: ``TGObject.__getattr__`` returns ``_Stub()`` for any
        missing attribute, so ``hasattr(obj, "StartGetSubsystemMatch")``
        is True for every TGObject subclass — including the bridge
        interior ObjectClass in the "bridge" set on this codebase.
        Iterating subsystems on such a stub leads to an infinite loop
        (``_Stub() is not None`` is True). The isinstance check rejects
        non-ships at the API boundary.
        """
        import App as _App
        from engine.appc.ships import ShipClass
        if ship is None or not isinstance(ship, ShipClass):
            return
        row = self.GetObjectEntry(ship)
        if row is None:
            row = STSubsystemMenu(ship, ship.GetName())
            self.AddChild(row)
        row.KillChildren()
        kIter = ship.StartGetSubsystemMatch(_App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(kIter)
        while sub is not None:
            label = sub.GetName() if hasattr(sub, "GetName") else ""
            row.AddChild(STMenu(label))
            sub = ship.GetNextSubsystemMatch(kIter)
        ship.EndGetSubsystemMatch(kIter)

    def RebuildShipMenus(self, source_set=None) -> None:
        """Bulk rebuild. Never called from SDK Python; included so the
        engine auto-population hook has a single entry point.

        Walks ``source_set`` (or the "bridge" set when ``None``, for
        backward compatibility with existing tests) and rebuilds rows
        for every ShipClass member. Non-ship members are skipped —
        see RebuildShipMenu for the underlying reason.

        In this codebase the "bridge" set holds the bridge interior
        only; spawned ships live in mission-named spatial sets like
        "Biranu1". Pass that spatial set explicitly to populate the
        target list from real ships.
        """
        import App as _App
        from engine.appc.ships import ShipClass
        if source_set is None:
            source_set = _App.g_kSetManager.GetSet("bridge")
        if source_set is None:
            return
        for obj in source_set.GetObjectList():
            if isinstance(obj, ShipClass):
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


# ── Bridge-set integration ───────────────────────────────────────────────────

def _on_bridge_set_event(event: str, obj, identifier: str) -> None:
    """SetClass subscriber callback — drives target-menu rows from
    bridge-set add/remove events."""
    menu = STTargetMenu_GetTargetMenu()
    if menu is None:
        return
    if event == "added":
        if hasattr(obj, "StartGetSubsystemMatch"):
            menu.RebuildShipMenu(obj)
            menu.ResetAffiliationColors()
    elif event == "removed":
        row = menu.GetObjectEntry(obj)
        if row is not None:
            menu.DeleteChild(row)


def wire_to_bridge_set(bridge_set) -> None:
    """Subscribe the target-menu singleton to a bridge set.

    Idempotent — subscribing the same callback twice is a no-op (the
    SetClass.subscribe API enforces uniqueness).
    """
    bridge_set.subscribe(_on_bridge_set_event)


def unwire_from_bridge_set(bridge_set) -> None:
    """Counterpart to wire_to_bridge_set — removes the target-menu
    callback from this bridge set's subscriber list. Called by
    ``reset_sdk_globals`` on mission swap so the subscription doesn't
    leak across missions.
    """
    bridge_set.unsubscribe(_on_bridge_set_event)


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
