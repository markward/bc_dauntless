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
    """Walk the ship's subsystems and return the first whose GetName()
    matches. Returns None if no match — caller treats that as "clear
    subsystem lock"."""
    import App
    it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
    try:
        sub = ship.GetNextSubsystemMatch(it)
        while sub is not None:
            if hasattr(sub, "GetName") and sub.GetName() == name:
                return sub
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

        rows = []
        child = target_menu.GetFirstChild()
        while child is not None:
            if isinstance(child, STSubsystemMenu):
                ship = child.GetShip()
                if ship is not None and ship is not player:
                    hull_pct = _query_hull_percentage(ship)
                    shield_pct = _query_shield_percentage(ship)
                    subsystems = tuple(
                        sub_child.GetLabel()
                        for sub_child in child._children
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

    def render_payload(self) -> Optional[str]:
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
                    "subsystems": [{"name": s} for s in subs],
                    "expanded": expanded,
                }
                for (name, aff, is_vis, hull, shields, subs, expanded) in rows
                if is_vis
            ],
        }
        return "setTargetList(" + json.dumps(payload) + ");"

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
