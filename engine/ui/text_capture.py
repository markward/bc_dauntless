"""Keyboard capture for in-game CEF text fields.

While an editable element in the page has focus, it owns the keyboard: the
native KeyGate (renderer/key_gate.h) makes every key read False, so no polled
read, ET_KEYBOARD event or dev binding fires. Typed text goes to CEF instead.

The page (native/assets/ui-cef/js/text_capture.js) reports focus as
``kbd/focus:<panel>`` and ``kbd/blur``. This controller turns the gate on and
off, forwards the text queue to CEF only while a field holds the keyboard, and
enforces the release triggers so the game can never be left deaf:

  1. the page blurs the field (``kbd/blur``);
  2. native reset on page load / renderer crash (observed via
     ``host_io.key_capture_active()``);
  3. the owning panel is no longer open (checked every ``tick``);
  4. mission swap (``release`` is a pre-swap hook);
  5. a left click the host did not route to CEF (``release``).

A forced release (3-5) abandons the edit: the page reverts, then blurs.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md
"""
from __future__ import annotations

import logging
from typing import Optional

from engine import host_io
from engine.ui.panel import Panel

_log = logging.getLogger(__name__)

BLUR_SCRIPT = "window.__dauntlessBlurText&&window.__dauntlessBlurText()"


def _is_open(panel: Panel) -> bool:
    fn = getattr(panel, "is_open", None)
    if callable(fn):
        return bool(fn())
    return bool(panel.visible)


class TextCaptureController(Panel):
    def __init__(self, registry):
        super().__init__()
        self._registry = registry
        self.owner: Optional[str] = None
        self._blur_pending = False

    @property
    def name(self) -> str:
        return "kbd"

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("focus:"):
            name = action[len("focus:"):]
            panel = self._registry.find(name) if name else None
            if panel is not None and panel is not self and _is_open(panel):
                self.owner = name
                host_io.set_key_capture(True)
                # A key held across the boundary (e.g. the click/Enter that
                # triggered focus) must not replay a stale KEYUP into the
                # field it never saw the KEYDOWN for.
                host_io.cef_reset_text_translator()
            else:
                if panel is None:
                    _log.warning(
                        "text capture refused: no panel named %r -- is the "
                        "field's panel root missing its data-panel tag?", name)
                # Also releases a field that was holding the keyboard: tabbing
                # to an untagged field sends no blur first.
                self.owner = None
                host_io.set_key_capture(False)
                host_io.cef_reset_text_translator()
                self._blur_pending = True
            return True
        if action == "blur":
            self.owner = None
            host_io.set_key_capture(False)
            host_io.cef_reset_text_translator()
            return True
        return False

    def render_payload(self) -> Optional[str]:
        if not self._blur_pending:
            return None
        self._blur_pending = False
        return BLUR_SCRIPT

    def release(self) -> None:
        """Forced release (panel gone, mission swap, click on the game world).
        Abandons the edit: the page reverts, then blurs."""
        if self.owner is None:
            return
        self.owner = None
        host_io.set_key_capture(False)
        host_io.cef_reset_text_translator()
        self._blur_pending = True

    def tick(self) -> None:
        """Once per frame, at the top of the input block."""
        if self.owner is not None and not host_io.key_capture_active():
            # Native reset: the page that held the field reloaded or died.
            self.owner = None
            host_io.cef_reset_text_translator()
        if self.owner is not None:
            panel = self._registry.find(self.owner)
            if panel is None or not _is_open(panel):
                self.release()
        # Drain EVERY frame, so keys typed in flight never arrive in a field
        # that gains focus later.
        events = host_io.drain_text_events()
        if self.owner is not None and events:
            host_io.cef_send_text_events(events)
