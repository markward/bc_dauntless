"""SPV light-emitter child nodes: data model, dispatch, tree, selection.

Mirrors test_ship_property_viewer_panel_light_modal.py's fixture/dispatch
pattern but for the (subsystem_index, emitter_index)-keyed emitter API.
"""
import json
import math
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


def test_add_emitter_seeds_color_and_intensity_when_provided():
    p = _panel_with_subsystem()
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({
            "i": 0, "kind": "cone",
            "color": [0.2, 0.4, 0.9], "intensity": 5.5,
        })) is True
    spec = p._effective_emitter(0, 0)
    assert spec["kind"] == "cone"
    assert spec["color"] == (0.2, 0.4, 0.9)
    assert spec["intensity"] == 5.5


def test_add_emitter_without_color_or_intensity_keeps_defaults():
    p = _panel_with_subsystem()
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({"i": 0, "kind": "point"})) is True
    from engine.appc.light_emitters import default_emitter_spec
    default = default_emitter_spec("point")
    spec = p._effective_emitter(0, 0)
    assert spec["color"] == default["color"]
    assert spec["intensity"] == default["intensity"]


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
    emitter target; every consumer that unpacks it as `kind, i = t` must
    guard the emitter case instead of crashing. The 3D gizmos stay None
    (no camera in this fixture); the value readouts return a dict or None
    without crashing (Task 10 makes them render for emitters)."""
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    for tool in ("transform", "scale", "rotate"):
        assert p.dispatch_event('set_tool:' + tool) is True
        assert p.active_tool == tool
        # No camera in this fixture, so the 3D gizmos stay None regardless.
        assert p.transform_gizmo() is None
        assert p.scale_gizmo() is None
        assert p.rotate_gizmo() is None
        # Value readouts must not crash on the emitter 3-tuple.
        assert p.transform_coords() is None or isinstance(p.transform_coords(), dict)
        assert p.scale_values() is None or isinstance(p.scale_values(), dict)
        assert p.rotate_values() is None or isinstance(p.rotate_values(), dict)
        js = p.render_payload()
        assert js is None or isinstance(js, str)
    # A point emitter has no rotate panel, but coords/scale readouts render.
    assert p.dispatch_event('set_tool:transform') is True
    assert p.transform_coords() is not None
    assert p.dispatch_event('set_tool:scale') is True
    assert p.scale_values() is not None
    assert p.dispatch_event('set_tool:rotate') is True
    assert p.rotate_values() is None
    # Reported crash sites in the drag-begin/apply helpers (host input path,
    # but plain-Python callable without a host).
    p.active_tool = "transform"
    p._begin_axis_drag(0, 0.0)
    p._apply_axis_drag(1.0)
    p.active_tool = "scale"
    p._begin_scale_drag(0, 0.0)
    p._apply_scale_drag(1.0)


def test_scale_copy_on_emitter_records_real_radius_not_placeholder():
    """Task 10: with _scale_kind_and_fields now emitter-aware, scale_copy on a
    point emitter records its REAL radius (1.0), NOT the old inert placeholder
    ("radius", (0.0,)). A subsequent scale_paste applies the real value, never
    SCALE_MIN from a clobbered placeholder — the old corruption path stays
    closed because the copied data is now genuine."""
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    # First copy a real subsystem radius so we can prove the clipboard holds a
    # valid value throughout, not a 0.0 placeholder.
    assert p.dispatch_event("select_pin:0") is True
    assert p.dispatch_event("set_tool:scale") is True
    assert p.dispatch_event("scale_copy") is True
    assert p._scale_clipboard == ("radius", (0.3,))

    # Copy on the emitter now records the emitter's REAL radius (1.0), a valid
    # clipboard — not (0.0,).
    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": 0, "j": 0})) is True
    assert p.dispatch_event("scale_copy") is True
    assert p._scale_clipboard == ("radius", (1.0,))   # real, never 0.0

    # Paste that real radius back onto the subsystem: applies 1.0, not
    # SCALE_MIN.
    assert p.dispatch_event("select_pin:0") is True
    assert p.dispatch_event("scale_paste") is True
    assert p._pending_radius[0] == 1.0                # real value, not 0.01


def test_scale_copy_emitter_then_paste_onto_box_light_is_kind_blocked():
    """Different-kind corruption guard stays closed: copy an emitter radius,
    then a Box light (kind 'xyz') must REJECT the paste via the kind-match —
    its scale is untouched (never overwritten with SCALE_MIN)."""
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    p._descriptors[0]["light"] = True
    p._descriptors[0]["light_region"] = {
        "shape": "Box", "position": (0.0, 0.0, 0.0),
        "axis": (0.0, -1.0, 0.0), "radius": (0.25,), "extent": (0.0, 2.0),
        "scale": (0.4, 0.5, 0.6),
        "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    }
    _select_emitter(p)
    p.active_tool = "scale"
    assert p.dispatch_event("scale_copy") is True      # ("radius", (1.0,))
    assert p.dispatch_event("select_light:0") is True
    sv = p.scale_values()
    assert sv["kind"] == "xyz"
    assert sv["can_paste"] is False
    assert p.dispatch_event("scale_paste") is True
    assert p._effective_light(0)["scale"] == (0.4, 0.5, 0.6)   # untouched


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


# ----------------------------------------------------------------------
# Task 7: transform / scale / rotate gizmo routing for emitters
# ----------------------------------------------------------------------
def _select_emitter(p, i=0, j=0):
    assert p.dispatch_event(
        'select_emitter:' + json.dumps({"i": i, "j": j})) is True


def test_transform_drag_moves_emitter_position():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    _select_emitter(p)
    p.active_tool = "transform"
    p._begin_axis_drag_for_test(axis=0, grab_param=0.0)
    p._apply_axis_drag(1.5)
    spec = p._effective_emitter(0, 0)
    assert abs(spec["position"][0] - 1.5) < 1e-9   # X advanced by 1.5
    assert spec["position"][1] == 0.0
    assert spec["position"][2] == 0.0


def test_transform_drag_restages_whole_list_keeps_other_emitter():
    """Moving emitter j=1 must restage the WHOLE compacted list, leaving the
    sibling emitter j=0 untouched and indices dense."""
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("point"), _emitter_spec("cone")])
    _select_emitter(p, j=1)
    p.active_tool = "transform"
    p._begin_axis_drag_for_test(axis=2, grab_param=0.0)
    p._apply_axis_drag(3.0)
    specs = p._effective_emitters(0)
    assert [s["kind"] for s in specs] == ["point", "cone"]
    assert specs[0]["position"] == (0.0, 0.0, 0.0)            # untouched
    assert abs(specs[1]["position"][2] - 3.0) < 1e-9          # moved


def test_scale_drag_strip_axial_scales_length_perp_scales_radius():
    from engine.ui.ship_property_viewer import gizmo_length
    # Strip axis default (0,-1,0) -> dominant body component index 1 (Y). The
    # Y handle is axial (Length); the X handle is perpendicular (Radius).
    p = _panel_with_subsystem(emitters=[_emitter_spec("strip")])
    _select_emitter(p)
    p.active_tool = "scale"
    L = gizmo_length(p.camera)
    p._begin_scale_drag(1, L)          # axial handle -> Length (field 1)
    p._apply_scale_drag(1.5 * L)       # ratio 1.5
    spec = p._effective_emitter(0, 0)
    assert round(spec["length"], 6) == 3.0    # 2.0 * 1.5
    assert round(spec["radius"], 6) == 1.0    # unchanged

    p2 = _panel_with_subsystem(emitters=[_emitter_spec("strip")])
    _select_emitter(p2)
    p2.active_tool = "scale"
    L2 = gizmo_length(p2.camera)
    p2._begin_scale_drag(0, L2)        # perpendicular handle -> Radius (field 0)
    p2._apply_scale_drag(2.0 * L2)     # ratio 2.0
    spec2 = p2._effective_emitter(0, 0)
    assert round(spec2["radius"], 6) == 2.0   # 1.0 * 2
    assert round(spec2["length"], 6) == 2.0   # unchanged


def test_scale_drag_cone_axial_grows_length_perp_grows_a_radius():
    from engine.ui.ship_property_viewer import gizmo_length
    # Cone is now a 3-field (radius_xy_length) shape. Default axis (0,-1,0):
    # forward=Y -> Length; the Z (right) handle -> Radius X; the X (up) handle ->
    # Radius Y. Per-handle field mapping is exhaustively covered by
    # test_begin_scale_drag_cone_default_handles_map_distinct_fields; here we
    # just confirm the axial handle still drives Length and a perpendicular
    # handle drives a radius.
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p)
    p.active_tool = "scale"
    L = gizmo_length(p.camera)
    p._begin_scale_drag(2, L)          # right (Z) -> Radius X
    p._apply_scale_drag(2.0 * L)
    spec = p._effective_emitter(0, 0)
    assert round(spec["radius"], 6) == 2.0    # 1.0 * 2 (wider angle)
    assert round(spec["length"], 6) == 2.0    # unchanged

    p2 = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p2)
    p2.active_tool = "scale"
    L2 = gizmo_length(p2.camera)
    p2._begin_scale_drag(1, L2)        # axial (Y, forward) -> Length
    p2._apply_scale_drag(1.5 * L2)
    spec2 = p2._effective_emitter(0, 0)
    assert round(spec2["length"], 6) == 3.0   # 2.0 * 1.5
    assert round(spec2["radius"], 6) == 1.0   # unchanged


def test_rotate_target_is_emitter_for_strip_and_cone():
    for kind in ("strip", "cone"):
        p = _panel_with_subsystem(emitters=[_emitter_spec(kind)])
        _select_emitter(p)
        p.active_tool = "rotate"
        assert p._rotate_target() == ("emitter", 0, 0)


def test_rotate_ring_drag_rotates_cone_axis():
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p)
    p.active_tool = "rotate"
    p._begin_ring_drag(0, 0.0)                       # ring 0 -> rotate about +X
    p._apply_ring_drag_angle(math.radians(90.0))
    ax = p._effective_emitter(0, 0)["axis"]
    # axis (0,-1,0) rotated +90deg about +X -> (0, 0, -1)
    assert abs(ax[0]) < 1e-6
    assert abs(ax[1]) < 1e-6
    assert abs(ax[2] - (-1.0)) < 1e-6


def test_rotate_ring_drag_restages_whole_list_keeps_other_emitter():
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("point"), _emitter_spec("cone")])
    _select_emitter(p, j=1)
    p.active_tool = "rotate"
    p._begin_ring_drag(0, 0.0)
    p._apply_ring_drag_angle(math.radians(90.0))
    specs = p._effective_emitters(0)
    assert [s["kind"] for s in specs] == ["point", "cone"]
    assert specs[0]["axis"] == (0.0, -1.0, 0.0)      # sibling untouched
    assert abs(specs[1]["axis"][2] - (-1.0)) < 1e-6  # cone rotated


def test_point_emitter_rotate_is_inert_no_crash():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    _select_emitter(p)
    p.active_tool = "rotate"
    assert p._rotate_target() is None            # point rotate inert
    assert p.rotate_gizmo() is None
    # A ring drag on a point emitter is a clean no-op (no crash, no mutation).
    p._begin_ring_drag(0, 0.0)
    p._apply_ring_drag_angle(math.radians(45.0))
    assert p._effective_emitter(0, 0)["axis"] == (0.0, -1.0, 0.0)


def test_scale_drag_restages_whole_list_keeps_other_emitter():
    """Scaling emitter j=1 restages the WHOLE compacted list, leaving the
    sibling emitter j=0 untouched (mirrors the transform/rotate invariant)."""
    from engine.ui.ship_property_viewer import gizmo_length
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("strip"), _emitter_spec("cone")])
    _select_emitter(p, j=1)          # scale the cone
    p.active_tool = "scale"
    L = gizmo_length(p.camera)
    p._begin_scale_drag(2, L)        # right handle (Z) -> Radius X for default cone
    p._apply_scale_drag(2.0 * L)     # ratio 2.0
    specs = p._effective_emitters(0)
    assert [s["kind"] for s in specs] == ["strip", "cone"]
    assert round(specs[1]["radius"], 6) == 2.0   # cone radius scaled
    assert specs[0]["radius"] == 1.0             # strip sibling untouched
    assert specs[0]["length"] == 2.0


def _cylinder_light_region():
    return {
        "shape": "Cylinder", "position": (0.0, 0.0, 0.0),
        "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
        "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
        "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    }


def test_emitter_and_light_rotate_readouts_are_independent():
    """Regression: _rotate_accum must be keyed by the target identity, not the
    bare subsystem index — otherwise a subsystem's Cylinder-light rotate
    readout and its cone-emitter rotate share a key and cross-contaminate."""
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    p._descriptors[0]["light"] = True
    p._descriptors[0]["light_region"] = _cylinder_light_region()
    p.active_tool = "rotate"

    # Rotate the cone emitter's axis 90deg about +X.
    _select_emitter(p)
    assert p._rotate_target() == ("emitter", 0, 0)
    p._begin_ring_drag(0, 0.0)
    p._apply_ring_drag_angle(math.radians(90.0))

    # The sibling light's degree readout must be untouched (still all zero) —
    # before the fix it showed the emitter's 90deg in X.
    assert p.dispatch_event('select_light:0') is True
    assert p._rotate_target() == ("light", 0)
    rv = p.rotate_values()
    assert rv is not None
    assert [f["value"] for f in rv["fields"]] == [0.0, 0.0, 0.0]

    # Rotate the light 45deg about +Y; its readout updates independently.
    p._begin_ring_drag(1, 0.0)
    p._apply_ring_drag_angle(math.radians(45.0))
    assert round(p.rotate_values()["fields"][1]["value"], 3) == 45.0

    # And the light rotate must not have disturbed the emitter's staged axis.
    _select_emitter(p)
    ax = p._effective_emitter(0, 0)["axis"]
    assert abs(ax[2] - (-1.0)) < 1e-6


# ----------------------------------------------------------------------
# Task 9: save routing (_pending_emitter -> __emitter__ edits) + tally
# ----------------------------------------------------------------------

def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1: payload.rindex(")")])


def test_emitter_save_edits_dense_with_clear_for_removed_trailing():
    """Stage two emitters, edit one, remove the other: _emitter_save_edits()
    must emit one __emitter__ edit per DENSE index up to the widest of the
    new/baked/saved lists, with [] clearing the now-unused trailing index
    (drives the writer's drop-empty path) rather than leaving a gap."""
    from engine.ui.ship_property_viewer import emitter_spec_to_calls
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("point"), _emitter_spec("cone")])
    assert p.dispatch_event('set_emitter:' + json.dumps({
        "i": 0, "j": 0, "kind": "point",
        "color": [1.0, 0.0, 0.0], "intensity": 5.0,
    })) is True
    assert p.dispatch_event(
        'remove_emitter:' + json.dumps({"i": 0, "j": 1})) is True

    edits = p._emitter_save_edits()

    assert len(edits) == 2
    name0, tag0, j0, calls0 = edits[0]
    assert (name0, tag0, j0) == ("Center Impulse", "__emitter__", 0)
    kept_spec = p._effective_emitter(0, 0)
    assert calls0 == emitter_spec_to_calls(0, kept_spec)
    name1, tag1, j1, calls1 = edits[1]
    assert (name1, tag1, j1) == ("Center Impulse", "__emitter__", 1)
    assert calls1 == []          # removed trailing emitter -> clear, not gap


