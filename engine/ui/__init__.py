"""Reusable UI components for the open_stbc renderer.

See docs/superpowers/specs/2026-05-11-ui-components-design.md for the design.
"""
from . import bindings, theme
from .bindings import init as _bindings_init
from .button import UiButton
from .collapsible import UiCollapsibleList
from .panel import UiPanel

# Global UI scale. Every `dp` value in RCSS / inline style is multiplied
# by this. 1.0 = native pixels; 2.0 = doubled. Will become user-configurable
# (settings menu / cli flag) — for now hardcoded here so the panel reads
# comfortably on a 1080p / 1440p display.
UI_SCALE: float = 2.0


def init() -> None:
    """Bind to the real renderer host and apply UI_SCALE.

    Must be called once after engine.renderer.init().
    """
    _bindings_init()
    bindings.dom().set_ui_scale(UI_SCALE)


__all__ = ["init", "bindings", "theme", "UI_SCALE",
           "UiButton", "UiCollapsibleList", "UiPanel"]
