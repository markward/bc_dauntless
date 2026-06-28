"""Quick Battle Setup panel — on-theme tabbed modal.

Reads the live SDK QuickBattle config widgets (built by BuildDialog) and
projects them into the CEF panel: an expandable ship-category accordion plus
the Friendly/Enemy ship lists. Reuses the configuration panel's cp-* chrome and
the crew-menu accordion styling — no new design tokens or fonts.

The boot path opens this panel instead of auto-starting the battle, so the
player lands on a config screen (and the SDK config button stays un-greyed
because StartSimulation -> DisableSimulationMenus no longer fires at boot).

The panel only READS the SDK widgets here; routing a click back to the SDK
(SendActivationEvent) is a later task. A stable widget-id map (widget_for_id)
is maintained so that task can resolve a clicked id to its live widget.

Subclasses engine.ui.panel.Panel; pumped by PanelRegistry like the
configuration panel.
"""
from __future__ import annotations

import json
from typing import Callable, Dict, Optional, Set

from engine.ui.panel import Panel


class QuickBattleSetupPanel(Panel):
    # Sentinel: _qb_module not yet resolved. Distinct from None (which means
    # "no QuickBattle module" — render empty lists).
    _UNSET = object()

    def __init__(self, on_start: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        # Start wiring is a later task — keep a clear seam. When unset, Start
        # is still "handled" (returns True) but does nothing.
        self._on_start = on_start
        self._visible = False
        self._last_pushed: Optional[str] = None
        # Category widget ids that are currently expanded (default collapsed).
        self._expanded_ids: Set[int] = set()
        # The ship row the player last clicked (highlighted in the accordion).
        self._selected_ship_id: Optional[int] = None
        # Rebuilt each render: snapshot-node id -> live SDK widget.
        self._id_to_widget: Dict[int, object] = {}
        # The QuickBattle script module (source of g_pShipsPane / g_pFriendMenu
        # / g_pEnemyMenu). Resolved lazily; tests inject a stub or None.
        self._qb_module = self._UNSET

    @property
    def name(self) -> str:
        return "quick-battle-setup"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._visible = True

    def close(self) -> None:
        self._visible = False

    # ── SDK widget reading ────────────────────────────────────────────────────

    def _qb(self):
        """Resolve the QuickBattle module (cached). _UNSET -> import attempt
        (None on failure); an injected stub/None is returned as-is."""
        m = self._qb_module
        if m is self._UNSET:
            try:
                import importlib
                m = importlib.import_module("QuickBattle.QuickBattle")
            except Exception:
                m = None
            self._qb_module = m
        return m

    @staticmethod
    def _child_widgets(node) -> list:
        """Direct child widgets of any container, normalising the three
        storage conventions: TGPane/STSubPane store (child, x, y) tuples;
        _STStylizedWindow and STMenu store bare widgets. All use _children."""
        if node is None:
            return []
        kids = node.__dict__.get("_children")
        if not kids:
            return []
        return [k[0] if isinstance(k, tuple) else k for k in kids]

    def _collect_categories(self, root) -> list:
        """DFS the pane subtree for STCharacterMenu nodes (the ship-category
        menus), in tree order. Their button children are the ships."""
        from engine.appc.tg_ui.st_widgets import STCharacterMenu
        cats: list = []

        def dfs(node) -> None:
            for child in self._child_widgets(node):
                if isinstance(child, STCharacterMenu):
                    cats.append(child)
                else:
                    dfs(child)

        dfs(root)
        return cats

    def _read_pane_categories(self, pane, ship_extra):
        """Walk a ship-menu pane (g_pShipsPane / g_pPlayerPane) into a list of
        {id, label, expanded, ships:[{id, label, enabled, **extra}]} and register
        the id->widget map. `ship_extra(sid, btn)` adds per-ship flags (e.g.
        'selected' for the enemy catalog, 'current' for the player ship)."""
        from engine.appc.characters import STButton
        from engine.appc.tg_ui.widgets import ensure_widget_id
        categories: list = []
        for cat in self._collect_categories(pane):
            cid = ensure_widget_id(cat)
            self._id_to_widget[cid] = cat
            ships = []
            for btn in self._child_widgets(cat):
                if isinstance(btn, STButton):
                    sid = ensure_widget_id(btn)
                    self._id_to_widget[sid] = btn
                    ship = {
                        "id": sid,
                        "label": btn.GetLabel(),
                        "enabled": bool(btn.IsEnabled()),
                    }
                    ship.update(ship_extra(sid, btn))
                    ships.append(ship)
            categories.append({
                "id": cid,
                "label": cat.GetLabel(),
                "expanded": cid in self._expanded_ids,
                "ships": ships,
            })
        return categories

    def _read_ships(self):
        """Walk the live QuickBattle widgets and return
        (categories, friendly, enemy, player_ship_name), rebuilding the
        id->widget map. The single Ships catalog feeds all three assignments
        (friendly/enemy/player); the player ship is the singular g_sPlayerType
        name. Friendly/enemy rosters are stacked by ship label into
        [{label, count}] (shopping-basket tally). Empty/None (never raises)
        when the module/globals are absent."""
        self._id_to_widget = {}

        m = self._qb()
        if m is None:
            return [], [], [], None

        # The one ship catalog (Ships pane); highlight the clicked ship.
        categories = self._read_pane_categories(
            getattr(m, "g_pShipsPane", None),
            lambda sid, btn: {"selected": sid == self._selected_ship_id},
        )

        friendly = self._read_roster(getattr(m, "g_pFriendMenu", None))
        enemy = self._read_roster(getattr(m, "g_pEnemyMenu", None))

        # The current player ship (singular). g_sPlayerType is the ship NAME.
        player_ship_name = getattr(m, "g_sPlayerType", None)
        return categories, friendly, enemy, player_ship_name

    def _read_roster(self, pane) -> list:
        """Walk a roster pane's STButton children and stack identical ships by
        label into [{label, count}], preserving first-seen order. Roster
        mutations re-walk the live pane by label, so no id is emitted here."""
        from engine.appc.characters import STButton
        order: list = []
        counts: Dict[str, int] = {}
        for btn in self._child_widgets(pane):
            if isinstance(btn, STButton):
                label = btn.GetLabel()
                if label not in counts:
                    counts[label] = 0
                    order.append(label)
                counts[label] += 1
        return [{"label": label, "count": counts[label]} for label in order]

    def _has_roster_ships(self) -> bool:
        """True if either roster pane currently holds at least one ship button.
        Walks the live SDK menus so it reflects the latest add/remove (never
        raises; False when the module/menus are absent)."""
        from engine.appc.characters import STButton
        m = self._qb()
        if m is None:
            return False
        for name in ("g_pFriendMenu", "g_pEnemyMenu"):
            for btn in self._child_widgets(getattr(m, name, None)):
                if isinstance(btn, STButton):
                    return True
        return False

    def widget_for_id(self, wid):
        """Resolve a snapshot-node id back to its live SDK widget (or None)."""
        try:
            return self._id_to_widget.get(int(wid))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _activate_widget(widget) -> None:
        """Fire a widget's SDK activation event (best-effort, never raises)."""
        if widget is not None and hasattr(widget, "SendActivationEvent"):
            try:
                widget.SendActivationEvent()
            except Exception:
                pass

    def _activate_qb_button(self, global_name: str) -> None:
        """Activate a QuickBattle module-global button (e.g. g_pAddEnemyButton)."""
        m = self._qb()
        self._activate_widget(getattr(m, global_name, None) if m is not None else None)

    # ── Roster mutation (stacked friendly/enemy lists) ────────────────────────

    # side -> (roster-menu global, add-button global, type->details table global)
    _ROSTER_SIDES = {
        "friendly": ("g_pFriendMenu", "g_pAddFriendButton", "g_dFriendlyShipTypeToDetails"),
        "enemy": ("g_pEnemyMenu", "g_pAddEnemyButton", "g_dEnemyShipTypeToDetails"),
    }

    def _first_roster_button(self, side: str, label: str):
        """First live roster button on `side` whose GetLabel() == label (or None).
        Re-walks the live SDK pane so it survives RebuildMenu's KillChildren."""
        from engine.appc.characters import STButton
        m = self._qb()
        spec = self._ROSTER_SIDES.get(side)
        if m is None or spec is None:
            return None
        for btn in self._child_widgets(getattr(m, spec[0], None)):
            if isinstance(btn, STButton) and btn.GetLabel() == label:
                return btn
        return None

    def _label_to_type(self, side: str, label: str):
        """Reverse-map a roster label to its ship-type int via the side's
        type->details table (details[1] is the GetString key for the label).
        Returns None when the module/table is absent or no entry matches."""
        m = self._qb()
        spec = self._ROSTER_SIDES.get(side)
        if m is None or spec is None:
            return None
        details = getattr(m, spec[2], None)
        db = getattr(m, "g_pMissionDatabase", None)
        if details is None:
            return None
        try:
            for type_int, data in details.items():
                key = data[1]
                resolved = db.GetString(key) if db is not None else key
                if resolved == label:
                    return type_int
        except Exception:
            return None
        return None

    def _roster_add_one(self, side: str, label: str) -> None:
        """Add one more ship of `label` to `side` via the SDK add path: set
        g_iSelectedShipType to the resolved type, then activate the add button
        (AddShipAsFriend/Enemy). No-op when the type can't be resolved."""
        m = self._qb()
        spec = self._ROSTER_SIDES.get(side)
        if m is None or spec is None:
            return
        type_int = self._label_to_type(side, label)
        if type_int is None:
            return
        try:
            m.g_iSelectedShipType = type_int
        except Exception:
            return
        self._activate_qb_button(spec[1])

    def _roster_remove_one(self, side: str, label: str) -> bool:
        """Remove one ship of `label` from `side`: select its first live roster
        button (ET_SELECT_FRIEND/ENEMY), then activate g_pDeleteButton (Delete).
        Returns True if a matching button was found and removal was driven."""
        btn = self._first_roster_button(side, label)
        if btn is None:
            return False
        self._activate_widget(btn)
        self._activate_qb_button("g_pDeleteButton")
        return True

    def _roster_remove_all(self, side: str, label: str) -> None:
        """Remove every ship of `label` from `side`. Re-walks the live pane each
        pass (Delete -> RebuildMenu KillChildren invalidates prior refs);
        bounded by the current count so a stuck removal can't loop forever."""
        m = self._qb()
        spec = self._ROSTER_SIDES.get(side)
        if m is None or spec is None:
            return
        from engine.appc.characters import STButton
        bound = sum(
            1 for btn in self._child_widgets(getattr(m, spec[0], None))
            if isinstance(btn, STButton) and btn.GetLabel() == label
        )
        for _ in range(bound):
            if not self._roster_remove_one(side, label):
                break

    def _set_player_from_selection(self) -> None:
        """Set the player ship to the currently-selected catalog ship.

        g_iSelectedShipType is the ship-type int set by SelectShipType when the
        ship was clicked. g_dFriendlyShipTypeToDetails[int][0] is the ship NAME
        (exactly what SelectPlayerShip assigns to g_sPlayerType). No-op when
        nothing is selected or the ship isn't flyable (not in the friendly
        table — e.g. a starbase). Swaps live in combat via RecreatePlayer."""
        m = self._qb()
        if m is None:
            return
        sel = getattr(m, "g_iSelectedShipType", None)
        details = getattr(m, "g_dFriendlyShipTypeToDetails", None)
        try:
            if details is None or sel not in details:
                return
            m.g_sPlayerType = details[sel][0]
        except Exception:
            return
        self._recreate_player_if_in_sim()

    def _recreate_player_if_in_sim(self) -> None:
        """If combat is active (bInSimulation), call the SDK's RecreatePlayer to
        swap the player ship live to the just-selected g_sPlayerType. No-op out
        of combat (the type is just staged for the next Start). Best-effort."""
        m = self._qb()
        if m is None or not getattr(m, "bInSimulation", 0):
            return
        try:
            m.RecreatePlayer()
        except Exception:
            pass

    def _fire_close_dialog(self) -> None:
        """Post ET_CLOSE_DIALOG to g_pXO so the SDK closes the config dialog:
        clears g_bDialogUp (which _sync_quick_battle_panel mirrors to hide this
        panel) and re-enables the XO config button so it can reopen. Best-effort."""
        m = self._qb()
        if m is None:
            return
        et = getattr(m, "ET_CLOSE_DIALOG", None)
        xo = getattr(m, "g_pXO", None)
        if et is None or xo is None:
            return
        try:
            import App
            evt = App.TGEvent_Create()
            evt.SetEventType(et)
            evt.SetDestination(xo)
            App.g_kEventManager.AddEvent(evt)
        except Exception:
            pass

    # ── Render / dispatch ─────────────────────────────────────────────────────

    def render_payload(self) -> Optional[str]:
        if not self._visible:
            payload = {"open": False}
        else:
            categories, friendly, enemy, player_ship = self._read_ships()
            payload = {
                "open": True,
                "categories": categories,
                "friendly": friendly,
                "enemy": enemy,
                "player_ship": player_ship,   # current player ship NAME (or null)
                # Start is disabled until at least one ship is on a roster
                # (mirrors the SDK enabling Start once g_kFriend/EnemyList fills).
                "can_start": bool(friendly or enemy),
            }
        out = "setQuickBattleSetup(" + json.dumps(payload) + ");"
        if out == self._last_pushed:
            return None
        self._last_pushed = out
        return out

    def dispatch_event(self, action: str) -> bool:
        if action == "close":
            # Faithful close: ET_CLOSE_DIALOG clears g_bDialogUp + re-enables the
            # XO config button. _sync_quick_battle_panel then hides this panel.
            self._fire_close_dialog()
            self.close()
            return True
        if action == "start":
            # Start drives the real flow via the on_start seam (the host wires
            # it to start_quickbattle -> ET_START_SIMULATION); close the dialog
            # first so g_bDialogUp clears and the panel doesn't reopen. With no
            # callback wired it stays a handled no-op. Defensively gated on a
            # non-empty roster (the JS also disables the button) so an empty
            # battle can't be launched.
            if self._on_start is not None and self._has_roster_ships():
                self._fire_close_dialog()
                self._on_start()
                self.close()
            return True
        if action == "add-friend":
            self._activate_qb_button("g_pAddFriendButton")
            return True
        if action == "add-enemy":
            self._activate_qb_button("g_pAddEnemyButton")
            return True
        if action == "set-player":
            # Assign the currently-selected catalog ship as the player ship.
            # SelectShipType already set g_iSelectedShipType (the ship-type int)
            # when the ship was clicked — the same int Add As Enemy/Friend use.
            # Set g_sPlayerType from it (as SelectPlayerShip does), then swap live
            # in combat. No-op for a non-flyable selection (e.g. a starbase isn't
            # in the friendly table) or no selection.
            self._set_player_from_selection()
            return True
        if action.startswith("expand:"):
            try:
                wid = int(action[len("expand:"):])
            except ValueError:
                return False
            self._expanded_ids.discard(wid) if wid in self._expanded_ids \
                else self._expanded_ids.add(wid)
            return True
        if action.startswith("click-ship:"):
            # Fire the ship button's SDK event (ET_SELECT_SHIP_TYPE -> the
            # mission's SelectShipType handler) so the SDK tracks the selection
            # that Add As Friendly/Enemy then acts on, and record it so the
            # accordion highlights the clicked row.
            raw = action[len("click-ship:"):]
            self._activate_widget(self.widget_for_id(raw))
            try:
                self._selected_ship_id = int(raw)
            except ValueError:
                pass
            return True
        if action.startswith("roster-inc:"):
            side, label = self._parse_roster_action(action[len("roster-inc:"):])
            if side is None:
                return False
            self._roster_add_one(side, label)
            return True
        if action.startswith("roster-dec:"):
            side, label = self._parse_roster_action(action[len("roster-dec:"):])
            if side is None:
                return False
            self._roster_remove_one(side, label)
            return True
        if action.startswith("roster-remove:"):
            side, label = self._parse_roster_action(action[len("roster-remove:"):])
            if side is None:
                return False
            self._roster_remove_all(side, label)
            return True
        return False

    @staticmethod
    def _parse_roster_action(arg: str):
        """Split a 'roster-*' arg of the form '<side>:<url-encoded-label>' into
        (side, label). Returns (None, '') for an unknown side or malformed arg
        so dispatch_event can reject it."""
        from urllib.parse import unquote
        side, sep, raw = arg.partition(":")
        if not sep or side not in QuickBattleSetupPanel._ROSTER_SIDES:
            return None, ""
        return side, unquote(raw)

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()
