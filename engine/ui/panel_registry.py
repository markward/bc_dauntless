"""Coordinates CEF-rendered panels — render pump + event dispatch.

The host loop owns one PanelRegistry instance. Each tick:
  scripts = registry.render_all()
  for s in scripts: _h.cef_execute_javascript(s)

The registry's dispatch() is wired as the single CEF event handler;
slash-prefixed events route to the matching panel (`target/USS X` ->
panel "target", action "USS X"), unprefixed events fall through to the
optional legacy handler (used for the pre-framework pause menu).
"""
from __future__ import annotations

from typing import Callable, List, Optional

from engine.ui.panel import Panel


class PanelRegistry:
    def __init__(self, legacy_handler: Optional[Callable[[str], None]] = None):
        self._panels: List[Panel] = []
        self._legacy = legacy_handler

    def register(self, panel: Panel) -> None:
        if any(p.name == panel.name for p in self._panels):
            raise ValueError("duplicate panel name: " + panel.name)
        self._panels.append(panel)

    def render_all(self) -> List[str]:
        out: List[str] = []
        for p in self._panels:
            payload = p.render_payload()
            if payload is not None:
                out.append(payload)
        return out

    def dispatch(self, event_name: str) -> bool:
        """Route a JS event to the right panel.

        Slash-prefixed: ``"target/USS Enterprise"`` -> panel "target",
        action "USS Enterprise". Unprefixed: routed to the legacy
        handler if one was provided. Returns True if any handler ran.
        """
        if "/" in event_name:
            prefix, _, action = event_name.partition("/")
            for p in self._panels:
                if p.name == prefix:
                    return p.dispatch_event(action)
            return False
        if self._legacy is not None:
            self._legacy(event_name)
            return True
        return False
