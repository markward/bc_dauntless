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
        #
        # Consequence, accepted: TargetListView justifies its 0.5 s interval by
        # matching subsystems.SHIELD_CHARGE_PERIOD_S, but that period is
        # accumulated from GAME dt, so the two decouple under a time scale (Q3
        # measured BC's game clock at 0.204x in slow motion -- see CLAUDE.md).
        # The mismatch only ever runs one way in practice: a slowed sim ticks
        # shields SLOWER than wall clock, so this over-polls rather than
        # missing a change. Over-polling costs frame time and nothing else.
        self._clock = clock if clock is not None else time.monotonic
        self._next_poll: dict = {}
        # Last visibility seen per panel, so render_all can notice a flip the
        # panel never announced. Defaults to the panel's CURRENT value on
        # first sight, so registering a hidden panel is not itself a "flip".
        self._last_visible: dict = {}

    def register(self, panel: Panel) -> None:
        if any(p.name == panel.name for p in self._panels):
            raise ValueError("duplicate panel name: " + panel.name)
        self._panels.append(panel)

    def render_all(self) -> List[str]:
        """Poll every panel that is due and collect the JS each emits.

        Three gates, in order:

        * DUE -- marked by invalidate(), by a visibility flip, or by having
          just handled an event. A due panel always renders on the next frame,
          bypassing both gates below, so interaction never lags.
        * HIDDEN -- a panel that is not visible is not polled at all. Safe
          because a CHANGE in visibility is observed here, below, and forces
          one more poll: the payload that tells JS to hide still goes out, and
          becoming visible again resumes polling. This is the bigger win of
          the two -- the target list is off screen for the whole of bridge
          view, every cutscene, and the whole time the Ship Property Viewer is
          open.

          This used to rely on panels routing through the ``Panel.visible``
          SETTER, which is where the due-marking lived. Nothing enforced that,
          and six panels assign ``_visible`` directly in ``close()``; those
          panels' ESC path therefore killed their GL half and left their CEF
          chrome drawn on screen, because the hiding payload was never polled
          for. Observing the flag here instead makes the guarantee structural:
          a panel cannot get it wrong, including one written later.
        * INTERVAL -- poll_interval_s == 0 (the default) means every frame; a
          positive value means at most that often.
        """
        now = self._clock()
        out: List[str] = []
        for p in self._panels:
            interval = p.poll_interval_s
            # Read once: `visible` is a property, and the flip test and the
            # skip below must agree on the same value.
            visible = p.visible
            flipped = self._last_visible.get(p.name, visible) != visible
            self._last_visible[p.name] = visible
            if not p.consume_due() and not flipped:
                if not visible:
                    continue
                if interval > 0.0 and now < self._next_poll.get(p.name, 0.0):
                    continue
            if interval > 0.0:
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
                        p.mark_due()
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
            # Mark due HERE rather than relying on the subclass calling
            # super().invalidate(). Most overrides in this package do not, and
            # marking here means neither the poll interval nor the hidden-panel
            # skip can swallow an invalidate for a panel whose override forgot.
            p.mark_due()
            p.invalidate()
