"""SPV light-emitter child nodes: data model, dispatch, tree, selection.

Mirrors test_ship_property_viewer_panel_light_modal.py's fixture/dispatch
pattern but for the (subsystem_index, emitter_index)-keyed emitter API.
"""
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

_DEFAULT_LIGHT_REGION = {
    "shape": "Sphere", "position": (0.0, 0.0, 0.0),
    "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
    "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
    "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}


def _panel_with_subsystem(emitters=None):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
        "emitters": list(emitters or []),
    }]
    return p


def _emitter_spec(kind="point"):
    return {
        "kind": kind,
        "position": (0.0, 0.0, 0.0),
        "axis": (0.0, -1.0, 0.0),
        "length": 2.0,
        "radius": 1.0,
        "color": (1.0, 0.9, 0.7),
        "intensity": 2.0,
    }


def test_add_emitter_stages_point_and_selects():
    p = _panel_with_subsystem()
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({"i": 0, "kind": "point"})) is True
    specs = p._effective_emitters(0)
    assert len(specs) == 1
    assert specs[0]["kind"] == "point"
    assert p._selected_emitter == (0, 0)
    assert p.selected_index is None
    assert p._selected_light_index is None


def test_second_add_emitter_appends_and_selects_next_index():
    p = _panel_with_subsystem()
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({"i": 0, "kind": "point"})) is True
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({"i": 0, "kind": "cone"})) is True
    specs = p._effective_emitters(0)
    assert len(specs) == 2
    assert specs[0]["kind"] == "point"
    assert specs[1]["kind"] == "cone"
    assert p._selected_emitter == (0, 1)


def test_set_emitter_updates_kind_color_intensity_preserves_geometry():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    assert p.dispatch_event('set_emitter:' + json.dumps({
        "i": 0, "j": 0, "kind": "cone",
        "color": [1.0, 0.0, 0.0], "intensity": 3.0,
    })) is True
    spec = p._effective_emitter(0, 0)
    assert spec["kind"] == "cone"
    assert spec["color"] == (1.0, 0.0, 0.0)
    assert spec["intensity"] == 3.0
    # geometry preserved from the baked spec
    assert spec["position"] == (0.0, 0.0, 0.0)
    assert spec["axis"] == (0.0, -1.0, 0.0)
    assert spec["length"] == 2.0
    assert spec["radius"] == 1.0


def test_set_emitter_rejects_unknown_kind():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    assert p.dispatch_event('set_emitter:' + json.dumps({
        "i": 0, "j": 0, "kind": "blob",
    })) is False


def test_set_emitter_missing_target_returns_false():
    p = _panel_with_subsystem()
    assert p.dispatch_event('set_emitter:' + json.dumps({
        "i": 0, "j": 0, "kind": "cone",
    })) is False


def test_remove_emitter_drops_it_and_clears_selection():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    assert p._selected_emitter == (0, 0)
    assert p.dispatch_event(
        'remove_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    assert p._effective_emitters(0) == []
    assert p._selected_emitter is None


def test_remove_then_add_does_not_clobber_a_surviving_emitter():
    """Regression for the whole-list staging model: add point, add cone,
    remove the point (index 0) so the cone compacts down to index 0, then
    add a strip. All three emitters must survive with dense indices — a
    stale (i,j)-keyed staging dict would clobber the compacted cone because
    the next add computed its new index from the pre-removal length."""
    p = _panel_with_subsystem()
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({"i": 0, "kind": "point"})) is True
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({"i": 0, "kind": "cone"})) is True
    assert p.dispatch_event(
        'remove_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    specs = p._effective_emitters(0)
    assert [s["kind"] for s in specs] == ["cone"]
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({"i": 0, "kind": "strip"})) is True
    specs = p._effective_emitters(0)
    assert [s["kind"] for s in specs] == ["cone", "strip"]
    assert p._selected_emitter == (0, 1)


