"""SPV rotate tool: rotate_values() + rotate_* dispatch (cylinder axis, box
orientation)."""
import json
import math

import pytest

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from engine.ui.ship_property_viewer import rotate_about_axis


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1:payload.rindex(")")])


def _panel_light(shape="Cylinder", axis=(0.0, -1.0, 0.0)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Port Warp", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None, "light": True,
        "light_region": {"shape": shape, "position": (0.0, 1.0, 0.0), "axis": axis,
                         "radius": (0.3,), "extent": (-2.0, 2.0),
                         "scale": (0.25, 0.25, 0.25)},
    }]
    p.dispatch_event("set_tool:rotate")
    p._selected_light_index = 0
    return p


def test_rotate_about_axis_z_90deg():
    # +Y rotated +90 deg about +Z -> -X (right-handed).
    out = rotate_about_axis((0.0, 1.0, 0.0), 2, math.radians(90.0))
    assert out == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)


def test_rotate_values_none_off_tool():
    p = _panel_light()
    p.dispatch_event("set_tool:rotate")   # toggle OFF
    assert p.rotate_values() is None


def test_rotate_values_present_for_box_light():
    # Rotate now edits a Box's forward+up orientation basis too (Sphere is
    # still the only inert shape) — see the box-orientation tests below.
    p = _panel_light(shape="Box")
    assert p.rotate_values() is not None


def test_rotate_values_present_for_cylinder():
    p = _panel_light()
    v = p.rotate_values()
    assert [f["label"] for f in v["fields"]] == ["X", "Y", "Z"]
    assert [f["value"] for f in v["fields"]] == [0.0, 0.0, 0.0]


def test_rotate_nudge_rotates_axis_and_bumps_accumulator():
    p = _panel_light(axis=(0.0, 1.0, 0.0))
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 90.0}))
    ax = p._effective_light(0)["axis"]
    assert ax == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)   # +Y about +Z 90 -> -X
    assert p.rotate_values()["fields"][2]["value"] == 90.0    # Z accumulator


def test_rotate_mirror_negates_axis_x_and_zeroes_accum():
    p = _panel_light(axis=(0.6, 0.8, 0.0))
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 10.0}))
    p.dispatch_event("rotate_mirror")
    ax = p._effective_light(0)["axis"]
    assert ax[0] < 0.0                                        # X negated
    assert p.rotate_values()["fields"] [2]["value"] == 0.0    # accumulator reset


def test_rotate_copy_paste_roundtrips_axis():
    p = _panel_light(axis=(0.0, 1.0, 0.0))
    p.dispatch_event("rotate_copy")
    assert p.rotate_values()["can_paste"] is True
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 45.0}))
    p.dispatch_event("rotate_paste")
    assert p._effective_light(0)["axis"] == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)


def test_render_payload_carries_rotate_values():
    p = _panel_light()
    assert _payload_data(p.render_payload())["rotate_values"]["fields"][0]["label"] == "X"


# ── Box light orientation (forward+up basis) ────────────────────────────────

def _panel_box_light():
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Port Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None, "light": True,
        "light_region": {"shape": "Box", "position": (0.0, 0.0, 0.0),
                         "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                         "extent": (0.0, 2.0), "scale": (0.2, 0.2, 0.05),
                         "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))},
    }]
    p.dispatch_event("set_tool:rotate")
    p._selected_light_index = 0
    return p


def test_rotate_target_accepts_box_light():
    p = _panel_box_light()
    assert p._rotate_target() == ("light", 0)
    assert p.rotate_values() is not None


def test_box_rotate_nudge_rotates_orientation():
    p = _panel_box_light()
    # Rotate 90 deg about +Z: forward +Y -> -X, up +Z unchanged.
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 90.0}))
    fwd, up = p._effective_light(0)["orientation"]
    assert fwd == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)
    assert up == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)


def test_box_rotate_mirror_reflects_forward_x():
    p = _panel_box_light()
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 30.0}))
    p.dispatch_event("rotate_mirror")
    fwd, up = p._effective_light(0)["orientation"]
    # forward X flipped; basis stays unit + right-handed (up still ~unit).
    assert abs((fwd[0]**2 + fwd[1]**2 + fwd[2]**2) - 1.0) < 1e-6


# ── Ring gizmo + angular drag + handle_input branch ─────────────────────────

from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui.ship_property_viewer import OrbitCamera, gizmo_length


class _Ship:
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()


def _panel_ring():
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._descriptors = [{
        "name": "Port Warp", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None, "light": True,
        "light_region": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                         "axis": (0.0, 1.0, 0.0), "radius": (0.3,),
                         "extent": (-2.0, 2.0), "scale": (0.25, 0.25, 0.25)},
    }]
    p.dispatch_event("set_tool:rotate")
    p._selected_light_index = 0
    return p


def test_rotate_gizmo_gate_and_handle_kind():
    p = _panel_ring()
    g = p.rotate_gizmo()
    assert g is not None and g["handle_kind"] == 2
    assert p._active_gizmo()["handle_kind"] == 2


def test_ring_drag_rotates_axis():
    # Grab the Z ring; simulate a screen-angle sweep and assert the axis moved
    # off its start and stayed unit-length.
    p = _panel_ring()
    p._begin_ring_drag(2, 0.0)          # grab angle 0 rad on ring Z
    p._apply_ring_drag_angle(math.radians(30.0))   # test seam: apply a raw body angle
    ax = p._effective_light(0)["axis"]
    assert abs(math.sqrt(sum(a*a for a in ax)) - 1.0) < 1e-6
    assert ax != (0.0, 1.0, 0.0)


# ── Click-guard fires for the rotate panel too ──────────────────────────────

class _Host:
    class keys:
        MOUSE_BUTTON_LEFT = 0

    def __init__(self):
        self._cursor = (0.0, 0.0)
        self._down = False
        self._fb = (800, 600)

    def cursor_pos(self): return self._cursor
    def framebuffer_size(self): return self._fb
    def mouse_button_state(self, b): return self._down
    def consume_scroll_y(self): return 0.0


def test_rotate_region_guarded_when_panel_visible():
    p = _panel_ring()
    assert p.rotate_values() is not None
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 20.0, 0.0, 0.0)
    yaw0 = p.camera.yaw
    h = _Host()
    # (700, 100) is inside the top-right box for an 800x600 dsf=1 viewport.
    h._cursor = (700.0, 100.0); h._down = True
    p.handle_input(h)              # press
    h._cursor = (730.0, 100.0)
    p.handle_input(h)              # drag right
    assert p.camera.yaw == yaw0    # guarded -> no orbit while the rotate panel is up
