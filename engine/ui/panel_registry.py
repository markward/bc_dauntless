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

import time
from typing import Callable, List, Optional
from engine.core import frame_profiler as _prof

from engine.ui.panel import Panel


class PanelRegistry:
    def __init__(self, legacy_handler: Optional[Callable[[str], None]] = None,
                 clock: Optional[Callable[[], float]] = None):
        self._panels: List[Panel] = []
        self._legacy = legacy_handler
        # WALL clock, not game time. A throttled panel should keep its cadence
        # while the sim is paused or frozen (DevTools, pause menu) -- the UI is
        # still interactive there. Injectable so tests can drive it.
        self._clock = clock if clock is not None else time.monotonic
        self._next_poll: dict = {}

    def register(self, panel: Panel) -> None:
        if any(p.name == panel.name for p in self._panels):
            raise ValueError("duplicate panel name: " + panel.name)
        self._panels.append(panel)

    def render_all(self) -> List[str]:
        """Poll every panel that is due and collect the JS each emits.

        A panel with poll_interval_s == 0 (the default) is polled every frame.
        A panel with a positive interval is polled on that cadence UNLESS it is
        marked due -- by invalidate(), by a visibility flip, or by having just
        handled an event -- in which case it renders on the next frame so
        interaction never lags behind the throttle.
        """
        now = self._clock()
        out: List[str] = []
        for p in self._panels:
            interval = p.poll_interval_s
            if interval > 0.0:
                if p._render_due:
                    p._render_due = False
                elif now < self._next_poll.get(p.name, 0.0):
                    continue
                self._next_poll[p.name] = now + interval
            # Per-panel scope: render_all is a thin loop, so a single timing
            # around it says only "the UI is expensive". Each panel has to
            # BUILD its snapshot before it can tell whether anything changed,
            # so the cost lives here and is worth attributing by name. Inert
            # unless the frame profiler is enabled.
            with _prof.scope("ui." + (p.name or "?")):
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
                    handled = p.dispatch_event(action)
                    # A click must show on the next frame, not at the next
                    # poll -- a throttled panel would otherwise feel like it
                    # ignored the input for up to its whole interval.
                    if handled:
                        p._render_due = True
                    return handled
            return False
        if self._legacy is not None:
            self._legacy(event_name)
            return True
        return False

    def invalidate_all(self) -> None:
        """Call ``panel.invalidate()`` on every registered panel.

        Used by the host loop as a CEF load-end callback so that all
        panel snapshot caches drop their last-pushed state. The next
        ``render_all()`` then re-emits regardless of whether Python-side
        state has changed since the last tick.
        """
        for p in self._panels:
            # Set the flag HERE rather than relying on the subclass calling
            # super().invalidate(). Most overrides in this package do not, and
            # they are correct not to today -- the flag is only consulted for a
            # panel with a positive poll_interval_s. Setting it here means
            # giving any existing panel an interval later cannot silently break
            # its invalidate path.
            p._render_due = True
            p.invalidate()
