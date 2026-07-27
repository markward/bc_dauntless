"""SPV scale tool: scale_values() + scale_* dispatch (shape-aware)."""
import json

import pytest

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1:payload.rindex(")")])


def _panel_subsystem(radius=0.3):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": radius},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
    }]
    p.dispatch_event("set_tool:scale")
    p.selected_index = 0
    return p


def _panel_light(shape, **spec):
    base = {"shape": shape, "position": (0.0, 1.0, 0.0), "axis": (0.0, -1.0, 0.0),
            "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    base.update(spec)
    p = _panel_subsystem()
    p._descriptors[0]["light"] = True
    p._descriptors[0]["light_region"] = base
    p.selected_index = None
    p._selected_light_index = 0
    return p


def test_scale_values_none_off_tool():
    p = _panel_subsystem()
    p.dispatch_event("set_tool:scale")   # toggle OFF
    assert p.scale_values() is None


def test_subsystem_scale_is_radius():
    p = _panel_subsystem(0.3)
    v = p.scale_values()
    assert v["kind"] == "radius"
    assert [f["label"] for f in v["fields"]] == ["Radius"]
    assert v["fields"][0]["value"] == 0.3


def test_box_scale_is_xyz():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    v = p.scale_values()
    assert v["kind"] == "xyz"
    assert [f["value"] for f in v["fields"]] == [0.15, 0.2, 0.05]


def test_cylinder_scale_is_radius_length():
    p = _panel_light("Cylinder", radius=(0.3,), extent=(0.0, 2.0))
    v = p.scale_values()
    assert v["kind"] == "radius_length"
    assert [f["label"] for f in v["fields"]] == ["Radius", "Length"]
    assert v["fields"][1]["value"] == 2.0   # fore - aft


def test_scale_nudge_moves_only_that_field_and_floors():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    p.dispatch_event('scale_nudge:' + json.dumps({"index": 1, "delta": 0.1}))
    assert round(p.scale_values()["fields"][1]["value"], 6) == 0.3
    # Floor: nudging the tiny Z far negative clamps at SCALE_MIN, not <= 0.
    p.dispatch_event('scale_nudge:' + json.dumps({"index": 2, "delta": -5.0}))
    from engine.ui.ship_property_viewer_panel import SCALE_MIN
    assert p.scale_values()["fields"][2]["value"] == SCALE_MIN


def test_scale_copy_paste_kind_matched():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    p.dispatch_event("scale_copy")
    v = p.scale_values()
    assert v["has_clipboard"] is True and v["can_paste"] is True
    p.dispatch_event('scale_nudge:' + json.dumps({"index": 0, "delta": 0.5}))
    p.dispatch_event("scale_paste")
    assert [f["value"] for f in p.scale_values()["fields"]] == [0.15, 0.2, 0.05]


def test_scale_paste_disabled_across_kinds():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    p.dispatch_event("scale_copy")           # clipboard kind = xyz
    q = _panel_light("Sphere", radius=(0.4,))
    q._scale_clipboard = p._scale_clipboard  # simulate shared clipboard
    v = q.scale_values()
    assert v["has_clipboard"] is True and v["can_paste"] is False


def test_scale_uniform_sets_box_axes_to_max():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    p.dispatch_event("scale_uniform")
    assert [f["value"] for f in p.scale_values()["fields"]] == [0.2, 0.2, 0.2]


def test_scale_uniform_noop_on_sphere():
    p = _panel_light("Sphere", radius=(0.4,))
    assert p.dispatch_event("scale_uniform") is True
    assert p.scale_values()["fields"][0]["value"] == 0.4


def test_render_payload_carries_scale_values():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    data = _payload_data(p.render_payload())
    assert data["scale_values"]["kind"] == "xyz"


# ── Scale gizmo + multiplicative drag + click-guard ─────────────────────────

from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui.ship_property_viewer import OrbitCamera


class _Ship:
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()


def _panel_box_gizmo():
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None,
        "light": True,
        "light_region": {"shape": "Box", "position": (0.0, 0.0, 0.0),
                         "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                         "extent": (0.0, 2.0), "scale": (0.2, 0.2, 0.2)},
    }]
    p.dispatch_event("set_tool:scale")
    p._selected_light_index = 0
    return p


def test_scale_gizmo_gate_and_handle_kind():
    p = _panel_box_gizmo()
    g = p.scale_gizmo()
    assert g is not None and g["handle_kind"] == 1
    assert p.transform_gizmo() is None          # wrong tool
    assert p._active_gizmo() is g or p._active_gizmo()["handle_kind"] == 1


def test_transform_gizmo_handle_kind_zero():
    p = _panel_box_gizmo()
    p.dispatch_event("set_tool:transform")
    assert p.transform_gizmo()["handle_kind"] == 0


