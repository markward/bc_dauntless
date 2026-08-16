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
        super().__init__(label or (ship.GetDisplayName() if ship else ""))
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
    """The whole target list — children are STSubsystemMenu rows.

    Children are DERIVED, not stored. `_row_cache` holds one row per ship ever
    seen (identity-stable, because CycleTarget resolves a row then walks
    siblings from it); `_contacts` is the membership pushed each frame. The
    child list is their intersection, computed on read.

    This is why warp needs no target-list code: mid-warp the player is alone in
    the _WarpTransit set, so the pushed list is empty and the menu empties
    itself; on arrival it fills from the destination set.
    """

    def __init__(self, label: str = ""):
        # Set before super().__init__ — the base assigns self._children, which
        # is a property here whose getter reads these.
        self._row_cache: dict = {}
        self._contacts: tuple = ()
        super().__init__(label)
        # The last ship the player manually selected. Survives across
        # mission saves so a reload restores the selection. SDK callers
        # mutate via ClearPersistentTarget; engine sets it on real clicks.
        self._persistent_target_name: str | None = None

    # ── Derived membership ───────────────────────────────────────────────────

    def set_contacts(self, ships) -> None:
        """Push this frame's membership (from perception.contacts_for).

        Idempotent and cheap: rows are built once per ship and reused, so a
        repeated push costs a dict lookup per contact.
        """
        from engine.appc.ships import ShipClass
        self._contacts = tuple(s for s in ships if isinstance(s, ShipClass))
        for ship in self._contacts:
            if ship not in self._row_cache:
                self.RebuildShipMenu(ship)

    def _rows(self) -> list:
        """The projection: cached rows for the current contacts, in order.

        Defensive on both attributes: `_children` is a property, so anything
        that reads it during base-class construction would land here before
        __init__ finishes. TGObject.__getattr__ raises for _private names, so
        getattr-with-default is the guard that works.
        """
        cache = getattr(self, "_row_cache", None)
        contacts = getattr(self, "_contacts", None)
        if not cache or not contacts:
            return []
        return [cache[s] for s in contacts if s in cache]

    @property
    def _children(self) -> list:
        # STMenu.__init__ assigns self._children = []; the setter below absorbs
        # that. Everything that reads children — base class, SDK, our CEF views
        # — goes through this, so nothing can bypass the projection.
        return self._rows()

    @_children.setter
    def _children(self, value) -> None:
        # Membership is derived; there is nothing to store. STMenu.__init__ and
        # KillChildren both assign here and both are correctly no-ops.
        pass

    # ── Sibling traversal required by CycleTarget ──
    def GetFirstChild(self):
        rows = self._rows()
        return rows[0] if rows else None

    def GetLastChild(self):
        rows = self._rows()
        return rows[-1] if rows else None

    def GetNextChild(self, child):
        rows = self._rows()
        try:
            i = rows.index(child)
        except ValueError:
            return None
        return rows[i + 1] if i + 1 < len(rows) else None

    def GetPrevChild(self, child):
        rows = self._rows()
        try:
            i = rows.index(child)
        except ValueError:
            return None
        return rows[i - 1] if i > 0 else None

    def GetNumChildren(self) -> int:
        return len(self._rows())

    def GetObjectEntry(self, ship):
        """Return the listed STSubsystemMenu whose GetShip() is ``ship``.

        SDK: TacticalInterfaceHandlers.py:711 (CycleTarget). Identity
        comparison — the SDK passes the actual ShipClass object.

        Returns None for a ship that is not a current contact even if a row is
        cached, so this agrees with the listing by construction — SDK
        CycleTarget must never be able to select a contact the panel drops.
        """
        if ship not in self._contacts:
            return None
        return self._row_cache.get(ship)

    # ── Mutators SDK scripts actually call ──

    def ClearTargetList(self) -> None:
        """SDK: Multiplayer/MissionShared.py:353.

        Under a derived list this can only drop the cached rows — the contents
        come back on the next push if those ships are still present. That is
        correct for its real caller (MissionShared.ClearShips deletes the ships
        immediately afterwards, so the next push is empty anyway).
        """
        self._row_cache.clear()
        self._contacts = ()

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
        """Create or refresh the cached row for ``ship``. SDK callsites:
        MissionLib.py:2200, MissionLib.py:2225 (HideSubsystems /
        ShowSubsystems).

        It no longer decides whether the ship is LISTED — set_contacts does
        that — so a mission may refresh a ship in another set harmlessly.

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
        row = self._row_cache.get(ship)
        if row is None:
            # Target-list label uses the localized display name ("USS Sovereign",
            # "Galor"), not the raw internal identifier ("player",
            # "Cardassian_Galor1"). The hail list already does this; the target
            # list regressed to identifiers once sensor-identification began
            # populating it. Affiliation/group lookups still key off GetName().
            row = STSubsystemMenu(ship, ship.GetDisplayName())
            self._row_cache[ship] = row
        row.KillChildren()
        kIter = ship.StartGetSubsystemMatch(_App.CT_SHIP_SUBSYSTEM)
        sub = ship.GetNextSubsystemMatch(kIter)
        while sub is not None:
            self._add_subsystem_row(row, sub)
            sub = ship.GetNextSubsystemMatch(kIter)
        ship.EndGetSubsystemMatch(kIter)

    def _add_subsystem_row(self, parent_row, sub):
        """Add a row for `sub` under `parent_row`, then recurse into its
        child subsystems so aggregators (Phasers, Impulse Engines, Tractors,
        ...) become expandable parents of their leaves.

        Filters like BC's native RebuildShipMenu, mirroring
        AI/Preprocessors.GetTargetableSubsystems:

        * The **hull** is never a subsystem row — it is the ship-level bar.
          (An asteroid's hull property is Targetable(1), so it must be
          excluded by type, not by the targetable flag.)
        * A **targetable** subsystem gets a row; its children recurse under it.
        * A **non-targetable** subsystem gets NO row, but its children still
          recurse at the PARENT level — so a targetable weapon bank under a
          non-targetable "Torpedoes"/"Phasers" group is promoted, while an
          inert asteroid's Shield Generator / Power Plant (Targetable(0), no
          children) simply vanishes.
        """
        from engine.appc.subsystems import HullSubsystem
        if isinstance(sub, HullSubsystem):
            return
        targetable = True
        if hasattr(sub, "IsTargetable"):
            try:
                targetable = bool(sub.IsTargetable())
            except Exception:
                targetable = True
        n = sub.GetNumChildSubsystems() if hasattr(sub, "GetNumChildSubsystems") else 0
        if targetable:
            label = sub.GetName() if hasattr(sub, "GetName") else ""
            sub_row = STMenu(label)
            parent_row.AddChild(sub_row)
            recurse_into = sub_row
        else:
            # Not a row itself, but promote any targetable descendants.
            recurse_into = parent_row
        for i in range(n):
            child = sub.GetChildSubsystem(i)
            if child is not None:
                self._add_subsystem_row(recurse_into, child)

    def RebuildShipMenus(self, source_set=None) -> None:
        """Bulk refresh from a set. Never called from SDK Python; included so
        the engine auto-population hook has a single entry point.

        Retained for the existing callers; it now pushes membership rather
        than appending children, so its effect is the same as set_contacts
        over that set's ships. Non-ship members are skipped — see
        RebuildShipMenu for the underlying reason.

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
        self.set_contacts([o for o in source_set.GetObjectList()
                           if isinstance(o, ShipClass)])

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


# ── Cloak → target-menu gate ─────────────────────────────────────────────────
#
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
