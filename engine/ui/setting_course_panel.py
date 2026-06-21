"""SettingCoursePanel — placeholder Set Course modal.

A minimal cp-* modal shown when the Helm "Set Course" button is clicked.
It currently displays a "Setting course…" message; the `destinations`
payload field is the seam where the real warp-destination list will be
wired in later (from the SortedRegionMenu passed to `open`).

Modeled on engine.ui.developer_options_panel.DeveloperOptionsPanel: a
Panel subclass pumped by PanelRegistry, reusing the configuration panel's
cp-* CSS. Reached from a Helm crew-menu click (not the pause menu).

Spec: docs/superpowers/specs/2026-06-21-set-course-button-popup-design.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel


class SettingCoursePanel(Panel):
    def __init__(self) -> None:
        super().__init__()
        self._visible = False
        self._course_menu = None
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "setting-course"

    def is_open(self) -> bool:
        return self._visible

    def open(self, course_menu=None) -> None:
        # course_menu is the SortedRegionMenu whose region children will
        # populate the destination list in a future iteration.
        self._course_menu = course_menu
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible,)
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setSettingCoursePanel(" + json.dumps({"visible": False}) + ");"
        payload = {
            "visible": True,
            "title": "Set Course",
            "message": "Setting course…",
            "destinations": [],
        }
        return "setSettingCoursePanel(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
