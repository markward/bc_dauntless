"""Collapsible header (button + arrow) plus a list of child rows.

The header is composed of two elements (arrow + title) so the arrow can
be styled and clicked independently of the title region. The children
container is a separate sibling div whose `visible` flag is toggled by
the arrow.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import bindings
from .button import _RadioGroup, UiButton


class UiCollapsibleList:
    def __init__(self, *,
                 parent_element: int,
                 label: str,
                 affiliation: Optional[str] = None,
                 menu_level: int = 3,
                 expanded: bool = True,
                 selected: bool = False,
                 on_click: Optional[Callable[[], None]] = None):
        self._parent_element = parent_element
        self._label = label
        self._affiliation = affiliation
        self._menu_level = menu_level
        self._expanded = expanded
        self._selected = selected
        self._on_click = on_click
        self._destroyed = False
        self._children: list[object] = []
        self._radio_group = _RadioGroup()

        # Wrapper: contains header + children container so destroy() can
        # tear the whole subtree down with one remove_element call.
        self._wrapper_id = bindings.append_div(parent_element, "bc-collapsible")
        self.header_element_id = bindings.append_div(self._wrapper_id,
                                                     self._header_classes())
        self._arrow_id = bindings.append_div(self.header_element_id, "bc-arrow")
        self._title_id = bindings.append_div(self.header_element_id, "bc-title")
        bindings.set_text(self._title_id, label)
        self._children_container_id = bindings.append_div(
            self._wrapper_id, "bc-collapsible-children")
        bindings.set_visible(self._children_container_id, expanded)

        bindings.on_click(self._arrow_id, self._toggle_expanded)
        bindings.on_click(self._title_id, self._handle_title_click)

    # ── Public state ─────────────────────────────────────────────────────────

    @property
    def label(self) -> str: return self._label
    @property
    def expanded(self) -> bool: return self._expanded
    @property
    def selected(self) -> bool: return self._selected

    def set_label(self, label: str) -> None:
        self._label = label
        bindings.set_text(self._title_id, label)

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        bindings.set_visible(self._children_container_id, expanded)
        bindings.set_class(self.header_element_id, self._header_classes())

    def set_affiliation(self, name: Optional[str]) -> None:
        self._affiliation = name
        bindings.set_class(self.header_element_id, self._header_classes())

    def set_menu_level(self, level: int) -> None:
        self._menu_level = level
        bindings.set_class(self.header_element_id, self._header_classes())

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        bindings.set_class(self.header_element_id, self._header_classes())

    def clear(self) -> None:
        for child in self._children:
            child.destroy()  # type: ignore[attr-defined]
        self._children.clear()
        self._radio_group = _RadioGroup()

    def destroy(self) -> None:
        if self._destroyed:
            return
        bindings.remove_element(self._wrapper_id)
        self._destroyed = True

    # ── Internals ────────────────────────────────────────────────────────────

    def _header_classes(self) -> str:
        parts = ["bc-collapsible-header"]
        if self._affiliation is not None:
            parts.append(f"aff-{self._affiliation}")
        else:
            parts.append(f"menu-{self._menu_level}")
        if self._expanded:
            parts.append("expanded")
        else:
            parts.append("collapsed")
        if self._selected:
            parts.append("selected")
        return " ".join(parts)

    def _toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def _handle_title_click(self) -> None:
        if self._on_click is not None:
            self._on_click()
