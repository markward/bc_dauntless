"""Ship Property Viewer pause-menu modal (Panel subclass).

Mirrors engine.ui.developer_options_panel: pumped by PanelRegistry, opened from
the dev pause menu. Snapshot-diffs its payload like the other panels.
Spec: docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

import json
import math
from typing import Callable, List, Optional

from engine.ui.panel import Panel
from engine.ui.ship_property_viewer import (
    build_descriptors, OrbitCamera, pick_pin,
)

# Fraction of the view height the ship's bounding sphere should fill when the
# viewer first frames the ship (1.0 = sphere touches top/bottom edges).
SCREEN_FILL = 0.95

# Radians of orbit per pixel of left-drag. ~0.35 rad (20°) for a 50 px drag.
ORBIT_SENS = 0.007
# Fraction of distance removed per scroll notch (positive scroll = zoom in).
ZOOM_STEP = 0.1
# Multiplicative distance step per =/- key press (zoom in multiplies by this;
# zoom out divides). Mirrors the external view's notch zoom.
ZOOM_KEY_FACTOR = 0.9
# Orbit distance clamps (game units) so the ship can't be lost or clipped.
MIN_DISTANCE = 1.0
MAX_DISTANCE = 1.0e5
# A left press+release that moved less than this many pixels counts as a
# click (pin pick) rather than an orbit drag.
CLICK_SLOP_PX = 4.0

# CEF chrome geometry in logical points — MUST match ship_property_viewer.css.
# Mouse input inside these regions belongs to the CEF overlay: presses there
# never start an orbit drag or a pin pick, and the wheel is left in the host
# accumulator so host_loop's scroll router forwards it to CEF (scrolling the
# subsystem list) instead of zooming the camera.
TITLEBAR_H_PT = 34        # .spv-titlebar height
LEFT_COL_X1_PT = 268      # #spv-left right edge (left 12 + width 248 + pad 8)
LEFT_COL_Y0_PT = 44       # #spv-left top


class ShipPropertyViewerPanel(Panel):
    def __init__(self, ship_getter: Callable[[], object]) -> None:
        super().__init__()
        self._ship_getter = ship_getter
        self._visible = False
        self._descriptors: List[dict] = []
        self.selected_index: Optional[int] = None
        self.camera: Optional[OrbitCamera] = None
        # Titlebar overlay toggles — both off by default, reset every open.
        self.show_glow_regions = False
        self.show_weapon_arcs = False
        self._last_pushed: Optional[tuple] = None
        # Left-drag tracking (panel-local edge detection so we don't steal
        # the CEF mouse-release edge — see handle_input).
        self._lmb_down = False
        self._drag_last: Optional[tuple] = None   # (x, y) previous cursor
        self._press_pos: Optional[tuple] = None   # (x, y) where press began
        self._drag_dist = 0.0                     # accumulated |motion| px
        self._chrome_press = False                # press began over CEF chrome

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
        self.show_glow_regions = False
        self.show_weapon_arcs = False
        target = self._fit_target()
        self.camera = OrbitCamera(target=target, distance=self._fit_distance(target))
        self._visible = True

    def close(self) -> None:
        self._visible = False
        self._descriptors = []
        self.selected_index = None
        self.show_glow_regions = False
        self.show_weapon_arcs = False
        self.camera = None
        self._lmb_down = False
        self._drag_last = None
        self._press_pos = None
        self._drag_dist = 0.0
        self._chrome_press = False

    def frame_to_bounds(self, center, radius: float) -> None:
        """Point the orbit camera at `center` and pull back so the model's
        world-space bounding sphere (`radius`) fills ~SCREEN_FILL of the view
        height. Called by the host loop on open with the real ship bounds
        (the subsystem-centroid framing in open() is only a fallback)."""
        if self.camera is None or radius <= 0.0:
            return
        self.camera.target = (float(center[0]), float(center[1]), float(center[2]))
        half_fov = self.camera.fov_y_rad / 2.0
        tan_half = math.tan(half_fov)
        if tan_half <= 0.0:
            return
        d = radius / (SCREEN_FILL * tan_half)
        self.camera.distance = max(min(d, MAX_DISTANCE), MIN_DISTANCE)

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

    def selected_descriptor(self) -> Optional[dict]:
        """The currently-selected pin's descriptor, or None."""
        if self.selected_index is None:
            return None
        if 0 <= self.selected_index < len(self._descriptors):
            return self._descriptors[self.selected_index]
        return None

    def selected_name(self) -> Optional[str]:
        """Name of the selected subsystem (matches a phaser bank's GetName()
        for firing-arc overlay selection), or None."""
        d = self.selected_descriptor()
        return d["name"] if d else None

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible, len(self._descriptors), self.selected_index,
                    self.show_glow_regions, self.show_weapon_arcs)
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
            "selected_index": self.selected_index,
            "show_glow": self.show_glow_regions,
            "show_arcs": self.show_weapon_arcs,
            # Left-column subsystem list: index-aligned with the pin
            # descriptors so a row click can fire select_pin:<index>.
            "subsystems": [
                {"name": d.get("name", ""),
                 "targetable": bool(d.get("targetable", False)),
                 "condition_pct": d.get("condition_pct"),
                 "kind": d.get("kind", "subsystem")}
                for d in self._descriptors
            ],
        }
        return "setShipPropertyViewer(" + json.dumps(payload) + ");"

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    # ------------------------------------------------------------------
    # Pure camera math (host-free → unit-testable in isolation)
    # ------------------------------------------------------------------
    def apply_orbit(self, dx: float, dy: float) -> None:
        """Advance yaw by dx px and pitch by dy px of left-drag. OrbitCamera
        clamps pitch internally (in eye()), so no clamp here."""
        if self.camera is None:
            return
        self.camera.yaw += dx * ORBIT_SENS
        self.camera.pitch += dy * ORBIT_SENS

    def apply_zoom(self, wheel: float) -> None:
        """Scale orbit distance by a scroll delta (positive wheel = zoom in),
        clamped to [MIN_DISTANCE, MAX_DISTANCE]."""
        if self.camera is None or wheel == 0.0:
            return
        new_d = self.camera.distance * (1.0 - wheel * ZOOM_STEP)
        self.camera.distance = max(MIN_DISTANCE, min(MAX_DISTANCE, new_d))

    def zoom_by_factor(self, factor: float) -> None:
        """Multiply orbit distance by `factor` (=-key zoom in, -key zoom out),
        clamped to [MIN_DISTANCE, MAX_DISTANCE]."""
        if self.camera is None:
            return
        new_d = self.camera.distance * factor
        self.camera.distance = max(MIN_DISTANCE, min(MAX_DISTANCE, new_d))

    def pick_at(self, x: float, y: float, viewport,
                device_scale_factor: float = 1.0) -> None:
        """Run a pin pick at cursor (x, y) and emit select/deselect."""
        if self.camera is None:
            return
        idx = pick_pin(x, y, self._descriptors, self.camera, viewport,
                       device_scale_factor)
        if idx is not None:
            self.dispatch_event("select_pin:%d" % idx)
        else:
            self.dispatch_event("deselect")

    # ------------------------------------------------------------------
    # Host input pump (called each frame while open + focused)
    # ------------------------------------------------------------------
    def handle_input(self, h) -> None:
        """Mouse orbit / zoom / pin-pick.

        `h` is the host bindings module (`_dauntless_host`). We read the raw
        left-button state via mouse_button_state (which does NOT consume the
        edge that the pause-menu CEF forwarding relies on) and track the
        press/drag/release ourselves. Cursor + viewport are framebuffer
        pixels — the same space project()/pick_pin() and the GL render use.

        Degrades to a no-op if any required binding is missing (headless)."""
        if self.camera is None:
            return
        try:
            btn_state = h.mouse_button_state
            cursor_pos = h.cursor_pos
            fb_size = h.framebuffer_size
            left = h.keys.MOUSE_BUTTON_LEFT
        except AttributeError:
            return

        # Device-pixel ratio = framebuffer / logical window height, so the
        # pin click radius (logical points) matches the GL-rendered disc on
        # HiDPI displays. Degrades to 1.0 if window_size is unavailable.
        dsf = 1.0
        win_size = getattr(h, "window_size", None)
        if win_size is not None:
            try:
                _fb_w, fb_h = fb_size()
                _win_w, win_h = win_size()
                if win_h > 0:
                    dsf = float(fb_h) / float(win_h)
            except (TypeError, ValueError, ZeroDivisionError):
                dsf = 1.0

        x, y = cursor_pos()
        over_chrome = self._cursor_over_chrome(x, y, dsf)
        over_left_col = self._cursor_over_left_column(x, y, dsf)

        # Zoom: drain the wheel accumulator even when no other input so a
        # later open doesn't inherit stale scroll — EXCEPT over the left
        # column, where the accumulator is deliberately left alone so
        # host_loop's scroll router (the frame's later consumer) forwards
        # the wheel to CEF and the subsystem list scrolls.
        consume_scroll = getattr(h, "consume_scroll_y", None)
        if consume_scroll is not None and not over_left_col:
            self.apply_zoom(consume_scroll())

        # Keyboard zoom: = / - notch zoom, matching the external view.
        kp = getattr(h, "key_pressed", None)
        if kp is not None:
            k_eq = getattr(h.keys, "KEY_EQUAL", None)
            k_min = getattr(h.keys, "KEY_MINUS", None)
            if k_eq is not None and kp(k_eq):
                self.zoom_by_factor(ZOOM_KEY_FACTOR)
            if k_min is not None and kp(k_min):
                self.zoom_by_factor(1.0 / ZOOM_KEY_FACTOR)

        down = btn_state(left)

        if down and not self._lmb_down:
            # Press edge. A press over the CEF chrome (titlebar / left
            # column) belongs to the overlay — never starts an orbit drag
            # and never picks on release (CEF fires the row/button event).
            self._lmb_down = True
            self._chrome_press = over_chrome
            self._drag_last = (x, y)
            self._press_pos = (x, y)
            self._drag_dist = 0.0
        elif down and self._lmb_down:
            # Drag: orbit by the per-frame cursor delta.
            if self._drag_last is not None and not self._chrome_press:
                dx = x - self._drag_last[0]
                dy = y - self._drag_last[1]
                self.apply_orbit(dx, dy)
                self._drag_dist += (dx * dx + dy * dy) ** 0.5
            self._drag_last = (x, y)
        elif (not down) and self._lmb_down:
            # Release edge: a near-stationary press+release is a click → pick.
            self._lmb_down = False
            if self._drag_dist <= CLICK_SLOP_PX and not self._chrome_press:
                self.pick_at(x, y, fb_size(), dsf)
            self._drag_last = None
            self._press_pos = None
            self._drag_dist = 0.0
            self._chrome_press = False

    @staticmethod
    def _cursor_over_left_column(x: float, y: float, dsf: float) -> bool:
        """Cursor (framebuffer px) inside the left tool/subsystem column."""
        s = dsf or 1.0
        return (x / s) <= LEFT_COL_X1_PT and (y / s) >= LEFT_COL_Y0_PT

    @classmethod
    def _cursor_over_chrome(cls, x: float, y: float, dsf: float) -> bool:
        """Cursor (framebuffer px) over any CEF chrome region (titlebar or
        left column) whose clicks the overlay owns."""
        s = dsf or 1.0
        return (y / s) <= TITLEBAR_H_PT or cls._cursor_over_left_column(x, y, dsf)

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action == "toggle_glow_regions":
            self.show_glow_regions = not self.show_glow_regions
            self._last_pushed = None  # re-push so the button state updates
            return True
        if action == "toggle_weapon_arcs":
            self.show_weapon_arcs = not self.show_weapon_arcs
            self._last_pushed = None
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
