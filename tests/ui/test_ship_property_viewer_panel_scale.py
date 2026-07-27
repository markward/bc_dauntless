"""SPV scale tool: scale_values() + scale_* dispatch (shape-aware)."""
import json
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
