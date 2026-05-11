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
from .stat_row import UiStatRow


Anchor = Literal["top-left", "top-right", "bottom-left", "bottom-right", "center"]


class UiPanel:
    # Toggle glyphs — Noto Sans Symbols 2 fallback supplies these when Antonio
    # doesn't cover them. User-spec: arrow-up when collapsed, arrow-down when
    # expanded (the arrow always points the direction expansion would go).
    _GLYPH_EXPANDED  = "▼"
    _GLYPH_COLLAPSED = "▲"

    def __init__(self, *,
                 id: str,
                 anchor: Anchor = "top-right",
                 width_vw: float = 20.0,
                 height_vh: float = 60.0,
                 title: Optional[str] = None,
                 collapsible: bool = False):
        self._id = id
        self._anchor = anchor
        self._width_vw = width_vw
        self._height_vh = height_vh
        self._title = title
        self._collapsible = collapsible
        self._collapsed = False
        self._title_element_id: Optional[int] = None
        self._toggle_element_id: Optional[int] = None
        self._header_element_id: Optional[int] = None
        self._children: list[object] = []
        self._radio_group = _RadioGroup()
        self._destroyed = False
        self._footer_element_id: Optional[int] = None
        self._footer_button: Optional[UiButton] = None

        self.panel_id = bindings.create_panel(id, anchor, width_vw, height_vh)
        self.refresh_theme()

        panel_root_id = bindings.panel_root(self.panel_id)

        # Optional header (title text on the left, collapse toggle on the right).
        # Header is only emitted when at least one of (title, collapsible) is
        # requested. Otherwise content attaches directly to #root, preserving
        # the old single-div layout used in the lightweight tests.
        has_header = title is not None or collapsible
        if has_header:
            self._header_element_id = bindings.append_div(
                panel_root_id, "bc-panel-header")
            self._title_element_id = bindings.append_div(
                self._header_element_id, "bc-panel-title")
            if title is not None:
                bindings.set_text(self._title_element_id, title)
            if collapsible:
                self._toggle_element_id = bindings.append_div(
                    self._header_element_id, "bc-panel-toggle")
                bindings.set_text(self._toggle_element_id, self._GLYPH_EXPANDED)
                bindings.on_click(self._toggle_element_id, self._handle_toggle_click)
            self._content_element_id = bindings.append_div(
                panel_root_id, "bc-panel-body")
        else:
            self._content_element_id = panel_root_id

    # ── Public state ─────────────────────────────────────────────────────────

    @property
    def root(self) -> int:
        """Element id that child components attach to.

        With a header, this is the bc-panel-body div inside #root; without
        a header it's #root itself.
        """
        return self._content_element_id

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @property
    def title(self) -> Optional[str]:
        return self._title

    def set_collapsed(self, collapsed: bool) -> None:
        if not self._collapsible:
            raise RuntimeError(
                "Panel is not collapsible; construct with collapsible=True")
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        bindings.set_visible(self._content_element_id, not collapsed)
        bindings.set_text(
            self._toggle_element_id,
            self._GLYPH_COLLAPSED if collapsed else self._GLYPH_EXPANDED)
        # Shrink bc-panel to header height when collapsed; back to full
        # height when expanded.
        bindings.set_class(
            bindings.panel_root(self.panel_id),
            "bc-panel bc-panel-collapsed" if collapsed else "bc-panel")

    def set_title(self, title: str) -> None:
        if self._title_element_id is None:
            raise RuntimeError(
                "Panel has no header; construct with title=... to enable")
        self._title = title
        bindings.set_text(self._title_element_id, title)

    def _handle_toggle_click(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_footer_button(self, label: str,
                          on_click: Optional[Callable[[], None]] = None,
    ) -> UiButton:
        """Create or re-bind the panel's single footer button.

        The footer container is created lazily on first call. Subsequent
        calls update the label and on_click on the same button.
        """
        if self._footer_element_id is None:
            self._footer_element_id = bindings.append_div(
                bindings.panel_root(self.panel_id), "bc-panel-footer")
            self._footer_button = UiButton(
                parent_element=self._footer_element_id,
                label=label, menu_level=3, selected=False,
                on_click=on_click,
            )
        else:
            assert self._footer_button is not None
            self._footer_button.set_label(label)
            self._footer_button._on_click = on_click
        return self._footer_button

    def button(self, label: str, *,
               menu_level: int = 3,
               selected: bool = False,
               on_click: Optional[Callable[[], None]] = None,
               radio: bool = True,
    ) -> UiButton:
        """Create a button as a direct child of this panel.

        With ``radio=True`` (the default) the button joins the panel's
        radio group: only one of those buttons can be selected at a
        time, and clicking the already-selected one is a no-op.

        For action buttons whose handler should fire on EVERY click
        (e.g., "Load Mission"), pass ``radio=False``. Such buttons are
        not selectable and never block their own re-firing.
        """
        btn = UiButton(parent_element=self.root, label=label,
                       menu_level=menu_level, selected=selected,
                       on_click=on_click)
        if radio:
            self._radio_group.adopt(btn)
            if selected:
                self._radio_group.select(btn)
        self._children.append(btn)
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

    def stat(self, label: str, value: str = "") -> UiStatRow:
        row = UiStatRow(parent_element=self.root, label=label, value=value)
        self._children.append(row)
        return row

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

    def refresh_theme(self) -> None:
        """Push the current theme registry values to the panel's CSS variables."""
        from . import theme
        for name, value in theme.css_var_pairs().items():
            bindings.set_panel_css_var(self.panel_id, name, value)