def test_select_emitter_with_each_gizmo_tool_does_not_crash():
    """Regression: _active_transform_target() returns a 3-tuple for an
    emitter target; every pre-existing consumer that unpacks it as
    `kind, i = t` must guard the emitter case instead of crashing (gizmo
    ROUTING for emitters is Task 7 — this only asserts "no crash, no
    gizmo")."""
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    for tool in ("transform", "scale", "rotate"):
        assert p.dispatch_event('set_tool:' + tool) is True
        assert p.active_tool == tool
        # Reported crash sites: transform_gizmo/scale_gizmo/_rotate_target
        # (via rotate_gizmo), plus the coord/scale/rotate value readouts
        # that render_payload() exercises every frame.
        assert p.transform_gizmo() is None
        assert p.scale_gizmo() is None
        assert p.rotate_gizmo() is None
        assert p.transform_coords() is None
        assert p.scale_values() is None
        assert p.rotate_values() is None
        js = p.render_payload()
        assert js is None or isinstance(js, str)
    # Reported crash sites in the drag-begin/apply helpers (host input path,
    # but plain-Python callable without a host).
    p.active_tool = "transform"
    p._begin_axis_drag(0, 0.0)
    p._apply_axis_drag(1.0)
    p.active_tool = "scale"
    p._begin_scale_drag(0, 0.0)
    p._apply_scale_drag(1.0)


def test_scale_copy_with_emitter_selected_does_not_clobber_clipboard():
    """Regression: scale_copy read _scale_kind_and_fields's inert emitter
    placeholder ("radius", [0.0]) as real data and silently overwrote
    _scale_clipboard. A real subsystem scale value copied to the clipboard
    must survive selecting an emitter and pressing scale_copy again, and a
    subsequent scale_paste onto the original target must restore the real
    value — not SCALE_MIN from a clobbered placeholder."""
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    assert p.dispatch_event("select_pin:0") is True
    assert p.dispatch_event("set_tool:scale") is True
    assert p.dispatch_event("scale_copy") is True
    assert p._scale_clipboard == ("radius", (0.3,))

    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    assert p.dispatch_event("scale_copy") is True
    assert p._scale_clipboard == ("radius", (0.3,))   # NOT clobbered to 0.0

    assert p.dispatch_event("select_pin:0") is True
    assert p.dispatch_event("scale_paste") is True
    assert p._pending_radius[0] == 0.3                # NOT SCALE_MIN (0.01)


def test_select_emitter_clears_subsystem_and_light_selection():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    p.selected_index = 0
    p._selected_light_index = 0
    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    assert p._selected_emitter == (0, 0)
    assert p.selected_index is None
    assert p._selected_light_index is None


def test_select_emitter_missing_returns_false():
    p = _panel_with_subsystem()
    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": 0, "j": 0})) is False


def test_subsystem_rows_emit_emitter_child_row_per_emitter():
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("point"), _emitter_spec("cone")])
    rows = p._subsystem_rows()
    assert len(rows) == 1
    emitter_children = [c for c in rows[0]["children"] if c["kind"] == "emitter"]
    assert len(emitter_children) == 2
    assert emitter_children[0]["name"] == "Light Emitter"
    assert emitter_children[0]["emitter_of"] == 0
    assert emitter_children[0]["emitter_index"] == 0
    assert emitter_children[0]["emitter_kind"] == "point"
    assert emitter_children[1]["emitter_index"] == 1
    assert emitter_children[1]["emitter_kind"] == "cone"


def test_render_payload_carries_selected_emitter():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    js = p.render_payload()
    assert js is not None
    assert '"selected_emitter": [0, 0]' in js

    assert p.dispatch_event('remove_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    js2 = p.render_payload()
    assert js2 is not None
    assert '"selected_emitter": null' in js2


def test_active_transform_target_prefers_emitter_over_subsystem_and_light():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    p.selected_index = 0
    p._selected_light_index = 0
    p._selected_emitter = (0, 0)
    assert p._active_transform_target() == ("emitter", 0, 0)