def test_save_dispatch_writes_dense_emitter_edits_and_clears_pending(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits):
            calls.append((leaf, edits))

    class _Ship:
        def GetScript(self):
            return "ships.Galaxy"

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")

    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
        "emitters": [_emitter_spec("point")],
    }]
    assert p.dispatch_event(
        'remove_emitter:' + json.dumps({"i": 0, "j": 0})) is True

    assert p.dispatch_event("save") is True

    assert len(calls) == 1
    leaf, edits = calls[0]
    assert leaf == "galaxy"
    assert edits == [("Center Impulse", "__emitter__", 0, [])]
    # Staged edits are gone; the saved-this-session cache keeps driving the
    # live preview (empty list = no emitters left) without re-dirtying.
    assert p._pending_emitter == {}
    assert p._saved_emitter == {0: []}
    assert _payload_data(p.render_payload())["pending_count"] == 0


def test_save_confirm_tally_counts_staged_emitter_edit():
    # The Save-confirm modal's per-subsystem tally must count a subsystem
    # that ONLY has a staged emitter edit (no radius/light/pos edit) — this
    # closes a Task-6 deferred gap (emitter edits were invisible to the
    # tally/dirty/early-out unions).
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    assert p.dispatch_event('set_emitter:' + json.dumps({
        "i": 0, "j": 0, "kind": "cone",
        "color": [1.0, 0.0, 0.0], "intensity": 3.0,
    })) is True
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1
    assert data["pending"] == [{"name": "Center Impulse", "count": 1}]
    assert data["subsystems"][0]["dirty"] is True


