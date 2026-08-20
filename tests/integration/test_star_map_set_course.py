"""Helm -> Set Course opens the star map, and picking a warp point reaches
the same on_course_set contract SettingCoursePanel satisfied.

Entered at the HOST layer — engine.host_loop's seams and the PanelRegistry
dispatch the CEF event handler actually uses — not at the panel's own API.
The map drawing is driven through the engine.host_io façade, so the tests
install a recording stand-in for the native module (host_io._h) and read the
calls the real wrappers make.
"""
import json

import pytest

from engine import host_io
from engine.ui import star_map
from engine.ui.panel_registry import PanelRegistry
from engine.ui.star_map_panel import MAP_RECT, StarMapPanel


def _payload(js):
    assert js.startswith("setStarMapPanel(") and js.endswith(");")
    return json.loads(js[len("setStarMapPanel("):-2])


class _RecordingHost:
    """Stand-in for the _dauntless_host module — records the four starmap
    bindings the host_io wrappers call."""

    def __init__(self):
        self.enabled = []
        self.viewport = []
        self.camera = []
        self.scene = []

    def starmap_set_enabled(self, enabled):
        self.enabled.append(enabled)

    def starmap_set_viewport(self, x, y, w, h):
        self.viewport.append((x, y, w, h))

    def starmap_set_camera(self, eye, target, up, fov_y_rad, near, far):
        self.camera.append((eye, target, up, fov_y_rad, near, far))

    def starmap_set_scene(self, discs, lines, points, brackets):
        self.scene.append((discs, lines, points, brackets))


@pytest.fixture
def rec(monkeypatch):
    host = _RecordingHost()
    monkeypatch.setattr(host_io, "_h", host)
    return host


# --- the contract the swap must preserve ---------------------------------

def test_selection_reaches_the_course_set_callback_through_the_registry():
    """The whole point of the swap: routed through PanelRegistry (the single
    CEF event handler), the map satisfies the SAME contract the list panel
    did, so the warp button, Kiska's ack and the spine are untouched."""
    recorded = []
    registry = PanelRegistry()
    panel = StarMapPanel(on_course_set=recorded.append)
    registry.register(panel)

    # what host_loop's on_set_course hook does
    panel.open(course_menu=None, set_name="Vesuvi6")
    assert panel.is_open()

    assert registry.dispatch("star-map/select-system:vesuvi") is True
    data = _payload(registry.render_all()[0])
    wp = next(w for w in data["warp_points"] if w["available"])

    assert registry.dispatch("star-map/set-course:" + wp["id"]) is True
    assert len(recorded) == 1
    assert recorded[0].startswith("Systems.")
    assert not panel.is_open()


# --- driving the native pass ---------------------------------------------

def test_drive_star_map_pushes_viewport_camera_and_scene(rec):
    from engine.host_loop import _drive_star_map

    panel = StarMapPanel()
    panel.open(set_name="Vesuvi6")
    _drive_star_map(panel, (1280, 720), 720)

    assert rec.enabled == [True]
    assert len(rec.camera) == 1
    eye, target, up, fov_y_rad, near, far = rec.camera[0]
    cam = panel.cam.camera
    assert eye == cam.eye()
    assert target == panel.cam.anchor      # anchored on the player's system
    assert up == cam.up()
    assert (fov_y_rad, near, far) == (cam.fov_y_rad, cam.near, cam.far)
    assert len(rec.scene) == 1


def test_drive_star_map_flips_y_into_gl_viewport_space(rec):
    """MAP_RECT is CEF logical pixels, origin TOP-left; the GL viewport is
    origin BOTTOM-left. Without the flip the map draws mirrored up the
    screen."""
    from engine.host_loop import _drive_star_map

    panel = StarMapPanel()
    panel.open(set_name="Vesuvi6")
    rx, ry, rw, rh = MAP_RECT
    assert (rx, ry, rw, rh) == (200, 108, 640, 520)

    _drive_star_map(panel, (1280, 720), 720)          # 1:1 framebuffer
    assert rec.viewport == [(200, 720 - (108 + 520), 640, 520)]

    _drive_star_map(panel, (2560, 1440), 720)         # Retina: scale 2
    assert rec.viewport[1] == (400, 1440 - (108 + 520) * 2, 1280, 1040)


def test_drive_star_map_disables_the_pass_when_the_map_is_closed(rec):
    from engine.host_loop import _drive_star_map

    panel = StarMapPanel()                            # never opened
    _drive_star_map(panel, (1280, 720), 720)

    assert rec.enabled == [False]
    assert rec.viewport == [] and rec.camera == [] and rec.scene == []


