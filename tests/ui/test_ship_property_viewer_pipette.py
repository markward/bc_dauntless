"""SPV pipette eyedropper: arm on the selected target, the next element pick
is the source, and every aspect both sides support (position always;
rotation/scale/colour+intensity when kinds match) copies onto the target.

Fixture mirrors test_ship_property_viewer_undo.py's `build_descriptors`
monkeypatch pattern (not the manual `p._descriptors =` override) because
test_pipette_esc_disarms below calls `p.open()` a second time — open()
rebuilds `_descriptors` from `build_descriptors(ship)`, so only a
monkeypatched `build_descriptors` survives a second open().
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


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1: payload.rindex(")")])


# ----------------------------------------------------------------------
# Brief's core cases
# ----------------------------------------------------------------------

def test_pipette_requires_selection(spv_panel):
    p = spv_panel
    p.dispatch_event("deselect")
    p.dispatch_event("pipette")
    assert p._pipette_armed is False   # nothing selected → cannot arm


def test_pipette_copies_position_without_changing_selection(spv_panel):
    p = spv_panel
    # Two subsystems: give #1 a distinct position, select #0 as target.
    p.set_subsystem_position(1, (5.0, 0.0, 0.0))
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    assert p._pipette_armed is True
    p.dispatch_event("select_pin:1")   # #1 is the SOURCE
    assert p._pipette_armed is False
    assert p.selected_index == 0        # selection unchanged
    assert p._effective_pos(0) == (5.0, 0.0, 0.0)
    assert p._undo_stack               # one undo entry for the apply


def test_pipette_source_equals_target_is_noop(spv_panel):
    p = spv_panel
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    p.dispatch_event("select_pin:0")
    assert p._pipette_armed is False
    assert not p._undo_stack


# ----------------------------------------------------------------------
# Arming / cancellation edge cases
# ----------------------------------------------------------------------

def test_pipette_toggles_off_when_pressed_again_while_armed(spv_panel):
    p = spv_panel
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    assert p._pipette_armed is True
    p.dispatch_event("pipette")
    assert p._pipette_armed is False
    assert not p._undo_stack


def test_non_select_action_while_armed_disarms_and_falls_through(spv_panel):
    p = spv_panel
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    assert p._pipette_armed is True
    # A non-select action (toggling glow regions) disarms and still runs
    # normally instead of being swallowed by the interception.
    before = p.show_glow_regions
    p.dispatch_event("toggle_glow_regions")
    assert p._pipette_armed is False
    assert p.show_glow_regions is not before


def test_invalid_source_pick_disarms_without_applying(spv_panel):
    p = spv_panel
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    p.dispatch_event("select_pin:99")   # out of range → invalid pick
    assert p._pipette_armed is False
    assert not p._undo_stack
    assert p.selected_index == 0        # selection untouched (invalid pick)


# ----------------------------------------------------------------------
# Scale copy
# ----------------------------------------------------------------------

def test_pipette_copies_scale_on_matching_kind(spv_panel):
    p = spv_panel
    # both #0 and #1 are subsystems → scale kind "radius" matches
    p.dispatch_event('set_radius:{"i":1,"value":7.0}')
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    p.dispatch_event("select_pin:1")
    assert p._effective_radius(0, None) == 7.0


# ----------------------------------------------------------------------
# ESC disarm
# ----------------------------------------------------------------------

def test_pipette_esc_disarms(spv_panel):
    p = spv_panel
    p.open()
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    assert p._pipette_armed is True
    p.handle_key_esc()
    assert p._pipette_armed is False
    assert p.is_open()   # ESC only disarmed; did not close the panel


# ----------------------------------------------------------------------
# Rotation copy (matching kind) and skip (mismatched kind)
# ----------------------------------------------------------------------

def test_pipette_copies_rotation_axis_between_matching_strip_emitters(spv_panel):
    p = spv_panel
    # Rotate the source emitter (subsystem 1's strip) 90deg about +X.
    p.dispatch_event('select_emitter:' + json.dumps({"i": 1, "j": 0}))
    p.active_tool = "rotate"
    p._rotate_axis(0, 90.0)
    src_axis = p._effective_emitter(1, 0)["axis"]
    assert abs(src_axis[2] - (-1.0)) < 1e-6   # sanity: it moved

    # Target: subsystem 0's strip emitter, still at the default axis.
    p.dispatch_event('select_emitter:' + json.dumps({"i": 0, "j": 0}))
    p.dispatch_event("pipette")
    assert p._pipette_armed is True
    p.dispatch_event('select_emitter:' + json.dumps({"i": 1, "j": 0}))
    assert p._pipette_armed is False

    tgt_axis = p._effective_emitter(0, 0)["axis"]
    assert abs(tgt_axis[0] - src_axis[0]) < 1e-6
    assert abs(tgt_axis[1] - src_axis[1]) < 1e-6
    assert abs(tgt_axis[2] - src_axis[2]) < 1e-6


def test_pipette_skips_rotation_on_kind_mismatch_but_still_copies_position(spv_panel):
    p = spv_panel
    # Turn subsystem 1's emitter into a "point" emitter (not rotate-capable at
    # all) and give it a distinct position, so we can prove position still
    # copies while rotation (kind mismatch: None vs cylinder_axis) is skipped.
    p.dispatch_event('set_emitter:' + json.dumps({"i": 1, "j": 0, "kind": "point"}))
    p.set_emitter_position(1, 0, (9.0, 0.0, 0.0))

    p.dispatch_event('select_emitter:' + json.dumps({"i": 0, "j": 0}))
    before_axis = p._effective_emitter(0, 0)["axis"]
    p.dispatch_event("pipette")
    p.dispatch_event('select_emitter:' + json.dumps({"i": 1, "j": 0}))

    after = p._effective_emitter(0, 0)
    assert after["position"] == (9.0, 0.0, 0.0)   # position copied
    assert after["axis"] == before_axis           # rotation skipped (untouched)


# ----------------------------------------------------------------------
# Colour + intensity copy (emitter -> emitter only)
# ----------------------------------------------------------------------

def test_pipette_copies_color_and_intensity_between_emitters(spv_panel):
    p = spv_panel
    p.dispatch_event('set_emitter:' + json.dumps({
        "i": 1, "j": 0, "kind": "strip",
        "color": [0.2, 0.4, 0.9], "intensity": 5.5,
    }))
    p.dispatch_event('select_emitter:' + json.dumps({"i": 0, "j": 0}))
    p.dispatch_event("pipette")
    p.dispatch_event('select_emitter:' + json.dumps({"i": 1, "j": 0}))

    spec = p._effective_emitter(0, 0)
    assert spec["color"] == (0.2, 0.4, 0.9)
    assert spec["intensity"] == 5.5


def test_pipette_skips_color_when_source_is_not_an_emitter(spv_panel):
    p = spv_panel
    original = dict(p._effective_emitter(0, 0))
    p.dispatch_event('select_emitter:' + json.dumps({"i": 0, "j": 0}))
    p.dispatch_event("pipette")
    p.dispatch_event("select_pin:1")   # a subsystem, not an emitter

    spec = p._effective_emitter(0, 0)
    assert spec["color"] == original["color"]
    assert spec["intensity"] == original["intensity"]


# ----------------------------------------------------------------------
# Payload keys
# ----------------------------------------------------------------------

def test_undo_while_armed_disarms_pipette(spv_panel):
    p = spv_panel
    p.dispatch_event("select_pin:0")
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    assert p._pipette_armed is True
    p.dispatch_event("undo")            # non-select action while armed
    assert p._pipette_armed is False    # disarmed...
    assert 0 not in p._pending_radius   # ...AND the undo still happened


def test_undo_reverses_pipette_apply(spv_panel):
    p = spv_panel
    p.set_subsystem_position(1, (5.0, 0.0, 0.0))
    p.dispatch_event("select_pin:0")
    before = p._effective_pos(0)
    p.dispatch_event("pipette")
    p.dispatch_event("select_pin:1")   # #1 is the SOURCE, applies onto #0
    assert p._effective_pos(0) == (5.0, 0.0, 0.0)
    p.dispatch_event("undo")
    assert p._effective_pos(0) == before


def test_render_payload_reports_pipette_armed_and_has_selection(spv_panel):
    p = spv_panel
    data = _payload_data(p.render_payload())
    assert data["pipette_armed"] is False
    assert data["has_selection"] is False

    p.dispatch_event("select_pin:0")
    data = _payload_data(p.render_payload())
    assert data["has_selection"] is True

    p.dispatch_event("pipette")
    data = _payload_data(p.render_payload())
    assert data["pipette_armed"] is True
