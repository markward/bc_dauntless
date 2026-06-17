"""Headless TG retained-mode widget tier.

SDK interface scripts build this tree (TGPane/TGIcon/TGParagraph + managers);
dauntless stores the state and never renders it — CEF panels observe selected
subtrees. Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md
"""
from engine.appc.tg_ui.widgets import (  # noqa: F401
    TGPane, TGPane_Create, TGPane_Cast,
    TGIcon, TGIcon_Create, TGIcon_Cast,
    TGParagraph, TGParagraph_Create, TGParagraph_CreateW, TGParagraph_Cast,
    TGIconGroup,
    WC_BACKSPACE, WC_TAB, WC_LINEFEED, WC_RETURN, WC_SPACE, WC_CURSOR, wc_to_str,
    ensure_widget_id,
)