def test_save_early_out_guard_does_not_skip_emitter_only_edit(monkeypatch):
    # Regression for the early-out at the top of the "save" handler: before
    # the fix it checked only radius/light/pos, so an emitter-only edit hit
    # the "nothing staged" fast path and the write was skipped entirely.
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits):
            calls.append((leaf, edits))

    class _Ship:
        def GetScript(self):
            return "ships.Galaxy"

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")

    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
        "emitters": [],
    }]
    assert p.dispatch_event(
        'add_emitter:' + json.dumps({"i": 0, "kind": "point"})) is True
    assert p.dispatch_event("save") is True
    assert len(calls) == 1        # write happened, not skipped


# ----------------------------------------------------------------------
# Task 10: emitter value panels (transform / scale / rotate) + Copy /
# Paste / Mirror / Nudge — parity with light volumes.
# ----------------------------------------------------------------------

def test_transform_coords_shows_point_emitter_position():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    _select_emitter(p)
    p.active_tool = "transform"
    tc = p.transform_coords()
    assert tc is not None
    assert (tc["x"], tc["y"], tc["z"]) == (0.0, 0.0, 0.0)


def test_scale_values_point_emitter_is_radius():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    _select_emitter(p)
    p.active_tool = "scale"
    sv = p.scale_values()
    assert sv is not None
    assert sv["kind"] == "radius"
    assert [f["label"] for f in sv["fields"]] == ["Radius"]
    assert sv["fields"][0]["value"] == 1.0


