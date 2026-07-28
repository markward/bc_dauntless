"""CEF view for the tactical Orders/Tactics/Maneuvers command panes.

Projects the three SDK widgets built by Bridge.TacticalMenuHandlers
(CreateOrdersStatusDisplay): g_pOrdersStatusUIPane (the TGPane the order
buttons are actually AddChild'd onto — NOT the g_pOrdersStatusUI
STStylizedWindow container around it, which stays permanently childless
under our STStylizedWindow_CreateW shim), g_pTacticsStatusUIMenu,
g_pManeuversStatusUIMenu. Reads label/chosen/enabled per button each tick and
emits setTacticalOrders({...}); a click resolves the matching SDK button
WITHIN its own group (row ids are group-qualified — BC's localized labels
collide across groups, e.g. "At Will" for both TacticAtWill and
ManeuverAtWill) and calls SendActivationEvent(), which fires the SDK's own
ET_MANEUVER event.

Availability (which tactics/maneuvers are enabled) is computed by the SDK's
UpdateOrderMenus from the g_dAIs table and reflected in each button's
IsDisabled()/IsChosen() — we only read it.

Sub-step 3a (widget-construction probe) found g_pTacticsStatusUIMenu /
g_pManeuversStatusUIMenu (STCharacterMenu instances) had no
GetFirstChild/GetNextChild override, so SDK code (and this panel) walking
their children via TGObject.__getattr__'s truthy _Stub never terminated.
Fixed at the widget layer: engine/appc/tg_ui/st_widgets.py's
STCharacterMenu now has real sibling traversal, mirroring
engine/appc/target_menu.py's STTargetMenu.

Spec:  docs/superpowers/specs/2026-07-28-bridge-tactical-mode-f2-hud-design.md
Plan:  docs/superpowers/plans/2026-07-28-bridge-tactical-mode.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel


class TacticalOrdersPanel(Panel):
    @property
    def name(self) -> str:
        return "tactical-orders"

    def __init__(self):
        super().__init__()
        self._last_snapshot: Optional[tuple] = None

    def _resolve_panes(self):
        """Return (orders_pane, tactics_pane, maneuvers_pane), any of which
        may be None before a bridge load. Overridden in tests.

        Orders reads g_pOrdersStatusUIPane (the TGPane the order buttons are
        actually AddChild'd onto — SDK Bridge/TacticalMenuHandlers.py:591,
        609/611), NOT g_pOrdersStatusUI (the STStylizedWindow *container*
        around that pane). The SDK's own UpdateOrderMenus walks
        g_pOrdersStatusUIPane.GetFirstChild()/GetNextChild() (lines
        1507-1510, 1581-1600) for exactly this reason — our
        STStylizedWindow_CreateW (engine/appc/windows.py) discards the pane
        arg, so g_pOrdersStatusUI._children is permanently empty. Reading
        the wrong global here shipped the Orders group empty (fixed after
        code review — tests/unit/test_tactical_orders_panel.py's
        test_resolve_panes_reads_orders_status_ui_pane covers it).
        """
        try:
            import Bridge.TacticalMenuHandlers as T
        except Exception:
            return (None, None, None)
        return (getattr(T, "g_pOrdersStatusUIPane", None),
                getattr(T, "g_pTacticsStatusUIMenu", None),
                getattr(T, "g_pManeuversStatusUIMenu", None))

    @staticmethod
    def _iter_buttons(pane):
        """Yield the clickable child buttons of a pane, tolerant of the
        widget surface. Prefers a helper _iter_buttons (test fakes / future
        widget), else walks GetFirstChild/GetNextChild."""
        if pane is None:
            return []
        if hasattr(pane, "_iter_buttons"):
            return list(pane._iter_buttons())
        out = []
        if hasattr(pane, "GetFirstChild"):
            child = pane.GetFirstChild()
            while child is not None:
                out.append(child)
                child = pane.GetNextChild(child)
        return out

    @staticmethod
    def _row(button, group: str) -> dict:
        # id is group-qualified ("orders:<label>") because BC's own
        # localized labels collide across groups — e.g. TacticAtWill and
        # ManeuverAtWill both localize to "At Will" (data/TGL/Bridge
        # Menus.tgl). An unqualified id made dispatch_event's first-match
        # search (orders -> tactics -> maneuvers) activate the wrong
        # button's SDK action for every such collision (fixed after code
        # review; see test_maneuver_atwill_activates_maneuvers_not_tactics).
        label = button.GetLabel() if hasattr(button, "GetLabel") else ""
        chosen = bool(button.IsChosen()) if hasattr(button, "IsChosen") else False
        if hasattr(button, "IsDisabled"):
            enabled = not bool(button.IsDisabled())
        elif hasattr(button, "IsEnabled"):
            enabled = bool(button.IsEnabled())
        else:
            enabled = True
        return {"label": label, "id": group + ":" + label,
                "chosen": chosen, "enabled": enabled}

    def _build(self):
        """Read the three panes and return {orders, tactics, maneuvers} row
        lists (each row a dict). Single source of the projected model."""
        orders_pane, tactics_pane, maneuvers_pane = self._resolve_panes()
        return {
            "orders": [self._row(b, "orders") for b in self._iter_buttons(orders_pane)],
            "tactics": [self._row(b, "tactics") for b in self._iter_buttons(tactics_pane)],
            "maneuvers": [self._row(b, "maneuvers") for b in self._iter_buttons(maneuvers_pane)],
        }

    @staticmethod
    def _key(visible, groups):
        """Hashable snapshot key derived from the built model."""
        return (visible, tuple(
            (g, tuple(tuple(sorted(r.items())) for r in groups[g]))
            for g in ("orders", "tactics", "maneuvers")))

    def render_payload(self) -> Optional[str]:
        groups = self._build()
        key = self._key(self._visible, groups)
        if key == self._last_snapshot:
            return None
        self._last_snapshot = key
        payload = {"visible": self._visible, **groups}
        return "setTacticalOrders(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if not action.startswith("click:"):
            return False
        row_id = action[len("click:"):]
        group, sep, label = row_id.partition(":")
        if not sep:
            return False
        orders_pane, tactics_pane, maneuvers_pane = self._resolve_panes()
        pane = {"orders": orders_pane, "tactics": tactics_pane,
                "maneuvers": maneuvers_pane}.get(group)
        if pane is None:
            return False
        # Resolve WITHIN the matching group only — labels can collide across
        # groups (e.g. "At Will" for both TacticAtWill and ManeuverAtWill),
        # and each group's SDK button fires a different ET_MANEUVER subtype.
        for button in self._iter_buttons(pane):
            if hasattr(button, "GetLabel") and button.GetLabel() == label:
                if hasattr(button, "SendActivationEvent"):
                    button.SendActivationEvent()
                return True
        return False

    def invalidate(self) -> None:
        self._last_snapshot = None