def test_scale_drag_multiplies_box_axis():
    p = _panel_box_gizmo()
    # Grab X (axis 0) with grab param = length, then drag to 1.5x that param.
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(0, L)
    p._apply_scale_drag(1.5 * L)
    assert round(p.scale_values()["fields"][0]["value"], 6) == 0.3   # 0.2 * 1.5
    assert round(p.scale_values()["fields"][1]["value"], 6) == 0.2   # Y unchanged


def test_scale_drag_uniform_radius_on_sphere():
    p = _panel_box_gizmo()
    p._descriptors[0]["light_region"] = {"shape": "Sphere", "position": (0, 0, 0),
        "axis": (0, -1, 0), "radius": (0.4,), "extent": (0, 2), "scale": (0.25, 0.25, 0.25)}
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(2, L)          # any axis -> radius
    p._apply_scale_drag(2.0 * L)
    assert round(p.scale_values()["fields"][0]["value"], 6) == 0.8   # 0.4 * 2


# ── Click-guard fires for the scale panel too ───────────────────────────────

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


def _scale_panel_selected():
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
    }]
    p.dispatch_event("set_tool:scale")
    p.selected_index = 0
    return p


def test_scale_region_guarded_when_panel_visible():
    p = _scale_panel_selected()
    assert p.scale_values() is not None
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 20.0, 0.0, 0.0)
    yaw0 = p.camera.yaw
    h = _Host()
    # (700, 100) is inside the top-right box for an 800x600 dsf=1 viewport.
    h._cursor = (700.0, 100.0); h._down = True
    p.handle_input(h)              # press
    h._cursor = (730.0, 100.0)
    p.handle_input(h)              # drag right
    assert p.camera.yaw == yaw0    # guarded -> no orbit while the scale panel is up


# ── Cylinder: axial handle scales Length, radial handles scale Radius ────────

def _panel_cylinder_gizmo(axis=(0.0, -1.0, 0.0)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._descriptors = [{
        "name": "Port Warp", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None,
        "light": True,
        "light_region": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                         "axis": axis, "radius": (0.3,),
                         "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)},
    }]
    p.dispatch_event("set_tool:scale")
    p._selected_light_index = 0
    return p


def test_cylinder_axial_handle_scales_length():
    # Cylinder axis = body -Y -> aligns with gizmo axis 1 (Y). Grabbing that
    # handle must scale Length (field 1), not Radius.
    p = _panel_cylinder_gizmo(axis=(0.0, -1.0, 0.0))
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(1, L)
    p._apply_scale_drag(1.5 * L)
    v = p.scale_values()["fields"]
    assert round(v[1]["value"], 6) == 3.0    # Length 2.0 * 1.5
    assert round(v[0]["value"], 6) == 0.3    # Radius unchanged


def test_cylinder_radial_handle_scales_radius():
    # A handle perpendicular to the cylinder axis (X here) scales Radius.
    p = _panel_cylinder_gizmo(axis=(0.0, -1.0, 0.0))
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(0, L)
    p._apply_scale_drag(2.0 * L)
    v = p.scale_values()["fields"]
    assert round(v[0]["value"], 6) == 0.6    # Radius 0.3 * 2
    assert round(v[1]["value"], 6) == 2.0    # Length unchanged


def test_cylinder_axis_along_z_maps_z_handle_to_length():
    # Axis orientation drives the mapping: axis = +Z -> gizmo axis 2 = Length.
    p = _panel_cylinder_gizmo(axis=(0.0, 0.0, 1.0))
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(2, L)                # Z handle now the axial one
    p._apply_scale_drag(1.5 * L)
    assert round(p.scale_values()["fields"][1]["value"], 6) == 3.0


def test_cylinder_length_scales_about_anchor_not_end():
    # Cylinder extent (-2, 2): pos (offset 0) is the anchor the widget sits on.
    # Scaling Length must keep pos fixed and grow both ends about it, NOT hold
    # the aft end fixed and grow only the fore end.
    p = _panel_cylinder_gizmo(axis=(0.0, -1.0, 0.0))
    p._descriptors[0]["light_region"]["extent"] = (-2.0, 2.0)   # pos-centered, len 4
    p.dispatch_event('scale_nudge:' + json.dumps({"index": 1, "delta": 2.0}))  # len 4 -> 6
    ext = p._effective_light(0)["extent"]
    assert ext == pytest.approx((-3.0, 3.0))    # scaled about pos, not (-2.0, 4.0)


def test_cylinder_length_drag_stays_anchored():
    # A multiplicative drag likewise scales the extent about pos.
    p = _panel_cylinder_gizmo(axis=(0.0, -1.0, 0.0))
    p._descriptors[0]["light_region"]["extent"] = (-2.0, 2.0)   # len 4
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(1, L)          # axial handle -> Length
    p._apply_scale_drag(1.5 * L)        # ratio 1.5 -> len 6
    ext = p._effective_light(0)["extent"]
    assert ext == pytest.approx((-3.0, 3.0))
