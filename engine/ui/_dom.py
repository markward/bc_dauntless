"""In-memory DOM that mirrors the C++ binding contract for unit tests.

The real binding layer in engine.ui.bindings forwards the same calls to the
_open_stbc_host extension; tests substitute this class in its place so the
component logic can be exercised without a native build, a window, or RmlUi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class _Element:
    id: int
    parent: Optional[int]
    classes: list[str]      = field(default_factory=list)
    text: str               = ""
    visible: bool           = True
    children: list[int]     = field(default_factory=list)
    on_click: Optional[Callable[[], None]] = None


@dataclass
class _Panel:
    id: int
    name: str
    anchor: str
    width_vw: float
    height_vh: float
    root: int
    css_vars: dict[str, str] = field(default_factory=dict)
    visible: bool = True


class FakeDom:
    """A minimal DOM-like store. All IDs are integers. Element 0 is unused."""

    def __init__(self) -> None:
        self._elements: dict[int, _Element] = {}
        self._panels:   dict[int, _Panel]   = {}
        self._next_id = 1  # IDs share a namespace; 0 reserved for "invalid"

    # ── Panel lifecycle ──────────────────────────────────────────────────────

    def create_panel(self, name: str, anchor: str,
                     width_vw: float, height_vh: float) -> int:
        pid = self._next_id; self._next_id += 1
        root_id = self._next_id; self._next_id += 1
        self._elements[root_id] = _Element(id=root_id, parent=None)
        self._panels[pid] = _Panel(id=pid, name=name, anchor=anchor,
                                   width_vw=width_vw, height_vh=height_vh,
                                   root=root_id)
        return pid

    def destroy_panel(self, panel_id: int) -> None:
        panel = self._panels.pop(panel_id)
        self._destroy_subtree(panel.root)

    def clear_panel(self, panel_id: int) -> None:
        root_id = self._panels[panel_id].root
        for child in list(self._elements[root_id].children):
            self._destroy_subtree(child)
        self._elements[root_id].children.clear()

    def panel_root(self, panel_id: int) -> int:
        return self._panels[panel_id].root

    def panel_css_vars(self, panel_id: int) -> dict[str, str]:
        return dict(self._panels[panel_id].css_vars)

    def set_panel_css_var(self, panel_id: int, name: str, value: str) -> None:
        self._panels[panel_id].css_vars[name] = value

    def set_panel_visible(self, panel_id: int, visible: bool) -> None:
        self._panels[panel_id].visible = visible

    # ── Element mutation ─────────────────────────────────────────────────────

    def append_div(self, parent_id: int, class_names: str) -> int:
        eid = self._next_id; self._next_id += 1
        classes = [c for c in class_names.split() if c]
        self._elements[eid] = _Element(id=eid, parent=parent_id, classes=classes)
        self._elements[parent_id].children.append(eid)
        return eid

    def remove_element(self, element_id: int) -> None:
        el = self._elements[element_id]
        if el.parent is not None:
            self._elements[el.parent].children.remove(element_id)
        self._destroy_subtree(element_id)

    def set_class(self, element_id: int, class_names: str) -> None:
        self._elements[element_id].classes = [c for c in class_names.split() if c]

    def set_text(self, element_id: int, text: str) -> None:
        self._elements[element_id].text = text

    def set_visible(self, element_id: int, visible: bool) -> None:
        self._elements[element_id].visible = visible

    def on_click(self, element_id: int, callback: Callable[[], None]) -> None:
        self._elements[element_id].on_click = callback

    # ── Test introspection ───────────────────────────────────────────────────

    def element(self, element_id: int) -> _Element:
        return self._elements[element_id]

    def children(self, element_id: int) -> list[int]:
        return list(self._elements[element_id].children)

    def fire_click(self, element_id: int) -> None:
        cb = self._elements[element_id].on_click
        if cb is not None:
            cb()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _destroy_subtree(self, root_id: int) -> None:
        for child in list(self._elements[root_id].children):
            self._destroy_subtree(child)
        self._elements.pop(root_id, None)
