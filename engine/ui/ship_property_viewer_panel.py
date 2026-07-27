"""Ship Property Viewer pause-menu modal (Panel subclass).

Mirrors engine.ui.developer_options_panel: pumped by PanelRegistry, opened from
the dev pause menu. Snapshot-diffs its payload like the other panels.
Spec: docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

import json
import math
from typing import Callable, List, Optional

from engine.appc.override_routing import (
    resolve_override_target, hardpoint_leaf_for_ship,
)
from engine.ui.panel import Panel
from engine.ui.ship_property_viewer import (
    build_descriptors, OrbitCamera, pick_pin, region_spec_to_calls,
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

# Bottom-right tool-button cluster (#spv-tools). Anchored right:12/bottom:12
# with N 40px buttons and 6px gaps in a flex row. Mouse input here belongs to
# the CEF buttons, so it never starts an orbit drag or pin pick.
TOOLS_MARGIN_PT = 12      # #spv-tools right / bottom offset
TOOLS_BTN_PT = 40         # .spv-tool size
TOOLS_GAP_PT = 6          # #spv-tools gap
TOOLS_COUNT = 3           # buttons in the row (glow / arcs / hull-texture)
TOOLS_W_PT = TOOLS_COUNT * TOOLS_BTN_PT + (TOOLS_COUNT - 1) * TOOLS_GAP_PT
TOOLS_H_PT = TOOLS_BTN_PT

# Transform-tools row (#spv-transform-tools: Transform/Rotate/Scale), stacked
# directly above #spv-tools with the same TOOLS_GAP_PT between the two rows.
# Same width/button-size as the render row, so it shares TOOLS_W_PT.
TRANSFORM_H_PT = TOOLS_BTN_PT
TOOLS_CLUSTER_H_PT = TOOLS_H_PT + TOOLS_GAP_PT + TRANSFORM_H_PT

# Top-right transform coordinate panel (#spv-coords). Anchored right:12/top:46
# with width 220 / height ~172 (three coord rows + Copy/Paste/Mirror). Clicks
# here belong to the CEF panel, so they never start an orbit or gizmo drag.
COORDS_MARGIN_PT = 12
COORDS_TOP_PT = 46
COORDS_W_PT = 220
COORDS_H_PT = 172

# Wireframe colour for the selected subsystem's radius sphere — a soft green,
# distinct from the orange glow-region and cyan weapon-arc overlays.
SUBSYS_SPHERE_COLOR = (0.5, 1.0, 0.6)

# Floor for any scale-tool field (radius / box axis / cylinder length) — a
# nudge or paste can never drive a dimension to zero or negative.
SCALE_MIN = 0.01


class ShipPropertyViewerPanel(Panel):
    def __init__(self, ship_getter: Callable[[], object]) -> None:
        super().__init__()
        self._ship_getter = ship_getter
        self._visible = False
        self._descriptors: List[dict] = []
        self.selected_index: Optional[int] = None
        # Active transform-gizmo tool: None|"transform"|"rotate"|"scale".
        # Mutually exclusive radio, reset every open/close.
        self.active_tool: Optional[str] = None
        # Selected LIGHT volume (descriptor index of the subsystem whose light
        # is selected), mutually exclusive with selected_index. Shows only that
        # light's glow wireframe; the parent radius sphere is hidden.
        self._selected_light_index: Optional[int] = None
        self.camera: Optional[OrbitCamera] = None
        # Titlebar overlay toggles — both off by default, reset every open.
        self.show_glow_regions = False
        self.show_weapon_arcs = False
        # Render mode toggle: False = blue Fresnel hologram (default),
        # True = the ship's real hull textures. Reset every open.
        self.show_hull_texture = False
        # Names of aggregator subsystems whose child rows are expanded in the
        # left-column list (accordion, like the target list). Collapsed by
        # default; reset every open.
        self._expanded_groups: set = set()
        # Staged radius edits: descriptor index -> new radius. Reset every
        # open/close. Not applied to the live sim (radius has no in-session
        # visual); persisted on Save, applied on the next ship build.
        self._pending_radius: dict = {}
        # Staged glow/light edits: descriptor index -> baked-shaped region spec.
        self._pending_light: dict = {}
        # Glow/light edits saved THIS session (descriptor index -> spec). Save
        # persists to the file, which only reaches the live template on the next
        # ship build — so we keep the saved spec here to keep driving the SPV's
        # live wireframe + modal pre-fill (not dirty, no Save bar). Reset on
        # open/close. See pending_light_specs / the save handler.
        self._saved_light: dict = {}
        # Radius edits saved THIS session (descriptor index -> radius). Same
        # persist->reload story as _saved_light: keeps the volume sphere + the
        # radius readout on the saved value until the next ship build.
        self._saved_radius: dict = {}
        # Staged position edits: descriptor index -> body-frame (x, y, z).
        # Same story as _pending_radius: not applied to the live sim, persisted
        # on Save, applied on the next ship build.
        self._pending_pos: dict = {}
        # Position edits saved THIS session (descriptor index -> body pos).
        # Same persist->reload story as _saved_radius/_saved_light.
        self._saved_pos: dict = {}
        # True while a CEF context menu / modal is open: handle_input suppresses
        # orbit + pick so clicks on that chrome don't reach the 3D view.
        self._overlay_open = False
        # One-shot flag: set by handle_key_esc() when ESC closes an overlay
        # (not the panel); render_payload() surfaces it once as
        # payload["close_overlays"] then clears it. Deliberately excluded
        # from the snapshot tuple so a payload carrying it always gets
        # pushed even if nothing else changed.
        self._close_overlays = False
        self._last_pushed: Optional[tuple] = None
        # Left-drag tracking (panel-local edge detection so we don't steal
        # the CEF mouse-release edge — see handle_input).
        self._lmb_down = False
        self._drag_last: Optional[tuple] = None   # (x, y) previous cursor
        self._press_pos: Optional[tuple] = None   # (x, y) where press began
        self._drag_dist = 0.0                     # accumulated |motion| px
        self._chrome_press = False                # press began over CEF chrome
        # Transform-gizmo axis drag state (subsystem target). _axis_drag is the
        # grabbed axis index (0/1/2) while dragging, else None. _gizmo_hover is
        # the hovered axis for the highlight, -1 when none.
        self._axis_drag: Optional[int] = None
        self._axis_grab_param = 0.0
        self._axis_grab_pos = (0.0, 0.0, 0.0)
        self._axis_grab_origin = (0.0, 0.0, 0.0)
        # Scale-drag grab state: (field-index, grabbed-value) captured at
        # press so the multiplicative drag stays anchored to the start size.
        self._scale_grab = (0, 0.0)
        # Ring-drag (rotate tool) grab state, captured at press: the grabbed
        # screen angle, the grab-start body axis/orientation basis + degree
        # accumulators, and the screen-vs-body rotation sign. Reset every
        # open/close.
        self._ring_grab_angle = 0.0
        self._ring_grab_axis = (0.0, -1.0, 0.0)
        self._ring_grab_orientation = ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self._ring_grab_accum = [0.0, 0.0, 0.0]
        self._ring_sign = 1.0
        self._gizmo_hover = -1
        # Clipboard for the transform-coord panel's Copy/Paste — a body-frame
        # (x, y, z) tuple, or None. Reset every open/close.
        self._coord_clipboard = None
        # Clipboard for the scale tool's Copy/Paste — (kind, values-tuple),
        # or None. Reset every open/close.
        self._scale_clipboard = None
        # Clipboard for the rotate tool's Copy/Paste — ("cylinder_axis",
        # (x, y, z)), or None. Reset every open/close.
        self._rotate_clipboard = None
        # Rotate-tool per-light degree accumulators (readout only, not
        # persisted): descriptor index -> [x, y, z] cumulative degrees
        # since the light was last selected/reset. Reset every open/close.
        self._rotate_accum: dict = {}

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
        self._selected_light_index = None
        self.active_tool = None
        self.show_glow_regions = False
        self.show_weapon_arcs = False
        self.show_hull_texture = False
        self._expanded_groups = set()
        self._pending_radius = {}
        self._pending_light = {}
        self._saved_light = {}
        self._saved_radius = {}
        self._pending_pos = {}
        self._saved_pos = {}
        self._overlay_open = False
        self._close_overlays = False
        self._axis_drag = None
        self._axis_grab_param = 0.0
        self._axis_grab_pos = (0.0, 0.0, 0.0)
        self._axis_grab_origin = (0.0, 0.0, 0.0)
        self._scale_grab = (0, 0.0)
        self._ring_grab_angle = 0.0
        self._ring_grab_axis = (0.0, -1.0, 0.0)
        self._ring_grab_orientation = ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self._ring_grab_accum = [0.0, 0.0, 0.0]
        self._ring_sign = 1.0
        self._gizmo_hover = -1
        self._coord_clipboard = None
        self._scale_clipboard = None
        self._rotate_clipboard = None
        self._rotate_accum = {}
        target = self._fit_target()
        self.camera = OrbitCamera(target=target, distance=self._fit_distance(target))
        self._visible = True

    def close(self) -> None:
        self._visible = False
        self._descriptors = []
        self.selected_index = None
        self._selected_light_index = None
        self.active_tool = None
        self.show_glow_regions = False
        self.show_weapon_arcs = False
        self.show_hull_texture = False
        self._expanded_groups = set()
        self._pending_radius = {}
        self._pending_light = {}
        self._saved_light = {}
        self._saved_radius = {}
        self._pending_pos = {}
        self._saved_pos = {}
        self._overlay_open = False
        self._close_overlays = False
        self.camera = None
        self._lmb_down = False
        self._drag_last = None
        self._press_pos = None
        self._drag_dist = 0.0
        self._chrome_press = False
        self._axis_drag = None
        self._axis_grab_param = 0.0
        self._axis_grab_pos = (0.0, 0.0, 0.0)
        self._axis_grab_origin = (0.0, 0.0, 0.0)
        self._scale_grab = (0, 0.0)
        self._ring_grab_angle = 0.0
        self._ring_grab_axis = (0.0, -1.0, 0.0)
        self._ring_grab_orientation = ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self._ring_grab_accum = [0.0, 0.0, 0.0]
        self._ring_sign = 1.0
        self._gizmo_hover = -1
        self._coord_clipboard = None
        self._scale_clipboard = None
        self._rotate_clipboard = None
        self._rotate_accum = {}

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

    def _effective_radius(self, index: int, baked):
        """Radius to display for a descriptor: a staged (unsaved) edit wins,
        then an edit saved this session, else the baked GetRadius(). Keeps the
        volume sphere + readout in step with the Set Radius editor (which only
        reaches the live template on the next ship build)."""
        if index in self._pending_radius:
            return self._pending_radius[index]
        if index in self._saved_radius:
            return self._saved_radius[index]
        return baked

    def _effective_light(self, index):
        """Effective index-0 light spec for a descriptor: a staged (unsaved)
        edit wins, then a saved-this-session edit, else the baked region — with
        `None` meaning 'no light' (absent, or a staged/saved removal)."""
        if index in self._pending_light:
            return self._pending_light[index]      # spec dict, or None (removed)
        if index in self._saved_light:
            return self._saved_light[index]
        d = self._descriptors[index]
        return d.get("light_region") if d.get("light") else None

    def _has_light(self, index) -> bool:
        return (0 <= index < len(self._descriptors)
                and self._effective_light(index) is not None)

    def _effective_pos(self, index: int):
        """Body-frame position to use for a descriptor: a staged (unsaved)
        edit wins, then an edit saved this session, else the baked body-frame
        mount (`properties.position`). Mirrors `_effective_radius`."""
        if index in self._pending_pos:
            return self._pending_pos[index]
        if index in self._saved_pos:
            return self._saved_pos[index]
        props = self._descriptors[index].get("properties", {})
        return tuple(props.get("position") or (0.0, 0.0, 0.0))

    def _effective_world_pos(self, index: int):
        """World-space point for `_effective_pos(index)`, so a staged/dragged
        position moves the sphere + pin live even though it has no in-session
        effect on the sim. Falls back to the baked world_pos if the ship is
        unavailable (headless / not yet resolved)."""
        from engine.ui.ship_property_viewer import world_from_body
        ship = self._ship_getter()
        if ship is None or not hasattr(ship, "GetWorldLocation"):
            return self._descriptors[index].get("world_pos", (0.0, 0.0, 0.0))
        return world_from_body(ship, self._effective_pos(index))

    def set_subsystem_position(self, index: int, body_pos) -> None:
        """Stage a body-frame position edit for `index`. Not applied to the
        live sim (position has no in-session physics effect); persisted on
        Save, applied on the next ship build. Mirrors set_radius staging."""
        if 0 <= index < len(self._descriptors):
            self._pending_pos[index] = (float(body_pos[0]), float(body_pos[1]),
                                         float(body_pos[2]))
            self._last_pushed = None

    def set_light_position(self, index: int, body_pos) -> None:
        """Stage a body-frame position edit for light `index`'s region-0
        spec. Mirrors `set_subsystem_position`; the existing light save path
        (`_pending_light` → `region_spec_to_calls`) already persists it."""
        spec = dict(self._effective_light(index) or {})
        spec["position"] = tuple(float(c) for c in body_pos)
        self._pending_light[index] = spec
        self._last_pushed = None

    # ------------------------------------------------------------------
    # Transform gizmo (subsystem or light-volume target)
    # ------------------------------------------------------------------
    def _active_transform_target(self):
        """Which node the transform gizmo/drag currently targets: ("light",
        i), ("subsystem", i), or None. Light selection and subsystem
        selection are mutually exclusive by construction (dispatch_event's
        selection handlers clear the other), so light wins when set."""
        if self._selected_light_index is not None:
            return ("light", self._selected_light_index)
        if self.selected_index is not None:
            return ("subsystem", self.selected_index)
        return None

    def _transform_target_pos(self):
        """Body-frame (x, y, z) of the current transform target, or None (no
        tool target). Mirrors `transform_gizmo`'s target resolution but
        returns the raw position tuple instead of the gizmo geometry."""
        t = self._active_transform_target()
        if t is None:
            return None
        kind, i = t
        if kind == "light":
            spec = self._effective_light(i)
            if not spec:
                return None
            return tuple(float(c) for c in spec["position"])
        return tuple(float(c) for c in self._effective_pos(i))

    def _set_transform_target_pos(self, xyz) -> None:
        """Stage `xyz` as the current transform target's body-frame position,
        routing to the light or subsystem staging path as appropriate."""
        t = self._active_transform_target()
        if t is None:
            return
        kind, i = t
        if kind == "light":
            self.set_light_position(i, xyz)
        else:
            self.set_subsystem_position(i, xyz)

    def transform_coords(self) -> Optional[dict]:
        """Data for the transform-coordinate panel: `{"x","y","z",
        "has_clipboard"}` for the current transform target, or None when the
        transform tool isn't active or nothing is selected."""
        if self.active_tool != "transform":
            return None
        pos = self._transform_target_pos()
        if pos is None:
            return None
        return {"x": pos[0], "y": pos[1], "z": pos[2],
                "has_clipboard": self._coord_clipboard is not None}

    # ------------------------------------------------------------------
    # Scale tool (shape-aware size fields for the current transform target)
    # ------------------------------------------------------------------
    def _scale_kind_and_fields(self, target):
        """Shape-aware size fields for `target` (see `_active_transform_target`).
        A subsystem is always a sphere (`radius`); a light volume's fields
        depend on its shape (`Box` -> xyz axes, `Cylinder` -> radius+length,
        else -> radius)."""
        kt, i = target
        if kt == "subsystem":
            r = self._effective_radius(i, self._descriptors[i].get("properties", {}).get("radius"))
            try:
                r = float(r)
            except (TypeError, ValueError):
                r = 0.0
            return "radius", [{"label": "Radius", "value": r}]
        spec = self._effective_light(i)
        if not spec:
            return "radius", [{"label": "Radius", "value": 0.0}]
        shape = spec.get("shape", "Sphere")
        if shape == "Box":
            sx, sy, sz = spec.get("scale", (0.25, 0.25, 0.25))
            return "xyz", [{"label": "X", "value": float(sx)},
                           {"label": "Y", "value": float(sy)},
                           {"label": "Z", "value": float(sz)}]
        if shape == "Cylinder":
            r = spec.get("radius", (0.25,))[0]
            aft, fore = spec.get("extent", (0.0, 2.0))
            return "radius_length", [{"label": "Radius", "value": float(r)},
                                     {"label": "Length", "value": float(fore) - float(aft)}]
        return "radius", [{"label": "Radius", "value": float(spec.get("radius", (0.25,))[0])}]

    def scale_values(self) -> Optional[dict]:
        """Data for the scale-tool panel: `{"kind", "fields", "has_clipboard",
        "can_paste"}` for the current transform target, or None when the
        scale tool isn't active or nothing is selected."""
        if self.active_tool != "scale":
            return None
        t = self._active_transform_target()
        if t is None:
            return None
        kind, fields = self._scale_kind_and_fields(t)
        clip = self._scale_clipboard
        return {"kind": kind, "fields": fields,
                "has_clipboard": clip is not None,
                "can_paste": clip is not None and clip[0] == kind}

    def _set_scale_field(self, index, value) -> None:
        """Stage `value` (floored at SCALE_MIN) for size field `index` of the
        current transform target, routing to the radius or light-spec staging
        path as appropriate."""
        t = self._active_transform_target()
        if t is None:
            return
        value = max(SCALE_MIN, float(value))
        kt, i = t
        kind, fields = self._scale_kind_and_fields(t)
        if not (0 <= index < len(fields)):
            return
        if kt == "subsystem":
            self._pending_radius[i] = value
            self._last_pushed = None
            return
        spec = dict(self._effective_light(i) or {})
        if not spec:
            return
        shape = spec.get("shape", "Sphere")
        if shape == "Box":
            sc = list(spec.get("scale", (0.25, 0.25, 0.25)))
            sc[index] = value
            spec["scale"] = tuple(sc)
        elif shape == "Cylinder":
            if index == 0:
                spec["radius"] = (value,)
            else:
                # Length scales the extent about the anchor (pos = offset 0,
                # where the gizmo sits), NOT by holding the aft end fixed —
                # so a pos-centred cylinder grows symmetrically instead of
                # sliding off one end. Proportional scale keeps offset 0 fixed.
                aft, fore = spec.get("extent", (0.0, 2.0))
                length = fore - aft
                if abs(length) > 1e-9:
                    r = value / length
                    spec["extent"] = (aft * r, fore * r)
                else:
                    spec["extent"] = (-value / 2.0, value / 2.0)
        else:
            spec["radius"] = (value,)
        self._pending_light[i] = spec
        self._last_pushed = None

    # ------------------------------------------------------------------
    # Rotate tool (Cylinder light-volume axis only)
    # ------------------------------------------------------------------
    def _rotate_target(self):
        """("light", i) when the current transform target is a light whose
        effective spec is a Cylinder (rotate its axis) or a Box (rotate its
        forward+up orientation basis); None otherwise (sphere/subsystem are
        inert)."""
        t = self._active_transform_target()
        if t is None:
            return None
        kt, i = t
        if kt != "light":
            return None
        spec = self._effective_light(i)
        if not spec or spec.get("shape") not in ("Cylinder", "Box"):
            return None
        return ("light", i)

    def rotate_values(self) -> Optional[dict]:
        """Data for the rotate-tool panel: `{"fields", "has_clipboard",
        "can_paste"}` for the current rotate target, or None when the rotate
        tool isn't active or the target isn't a cylinder/box light.
        `can_paste` is kind-aware: true only when the clipboard's kind
        (`cylinder_axis`/`box_orientation`) matches the selected target's
        shape."""
        if self.active_tool != "rotate":
            return None
        t = self._rotate_target()
        if t is None:
            return None
        _, i = t
        acc = self._rotate_accum.get(i, [0.0, 0.0, 0.0])
        clip = self._rotate_clipboard
        kind = self._rotate_clipboard_kind(i)
        return {"fields": [{"label": "X", "value": acc[0]},
                           {"label": "Y", "value": acc[1]},
                           {"label": "Z", "value": acc[2]}],
                "has_clipboard": clip is not None,
                "can_paste": clip is not None and clip[0] == kind}

    def _rotate_clipboard_kind(self, i) -> str:
        """Clipboard kind for light `i`'s current shape: `box_orientation`
        for a Box, `cylinder_axis` otherwise."""
        spec = self._effective_light(i) or {}
        return "box_orientation" if spec.get("shape") == "Box" else "cylinder_axis"

    def _rotate_axis(self, index, delta_deg) -> None:
        """Rotate the current rotate target by `delta_deg` about basis axis
        `index` (Rodrigues, via rotate_about_axis) and bump that axis's
        degree accumulator. Shape-aware: a Cylinder rotates its `axis`; a Box
        rotates BOTH `forward` and `up` of its orientation basis, then
        re-orthonormalizes."""
        t = self._rotate_target()
        if t is None:
            return
        _, i = t
        from engine.ui.ship_property_viewer import (
            rotate_about_axis, orthonormalize_basis)
        spec = dict(self._effective_light(i) or {})
        if not spec:
            return
        ang = math.radians(delta_deg)
        if spec.get("shape") == "Box":
            fwd, up = spec.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            fwd = rotate_about_axis(fwd, index, ang)
            up = rotate_about_axis(up, index, ang)
            spec["orientation"] = orthonormalize_basis(fwd, up)
        else:
            axis = spec.get("axis") or (0.0, -1.0, 0.0)
            spec["axis"] = rotate_about_axis(axis, index, ang)
        self._pending_light[i] = spec
        self._rotate_accum.setdefault(i, [0.0, 0.0, 0.0])[index] += delta_deg
        self._last_pushed = None

    def _set_axis_absolute(self, i, axis) -> None:
        """Stage a normalized `axis` for light `i` directly (Mirror/Paste,
        not an incremental rotation) and zero its degree accumulator."""
        spec = dict(self._effective_light(i) or {})
        if not spec:
            return
        n = math.sqrt(sum(a*a for a in axis)) or 1.0
        spec["axis"] = (axis[0]/n, axis[1]/n, axis[2]/n)
        self._pending_light[i] = spec
        self._rotate_accum[i] = [0.0, 0.0, 0.0]
        self._last_pushed = None

    def _set_orientation_absolute(self, i, forward, up) -> None:
        """Stage a re-orthonormalized `(forward, up)` orientation for box
        light `i` directly (Mirror/Paste, not an incremental rotation) and
        zero its degree accumulator. Mirrors `_set_axis_absolute`."""
        spec = dict(self._effective_light(i) or {})
        if not spec:
            return
        from engine.ui.ship_property_viewer import orthonormalize_basis
        spec["orientation"] = orthonormalize_basis(forward, up)
        self._pending_light[i] = spec
        self._rotate_accum[i] = [0.0, 0.0, 0.0]
        self._last_pushed = None

    def transform_gizmo(self) -> Optional[dict]:
        """The move-gizmo for the selected subsystem or light node, or None.

        `{"origin", "axes", "length", "highlight"}` when the transform tool is
        active and a subsystem or light node is selected; None otherwise (no
        tool, no selection, no camera, or the ship can't be resolved).
        `origin` follows any staged/dragged position (`_effective_world_pos`
        for a subsystem, `world_from_body` of the effective light position
        for a light); `axes` are the three world-space body axes; `highlight`
        is the hovered axis (-1 none)."""
        if self.active_tool != "transform" or self.camera is None:
            return None
        target = self._active_transform_target()
        if target is None:
            return None
        kind, i = target
        if kind == "subsystem" and not (0 <= i < len(self._descriptors)):
            return None
        ship = self._ship_getter()
        if ship is None or not hasattr(ship, "GetWorldRotation"):
            return None
        from engine.ui.ship_property_viewer import (
            gizmo_axes, gizmo_length, world_from_body)
        if kind == "light":
            light = self._effective_light(i)
            if light is None:
                return None
            origin = world_from_body(ship, light["position"])
        else:
            origin = self._effective_world_pos(i)
        return {
            "origin": origin,
            "axes": gizmo_axes(ship.GetWorldRotation()),
            "length": gizmo_length(self.camera),
            "highlight": self._gizmo_hover,
            "handle_kind": 0,
        }

    def scale_gizmo(self) -> Optional[dict]:
        """The scale-gizmo for the selected subsystem or light node, or None.

        Same shape as `transform_gizmo` (`{"origin","axes","length",
        "highlight"}`) but with `"handle_kind": 1` so the renderer draws box
        handles instead of arrows. Gated on the scale tool being active, a
        target selected, and the ship resolvable with a world rotation."""
        if self.active_tool != "scale" or self.camera is None:
            return None
        if self._active_transform_target() is None:
            return None
        ship = self._ship_getter()
        if ship is None or not hasattr(ship, "GetWorldRotation"):
            return None
        from engine.ui.ship_property_viewer import (
            gizmo_axes, gizmo_length, world_from_body)
        t = self._active_transform_target()
        kt, i = t
        # Defensive guards mirroring transform_gizmo (this runs every input
        # frame via _active_gizmo): a stale/removed light or out-of-range index
        # must degrade to None, never crash on a missing spec.
        if not (0 <= i < len(self._descriptors)):
            return None
        if kt == "light":
            light = self._effective_light(i)
            if light is None:
                return None
            origin = world_from_body(ship, light["position"])
        else:
            origin = self._effective_world_pos(i)
        return {
            "origin": origin,
            "axes": gizmo_axes(ship.GetWorldRotation()),
            "length": gizmo_length(self.camera),
            "highlight": self._gizmo_hover,
            "handle_kind": 1,
        }

    def rotate_gizmo(self) -> Optional[dict]:
        """The rotate-gizmo (orientation rings) for the selected cylinder light,
        or None. Same shape as `scale_gizmo` but with `"handle_kind": 2` so the
        renderer draws rings. Gated on the rotate tool being active, a rotate
        target (cylinder light) selected, and the ship resolvable with a world
        rotation."""
        if self.active_tool != "rotate" or self.camera is None:
            return None
        t = self._rotate_target()
        if t is None:
            return None
        ship = self._ship_getter()
        if ship is None or not hasattr(ship, "GetWorldRotation"):
            return None
        _, i = t
        if not (0 <= i < len(self._descriptors)):
            return None
        light = self._effective_light(i)
        if light is None:
            return None
        from engine.ui.ship_property_viewer import (
            gizmo_axes, gizmo_length, world_from_body)
        origin = world_from_body(ship, light["position"])
        return {
            "origin": origin,
            "axes": gizmo_axes(ship.GetWorldRotation()),
            "length": gizmo_length(self.camera),
            "highlight": self._gizmo_hover,
            "handle_kind": 2,
        }

    def _active_gizmo(self) -> Optional[dict]:
        """The gizmo for the active tool: `transform_gizmo` under Transform,
        `scale_gizmo` under Scale, `rotate_gizmo` under Rotate, else None.
        Shared by `_handle_gizmo_input` so hover/grab/drag geometry follows the
        current tool."""
        if self.active_tool == "transform":
            return self.transform_gizmo()
        if self.active_tool == "scale":
            return self.scale_gizmo()
        if self.active_tool == "rotate":
            return self.rotate_gizmo()
        return None

    def _begin_scale_drag(self, axis: int, grab_param: float) -> None:
        """Start a scale drag on `axis`, capturing the fixed drag-start world
        origin and the grabbed size value so `_apply_scale_drag` multiplies
        from a stable anchor. For xyz (Box) targets the axis picks the field;
        every other shape is uniform and scales field 0 (the radius)."""
        self._axis_drag = axis
        self._axis_grab_param = grab_param
        g = self._active_gizmo()
        self._axis_grab_origin = g["origin"] if g else (0.0, 0.0, 0.0)
        t = self._active_transform_target()
        if t is None:
            self._scale_grab = (0, 0.0)
            return
        kind, fields = self._scale_kind_and_fields(t)
        if kind == "xyz":
            self._scale_grab = (axis, fields[axis]["value"])   # per-axis
        elif kind == "radius_length":
            # Cylinder: the handle aligned with the cylinder's axis scales
            # Length (field 1); the two perpendicular handles scale Radius
            # (field 0). The gizmo axes are body X/Y/Z, so the aligned handle
            # is the dominant component of the region's body-frame axis vector.
            kt, i = t
            spec = self._effective_light(i) or {}
            av = spec.get("axis", (0.0, -1.0, 0.0))
            aligned = max(range(3), key=lambda k: abs(av[k]))
            field_idx = 1 if axis == aligned else 0
            self._scale_grab = (field_idx, fields[field_idx]["value"])
        else:
            self._scale_grab = (0, fields[0]["value"])          # uniform -> radius

    def _apply_scale_drag(self, t_now: float) -> None:
        """Scale the grabbed field to `grab_value * (t_now / grab_param)`,
        with the grab param floored at a quarter of the gizmo length so a
        drag past the origin can't invert or divide-by-zero."""
        if self._axis_drag is None:
            return
        from engine.ui.ship_property_viewer import gizmo_length
        L = gizmo_length(self.camera)
        ratio = t_now / max(self._axis_grab_param, 0.25 * L)
        idx, grab_val = self._scale_grab
        self._set_scale_field(idx, grab_val * ratio)

    def _begin_ring_drag(self, ring, grab_angle):
        """Start a ring drag on `ring` (0/1/2), capturing the grabbed screen
        angle, the grab-start axis/orientation + degree accumulators, and the
        screen-vs-body sign (so a screen-CCW sweep rotates about the axis
        toward the camera)."""
        g = self._active_gizmo()
        self._axis_drag = ring
        self._axis_grab_origin = g["origin"] if g else (0.0, 0.0, 0.0)
        self._ring_grab_angle = grab_angle
        t = self._rotate_target()
        if t is None:
            self._ring_grab_axis = (0.0, -1.0, 0.0)
            self._ring_grab_orientation = ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            self._ring_grab_accum = [0.0, 0.0, 0.0]
            self._ring_sign = 1.0
            return
        _, i = t
        spec = self._effective_light(i) or {}
        self._ring_grab_axis = tuple(spec.get("axis") or (0.0, -1.0, 0.0))
        self._ring_grab_orientation = spec.get("orientation") \
            or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self._ring_grab_accum = list(self._rotate_accum.get(i, [0.0, 0.0, 0.0]))
        eye, tgt = self.camera.eye(), self.camera.target
        fwd = (tgt[0]-eye[0], tgt[1]-eye[1], tgt[2]-eye[2])
        wa = g["axes"][ring] if g else (0.0, 0.0, 1.0)
        d = wa[0]*fwd[0] + wa[1]*fwd[1] + wa[2]*fwd[2]
        # Screen-CCW should rotate about the axis toward the camera. If it feels
        # inverted in-game, flip this comparison.
        self._ring_sign = -1.0 if d > 0.0 else 1.0

    def _apply_ring_drag_angle(self, d_body):
        """Apply a body-frame delta angle (radians) about the grabbed ring axis
        to the grab-start axis/orientation. Shared core for the cursor-driven
        drag + tests. Shape-aware: a Cylinder rotates its `axis`; a Box
        rotates BOTH `forward` and `up` of the grab-start orientation, then
        re-orthonormalizes."""
        t = self._rotate_target()
        if t is None or self._axis_drag is None:
            return
        _, i = t
        from engine.ui.ship_property_viewer import (
            rotate_about_axis, orthonormalize_basis)
        k = self._axis_drag
        spec = dict(self._effective_light(i) or {})
        if not spec:
            return
        if spec.get("shape") == "Box":
            fwd, up = self._ring_grab_orientation
            fwd = rotate_about_axis(fwd, k, d_body)
            up = rotate_about_axis(up, k, d_body)
            spec["orientation"] = orthonormalize_basis(fwd, up)
        else:
            spec["axis"] = rotate_about_axis(self._ring_grab_axis, k, d_body)
        self._pending_light[i] = spec
        self._rotate_accum.setdefault(i, [0.0, 0.0, 0.0])
        self._rotate_accum[i][k] = self._ring_grab_accum[k] + math.degrees(d_body)
        self._last_pushed = None

    def _apply_ring_drag(self, x, y, fb_size):
        """Map the cursor's screen angle to a body-frame delta about the grabbed
        ring axis (unwrapped to (-pi, pi], signed by `_ring_sign`)."""
        from engine.ui.ship_property_viewer import ring_drag_angle
        ang = ring_drag_angle(x, y, self._axis_grab_origin, self.camera, fb_size())
        d = ang - self._ring_grab_angle
        while d > math.pi:
            d -= 2.0 * math.pi
        while d < -math.pi:
            d += 2.0 * math.pi
        self._apply_ring_drag_angle(d * self._ring_sign)

    def _begin_axis_drag(self, axis: int, grab_param: float) -> None:
        """Start an axis drag on `axis` (0/1/2), capturing the fixed drag-start
        body position and world origin so the drag mapping stays stable."""
        target = self._active_transform_target()
        if target is None:
            return
        kind, i = target
        self._axis_drag = axis
        self._axis_grab_param = grab_param
        if kind == "light":
            self._axis_grab_pos = tuple(self._effective_light(i)["position"])
            ship = self._ship_getter()
            if ship is not None and hasattr(ship, "GetWorldRotation"):
                from engine.ui.ship_property_viewer import world_from_body
                self._axis_grab_origin = world_from_body(
                    ship, self._axis_grab_pos)
        else:
            self._axis_grab_pos = self._effective_pos(i)
            self._axis_grab_origin = self._effective_world_pos(i)

    def _begin_axis_drag_for_test(self, axis: int, grab_param: float) -> None:
        """Test seam: identical to a press-edge grab, without a host/gizmo."""
        self._begin_axis_drag(axis, grab_param)

    def _apply_axis_drag(self, param_now: float) -> None:
        """Move the selected node to grab_pos with the grabbed axis component
        advanced by (param_now - grab_param)."""
        target = self._active_transform_target()
        if self._axis_drag is None or target is None:
            return
        kind, i = target
        k = self._axis_drag
        base = list(self._axis_grab_pos)
        base[k] += (param_now - self._axis_grab_param)
        if kind == "light":
            self.set_light_position(i, tuple(base))
        else:
            self.set_subsystem_position(i, tuple(base))

    def _end_axis_drag(self) -> None:
        self._axis_drag = None

    def selected_subsystem_sphere(self) -> Optional[dict]:
        """Wireframe sphere for the selected subsystem's damage volume, or None.

        `center` is the subsystem world position (where its icon sits) and
        `radius` its GetRadius() (with any staged/saved Set Radius edit applied,
        so Apply/Save preview live) — the only geometric size a subsystem
        exposes, so every subsystem is a sphere. None when nothing is selected
        or the radius is missing/non-positive. Consumed by host_loop via
        engine.renderer.set_debug_spheres (viewer-mode only).

        No logic change needed for light selection: `selected_index` is always
        cleared whenever a light is selected (mutual-exclusion invariant), so
        this already returns None while a light node is selected."""
        sel = self.selected_index
        if sel is None or not (0 <= sel < len(self._descriptors)):
            return None
        d = self._descriptors[sel]
        r = self._effective_radius(sel, d.get("properties", {}).get("radius"))
        try:
            r = float(r)
        except (TypeError, ValueError):
            return None
        if r <= 0.0:
            return None
        return {"center": self._effective_world_pos(sel), "radius": r,
                "color": SUBSYS_SPHERE_COLOR}

    def subsystem_pins(self) -> List[tuple]:
        """Billboard pins to render, as (world_pos, icon_id, is_selected).

        Light selected -> show only its parent subsystem's pin (anchor icon);
        the glow wireframe is the focus. Subsystem selected -> only that pin
        (all others hidden) so the hologram isn't cluttered around the focused
        subsystem. Nothing selected -> every pin renders. Deselecting restores
        them all. (Pin PICKING still uses the full descriptor set — see
        pick_at — so clicking empty space deselects and reveals every pin
        again.)"""
        if self._selected_light_index is not None:
            i = self._selected_light_index
            if 0 <= i < len(self._descriptors):
                d = self._descriptors[i]
                return [(d["world_pos"], d["icon_id"], False)]
            return []
        sel = self.selected_index
        if sel is not None and 0 <= sel < len(self._descriptors):
            d = self._descriptors[sel]
            return [(self._effective_world_pos(sel), d["icon_id"], True)]
        return [(d["world_pos"], d["icon_id"], False) for d in self._descriptors]

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

    def selected_light_name(self) -> Optional[str]:
        """GetName() of the subsystem whose light is selected, or None."""
        i = self._selected_light_index
        if i is not None and 0 <= i < len(self._descriptors):
            return self._descriptors[i].get("name")
        return None

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible, len(self._descriptors), self.selected_index,
                    self._selected_light_index, self.active_tool,
                    self.show_glow_regions, self.show_weapon_arcs,
                    self.show_hull_texture,
                    tuple(sorted(self._pending_radius.items())),
                    tuple(sorted(self._pending_light)),   # indices with a staged light
                    tuple(sorted(self._pending_pos.items())),
                    tuple(sorted(self._expanded_groups)),
                    self._coord_clipboard,
                    self._scale_clipboard,
                    self._rotate_clipboard,
                    tuple(sorted((k, tuple(v)) for k, v in self._rotate_accum.items())))
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setShipPropertyViewer(" + json.dumps({"visible": False}) + ");"
        selected = None
        if self.selected_index is not None and \
                0 <= self.selected_index < len(self._descriptors):
            selected = dict(self._descriptors[self.selected_index])
            _props0 = selected.get("properties", {})
            _eff = self._effective_radius(self.selected_index, _props0.get("radius"))
            if _eff != _props0.get("radius"):
                props = dict(_props0)
                props["radius"] = _eff
                selected["properties"] = props
            _cur_props = selected.get("properties", {})
            _effpos = self._effective_pos(self.selected_index)
            if _effpos != _cur_props.get("position"):
                props = dict(_cur_props)
                props["position"] = _effpos
                selected["properties"] = props
        payload = {
            "visible": True,
            "pin_count": len(self._descriptors),
            "selected": selected,
            "selected_index": self.selected_index,
            "selected_light_index": self._selected_light_index,
            "active_tool": self.active_tool,
            "transform_coords": self.transform_coords(),
            "scale_values": self.scale_values(),
            "rotate_values": self.rotate_values(),
            "show_glow": self.show_glow_regions,
            "show_arcs": self.show_weapon_arcs,
            "show_hull": self.show_hull_texture,
            "pending_count": len(set(self._pending_radius) | set(self._pending_light)
                                 | set(self._pending_pos)),
            "pending": self._pending_edits(),
            "subsystems": self._subsystem_rows(),
            "close_overlays": self._close_overlays,
        }
        self._close_overlays = False
        return "setShipPropertyViewer(" + json.dumps(payload) + ");"

    def _pending_edits(self) -> List[dict]:
        """Modified subsystems with a tally of staged changes each, for the
        Save-confirm modal, e.g. [{"name": "Center Impulse", "count": 1}].
        Grouped by subsystem name; a subsystem with both a staged radius and
        a staged light/glow-region edit shows count 2. Deterministic order:
        first-seen by ascending descriptor index."""
        counts: dict = {}
        order: List[str] = []
        for i in sorted(set(self._pending_radius) | set(self._pending_light)
                         | set(self._pending_pos)):
            name = self._descriptors[i]["name"]
            if name not in counts:
                counts[name] = 0
                order.append(name)
            counts[name] += (1 if i in self._pending_radius else 0)
            counts[name] += (1 if i in self._pending_light else 0)
            counts[name] += (1 if i in self._pending_pos else 0)
        return [{"name": n, "count": counts[n]} for n in order]

    def _subsystem_rows(self) -> List[dict]:
        """Left-column subsystem list as a two-level accordion: top-level
        category rows with their child pods/banks/tubes nested under them
        (parent_index links, mirroring the ship's aggregator structure).
        Every row carries `index` — its pin-descriptor index — so a row
        click can fire select_pin:<index> regardless of nesting."""
        def _row(i: int, d: dict) -> dict:
            return {
                "index": i,
                "name": d.get("name", ""),
                "targetable": bool(d.get("targetable", False)),
                "condition_pct": d.get("condition_pct"),
                "kind": d.get("kind", "subsystem"),
                "children": [],
            }
        rows: List[dict] = []
        by_index: dict = {}
        for i, d in enumerate(self._descriptors):
            row = _row(i, d)
            row["dirty"] = ((i in self._pending_radius) or (i in self._pending_light)
                             or (i in self._pending_pos))
            row["radius"] = self._effective_radius(
                i, d.get("properties", {}).get("radius"))
            row["has_light"] = self._has_light(i)
            by_index[i] = row
            parent = by_index.get(d.get("parent_index"))
            if parent is not None:
                parent["children"].append(row)
            else:
                rows.append(row)
        # Light-volume child node under any subsystem that has one.
        for i in range(len(self._descriptors)):
            if self._has_light(i):
                by_index[i]["children"].append({
                    "kind": "light",
                    "name": "Light Volume",
                    "light_of": i,
                    "light_region": self._effective_light(i),
                    "dirty": (i in self._pending_light),
                })
        for row in by_index.values():
            if row["children"]:
                row["expanded"] = row["name"] in self._expanded_groups
        return rows

    def pending_light_specs(self) -> dict:
        """{subsystem_name: spec|None} overriding the baked overlay. A spec draws
        the staged/saved light; None hides a removed one. Saved then pending so a
        fresh stage wins."""
        out: dict = {}
        for source in (self._saved_light, self._pending_light):
            for i, spec in source.items():
                if 0 <= i < len(self._descriptors):
                    out[self._descriptors[i]["name"]] = spec
        return out

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        """ESC is dispatched raw by host_loop's modal-ESC router, independent
        of CEF focus (see `_dispatch_modal_esc`) — so it must be the single
        source of truth for "does ESC close the overlay or the panel", to
        avoid a JS-vs-native race. While a CEF overlay (context menu / radius
        modal / confirm) is open, ESC closes ONLY the overlay and preserves
        any staged edits; only when no overlay is open does ESC close the
        panel (discarding staged edits, matching the existing Cancel/close
        behaviour)."""
        if not self._visible:
            return
        if self._overlay_open:
            self._overlay_open = False
            self._close_overlays = True
            self._last_pushed = None
            return
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
        if self._overlay_open:
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
        fb_w = fb_h = 0.0
        try:
            fb_w, fb_h = fb_size()
        except (TypeError, ValueError):
            fb_w = fb_h = 0.0
        win_size = getattr(h, "window_size", None)
        if win_size is not None and fb_h > 0:
            try:
                _win_w, win_h = win_size()
                if win_h > 0:
                    dsf = float(fb_h) / float(win_h)
            except (TypeError, ValueError, ZeroDivisionError):
                dsf = 1.0

        x, y = cursor_pos()
        over_tools = self._cursor_over_tools(x, y, dsf, fb_w, fb_h)
        # Only guard the coord-panel region while the panel is actually
        # visible (Transform tool active + a target selected) — otherwise the
        # top-right rectangle would be a dead zone that swallows orbit-drag
        # starts and pin picks whenever the panel is hidden.
        over_coords = ((self.transform_coords() is not None
                        or self.scale_values() is not None
                        or self.rotate_values() is not None)
                       and self._cursor_over_coords(x, y, dsf, fb_w, fb_h))
        over_chrome = (self._cursor_over_chrome(x, y, dsf) or over_tools
                       or over_coords)
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

        # Transform-gizmo axis drag takes priority over orbit/pin: a press on a
        # gizmo shaft grabs that axis and drags the subsystem along it (orbit
        # suppressed, no pin pick on release). When no axis is grabbed this only
        # updates the hover highlight and returns False, so every existing path
        # (orbit / pick / chrome / zoom) runs untouched below.
        if self._handle_gizmo_input(x, y, down, over_chrome, dsf, fb_size):
            return

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

    def _handle_gizmo_input(self, x, y, down, over_chrome, dsf, fb_size) -> bool:
        """Gizmo hover / axis grab / drag / release. Returns True when it
        consumed the event (an axis drag was active or started/ended this
        frame), so the caller skips the orbit/pin block. Returns False (and
        leaves all edge bookkeeping to the caller) otherwise. Degrades to a
        no-op returning False if the gizmo helpers/camera aren't available."""
        try:
            from engine.ui.ship_property_viewer import (
                pick_gizmo_axis, axis_drag_param, gizmo_length,
                pick_gizmo_ring, ring_drag_angle,
            )
        except ImportError:
            return False

        # An axis drag is in progress — own the whole press/drag/release cycle.
        if self._axis_drag is not None:
            if not down:
                # Release edge: end the drag; no pin pick.
                self._end_axis_drag()
                self._lmb_down = False
                self._drag_last = None
                self._press_pos = None
                self._drag_dist = 0.0
                self._chrome_press = False
                self._gizmo_hover = -1
                return True
            # Drag: map the cursor onto the FIXED drag-start shaft so the
            # mapping stays stable as the origin moves with the subsystem.
            g = self._active_gizmo()
            if g is not None:
                if self.active_tool == "rotate":
                    self._apply_ring_drag(x, y, fb_size)
                else:
                    t = axis_drag_param(x, y, self._axis_grab_origin,
                                        g["axes"][self._axis_drag],
                                        gizmo_length(self.camera), self.camera,
                                        fb_size())
                    if self.active_tool == "scale":
                        self._apply_scale_drag(t)
                    else:
                        self._apply_axis_drag(t)
            self._drag_last = (x, y)
            return True

        g = self._active_gizmo()
        if g is None or over_chrome:
            self._gizmo_hover = -1
            return False

        # Press edge: try to grab an axis. If none, fall through to orbit-press.
        if down and not self._lmb_down:
            if self.active_tool == "rotate":
                ring = pick_gizmo_ring(x, y, g["origin"], g["axes"], g["length"],
                                       self.camera, fb_size(), dsf)
                if ring is None:
                    return False
                self._begin_ring_drag(
                    ring, ring_drag_angle(x, y, g["origin"], self.camera,
                                          fb_size()))
                self._gizmo_hover = ring
            else:
                axis = pick_gizmo_axis(x, y, g["origin"], g["axes"], g["length"],
                                       self.camera, fb_size(), dsf)
                if axis is None:
                    return False
                t_grab = axis_drag_param(x, y, g["origin"], g["axes"][axis],
                                         g["length"], self.camera, fb_size())
                if self.active_tool == "scale":
                    self._begin_scale_drag(axis, t_grab)
                else:
                    self._begin_axis_drag(axis, t_grab)
                self._gizmo_hover = axis
            self._chrome_press = False
            self._lmb_down = True
            self._drag_last = (x, y)
            self._press_pos = (x, y)
            self._drag_dist = 0.0
            return True

        # Not a press edge and no active drag: hover highlight only (idle).
        if not down:
            if self.active_tool == "rotate":
                hov = pick_gizmo_ring(x, y, g["origin"], g["axes"], g["length"],
                                      self.camera, fb_size(), dsf)
            else:
                hov = pick_gizmo_axis(x, y, g["origin"], g["axes"], g["length"],
                                      self.camera, fb_size(), dsf)
            self._gizmo_hover = hov if hov is not None else -1
        return False

    @staticmethod
    def _cursor_over_left_column(x: float, y: float, dsf: float) -> bool:
        """Cursor (framebuffer px) inside the left tool/subsystem column."""
        s = dsf or 1.0
        return (x / s) <= LEFT_COL_X1_PT and (y / s) >= LEFT_COL_Y0_PT

    @staticmethod
    def _cursor_over_tools(x: float, y: float, dsf: float,
                          fb_w: float, fb_h: float) -> bool:
        """Cursor (framebuffer px) inside the bottom-right tool-button
        cluster — BOTH rows: the render-tools row (#spv-tools) and the
        transform-tools row (#spv-transform-tools) stacked directly above it.

        Needs the viewport size (framebuffer px) because the cluster is anchored
        to the right/bottom edges. Returns False when the size is unknown."""
        if fb_w <= 0 or fb_h <= 0:
            return False
        s = dsf or 1.0
        px, py = x / s, y / s
        w_pt, h_pt = fb_w / s, fb_h / s
        x0 = w_pt - TOOLS_MARGIN_PT - TOOLS_W_PT
        x1 = w_pt - TOOLS_MARGIN_PT
        y0 = h_pt - TOOLS_MARGIN_PT - TOOLS_CLUSTER_H_PT
        y1 = h_pt - TOOLS_MARGIN_PT
        return x0 <= px <= x1 and y0 <= py <= y1

    @staticmethod
    def _cursor_over_coords(x: float, y: float, dsf: float,
                            fb_w: float, fb_h: float) -> bool:
        """Cursor (framebuffer px) inside the top-right coord panel box.
        Returns False when the viewport width is unknown."""
        if fb_w <= 0:
            return False
        s = dsf or 1.0
        px, py = x / s, y / s
        w_pt = fb_w / s
        x1 = w_pt - COORDS_MARGIN_PT
        x0 = x1 - COORDS_W_PT
        y0 = COORDS_TOP_PT
        y1 = y0 + COORDS_H_PT
        return x0 <= px <= x1 and y0 <= py <= y1

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
        if action == "toggle_hull_texture":
            self.show_hull_texture = not self.show_hull_texture
            self._last_pushed = None  # re-push so the button state updates
            return True
        if action.startswith("select_pin:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if 0 <= idx < len(self._descriptors):
                self.selected_index = idx
                self._selected_light_index = None
                # Reveal the selection in the list: expand its group so a
                # 3D pin click never lands on a hidden row.
                pi = self._descriptors[idx].get("parent_index")
                if pi is not None and 0 <= pi < len(self._descriptors):
                    self._expanded_groups.add(
                        self._descriptors[pi].get("name", ""))
                self._last_pushed = None  # force re-push of popover
                return True
            return False
        if action.startswith("select_light:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if not (0 <= idx < len(self._descriptors)) or not self._has_light(idx):
                return False
            self._selected_light_index = idx
            self.selected_index = None
            self._expanded_groups.add(self._descriptors[idx].get("name", ""))
            self._last_pushed = None
            return True
        if action.startswith("add_light:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if not (0 <= idx < len(self._descriptors)) or self._has_light(idx):
                return False
            base = self._descriptors[idx].get("light_region")
            if not base:
                return False
            self._pending_light[idx] = dict(base)     # from-scratch default spec
            self._selected_light_index = idx
            self.selected_index = None
            self._expanded_groups.add(self._descriptors[idx].get("name", ""))
            self._last_pushed = None
            return True
        if action.startswith("remove_light:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if not (0 <= idx < len(self._descriptors)):
                return False
            self._pending_light[idx] = None           # removed sentinel
            if self._selected_light_index == idx:
                self._selected_light_index = None
            self._last_pushed = None
            return True
        if action.startswith("toggle_group:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if not (0 <= idx < len(self._descriptors)):
                return False
            name = self._descriptors[idx].get("name", "")
            self._expanded_groups.symmetric_difference_update({name})
            self._last_pushed = None
            return True
        if action == "deselect":
            if self.selected_index is None and self._selected_light_index is None:
                return False
            self.selected_index = None
            self._selected_light_index = None
            self._last_pushed = None
            return True
        if action.startswith("overlay:"):
            self._overlay_open = action.endswith("1")
            return True
        if action.startswith("set_radius:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                idx = int(arg["i"]); value = float(arg["value"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0 <= idx < len(self._descriptors)):
                return False
            if value <= 0:
                return False
            self._pending_radius[idx] = value
            self._last_pushed = None
            return True
        if action.startswith("set_light:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                idx = int(arg["i"]); shape = str(arg["shape"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0 <= idx < len(self._descriptors)):
                return False
            base = dict(self._effective_light(idx) or self._descriptors[idx].get("light_region") or {})
            pos = base.get("position") or (0.0, 0.0, 0.0)
            axis = base.get("axis") or (0.0, -1.0, 0.0)
            spec = {"shape": shape, "position": tuple(pos), "axis": tuple(axis),
                    "radius": base.get("radius") or (0.25,),
                    "extent": base.get("extent") or (0.0, 2.0),
                    "scale": base.get("scale") or (0.25, 0.25, 0.25)}
            try:
                if shape == "Sphere":
                    r = float(arg["radius"])
                    if r <= 0.0:
                        return False
                    spec["radius"] = (r,)
                elif shape == "Cylinder":
                    r = float(arg["radius"]); aft = float(arg["aft"]); fore = float(arg["fore"])
                    if r <= 0.0 or fore <= aft:
                        return False
                    spec["radius"] = (r,); spec["extent"] = (aft, fore)
                elif shape == "Box":
                    sx = float(arg["sx"]); sy = float(arg["sy"]); sz = float(arg["sz"])
                    if sx <= 0.0 or sy <= 0.0 or sz <= 0.0:
                        return False
                    spec["scale"] = (sx, sy, sz)
                else:
                    return False
            except (KeyError, TypeError, ValueError):
                return False
            self._pending_light[idx] = spec
            self._last_pushed = None
            return True
        if action.startswith("set_tool:"):
            name = action.split(":", 1)[1]
            if name not in ("transform", "rotate", "scale"):
                return False
            self.active_tool = None if self.active_tool == name else name
            self._last_pushed = None
            return True
        if action.startswith("coord_nudge:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                axis = int(arg["axis"]); delta = float(arg["delta"])
            except (ValueError, KeyError, TypeError):
                return False
            if axis not in (0, 1, 2):
                return False
            pos = self._transform_target_pos()
            if pos is None:
                return False
            p = list(pos); p[axis] += delta
            self._set_transform_target_pos(tuple(p))
            self._last_pushed = None
            return True
        if action == "coord_copy":
            pos = self._transform_target_pos()
            if pos is not None:
                self._coord_clipboard = pos
                self._last_pushed = None
            return True
        if action == "coord_paste":
            if self._coord_clipboard is not None and self._transform_target_pos() is not None:
                self._set_transform_target_pos(self._coord_clipboard)
                self._last_pushed = None
            return True
        if action == "coord_mirror":
            pos = self._transform_target_pos()
            if pos is not None:
                p = list(pos); p[0] = -p[0]
                self._set_transform_target_pos(tuple(p))
                self._last_pushed = None
            return True
        if action.startswith("scale_nudge:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                index = int(arg["index"]); delta = float(arg["delta"])
            except (ValueError, KeyError, TypeError):
                return False
            t = self._active_transform_target()
            if t is None:
                return False
            kind, fields = self._scale_kind_and_fields(t)
            if not (0 <= index < len(fields)):
                return False
            self._set_scale_field(index, fields[index]["value"] + delta)
            return True
        if action == "scale_copy":
            t = self._active_transform_target()
            if t is not None:
                kind, fields = self._scale_kind_and_fields(t)
                self._scale_clipboard = (kind, tuple(f["value"] for f in fields))
                self._last_pushed = None
            return True
        if action == "scale_paste":
            t = self._active_transform_target()
            if t is not None and self._scale_clipboard is not None:
                kind, fields = self._scale_kind_and_fields(t)
                if self._scale_clipboard[0] == kind:
                    for idx, v in enumerate(self._scale_clipboard[1]):
                        self._set_scale_field(idx, v)
            return True
        if action == "scale_uniform":
            t = self._active_transform_target()
            if t is not None:
                kind, fields = self._scale_kind_and_fields(t)
                if kind == "xyz":
                    m = max(f["value"] for f in fields)
                    for idx in range(3):
                        self._set_scale_field(idx, m)
            return True
        if action.startswith("rotate_nudge:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                axis = int(arg["axis"]); delta = float(arg["delta"])
            except (ValueError, KeyError, TypeError):
                return False
            if axis not in (0, 1, 2) or self._rotate_target() is None:
                return False
            self._rotate_axis(axis, delta)
            return True
        if action == "rotate_copy":
            t = self._rotate_target()
            if t is not None:
                _, i = t
                spec = self._effective_light(i) or {}
                if spec.get("shape") == "Box":
                    fwd, up = spec.get("orientation") \
                        or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
                    self._rotate_clipboard = (
                        "box_orientation", (tuple(fwd), tuple(up)))
                else:
                    axis = spec.get("axis") or (0.0, -1.0, 0.0)
                    self._rotate_clipboard = ("cylinder_axis", tuple(axis))
                self._last_pushed = None
            return True
        if action == "rotate_paste":
            t = self._rotate_target()
            if (t is not None and self._rotate_clipboard is not None
                    and self._rotate_clipboard[0] == self._rotate_clipboard_kind(t[1])):
                _, i = t
                if self._rotate_clipboard[0] == "box_orientation":
                    fwd, up = self._rotate_clipboard[1]
                    self._set_orientation_absolute(i, fwd, up)
                else:
                    self._set_axis_absolute(i, self._rotate_clipboard[1])
            return True
        if action == "rotate_mirror":
            t = self._rotate_target()
            if t is not None:
                _, i = t
                spec = self._effective_light(i) or {}
                if spec.get("shape") == "Box":
                    fwd, up = spec.get("orientation") \
                        or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
                    fwd = (-fwd[0], fwd[1], fwd[2])
                    up = (-up[0], up[1], up[2])
                    self._set_orientation_absolute(i, fwd, up)
                else:
                    axis = list((self._effective_light(i) or {}).get("axis")
                                or (0.0, -1.0, 0.0))
                    axis[0] = -axis[0]
                    self._set_axis_absolute(i, axis)
            return True
        if action == "save":
            if (not self._pending_radius and not self._pending_light
                    and not self._pending_pos):
                return True
            ship = self._ship_getter()
            leaf = hardpoint_leaf_for_ship(ship)
            if not leaf:
                # Target can't be resolved — nothing written. Keep the staged
                # edits so the user can retry (e.g. after fixing the ship).
                self._last_pushed = None
                return True
            edits = [(self._descriptors[i]["name"], "SetRadius", (v,))
                     for i, v in sorted(self._pending_radius.items())]
            edits += [(self._descriptors[i]["name"], "__region__", 0,
                       region_spec_to_calls(0, spec) if spec is not None else [])
                      for i, spec in sorted(self._pending_light.items())]
            edits += [(self._descriptors[i]["name"], "SetPosition", tuple(v))
                      for i, v in sorted(self._pending_pos.items())]
            try:
                resolve_override_target(ship).write(leaf, edits)
            except Exception as e:
                from engine import dev_mode
                dev_mode.log_swallowed("spv light/radius save", e)
                # Write failed — keep the staged edits (dirty markers + Save
                # bar stay) rather than silently discarding them.
                self._last_pushed = None
                return True
            # Keep the just-saved edits driving the in-session preview (volume
            # sphere for radius, wireframe for glow): the file write only reaches
            # the live template on the next ship build, so without this the
            # preview would snap back to the old baked value right after Save
            # (they are no longer "dirty", though).
            self._saved_radius.update(self._pending_radius)
            self._pending_radius = {}
            self._saved_light.update(self._pending_light)
            self._pending_light = {}
            self._saved_pos.update(self._pending_pos)
            self._pending_pos = {}
            self._last_pushed = None
            return True
        return False
