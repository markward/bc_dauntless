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


def _query_hull_percentage(ship) -> int:
    """Return hull condition as an integer percentage 0-100, or 100 if
    the ship has no hull subsystem (defensive — shouldn't happen on
    real ships)."""
    if ship is None:
        return 100
    # Try GetHull then GetHullSubsystem — accessor name varies.
    hull = None
    for name in ("GetHull", "GetHullSubsystem"):
        if hasattr(ship, name):
            try:
                hull = getattr(ship, name)()
            except Exception:
                hull = None
            if hull is not None:
                break
    if hull is None or not hasattr(hull, "GetConditionPercentage"):
        return 100
    try:
        return int(round(hull.GetConditionPercentage() * 100))
    except Exception:
        return 100


def _resolve_subsystem_by_name(ship, name: str):
    """Walk the ship's subsystems (and their children) and return the first
    whose GetName() matches. Returns None if no match — caller treats that
    as 'clear subsystem lock'."""
    import App

    def _search(sub):
        if hasattr(sub, "GetName") and sub.GetName() == name:
            return sub
        n = sub.GetNumChildSubsystems() if hasattr(sub, "GetNumChildSubsystems") else 0
        for i in range(n):
            child = sub.GetChildSubsystem(i)
            if child is not None:
                hit = _search(child)
                if hit is not None:
                    return hit
        return None

    it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
    try:
        sub = ship.GetNextSubsystemMatch(it)
        while sub is not None:
            hit = _search(sub)
            if hit is not None:
                return hit
            sub = ship.GetNextSubsystemMatch(it)
    finally:
        ship.EndGetSubsystemMatch(it)
    return None


def _query_shield_percentage(ship) -> int:
    """Return shield strength as an integer percentage 0-100."""
    if ship is None or not hasattr(ship, "GetShields"):
        return 0
    shields = ship.GetShields()
    if shields is None or not hasattr(shields, "GetShieldPercentage"):
        return 0
    try:
        return int(round(shields.GetShieldPercentage() * 100))
    except Exception:
        return 0


def _query_subsystem_condition(ship, name: str) -> int:
    """Return the named subsystem's condition as an integer percentage
    0-100. Prefers GetCombinedConditionPercentage so parent weapon
    systems reflect aggregated child condition; falls back to
    GetConditionPercentage when the combined variant is absent.

    Defaults to 100 on any failure (subsystem missing, getter raises)
    so a transient resolution miss draws a full bar rather than an
    empty one."""
    if ship is None or not name:
        return 100
    sub = _resolve_subsystem_by_name(ship, name)
    if sub is None:
        return 100
    getter = getattr(sub, "GetCombinedConditionPercentage", None)
    if getter is None:
        getter = getattr(sub, "GetConditionPercentage", None)
    if getter is None:
        return 100
    try:
        return int(round(getter() * 100))
    except Exception:
        return 100


def _query_subsystem_destroyed(ship, name: str) -> bool:
    """True when the named subsystem is permanently destroyed (``IsDestroyed``).

    Defaults to False on any resolution/getter failure so a transient lookup
    miss never wrongly hides a live system — the mirror of
    ``_query_subsystem_condition`` defaulting to a full bar."""
    if ship is None or not name:
        return False
    sub = _resolve_subsystem_by_name(ship, name)
    if sub is None or not hasattr(sub, "IsDestroyed"):
        return False
    try:
        return bool(sub.IsDestroyed())
    except Exception:
        return False


def _next_living_sibling(sub):
    """Return the next non-destroyed sibling of ``sub`` within its parent
    subsystem group, searching cyclically from ``sub``. Returns None when the
    group has no surviving sibling or ``sub`` has no parent group (a top-level
    or last-of-group subsystem) — the caller reads None as "drop the lock back
    to ship level"."""
    parent = sub.GetParentSubsystem() if hasattr(sub, "GetParentSubsystem") else None
    if parent is None or not hasattr(parent, "GetNumChildSubsystems"):
        return None
    n = parent.GetNumChildSubsystems()
    siblings = [parent.GetChildSubsystem(i) for i in range(n)]
    start = next((i for i, s in enumerate(siblings) if s is sub), -1)
    order = siblings[start + 1:] + siblings[:start + 1] if start >= 0 else siblings
    for cand in order:
        if cand is None or cand is sub:
            continue
        if hasattr(cand, "IsDestroyed"):
            try:
                if cand.IsDestroyed():
                    continue
            except Exception:
                pass
        return cand
    return None


