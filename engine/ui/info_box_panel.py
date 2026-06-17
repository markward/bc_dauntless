# engine/ui/info_box_panel.py
"""InfoBoxPanel — renders SDK info boxes (MissionLib.SetupInfoBoxFromParagraph)
as dauntless-styled CEF modals.

Observes _STStylizedWindow children parented to TacticalControlWindow, serializes
each visible one (title + body segment stream + Close button), and routes CEF
Close clicks back through STButton.SendActivationEvent — the same event path the
crew-menu panel uses.

Spec: docs/superpowers/specs/2026-06-17-sdk-info-box-rendering-design.md
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.ui.panel import Panel
from engine.appc.tg_ui.widgets import TGParagraph, wc_to_str

_logger = logging.getLogger(__name__)


def _color_to_list(color):
    """Best-effort RGBA list from a TGColorA/NiColorA; None when absent."""
    if color is None:
        return None
    if hasattr(color, "r") and hasattr(color, "g") \
            and hasattr(color, "b") and hasattr(color, "a"):
        return [color.r, color.g, color.b, color.a]
    return None


def _find_first(widget, predicate):
    """Breadth-first search for the first descendant (incl. widget itself)
    matching predicate. Walks both TGPane (child, x, y) tuples and bare-child
    lists, so it works across the mixed STStylizedWindow/TGPane hierarchy."""
    queue = [widget]
    while queue:
        w = queue.pop(0)
        if w is None:
            continue
        if predicate(w):
            return w
        children = getattr(w, "_children", None)
        if children:
            for c in children:
                queue.append(c[0] if isinstance(c, tuple) else c)
    return None


def _serialize_body(paragraph) -> list:
    body = []
    for kind, val in paragraph.iter_segments():
        if kind == "text":
            if val:
                body.append({"kind": "text", "text": val})
        elif kind == "char":
            s = wc_to_str(val)
            if s:
                body.append({"kind": "text", "text": s})
        elif kind == "child":
            body.append({
                "kind": "key",
                "text": val.GetText(),
                "color": _color_to_list(getattr(val, "_color", None)),
            })
    return body


class InfoBoxPanel(Panel):
    def __init__(self):
        super().__init__()
        self._last_pushed: Optional[str] = None
        self._boxes_by_id: dict = {}

    @property
    def name(self) -> str:
        return "info-box"

    def render_payload(self) -> Optional[str]:
        from engine.appc.windows import _STStylizedWindow, TacticalControlWindow
        from engine.appc.characters import STButton

        entries: list = []
        self._boxes_by_id = {}
        for (child, _x, _y) in TacticalControlWindow.GetInstance()._children:
            if not isinstance(child, _STStylizedWindow):
                continue
            if not child.IsVisible():
                continue
            self._boxes_by_id[child._id] = child
            paragraph = _find_first(child, lambda w: isinstance(w, TGParagraph))
            button = _find_first(child, lambda w: isinstance(w, STButton))
            entry = {
                "id": child._id,
                "title": child._title,
                "body": _serialize_body(paragraph) if paragraph is not None else [],
                "button": None,
            }
            if button is not None:
                entry["button"] = {"id": child._id, "label": button.GetLabel()}
            entries.append(entry)

        payload = json.dumps({"entries": entries})
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setInfoBoxes(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        # Implemented in Task 5.
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
