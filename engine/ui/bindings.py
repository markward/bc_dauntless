"""Facade over the panel-DOM bindings.

In production, `_active_dom` is set during init() to a wrapper around the
_open_stbc_host extension. In tests, the fake_dom fixture swaps in an
engine.ui._dom.FakeDom. Component code calls these module-level helpers and
remains ignorant of which backing implementation is in use.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# Set by engine.ui.init() (production) or by the fake_dom fixture (tests).
# Typed as Any to avoid a hard import of the C++ binding module.
_active_dom: Optional[Any] = None


def dom() -> Any:
    if _active_dom is None:
        raise RuntimeError(
            "engine.ui bindings have no active DOM. Call engine.ui.init() "
            "after the renderer is up, or use the fake_dom test fixture."
        )
    return _active_dom


# ── Pass-through helpers (identical signatures to FakeDom) ──────────────────

def create_panel(name: str, anchor: str, width_vw: float, height_vh: float) -> int:
    return dom().create_panel(name, anchor, width_vw, height_vh)

def destroy_panel(panel_id: int) -> None:
    dom().destroy_panel(panel_id)

def clear_panel(panel_id: int) -> None:
    dom().clear_panel(panel_id)

def panel_root(panel_id: int) -> int:
    return dom().panel_root(panel_id)

def set_panel_css_var(panel_id: int, name: str, value: str) -> None:
    dom().set_panel_css_var(panel_id, name, value)

def append_div(parent_id: int, class_names: str) -> int:
    return dom().append_div(parent_id, class_names)

def remove_element(element_id: int) -> None:
    dom().remove_element(element_id)

def set_class(element_id: int, class_names: str) -> None:
    dom().set_class(element_id, class_names)

def set_text(element_id: int, text: str) -> None:
    dom().set_text(element_id, text)

def set_visible(element_id: int, visible: bool) -> None:
    dom().set_visible(element_id, visible)

def on_click(element_id: int, callback: Callable[[], None]) -> None:
    dom().on_click(element_id, callback)
