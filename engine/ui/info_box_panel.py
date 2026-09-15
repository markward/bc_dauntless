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
    """Best-effort RGBA list from a TGColorA/NiColorA; None when absent.

    Gates on the component TYPE, never on hasattr.  An undefined `App` global is
    a truthy `_NamedStub`, and a stub answers ``hasattr()`` for *every* name — so
    a hasattr gate cannot reject one.  The previous version passed four stubs
    straight into ``json.dumps`` and killed the frame with a fatal
    ``TypeError``: E1M1's tactical-view help box builds its key glyphs with
    ``App.g_kMainMenuButton2HighlightedColor``
    (``sdk/.../Maelstrom/Episode1/E1M1/E1M1.py:3343``), which the shim does not
    define.  It is not one constant — **40 of the 51 `g_k*Color` globals the SDK
    references are undefined**.  They are Appc *instances*, not scalars, so the
    q13 constant dump (scalars only) neither covered nor could fix them.

    ``float(stub)`` returns ``0.0`` rather than raising, so a try/float guard
    would silently paint every such colour black; ``isinstance`` is the only
    reliable discriminator.  An unresolvable colour degrades to None — the glyph
    renders in its default colour instead of the frame dying.  This stays silent
    on purpose: the undefined name is already recorded by stub telemetry at the
    `App.<NAME>` access itself (see ``docs/stub_heatmap.md``), which is the right
    layer to observe it; logging here would fire every frame.
    """
    if color is None:
        return None
    rgba = [getattr(color, component, None) for component in ("r", "g", "b", "a")]
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in rgba):
        return rgba
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
        # Visible boxes that carry a Close button, in stack order (last =
        # bottom of the CSS column). Only these can own ESC: a box without
        # Close (E1M1's Picard tutorial box) is dismissed by a mission event,
        # never by the player, so it must not block the pause menu.
        self._closeable_ids: list = []
        # On-screen rect of the modal stack in CEF view px, reported by JS
        # ("bounds:x,y,w,h") after each render and on window resize. The host
        # loop forwards left-clicks to CEF only inside a known bbox (see the
        # _cursor_in_* ladder in host_loop.py) -- the modal is centred and
        # sized by its text, so the only honest source for that bbox is the
        # laid-out DOM. None until JS reports; stale rects are harmless
        # because cursor_in_bounds() also requires is_open().
        self._bounds: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "info-box"

    def render_payload(self) -> Optional[str]:
        from engine.appc.windows import _STStylizedWindow, TacticalControlWindow
        from engine.appc.characters import STButton

        entries: list = []
        self._boxes_by_id = {}
        self._closeable_ids = []
        for (child, _x, _y) in TacticalControlWindow.GetInstance()._children:
            if not isinstance(child, _STStylizedWindow):
                continue
            if not child.IsVisible():
                continue
            self._boxes_by_id[child._id] = child
            # MissionLib.SetupInfoBoxFromParagraph always builds the body as the
            # outermost TGParagraph (a direct child of the box's content TGPane),
            # with key-glyph children carried inside that paragraph's segment
            # stream — so the BFS lands on the body, not a glyph.
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
                self._closeable_ids.append(child._id)
            entries.append(entry)

        payload = json.dumps({"entries": entries})
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setInfoBoxes(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("close:"):
            self._close(action[len("close:"):])
            return True
        if action.startswith("bounds:"):
            try:
                x, y, w, h = (float(v) for v in action[len("bounds:"):].split(","))
                self._bounds = (x, y, w, h)
            except ValueError:
                _logger.warning("info-box: malformed bounds %r dropped", action)
                self._bounds = None
            return True
        return False

    def _close(self, box_id: str) -> None:
        """Press the box's own Close button -- the SDK event path
        (ET_INPUT_CLOSE_MENU -> MissionLib.CloseInfoBox + the mission's
        handler, e.g. E1M1.TacticalInfoBoxClosed), never a bare
        SetNotVisible, so the mission's "closed" flag is set too."""
        box = self._boxes_by_id.get(box_id)
        if box is None:
            # Box rebuilt/removed between frames — drop; next snapshot
            # repairs the UI.
            _logger.info("info-box: stale close id %s dropped", box_id)
            return
        from engine.appc.characters import STButton
        button = _find_first(box, lambda w: isinstance(w, STButton))
        if button is not None:
            button.SendActivationEvent()
        else:
            _logger.warning("info-box: box %s has no close button; ignoring close", box_id)

    # ── Modal-blocker protocol (host_loop._modal_blockers) ──────────────────
    # A visible box WITH a Close button is a modal the player dismisses, so
    # it takes ESC ahead of the crew menu and the pause-menu toggle -- the
    # same bracket as the star map and Quick Battle Setup, which sit above
    # it (z-index 50 vs 40) and therefore precede it in the ladder.

    def is_open(self) -> bool:
        return bool(self._closeable_ids)

    def handle_key_esc(self) -> None:
        if self._closeable_ids:
            self._close(self._closeable_ids[-1])

    def cursor_in_bounds(self, mx: float, my: float) -> bool:
        """Click-forwarding gate for the host loop, in CEF view px. Half-open
        like the sibling _cursor_in_* bboxes. False whenever no closeable box
        is up, so a rect left over from the last box never swallows phaser
        fire."""
        if not self.is_open() or self._bounds is None:
            return False
        x, y, w, h = self._bounds
        return x <= mx < x + w and y <= my < y + h

    def invalidate(self) -> None:
        self._last_pushed = None
