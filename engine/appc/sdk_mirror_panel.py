"""SDKMirrorPanel — walks _TopWindow children + main windows, emits JSON
snapshot to CEF via setSdkMirror(...).

One panel registered against PanelRegistry; the only consumer of
_TopWindow._children for rendering purposes. SDK shims (_SubtitleWindow,
_STStylizedWindow, future TGIcon/STText/...) mutate their own state;
this panel observes via the children list once per tick.

Spec: docs/superpowers/specs/2026-06-03-cef-sdk-ui-mirror-design.md
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from engine.appc import top_window
from engine.ui.panel import Panel

_logger = logging.getLogger(__name__)


class SDKMirrorPanel(Panel):
    def __init__(self):
        super().__init__()
        self._last_pushed: Optional[str] = json.dumps({"entries": []})
        self._logged_unrecognised: set[str] = set()

    @property
    def name(self) -> str:
        return "sdk-mirror"

    def render_payload(self) -> Optional[str]:
        now = time.monotonic()
        entries: list = []

        tw = top_window.TopWindow_GetTopWindow()

        sub = tw._main_windows.get(top_window.MWT_SUBTITLE)
        if sub is not None:
            snap = sub._snapshot(now)
            if snap is not None:
                entries.append(snap)

        for (child, _x, _y) in tw._children:
            if self._has_real_snapshot(child):
                entries.append(child._snapshot())
            else:
                self._log_unrecognised_once(type(child).__name__)

        payload = json.dumps({"entries": entries})
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setSdkMirror(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("click:"):
            _logger.info("sdk-mirror click %s (no dispatch — v1)", action[len("click:"):])
            return True
        return False

    def invalidate(self) -> None:
        # Reset to None, NOT the empty-entries sentinel. PanelRegistry
        # calls invalidate() after a CEF page reload, when the DOM is
        # blank — even a quiescent (empty) payload must fire once to
        # confirm the empty state to the freshly loaded JS.
        self._last_pushed = None

    @staticmethod
    def _has_real_snapshot(child) -> bool:
        """True only if `child` defines a genuine `_snapshot` method.

        A plain `hasattr(child, "_snapshot")` is fooled by every TGObject:
        `TGObject.__getattr__` returns a `_Stub` for any attribute name, so
        `hasattr` is always True and calling the stub yields a `_Stub` that is
        not JSON-serializable. QuickBattle.BuildDialog adds a bare `TGPane`
        (g_pPane) to the TopWindow, which surfaced exactly this. Mirror
        `TGSequence._has_real_start`: walk the MRO for a real definition.
        """
        for cls in type(child).__mro__:
            if "_snapshot" in cls.__dict__:
                return True
        return False

    def _log_unrecognised_once(self, type_name: str) -> None:
        if type_name in self._logged_unrecognised:
            return
        self._logged_unrecognised.add(type_name)
        _logger.info("sdk-mirror: skipping unrecognised child type %s", type_name)
