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
        # Shields read down while the ship is fading in/out (they don't block —
        # see combat.cloak_shields_suspended); the charge is preserved for after.
        from engine.appc.combat import cloak_shields_suspended
        if cloak_shields_suspended(ship):
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


# How often the target list is polled. See TargetListView.poll_interval_s.
TARGET_LIST_POLL_S = 0.5


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

        rows = []
        child = target_menu.GetFirstChild()
        while child is not None:
            if isinstance(child, STSubsystemMenu):
                ship = child.GetShip()
                # The menu's children ARE the frame's targetable contacts
                # (STTargetMenu._rows filters on Contact.targetable, which
                # already folds in cloak, death, the wreck-linger window and
                # IsTargetable). This used to re-run is_hidden_by_cloak and
                # _out_of_action here on top of that — a second copy of the
                # rule that could disagree with the record, which is exactly
                # what got engine.ui.target_list_visibility retired.
                #
                # The player-identity guard stays: perceived_by never emits a
                # record for the observer, but STTargetMenu.RebuildShipMenus
                # (published Appc surface, bulk population from a SET) has no
                # observer and cannot make that call.
                if ship is not None and ship is not player:
                    hull_pct = _query_hull_percentage(ship)
                    shield_pct = _query_shield_percentage(ship)
                    has_shields = _query_has_shields(ship)
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

                    # A cloaked contact is a fuzzy sensor return: targetable
                    # at ship level, but its subsystem tree is suppressed
                    # here at the VIEW layer only. `child._children` (the
                    # cached STMenu subsystem rows in STTargetMenu._row_cache)
                    # is deliberately left untouched — it is reused across
                    # frames and across a contact leaving/re-entering the
                    # list, so rebuilding or mutating it here would corrupt
                    # that cache for every other reader. Read from the
                    # pushed Contact record (the frame's own answer), not a
                    # second cloak check.
                    contact = target_menu.contact_for(ship)
                    subsystems_targetable = (
                        contact is None or contact.subsystems_targetable)
                    name = ship.GetName()
                    row_expanded = name in self._expanded_ships
                    # COLLAPSED ROWS DO NOT BUILD THEIR SUBSYSTEM TREE.
                    #
                    # The tree is only ever DISPLAYED for an expanded row (see
                    # target_list.js: child rows are emitted inside
                    # `if (expanded)`). All a collapsed row needs is whether the
                    # list is non-empty, which decides the expand caret.
                    #
                    # Building it anyway walked every contact x every subsystem
                    # x every child subsystem, ~2-3 condition queries per
                    # grandchild, purely to produce a tuple that was compared
                    # and thrown away. At 100 contacts that made ui.target
                    # 84 ms -- the largest single non-sim item in the frame,
                    # bigger than any sim phase.
                    #
                    # `any(...)` short-circuits on the first surviving group, so
                    # a collapsed row costs one _keep instead of all of them.
                    #
                    # Dropping the conditions from a collapsed row's snapshot
                    # also makes change detection LESS twitchy in the right
                    # direction: damage to a subsystem nobody has expanded no
                    # longer forces a redraw of the whole list. A change that IS
                    # visible -- the last subsystem dying, so the caret goes --
                    # still flips has_subsystems and redraws.
                    if not subsystems_targetable:
                        subsystems = ()
                        has_subsystems = False
                    elif row_expanded:
                        subsystems = tuple(
                            _sub_entry(sub_child)
                            for sub_child in child._children
                            if _keep(sub_child)
                        )
                        has_subsystems = bool(subsystems)
                    else:
                        subsystems = ()
                        has_subsystems = any(
                            _keep(sub_child) for sub_child in child._children)
                    # NO `IsVisible()` HERE, DELIBERATELY — do not re-add it.
                    # VISIBILITY IS PUMP-OWNED: `STTargetMenu.set_contacts`
                    # asserts `SetVisible()` on every listed row
                    # unconditionally, every frame, so the flag carries no
                    # information this panel wants. Drawability is
                    # `Contact.targetable`, which the projection (`_rows`) has
                    # already applied by the time we walk the children.
                    #
                    # The filter that used to be here was not merely redundant,
                    # it was WRONG in the one window where the flag and the
                    # projection can disagree: an SDK caller clearing a row via
                    # `SetNotVisible` (real surface — CycleTarget reads it)
                    # would blank a live contact from the panel until the next
                    # push re-asserted it. Pinned by
                    # tests/unit/test_target_list_view.py::
                    # test_row_flag_does_not_gate_the_payload_drawability_is_targetable.
                    rows.append((
                        name,
                        child.GetAffiliation(),
                        hull_pct,
                        shield_pct,
                        has_shields,
                        subsystems,
                        row_expanded,
                        has_subsystems,
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
                    "has_shields": has_shields,
                    "subsystems": [
                        {"name": s_name, "condition": s_cond,
                         "expanded": s_expanded,
                         "children": [{"name": c_name, "condition": c_cond}
                                      for (c_name, c_cond) in s_kids]}
                        for (s_name, s_cond, s_kids, s_expanded) in subs
                    ],
                    "expanded": expanded,
                    # Collapsed rows ship an empty `subsystems`, so the caret
                    # cannot be derived from its length any more.
                    "has_subsystems": has_subs,
                }
                for (name, aff, hull, shields, has_shields, subs, expanded,
                     has_subs) in rows
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

        # Re-check subsystems_targetable at click time, not just at render
        # time. The clicked payload was rendered from a PRIOR frame's push;
        # if the ship finished cloaking in between, honouring the click
        # would set a subsystem lock the record no longer allows. Without
        # this the hole would self-heal one frame later via
        # _reconcile_subsystem_lock (which runs first thing in the next
        # render_payload), but there is no reason to let even a one-frame
        # flicker through when the record to check is one call away.
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

        This panel's _snapshot walks every contact x every subsystem x every
        child subsystem, querying condition on each, purely to compare against
        last frame's tuple. Measured at 33 contacts it is 26.0 ms of a 26.7 ms
        UI phase -- 97.5% of all panel cost, and every other panel returns in
        ~10 us.

        2 Hz is matched to the data, not just cheaper: the shield percentages
        it displays only CHANGE at 2 Hz (BC's 0.5 s shield charge tick, see
        subsystems.SHIELD_CHARGE_PERIOD_S), so polling at 60 Hz read the same
        value thirty times over. Hull condition is event-driven and bursty, so
        a row can lag a hit by up to half a second -- accepted, and the reason
        this is a named constant rather than a magic number.

        Interaction is unaffected: selection changes go through dispatch_event
        and visibility flips through the visible setter, both of which mark the
        panel due for the next frame.
        """
        return TARGET_LIST_POLL_S

    def invalidate(self) -> None:
        """Force the next render_payload to re-emit."""
        super().invalidate()
        self._last_snapshot = None