def test_scale_values_strip_emitter_is_radius_length():
    p = _panel_with_subsystem(emitters=[_emitter_spec("strip")])
    _select_emitter(p)
    p.active_tool = "scale"
    sv = p.scale_values()
    assert sv is not None
    assert sv["kind"] == "radius_length"
    assert [f["label"] for f in sv["fields"]] == ["Radius", "Length"]
    assert sv["fields"][0]["value"] == 1.0
    assert sv["fields"][1]["value"] == 2.0


def test_rotate_values_present_for_cone_absent_for_point():
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p)
    p.active_tool = "rotate"
    rv = p.rotate_values()
    assert rv is not None
    assert [f["label"] for f in rv["fields"]] == ["X", "Y", "Z"]
    assert [f["value"] for f in rv["fields"]] == [0.0, 0.0, 0.0]

    p2 = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    _select_emitter(p2)
    p2.active_tool = "rotate"
    assert p2.rotate_values() is None      # point emitter: no rotate panel


def test_coord_nudge_moves_emitter_position():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    _select_emitter(p)
    p.active_tool = "transform"
    assert p.dispatch_event(
        'coord_nudge:' + json.dumps({"axis": 0, "delta": 0.5})) is True
    assert abs(p._effective_emitter(0, 0)["position"][0] - 0.5) < 1e-9


