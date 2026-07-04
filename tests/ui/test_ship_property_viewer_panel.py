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
    data = _payload_data(p.render_payload())
    assert data["show_glow"] is False
    assert data["show_arcs"] is False


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
    # Toggling back off flips + re-pushes again.
    assert p.dispatch_event("toggle_glow_regions") is True
    assert _payload_data(p.render_payload())["show_glow"] is False


def test_toggles_reset_on_reopen_and_close():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open()
    p.dispatch_event("toggle_glow_regions")
    p.dispatch_event("toggle_weapon_arcs")
    p.close()
    assert p.show_glow_regions is False
    assert p.show_weapon_arcs is False
    p.open()
    assert p.show_glow_regions is False
    assert p.show_weapon_arcs is False


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


def _open_panel_for_input():
    from engine.ui.ship_property_viewer import OrbitCamera as _Cam
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open()
    p.camera = _Cam(target=(0, 0, 0), distance=100.0)
    return p
