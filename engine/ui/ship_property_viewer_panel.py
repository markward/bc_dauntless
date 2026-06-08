"""Ship Property Viewer pause-menu modal (Panel subclass).

Mirrors engine.ui.developer_options_panel: pumped by PanelRegistry, opened from
the dev pause menu. Snapshot-diffs its payload like the other panels.
Spec: docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

import json
from typing import Callable, List, Optional

from engine.ui.panel import Panel
from engine.ui.ship_property_viewer import build_descriptors, OrbitCamera


class ShipPropertyViewerPanel(Panel):
    def __init__(self, ship_getter: Callable[[], object]) -> None:
        super().__init__()
        self._ship_getter = ship_getter
        self._visible = False
        self._descriptors: List[dict] = []
        self.selected_index: Optional[int] = None
        self.camera: Optional[OrbitCamera] = None
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "ship-property-viewer"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._last_pushed = None
        ship = self._ship_getter()
        self._descriptors = build_descriptors(ship) if ship is not None else []
        self.selected_index = None
        target = self._fit_target()
        self.camera = OrbitCamera(target=target, distance=self._fit_distance(target))
        self._visible = True

    def close(self) -> None:
        self._visible = False
        self._descriptors = []
        self.selected_index = None
        self.camera = None

    def _fit_target(self) -> tuple:
        """Centroid of the subsystem mounts in world space. Descriptors carry
        absolute world positions (subsystem_world_position adds the ship's
        world location), so the viewer orbits the ship where it actually sits
        in the scene — consistent with the GL hologram re-drawing the real
        ship instance at its real transform. No re-centring."""
        if not self._descriptors:
            return (0.0, 0.0, 0.0)
        n = len(self._descriptors)
        sx = sum(d["world_pos"][0] for d in self._descriptors) / n
        sy = sum(d["world_pos"][1] for d in self._descriptors) / n
        sz = sum(d["world_pos"][2] for d in self._descriptors) / n
        return (sx, sy, sz)

    def _fit_distance(self, target: tuple) -> float:
        """Far enough to frame the furthest mount from the centroid."""
        if not self._descriptors:
            return 10.0
        def _r(d):
            wx, wy, wz = d["world_pos"]
            return ((wx-target[0])**2 + (wy-target[1])**2 + (wz-target[2])**2) ** 0.5
        max_r = max(_r(d) for d in self._descriptors)
        return max(max_r * 2.5, 5.0)

    def descriptors(self) -> List[dict]:
        return self._descriptors

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible, len(self._descriptors), self.selected_index)
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setShipPropertyViewer(" + json.dumps({"visible": False}) + ");"
        selected = None
        if self.selected_index is not None and \
                0 <= self.selected_index < len(self._descriptors):
            selected = self._descriptors[self.selected_index]
        payload = {
            "visible": True,
            "pin_count": len(self._descriptors),
            "selected": selected,
        }
        return "setShipPropertyViewer(" + json.dumps(payload) + ");"

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def handle_input(self, h) -> None:
        """Mouse orbit/zoom/pick input handling wired in task D1.
        Stub present to match DeveloperOptionsPanel's interface contract."""
        pass

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action.startswith("select_pin:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if 0 <= idx < len(self._descriptors):
                self.selected_index = idx
                self._last_pushed = None  # force re-push of popover
                return True
            return False
        if action == "deselect":
            if self.selected_index is None:
                return False
            self.selected_index = None
            self._last_pushed = None
            return True
        return False
