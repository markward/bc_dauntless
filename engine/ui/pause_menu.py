"""Pause-menu model + view.

A dauntless-native widget — the original SDK does not own its
construction (`DefaultKeyboardBinding.py:25` binds ESC to an event the
C++ engine consumes directly to spawn `MWT_OPTIONS`). The model lives
in Python; CEF/HTML is purely a view that Python re-renders by
pushing `setPauseMenu({...})` via `cef_execute_javascript`.

Shape is deliberately extensible: adding a row is one `add_item` call
plus the matching handler. Mouse clicks would need a JS→Python
back-channel (e.g. CefMessageRouter) which is not wired yet; today
input is keyboard-only.

See docs/ui_designs/10-pause-menu.md for the visual / palette spec.
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional


_Handler = Callable[[], None]


class PauseMenuItem:
    """A single row: label + stable action id + handler callable."""

    __slots__ = ("label", "action_id", "handler")

    def __init__(self, label: str, action_id: str, handler: _Handler):
        self.label = label
        self.action_id = action_id
        self.handler = handler


class PauseMenuModel:
    """Owns the ordered list of menu items, the focused index, and the
    last-pushed state snapshot used to keep `render_payload` idempotent.

    Navigation wraps top↔bottom. Focus is held even when the menu is
    closed — re-opening lands on the previously-focused row, mirroring
    the original BC behaviour.
    """

    def __init__(self):
        self._items: List[PauseMenuItem] = []
        # -1 means "no row focused" — the menu paints neutral until the
        # user signals intent with an arrow key. Mouse hover lights up
        # rows independently via CSS :hover, so the initial state reads
        # as "nothing pre-selected" rather than "Exit Program is one
        # click away".
        self._focused: int = -1
        self._last_pushed: Optional[tuple] = None

    # ---- item management -------------------------------------------------

    @property
    def items(self) -> List[PauseMenuItem]:
        return list(self._items)

    @property
    def focused_index(self) -> int:
        return self._focused

    def add_item(self, label: str, action_id: str, handler: _Handler) -> None:
        if any(it.action_id == action_id for it in self._items):
            raise ValueError("duplicate action_id: " + action_id)
        self._items.append(PauseMenuItem(label, action_id, handler))

    # ---- navigation ------------------------------------------------------

    def focus_next(self) -> None:
        if not self._items:
            return
        # First arrow key from the unfocused initial state lands on
        # row 0; subsequent presses wrap as usual.
        if self._focused < 0:
            self._focused = 0
        else:
            self._focused = (self._focused + 1) % len(self._items)

    def focus_prev(self) -> None:
        if not self._items:
            return
        # First arrow key from the unfocused initial state lands on
        # the last row, matching most desktop list-nav conventions.
        if self._focused < 0:
            self._focused = len(self._items) - 1
        else:
            self._focused = (self._focused - 1) % len(self._items)

    def activate(self) -> None:
        """Fire the focused row's handler. No-op when there is no
        focused row (initial state, or empty list)."""
        if not self._items or self._focused < 0:
            return
        self._items[self._focused].handler()

    def dispatch_event(self, action_id: str) -> bool:
        """Fire the handler whose item matches ``action_id``. Used by
        the CEF event channel — JS click on a row navigates to
        dauntless://event/<id>, the C++ intercept calls Python, and
        Python lands here. Returns True if a matching item was found,
        False otherwise (unknown event names are ignored)."""
        for it in self._items:
            if it.action_id == action_id:
                it.handler()
                return True
        return False

    # ---- input glue ------------------------------------------------------

    def handle_input(self, h) -> None:
        """Poll ↑/↓/Enter and update focus / fire handler.

        `h` is the bindings module (or fake) exposing `key_pressed` and
        `keys.KEY_UP / KEY_DOWN / KEY_ENTER`. Missing KEY_ENTER (older
        bindings) falls back silently — keyboard activation is then
        unavailable but navigation still works.
        """
        keys = h.keys
        if h.key_pressed(keys.KEY_UP):
            self.focus_prev()
        if h.key_pressed(keys.KEY_DOWN):
            self.focus_next()
        enter = getattr(keys, "KEY_ENTER", None)
        if enter is not None and h.key_pressed(enter):
            self.activate()

    # ---- view ------------------------------------------------------------

    def render_payload(self) -> Optional[str]:
        """Return a JS snippet that updates the runtime DOM, or None
        when nothing has changed since the last call. Pure-functional —
        does not touch CEF; callers thread the string through
        `cef_execute_javascript` themselves.
        """
        snapshot = (
            tuple((it.label, it.action_id) for it in self._items),
            self._focused,
        )
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        payload = {
            "items": [
                {"label": it.label, "action": it.action_id}
                for it in self._items
            ],
            "focused": self._focused,
        }
        return "setPauseMenu(" + json.dumps(payload) + ");"

    def invalidate(self) -> None:
        """Drop the last-pushed snapshot so the next `render_payload`
        re-emits even if the model state is unchanged. Also resets
        keyboard focus to the unfocused initial state — the host loop
        calls this every time the pause menu closes so the next open
        starts with nothing pre-selected (the user's first arrow key
        then lands focus on row 0)."""
        self._last_pushed = None
        self._focused = -1


def default_pause_menu(*, on_exit: _Handler, on_cancel: _Handler) -> PauseMenuModel:
    """Build the dauntless default pause menu: Exit Program + Cancel.

    Handlers are injected so the model has no compile-time dependency
    on the host loop. The host loop wires `on_exit` to a quit flag and
    `on_cancel` to the pause-controller toggle.
    """
    m = PauseMenuModel()
    m.add_item("Exit Program", "exit",   on_exit)
    m.add_item("Cancel",       "cancel", on_cancel)
    return m
