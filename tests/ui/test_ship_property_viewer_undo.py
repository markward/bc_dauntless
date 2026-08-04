"""SPV undo snapshot stack: pending-only undo over the four staged-edit
dicts (_pending_radius/_pending_light/_pending_emitter/_pending_pos).

Fixture mirrors test_ship_property_viewer_panel.py's `build_descriptors`
monkeypatch pattern (not the manual `p._descriptors =` override used in
test_ship_property_viewer_panel_emitter.py) because test_can_undo_in_payload
below calls `p.open()` a second time — open() rebuilds `_descriptors` from
`build_descriptors(ship)`, so only a monkeypatched `build_descriptors`
survives a second open().
"""
import json

import pytest

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

_DEFAULT_LIGHT_REGION = {
    "shape": "Sphere", "position": (0.0, 0.0, 0.0),
    "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
    "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
    "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}

_FAKE_DESCRIPTORS = [{
    "name": "Center Impulse", "kind": "subsystem",
    "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
    "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
    "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
    "emitters": [],
}]


@pytest.fixture
def spv_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: _FAKE_DESCRIPTORS)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    return p


def test_undo_restores_prior_radius(spv_panel):
    p = spv_panel
    # Select a subsystem and stage a radius edit via the public dispatch.
    p.dispatch_event("select_pin:0")
    assert 0 not in p._pending_radius
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    assert p._pending_radius[0] == 3.0
    assert p._undo_stack, "a real mutation records one undo entry"
    p.dispatch_event("undo")
    assert 0 not in p._pending_radius, "undo restored the pre-edit state"
    assert not p._undo_stack


def test_noop_dispatch_records_nothing(spv_panel):
    p = spv_panel
    p.dispatch_event("select_pin:0")     # selection is not an edit
    p.dispatch_event("scale_copy")       # clipboard only, no pending change
    assert not p._undo_stack


def test_can_undo_in_payload(spv_panel):
    p = spv_panel
    p.open()
    p.dispatch_event("select_pin:0")
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    js = p.render_payload()
    assert js is not None
    data = json.loads(js[js.index("(") + 1: js.rindex(")")])
    assert data["can_undo"] is True


def test_drag_records_one_undo_entry(spv_panel):
    p = spv_panel
    p.active_tool = "transform"
    p.dispatch_event("select_pin:0")
    p._begin_axis_drag(0, 0.0)          # press
    p._apply_axis_drag(0.5)             # move (stages a position edit)
    p._end_axis_drag()                  # release
    assert len(p._undo_stack) == 1


def test_save_clears_undo(spv_panel, monkeypatch):
    p = spv_panel
    p.dispatch_event("select_pin:0")
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')

    import engine.ui.ship_property_viewer_panel as mod

    class _Target:
        def write(self, leaf, edits):
            pass

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")

    p.dispatch_event("save")
    assert not p._undo_stack
