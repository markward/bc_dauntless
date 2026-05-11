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

def set_panel_visible(panel_id: int, visible: bool) -> None:
    dom().set_panel_visible(panel_id, visible)

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


# ── Production initialization ───────────────────────────────────────────────

def init() -> None:
    """Bind to the real _open_stbc_host extension.

    Must be called after engine.renderer.init() (the C++ host_bindings::init
    creates the UiSystem). Idempotent — re-calling rebinds to the same module.
    """
    global _active_dom
    import _open_stbc_host as _h
    _active_dom = _RealDom(_h)


class _RealDom:
    """Wrapper exposing the FakeDom-compatible surface over _open_stbc_host."""

    def __init__(self, mod) -> None:
        self._m = mod

    def create_panel(self, name, anchor, width_vw, height_vh):
        return self._m.create_panel(name, anchor, width_vw, height_vh)

    def destroy_panel(self, pid):           self._m.destroy_panel(pid)
    def clear_panel(self, pid):             self._m.clear_panel(pid)
    def panel_root(self, pid):              return self._m.panel_root(pid)
    def set_panel_visible(self, pid, vis):  self._m.set_panel_visible(pid, vis)

    def set_panel_css_var(self, pid, n, v):
        # RmlUi's RCSS does not consume CSS custom properties; pushing them
        # into the document only triggers parser warnings. Kept as a no-op
        # at the real-DOM layer until we either (a) wire up RmlUi animation
        # for dynamic tinting or (b) generate RCSS sources at runtime. Tests
        # against FakeDom still record the calls via the FakeDom backend.
        pass

    def set_ui_scale(self, scale):          self._m.set_ui_scale(scale)
    def append_div(self, parent, cls):      return self._m.append_div(parent, cls)
    def remove_element(self, eid):          self._m.remove_element(eid)
    def set_class(self, eid, cls):          self._m.set_class(eid, cls)
    def set_text(self, eid, text):          self._m.set_text(eid, text)
    def set_visible(self, eid, vis):        self._m.set_visible(eid, vis)
    def on_click(self, eid, cb):            self._m.on_click(eid, cb)
