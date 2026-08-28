"""Abstract base class for CEF-rendered UI panels.

Every Panel has:
  - ``name`` — string identifier used as the event-routing prefix in
    the JS→Python channel (e.g. clicking a row in the "target" panel
    fires `dauntlessEvent('target/USS Enterprise')`, which the
    PanelRegistry routes to the panel whose ``name`` is "target").
  - ``visible`` — Python-side flag. The host loop maps this to a CSS
    class toggle in the corresponding HTML container.
  - ``render_payload()`` — return a JS snippet to execute in CEF, or
    ``None`` if nothing has changed since the last call. Idempotency
    is the contract (matches PauseMenuModel.render_payload pattern).
  - ``dispatch_event(action)`` — return True if the action was handled.

PauseMenuModel predates this base class and is intentionally not a
Panel subclass — the registry treats unprefixed events as legacy and
falls back to the pause menu's existing dispatch.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class Panel(ABC):
    def __init__(self):
        self._visible: bool = True
        # True => the registry polls this panel on the next render_all
        # regardless of poll_interval_s. Starts True so a throttled panel
        # always emits once before its first interval elapses.
        self._render_due: bool = True

    @property
    @abstractmethod
    def name(self) -> str:
        """Routing prefix; lower-case, no slashes."""

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        value = bool(value)
        # A visibility FLIP must show immediately even on a throttled panel.
        # The host loop assigns this every frame, so only a real change marks
        # the panel due -- otherwise every panel would be due every frame and
        # the throttle would do nothing. Without this, switching from tactical
        # to bridge view would leave the HUD on screen for up to one interval.
        if value != self._visible:
            self.mark_due()
        self._visible = value

    @property
    def poll_interval_s(self) -> float:
        """Minimum seconds between polls of ``render_payload``.

        0.0 (the default) means every frame, which is right for a panel whose
        snapshot is cheap to build. Override with a positive value when the
        snapshot itself is expensive -- the contract is that render_payload
        returns None when nothing changed, but a panel still has to BUILD its
        snapshot to find that out, and for some panels that build is the cost.

        Throttling only affects POLLING. An explicit invalidate(), a
        visibility flip, or a dispatched event still renders on the next
        frame, so interaction stays immediate.
        """
        return 0.0

    @abstractmethod
    def render_payload(self) -> Optional[str]:
        """Return JS to execute, or None if no change since last call."""

    @abstractmethod
    def dispatch_event(self, action: str) -> bool:
        """Handle a JS-originated event. Return True if handled."""

    def mark_due(self) -> None:
        """Force the next ``PanelRegistry.render_all`` to poll this panel.

        The supported way to say "render me now" from outside: it bypasses
        both the poll interval and the hidden-panel skip for exactly one
        frame. Used by the registry (dispatched events, invalidate_all), by
        the ``visible`` setter, and by any caller that mutates state the panel
        reflects (the host loop invalidates the target list on a target
        change). Prefer this over touching ``_render_due``.
        """
        self._render_due = True

    def consume_due(self) -> bool:
        """Return whether the panel is marked due, clearing the mark.

        Registry-facing: exactly one caller may consume the mark per frame,
        which is why this both reads and clears.
        """
        due = self._render_due
        self._render_due = False
        return due

    def invalidate(self) -> None:
        """Drop any cached state so the next render_payload re-emits.

        Subclasses with snapshot caches (e.g. TargetListView) override this
        and MUST call ``super().invalidate()`` -- the base marks the panel due
        (see ``mark_due``), which is what lets a throttled panel bypass its
        interval. Wired by
        PanelRegistry.invalidate_all, which the host loop calls when the CEF
        page finishes loading so the first post-load emit is guaranteed to land.
        """
        self.mark_due()
