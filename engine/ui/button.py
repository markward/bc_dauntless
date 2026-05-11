"""Radio-group child row. Click → exclusive selection within siblings."""
from __future__ import annotations

from typing import Callable, Optional

from . import bindings


class UiButton:
    def __init__(self, *,
                 parent_element: int,
                 label: str,
                 menu_level: int = 3,
                 selected: bool = False,
                 on_click: Optional[Callable[[], None]] = None):
        self._parent_element = parent_element
        self._label = label
        self._menu_level = menu_level
        self._selected = selected
        self._on_click = on_click
        self._destroyed = False

        self.element_id = bindings.append_div(parent_element, self._class_names())
        bindings.set_text(self.element_id, label)
        bindings.on_click(self.element_id, self._handle_click)

    # ── Public state mutators ────────────────────────────────────────────────

    @property
    def label(self) -> str: return self._label
    @property
    def menu_level(self) -> int: return self._menu_level
    @property
    def selected(self) -> bool: return self._selected

    def set_label(self, label: str) -> None:
        self._label = label
        bindings.set_text(self.element_id, label)

    def set_menu_level(self, level: int) -> None:
        self._menu_level = level
        bindings.set_class(self.element_id, self._class_names())

    def set_selected(self, selected: bool) -> None:
        # Radio-group exclusivity is enforced by the parent (Phase 4 Task 7).
        # This method only flips the local flag and updates DOM classes.
        if self._selected == selected:
            return
        self._selected = selected
        bindings.set_class(self.element_id, self._class_names())

    def destroy(self) -> None:
        if self._destroyed:
            return
        bindings.remove_element(self.element_id)
        self._destroyed = True

    # ── Internals ────────────────────────────────────────────────────────────

    def _class_names(self) -> str:
        parts = ["bc-button", f"menu-{self._menu_level}"]
        if self._selected:
            parts.append("selected")
        return " ".join(parts)

    def _handle_click(self) -> None:
        # Filled in by the parent when it adopts this button into a radio
        # group (Task 7). For now: fire the consumer callback directly.
        if self._on_click is not None:
            self._on_click()
