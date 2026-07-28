import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1: payload.rindex(")")])


def test_panel_starts_closed_and_payload_is_hide():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    assert p.is_open() is False
    payload = p.render_payload()
    assert payload is not None and "setShipPropertyViewer" in payload
    assert _payload_data(payload)["visible"] is False


def test_open_builds_descriptors_and_payload_lists_subsystems(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy", "properties": {"name": "Phaser 1"}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert p.is_open() is True
    data = _payload_data(p.render_payload())
    assert data["visible"] is True
    assert data["pin_count"] == 1


def test_close_resets_and_emits_hide():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open(); p.close()
    assert p.is_open() is False
    assert p.selected_index is None


def test_select_pin_sets_popover_payload(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy",
             "properties": {"name": "Phaser 1", "type": "PhaserBank"}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert p.dispatch_event("select_pin:0") is True
    assert p.selected_index == 0
    data = _payload_data(p.render_payload())
    assert data["selected"]["properties"]["type"] == "PhaserBank"


def test_reopen_with_same_pin_count_repushes(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy", "properties": {"name": "Phaser 1"}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert p.render_payload() is not None      # first push
    assert p.render_payload() is None          # unchanged → diffed out
    p.close()
    assert p.render_payload() is not None       # hide push
    p.open()                                     # reopen, same pin_count
    assert p.render_payload() is not None       # MUST re-push, not None


def test_camera_frames_ship_in_world_space_not_origin(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    # Two mounts ~500 GU from origin, 2 GU apart → centroid near (500,*,*),
    # fit distance driven by the 1 GU half-spread, NOT the 500 GU offset.
    fake = [{"name": "A", "world_pos": (500.0, 1.0, 0.0),
             "state": "healthy", "properties": {}, "icon_id": 6},
            {"name": "B", "world_pos": (500.0, -1.0, 0.0),
             "state": "healthy", "properties": {}, "icon_id": 6}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert abs(p.camera.target[0] - 500.0) < 1e-6
    assert p.camera.distance < 50.0   # framed to the cloud, not the 500 GU offset


def test_close_after_open_emits_hide_payload(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [{"name": "A", "world_pos": (0, 0, 0),
                                       "state": "healthy", "properties": {},
                                       "icon_id": 6}])
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open(); p.render_payload()
    p.close()
    payload = p.render_payload()
    assert payload is not None
    assert '"visible": false' in payload.lower()


def test_deselect_noop_returns_false(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy", "properties": {}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p.render_payload()  # consume first push
    # deselect when nothing selected → no-op, no re-push
    assert p.dispatch_event("deselect") is False
    assert p.render_payload() is None  # snapshot unchanged → no spurious push


# ---------------------------------------------------------------------------
# Input handling (task D1): orbit / zoom / pick
# ---------------------------------------------------------------------------

import math

from engine.ui.ship_property_viewer import OrbitCamera
import engine.ui.ship_property_viewer_panel as _mod


class _FakeHost:
    """Minimal stand-in for the _dauntless_host bindings module."""
    class keys:
        MOUSE_BUTTON_LEFT = 0

    def __init__(self):
        self._cursor = (0.0, 0.0)
        self._down = False
        self._scroll = 0.0
        self._fb = (800, 600)

    def cursor_pos(self):
        return self._cursor

    def framebuffer_size(self):
        return self._fb

    def mouse_button_state(self, button):
        return self._down

    def consume_scroll_y(self):
        s = self._scroll
        self._scroll = 0.0
        return s


def _open_panel(monkeypatch, descriptors=None):
    monkeypatch.setattr(_mod, "build_descriptors",
                        lambda ship: descriptors or [])
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    return p


def test_apply_orbit_advances_yaw_and_pitch():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.camera = OrbitCamera(target=(0, 0, 0), distance=10.0, yaw=0.0, pitch=0.0)
    p.apply_orbit(50.0, -20.0)
    assert math.isclose(p.camera.yaw, 50.0 * _mod.ORBIT_SENS)
    assert math.isclose(p.camera.pitch, -20.0 * _mod.ORBIT_SENS)


def test_apply_zoom_scales_distance_and_clamps():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.camera = OrbitCamera(target=(0, 0, 0), distance=100.0)
    p.apply_zoom(1.0)  # zoom in by one notch
    assert math.isclose(p.camera.distance, 100.0 * (1.0 - _mod.ZOOM_STEP))
    # Clamp to MIN on extreme zoom-in.
    p.camera.distance = _mod.MIN_DISTANCE
    p.apply_zoom(100.0)
    assert p.camera.distance == _mod.MIN_DISTANCE
    # Clamp to MAX on extreme zoom-out.
    p.camera.distance = _mod.MAX_DISTANCE
    p.apply_zoom(-100.0)
    assert p.camera.distance == _mod.MAX_DISTANCE


def test_zoom_by_factor_multiplies_and_clamps():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.camera = OrbitCamera(target=(0, 0, 0), distance=100.0)
    p.zoom_by_factor(_mod.ZOOM_KEY_FACTOR)            # = key (zoom in)
    assert math.isclose(p.camera.distance, 100.0 * _mod.ZOOM_KEY_FACTOR)
    p.zoom_by_factor(1.0 / _mod.ZOOM_KEY_FACTOR)      # - key (zoom out)
    assert math.isclose(p.camera.distance, 100.0)
    p.camera.distance = _mod.MIN_DISTANCE
    p.zoom_by_factor(_mod.ZOOM_KEY_FACTOR)            # cannot go below MIN
    assert p.camera.distance == _mod.MIN_DISTANCE


def test_handle_input_equals_key_zooms_in():
    class _KeyHost(_FakeHost):
        class keys(_FakeHost.keys):
            KEY_EQUAL = 61
            KEY_MINUS = 45
        def __init__(self, pressed):
            super().__init__()
            self._pressed = pressed
        def key_pressed(self, code):
            return code == self._pressed
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.camera = OrbitCamera(target=(0, 0, 0), distance=100.0)
    p.handle_input(_KeyHost(pressed=61))   # '=' down → zoom in
    assert math.isclose(p.camera.distance, 100.0 * _mod.ZOOM_KEY_FACTOR)
    p.handle_input(_KeyHost(pressed=45))   # '-' down → zoom out
    assert math.isclose(p.camera.distance, 100.0)


def test_handle_input_drag_orbits_camera(monkeypatch):
    fake = [{"name": "A", "icon_id": 1, "world_pos": (0, 5, 0),
             "state": "healthy", "properties": {}}]
    p = _open_panel(monkeypatch, fake)
    yaw0 = p.camera.yaw
    h = _FakeHost()
    # Press at (400, 300).
    h._cursor = (400.0, 300.0); h._down = True
    p.handle_input(h)
    # Drag right by 30 px → yaw advances.
    h._cursor = (430.0, 300.0)
    p.handle_input(h)
    assert math.isclose(p.camera.yaw, yaw0 + 30.0 * _mod.ORBIT_SENS)


def test_handle_input_click_picks_pin(monkeypatch):
    # One pin at the orbit target → projects to screen centre.
    fake = [{"name": "A", "icon_id": 1, "world_pos": (0, 0, 0),
             "state": "healthy", "properties": {}}]
    p = _open_panel(monkeypatch, fake)
    # Force camera to look straight at the single pin at origin.
    p.camera = OrbitCamera(target=(0, 0, 0), distance=20.0)
    h = _FakeHost()
    cx, cy = h._fb[0] / 2.0, h._fb[1] / 2.0
    # Press then release at screen centre, no drag → click → pick.
    h._cursor = (cx, cy); h._down = True
    p.handle_input(h)
    h._down = False
    p.handle_input(h)
    assert p.selected_index == 0


def test_handle_input_click_on_empty_space_deselects(monkeypatch):
    fake = [{"name": "A", "icon_id": 1, "world_pos": (1000, 1000, 1000),
             "state": "healthy", "properties": {}}]
    p = _open_panel(monkeypatch, fake)
    p.camera = OrbitCamera(target=(0, 0, 0), distance=20.0)
    p.selected_index = 0  # pretend something was selected
    h = _FakeHost()
    # Empty 3D area — right of the left column, below the titlebar (clicks
    # inside those chrome regions belong to CEF and never reach the pick).
    h._cursor = (600.0, 300.0); h._down = True
    p.handle_input(h)
    h._down = False
    p.handle_input(h)
    assert p.selected_index is None


def test_handle_input_drag_then_release_is_not_a_pick(monkeypatch):
    fake = [{"name": "A", "icon_id": 1, "world_pos": (0, 0, 0),
             "state": "healthy", "properties": {}}]
    p = _open_panel(monkeypatch, fake)
    p.camera = OrbitCamera(target=(0, 0, 0), distance=20.0)
    h = _FakeHost()
    cx, cy = h._fb[0] / 2.0, h._fb[1] / 2.0
    h._cursor = (cx, cy); h._down = True
    p.handle_input(h)
    h._cursor = (cx + 40.0, cy)  # big drag past CLICK_SLOP_PX
    p.handle_input(h)
    h._down = False
    p.handle_input(h)
    assert p.selected_index is None  # drag, not click → no pick


def test_handle_input_missing_bindings_is_noop():
    # Headless: a host without mouse bindings must not raise.
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.camera = OrbitCamera(target=(0, 0, 0), distance=10.0)

    class _Bare:
        pass

    p.handle_input(_Bare())  # no exception


def test_frame_to_bounds_centers_and_fills(monkeypatch):
    import math
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [{"name": "A", "world_pos": (0, 0, 0),
                                       "state": "healthy", "properties": {},
                                       "icon_id": 6}])
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p.frame_to_bounds((100.0, 50.0, -7.0), 8.0)
    assert p.camera.target == (100.0, 50.0, -7.0)
    half = p.camera.fov_y_rad / 2.0
    expected = 8.0 / (mod.SCREEN_FILL * math.tan(half))
    assert abs(p.camera.distance - expected) < 1e-6


def test_frame_to_bounds_ignores_nonpositive_radius():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.camera = OrbitCamera(target=(1.0, 2.0, 3.0), distance=42.0)
    p.frame_to_bounds((9.0, 9.0, 9.0), 0.0)   # bad radius → no change
    assert p.camera.target == (1.0, 2.0, 3.0)
    assert p.camera.distance == 42.0


# ── titlebar overlay toggles (Glow Regions / Weapon Arcs) ──────────────────

def test_toggles_start_off_and_payload_carries_them():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open()
    assert p.show_glow_regions is False
    assert p.show_weapon_arcs is False
    assert p.show_hull_texture is False                 # hologram is default
    data = _payload_data(p.render_payload())
    assert data["show_glow"] is False
    assert data["show_arcs"] is False
    assert data["show_hull"] is False


def test_toggle_events_flip_flags_and_repush():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open()
    p.render_payload()                                  # settle the snapshot
    assert p.render_payload() is None                   # diffed out
    assert p.dispatch_event("toggle_glow_regions") is True
    data = _payload_data(p.render_payload())            # toggle → re-push
    assert data["show_glow"] is True and data["show_arcs"] is False
    assert p.dispatch_event("toggle_weapon_arcs") is True
    data = _payload_data(p.render_payload())
    assert data["show_arcs"] is True
    # Hull-texture toggle flips the render mode + re-pushes.
    assert p.dispatch_event("toggle_hull_texture") is True
    assert _payload_data(p.render_payload())["show_hull"] is True
    # Toggling back off flips + re-pushes again.
    assert p.dispatch_event("toggle_glow_regions") is True
    assert _payload_data(p.render_payload())["show_glow"] is False
    assert p.dispatch_event("toggle_hull_texture") is True
    assert _payload_data(p.render_payload())["show_hull"] is False


def test_toggles_reset_on_reopen_and_close():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open()
    p.dispatch_event("toggle_glow_regions")
    p.dispatch_event("toggle_weapon_arcs")
    p.dispatch_event("toggle_hull_texture")
    p.close()
    assert p.show_glow_regions is False
    assert p.show_weapon_arcs is False
    assert p.show_hull_texture is False
    p.open()
    assert p.show_glow_regions is False
    assert p.show_weapon_arcs is False
    assert p.show_hull_texture is False


# ── left-column subsystem list payload ─────────────────────────────────────

def test_payload_lists_subsystems_with_targetable_and_condition(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [
        {"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
         "state": "healthy", "targetable": True, "condition_pct": 88,
         "properties": {"name": "Phaser 1"}},
        {"name": "Shuttle Bay", "icon_id": 6, "world_pos": (0, 0, 1),
         "state": "mount", "kind": "mount", "targetable": False,
         "condition_pct": None, "properties": {"name": "Shuttle Bay"}},
    ]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    data = _payload_data(p.render_payload())
    subs = data["subsystems"]
    assert [s["name"] for s in subs] == ["Phaser 1", "Shuttle Bay"]
    assert subs[0]["targetable"] is True and subs[0]["condition_pct"] == 88
    assert subs[1]["targetable"] is False and subs[1]["condition_pct"] is None
    assert subs[1]["kind"] == "mount"
    assert data["selected_index"] is None
    p.dispatch_event("select_pin:1")
    assert _payload_data(p.render_payload())["selected_index"] == 1


# ── CEF chrome regions own their mouse input ───────────────────────────────

def test_wheel_over_left_column_is_left_for_cef():
    p = _open_panel_for_input()
    host = _FakeHost()
    host._scroll = 2.0
    host._cursor = (100.0, 300.0)          # inside the left column
    d0 = p.camera.distance
    p.handle_input(host)
    assert p.camera.distance == d0         # no zoom...
    assert host._scroll == 2.0             # ...and accumulator untouched


def test_wheel_outside_left_column_still_zooms():
    p = _open_panel_for_input()
    host = _FakeHost()
    host._scroll = 2.0
    host._cursor = (600.0, 300.0)          # open 3D area
    d0 = p.camera.distance
    p.handle_input(host)
    assert p.camera.distance < d0
    assert host._scroll == 0.0


def test_press_over_chrome_never_orbits_or_picks(monkeypatch):
    p = _open_panel_for_input()
    host = _FakeHost()
    picked = []
    monkeypatch.setattr(p, "pick_at", lambda *a, **k: picked.append(a))
    yaw0 = p.camera.yaw
    # Press inside the left column, drag, release — all ignored.
    host._cursor = (100.0, 300.0); host._down = True
    p.handle_input(host)
    host._cursor = (150.0, 350.0)
    p.handle_input(host)
    assert p.camera.yaw == yaw0
    host._down = False
    p.handle_input(host)
    assert picked == []
    # Titlebar press is chrome too.
    host._cursor = (600.0, 10.0); host._down = True
    p.handle_input(host)
    host._down = False
    p.handle_input(host)
    assert picked == []
    # A press in the open 3D area still picks on release.
    host._cursor = (600.0, 300.0); host._down = True
    p.handle_input(host)
    host._down = False
    p.handle_input(host)
    assert len(picked) == 1


def test_press_over_bottom_right_tools_never_orbits_or_picks(monkeypatch):
    """The relocated tool-button cluster (bottom-right) owns its clicks."""
    p = _open_panel_for_input()
    host = _FakeHost()                          # fb 800×600, dsf 1.0
    picked = []
    monkeypatch.setattr(p, "pick_at", lambda *a, **k: picked.append(a))
    yaw0 = p.camera.yaw
    # Centre of the cluster, derived from the panel's own geometry constants so
    # this survives adding/removing tool buttons.
    cx = 800.0 - (_mod.TOOLS_MARGIN_PT + _mod.TOOLS_W_PT / 2.0)
    cy = 600.0 - (_mod.TOOLS_MARGIN_PT + _mod.TOOLS_H_PT / 2.0)
    host._cursor = (cx, cy); host._down = True
    p.handle_input(host)
    host._cursor = (cx + 5.0, cy + 2.0)          # small drag
    p.handle_input(host)
    assert p.camera.yaw == yaw0                 # no orbit
    host._down = False
    p.handle_input(host)
    assert picked == []                         # no pick


def test_cursor_over_tools_covers_both_transform_and_render_rows():
    """_cursor_over_tools must guard the transform row (above) AND the
    render-tool row (below) as one contiguous chrome cluster, so a click on
    a Transform/Rotate/Scale button is never mistaken for a viewport click."""
    fb_w, fb_h, dsf = 800.0, 600.0, 1.0
    # Point inside the (new, upper) transform-tools row.
    x_transform = fb_w - _mod.TOOLS_MARGIN_PT - 20.0
    y_transform = (fb_h - _mod.TOOLS_MARGIN_PT - _mod.TOOLS_H_PT
                   - _mod.TOOLS_GAP_PT - 20.0)
    assert _mod.ShipPropertyViewerPanel._cursor_over_tools(
        x_transform, y_transform, dsf, fb_w, fb_h) is True
    # Point inside the original (lower) render-tools row still guarded.
    x_render = fb_w - _mod.TOOLS_MARGIN_PT - 20.0
    y_render = fb_h - _mod.TOOLS_MARGIN_PT - 20.0
    assert _mod.ShipPropertyViewerPanel._cursor_over_tools(
        x_render, y_render, dsf, fb_w, fb_h) is True
    # Point above the whole cluster is not chrome.
    x_above = fb_w - _mod.TOOLS_MARGIN_PT - 20.0
    y_above = (fb_h - _mod.TOOLS_MARGIN_PT - _mod.TOOLS_CLUSTER_H_PT
               - 20.0)
    assert _mod.ShipPropertyViewerPanel._cursor_over_tools(
        x_above, y_above, dsf, fb_w, fb_h) is False


def test_cursor_over_coords_guards_top_right_box():
    fb_w, fb_h, dsf = 800.0, 600.0, 1.0
    # A point inside the top-right coords box.
    x_in = fb_w - _mod.COORDS_MARGIN_PT - 20
    y_in = _mod.COORDS_TOP_PT + 20
    assert _mod.ShipPropertyViewerPanel._cursor_over_coords(
        x_in, y_in, dsf, fb_w, fb_h) is True
    # A point in the centre (not the box).
    assert _mod.ShipPropertyViewerPanel._cursor_over_coords(
        fb_w / 2, fb_h / 2, dsf, fb_w, fb_h) is False
    # Unknown viewport → False.
    assert _mod.ShipPropertyViewerPanel._cursor_over_coords(
        x_in, y_in, dsf, 0.0, 0.0) is False


def _open_panel_for_input():
    from engine.ui.ship_property_viewer import OrbitCamera as _Cam
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open()
    p.camera = _Cam(target=(0, 0, 0), distance=100.0)
    return p


# ── grouped (accordion) subsystem list ─────────────────────────────────────

_GROUPED = [
    {"name": "Warp Engines", "icon_id": 4, "world_pos": (0, -2, 0),
     "state": "healthy", "targetable": True, "condition_pct": 100,
     "parent_index": None, "properties": {"name": "Warp Engines"}},
    {"name": "Port Nacelle", "icon_id": 4, "world_pos": (-3, -2, 0),
     "state": "healthy", "targetable": True, "condition_pct": 75,
     "parent_index": 0, "properties": {"name": "Port Nacelle"}},
    {"name": "Star Nacelle", "icon_id": 4, "world_pos": (3, -2, 0),
     "state": "healthy", "targetable": True, "condition_pct": 75,
     "parent_index": 0, "properties": {"name": "Star Nacelle"}},
    {"name": "Sensor Array", "icon_id": 5, "world_pos": (0, 2, 0),
     "state": "healthy", "targetable": True, "condition_pct": 100,
     "parent_index": None, "properties": {"name": "Sensor Array"}},
]


def _open_grouped(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: _GROUPED)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    return p


def test_payload_nests_children_under_parent_collapsed_by_default(monkeypatch):
    p = _open_grouped(monkeypatch)
    subs = _payload_data(p.render_payload())["subsystems"]
    assert [s["name"] for s in subs] == ["Warp Engines", "Sensor Array"]
    warp = subs[0]
    assert warp["index"] == 0
    assert warp["expanded"] is False
    assert [c["name"] for c in warp["children"]] == ["Port Nacelle", "Star Nacelle"]
    assert [c["index"] for c in warp["children"]] == [1, 2]
    assert "expanded" not in subs[1]        # childless rows carry no flag


def test_toggle_group_expands_and_collapses(monkeypatch):
    p = _open_grouped(monkeypatch)
    assert p.dispatch_event("toggle_group:0") is True
    assert _payload_data(p.render_payload())["subsystems"][0]["expanded"] is True
    assert p.dispatch_event("toggle_group:0") is True
    assert _payload_data(p.render_payload())["subsystems"][0]["expanded"] is False
    assert p.dispatch_event("toggle_group:99") is False


def test_select_pin_reveals_its_group(monkeypatch):
    p = _open_grouped(monkeypatch)
    p.dispatch_event("select_pin:2")        # Star Nacelle, inside collapsed group
    data = _payload_data(p.render_payload())
    assert data["selected_index"] == 2
    assert data["subsystems"][0]["expanded"] is True


def test_expansion_resets_on_reopen(monkeypatch):
    p = _open_grouped(monkeypatch)
    p.dispatch_event("toggle_group:0")
    p.close()
    p.open()
    assert _payload_data(p.render_payload())["subsystems"][0]["expanded"] is False


# ── staged radius edits (Task 4) ────────────────────────────────────────────

import json as _json


class _RadiusShip:
    def GetScript(self):
        return "ships.Galaxy"


def _rad_descriptor(name):
    return {"name": name, "icon_id": 0, "world_pos": (0, 0, 0),
            "state": "healthy", "targetable": True, "condition_pct": 100,
            "parent_index": None,
            "properties": {"name": name, "radius": 0.25}}


def test_set_radius_stages_pending_and_marks_dirty(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    ok = p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    assert ok is True
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1
    assert data["subsystems"][0]["dirty"] is True
    # Readout reflects the staged value (no live mutation needed).
    p.selected_index = 0
    p._last_pushed = None
    assert _payload_data(p.render_payload())["selected"]["properties"]["radius"] == 0.5


def test_save_routes_edits_and_clears(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits): calls.append((leaf, edits))

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    p.dispatch_event("save")
    assert calls == [("galaxy", [("Center Impulse", "SetRadius", (0.5,))])]
    assert _payload_data(p.render_payload())["pending_count"] == 0


def test_save_keeps_pending_when_write_fails(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod

    class _FailingTarget:
        def write(self, leaf, edits):
            raise RuntimeError("disk full")

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _FailingTarget())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    ok = p.dispatch_event("save")
    assert ok is True
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1
    assert data["subsystems"][0]["dirty"] is True


def test_overlay_open_suppresses_orbit():
    p = _open_panel_for_input()
    p.dispatch_event("overlay:1")
    host = _FakeHost()
    yaw0 = p.camera.yaw
    host._cursor = (600.0, 300.0); host._down = True
    p.handle_input(host)
    host._cursor = (650.0, 350.0)
    p.handle_input(host)
    assert p.camera.yaw == yaw0


def test_close_without_save_discards_pending(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    p.close()
    p.open()
    assert _payload_data(p.render_payload())["pending_count"] == 0


def test_esc_with_overlay_open_closes_overlay_not_panel(monkeypatch):
    # ESC is read raw (GLFW), independent of CEF focus, by host_loop's
    # modal-ESC router, which calls handle_key_esc() directly — while a CEF
    # overlay (context menu / radius modal / confirm) is open, ESC must
    # close ONLY the overlay and preserve staged edits, never tear down the
    # whole panel (which would discard _pending_radius).
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    p.dispatch_event("overlay:1")
    assert p._overlay_open is True

    p.handle_key_esc()

    assert p.is_open() is True
    assert p._overlay_open is False
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1          # edit preserved, not discarded
    assert data["close_overlays"] is True       # one-shot signal to the JS

    # One-shot: the flag clears itself after being surfaced once.
    p._last_pushed = None
    data2 = _payload_data(p.render_payload())
    assert data2["close_overlays"] is False


def test_esc_without_overlay_closes_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    assert p._overlay_open is False

    p.handle_key_esc()

    assert p.is_open() is False


def test_payload_lists_modified_subsystems_with_tally(monkeypatch):
    # The Save-confirm modal lists modified subsystems + a change tally, e.g.
    # "Center Impulse (1)" — grouped by subsystem, not one row per value.
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse"),
                                      _rad_descriptor("Port Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    data = _payload_data(p.render_payload())
    assert data["pending"] == [{"name": "Center Impulse", "count": 1}]
    # A second subsystem's edit adds its own grouped row.
    p.dispatch_event("set_radius:" + _json.dumps({"i": 1, "value": 0.3}))
    data = _payload_data(p.render_payload())
    assert data["pending"] == [{"name": "Center Impulse", "count": 1},
                               {"name": "Port Impulse", "count": 1}]


def test_subsystem_rows_carry_radius(monkeypatch):
    # FIX 1: every row must carry its effective radius (pending value if
    # staged, else the descriptor's current radius) so a right-click on a
    # never-selected row still pre-fills the real value, not 0.
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    data = _payload_data(p.render_payload())
    assert data["subsystems"][0]["radius"] == 0.25

    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    data2 = _payload_data(p.render_payload())
    assert data2["subsystems"][0]["radius"] == 0.5


def test_set_radius_rejects_non_positive(monkeypatch):
    # FIX 2: 0 or negative radii must not be staged.
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    assert p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0})) is False
    assert p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": -1})) is False
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 0


def test_save_keeps_pending_when_leaf_unresolved(monkeypatch):
    # FIX 5 regression: if the hardpoint leaf can't be resolved, save() must
    # not call write() at all, and must keep the staged edit.
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits):
            calls.append((leaf, edits))

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: None)
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    ok = p.dispatch_event("save")
    assert ok is True
    assert calls == []
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1


# ── staged light/glow-region edits (Task 8) ─────────────────────────────────

import json as _json


def _light_descriptor(name):
    return {"name": name, "icon_id": 0, "world_pos": (0, 0, 0),
            "state": "healthy", "targetable": True, "condition_pct": 100,
            "parent_index": None, "light": True,
            "light_region": {"shape": "Cylinder", "position": (1.0, 0.0, 0.0),
                             "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                             "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)},
            "properties": {"name": name, "radius": 0.25}}


class _LightShip:
    def GetScript(self): return "ships.Galaxy"


def test_set_light_stages_and_marks_dirty(monkeypatch):
    # set_light is shape-only: it changes the shape and preserves the
    # existing spec's size/position fields (no size args accepted).
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    ok = p.dispatch_event("set_light:" + _json.dumps({"i": 0, "shape": "Box"}))
    assert ok is True
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1
    assert data["subsystems"][0]["dirty"] is True
    spec = p.pending_light_specs()["Center Impulse"]
    assert spec["shape"] == "Box"
    assert spec["radius"] == (0.25,)             # preserved from light_region
    assert spec["extent"] == (0.0, 2.0)          # preserved from light_region
    assert spec["scale"] == (0.25, 0.25, 0.25)   # preserved from light_region
    assert spec["position"] == (1.0, 0.0, 0.0)   # carried from light_region


def test_set_light_rejects_unknown_shape(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    ok = p.dispatch_event("set_light:" + _json.dumps({"i": 0, "shape": "Blob"}))
    assert ok is False
    assert _payload_data(p.render_payload())["pending_count"] == 0


def test_save_routes_light_region_edit(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits): calls.append((leaf, edits))
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("set_light:" + _json.dumps({"i": 0, "shape": "Box"}))
    p.dispatch_event("save")
    assert len(calls) == 1
    leaf, edits = calls[0]
    assert leaf == "galaxy"
    assert edits[0][0] == "Center Impulse"
    assert edits[0][1] == "__region__"
    assert edits[0][2] == 0
    assert ("SetGlowRegionShape", (0, "Box")) in edits[0][3]
    # scale/radius/extent carry through unchanged (shape-only edit).
    assert ("SetGlowRegionScale", (0, 0.25, 0.25, 0.25)) in edits[0][3]
    assert _payload_data(p.render_payload())["pending_count"] == 0


def test_subsystem_pins_shows_all_when_nothing_selected(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("A"), _rad_descriptor("B")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    pins = p.subsystem_pins()
    assert len(pins) == 2
    assert all(sel is False for _pos, _icon, sel in pins)


def test_subsystem_pins_hides_others_when_selected(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("A"), _rad_descriptor("B")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.selected_index = 1
    pins = p.subsystem_pins()
    assert len(pins) == 1                 # only the selected pin renders
    assert pins[0][2] is True             # flagged selected
    # Deselecting restores every pin.
    p.selected_index = None
    assert len(p.subsystem_pins()) == 2


def test_selected_subsystem_sphere_from_radius(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("A")])   # radius 0.25
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    assert p.selected_subsystem_sphere() is None       # nothing selected
    p.selected_index = 0
    sph = p.selected_subsystem_sphere()
    assert sph["center"] == (0, 0, 0)                  # world_pos passthrough
    assert sph["radius"] == 0.25
    assert sph["color"] == mod.SUBSYS_SPHERE_COLOR


def test_selected_sphere_reflects_pending_radius(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Shield Generator")])  # 0.25
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.selected_index = 0
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.7}))
    # The volume sphere reflects the STAGED radius immediately on Apply.
    assert p.selected_subsystem_sphere()["radius"] == 0.7


def test_selected_sphere_reflects_saved_radius_after_save(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod

    class _Target:
        def write(self, leaf, edits): pass

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Shield Generator")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.selected_index = 0
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.7}))
    p.dispatch_event("save")
    # Save persisted to file (not the live template); the sphere keeps showing
    # the saved radius for the rest of the session rather than snapping back.
    assert p.selected_subsystem_sphere()["radius"] == 0.7


def test_selected_subsystem_sphere_none_without_radius(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    d = _rad_descriptor("A")
    d["properties"]["radius"] = None                   # no usable radius
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: [d])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.selected_index = 0
    assert p.selected_subsystem_sphere() is None


def test_saved_light_keeps_driving_preview_after_save(monkeypatch):
    # After Save, the wireframe preview + modal pre-fill must keep showing the
    # SAVED shape (the file change only reaches the live template on the next
    # ship build), not snap back to the pre-save baked shape.
    import engine.ui.ship_property_viewer_panel as mod

    class _Target:
        def write(self, leaf, edits): pass

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("set_light:" + _json.dumps({"i": 0, "shape": "Box"}))
    p.dispatch_event("save")
    # Dirty/Save-bar state clears (the edit is no longer unsaved)...
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 0
    assert data["subsystems"][0]["dirty"] is False
    # ...but the saved Box still drives the live overlay + the light-child pre-fill.
    assert p.pending_light_specs()["Center Impulse"]["shape"] == "Box"
    child = data["subsystems"][0]["children"][0]
    assert child["light_region"]["shape"] == "Box"
    assert child["light_region"]["scale"] == [0.25, 0.25, 0.25]   # preserved


def test_saved_light_resets_on_close(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod

    class _Target:
        def write(self, leaf, edits): pass

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("set_light:" + _json.dumps(
        {"i": 0, "shape": "Box", "sx": 0.5, "sy": 0.6, "sz": 0.7}))
    p.dispatch_event("save")
    p.close()
    p.open()
    assert p.pending_light_specs() == {}


def test_row_light_region_reflects_pending_after_edit(monkeypatch):
    # After staging an Edit Light change, the row's light_region pre-fill
    # should reflect the pending spec (so re-opening the modal shows it).
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("set_light:" + _json.dumps({"i": 0, "shape": "Box"}))
    row = _payload_data(p.render_payload())["subsystems"][0]
    child = row["children"][0]
    assert child["light_region"]["shape"] == "Box"
    assert child["light_region"]["scale"] == [0.25, 0.25, 0.25]   # preserved


def _dark_descriptor(name):
    d = _rad_descriptor(name)
    d["light"] = False
    d["light_region"] = {"shape": "Sphere", "position": (1.0, 0.0, 0.0),
                         "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                         "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    return d


def test_add_light_stages_default_and_selects_it(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_dark_descriptor("Phaser Bank")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    assert p._has_light(0) is False
    assert p.dispatch_event("add_light:0") is True
    assert p._has_light(0) is True
    assert p._selected_light_index == 0
    assert p.selected_index is None                 # mutual exclusion
    assert p.pending_light_specs()["Phaser Bank"]["shape"] == "Sphere"


def test_add_light_rejected_when_already_lit(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])  # baked light
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    assert p._has_light(0) is True
    assert p.dispatch_event("add_light:0") is False


def test_remove_light_hides_node_and_clears_selection(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("select_light:0")
    assert p._selected_light_index == 0
    assert p.dispatch_event("remove_light:0") is True
    assert p._has_light(0) is False
    assert p._selected_light_index is None
    # Overlay must HIDE the baked region: name maps to None.
    assert "Center Impulse" in p.pending_light_specs()
    assert p.pending_light_specs()["Center Impulse"] is None


def test_select_pin_and_light_are_mutually_exclusive(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("select_pin:0")
    assert p.selected_index == 0 and p._selected_light_index is None
    assert p.selected_subsystem_sphere() is not None    # sphere while subsystem selected
    p.dispatch_event("select_light:0")
    assert p._selected_light_index == 0 and p.selected_index is None
    assert p.selected_subsystem_sphere() is None         # no sphere while light selected


def test_tree_has_light_child_and_add_flag(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    rows = p._subsystem_rows()
    row = rows[0]
    assert row["has_light"] is True
    kids = [c for c in row.get("children", []) if c.get("kind") == "light"]
    assert len(kids) == 1
    assert kids[0]["light_of"] == 0 and kids[0]["name"] == "Light Volume"


def test_pins_show_only_parent_when_light_selected(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("A"), _light_descriptor("B")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("select_light:1")
    pins = p.subsystem_pins()
    assert len(pins) == 1                    # only the parent of the selected light


def test_save_routes_removal_as_empty_region(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits): calls.append((leaf, edits))

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("remove_light:0")
    p.dispatch_event("save")
    assert calls == [("galaxy", [("Center Impulse", "__region__", 0, [])])]


def test_light_child_carries_region(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    child = _payload_data(p.render_payload())["subsystems"][0]["children"][0]
    assert child["kind"] == "light"
    assert child["light_region"]["shape"] == "Cylinder"


def test_light_child_reflects_pending_after_edit(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("set_light:" + _json.dumps(
        {"i": 0, "shape": "Box", "sx": 0.5, "sy": 0.6, "sz": 0.7}))
    child = _payload_data(p.render_payload())["subsystems"][0]["children"][0]
    assert child["light_region"]["shape"] == "Box"


def test_dark_subsystem_row_has_no_light_child(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_dark_descriptor("Phaser Bank")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    row = _payload_data(p.render_payload())["subsystems"][0]
    assert row["has_light"] is False
    assert [c for c in row.get("children", []) if c.get("kind") == "light"] == []


def test_add_light_rejected_on_descriptor_without_light_region(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    mount = {"name": "Shuttle Bay", "icon_id": 0, "world_pos": (0, 0, 0),
             "state": "mount", "kind": "mount", "targetable": False,
             "condition_pct": None, "parent_index": None,
             "properties": {"name": "Shuttle Bay"}}   # NO light_region key
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: [mount])
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert p.dispatch_event("add_light:0") is False
    assert p._has_light(0) is False
    assert 0 not in p._pending_light
