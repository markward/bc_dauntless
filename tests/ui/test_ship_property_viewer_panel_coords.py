"""SPV transform coordinate panel: transform_coords() + coord_* dispatch."""
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _payload_data(payload):
    # payload is "setShipPropertyViewer({...});" — slice the JSON argument.
    start = payload.index("(") + 1
    end = payload.rindex(")")
    return json.loads(payload[start:end])


def _panel_subsystem(baked_pos=(0.0, 1.0, 0.0)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": baked_pos, "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
    }]
    p.dispatch_event("set_tool:transform")
    p.selected_index = 0
    return p


def _panel_light(baked_pos=(0.0, 1.0, 0.0)):
    p = _panel_subsystem(baked_pos)
    p._descriptors[0]["light"] = True
    p._descriptors[0]["light_region"] = {
        "shape": "Sphere", "position": baked_pos, "axis": (0.0, -1.0, 0.0),
        "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    p.selected_index = None
    p._selected_light_index = 0
    return p


def test_transform_coords_none_off_tool():
    p = _panel_subsystem()
    p.dispatch_event("set_tool:transform")   # toggles OFF (already transform)
    assert p.active_tool is None
    assert p.transform_coords() is None


def test_transform_coords_none_without_selection():
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p.dispatch_event("set_tool:transform")
    assert p.transform_coords() is None


def test_transform_coords_reports_subsystem_xyz():
    p = _panel_subsystem((0.1, 2.3, -0.4))
    c = p.transform_coords()
    assert (c["x"], c["y"], c["z"]) == (0.1, 2.3, -0.4)
    assert c["has_clipboard"] is False


def test_coord_nudge_moves_only_that_axis():
    p = _panel_subsystem((0.0, 1.0, 0.0))
    assert p.dispatch_event('coord_nudge:' + json.dumps({"axis": 1, "delta": -0.1})) is True
    c = p.transform_coords()
    assert round(c["y"], 6) == 0.9 and c["x"] == 0.0 and c["z"] == 0.0


def test_coord_nudge_on_light_target():
    p = _panel_light((0.0, 1.0, 0.0))
    p.dispatch_event('coord_nudge:' + json.dumps({"axis": 0, "delta": 0.5}))
    assert round(p.transform_coords()["x"], 6) == 0.5


def test_coord_copy_then_paste_roundtrips():
    p = _panel_subsystem((1.0, 2.0, 3.0))
    assert p.dispatch_event("coord_copy") is True
    assert p.transform_coords()["has_clipboard"] is True
    # move away, then paste restores
    p.dispatch_event('coord_nudge:' + json.dumps({"axis": 0, "delta": 5.0}))
    assert p.transform_coords()["x"] == 6.0
    p.dispatch_event("coord_paste")
    c = p.transform_coords()
    assert (c["x"], c["y"], c["z"]) == (1.0, 2.0, 3.0)


def test_coord_paste_noop_without_clipboard():
    p = _panel_subsystem((1.0, 2.0, 3.0))
    assert p.dispatch_event("coord_paste") is True   # handled, but no change
    c = p.transform_coords()
    assert (c["x"], c["y"], c["z"]) == (1.0, 2.0, 3.0)


def test_coord_mirror_negates_x_only():
    p = _panel_subsystem((0.065, -1.25, -0.17))
    p.dispatch_event("coord_mirror")
    c = p.transform_coords()
    assert round(c["x"], 6) == -0.065
    assert round(c["y"], 6) == -1.25 and round(c["z"], 6) == -0.17


def test_render_payload_carries_coords_and_clipboard():
    p = _panel_subsystem((0.0, 1.0, 0.0))
    data = _payload_data(p.render_payload())
    assert data["transform_coords"]["y"] == 1.0
    assert data["transform_coords"]["has_clipboard"] is False
    p.dispatch_event("coord_copy")
    data2 = _payload_data(p.render_payload())   # snapshot changed -> re-push
    assert data2 is not None
    assert data2["transform_coords"]["has_clipboard"] is True


# ── Click-guard only applies while the coord panel is visible ───────────────

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


def _drag_in_coords_box(p):
    # (700, 100) is inside the top-right coord box for an 800x600 dsf=1 viewport
    # (x in [568,788], y in [46,218]).
    from engine.ui.ship_property_viewer import OrbitCamera
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 20.0, 0.0, 0.0)
    yaw0 = p.camera.yaw
    h = _Host()
    h._cursor = (700.0, 100.0); h._down = True
    p.handle_input(h)              # press
    h._cursor = (730.0, 100.0)
    p.handle_input(h)              # drag right
    return yaw0, p.camera.yaw


def test_coord_region_not_guarded_when_panel_hidden():
    p = _panel_subsystem((0.0, 1.0, 0.0))
    p.dispatch_event("set_tool:transform")     # toggle OFF -> panel hidden
    assert p.transform_coords() is None
    yaw0, yaw1 = _drag_in_coords_box(p)
    assert yaw1 != yaw0            # drag orbited -> region is NOT a dead zone


def test_coord_region_guarded_when_panel_visible():
    p = _panel_subsystem((0.0, 1.0, 0.0))       # Transform on + selected
    assert p.transform_coords() is not None
    yaw0, yaw1 = _drag_in_coords_box(p)
    assert yaw1 == yaw0            # guarded -> no orbit while the panel is up
