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
from typing import Callable, Dict, List, Optional, Set, Tuple

from engine.ui.panel import Panel


class QuickBattleSetupPanel(Panel):
    # Sentinel: _qb_module not yet resolved. Distinct from None (which means
    # "no QuickBattle module" — render empty lists).
    _UNSET = object()

    def __init__(self, on_start: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        # Single Ships tab for the first pass; later tasks add more.
        self._tabs: List[Tuple[str, str]] = [("ships", "Ships")]
        self._selected_tab = "ships"
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
        (categories, friendly, enemy, player_ship), rebuilding the id->widget
        map. Empty lists (never raises) when the module/globals are absent."""
        from engine.appc.characters import STButton
        from engine.appc.tg_ui.widgets import ensure_widget_id

        self._id_to_widget = {}
        friendly: list = []
        enemy: list = []

        m = self._qb()
        if m is None:
            return [], friendly, enemy, []

        # Enemy/friendly catalog (Ships pane): highlight the clicked ship.
        categories = self._read_pane_categories(
            getattr(m, "g_pShipsPane", None),
            lambda sid, btn: {"selected": sid == self._selected_ship_id},
        )
        # Player-ship catalog (Player pane): highlight the current player ship
        # (g_sPlayerType is the ship-name string; player buttons label == name).
        current = getattr(m, "g_sPlayerType", None)
        player_ship = self._read_pane_categories(
            getattr(m, "g_pPlayerPane", None),
            lambda sid, btn: {"current": btn.GetLabel() == current},
        )

        for pane, out in ((getattr(m, "g_pFriendMenu", None), friendly),
                          (getattr(m, "g_pEnemyMenu", None), enemy)):
            for btn in self._child_widgets(pane):
                if isinstance(btn, STButton):
                    bid = ensure_widget_id(btn)
                    self._id_to_widget[bid] = btn
                    out.append({"id": bid, "label": btn.GetLabel()})

        return categories, friendly, enemy, player_ship

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
                "selected_tab": self._selected_tab,
                "tabs": [{"id": tid, "label": label} for tid, label in self._tabs],
                "categories": categories,
                "friendly": friendly,
                "enemy": enemy,
                "player_ship": player_ship,
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
            # callback wired it stays a handled no-op.
            if self._on_start is not None:
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
        if action.startswith("select-player-ship:"):
            # Fire the player-ship button (ET_SELECT_PLAYER_SHIP_TYPE ->
            # SelectPlayerShip sets g_sPlayerType). In combat, swap the player
            # ship live via the SDK's own RecreatePlayer; out of combat it just
            # sets the type for the next Start (stock behaviour). The host's
            # reconciliation realizes the new ship + retargets the camera.
            raw = action[len("select-player-ship:"):]
            self._activate_widget(self.widget_for_id(raw))
            self._recreate_player_if_in_sim()
            return True
        if action.startswith("tab:"):
            tab_id = action[len("tab:"):]
            if any(tid == tab_id for tid, _ in self._tabs):
                self._selected_tab = tab_id
                return True
            return False
        return False

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()
