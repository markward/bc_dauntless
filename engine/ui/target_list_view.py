"""CEF view for the target list panel.

Reads the STTargetMenu singleton each tick, builds a state dict, and
emits a `setTargetList({...})` JS call. Idempotent — only re-emits
when the state snapshot changes from the previous call.

Click events from JS (action = ship name) translate to
``pPlayer.SetTarget(name)``, which posts only ET_TARGET_WAS_CHANGED
(``engine/appc/ships.py:1565-1571``). ET_SET_TARGET has a real constant
value now but no engine emitter -- it is one of the twelve dead-handler
event types tracked in docs/reference/engine/event-emitter-gaps.md (gap 2).

Plan: docs/superpowers/plans/2026-05-25-target-list-shim.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui import target_markers as _markers
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
        # Same rule as the target-status panel's `_shields_tuple`: the readout
        # must agree with whether shields actually BLOCK, because the shield
        # bubble is gated on that same predicate. This used to special-case
        # only the cloak-transition window; `shields_block` covers that plus a
        # disabled or destroyed generator and the dev disable-NPC-shields
        # cheat, each of which stops absorption while this still reported the
        # stored charge.
        #
        # Fixed in the same change as `_shields_tuple` deliberately — the two
        # readouts sit on screen together, so fixing one alone would have them
        # contradict each other, which is worse than both being wrong.
        # Preserves the charge; it is hidden, not drained.
        from engine.appc.combat import shields_block
        if not shields_block(ship):
            return 0
        return int(round(shields.GetShieldPercentage() * 100))
    except Exception:
        return 0


def _query_has_shields(ship) -> bool:
    """True only when the ship carries a shield subsystem with real capacity.

    Inert hulls (asteroids) still get a ShieldSubsystem, but with all six faces
    at MaxShields=0 — GetShieldPercentage() then reports 1.0 ("shields not a
    factor" for the AI), which would render a full bar. HasShields() lets the
    view suppress the shield bar entirely for those targets."""
    if ship is None or not hasattr(ship, "GetShields"):
        return False
    shields = ship.GetShields()
    if shields is None or not hasattr(shields, "HasShields"):
        return False
    try:
        return bool(shields.HasShields())
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


# How often the target list is polled. See TargetListView.poll_interval_s.
TARGET_LIST_POLL_S = 0.5


SORTS = ("name", "distance", "health")
FILTERABLE = ("FRIENDLY", "NEUTRAL", "ENEMY")


def _natural(label: str) -> tuple:
    """Casefolded label with digit runs as ints, so "Unknown 2" < "Unknown 10".
    Parts alternate text, number, text, ... so tuples always compare like
    with like."""
    import re
    parts = re.split(r"(\d+)", label.casefold())
    return tuple(int(p) if i % 2 else p for i, p in enumerate(parts))


def sort_key(row: dict, sort: str) -> tuple:
    """Ordering key for one payload row under *sort*.

    name: label, case-insensitive and natural (digit runs compare as numbers). distance: surface km, ties by name.
    health: hull, then shields (a shieldless ship counts as 0), then name.
    """
    label = _natural(row["label"])
    if sort == "distance":
        return (row["dist_km"], label)
    if sort == "health":
        return (row["hull"], row["shields"] if row["has_shields"] else 0, label)
    return (label,)


class TargetListView(Panel):
    @property
    def name(self) -> str:
        return "target"

    def __init__(self):
        super().__init__()
        self._last_snapshot: Optional[tuple] = None
        # Sides whose rows are hidden. UNKNOWN (and anything else) always shows.
        self._hidden: set = set()
        self._sort = "name"

    def _snapshot(self):
        """Build a hashable snapshot of the rendered state."""
        import App
        from engine.units import GU_TO_KM
        hidden = tuple(s for s in FILTERABLE if s in self._hidden)
        target_menu = App.STTargetMenu_GetTargetMenu()
        if target_menu is None:
            return (self._visible, None, None, hidden, self._sort, ())
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
                # The menu's children ARE the frame's targetable contacts
                # (STTargetMenu._rows filters on Contact.targetable, which
                # already folds in cloak, death, the wreck-linger window and
                # IsTargetable). Do not re-derive any of that here.
                #
                # The player-identity guard stays: perceived_by never emits a
                # record for the observer, but STTargetMenu.RebuildShipMenus
                # (published Appc surface, bulk population from a SET) has no
                # observer and cannot make that call.
                #
                # NO `IsVisible()` HERE, DELIBERATELY: visibility is
                # pump-owned (set_contacts asserts SetVisible() on every
                # listed row); drawability is Contact.targetable. Pinned by
                # test_row_flag_does_not_gate_the_payload_drawability_is_targetable.
                aff = child.GetAffiliation()
                if ship is not None and ship is not player and aff not in self._hidden:
                    name = ship.GetName()
                    dist_km = (round(target_menu.surface_gu_to(ship, player) * GU_TO_KM, 2)
                               if player is not None else 0.0)
                    rows.append((
                        name,
                        child.GetCaption(),
                        aff,
                        _query_hull_percentage(ship),
                        _query_shield_percentage(ship),
                        _query_has_shields(ship),
                        dist_km,
                        _markers.marker_for(name),
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
        return (self._visible, selected, selected_subsystem, hidden,
                self._sort, tuple(rows))

    def render_payload(self) -> Optional[str]:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, selected, selected_subsystem, hidden, sort, rows = snapshot
        payload_rows = [
            {
                "name": name,
                "label": caption,
                "affiliation": aff,
                "hull": hull,
                "shields": shields,
                "has_shields": has_shields,
                "dist_km": dist_km,
                "marker": marker,
            }
            for (name, caption, aff, hull, shields, has_shields, dist_km,
                 marker) in rows
        ]
        payload_rows.sort(key=lambda r: sort_key(r, sort))
        payload = {
            "visible": visible,
            "selected": selected,
            "selected_subsystem": selected_subsystem,
            "filters": {s: s not in hidden for s in FILTERABLE},
            "sort": sort,
            "rows": payload_rows,
        }
        return "setTargetList(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        """Action format:
          - ``<ship>``                      — set target ship, clear sub lock
          - ``<ship>/<subsystem>``          — set target + subsystem
          - ``__filter__/<SIDE>``           — toggle a side's rows
          - ``__sort__/<name|distance|health>`` — set the sort
        """
        # List controls are pure UI state: handled before any SetTarget, and
        # without a player (a ship can never be named "__filter__").
        if action.startswith("__filter__/"):
            side = action[len("__filter__/"):]
            if side not in FILTERABLE:
                return False
            self._hidden.symmetric_difference_update({side})
            self.mark_due()
            return True
        if action.startswith("__sort__/"):
            sort = action[len("__sort__/"):]
            if sort not in SORTS:
                return False
            self._sort = sort
            self.mark_due()
            return True

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

        # Re-check subsystems_targetable at click time, not just at render
        # time. The clicked payload was rendered from a PRIOR frame's push;
        # if the ship finished cloaking in between, honouring the click
        # would set a subsystem lock the record no longer allows. Without
        # this the hole would self-heal one frame later via
        # reconcile_subsystem_lock (which the HOST LOOP runs every frame --
        # not this panel, which polls at 2 Hz), but there is no reason to let
        # even a one-frame flicker through when the record to check is one
        # call away.
        import App
        target_menu = App.STTargetMenu_GetTargetMenu()
        contact = target_menu.contact_for(target_ship) if target_menu is not None else None
        if contact is not None and not contact.subsystems_targetable:
            player.SetTargetSubsystem(None)
            return True

        sub = _resolve_subsystem_by_name(target_ship, suffix)
        # A non-targetable subsystem is a GROUP HEADER ("Warp Engines",
        # "Phasers", ...), drawn to organise the list but never lockable —
        # BC flags every aggregator SetTargetable(0). The JS gives a header
        # row the same click action as a lockable leaf, so the refusal is
        # enforced here; the click still retargets the ship.
        from engine.appc.target_menu import _is_targetable
        if sub is not None and not _is_targetable(sub):
            player.SetTargetSubsystem(None)
            return True
        player.SetTargetSubsystem(sub)
        return True

    @property
    def poll_interval_s(self) -> float:
        """Polled at 2 Hz, not per frame.

        The per-subsystem condition walk that once made this panel the
        costliest in the UI phase was removed when the subsystem tree moved to
        the target panel; the rows now carry only hull, shields and distance.

        2 Hz still fits the data: the shield percentages only CHANGE at 2 Hz
        (BC's 0.5 s shield charge tick, see subsystems.SHIELD_CHARGE_PERIOD_S),
        so polling faster re-reads the same value. Hull condition is
        event-driven and bursty, so a row can lag a hit by up to half a
        second -- accepted, and the reason this is a named constant rather
        than a magic number. The list also re-sorts live at this cadence
        (distance and health order follow the data), so a row can take up to
        half a second to move.

        Interaction is unaffected: selection changes go through dispatch_event
        and visibility flips through the visible setter, both of which mark the
        panel due for the next frame.
        """
        return TARGET_LIST_POLL_S

    def invalidate(self) -> None:
        """Force the next render_payload to re-emit."""
        super().invalidate()
        self._last_snapshot = None


def reconcile_subsystem_lock() -> None:
    """If the player's locked subsystem has been destroyed, hand the lock
    off to the next surviving sibling in its group; when the whole group is
    gone, clear the lock back to ship-level targeting. Runs every tick so a
    subsystem dying from any cause triggers the handoff.

    Also drops the lock outright — no handoff, straight to ship-level —
    when the locked ship has cloaked (`Contact.subsystems_targetable`
    False). A fuzzy sensor return has no subsystem to hand the lock off
    to; the player keeps the ship-level target, only the subsystem pick
    clears. Reads the pushed record rather than re-deriving cloak state,
    same reasoning as `_snapshot`'s subsystem suppression.

    And drops the lock when there is no ship-level target at all.
    `sensor_detection.clear_undetectable_player_lock` (a ship cloaking
    OUTSIDE its detection bubble is one way there) calls
    `player.SetTarget(None)`, but `ShipClass.SetTarget` never touches
    `_target_subsystem` — nothing does, there are only four clear sites
    and none of them covers this. Left alone, the stale subsystem
    reference survives with no ship attached and resurfaces as
    `selected_subsystem` the moment the player targets a DIFFERENT ship,
    since `GetTargetSubsystem()` answers unconditionally regardless of
    the current ship-level target. Pre-existing gap; closed here because
    this is the natural place, not because this branch introduced it."""
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    if player is None or not hasattr(player, "GetTargetSubsystem"):
        return
    locked = player.GetTargetSubsystem()
    if locked is None:
        return

    target = player.GetTarget()
    if target is None:
        player.SetTargetSubsystem(None)
        return

    import App
    target_menu = App.STTargetMenu_GetTargetMenu()
    contact = target_menu.contact_for(target) if target_menu is not None else None
    if contact is not None and not contact.subsystems_targetable:
        player.SetTargetSubsystem(None)
        return

    if not hasattr(locked, "IsDestroyed"):
        return
    try:
        destroyed = bool(locked.IsDestroyed())
    except Exception:
        return
    if not destroyed:
        return
    player.SetTargetSubsystem(_next_living_sibling(locked))
