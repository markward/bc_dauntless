"""Root container for stackable UI components.

Owns a panel handle in the binding layer and exposes button/collapsible
factories that attach directly to the panel's root element. A panel
maintains its own _RadioGroup for top-level button exclusivity.
"""
from __future__ import annotations

from typing import Callable, Literal, Optional

from . import bindings
from .button import _RadioGroup, UiButton
from .collapsible import UiCollapsibleList


Anchor = Literal["top-left", "top-right", "bottom-left", "bottom-right"]


class UiPanel:
    def __init__(self, *,
                 id: str,
                 anchor: Anchor = "top-right",
                 width_vw: float = 20.0,
                 height_vh: float = 60.0):
        self._id = id
        self._anchor = anchor
        self._width_vw = width_vw
        self._height_vh = height_vh
        self._children: list[object] = []
        self._radio_group = _RadioGroup()
        self._destroyed = False

        self.panel_id = bindings.create_panel(id, anchor, width_vw, height_vh)

    @property
    def root(self) -> int:
        return bindings.panel_root(self.panel_id)

    def button(self, label: str, *,
               menu_level: int = 3,
               selected: bool = False,
               on_click: Optional[Callable[[], None]] = None,
    ) -> UiButton:
        btn = UiButton(parent_element=self.root, label=label,
                       menu_level=menu_level, selected=selected,
                       on_click=on_click)
        self._radio_group.adopt(btn)
        self._children.append(btn)
        if selected:
            self._radio_group.select(btn)
        return btn

    def collapsible(self, label: str, *,
                    affiliation: Optional[str] = None,
                    menu_level: int = 3,
                    expanded: bool = True,
                    on_click: Optional[Callable[[], None]] = None,
    ) -> UiCollapsibleList:
        c = UiCollapsibleList(parent_element=self.root, label=label,
                              affiliation=affiliation, menu_level=menu_level,
                              expanded=expanded, on_click=on_click)
        self._children.append(c)
        return c

    def clear(self) -> None:
        for child in self._children:
            child.destroy()  # type: ignore[attr-defined]
        self._children.clear()
        self._radio_group = _RadioGroup()

    def destroy(self) -> None:
        if self._destroyed:
            return
        bindings.destroy_panel(self.panel_id)
        self._destroyed = True