class TargetListView(Panel):
    @property
    def name(self) -> str:
        return "target"

    # Special subsystem-name sentinel for "toggle this row's expansion".
    # Real subsystem names never start with __, so this can't collide.
    _TOGGLE_ACTION = "__toggle__"

    def __init__(self):
        super().__init__()
        self._last_snapshot: Optional[tuple] = None
        # Names of ships whose subsystem children are currently expanded
        # in the panel. Persists across re-renders so a Cmd+R reload
        # preserves the user's open accordions until something
        # invalidates explicitly.
        self._expanded_ships: set = set()
        # Keys are "<ship-name>/<subsystem-name>" for subsystem (aggregator)
        # rows whose child leaves are expanded in the panel (2nd accordion
        # level). Persists across re-renders like _expanded_ships.
        self._expanded_subsystems: set = set()

    def _snapshot(self):
        """Build a hashable snapshot of the rendered state."""
        import App
        target_menu = App.STTargetMenu_GetTargetMenu()
        if target_menu is None:
            return (self._visible, None, None, ())
        from engine.appc.target_menu import STSubsystemMenu
        # Resolve the player ship so we can exclude it from the panel —
        # the player's own ship shouldn't be a target.
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        player = game.GetPlayer() if game is not None else None

        from engine.appc.ship_death import _out_of_action, is_targetable_wreck
        rows = []
        child = target_menu.GetFirstChild()
        while child is not None:
            if isinstance(child, STSubsystemMenu):
                ship = child.GetShip()
                # A living ship, or a destroyed ship still inside its wreck
                # linger window, is a valid target; a ship past final removal
                # is dropped.
                if ship is not None and ship is not player \
                        and (not _out_of_action(ship) or is_targetable_wreck(ship)):
                    hull_pct = _query_hull_percentage(ship)
                    shield_pct = _query_shield_percentage(ship)
                    # sub_child.GetLabel() equals the subsystem's GetName()
                    # by construction in STSubsystemMenu.RebuildShipMenu, so
                    # the label is a valid lookup key for the name-based
                    # _resolve_subsystem_by_name path inside _query_subsystem_condition.
                    ship_name_for_keys = ship.GetName()
                    def _sub_entry(sub_child):
                        label = sub_child.GetLabel()
                        cond = _query_subsystem_condition(ship, label)
                        # Destroyed children drop out of the parent's child list.
                        kids = tuple(
                            (gc.GetLabel(), _query_subsystem_condition(ship, gc.GetLabel()))
                            for gc in getattr(sub_child, "_children", ())
                            if not _query_subsystem_destroyed(ship, gc.GetLabel())
                        )
                        expanded = (ship_name_for_keys + "/" + label) in self._expanded_subsystems
                        return (label, cond, kids, expanded)

                    def _keep(sub_child):
                        # A parent group stays listed while at least one child
                        # survives; once every child is destroyed the parent is
                        # delisted too. A childless (leaf) row is delisted when
                        # it is itself destroyed.
                        menu_children = getattr(sub_child, "_children", ())
                        if menu_children:
                            return any(
                                not _query_subsystem_destroyed(ship, gc.GetLabel())
                                for gc in menu_children
                            )
                        return not _query_subsystem_destroyed(ship, sub_child.GetLabel())

                    subsystems = tuple(
                        _sub_entry(sub_child)
                        for sub_child in child._children
                        if _keep(sub_child)
                    )
                    name = ship.GetName()
                    rows.append((
                        name,
                        child.GetAffiliation(),
                        child.IsVisible(),
                        hull_pct,
                        shield_pct,
                        subsystems,
                        name in self._expanded_ships,
                    ))
            child = target_menu.GetNextChild(child)

        selected = None
        selected_subsystem = None
        if player is not None:
            target = player.GetTarget()
            if target is not None:
                selected = target.GetName()
            target_sub = player.GetTargetSubsystem()
            if target_sub is not None and hasattr(target_sub, "GetName"):
                selected_subsystem = target_sub.GetName()
        return (self._visible, selected, selected_subsystem, tuple(rows))

    def _reconcile_subsystem_lock(self) -> None:
        """If the player's locked subsystem has been destroyed, hand the lock
        off to the next surviving sibling in its group; when the whole group is
        gone, clear the lock back to ship-level targeting. Runs every tick so a
        subsystem dying from any cause triggers the handoff."""
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        player = game.GetPlayer() if game is not None else None
        if player is None or not hasattr(player, "GetTargetSubsystem"):
            return
        locked = player.GetTargetSubsystem()
        if locked is None or not hasattr(locked, "IsDestroyed"):
            return
        try:
            destroyed = bool(locked.IsDestroyed())
        except Exception:
            return
        if not destroyed:
            return
        player.SetTargetSubsystem(_next_living_sibling(locked))

    def render_payload(self) -> Optional[str]:
        self._reconcile_subsystem_lock()
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, selected, selected_subsystem, rows = snapshot
        payload = {
            "visible": visible,
            "selected": selected,
            "selected_subsystem": selected_subsystem,
            "rows": [
                {
                    "name": name,
                    "affiliation": aff,
                    "hull": hull,
                    "shields": shields,
                    "subsystems": [
                        {"name": s_name, "condition": s_cond,
                         "expanded": s_expanded,
                         "children": [{"name": c_name, "condition": c_cond}
                                      for (c_name, c_cond) in s_kids]}
                        for (s_name, s_cond, s_kids, s_expanded) in subs
                    ],
                    "expanded": expanded,
                }
                for (name, aff, is_vis, hull, shields, subs, expanded) in rows
                if is_vis
            ],
        }
        return "setTargetList(" + json.dumps(payload) + ");"

    def dispatch_event_subsystem_toggle(self, ship_name: str, subsystem_name: str) -> bool:
        """Toggle the expansion of a subsystem (aggregator) row. Pure UI
        state, no target change."""
        key = ship_name + "/" + subsystem_name
        if key in self._expanded_subsystems:
            self._expanded_subsystems.discard(key)
        else:
            self._expanded_subsystems.add(key)
        return True

    def dispatch_event(self, action: str) -> bool:
        """Action format:
          - ``<ship>``                      — set target ship, clear sub lock
          - ``<ship>/<subsystem>``          — set target + subsystem
          - ``<ship>/__toggle__``           — toggle row expansion (accordion)
        """
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        if game is None:
            return False
        player = game.GetPlayer()
        if player is None:
            return False

        if "/" in action:
            ship_name, suffix = action.split("/", 1)
        else:
            ship_name, suffix = action, None

        # Accordion toggle — pure UI state, no target change.
        if suffix == self._TOGGLE_ACTION:
            if ship_name in self._expanded_ships:
                self._expanded_ships.discard(ship_name)
            else:
                self._expanded_ships.add(ship_name)
            return True

        # Subsystem-level accordion toggle: "<subsystem>/__toggle__".
        if suffix is not None and suffix.endswith("/" + self._TOGGLE_ACTION):
            subsystem_name = suffix[: -(len(self._TOGGLE_ACTION) + 1)]
            return self.dispatch_event_subsystem_toggle(ship_name, subsystem_name)

        player.SetTarget(ship_name)

        if suffix is None:
            # Ship-only click — clear any subsystem lock.
            player.SetTargetSubsystem(None)
            return True

        # Subsystem click — find the subsystem instance on the now-targeted
        # ship and lock it.
        target_ship = player.GetTarget()
        if target_ship is None:
            return True  # ship resolution failed, but the SetTarget call already happened
        sub = _resolve_subsystem_by_name(target_ship, suffix)
        player.SetTargetSubsystem(sub)
        return True

    def invalidate(self) -> None:
        """Force the next render_payload to re-emit."""
        self._last_snapshot = None