def test_scene_buffers_match_the_binding_tuple_shapes(rec):
    """discs ((x,y,z),(r,g,b),radius,opacity) / lines ((a),(b),(rgb)) /
    points ((x,y,z),(r,g,b),size_px,selected) / brackets ((x,y,z),mark,
    (r,g,b),size_px) — exactly what host_bindings.cc unpacks."""
    from engine.host_loop import _drive_star_map

    panel = StarMapPanel()
    panel.open(set_name="Vesuvi6")
    panel.dispatch_event("select-system:vesuvi")
    _drive_star_map(panel, (1280, 720), 720)

    discs, lines, points, brackets = rec.scene[0]
    scene = panel.scene
    assert len(discs) == len(scene["discs"])
    assert len(lines) == len(scene["lines"])
    assert len(points) == len(scene["points"])
    assert len(brackets) == len(scene["brackets"])
    assert points and brackets and lines and discs

    for pos, color, radius, opacity in discs:
        assert len(pos) == 3 and len(color) == 3
        assert isinstance(radius, float) and isinstance(opacity, float)
    for a, b, color in lines:
        assert len(a) == 3 and len(b) == 3 and len(color) == 3
    for pos, color, size_px, selected in points:
        assert len(pos) == 3 and len(color) == 3
        assert isinstance(size_px, float) and isinstance(selected, bool)
    for pos, mark, color, size_px in brackets:
        assert len(pos) == 3 and len(color) == 3
        assert isinstance(mark, int) and isinstance(size_px, float)

    # size_px arrives already selection-scaled by build_scene; the pass must
    # not scale it again, so it must equal the module's constant exactly.
    selected = [p for p in points if p[3]]
    assert len(selected) == 1
    assert selected[0][2] == star_map.STAR_SELECTED_SIZE_PX

    # The reticle for "you are here" rides along with its own colour.
    here = [b for b in brackets if b[1] == star_map.MARK_HERE]
    assert len(here) == 1
    assert here[0][2] == star_map.MARK_HERE_COLOR


# --- the anchor the Helm hook feeds the map -------------------------------

def test_player_set_name_resolves_the_anchor_set():
    """host_loop's Set Course hook anchors the map on the player's set."""
    from engine.appc.sets import SetClass
    from engine.appc.ships import ShipClass_Create
    from engine.host_loop import _player_set_name

    pSet = SetClass()
    pSet.SetName("Vesuvi6")
    ship = ShipClass_Create("TestPlayer")
    pSet.AddObjectToSet(ship, "TestPlayer")

    assert _player_set_name(ship) == "Vesuvi6"
    # The map anchors on the SYSTEM that set belongs to.
    assert star_map.resolve_anchor(_player_set_name(ship))[0] == "vesuvi"


@pytest.mark.parametrize("player", [None, object()])
def test_player_set_name_is_none_when_unresolvable(player):
    """No player / no set / a broken handle must degrade to None, not raise:
    resolve_anchor then centres on the sector and draws no "here" reticle."""
    from engine.host_loop import _player_set_name

    assert _player_set_name(player) is None
    assert star_map.resolve_anchor(None)[0] is None


# --- cursor + ESC wiring --------------------------------------------------

class _RecordingRenderer:
    def __init__(self):
        self.cursor_lock_calls = []

    def set_cursor_locked(self, locked):
        self.cursor_lock_calls.append(locked)

    def bridge_pass_set_enabled(self, enabled):
        pass


class _FakeCrewMenu:
    def __init__(self, open_=False):
        self._open = open_

    def has_open_menu(self):
        return self._open

    def close_open_menu(self):
        self._open = False


def test_open_star_map_frees_the_cursor():
    """The map is a centred CEF modal opened from the Helm crew menu, which
    closes as it opens — so the cursor must be freed off the MAP's state,
    exactly as the Set Course list modal's was."""
    from engine.host_loop import (_apply_crew_menu_side_effects,
                                  _PauseMenuController, _ViewModeController)

    vm = _ViewModeController()
    vm._last_synced_is_bridge = True
    h, pause = _RecordingRenderer(), _PauseMenuController()
    panel = StarMapPanel()
    panel.open(set_name="Vesuvi6")

    _apply_crew_menu_side_effects(_FakeCrewMenu(False), vm, pause, h,
                                  star_map_panel=panel)
    assert h.cursor_lock_calls == [False]


def test_esc_through_the_modal_dispatcher_closes_the_map():
    """StarMapPanel must satisfy the modal-blocker protocol the host loop's
    ESC ladder uses (is_open/handle_key_esc), or ESC never closes the map."""
    from engine.host_loop import _dispatch_modal_esc, _PauseMenuController

    class _Keys:
        KEY_ESCAPE = 256

    class _Host:
        keys = _Keys()

        def key_pressed(self, key):
            return key == _Keys.KEY_ESCAPE

    panel = StarMapPanel()
    panel.open(set_name="Vesuvi6")
    _dispatch_modal_esc([panel], _FakeCrewMenu(False),
                        _PauseMenuController(), _Host())
    assert panel.is_open() is False
