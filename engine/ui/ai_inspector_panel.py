"""AI Inspector panel — dev-only live AI-tree inspector modal (Panel subclass).

Mirrors engine.ui.developer_options_panel / ship_property_viewer_panel: a
Panel pumped by PanelRegistry, opened from the dev pause menu, snapshot-diffing
its payload like the other panels. While open it pushes every live ship's
serialized AI subtree to the CEF ``setAIInspector`` renderer.

Registration into the pause menu is W4.T2; this module only builds the panel
class + collects state, so it must never be constructed at import time (only
instantiated under the developer flag).

Modeled on the original BC AIActiveLogView.py socket monitor.
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel
from engine.ui.ai_inspector_model import collect_all_ship_ai


class AIInspectorPanel(Panel):
    def __init__(self) -> None:
        super().__init__()
        self._visible = False
        # Seed the cache with the hide payload so a never-opened panel emits
        # nothing (only a real close, which sets _visible back to False after
        # an open, produces a fresh hide push).
        self._last_pushed: Optional[str] = (
            "setAIInspector(" + json.dumps({"visible": False}) + ");"
        )
        # UI-only open/collapse tracking; the JS owns expansion but we accept
        # the events so the registry routing has a handler.
        self._open_ids: set = set()

    @property
    def name(self) -> str:
        return "ai-inspector"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._last_pushed = None
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def render_payload(self) -> Optional[str]:
        if not self._visible:
            # Emit the hide payload exactly once after a close.
            hide = "setAIInspector(" + json.dumps({"visible": False}) + ");"
            if self._last_pushed == hide:
                return None
            self._last_pushed = hide
            return hide
        payload = {"visible": True, "ships": collect_all_ship_ai()}
        js = "setAIInspector(" + json.dumps(payload) + ");"
        if js == self._last_pushed:
            return None
        self._last_pushed = js
        return js

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action.startswith("expand:"):
            self._open_ids.add(action[len("expand:"):])
            return True
        if action.startswith("collapse:"):
            self._open_ids.discard(action[len("collapse:"):])
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()