def test_coord_copy_paste_between_two_emitters_keeps_list_dense():
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("point"), _emitter_spec("point")])
    _select_emitter(p, j=0)
    p.active_tool = "transform"
    p.set_emitter_position(0, 0, (1.0, 2.0, 3.0))
    assert p.dispatch_event("coord_copy") is True
    _select_emitter(p, j=1)
    assert p.dispatch_event("coord_paste") is True
    specs = p._effective_emitters(0)
    assert len(specs) == 2                       # dense, sibling survives
    assert specs[1]["position"] == (1.0, 2.0, 3.0)
    assert specs[0]["position"] == (1.0, 2.0, 3.0)


def test_coord_mirror_negates_emitter_x():
    p = _panel_with_subsystem(emitters=[_emitter_spec("point")])
    _select_emitter(p)
    p.active_tool = "transform"
    p.set_emitter_position(0, 0, (1.5, 2.0, 3.0))
    assert p.dispatch_event("coord_mirror") is True
    assert p._effective_emitter(0, 0)["position"] == (-1.5, 2.0, 3.0)


def test_scale_paste_radius_clipboard_rejected_on_radius_length_emitter():
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("point"), _emitter_spec("strip")])
    _select_emitter(p, j=0)              # point -> radius
    p.active_tool = "scale"
    assert p.dispatch_event("scale_copy") is True
    assert p._scale_clipboard == ("radius", (1.0,))
    _select_emitter(p, j=1)              # strip -> radius_length
    sv = p.scale_values()
    assert sv["kind"] == "radius_length"
    assert sv["can_paste"] is False      # radius clipboard can't paste here
    assert p.dispatch_event("scale_paste") is True
    assert p._effective_emitter(0, 1)["radius"] == 1.0   # untouched
    assert p._effective_emitter(0, 1)["length"] == 2.0


def test_scale_nudge_and_copy_paste_roundtrip_on_strip_emitter():
    p = _panel_with_subsystem(emitters=[_emitter_spec("strip")])
    _select_emitter(p)
    p.active_tool = "scale"
    # nudge Radius (field 0) +0.5
    assert p.dispatch_event(
        'scale_nudge:' + json.dumps({"index": 0, "delta": 0.5})) is True
    assert round(p._effective_emitter(0, 0)["radius"], 6) == 1.5
    assert p.dispatch_event("scale_copy") is True
    assert p._scale_clipboard == ("radius_length", (1.5, 2.0))
    # mutate then paste restores
    p._set_scale_field(0, 3.0)
    assert round(p._effective_emitter(0, 0)["radius"], 6) == 3.0
    assert p.dispatch_event("scale_paste") is True
    assert round(p._effective_emitter(0, 0)["radius"], 6) == 1.5
    assert round(p._effective_emitter(0, 0)["length"], 6) == 2.0


def test_rotate_copy_cone_emitter_records_cone_orientation():
    # A cone now carries a forward+up basis, so its clipboard kind is
    # "cone_orientation" (default axis (0,-1,0), derived up (1,0,0)); strip
    # stays "cylinder_axis" (see test_rotate_copy below is exercised elsewhere).
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p)
    p.active_tool = "rotate"
    assert p.dispatch_event("rotate_copy") is True
    assert p._rotate_clipboard == (
        "cone_orientation", ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0)))


def test_rotate_copy_strip_emitter_still_records_cylinder_axis():
    p = _panel_with_subsystem(emitters=[_emitter_spec("strip")])
    _select_emitter(p)
    p.active_tool = "rotate"
    assert p.dispatch_event("rotate_copy") is True
    assert p._rotate_clipboard == ("cylinder_axis", (0.0, -1.0, 0.0))


