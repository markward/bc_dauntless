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

    @property
    def name(self) -> str:
        return "crew-menu"

    def render_payload(self) -> Optional[str]:
        self._widgets_by_id = {}
        menus = [
            self._snapshot_node(m)
            for m in TacticalControlWindow.GetInstance().GetMenuList()
        ]
        payload = json.dumps({"menus": [m for m in menus if m is not None]})
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
            children = [self._snapshot_node(c) for c in widget._children]
            node["children"] = [c for c in children if c is not None]
        return node

    def dispatch_event(self, action: str) -> bool:
        if not action.startswith("click:"):
            return False
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
        # Menu nodes open/close client-side in CEF; no SDK event needed.
        return True

    def invalidate(self) -> None:
        self._last_pushed = None

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
