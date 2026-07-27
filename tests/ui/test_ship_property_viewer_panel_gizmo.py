"""SPV transform gizmo accessor + drag application (subsystem target)."""
import json
import pytest
from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from engine.ui.ship_property_viewer import OrbitCamera, project


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1: payload.rindex(")")])


class _Ship:
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()  # identity


def _panel():
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "icon_id": 1,
    }]
    return p


def test_no_gizmo_without_transform_tool():
    p = _panel()
    p.selected_index = 0
    assert p.transform_gizmo() is None       # tool is None
    p.dispatch_event("set_tool:transform")
    g = p.transform_gizmo()
    assert g is not None
    assert g["origin"] == pytest.approx((0.0, 1.0, 0.0))
    assert g["length"] > 0.0


def test_no_gizmo_without_selection():
    p = _panel()
    p.dispatch_event("set_tool:transform")
    assert p.transform_gizmo() is None       # nothing selected


def test_gizmo_origin_follows_pending_position():
    p = _panel()
    p.selected_index = 0
    p.dispatch_event("set_tool:transform")
    p.set_subsystem_position(0, (0.0, 4.0, 0.0))
    assert p.transform_gizmo()["origin"] == pytest.approx((0.0, 4.0, 0.0))


def test_apply_axis_drag_moves_only_that_component():
    p = _panel()
    p.selected_index = 0
    p.dispatch_event("set_tool:transform")
    # Simulate a grab on axis Y (1) then a move of +2.0 world units along it.
    p._begin_axis_drag_for_test(axis=1, grab_param=0.0)
    p._apply_axis_drag(2.0)   # param delta = 2.0 along +Y
    x, y, z = p._effective_pos(0)
    assert (x, z) == pytest.approx((0.0, 0.0))
    assert y == pytest.approx(3.0)   # baked 1.0 + 2.0


# ---------------------------------------------------------------------------
# handle_input-driven integration: real projection axis grab + drag, no orbit
# ---------------------------------------------------------------------------
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


def _panel_with_light():
    # Builds on _panel(): give the descriptor a baked light region.
    p = _panel()
    p._descriptors[0]["light"] = True
    p._descriptors[0]["light_region"] = {
        "shape": "Sphere", "position": (0.0, 1.0, 0.0), "axis": (0.0, -1.0, 0.0),
        "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    return p


def test_gizmo_targets_selected_light_node():
    p = _panel_with_light()
    p.dispatch_event("set_tool:transform")
    p._selected_light_index = 0     # light node selected (subsystem not)
    g = p.transform_gizmo()
    assert g is not None
    assert g["origin"] == pytest.approx((0.0, 1.0, 0.0))


def test_axis_drag_moves_light_position():
    p = _panel_with_light()
    p.dispatch_event("set_tool:transform")
    p._selected_light_index = 0
    p._begin_axis_drag_for_test(axis=0, grab_param=0.0)  # +X (starboard)
    p._apply_axis_drag(1.5)
    spec = p._effective_light(0)
    assert spec["position"] == pytest.approx((1.5, 1.0, 0.0))


def test_light_and_subsystem_selection_mutually_exclusive_for_gizmo():
    p = _panel_with_light()
    p.dispatch_event("set_tool:transform")
    p.selected_index = 0
    p._selected_light_index = None
    g = p.transform_gizmo()
    assert g is not None
    assert g["origin"] == pytest.approx((0.0, 1.0, 0.0))
    p._begin_axis_drag_for_test(axis=0, grab_param=0.0)
    p._apply_axis_drag(1.5)
    # Subsystem moved; light spec untouched (still baked default).
    x, y, z = p._effective_pos(0)
    assert x == pytest.approx(1.5)
    assert p._effective_light(0)["position"] == pytest.approx((0.0, 1.0, 0.0))


def test_handle_input_axis_drag_moves_subsystem_and_does_not_orbit():
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 20.0, 0.0, 0.0)
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "icon_id": 1,
    }]
    p.selected_index = 0
    p.dispatch_event("set_tool:transform")

    g = p.transform_gizmo()
    assert g is not None
    origin = g["origin"]
    ax = g["axes"][0]   # world +X shaft (identity rotation)
    length = g["length"]
    vp = (800, 600)

    def _px(frac):
        pt = (origin[0] + ax[0] * length * frac,
              origin[1] + ax[1] * length * frac,
              origin[2] + ax[2] * length * frac)
        sx, sy, _z, vis = project(pt, p.camera, vp)
        assert vis
        return (sx, sy)

    grab_px = _px(0.5)
    move_px = _px(0.9)

    yaw0 = p.camera.yaw
    h = _FakeHost()

    # Press exactly on the projected X shaft → grab axis 0.
    h._cursor = grab_px
    h._down = True
    p.handle_input(h)
    assert p._axis_drag == 0

    # Drag further along the projected shaft → subsystem moves along +X.
    h._cursor = move_px
    p.handle_input(h)

    # Release ends the drag (and picks no pin).
    h._down = False
    p.handle_input(h)
    assert p._axis_drag is None

    x, y, z = p._effective_pos(0)
    assert x > 0.1               # moved along +X
    assert y == pytest.approx(1.0)
    assert z == pytest.approx(0.0)
    assert p.camera.yaw == yaw0   # orbit suppressed during the axis drag


# ---------------------------------------------------------------------------
# Final-review fixes: edit-loss on Edit-Light after a gizmo drag, and the
# popover position readout following a staged/dragged subsystem position.
# ---------------------------------------------------------------------------
def test_edit_light_shape_preserves_dragged_position():
    p = _panel_with_light()
    p.dispatch_event("set_tool:transform")
    p._selected_light_index = 0
    p._begin_axis_drag_for_test(axis=0, grab_param=0.0)  # +X (starboard)
    p._apply_axis_drag(1.5)
    # Sanity: drag staged before the Edit-Light dispatch.
    assert p._effective_light(0)["position"] == pytest.approx((1.5, 1.0, 0.0))

    p.dispatch_event("set_light:" + json.dumps({"i": 0, "shape": "Sphere", "radius": 0.4}))

    spec = p._effective_light(0)
    assert spec["position"] == pytest.approx((1.5, 1.0, 0.0))  # dragged X survived
    assert spec["radius"] == pytest.approx((0.4,))


def test_popover_position_follows_pending_drag():
    p = _panel()
    p.selected_index = 0
    p.set_subsystem_position(0, (2.0, 1.0, 0.0))

    data = _payload_data(p.render_payload())
    assert data["selected"]["properties"]["position"] == [2.0, 1.0, 0.0]