def test_rotate_paste_between_two_cone_emitters_keeps_list_dense():
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("cone"), _emitter_spec("cone")])
    _select_emitter(p, j=0)
    p.active_tool = "rotate"
    p._rotate_axis(0, 90.0)              # (0,-1,0) about +X -> (0,0,-1)
    assert p.dispatch_event("rotate_copy") is True
    _select_emitter(p, j=1)
    assert p.dispatch_event("rotate_paste") is True
    ax = p._effective_emitter(0, 1)["axis"]
    assert abs(ax[0]) < 1e-6 and abs(ax[1]) < 1e-6 and abs(ax[2] - (-1.0)) < 1e-6
    specs = p._effective_emitters(0)
    assert len(specs) == 2               # dense; sibling intact


def test_rotate_mirror_negates_cone_emitter_axis_x():
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p)
    p.active_tool = "rotate"
    p._set_axis_absolute(("emitter", 0, 0), (0.6, -0.8, 0.0))
    assert p.dispatch_event("rotate_mirror") is True
    ax = p._effective_emitter(0, 0)["axis"]
    assert abs(ax[0] - (-0.6)) < 1e-6
    assert abs(ax[1] - (-0.8)) < 1e-6
    assert abs(ax[2]) < 1e-6


def test_rotate_nudge_on_cone_emitter_restages_whole_list():
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("point"), _emitter_spec("cone")])
    _select_emitter(p, j=1)
    p.active_tool = "rotate"
    assert p.dispatch_event(
        'rotate_nudge:' + json.dumps({"axis": 0, "delta": 90.0})) is True
    specs = p._effective_emitters(0)
    assert [s["kind"] for s in specs] == ["point", "cone"]
    assert specs[0]["axis"] == (0.0, -1.0, 0.0)          # sibling untouched
    assert abs(specs[1]["axis"][2] - (-1.0)) < 1e-6      # cone rotated
    # the degree accumulator drives the rotate readout
    assert round(p.rotate_values()["fields"][0]["value"], 3) == 90.0


def test_cylinder_light_axis_pastes_onto_strip_emitter_cross_kind():
    """The mirror-a-light workflow: a cylinder LIGHT's copied axis (kind
    'cylinder_axis') pastes onto a STRIP emitter (same kind) and vice versa. A
    cone now uses 'cone_orientation' and no longer interchanges with a cylinder
    light (see test_rotate_paste_cone_orientation_rejected_on_strip_emitter)."""
    p = _panel_with_subsystem(emitters=[_emitter_spec("strip")])
    p._descriptors[0]["light"] = True
    p._descriptors[0]["light_region"] = _cylinder_light_region()
    p.active_tool = "rotate"
    assert p.dispatch_event("select_light:0") is True
    p._rotate_axis(0, 90.0)               # cylinder axis (0,-1,0) -> (0,0,-1)
    assert p.dispatch_event("rotate_copy") is True
    assert p._rotate_clipboard[0] == "cylinder_axis"
    _select_emitter(p)
    rv = p.rotate_values()
    assert rv is not None
    assert rv["can_paste"] is True        # kinds match across light<->emitter
    assert p.dispatch_event("rotate_paste") is True
    ax = p._effective_emitter(0, 0)["axis"]
    assert abs(ax[2] - (-1.0)) < 1e-6


# ----------------------------------------------------------------------
# Task 3: cone 3-field scale (Radius X / Radius Y / Length) + ORIENTED
# cone rotate (forward+up, like a Box light). Cone rotate clipboard kind
# is "cone_orientation"; strip stays single-axis "cylinder_axis".
# ----------------------------------------------------------------------

def _cone_with_orientation(axis, up, radius=1.0, radius_y=0.5, length=2.0):
    s = _emitter_spec("cone")
    s["axis"] = axis
    s["up"] = up
    s["radius"] = radius
    s["radius_y"] = radius_y
    s["length"] = length
    return s


def test_scale_values_cone_emitter_is_radius_xy_length():
    p = _panel_with_subsystem(
        emitters=[_cone_with_orientation((0.0, -1.0, 0.0), (1.0, 0.0, 0.0),
                                         radius=1.0, radius_y=0.5, length=2.0)])
    _select_emitter(p)
    p.active_tool = "scale"
    sv = p.scale_values()
    assert sv is not None
    assert sv["kind"] == "radius_xy_length"
    assert [f["label"] for f in sv["fields"]] == ["Radius X", "Radius Y", "Length"]
    assert [f["value"] for f in sv["fields"]] == [1.0, 0.5, 2.0]


