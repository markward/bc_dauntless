"""SPV light-type modal dispatch: set_light shape-only, add_light gains shape."""
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _panel_with_light(shape="Cylinder", radius=(0.3,), extent=(-2.0, 2.0),
                      scale=(0.2, 0.3, 0.4)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Port Warp", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None, "light": True,
        "light_region": {"shape": shape, "position": (0.1, 1.0, 0.2),
                         "axis": (0.0, -1.0, 0.0), "radius": radius,
                         "extent": extent, "scale": scale,
                         "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))},
    }]
    p._selected_light_index = 0
    return p


def _panel_no_light():
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Hull", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None, "light": False,
        # from-scratch default spec (Sphere), as _light_annotation attaches:
        "light_region": {"shape": "Sphere", "position": (0.0, 0.0, 0.0),
                         "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                         "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
                         "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))},
    }]
    return p


def test_set_light_changes_only_shape_preserves_size():
    p = _panel_with_light(shape="Cylinder", radius=(0.3,), extent=(-2.0, 2.0),
                          scale=(0.2, 0.3, 0.4))
    assert p.dispatch_event('set_light:' + json.dumps({"i": 0, "shape": "Box"})) is True
    spec = p._effective_light(0)
    assert spec["shape"] == "Box"
    # every non-shape field preserved
    assert spec["radius"] == (0.3,)
    assert spec["extent"] == (-2.0, 2.0)
    assert spec["scale"] == (0.2, 0.3, 0.4)
    assert spec["position"] == (0.1, 1.0, 0.2)
    assert spec["orientation"] == ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def test_set_light_rejects_unknown_shape():
    p = _panel_with_light()
    assert p.dispatch_event('set_light:' + json.dumps({"i": 0, "shape": "Blob"})) is False


def test_add_light_stages_chosen_shape_and_selects():
    p = _panel_no_light()
    assert p.dispatch_event('add_light:' + json.dumps({"i": 0, "shape": "Cylinder"})) is True
    assert p._selected_light_index == 0
    assert p.selected_index is None
    assert p._effective_light(0)["shape"] == "Cylinder"


def test_add_light_bare_int_still_works():
    p = _panel_no_light()
    assert p.dispatch_event("add_light:0") is True     # legacy payload
    assert p._selected_light_index == 0
    assert p._effective_light(0)["shape"] == "Sphere"  # base spec's own shape


def test_add_light_guarded_when_already_lit():
    p = _panel_with_light()
    assert p.dispatch_event('add_light:' + json.dumps({"i": 0, "shape": "Box"})) is False
