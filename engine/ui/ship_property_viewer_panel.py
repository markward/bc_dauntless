"""Ship Property Viewer pause-menu modal (Panel subclass).

Mirrors engine.ui.developer_options_panel: pumped by PanelRegistry, opened from
the dev pause menu. Snapshot-diffs its payload like the other panels.
Spec: docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

import json
import math
import time
from typing import Callable, List, Optional

from engine.appc.override_routing import (
    resolve_override_target, hardpoint_leaf_for_ship,
)
from engine.ui.panel import Panel
from engine.ui.ship_property_viewer import (
    build_descriptors, OrbitCamera, pick_pin, region_spec_to_calls,
    emitter_spec_to_calls,
)
from engine.ui import ship_property_viewer as _spv

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
# Action-tools row (#spv-action-tools: Undo / Pipette / Mirror), stacked
# directly above #spv-transform-tools with the same TOOLS_GAP_PT.
ACTION_H_PT = TOOLS_BTN_PT
TOOLS_CLUSTER_H_PT = (TOOLS_H_PT + TOOLS_GAP_PT + TRANSFORM_H_PT
                      + TOOLS_GAP_PT + ACTION_H_PT)

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

# Model Parts nodes (spec 2026-09-25 section 7). A state's node label is
# "<label> Transformation".
STATE_LABELS = {"cruise": "Cruising", "yellow": "Yellow Alert",
                "red": "Red Alert", "warp": "Warp"}
# A new {State} Transformation starts at the NIF pose.
IDENTITY_POSE6 = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
# Make Breakable starts a part at 20% of the ship's max hull.
DEFAULT_BREAK_FRACTION = 0.20
# How long a toast stays at the top of the SPV (spec section 7.4).
TOAST_SECONDS = 3.0
TOAST_NO_ANCHOR = "Add an anchor first — transformations swing around it"
TOAST_ANCHOR_IN_USE = ("Remove the transformations first — they swing around "
                       "the anchor")


class ShipPropertyViewerPanel(Panel):
    # Actions the dispatch_event undo wrapper does not snapshot around:
    # "undo" itself, "save"/"cancel" (which clear/discard state wholesale
    # rather than mutate it), and any "overlay:" chrome toggle.
    _NO_UNDO_ACTIONS = ("undo", "save", "cancel")

    def __init__(self, ship_getter: Callable[[], object],
                 on_saved: Optional[Callable[[object, dict], None]] = None,
                 iid_getter: Optional[Callable[[], Optional[int]]] = None,
                 on_regions_saved: Optional[Callable[[object, dict], None]] = None,
                 ) -> None:
        super().__init__()
        self._ship_getter = ship_getter
        # Optional caller hook invoked after a successful Save with
        # (ship, regions_by_sub_id): the effective glow-region list per
        # subsystem, so the host can re-register them without a mission
        # reload (host_loop.refresh_ship_glow). Construction-time config.
        self._on_regions_saved = on_regions_saved
        # Resolves the player ship's renderer InstanceId (session.ship_
        # instances[ship]) for host_io.model_nodes(iid) -- the Model Parts
        # pane's node list. Optional: a caller that never wires it (or a test)
        # just sees an empty pane. Construction-time config, not session
        # state: never reset in open()/close().
        self._iid_getter = iid_getter
        # Optional caller hook invoked after a successful Save with
        # (ship, specs_by_sub_id) — see the "save" action handler below.
        # Construction-time config, not session state: never reset in
        # open()/close().
        self._on_saved = on_saved
        self._visible = False
        self._descriptors: List[dict] = []
        # Model Parts pane: the ship's mesh nodes (host_io.model_nodes),
        # snapshotted once at open() like _descriptors (the mesh doesn't
        # change mid-session). "show all" defaults off every open — the
        # pane always starts hiding exporter plumbing.
        self._model_part_nodes: List[dict] = []
        self._model_parts_show_all: bool = False
        # Staged part edits: part name -> full merged spec
        # ({"anchor","transition","poses","break"}). Whole-spec-per-name, like
        # _pending_light -- any single-field edit re-stages the full merged
        # spec (see _effective_part) so a later save never loses a field the
        # designer isn't currently touching. Reset every open/close.
        self._pending_part: dict = {}
        # Part edits saved THIS session -- same persist->reload story as
        # _saved_light/_saved_radius/_saved_emitter/_saved_pos (the write only
        # reaches the live ArticulatedPartProperty snapshot on the next ship
        # build). Survives close/reopen of the SAME ship; dropped on a ship-
        # identity change in open() alongside the others (_clear_saved_edits).
        self._saved_part: dict = {}
        # Toast shown at the top of the SPV: (text, expires_at monotonic
        # seconds) or None. Reset every open/close. See _show_toast.
        self._toast: Optional[tuple] = None
        # The part pose `_sync_part_pose` last forced: (part, state, p6) while
        # a {State} Transformation node is selected, None for the NIF pose.
        self._applied_part_pose: Optional[tuple] = None
        self.selected_index: Optional[int] = None
        # Active transform-gizmo tool: None|"transform"|"rotate"|"scale".
        # Mutually exclusive radio, reset every open/close.
        self.active_tool: Optional[str] = None
        # Selected LIGHT volume (descriptor index of the subsystem whose light
        # is selected), mutually exclusive with selected_index. Shows only that
        # light's glow wireframe; the parent radius sphere is hidden.
        self._selected_light_index: Optional[int] = None
        # Selected LIGHT EMITTER (subsystem_idx, emitter_idx), mutually
        # exclusive with selected_index and _selected_light_index (highest
        # priority — see _active_transform_target). One subsystem can have
        # 0..N emitters, so this is keyed by (i, j) not a single index.
        self._selected_emitter: Optional[tuple] = None
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
        # Staged/saved light-EMITTER edits: subsystem_idx -> the FULL
        # compacted emitter list for that subsystem (whole-list-per-
        # subsystem, not a per-(i,j) sentinel dict). Emitter indices must
        # stay dense (0..N-1, no gaps) because baked_emitters() stops at the
        # first unset LightEmitterKind on reload — a (i,j)-keyed removal
        # sentinel would leave a gap that truncates every later emitter on
        # the next ship build. Same persist->reload story as
        # _pending_light/_saved_light otherwise. See _effective_emitter(s).
        self._pending_emitter: dict = {}
        self._saved_emitter: dict = {}
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
        # Undo stack: list of snapshots (deep copies of the four staged-edit
        # dicts), one per real mutation. Pending-only — no redo, cleared on
        # Save. Reset every open/close. See _snapshot_pending/undo.
        self._undo_stack: list = []
        # Transient snapshot captured at drag-begin, committed at drag-end.
        self._drag_undo_before = None
        # Pipette eyedropper: armed on the selected target, disarmed by the
        # next source pick (or ESC). Reset every open/close.
        self._pipette_armed = False
        # Saved (persisted-to-file) edits are an in-memory overlay on top of the
        # baked descriptors — the live subsystem property is only updated on the
        # next ship build, so build_descriptors keeps reading the ORIGINAL until
        # then. This overlay SURVIVES close/reopen of the same ship (so a
        # re-opened SPV reflects edits saved this session), and is dropped only
        # when the player ship IDENTITY changes (a respawn applies the file to
        # the fresh property, making the overlay stale). See open().
        self._authored_ship_id = None
        self._saved_radius = {}
        self._saved_light = {}
        self._saved_emitter = {}
        self._saved_pos = {}
        self._saved_part = {}

    @property
    def name(self) -> str:
        return "ship-property-viewer"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._last_pushed = None
        ship = self._ship_getter()
        # ── Settle the POSE before anything reads it ──────────────────────
        # This runs FIRST, above build_descriptors, and the order is the
        # feature. `build_descriptors` resolves `subsystem_world_position`
        # once and CACHES it as `descriptor["world_pos"]`; that tuple is what
        # `subsystem_pins()` hands the renderer and what `pick_pin` picks
        # against. Build it first and every pin is captured in the ship's
        # live articulated pose, so forcing the anchor pose afterwards moves
        # the hull and leaves the pins floating clear of it -- shipped twice.
        #
        # Preview lock (Task 7): a stale forced state from whatever was open
        # before (or left by the 'K' dev keybinding) must not carry into a
        # freshly-opened ship -- the lock is read live from
        # articulation.dev_override() (see _mount_lock_state_and_reason), so
        # clearing it here is the only reset this needs.
        from engine.appc import articulation as _articulation
        _articulation.set_dev_override(None)
        # ...and SNAP this ship to that released state's pose right now. The
        # SPV freezes the sim, so `tick_ship` will not run again until it
        # closes: without this the hull would keep whatever angles it held
        # when the pause menu opened, and a mount authored through it would
        # be recorded ~0.9 ship units out at a wingtip. force_pose writes the
        # ONE dict every reader of a live pose consults, so the mesh, the
        # pins and the derived-box queries all resolve the same angle.
        _articulation.force_pose(ship, None)
        # No part node survives a reopen: the pose just forced is the NIF
        # pose, which is what "no State Transformation selected" means.
        _spv.select_part_node(None, None)
        self._applied_part_pose = None
        self._toast = None
        # ── ...and only now resolve anything FROM it ──────────────────────
        self._descriptors = build_descriptors(ship) if ship is not None else []
        self._model_part_nodes = self._fetch_model_part_nodes()
        self._model_parts_show_all = False
        self.selected_index = None
        self._selected_light_index = None
        self._selected_emitter = None
        self.active_tool = None
        self.show_glow_regions = False
        self.show_weapon_arcs = False
        self.show_hull_texture = False
        self._expanded_groups = set()
        self._pending_radius = {}
        self._pending_light = {}
        self._pending_emitter = {}
        self._pending_pos = {}
        self._pending_part = {}
        # Persist the saved-edit overlay across open/close of the SAME ship so a
        # re-opened SPV reflects edits saved this session (build_descriptors
        # reads the still-original property until the next ship build). Drop it
        # only when the ship identity changed — a respawn already applied the
        # file to the fresh property, so the stale overlay would shadow it.
        sid = id(ship) if ship is not None else None
        if sid != self._authored_ship_id:
            self._clear_saved_edits()
            self._authored_ship_id = sid
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
        self._undo_stack = []
        self._drag_undo_before = None
        self._pipette_armed = False
        target = self._fit_target()
        self.camera = OrbitCamera(target=target, distance=self._fit_distance(target))
        self.visible = True

    def _clear_saved_edits(self) -> None:
        """Drop the persisted-edit overlay. Called from open() when the authored
        ship identity changed (a respawn applied the file to the fresh property,
        so the overlay would only shadow the now-correct baked values)."""
        self._saved_radius = {}
        self._saved_light = {}
        self._saved_emitter = {}
        self._saved_pos = {}
        self._saved_part = {}

    def close(self) -> None:
        self.visible = False
        self._descriptors = []
        self._model_part_nodes = []
        self._model_parts_show_all = False
        self.selected_index = None
        self._selected_light_index = None
        self._selected_emitter = None
        self.active_tool = None
        self.show_glow_regions = False
        self.show_weapon_arcs = False
        self.show_hull_texture = False
        self._expanded_groups = set()
        self._pending_radius = {}
        self._pending_light = {}
        self._pending_emitter = {}
        self._pending_pos = {}
        self._pending_part = {}
        from engine.appc import articulation as _articulation
        # Closing returns every part to the NIF pose (spec section 7.3) -- the
        # pose the viewer opened in, so a State Transformation previewed here
        # never leaks out as the ship's live pose. The sim then resumes and
        # `tick_ship` eases the rig from there toward `state_for(ship)` over
        # each part's transition, exactly as it would after an open/close with
        # nothing selected.
        _articulation.force_pose(self._ship_getter(), None)
        _articulation.set_dev_override(None)
        _spv.select_model_part(None, self._model_part_nodes)
        self._applied_part_pose = None
        self._toast = None
        # NOTE: _saved_* (and _authored_ship_id) deliberately persist across
        # close so a reopen of the same ship still shows edits saved this
        # session. They are dropped in open() on a ship-identity change.
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
        self._undo_stack = []
        self._drag_undo_before = None
        self._pipette_armed = False

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

    def _fetch_model_part_nodes(self) -> List[dict]:
        """host_io.model_nodes(iid) for the current ship, or [] when the ship
        or its renderer instance id can't be resolved (headless, no
        iid_getter wired, or between missions) -- the Model Parts pane just
        shows no rows in that case rather than raising."""
        if self._iid_getter is None:
            return []
        try:
            iid = self._iid_getter()
        except Exception:
            return []
        if iid is None:
            return []
        from engine import host_io
        try:
            return host_io.model_nodes(iid)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Model Parts pane: part NODES (spec 2026-09-25 section 7)
    # ------------------------------------------------------------------
    # A part's rules are child nodes -- Anchor, one {State} Transformation
    # per state, Breakage -- each added/removed by right-click and edited by
    # selecting it. The staged spec per part is
    #   {"anchor": (x,y,z)|None, "transition": s, "poses": {state: p6},
    #    "break": fraction|None}
    # in SHIP units / degrees / fraction of max hull, exactly what
    # `part_save_edits` turns into SetAnchor / SetTransitionSeconds /
    # SetStatePose / SetBreakFraction.
    def _baked_articulated_part(self, name: str):
        """The `ArticulatedPartProperty` registered for `name` on the current
        ship's rig, or None (unrigged part / no ship / no rig at all).
        Reuses `articulation.parts_for_leaf`, which is the same
        case-insensitive, None-safe lookup the live per-tick articulation
        already uses -- one leaf resolution, one rig lookup, everywhere."""
        ship = self._ship_getter()
        if ship is None:
            return None
        leaf = hardpoint_leaf_for_ship(ship)
        from engine.appc import articulation
        for p in articulation.parts_for_leaf(leaf):
            if p.GetName() == name:
                return p
        return None

    def _baked_part_spec(self, name: str) -> dict:
        """The part's spec as BC (or a mod's hardpoint file) authored it,
        read through the template's pose surface -- a legacy hinge file
        arrives here already converted (anchor at its pivot, one rigid pose
        per authored angle). A part with no rig entry has no nodes at all:
        no anchor, no poses, not breakable (`break` None, never 0.0 --
        absent must not read as 'shears at once')."""
        from engine.appc.articulated_part import ArticulatedPartProperty
        p = self._baked_articulated_part(name)
        if p is None:
            return {"anchor": None,
                    "transition": ArticulatedPartProperty(name).transition_seconds,
                    "poses": {}, "break": None}
        anchor = p.anchor
        return {"anchor": tuple(anchor) if anchor is not None else None,
                "transition": float(p.transition_seconds),
                "poses": dict((s, tuple(p.pose6_for(s)))
                              for s in p.authored_states()),
                "break": p.break_fraction}

    def _effective_part(self, name: str) -> dict:
        """Spec to show/edit for part `name`: a staged (unsaved) edit wins,
        then an edit saved this session, else the baked spec. Mirrors
        `_effective_light`/`_effective_radius`."""
        if name in self._pending_part:
            return self._pending_part[name]
        if name in self._saved_part:
            return self._saved_part[name]
        return self._baked_part_spec(name)

    def _stage_part_field(self, name: str, **fields) -> None:
        """Merge `fields` onto part `name`'s current effective spec and stage
        the FULL result -- the same whole-spec-per-edit pattern as
        `set_light_position`/`_set_scale_field` for a light, so editing one
        field (say, the anchor) never drops another (say, an already-staged
        pose). `poses` is copied, never shared with the saved/baked spec it
        came from."""
        spec = dict(self._effective_part(name))
        spec["poses"] = dict(spec.get("poses") or {})
        spec.update(fields)
        self._pending_part[name] = spec
        self._last_pushed = None

    def _part_box_centre(self, name: str) -> tuple:
        """Centre of part `name`'s derived box (ship units) from the model
        nodes snapshotted at open -- where a new anchor starts. The origin
        when the node carries no bounds."""
        for n in self._model_part_nodes:
            if n.get("name") != name:
                continue
            lo, hi = n.get("bounds_min"), n.get("bounds_max")
            if lo is None or hi is None:
                break
            return tuple((float(lo[k]) + float(hi[k])) / 2.0 for k in range(3))
        return (0.0, 0.0, 0.0)

    def _part_node_exists(self, name: str, kind) -> bool:
        """True when part `name` currently has child node `kind` ("anchor",
        "breakage" or a state name) in its effective spec."""
        if name not in self._model_part_names():
            return False
        spec = self._effective_part(name)
        if kind == "anchor":
            return spec.get("anchor") is not None
        if kind == "breakage":
            return spec.get("break") is not None
        return kind in (spec.get("poses") or {})

    def _selected_state_node(self):
        """(part_name, state) while a {State} Transformation node is
        selected, else None."""
        from engine.appc.articulated_part import STATES
        node = _spv.selected_part_node()
        if node is not None and node[1] in STATES:
            return node
        return None

    def _state_is_articulated(self, state: str) -> bool:
        """True when any part of the current ship's rig -- INCLUDING this
        session's staged/saved edits -- has a pose in `state` that is not the
        NIF pose. What the 'K' dev override's arm of the lock checks: a
        state whose poses are all identity moves nothing, so forcing it must
        not lock anything. Staged edits are folded in (not just the baked
        rig) so re-authoring a pose updates the lock on the very next render,
        not only after Save."""
        from engine.appc import articulation, part_pose
        ship = self._ship_getter()
        leaf = hardpoint_leaf_for_ship(ship) if ship is not None else None
        names = set(p.GetName() for p in articulation.parts_for_leaf(leaf))
        names |= set(self._pending_part) | set(self._saved_part)
        for nm in names:
            p6 = (self._effective_part(nm).get("poses") or {}).get(state)
            if p6 is not None and not part_pose.is_identity(part_pose.pose_from6(p6)):
                return True
        return False

    def _sync_part_pose(self) -> None:
        """Apply the pose the node selection calls for, at the event edge.

        A selected {State} Transformation draws THAT part in that pose and
        every other part at the NIF pose (`articulation.force_part_pose`);
        anything else -- the part row, the Anchor or Breakage node, a mount,
        nothing -- draws the whole rig at the NIF pose
        (`articulation.force_pose(ship, None)`), the frame a hardpoint mount
        is stored in. The SPV freezes the sim, so nothing else would move
        the rig: the forced pose goes into `ship._articulation_poses`, which
        the mesh, the pins and the derived-box queries all read, and the
        CACHED pin positions are then re-resolved from it
        (`_refresh_world_positions`) -- without that the part swings out from
        under stationary pins.

        Runs after every dispatched action (see `dispatch_event`), so undo
        and a node removed from under its selection are covered too: a
        selection that names a node which no longer exists is dropped first.
        Acts only when the wanted pose CHANGED, so an unrelated click does
        not rebuild every descriptor."""
        from engine.appc import articulation, part_pose
        node = _spv.selected_part_node()
        if node is not None and not self._part_node_exists(*node):
            _spv.select_part_node(None, None)
        state_node = self._selected_state_node()
        want = None
        if state_node is not None:
            name, state = state_node
            p6 = self._effective_part(name)["poses"][state]
            want = (name, state, tuple(float(v) for v in p6))
        if want == self._applied_part_pose:
            return
        ship = self._ship_getter()
        if want is None:
            articulation.force_pose(ship, None)
        else:
            articulation.force_part_pose(ship, want[0],
                                         part_pose.pose_from6(want[2]))
        self._applied_part_pose = want
        self._refresh_world_positions()
        self._last_pushed = None

    def _show_toast(self, text: str) -> None:
        """Show `text` at the top of the SPV for TOAST_SECONDS -- one at a
        time, a newer toast replaces the current one (spec section 7.4)."""
        self._toast = (text, time.monotonic() + TOAST_SECONDS)
        self._last_pushed = None

    def _current_toast(self):
        """The toast text while it is unexpired, else None. Read-only: an
        expired toast simply stops being reported (it is part of the payload
        snapshot, so its expiry alone triggers the re-push that hides it)."""
        if self._toast is None:
            return None
        text, until = self._toast
        return text if time.monotonic() < until else None

    def _dispatch_part_action(self, action: str) -> bool:
        """The `part/*` actions: add/remove/select a part's child nodes and
        edit their inline fields. Returns False for a malformed action, an
        unknown part, or a no-op (adding a node that is already there); a
        refusal that shows a toast returns True with nothing staged."""
        from engine.appc.articulated_part import STATES
        verb, _sep, arg = action.partition(":")
        if verb in ("part/add_anchor", "part/make_breakable"):
            name = arg
            if name not in self._model_part_names():
                return False
            spec = self._effective_part(name)
            if verb == "part/add_anchor":
                if spec.get("anchor") is not None:
                    return False
                self._stage_part_field(name, anchor=self._part_box_centre(name))
            else:
                if spec.get("break") is not None:
                    return False
                self._stage_part_field(name, **{"break": DEFAULT_BREAK_FRACTION})
            return True
        try:
            data = json.loads(arg)
            name = str(data["name"])
        except (ValueError, KeyError, TypeError):
            return False
        if name not in self._model_part_names():
            return False
        spec = self._effective_part(name)
        if verb == "part/add_state":
            state = data.get("state")
            if state not in STATES:
                return False
            if spec.get("anchor") is None:
                self._show_toast(TOAST_NO_ANCHOR)
                return True
            poses = dict(spec.get("poses") or {})
            if state in poses:
                return False
            poses[state] = IDENTITY_POSE6
            self._stage_part_field(name, poses=poses)
            return True
        if verb == "part/remove":
            kind = data.get("kind")
            if not self._part_node_exists(name, kind):
                return False
            if kind == "anchor":
                if spec.get("poses"):
                    self._show_toast(TOAST_ANCHOR_IN_USE)
                    return True
                self._stage_part_field(name, anchor=None)
            elif kind == "breakage":
                self._stage_part_field(name, **{"break": None})
            else:
                poses = dict(spec.get("poses") or {})
                del poses[kind]
                self._stage_part_field(name, poses=poses)
            return True
        if verb == "part/select_node":
            kind = data.get("kind")
            if not self._part_node_exists(name, kind):
                return False
            _spv.select_model_part(name, self._model_part_nodes)
            _spv.select_part_node(name, kind)
            # Mutually exclusive with subsystem/light/emitter selection, as
            # model_parts/select is.
            self.selected_index = None
            self._selected_light_index = None
            self._selected_emitter = None
            self._last_pushed = None
            return True
        if verb == "part/set_transition":
            try:
                seconds = float(data["seconds"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (seconds > 0.0) or math.isinf(seconds):
                return False
            if spec.get("anchor") is None:
                return False
            self._stage_part_field(name, transition=seconds)
            return True
        if verb == "part/set_break":
            try:
                percent = float(data["percent"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0.0 < percent <= 100.0):
                return False
            if spec.get("break") is None:
                return False
            self._stage_part_field(name, **{"break": percent / 100.0})
            return True
        return False

    def _refresh_world_positions(self) -> None:
        """Re-resolve every descriptor's cached `world_pos` in the ship's
        CURRENT pose, leaving everything else about them untouched.

        Rebuilds through `build_descriptors` -- the one function that knows
        how a mount resolves -- and copies ONLY `world_pos` across, by index.
        A wholesale swap of `self._descriptors` would be shorter and is not
        safe: `_pending_pos`, `_pending_radius`, `_pending_light`,
        `_pending_emitter`, `selected_index`, `_selected_light_index` and the
        transform targets are ALL keyed by descriptor index, and several
        descriptor fields are annotated in place after the build. Copying one
        field cannot reorder, renumber or drop anything.

        Bails out entirely if the rebuild disagrees on length or on the name
        at any index -- that would mean the subsystem set changed under us
        (a respawn mid-session), and a partial copy would point live pins at
        the wrong mounts. A stale pin is recoverable by reopening; a
        misattributed one is not.
        """
        ship = self._ship_getter()
        if ship is None or not self._descriptors:
            return
        fresh = build_descriptors(ship)
        if len(fresh) != len(self._descriptors):
            return
        if any(f.get("name") != d.get("name")
               for f, d in zip(fresh, self._descriptors)):
            return
        for f, d in zip(fresh, self._descriptors):
            d["world_pos"] = f["world_pos"]

    def _current_articulation_override(self):
        """`articulation.dev_override()` -- the state the 'K' dev keybinding
        is forcing the rig toward, or None (the rig follows `state_for` /
        alert level as normal). Read live, never mirrored: 'K' writes only
        the override, so any shadow copy here would silently disagree with
        the lock."""
        from engine.appc import articulation
        return articulation.dev_override()

    def _mount_lock_state_and_reason(self):
        """(locked: bool, reason: str|None), computed LIVE on every check --
        never from a cached boolean. Two arms:

        * a {State} Transformation node is selected: the part is drawn posed,
          and a hardpoint is stored in the model's own unposed frame, so a
          mount placed through this pose would be recorded wrong;
        * the 'K' dev override forces a state in which some part of the rig
          (staged edits included) is not at the NIF pose. A state whose
          poses are all identity moves nothing and locks nothing."""
        node = self._selected_state_node()
        if node is not None:
            name, state = node
            return True, ("Posing %s Transformation on %s — mount editing "
                          "is locked" % (STATE_LABELS[state], name))
        state = self._current_articulation_override()
        if state is None or not self._state_is_articulated(state):
            return False, None
        reason = (
            "Mount editing is locked while the rig is forced to %r: a "
            "hardpoint is stored in the model's own unposed frame, so a "
            "mount placed or dragged in this pose would be recorded wrong "
            "for every other pose. Release the forced state to unlock."
            % state)
        return True, reason

    def _mount_editing_enabled(self) -> bool:
        return not self._mount_lock_state_and_reason()[0]

    def _model_part_names(self) -> set:
        return set(n.get("name") for n in self._model_part_nodes)

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

    def _effective_regions_by_sub(self, ship) -> dict:
        """{id(sub): [region spec, ...]} for every subsystem the panel lists.

        Region 0 is the panel's effective light (staged, saved this session,
        or baked; absent when removed); regions 1.. are the property's own
        baked ones, which the panel does not edit. Walks subsystems exactly as
        `build_descriptors` does (same skip rule), so descriptor index `di`
        lines up with the subsystem.
        """
        from engine.appc.subsystem_glow import baked_glow_regions
        from engine.ui.ship_property_viewer import _iter_subsystems
        out = {}
        di = 0
        for sub in _iter_subsystems(ship):
            local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
            if local is None:
                continue                       # same skip as build_descriptors
            prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
            region0 = self._effective_light(di)
            out[id(sub)] = (([dict(region0)] if region0 else [])
                            + baked_glow_regions(prop)[1:])
            di += 1
        return out

    def _has_light(self, index) -> bool:
        return (0 <= index < len(self._descriptors)
                and self._effective_light(index) is not None)

    def _baked_emitters(self, i):
        d = self._descriptors[i]
        return list(d.get("emitters") or [])

    def _effective_emitters(self, i):
        """The full, compacted emitter list for subsystem i: a staged
        (unsaved) list wins, then a saved-this-session list, else the baked
        list. Whole-list-per-subsystem (not a per-(i,j) sentinel dict) so
        indices are always dense — add/set/remove all stage a full copy of
        the list, never a sparse override — which is required because
        baked_emitters() stops at the first gap on reload."""
        if i in self._pending_emitter:
            return list(self._pending_emitter[i])
        if i in self._saved_emitter:
            return list(self._saved_emitter[i])
        return self._baked_emitters(i)

    def _effective_emitter(self, i, j):
        """Positional lookup into `_effective_emitters(i)` — j always
        addresses the CURRENT compacted list, so it stays valid across
        add/remove within the same session."""
        lst = self._effective_emitters(i)
        return lst[j] if 0 <= j < len(lst) else None

    def _emitter_save_edits(self):
        """DENSE `__emitter__` edits for every subsystem with a staged
        emitter-list edit. `_pending_emitter[i]` is the FULL new (compacted)
        list, not a per-(i,j) sentinel — so unlike the light save (a single
        index 0) this must emit one edit per index across the widest of the
        new list, the baked list, and any list already saved this session:
        a same-session shrink or a shrink relative to the baked count must
        CLEAR the now-unused trailing indices (`[]` — drives the writer's
        drop-empty path) or they'd survive as stale emitters on disk, and
        persisted indices must stay dense because baked_emitters() stops at
        the first unset index on reload."""
        edits = []
        for i, lst in sorted(self._pending_emitter.items()):
            name = self._descriptors[i]["name"]
            baked = self._descriptors[i].get("emitters") or []
            saved = self._saved_emitter.get(i) or []
            clear_to = max(len(lst), len(baked), len(saved))
            for j in range(clear_to):
                calls = emitter_spec_to_calls(j, lst[j]) if j < len(lst) else []
                edits.append((name, "__emitter__", j, calls))
        return edits

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
        unavailable (headless / not yet resolved).

        THE SELECTED PIN'S ROAD. Every OTHER pin rides the cached
        `descriptor["world_pos"]`, which `build_descriptors` resolved through
        `subsystem_world_position`. The moment a subsystem is selected,
        `subsystem_pins`, `selected_subsystem_sphere` and the transform gizmo
        switch to this instead -- and this used to hand the body position
        straight to `world_from_body`, which is `loc + R * v` with NO
        articulation. So selecting a wingtip cannon under a previewed pose
        snapped its pin back to the rest mount while every neighbour stayed
        out on the wing.

        `part_transform_point` closes that: the SAME call
        `subsystem_world_position` makes, reading the same
        `ship._articulation_poses`, so the two roads arrive at one place by
        construction rather than by two transforms being kept in step. It is
        applied to `_effective_pos`, not to the baked mount, because a
        staged/dragged position is authored in the model's UNROTATED frame
        like every other mount and has to go through the hinge on the way
        out too.

        Identity for an unrigged hull, a body mount, a severed part and at
        angle 0 -- so the common case is byte-identical.
        """
        from engine.ui.ship_property_viewer import world_from_body
        from engine.appc.articulation import part_transform_point
        ship = self._ship_getter()
        if ship is None or not hasattr(ship, "GetWorldLocation"):
            return self._descriptors[index].get("world_pos", (0.0, 0.0, 0.0))
        return world_from_body(
            ship, part_transform_point(ship, self._effective_pos(index)))

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

    def set_emitter_position(self, i: int, j: int, body_pos) -> None:
        """Stage a body-frame position edit for emitter (i, j). Restages the
        WHOLE compacted emitter list (dense-index invariant — see
        `_pending_emitter`), mirroring `set_light_position` but through the
        whole-list-per-subsystem staging model rather than a per-(i,j) key."""
        lst = list(self._effective_emitters(i))
        if not (0 <= j < len(lst)):
            return
        spec = dict(lst[j])
        spec["position"] = tuple(float(c) for c in body_pos)
        lst[j] = spec
        self._pending_emitter[i] = lst
        self._last_pushed = None

    # ------------------------------------------------------------------
    # Undo (pending-only; no redo; cleared on Save)
    # ------------------------------------------------------------------
    def _snapshot_pending(self):
        """Deep copy of the five staged-edit dicts — one undo unit."""
        import copy
        return (copy.deepcopy(self._pending_radius),
                copy.deepcopy(self._pending_light),
                copy.deepcopy(self._pending_emitter),
                copy.deepcopy(self._pending_pos),
                copy.deepcopy(self._pending_part))

    def _restore_pending(self, snap) -> None:
        """Replace the five staged-edit dicts from a snapshot, drop a now-stale
        emitter selection, and force a CEF re-push."""
        import copy
        r, l, e, p, pt = snap
        self._pending_radius = copy.deepcopy(r)
        self._pending_light = copy.deepcopy(l)
        self._pending_emitter = copy.deepcopy(e)
        self._pending_pos = copy.deepcopy(p)
        self._pending_part = copy.deepcopy(pt)
        if self._selected_emitter is not None:
            i, j = self._selected_emitter
            if not (0 <= i < len(self._descriptors)) \
                    or self._effective_emitter(i, j) is None:
                self._selected_emitter = None
        self._last_pushed = None

    def undo(self) -> None:
        if self._undo_stack:
            self._restore_pending(self._undo_stack.pop())

    # ------------------------------------------------------------------
    # Transform gizmo (subsystem or light-volume target)
    # ------------------------------------------------------------------
    def _active_transform_target(self):
        """Which node the transform gizmo/drag currently targets:
        ("emitter", i, j), ("light", i), ("subsystem", i), or None. Emitter,
        light, and subsystem selection are mutually exclusive by construction
        (dispatch_event's selection handlers clear the others).

        A model part -- its row or any of its nodes -- is NOT a transform
        target: selecting one clears the mount selection, so this answers
        None and no gizmo appears. The part-node gizmos (anchor Move, pose
        Move/Rotate about the anchor) are a separate, later surface (spec
        2026-09-25 section 8, stage 4). Every consumer that unpacks a 2-tuple
        (`kind, i = t`) branches on `t[0] == "emitter"` first."""
        if self._selected_emitter is not None:
            return ("emitter",) + self._selected_emitter   # ("emitter", i, j)
        if self._selected_light_index is not None:
            return ("light", self._selected_light_index)
        if self.selected_index is not None:
            return ("subsystem", self.selected_index)
        return None

    def _target_pos_of(self, target):
        """Body-frame (x, y, z) of an arbitrary transform target, or None."""
        if target is None:
            return None
        if target[0] == "emitter":
            _, i, j = target
            spec = self._effective_emitter(i, j)
            return tuple(float(c) for c in spec["position"]) if spec else None
        kind, i = target
        if kind == "light":
            spec = self._effective_light(i)
            return tuple(float(c) for c in spec["position"]) if spec else None
        return tuple(float(c) for c in self._effective_pos(i))

    def _transform_target_pos(self):
        """Body-frame (x, y, z) of the current transform target, or None (no
        tool target). Mirrors `transform_gizmo`'s target resolution but
        returns the raw position tuple instead of the gizmo geometry."""
        return self._target_pos_of(self._active_transform_target())

    def _set_transform_target_pos(self, xyz) -> None:
        """Stage `xyz` as the current transform target's body-frame position,
        routing to the emitter (whole-list restage), light, or subsystem
        staging path as appropriate."""
        t = self._active_transform_target()
        if t is None:
            return
        if t[0] == "emitter":
            _, i, j = t
            self.set_emitter_position(i, j, xyz)
            return
        kind, i = t
        if kind == "light":
            self.set_light_position(i, xyz)
        else:
            self.set_subsystem_position(i, xyz)

    # ------------------------------------------------------------------
    # Pipette eyedropper
    # ------------------------------------------------------------------
    def _src_rotate_target(self, src):
        """src if it is rotate-capable (cylinder/box light, strip/cone emitter),
        else None — mirrors _rotate_target but for an explicit target."""
        if src[0] == "emitter":
            spec = self._effective_emitter(src[1], src[2])
            return src if spec and spec.get("kind") in ("strip", "cone") else None
        if src[0] == "light":
            spec = self._effective_light(src[1])
            return src if spec and spec.get("shape") in ("Cylinder", "Box") else None
        return None

    def _src_axis(self, src):
        if src[0] == "emitter":
            spec = self._effective_emitter(src[1], src[2]) or {}
        else:
            spec = self._effective_light(src[1]) or {}
        return tuple(spec.get("axis") or (0.0, -1.0, 0.0)) if spec else None

    def _src_orientation(self, src):
        """(forward, up) for a box light or cone emitter source, else None."""
        if src[0] == "emitter":
            spec = self._effective_emitter(src[1], src[2]) or {}
            if spec.get("kind") == "cone":
                from engine.appc.light_emitters import _derive_up
                fwd = spec.get("axis") or (0.0, -1.0, 0.0)
                return (tuple(fwd), tuple(spec.get("up") or _derive_up(fwd)))
            return None
        spec = self._effective_light(src[1]) or {}
        if spec.get("shape") == "Box":
            fwd, up = spec.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            return (tuple(fwd), tuple(up))
        return None

    def _apply_pipette(self, src) -> None:
        """Copy every aspect the target can hold from `src` onto the current
        selection (the target). Incompatible aspects are silently skipped."""
        tgt = self._active_transform_target()
        if tgt is None or src == tgt:
            return
        # 1. Position (always) — set on the active target.
        spos = self._target_pos_of(src)
        if spos is not None:
            self._set_transform_target_pos(spos)
        # 2. Rotation — only when both share a rotate kind.
        if self._rotate_target() is not None \
                and self._src_rotate_target(src) is not None \
                and self._rotate_clipboard_kind(src) == self._rotate_clipboard_kind(tgt):
            kind = self._rotate_clipboard_kind(src)
            if kind == "cylinder_axis":
                axis = self._src_axis(src)
                if axis is not None:
                    self._set_axis_absolute(tgt, axis)
            else:  # box_orientation / cone_orientation
                fu = self._src_orientation(src)
                if fu is not None:
                    self._set_orientation_absolute(tgt, fu[0], fu[1])
        # 3. Scale — only when both share a scale kind.
        skind, sfields = self._scale_kind_and_fields(src)
        tkind, _ = self._scale_kind_and_fields(tgt)
        if skind == tkind:
            for idx, f in enumerate(sfields):
                self._set_scale_field(idx, f["value"])
        # 4. Colour + intensity — emitter → emitter only.
        if src[0] == "emitter" and tgt[0] == "emitter":
            ssp = self._effective_emitter(src[1], src[2])
            if ssp is not None:
                _, ti, tj = tgt
                lst = list(self._effective_emitters(ti))
                if 0 <= tj < len(lst):
                    spec = dict(lst[tj])
                    spec["color"] = tuple(ssp["color"])
                    spec["intensity"] = float(ssp["intensity"])
                    lst[tj] = spec
                    self._pending_emitter[ti] = lst
                    self._last_pushed = None

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
        else -> radius). An emitter is scalar-`radius`/`length`: a point emitter
        exposes only Radius; a strip or cone exposes Radius + Length (the cone's
        half-angle is DERIVED from radius/length, so no separate field)."""
        if target[0] == "emitter":
            _, i, j = target
            spec = self._effective_emitter(i, j)
            if not spec:
                return "radius", [{"label": "Radius", "value": 0.0}]
            kind = spec.get("kind", "point")
            if kind == "point":
                return "radius", [{"label": "Radius", "value": float(spec["radius"])}]
            if kind == "cone":
                # A cone now has TWO base radii (X = radius, Y = radius_y) plus a
                # Length, so it exposes a 3-field kind (mirrors the Box light's
                # xyz). A circular/legacy cone reports Radius Y == Radius X.
                return "radius_xy_length", [
                    {"label": "Radius X", "value": float(spec["radius"])},
                    {"label": "Radius Y",
                     "value": float(spec.get("radius_y", spec["radius"]))},
                    {"label": "Length", "value": float(spec["length"])}]
            # strip exposes Radius + Length.
            return "radius_length", [
                {"label": "Radius", "value": float(spec["radius"])},
                {"label": "Length", "value": float(spec["length"])}]
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
        "can_paste"}` for the current transform target, or None when the scale
        tool isn't active or nothing is selected. `_scale_kind_and_fields` is
        shape-aware for subsystems, light volumes, AND emitters (point ->
        "radius", strip/cone -> "radius_length")."""
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
        kind, fields = self._scale_kind_and_fields(t)
        if not (0 <= index < len(fields)):
            return
        if t[0] == "emitter":
            # Emitter spec uses SCALAR radius/length floats (NOT the light's
            # tuple/extent form). Field 0 -> radius, field 1 -> length; restage
            # the whole compacted list to keep indices dense.
            _, i, j = t
            lst = list(self._effective_emitters(i))
            if not (0 <= j < len(lst)):
                return
            spec = dict(lst[j])
            if spec.get("kind") == "cone":
                # 3 fields: 0 -> Radius X (radius), 1 -> Radius Y (radius_y),
                # 2 -> Length. index is bounds-checked against the 3-field kind.
                spec[("radius", "radius_y", "length")[index]] = value
            else:  # strip / point: field 0 -> radius, field 1 -> length
                spec["radius" if index == 0 else "length"] = value
            lst[j] = spec
            self._pending_emitter[i] = lst
            self._last_pushed = None
            return
        kt, i = t
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
        """The rotate tool's target: ("light", i) for a Cylinder (rotate its axis) or Box (rotate its
        forward+up orientation basis) light; ("emitter", i, j) for a strip
        emitter (rotate its single `axis`) or a cone emitter (rotate its
        forward+up basis, like a Box); None otherwise (sphere/subsystem, and
        a point emitter, are inert)."""
        t = self._active_transform_target()
        if t is None:
            return None
        kt = t[0]
        if kt == "emitter":
            _, i, j = t
            spec = self._effective_emitter(i, j)
            if not spec or spec.get("kind") not in ("strip", "cone"):
                return None
            return ("emitter", i, j)
        if kt != "light":
            return None
        i = t[1]
        spec = self._effective_light(i)
        if not spec or spec.get("shape") not in ("Cylinder", "Box"):
            return None
        return ("light", i)

    def _mirror_target_rotation(self, t) -> None:
        """Reflect the rotate target `t`'s orientation across the ship X axis
        (starboard): negate X of the axis (cylinder/strip) or of both forward
        and up (box/cone), then set it absolutely."""
        if t[0] == "emitter":
            _, i, j = t
            spec = self._effective_emitter(i, j) or {}
            if spec.get("kind") == "cone":
                from engine.appc.light_emitters import _derive_up
                fwd = spec.get("axis") or (0.0, -1.0, 0.0)
                up = spec.get("up") or _derive_up(fwd)
                self._set_orientation_absolute(t, (-fwd[0], fwd[1], fwd[2]),
                                               (-up[0], up[1], up[2]))
            else:
                axis = list(spec.get("axis") or (0.0, -1.0, 0.0))
                axis[0] = -axis[0]
                self._set_axis_absolute(t, axis)
        else:
            _, i = t
            spec = self._effective_light(i) or {}
            if spec.get("shape") == "Box":
                fwd, up = spec.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
                self._set_orientation_absolute(i, (-fwd[0], fwd[1], fwd[2]),
                                               (-up[0], up[1], up[2]))
            else:
                axis = list(spec.get("axis") or (0.0, -1.0, 0.0))
                axis[0] = -axis[0]
                self._set_axis_absolute(t, axis)

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
            # _rotate_target() already returns None for a point emitter and for
            # non-cylinder/box lights/subsystems, so no panel there — correct.
            return None
        # Keyed by the full target tuple (("light", i) / ("emitter", i, j)) so a
        # subsystem's light readout stays independent of that same subsystem's
        # emitter readouts — a bare index i would collide.
        acc = self._rotate_accum.get(t, [0.0, 0.0, 0.0])
        clip = self._rotate_clipboard
        kind = self._rotate_clipboard_kind(t)
        return {"fields": [{"label": "X", "value": acc[0]},
                           {"label": "Y", "value": acc[1]},
                           {"label": "Z", "value": acc[2]}],
                "has_clipboard": clip is not None,
                "can_paste": clip is not None and clip[0] == kind}

    def _rotate_clipboard_kind(self, target) -> str:
        """Clipboard kind for `target`'s current shape: `box_orientation` for a
        Box light; `cone_orientation` for a CONE emitter (an oriented
        forward+up basis, like a Box); `cylinder_axis` for a Cylinder light OR a
        strip emitter. Strip emitters and cylinder lights share `cylinder_axis`
        INTENTIONALLY — both rotate a single axis, so a cylinder-light rotation
        can be copied and pasted/mirrored onto a strip emitter and vice versa
        (the mirror-a-light workflow). A cone carries a full orientation basis,
        so it uses `cone_orientation` and only interchanges with other cones."""
        if target[0] == "emitter":
            spec = self._effective_emitter(target[1], target[2]) or {}
            return "cone_orientation" if spec.get("kind") == "cone" \
                else "cylinder_axis"
        spec = self._effective_light(target[1]) or {}
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
        from engine.ui.ship_property_viewer import (
            rotate_about_axis, orthonormalize_basis)
        ang = math.radians(delta_deg)
        if t[0] == "emitter":
            # A CONE carries an oriented (forward=axis, up) basis like a Box, so
            # it rotates BOTH and re-orthonormalizes; a strip rotates its single
            # `axis` (same math as the cylinder-light branch). Restage the whole
            # compacted list to keep emitter indices dense.
            _, i, j = t
            lst = list(self._effective_emitters(i))
            if not (0 <= j < len(lst)):
                return
            spec = dict(lst[j])
            if spec.get("kind") == "cone":
                from engine.appc.light_emitters import _derive_up
                fwd = spec.get("axis") or (0.0, -1.0, 0.0)
                up = spec.get("up") or _derive_up(fwd)
                fwd = rotate_about_axis(fwd, index, ang)
                up = rotate_about_axis(up, index, ang)
                spec["axis"], spec["up"] = orthonormalize_basis(fwd, up)
            else:
                axis = spec.get("axis") or (0.0, -1.0, 0.0)
                spec["axis"] = rotate_about_axis(axis, index, ang)
            lst[j] = spec
            self._pending_emitter[i] = lst
            self._rotate_accum.setdefault(t, [0.0, 0.0, 0.0])[index] += delta_deg
            self._last_pushed = None
            return
        _, i = t
        spec = dict(self._effective_light(i) or {})
        if not spec:
            return
        if spec.get("shape") == "Box":
            fwd, up = spec.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            fwd = rotate_about_axis(fwd, index, ang)
            up = rotate_about_axis(up, index, ang)
            spec["orientation"] = orthonormalize_basis(fwd, up)
        else:
            axis = spec.get("axis") or (0.0, -1.0, 0.0)
            spec["axis"] = rotate_about_axis(axis, index, ang)
        self._pending_light[i] = spec
        self._rotate_accum.setdefault(t, [0.0, 0.0, 0.0])[index] += delta_deg
        self._last_pushed = None

    def _set_axis_absolute(self, target, axis) -> None:
        """Stage a normalized `axis` directly (Mirror/Paste, not an incremental
        rotation) and zero its degree accumulator. Target-aware: `target` may be
        a light tuple `("light", i)` (or a bare int i, for legacy callers) which
        writes `_pending_light[i]`, or an emitter tuple `("emitter", i, j)` which
        restages the whole compacted emitter list (dense-index invariant)."""
        n = math.sqrt(sum(a*a for a in axis)) or 1.0
        naxis = (axis[0]/n, axis[1]/n, axis[2]/n)
        if isinstance(target, tuple) and target[0] == "emitter":
            _, i, j = target
            lst = list(self._effective_emitters(i))
            if not (0 <= j < len(lst)):
                return
            spec = dict(lst[j])
            spec["axis"] = naxis
            lst[j] = spec
            self._pending_emitter[i] = lst
            self._rotate_accum[("emitter", i, j)] = [0.0, 0.0, 0.0]
            self._last_pushed = None
            return
        i = target[1] if isinstance(target, tuple) else target
        spec = dict(self._effective_light(i) or {})
        if not spec:
            return
        spec["axis"] = naxis
        self._pending_light[i] = spec
        self._rotate_accum[("light", i)] = [0.0, 0.0, 0.0]
        self._last_pushed = None

    def _set_orientation_absolute(self, target, forward, up) -> None:
        """Stage a re-orthonormalized `(forward, up)` orientation directly
        (Mirror/Paste, not an incremental rotation) and zero its degree
        accumulator. Target-aware like `_set_axis_absolute`: `target` may be a
        Box-light tuple `("light", i)` (or a bare int i, for legacy callers)
        which writes `orientation` into `_pending_light[i]`, or a CONE-emitter
        tuple `("emitter", i, j)` which restages the whole compacted emitter
        list, writing `axis` (=forward) + `up` (dense-index invariant)."""
        from engine.ui.ship_property_viewer import orthonormalize_basis
        fwd, u = orthonormalize_basis(forward, up)
        if isinstance(target, tuple) and target[0] == "emitter":
            _, i, j = target
            lst = list(self._effective_emitters(i))
            if not (0 <= j < len(lst)):
                return
            spec = dict(lst[j])
            spec["axis"] = fwd
            spec["up"] = u
            lst[j] = spec
            self._pending_emitter[i] = lst
            self._rotate_accum[("emitter", i, j)] = [0.0, 0.0, 0.0]
            self._last_pushed = None
            return
        i = target[1] if isinstance(target, tuple) else target
        spec = dict(self._effective_light(i) or {})
        if not spec:
            return
        spec["orientation"] = (fwd, u)
        self._pending_light[i] = spec
        self._rotate_accum[("light", i)] = [0.0, 0.0, 0.0]
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
        kt = target[0]
        if kt == "subsystem" and not (0 <= target[1] < len(self._descriptors)):
            return None
        ship = self._ship_getter()
        if ship is None or not hasattr(ship, "GetWorldRotation"):
            return None
        from engine.ui.ship_property_viewer import (
            gizmo_axes, gizmo_length, world_from_body)
        if kt == "emitter":
            spec = self._effective_emitter(target[1], target[2])
            if spec is None:
                return None
            origin = world_from_body(ship, spec["position"])
        elif kt == "light":
            light = self._effective_light(target[1])
            if light is None:
                return None
            origin = world_from_body(ship, light["position"])
        else:
            origin = self._effective_world_pos(target[1])
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
        t = self._active_transform_target()
        if t is None:
            return None
        ship = self._ship_getter()
        if ship is None or not hasattr(ship, "GetWorldRotation"):
            return None
        from engine.ui.ship_property_viewer import (
            gizmo_axes, gizmo_length, world_from_body)
        kt = t[0]
        i = t[1]
        # Defensive guards mirroring transform_gizmo (this runs every input
        # frame via _active_gizmo): a stale/removed node or out-of-range index
        # must degrade to None, never crash on a missing spec.
        if not (0 <= i < len(self._descriptors)):
            return None
        if kt == "emitter":
            spec = self._effective_emitter(i, t[2])
            if spec is None:
                return None
            origin = world_from_body(ship, spec["position"])
        elif kt == "light":
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
        """The rotate-gizmo (orientation rings) for the selected cylinder/box
        light or strip-or-cone emitter, or None. Same shape as `scale_gizmo` but
        with `"handle_kind": 2` so the renderer draws rings. Gated on the
        rotate tool being active, a rotate target selected, and the ship
        resolvable with a world rotation."""
        if self.active_tool != "rotate" or self.camera is None:
            return None
        t = self._rotate_target()
        if t is None:
            return None
        ship = self._ship_getter()
        if ship is None or not hasattr(ship, "GetWorldRotation"):
            return None
        from engine.ui.ship_property_viewer import (
            gizmo_axes, gizmo_length, world_from_body)
        i = t[1]
        if not (0 <= i < len(self._descriptors)):
            return None
        if t[0] == "emitter":
            spec = self._effective_emitter(i, t[2])
            if spec is None:
                return None
            origin = world_from_body(ship, spec["position"])
        else:
            light = self._effective_light(i)
            if light is None:
                return None
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
        self._drag_undo_before = self._snapshot_pending()
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
        elif kind == "radius_xy_length":
            # Oriented cone: the handle aligned with `forward` (=axis) scales
            # Length (field 2); of the two perpendicular handles, the one aligned
            # with right = cross(forward, up) scales Radius X (field 0), the other
            # (aligned with up) scales Radius Y (field 1). Gizmo handles are body
            # X/Y/Z, so match each frame vector by its dominant body component.
            from engine.appc.light_emitters import _derive_up
            spec = self._effective_emitter(t[1], t[2]) or {}
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            up = spec.get("up") or _derive_up(fwd)
            right = (fwd[1]*up[2] - fwd[2]*up[1],
                     fwd[2]*up[0] - fwd[0]*up[2],
                     fwd[0]*up[1] - fwd[1]*up[0])
            def _dom(v):
                return max(range(3), key=lambda k: abs(v[k]))
            if axis == _dom(fwd):
                field_idx = 2
            elif axis == _dom(right):
                field_idx = 0
            else:
                field_idx = 1
            self._scale_grab = (field_idx, fields[field_idx]["value"])
        elif kind == "radius_length":
            # Cylinder light OR strip emitter: the handle aligned with the
            # node's body-frame axis scales Length (field 1); the two
            # perpendicular handles scale Radius (field 0). The gizmo axes are
            # body X/Y/Z, so the aligned handle is the dominant component of the
            # region's/emitter's body-frame axis vector.
            if t[0] == "emitter":
                spec = self._effective_emitter(t[1], t[2]) or {}
            else:
                spec = self._effective_light(t[1]) or {}
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
        if self._current_target_is_locked_mount():
            # Defence in depth: _handle_gizmo_input already refuses to BEGIN
            # this drag on a locked mount, but a mount's radius edit must
            # never apply even if this is ever reached some other way.
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
        self._drag_undo_before = self._snapshot_pending()
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
        i = t[1]
        if t[0] == "emitter":
            spec = self._effective_emitter(i, t[2]) or {}
        else:
            spec = self._effective_light(i) or {}
        self._ring_grab_axis = tuple(spec.get("axis") or (0.0, -1.0, 0.0))
        if t[0] == "emitter" and spec.get("kind") == "cone":
            # A cone rotates from its (forward=axis, up) basis, like a Box light;
            # seed the grab-start orientation from it (deriving up if absent) so
            # the ring drag rolls the ellipse + re-aims from the grab pose.
            from engine.appc.light_emitters import _derive_up
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            up = spec.get("up") or _derive_up(fwd)
            self._ring_grab_orientation = (tuple(fwd), tuple(up))
        else:
            self._ring_grab_orientation = spec.get("orientation") \
                or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        # Keyed by the full target tuple so light and emitter accumulators on
        # the same subsystem stay independent (see rotate_values).
        self._ring_grab_accum = list(self._rotate_accum.get(t, [0.0, 0.0, 0.0]))
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
        if self._current_target_is_locked_mount():
            # Defence in depth -- see _apply_scale_drag's identical guard.
            return
        from engine.ui.ship_property_viewer import (
            rotate_about_axis, orthonormalize_basis)
        k = self._axis_drag
        if t[0] == "emitter":
            # A CONE rotates BOTH `forward` and `up` of its grab-start
            # orientation (like a Box), then re-orthonormalizes; a strip rotates
            # its single `axis`. Restage the whole compacted list.
            _, i, j = t
            lst = list(self._effective_emitters(i))
            if not (0 <= j < len(lst)):
                return
            spec = dict(lst[j])
            if spec.get("kind") == "cone":
                fwd, up = self._ring_grab_orientation
                fwd = rotate_about_axis(fwd, k, d_body)
                up = rotate_about_axis(up, k, d_body)
                spec["axis"], spec["up"] = orthonormalize_basis(fwd, up)
            else:
                spec["axis"] = rotate_about_axis(self._ring_grab_axis, k, d_body)
            lst[j] = spec
            self._pending_emitter[i] = lst
            self._rotate_accum.setdefault(t, [0.0, 0.0, 0.0])
            self._rotate_accum[t][k] = self._ring_grab_accum[k] + math.degrees(d_body)
            self._last_pushed = None
            return
        _, i = t
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
        self._rotate_accum.setdefault(t, [0.0, 0.0, 0.0])
        self._rotate_accum[t][k] = self._ring_grab_accum[k] + math.degrees(d_body)
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
        self._drag_undo_before = self._snapshot_pending()
        target = self._active_transform_target()
        if target is None:
            return
        if target[0] == "emitter":
            _, i, j = target
            spec = self._effective_emitter(i, j)
            if spec is None:
                return
            self._axis_drag = axis
            self._axis_grab_param = grab_param
            self._axis_grab_pos = tuple(float(c) for c in spec["position"])
            ship = self._ship_getter()
            if ship is not None and hasattr(ship, "GetWorldRotation"):
                from engine.ui.ship_property_viewer import world_from_body
                self._axis_grab_origin = world_from_body(ship, self._axis_grab_pos)
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
        if self._current_target_is_locked_mount():
            # Defence in depth -- see _apply_scale_drag's identical guard.
            # This is THE bug the reviewer reproduced: without this check
            # (and _handle_gizmo_input's press-edge refusal), a subsystem
            # selected BEFORE a Preview click stayed draggable through it.
            return
        k = self._axis_drag
        base = list(self._axis_grab_pos)
        base[k] += (param_now - self._axis_grab_param)
        if target[0] == "emitter":
            _, i, j = target
            self.set_emitter_position(i, j, tuple(base))
            return
        kind, i = target
        if kind == "light":
            self.set_light_position(i, tuple(base))
        else:
            self.set_subsystem_position(i, tuple(base))

    def _end_axis_drag(self) -> None:
        self._axis_drag = None
        if self._drag_undo_before is not None:
            if self._drag_undo_before != self._snapshot_pending():
                self._undo_stack.append(self._drag_undo_before)
            self._drag_undo_before = None

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
        if self._selected_emitter is not None:
            i = self._selected_emitter[0]
            if 0 <= i < len(self._descriptors):
                d = self._descriptors[i]
                return [(d["world_pos"], d["icon_id"], False)]
            return []
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
                    self._selected_light_index, self._selected_emitter,
                    self.active_tool,
                    self.show_glow_regions, self.show_weapon_arcs,
                    self.show_hull_texture,
                    _spv.model_parts_expanded(), _spv.selected_model_part(),
                    _spv.selected_part_node(),
                    self._model_parts_show_all,
                    # The toast TEXT while unexpired, None after: its expiry
                    # alone changes the snapshot, so the push that hides it
                    # happens without anything else changing.
                    self._current_toast(),
                    # Read live from articulation.dev_override() (not a
                    # shadow copy) so a change made by the 'K' dev
                    # keybinding -- which never touches this panel's own
                    # state -- still triggers a re-push. See Finding 2.
                    self._current_articulation_override(),
                    self._mount_editing_enabled(),
                    tuple(sorted(self._pending_radius.items())),
                    tuple(sorted(self._pending_light)),   # indices with a staged light
                    tuple(sorted(self._pending_emitter)),  # subsystem indices with a staged emitter list
                    tuple(sorted(self._pending_pos.items())),
                    tuple(sorted(self._pending_part)),    # names with a staged part edit
                    tuple(sorted(self._expanded_groups)),
                    self._coord_clipboard,
                    self._scale_clipboard,
                    self._rotate_clipboard,
                    tuple(sorted((k, tuple(v)) for k, v in self._rotate_accum.items())),
                    len(self._undo_stack),
                    self._pipette_armed,
                    self._active_transform_target() is not None)
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
            "selected_emitter": list(self._selected_emitter) if self._selected_emitter else None,
            "active_tool": self.active_tool,
            "transform_coords": self.transform_coords(),
            "scale_values": self.scale_values(),
            "rotate_values": self.rotate_values(),
            "show_glow": self.show_glow_regions,
            "show_arcs": self.show_weapon_arcs,
            "show_hull": self.show_hull_texture,
            "pending_count": (len(set(self._pending_radius) | set(self._pending_light)
                                  | set(self._pending_pos) | set(self._pending_emitter))
                              + len(self._pending_part)),
            "pending": self._pending_edits(),
            "subsystems": self._subsystem_rows(),
            "model_parts": self._model_parts_payload(),
            "close_overlays": self._close_overlays,
            "can_undo": bool(self._undo_stack),
            "pipette_armed": self._pipette_armed,
            "has_selection": self._active_transform_target() is not None,
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
                         | set(self._pending_pos) | set(self._pending_emitter)):
            name = self._descriptors[i]["name"]
            if name not in counts:
                counts[name] = 0
                order.append(name)
            counts[name] += (1 if i in self._pending_radius else 0)
            counts[name] += (1 if i in self._pending_light else 0)
            counts[name] += (1 if i in self._pending_pos else 0)
            counts[name] += (1 if i in self._pending_emitter else 0)
        for name in sorted(self._pending_part):
            if name not in counts:
                counts[name] = 0
                order.append(name)
            counts[name] += 1
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
                             or (i in self._pending_pos) or (i in self._pending_emitter))
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
        # Light Emitter child node(s) — 0..N per subsystem, addressed
        # positionally by (i, j) into the effective (compacted) list (see
        # _effective_emitters). "dirty" is per-subsystem (whole-list staging)
        # since an edit anywhere in the list re-stages the whole list.
        for i in range(len(self._descriptors)):
            i_dirty = i in self._pending_emitter
            for j, spec in enumerate(self._effective_emitters(i)):
                by_index[i]["children"].append({
                    "kind": "emitter",
                    "name": "Light Emitter",
                    "emitter_of": i,
                    "emitter_index": j,
                    "emitter_kind": spec["kind"],
                    "emitter_spec": spec,
                    "dirty": i_dirty,
                })
        for row in by_index.values():
            if row["children"]:
                row["expanded"] = row["name"] in self._expanded_groups
        return rows

    def _model_parts_payload(self) -> dict:
        """The Model Parts pane (spec 2026-09-25 section 7):
        {"expanded", "show_all", "selected_box", "toast",
        "mount_editing_enabled", "mount_editing_reason", "rows"}.

        `rows` is flat, in display order: each listed part (candidates only
        unless `show_all`) as
          {"kind": "part", "name", "depth": 0, "chosen", "dirty",
           "has_anchor", "missing_states", "breakable"}
        followed by its child nodes, each
          {"kind": "anchor"|"state"|"breakage", "part", "state"?, "label",
           "depth": 1, "chosen", "value"?}
        -- Anchor first (value = transition seconds), then one
        "<Label> Transformation" per posed state in STATES order, then
        Breakage (value = break PERCENT of the ship's max hull). Everything
        comes from the EFFECTIVE spec, so staged edits show at once.
        `missing_states` feeds the "Add State Transformation" submenu."""
        from engine.appc.articulated_part import STATES
        # model_part_rows first: it reconciles a selection whose part has
        # vanished from the node list before anything reads the selection.
        listed = _spv.model_part_rows(self._model_part_nodes,
                                      show_all=self._model_parts_show_all)
        node = _spv.selected_part_node()
        selected_part = _spv.selected_model_part()
        rows: List[dict] = []
        for base in listed:
            name = base["name"]
            spec = self._effective_part(name)
            poses = spec.get("poses") or {}
            anchor = spec.get("anchor")
            fraction = spec.get("break")
            rows.append({
                "kind": "part", "name": name, "depth": 0,
                "chosen": selected_part == name and node is None,
                "dirty": name in self._pending_part,
                "has_anchor": anchor is not None,
                "missing_states": [s for s in STATES if s not in poses],
                "breakable": fraction is not None,
            })
            if anchor is not None:
                rows.append({"kind": "anchor", "part": name, "label": "Anchor",
                             "depth": 1, "chosen": node == (name, "anchor"),
                             "value": float(spec.get("transition", 2.0))})
            for state in STATES:
                if state in poses:
                    rows.append({"kind": "state", "part": name, "state": state,
                                 "label": "%s Transformation" % STATE_LABELS[state],
                                 "depth": 1, "chosen": node == (name, state)})
            if fraction is not None:
                rows.append({"kind": "breakage", "part": name,
                             "label": "Breakage", "depth": 1,
                             "chosen": node == (name, "breakage"),
                             "value": round(float(fraction) * 100.0, 6)})
        locked, reason = self._mount_lock_state_and_reason()
        return {
            "expanded": _spv.model_parts_expanded(),
            "show_all": self._model_parts_show_all,
            "selected_box": _spv.selected_part_box(),
            "toast": self._current_toast(),
            "mount_editing_enabled": not locked,
            "mount_editing_reason": reason,
            "rows": rows,
        }

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
        if self._pipette_armed:
            self._pipette_armed = False
            self._last_pushed = None
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
            if not down or self._current_target_is_locked_mount():
                # Release edge, OR the lock engaged mid-gesture (e.g. a
                # Preview click landed between two drag frames): end the
                # drag without applying any further delta. No pin pick.
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
            if self._current_target_is_locked_mount():
                # Refuse the grab outright: the click falls through to an
                # ordinary orbit-press, exactly as if no gizmo handle were
                # under the cursor. THE actual gate -- see
                # _current_target_is_locked_mount's docstring for why this
                # cannot be the DOM's `disabled` attribute alone.
                return False
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
        cluster — all THREE rows: the render-tools row (#spv-tools), the
        transform-tools row (#spv-transform-tools), and the action-tools row
        (#spv-action-tools) stacked above it.

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
        """Public dispatch entry point: wraps `_dispatch_event_inner` with the
        undo snapshot/record bracket, skipping "undo"/"save"/"cancel" (which
        themselves clear/discard state) and "overlay:" chrome toggles."""
        if action in self._NO_UNDO_ACTIONS or action.startswith("overlay:"):
            result = self._dispatch_event_inner(action)
        else:
            before = self._snapshot_pending()
            result = self._dispatch_event_inner(action)
            if before != self._snapshot_pending():
                self._undo_stack.append(before)
        # Every action -- a node select, an undo, a node removed from under
        # its selection -- may change which pose the rig should be drawn in.
        if self._visible:
            self._sync_part_pose()
        return result

    # Actions that pick TOWARD subsystem/light/emitter editing -- refused
    # outright while mount editing is locked, not just greyed in the DOM.
    _MOUNT_SELECT_ACTIONS = (
        "select_pin:", "select_light:", "select_emitter:",
        "add_light:", "remove_light:", "add_emitter:", "remove_emitter:",
        "set_radius:", "set_light:", "set_emitter:",
    )
    # Shared gizmo verbs: these edit whatever the CURRENT transform target is,
    # so they are refused only when that target is a subsystem/light/emitter
    # mount. (A part is never a transform target -- see
    # _active_transform_target -- and the part/* actions are never locked:
    # tuning the very pose you are looking at is the point.)
    _MOUNT_GIZMO_VERBS = (
        "pipette", "coord_copy", "coord_paste", "coord_mirror",
        "scale_copy", "scale_paste", "scale_uniform",
        "rotate_copy", "rotate_paste", "rotate_mirror", "mirror_element",
    )
    _MOUNT_GIZMO_PREFIXES = ("coord_nudge:", "scale_nudge:", "rotate_nudge:")

    def _current_target_is_locked_mount(self) -> bool:
        """True when mount editing is locked AND the CURRENT transform
        target is a subsystem/light/emitter mount -- the single predicate
        both the action-string gate (`_is_locked_mount_action`, for
        `_dispatch_event_inner`) and the raw mouse-driven gizmo drag gate
        (`_handle_gizmo_input` / the `_apply_*_drag` methods) consult, so
        there is exactly one place that decides "is the thing under the
        gizmo right now a locked mount" rather than two copies that could
        drift."""
        if self._mount_editing_enabled():
            return False
        t = self._active_transform_target()
        return t is not None and t[0] in ("subsystem", "light", "emitter")

    def _is_locked_mount_action(self, action: str) -> bool:
        """True when `action` would select-toward-editing or edit a
        subsystem/light/emitter mount while `_mount_editing_enabled()` is
        False -- see `_dispatch_event_inner`'s call site and the module
        docstring of `tests/unit/test_spv_part_controls.py` for why this must
        be a Python-side gate, not only a greyed-out DOM: a stale click, a queued
        event, or a JS path that skips the disabled attribute must not slip
        an edit through. Covers ACTION STRINGS only -- the raw mouse-driven
        gizmo drag (`_handle_gizmo_input`) never goes through
        `_dispatch_event_inner` at all and is gated separately, by
        `_current_target_is_locked_mount()` directly."""
        if action.startswith(self._MOUNT_SELECT_ACTIONS):
            return True
        if action in self._MOUNT_GIZMO_VERBS or action.startswith(self._MOUNT_GIZMO_PREFIXES):
            return self._current_target_is_locked_mount()
        return False

    def _dispatch_event_inner(self, action: str) -> bool:
        if not self._mount_editing_enabled() and self._is_locked_mount_action(action):
            return False
        if action == "pipette":
            if self._pipette_armed:
                self._pipette_armed = False
            elif self._active_transform_target() is not None:
                self._pipette_armed = True
            self._last_pushed = None
            return True
        if self._pipette_armed:
            src = None
            if action.startswith("select_pin:"):
                try:
                    idx = int(action.split(":", 1)[1])
                except ValueError:
                    idx = -1
                if 0 <= idx < len(self._descriptors):
                    src = ("subsystem", idx)
            elif action.startswith("select_light:"):
                try:
                    idx = int(action.split(":", 1)[1])
                except ValueError:
                    idx = -1
                if 0 <= idx < len(self._descriptors) and self._has_light(idx):
                    src = ("light", idx)
            elif action.startswith("select_emitter:"):
                try:
                    arg = json.loads(action.split(":", 1)[1])
                    i = int(arg["i"]); j = int(arg["j"])
                except (ValueError, KeyError, TypeError):
                    i = j = -1
                if 0 <= i < len(self._descriptors) and self._effective_emitter(i, j) is not None:
                    src = ("emitter", i, j)
            # Any select_* while armed consumes the pick (valid → apply); any other
            # action, or an invalid pick, cancels the arm and falls through.
            if action.startswith(("select_pin:", "select_light:", "select_emitter:")):
                self._pipette_armed = False
                self._last_pushed = None
                if src is not None:
                    self._apply_pipette(src)
                return True
            self._pipette_armed = False
            self._last_pushed = None
            # fall through to normal handling of the non-select action
        if action == "undo":
            self.undo()
            return True
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
        if action == "model_parts/toggle":
            _spv.toggle_model_parts_expanded()
            self._last_pushed = None  # re-push so the pane's expanded state updates
            return True
        if action == "model_parts/toggle_show_all":
            self._model_parts_show_all = not self._model_parts_show_all
            self._last_pushed = None
            return True
        if action.startswith("model_parts/select:"):
            name = action.split(":", 1)[1]
            _spv.select_model_part(name, self._model_part_nodes)
            # Mutually exclusive with subsystem/light/emitter selection, same
            # as those three are with each other. (A part row is not itself a
            # transform target -- see _active_transform_target.)
            if _spv.selected_model_part() is not None:
                self.selected_index = None
                self._selected_light_index = None
                self._selected_emitter = None
            self._last_pushed = None
            return True
        if action.startswith("part/"):
            return self._dispatch_part_action(action)
        if action.startswith("select_pin:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if 0 <= idx < len(self._descriptors):
                self.selected_index = idx
                self._selected_light_index = None
                self._selected_emitter = None
                _spv.select_model_part(None, self._model_part_nodes)
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
            self._selected_emitter = None
            _spv.select_model_part(None, self._model_part_nodes)
            self._expanded_groups.add(self._descriptors[idx].get("name", ""))
            self._last_pushed = None
            return True
        if action.startswith("add_light:"):
            payload = action.split(":", 1)[1]
            shape = None
            try:
                arg = json.loads(payload)
                idx = int(arg["i"]); shape = str(arg["shape"])
            except (ValueError, KeyError, TypeError):
                try:
                    idx = int(payload)          # legacy bare-int payload
                except ValueError:
                    return False
            if not (0 <= idx < len(self._descriptors)) or self._has_light(idx):
                return False
            base = self._descriptors[idx].get("light_region")
            if not base:
                return False
            spec = dict(base)
            if shape in ("Sphere", "Cylinder", "Box"):
                spec["shape"] = shape
            self._pending_light[idx] = spec
            self._selected_light_index = idx
            self.selected_index = None
            self._selected_emitter = None
            _spv.select_model_part(None, self._model_part_nodes)
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
        if action.startswith("select_emitter:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                i = int(arg["i"]); j = int(arg["j"])
            except (ValueError, KeyError, TypeError):
                return False
            if (not (0 <= i < len(self._descriptors))
                    or self._effective_emitter(i, j) is None):
                return False
            self._selected_emitter = (i, j)
            self.selected_index = None
            self._selected_light_index = None
            _spv.select_model_part(None, self._model_part_nodes)
            self._expanded_groups.add(self._descriptors[i].get("name", ""))
            self._last_pushed = None
            return True
        if action.startswith("add_emitter:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                i = int(arg["i"]); kind = str(arg["kind"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0 <= i < len(self._descriptors)) or kind not in ("point", "strip", "cone"):
                return False
            from engine.appc.light_emitters import default_emitter_spec
            # Stage a full copy of the compacted list with the new emitter
            # appended — never a sparse (i,j) override — so indices stay
            # dense (see _pending_emitter docstring: baked_emitters() stops
            # at the first gap on reload).
            spec = default_emitter_spec(kind)
            # Seed-on-add: the CEF modal picks colour/intensity before the
            # emitter exists, so it sends them in the SAME add_emitter
            # dispatch rather than a fragile echo-then-set round-trip (see
            # task-10-brief.md). Both are optional — the {i, kind}-only path
            # (existing callers, e.g. a bare "Add Light Volume" menu action)
            # still works and keeps the spec's stock default color/intensity.
            if "color" in arg:
                spec["color"] = tuple(float(c) for c in arg["color"])
            if "intensity" in arg:
                spec["intensity"] = float(arg["intensity"])
            lst = list(self._effective_emitters(i))
            lst.append(spec)
            self._pending_emitter[i] = lst
            self._selected_emitter = (i, len(lst) - 1)
            self.selected_index = None
            self._selected_light_index = None
            _spv.select_model_part(None, self._model_part_nodes)
            self._expanded_groups.add(self._descriptors[i].get("name", ""))
            self._last_pushed = None
            return True
        if action.startswith("remove_emitter:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                i = int(arg["i"]); j = int(arg["j"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0 <= i < len(self._descriptors)):
                return False
            lst = list(self._effective_emitters(i))
            if not (0 <= j < len(lst)):
                return False
            del lst[j]                          # keeps remaining indices dense
            self._pending_emitter[i] = lst
            # A shifted selection is not re-tracked: any (i,j) selection on
            # this subsystem is invalidated by a removal (positions may have
            # moved), so simplest-correct is to always clear it here.
            if self._selected_emitter is not None and self._selected_emitter[0] == i:
                self._selected_emitter = None
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
            if (self.selected_index is None and self._selected_light_index is None
                    and self._selected_emitter is None):
                return False
            self.selected_index = None
            self._selected_light_index = None
            self._selected_emitter = None
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
            if not (0 <= idx < len(self._descriptors)) or shape not in ("Sphere", "Cylinder", "Box"):
                return False
            base = dict(self._effective_light(idx)
                        or self._descriptors[idx].get("light_region") or {})
            spec = {"shape": shape,
                    "position": tuple(base.get("position") or (0.0, 0.0, 0.0)),
                    "axis": tuple(base.get("axis") or (0.0, -1.0, 0.0)),
                    "radius": base.get("radius") or (0.25,),
                    "extent": base.get("extent") or (0.0, 2.0),
                    "scale": base.get("scale") or (0.25, 0.25, 0.25),
                    "orientation": base.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))}
            self._pending_light[idx] = spec
            self._last_pushed = None
            return True
        if action.startswith("set_emitter:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                i = int(arg["i"]); j = int(arg["j"]); kind = str(arg["kind"])
            except (ValueError, KeyError, TypeError):
                return False
            if kind not in ("point", "strip", "cone"):
                return False
            if not (0 <= i < len(self._descriptors)):
                return False
            lst = list(self._effective_emitters(i))
            if not (0 <= j < len(lst)):
                return False
            spec = dict(lst[j])
            spec["kind"] = kind
            if "color" in arg:
                spec["color"] = tuple(float(c) for c in arg["color"])
            if "intensity" in arg:
                spec["intensity"] = float(arg["intensity"])
            lst[j] = spec
            self._pending_emitter[i] = lst    # whole-list restage, dense j
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
            # _scale_kind_and_fields is emitter-aware (Task 7): a point emitter
            # copies real ("radius", (r,)), a strip/cone copies real
            # ("radius_length", (r, l)) — no inert placeholder to clobber the
            # clipboard with. The kind-match on scale_paste keeps a "radius"
            # clipboard from writing onto an "xyz"/"radius_length" target.
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
                # Only Box lights have kind "xyz"; emitters/subsystems/other
                # lights are naturally a no-op here.
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
                if t[0] == "emitter":
                    _, i, j = t
                    spec = self._effective_emitter(i, j) or {}
                    if spec.get("kind") == "cone":
                        from engine.appc.light_emitters import _derive_up
                        fwd = spec.get("axis") or (0.0, -1.0, 0.0)
                        up = spec.get("up") or _derive_up(fwd)
                        self._rotate_clipboard = (
                            "cone_orientation", (tuple(fwd), tuple(up)))
                    else:
                        axis = spec.get("axis") or (0.0, -1.0, 0.0)
                        self._rotate_clipboard = ("cylinder_axis", tuple(axis))
                else:
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
            if (t is not None
                    and self._rotate_clipboard is not None
                    and self._rotate_clipboard[0] == self._rotate_clipboard_kind(t)):
                if self._rotate_clipboard[0] == "box_orientation":
                    # box_orientation only matches a Box LIGHT target (an emitter
                    # kind is cylinder_axis/cone_orientation), so t is
                    # ("light", i) here.
                    fwd, up = self._rotate_clipboard[1]
                    self._set_orientation_absolute(t[1], fwd, up)
                elif self._rotate_clipboard[0] == "cone_orientation":
                    # cone_orientation only matches a CONE emitter target.
                    fwd, up = self._rotate_clipboard[1]
                    self._set_orientation_absolute(t, fwd, up)
                else:
                    self._set_axis_absolute(t, self._rotate_clipboard[1])
            return True
        if action == "rotate_mirror":
            t = self._rotate_target()
            if t is not None:
                self._mirror_target_rotation(t)
            return True
        if action == "mirror_element":
            t = self._active_transform_target()
            if t is not None:
                pos = self._transform_target_pos()
                if pos is not None:
                    self._set_transform_target_pos((-pos[0], pos[1], pos[2]))
                rt = self._rotate_target()
                if rt is not None:
                    self._mirror_target_rotation(rt)
            return True
        if action == "save":
            if (not self._pending_radius and not self._pending_light
                    and not self._pending_pos and not self._pending_emitter
                    and not self._pending_part):
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
            edits += self._emitter_save_edits()
            edits += _spv.part_save_edits(self._pending_part)
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
            self._saved_emitter.update(self._pending_emitter)
            self._pending_emitter = {}
            self._saved_part.update(self._pending_part)
            self._pending_part = {}
            self._undo_stack.clear()
            self._drag_undo_before = None
            self._last_pushed = None
            if self._on_saved is not None:
                try:
                    from engine.ui.ship_property_viewer import _iter_subsystems
                    specs_by_sub_id = {}
                    di = 0
                    for sub in _iter_subsystems(ship):
                        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
                        if local is None:
                            continue                       # same skip as build_descriptors
                        specs_by_sub_id[id(sub)] = self._effective_emitters(di)
                        di += 1
                    self._on_saved(ship, specs_by_sub_id)
                except Exception:
                    pass   # live refresh is best-effort; never break Save/persistence
            if self._on_regions_saved is not None:
                try:
                    self._on_regions_saved(ship, self._effective_regions_by_sub(ship))
                except Exception:
                    pass   # live refresh is best-effort; never break Save/persistence
            return True
        return False
