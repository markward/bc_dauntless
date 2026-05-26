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

    @property
    @abstractmethod
    def name(self) -> str:
        """Routing prefix; lower-case, no slashes."""

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._visible = bool(value)

    @abstractmethod
    def render_payload(self) -> Optional[str]:
        """Return JS to execute, or None if no change since last call."""

    @abstractmethod
    def dispatch_event(self, action: str) -> bool:
        """Handle a JS-originated event. Return True if handled."""

    def invalidate(self) -> None:
        """Drop any cached state so the next render_payload re-emits.

        Default no-op — subclasses with snapshot caches (e.g.
        TargetListView) override this. Wired by PanelRegistry.invalidate_all,
        which the host loop calls when the CEF page finishes loading
        so the first post-load emit is guaranteed to land.
        """
        pass
