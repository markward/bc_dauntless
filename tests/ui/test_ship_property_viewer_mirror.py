"""SPV whole-element Mirror: flip the selected element to its port<->starboard
twin in one click. Negates position X, mirrors the rotation basis across X,
leaves scale/colour/intensity unchanged.

Fixture mirrors test_ship_property_viewer_undo.py's `build_descriptors`
monkeypatch pattern.
"""
import pytest

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

_DEFAULT_LIGHT_REGION = {
    "shape": "Sphere", "position": (0.0, 0.0, 0.0),
    "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
    "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
    "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}


def _strip_emitter():
    return {
        "kind": "strip",
        "position": (0.0, 0.0, 0.0),
        "axis": (0.0, -1.0, 0.0),
        "length": 2.0,
        "radius": 1.0,
        "color": (1.0, 0.9, 0.7),
        "intensity": 2.0,
    }


_FAKE_DESCRIPTORS = [
    {
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
        "emitters": [_strip_emitter()],
    },
    {
        "name": "Aft Impulse", "kind": "subsystem",
        "properties": {"position": (2.0, 0.0, 0.0), "radius": 0.5},
        "world_pos": (2.0, 0.0, 0.0), "parent_index": None,
        "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
        "emitters": [_strip_emitter()],
    },
]


@pytest.fixture
def spv_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(d, emitters=[dict(e) for e in d["emitters"]])
                      for d in _FAKE_DESCRIPTORS])
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    return p


def test_mirror_element_negates_position_x(spv_panel):
    p = spv_panel
    p.set_subsystem_position(0, (3.0, 1.0, 2.0))
    p.dispatch_event("select_pin:0")
    p.dispatch_event("mirror_element")
    assert p._effective_pos(0) == (-3.0, 1.0, 2.0)
    assert p._undo_stack


def test_mirror_element_flips_strip_emitter_axis_x(spv_panel):
    p = spv_panel
    # give subsystem 0 a strip emitter with a known axis
    p.dispatch_event('add_emitter:{"i":0,"kind":"strip"}')
    i, j = p._selected_emitter
    p._set_axis_absolute(("emitter", i, j), (0.6, 0.8, 0.0))
    p.dispatch_event("mirror_element")
    spec = p._effective_emitter(i, j)
    ax = spec["axis"]
    assert ax[0] < 0 and abs(ax[1] - 0.8) < 1e-6   # X negated, Y kept


def test_mirror_element_point_emitter_moves_position_only(spv_panel):
    p = spv_panel
    p.dispatch_event('add_emitter:{"i":0,"kind":"point"}')
    i, j = p._selected_emitter
    p.set_emitter_position(i, j, (2.0, 0.0, 0.0))
    before = dict(p._effective_emitter(i, j))
    p.dispatch_event("mirror_element")
    after = p._effective_emitter(i, j)
    assert after["position"][0] == -2.0
    assert after["color"] == before["color"]        # colour unchanged
    assert after["intensity"] == before["intensity"]