def test_scale_values_cone_without_radius_y_defaults_to_radius():
    # A circular/legacy cone (no radius_y) reports Radius Y == Radius X.
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p)
    p.active_tool = "scale"
    sv = p.scale_values()
    assert sv["kind"] == "radius_xy_length"
    assert [f["value"] for f in sv["fields"]] == [1.0, 1.0, 2.0]


def test_set_scale_field_cone_writes_the_three_fields_whole_list():
    # Each of the 3 fields routes to radius / radius_y / length; the sibling
    # emitter is restaged untouched and the list stays dense.
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("point"),
                  _cone_with_orientation((0.0, -1.0, 0.0), (1.0, 0.0, 0.0))])
    _select_emitter(p, j=1)
    p.active_tool = "scale"
    p._set_scale_field(0, 3.0)   # Radius X -> radius
    p._set_scale_field(1, 4.0)   # Radius Y -> radius_y
    p._set_scale_field(2, 5.0)   # Length   -> length
    specs = p._effective_emitters(0)
    assert [s["kind"] for s in specs] == ["point", "cone"]
    assert specs[1]["radius"] == 3.0
    assert specs[1]["radius_y"] == 4.0
    assert specs[1]["length"] == 5.0
    assert specs[0]["kind"] == "point"           # sibling untouched
    assert specs[0]["radius"] == 1.0


def test_begin_scale_drag_cone_default_handles_map_distinct_fields():
    # Default cone axis (0,-1,0): forward=Y, up=(1,0,0)=X, right=(0,0,1)=Z.
    # handle Y -> Length; handle X (up) -> Radius Y; handle Z (right) -> Radius X.
    from engine.ui.ship_property_viewer import gizmo_length

    def _drag(handle):
        p = _panel_with_subsystem(
            emitters=[_cone_with_orientation((0.0, -1.0, 0.0), (1.0, 0.0, 0.0))])
        _select_emitter(p)
        p.active_tool = "scale"
        L = gizmo_length(p.camera)
        p._begin_scale_drag(handle, L)
        p._apply_scale_drag(2.0 * L)          # ratio 2
        return p._effective_emitter(0, 0)

    z = _drag(2)                              # right -> Radius X
    assert round(z["radius"], 6) == 2.0 and round(z["radius_y"], 6) == 0.5
    assert round(z["length"], 6) == 2.0
    x = _drag(0)                              # up -> Radius Y
    assert round(x["radius_y"], 6) == 1.0 and round(x["radius"], 6) == 1.0
    assert round(x["length"], 6) == 2.0
    y = _drag(1)                              # forward -> Length
    assert round(y["length"], 6) == 4.0 and round(y["radius"], 6) == 1.0
    assert round(y["radius_y"], 6) == 0.5


def test_begin_scale_drag_oriented_cone_right_vs_up_split():
    # Cone forward=+X, up=+Z -> right=cross(+X,+Z)=(0,-1,0)=Y. So handle X ->
    # Length, handle Y (right) -> Radius X, handle Z (up) -> Radius Y. This
    # proves the two perpendicular handles resolve to DISTINCT radius fields by
    # oriented-frame alignment, not by fixed body axis.
    from engine.ui.ship_property_viewer import gizmo_length

    def _drag(handle):
        p = _panel_with_subsystem(
            emitters=[_cone_with_orientation((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))])
        _select_emitter(p)
        p.active_tool = "scale"
        L = gizmo_length(p.camera)
        p._begin_scale_drag(handle, L)
        p._apply_scale_drag(2.0 * L)
        return p._effective_emitter(0, 0)

    x = _drag(0)                              # forward -> Length
    assert round(x["length"], 6) == 4.0
    y = _drag(1)                              # right -> Radius X
    assert round(y["radius"], 6) == 2.0 and round(y["radius_y"], 6) == 0.5
    z = _drag(2)                              # up -> Radius Y
    assert round(z["radius_y"], 6) == 1.0 and round(z["radius"], 6) == 1.0


def test_rotate_ring_drag_cone_rotates_axis_and_up_orthonormal():
    # Ring 2 (+Z) by 90deg: axis (0,-1,0)->(1,0,0); up (1,0,0)->(0,1,0).
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p)
    p.active_tool = "rotate"
    p._begin_ring_drag(2, 0.0)
    p._apply_ring_drag_angle(math.radians(90.0))
    spec = p._effective_emitter(0, 0)
    ax, up = spec["axis"], spec["up"]
    assert abs(ax[0] - 1.0) < 1e-6 and abs(ax[1]) < 1e-6 and abs(ax[2]) < 1e-6
    assert abs(up[0]) < 1e-6 and abs(up[1] - 1.0) < 1e-6 and abs(up[2]) < 1e-6
    # orthonormal: unit + perpendicular
    assert abs(ax[0]*up[0] + ax[1]*up[1] + ax[2]*up[2]) < 1e-6
    assert abs(sum(c*c for c in up) - 1.0) < 1e-6


