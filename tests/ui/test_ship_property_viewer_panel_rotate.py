"""SPV rotate tool: rotate_values() + rotate_* dispatch (cylinder axis only)."""
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


def test_rotate_values_none_for_box_light():
    p = _panel_light(shape="Box")
    assert p.rotate_values() is None       # rotate is cylinder-only


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
