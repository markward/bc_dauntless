"""Quick Battle Setup panel — on-theme tabbed-modal SHELL.

T1 scope: header + a single "Ships" tab + Start/Close footer. NO ship data
yet — the body is a placeholder. Content (ship accordion, friend/enemy lists)
lands in a later task; this file establishes the Panel plumbing and the
event-routing seam.

Subclasses engine.ui.panel.Panel; pumped by PanelRegistry like the
configuration panel. Reuses the configuration panel's cp-* CSS chrome so the
look matches the rest of the UI — no new design tokens or fonts.

The boot path opens this panel instead of auto-starting the battle, so the
player lands on a config screen (and the SDK config button stays un-greyed
because StartSimulation -> DisableSimulationMenus no longer fires at boot).
"""
from __future__ import annotations

import json
from typing import Callable, List, Optional, Tuple

from engine.ui.panel import Panel


class QuickBattleSetupPanel(Panel):
    def __init__(self, on_start: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        # Single Ships tab for T1; later tasks add more (e.g. a Player tab).
        self._tabs: List[Tuple[str, str]] = [("ships", "Ships")]
        self._selected_tab = "ships"
        # Start wiring is a later task — keep a clear seam. When unset, Start
        # is still "handled" (returns True) but does nothing.
        self._on_start = on_start
        self._visible = False
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "quick-battle-setup"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible, tuple(self._tabs), self._selected_tab)
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setQuickBattleSetup(" + json.dumps({"open": False}) + ");"
        payload = {
            "open": True,
            "selected_tab": self._selected_tab,
            "tabs": [{"id": tid, "label": label} for tid, label in self._tabs],
        }
        return "setQuickBattleSetup(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "close":
            self.close()
            return True
        if action == "start":
            # Real Start wiring (reconcile with start_quickbattle) is a later
            # task. The seam is the on_start callback; absence is a no-op.
            if self._on_start is not None:
                self._on_start()
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
