"""CrewMenuPanel — projects the STTopLevelMenu trees registered on
TacticalControlWindow into CEF, and routes clicks back as SDK events.

Outbound: walk TacticalControlWindow.GetMenuList() once per tick, snapshot
labels/flags/ids, diff, emit setCrewMenus(...). Inbound: resolve clicked id
to the live widget and fire its activation event.

Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.appc.characters import STButton, STMenu
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.appc.windows import TacticalControlWindow
from engine.ui.panel import Panel

_logger = logging.getLogger(__name__)


class CrewMenuPanel(Panel):
    def __init__(self):
        super().__init__()
        # Empty-state sentinel (matches SDKMirrorPanel): a quiescent panel
        # emits nothing on the first tick; invalidate() resets to None so
        # the empty state still fires once after a CEF page reload.
        self._last_pushed: Optional[str] = json.dumps({"menus": []})
        self._widgets_by_id: dict = {}
        self._logged_unrecognised: set = set()
        self._open_menu_id: Optional[int] = None
        # Inline accordion expand-state for submenu rows — Python-owned,
        # mirroring TargetListView's per-row `expanded` flag. Cleared
        # whenever the open menu changes (a reopened menu starts collapsed,
        # matching BC).
        self._expanded_ids: set[int] = set()

    @property
    def name(self) -> str:
        return "crew-menu"

    def render_payload(self) -> Optional[str]:
        self._widgets_by_id = {}
        menus = []
        for m in TacticalControlWindow.GetInstance().GetMenuList():
            node = self._snapshot_node(m)
            if node is not None:
                node["open"] = (node["id"] == self._open_menu_id)
                menus.append(node)
        payload = json.dumps({"menus": menus})
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setCrewMenus(" + payload + ");"

    def _snapshot_node(self, widget) -> Optional[dict]:
        if isinstance(widget, STMenu):
            node_type = "menu"
        elif isinstance(widget, STButton):
            node_type = "button"
        else:
            self._log_unrecognised_once(type(widget).__name__)
            return None
        wid = ensure_widget_id(widget)
        self._widgets_by_id[wid] = widget
        node = {
            "id": wid,
            "type": node_type,
            "label": widget.GetLabel(),
            "enabled": bool(widget.IsEnabled()),
            "visible": bool(widget.IsVisible()),
        }
        if isinstance(widget, STMenu):
            node["expanded"] = wid in self._expanded_ids
            children = [self._snapshot_node(c) for c in widget._children]
            node["children"] = [c for c in children if c is not None]
        return node

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("expand:"):
            try:
                wid = int(action[len("expand:"):])
            except ValueError:
                _logger.info("crew-menu: malformed expand action %r", action)
                return True
            widget = self._widgets_by_id.get(wid)
            if widget is None:
                _logger.info("crew-menu: stale expand id %d dropped", wid)
                return True
            if isinstance(widget, STMenu):
                if wid in self._expanded_ids:
                    self._expanded_ids.discard(wid)
                else:
                    self._expanded_ids.add(wid)
            return True
        if action.startswith("toggle:"):
            try:
                wid = int(action[len("toggle:"):])
            except ValueError:
                _logger.info("crew-menu: malformed toggle action %r", action)
                return True
            widget = self._widgets_by_id.get(wid)
            if widget is None:
                _logger.info("crew-menu: stale toggle id %d dropped", wid)
                return True
            self.toggle_menu(widget)
            return True
        if action.startswith("click:"):
            try:
                wid = int(action[len("click:"):])
            except ValueError:
                _logger.info("crew-menu: malformed click action %r", action)
                return True
            widget = self._widgets_by_id.get(wid)
            if widget is None:
                # Menu rebuilt between frames — drop; next snapshot repairs the UI.
                _logger.info("crew-menu: stale click id %d dropped", wid)
                return True
            if not widget.IsEnabled():
                return True
            root = self._root_of(wid)
            if isinstance(widget, STButton):
                # Original engine order: per-button activation event, then
                # ET_ST_BUTTON_CLICKED at the owning top-level menu (the SDK
                # registers BridgeMenus.ButtonClicked there for click sounds).
                widget.SendActivationEvent()
                if root is not None:
                    import App
                    clicked = App.TGEvent_Create()
                    clicked.SetEventType(App.ET_ST_BUTTON_CLICKED)
                    clicked.SetDestination(root)
                    clicked.SetSource(widget)
                    App.g_kEventManager.AddEvent(clicked)
                    self._acknowledge(root)
            # Menu nodes open/close client-side in CEF; no SDK event needed.
            return True
        return False

    def _menu_officer(self):
        """The CharacterClass owning the currently-open top-level menu, or None."""
        label = self.open_menu_label()
        if label is None:
            return None
        try:
            from engine.ui import crew_menu_hotkeys
            return crew_menu_hotkeys.resolve_character(label)
        except Exception:
            return None

    @staticmethod
    def _reconcile_turn(old, new) -> None:
        """Turn the officer losing focus back, and the one gaining focus toward
        the captain. old/new are CharacterClass or None; identical -> no-op."""
        if old is new:
            return
        if old is not None:
            try:
                old.MenuDown()
            except Exception:
                pass
        if new is not None:
            try:
                new.MenuUp()
            except Exception:
                pass

    def toggle_menu(self, menu) -> None:
        """Open `menu` (closing any other), or close it if already open.
        Single-open invariant shared by hotkeys and CEF title clicks.
        Disabled menus stay closed (stock BC) and non-menus are ignored
        (the JS only emits toggle: for top-level titles, but hotkey code
        may resolve unexpected objects)."""
        if not isinstance(menu, STMenu) or not menu.IsEnabled():
            return
        wid = ensure_widget_id(menu)
        old_officer = self._menu_officer()
        opening = self._open_menu_id != wid
        self._open_menu_id = None if self._open_menu_id == wid else wid
        # Open menu changed (toggle always closes or switches) — a reopened
        # menu starts with all submenus collapsed.
        self._expanded_ids.clear()
        self._reconcile_turn(old_officer, self._menu_officer())
        if opening:
            self._acknowledge(menu)

    def _acknowledge(self, menu) -> None:
        """Fire the owning officer's spoken acknowledgement. A resolution miss
        (unknown label / no bridge set) is a silent no-op — menu interaction
        must never break on a speech hiccup."""
        try:
            from engine.ui import crew_menu_hotkeys
            from engine.appc import crew_speech
            char = crew_menu_hotkeys.resolve_character(menu.GetLabel())
            crew_speech.acknowledge(char)
        except Exception:
            _logger.debug("crew-menu ack failed", exc_info=True)

    def open_menu_label(self) -> Optional[str]:
        """Label of the open top-level (station) menu, or None. The open id is
        always a top-level menu (toggle_menu only fires for titles), so its
        root is itself; the label feeds crew_menu_hotkeys.resolve_character."""
        if self._open_menu_id is None:
            return None
        root = self._root_of(self._open_menu_id)
        return root.GetLabel() if root is not None else None

    def has_open_menu(self) -> bool:
        return self._open_menu_id is not None

    def close_open_menu(self) -> bool:
        """Close any open menu; True if one was open (ESC consumes the
        press in that case — see host_loop's modal ladder)."""
        if self._open_menu_id is None:
            return False
        officer = self._menu_officer()
        self._open_menu_id = None
        self._expanded_ids.clear()
        if officer is not None:
            try:
                officer.MenuDown()
            except Exception:
                pass
        return True

    def invalidate(self) -> None:
        self._last_pushed = None
        # Mission swap rebuilds menus with fresh widget ids — a stale open
        # id would keep has_open_menu() True and swallow one ESC press.
        self._open_menu_id = None
        self._expanded_ids.clear()

    def _root_of(self, wid: int):
        """Top-level menu whose subtree contains the widget id, else None."""
        for menu in TacticalControlWindow.GetInstance().GetMenuList():
            if self._contains(menu, wid):
                return menu
        return None

    def _contains(self, widget, wid: int) -> bool:
        # __dict__ read — TGObject.__getattr__ stubs missing attributes.
        if widget.__dict__.get("_widget_id") == wid:
            return True
        if isinstance(widget, STMenu):
            return any(self._contains(c, wid) for c in widget._children)
        return False

    def _log_unrecognised_once(self, type_name: str) -> None:
        if type_name in self._logged_unrecognised:
            return
        self._logged_unrecognised.add(type_name)
        _logger.info("crew-menu: skipping unrecognised child type %s", type_name)