def test_rotate_axis_nudge_cone_rotates_axis_and_up():
    # The nudge sibling (_rotate_axis) also rotates both forward and up.
    p = _panel_with_subsystem(emitters=[_emitter_spec("cone")])
    _select_emitter(p)
    p.active_tool = "rotate"
    p._rotate_axis(2, 90.0)                   # about +Z
    spec = p._effective_emitter(0, 0)
    ax, up = spec["axis"], spec["up"]
    assert abs(ax[0] - 1.0) < 1e-6
    assert abs(up[1] - 1.0) < 1e-6
    assert abs(ax[0]*up[0] + ax[1]*up[1] + ax[2]*up[2]) < 1e-6


def test_rotate_copy_paste_roundtrips_cone_orientation():
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("cone"), _emitter_spec("cone")])
    _select_emitter(p, j=0)
    p.active_tool = "rotate"
    p._rotate_axis(2, 90.0)                   # j=0 -> axis (1,0,0), up (0,1,0)
    src = p._effective_emitter(0, 0)
    assert p.dispatch_event("rotate_copy") is True
    assert p._rotate_clipboard[0] == "cone_orientation"
    _select_emitter(p, j=1)
    assert p.dispatch_event("rotate_paste") is True
    dst = p._effective_emitter(0, 1)
    for a, b in zip(dst["axis"], src["axis"]):
        assert abs(a - b) < 1e-6
    for a, b in zip(dst["up"], src["up"]):
        assert abs(a - b) < 1e-6
    assert len(p._effective_emitters(0)) == 2   # dense; sibling intact


def test_rotate_mirror_negates_cone_axis_and_up_x():
    p = _panel_with_subsystem(
        emitters=[_cone_with_orientation((0.6, -0.8, 0.0), (0.8, 0.6, 0.0))])
    _select_emitter(p)
    p.active_tool = "rotate"
    assert p.dispatch_event("rotate_mirror") is True
    spec = p._effective_emitter(0, 0)
    ax, up = spec["axis"], spec["up"]
    assert abs(ax[0] - (-0.6)) < 1e-6 and abs(ax[1] - (-0.8)) < 1e-6
    assert abs(up[0] - (-0.8)) < 1e-6 and abs(up[1] - 0.6) < 1e-6


def test_rotate_paste_cone_orientation_rejected_on_strip_emitter():
    # A cone_orientation clipboard must NOT paste onto a strip (kind mismatch);
    # strip stays cylinder_axis.
    p = _panel_with_subsystem(
        emitters=[_emitter_spec("cone"), _emitter_spec("strip")])
    _select_emitter(p, j=0)
    p.active_tool = "rotate"
    assert p.dispatch_event("rotate_copy") is True
    assert p._rotate_clipboard[0] == "cone_orientation"
    _select_emitter(p, j=1)                   # strip
    rv = p.rotate_values()
    assert rv["can_paste"] is False
    assert p.dispatch_event("rotate_paste") is True
    assert p._effective_emitter(0, 1)["axis"] == (0.0, -1.0, 0.0)   # untouched


def test_scale_uniform_is_noop_on_cone_three_field():
    p = _panel_with_subsystem(
        emitters=[_cone_with_orientation((0.0, -1.0, 0.0), (1.0, 0.0, 0.0),
                                         radius=1.0, radius_y=0.5, length=4.0)])
    _select_emitter(p)
    p.active_tool = "scale"
    assert p.dispatch_event("scale_uniform") is True
    spec = p._effective_emitter(0, 0)
    assert spec["radius"] == 1.0 and spec["radius_y"] == 0.5 and spec["length"] == 4.0


def test_scale_copy_paste_roundtrip_cone_three_fields():
    p = _panel_with_subsystem(
        emitters=[_cone_with_orientation((0.0, -1.0, 0.0), (1.0, 0.0, 0.0),
                                         radius=1.5, radius_y=0.75, length=3.0)])
    _select_emitter(p)
    p.active_tool = "scale"
    assert p.dispatch_event("scale_copy") is True
    assert p._scale_clipboard == ("radius_xy_length", (1.5, 0.75, 3.0))
    p._set_scale_field(0, 9.0)
    p._set_scale_field(1, 9.0)
    p._set_scale_field(2, 9.0)
    assert p.dispatch_event("scale_paste") is True
    spec = p._effective_emitter(0, 0)
    assert round(spec["radius"], 6) == 1.5
    assert round(spec["radius_y"], 6) == 0.75
    assert round(spec["length"], 6) == 3.0
