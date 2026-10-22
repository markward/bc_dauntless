"""SPV running lights: the Add / place / edit / remove flow (spec
docs/superpowers/specs/2026-10-22-spv-running-lights-design.md S2, S3.3,
S3.4).

`rl/place_begin` validates a spec and arms placing; the next viewport click
(`pick_at` -> `_rl_click`) traces the hull through the Decals pane's
`_decal_hull_hit` (mocked here), converts the NIF-unit body hit to unscaled
GU, lifts it off the hull along the normal, stages and selects the light.
`rl/edit` restages a light under its fixed name; `rl/remove` stages a
removal (or drops a pending-only add). Esc cancels placing before it closes
the panel.

Built on the Task 7 pane fixture (`make_panel`: one subsystem "Sub", two
baked lights "Port Nav" / "Star Nav")."""
import json
import math

import pytest

from engine.appc import running_light_dials
from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui import running_light_editor as rle
from engine.ui import spv_decals_pane
from engine.ui import spv_running_lights_pane as rl_mod
from engine.ui.ship_property_viewer import world_from_body
from tests.ui.test_spv_running_lights_pane import (  # noqa: F401 (fixture)
    _BOW, _PORT, _STAR, _payload, make_panel)

_VIEWPORT = (0, 0, 800, 600)
_NEW = {"name": "Dorsal Nav", "position": (0.0, 0.0, 0.0),
        "color": (0.0, 0.5, 1.0), "radius": 1.5, "period": 2.0,
        "duration": 0.25}
_HIT_PB = (10.0, -4.0, 6.0)          # NIF units, body frame
_HIT_NB = (0.0, 0.0, 1.0)
_SCALE = 0.5


@pytest.fixture
def hull(monkeypatch):
    """Mocks the hull trace and the instance scale. `hull.hit` is what the
    next `_decal_hull_hit` returns (None = a miss)."""
    class _Hull:
        hit = (_HIT_PB, _HIT_NB, None)
    h = _Hull()
    monkeypatch.setattr(rl_mod, "instance_scale", lambda ship: _SCALE)

    def _attach(p):
        p._decal_hull_hit = lambda x, y, viewport: h.hit
        return p
    h.attach = _attach
    return h


def _begin(p, spec=_NEW):
    return p.dispatch_event("rl/place_begin:" + json.dumps(spec))


def _click(p):
    p.pick_at(100.0, 100.0, _VIEWPORT)


def _lift(radius):
    return running_light_dials.current()["size_gu_per_radius"] * radius


def test_place_begin_then_click_stages_and_selects(make_panel, hull):
    p = hull.attach(make_panel())
    p.dispatch_event('rl/select:{"name": "Port Nav"}')
    p._undo_stack.clear()
    assert _begin(p) is True
    assert p._rl_placing["name"] == "Dorsal Nav"
    assert p._rl_error is None
    assert p._undo_stack == []          # placing is not an edit
    assert p._pending_running_light == {}
    _click(p)
    assert p._rl_placing is None
    assert p._rl_selected == "Dorsal Nav"
    staged = p._pending_running_light["Dorsal Nav"]
    for k in ("color", "radius", "period", "duration"):
        assert staged[k] == pytest.approx(rle.validate_spec(_NEW, set())[k])
    assert len(p._undo_stack) == 1


def test_place_position_converts_nif_to_gu_with_lift(make_panel, hull):
    p = hull.attach(make_panel())
    ship = p._ship_getter()
    rot = TGMatrix3()
    rot.MakeZRotation(math.radians(90.0))
    ship.GetWorldLocation = lambda: TGPoint3(100.0, -20.0, 5.0)
    ship.GetWorldRotation = lambda: rot
    assert _begin(p) is True
    _click(p)
    pos = p._pending_running_light["Dorsal Nav"]["position"]
    lift = _lift(_NEW["radius"])
    expect = tuple(_HIT_PB[k] * _SCALE + _HIT_NB[k] * lift for k in range(3))
    assert pos == pytest.approx(expect)
    # The frame: the light's world point is the hit's world point plus the
    # lift along the hit's world normal.
    hit_world = world_from_body(ship, tuple(c * _SCALE for c in _HIT_PB))
    n = TGPoint3(*_HIT_NB)
    n.MultMatrixLeft(rot)
    want = (hit_world[0] + n.x * lift, hit_world[1] + n.y * lift,
            hit_world[2] + n.z * lift)
    assert world_from_body(ship, pos) == pytest.approx(want)


def test_click_miss_keeps_placing_with_hint(make_panel, hull):
    p = hull.attach(make_panel())
    assert _begin(p) is True
    hull.hit = None
    _click(p)
    assert p._rl_placing is not None
    assert p._rl_error == spv_decals_pane.MISS_HINT
    assert p._pending_running_light == {}
    assert p._undo_stack == []
    hull.hit = (_HIT_PB, _HIT_NB, None)
    _click(p)
    assert p._rl_placing is None
    assert p._rl_error is None
    assert "Dorsal Nav" in p._pending_running_light


def test_click_without_placing_falls_through(make_panel, hull):
    p = hull.attach(make_panel())
    assert p._rl_click(1.0, 1.0, _VIEWPORT) is False


def test_esc_cancels_placing_before_closing_panel(make_panel, hull):
    p = hull.attach(make_panel())
    assert _begin(p) is True
    p.handle_key_esc()
    assert p._rl_placing is None
    assert p._visible is True
    p.handle_key_esc()
    assert p._visible is False


def test_place_cancel_clears_placing_and_error(make_panel, hull):
    p = hull.attach(make_panel())
    assert _begin(p) is True
    p._rl_error = "stale"
    assert p.dispatch_event("rl/place_cancel") is True
    assert p._rl_placing is None
    assert p._rl_error is None


def test_place_begin_refuses_taken_name(make_panel):
    p = make_panel()
    for taken in ("Port Nav", "Sub"):
        assert _begin(p, dict(_NEW, name=taken)) is False
        assert p._rl_placing is None
        assert taken in p._rl_error
    # A model part name shares the FindByName namespace too.
    p._model_part_nodes = [{"name": "Hull"}]
    assert _begin(p, dict(_NEW, name="Hull")) is False
    assert "Hull" in p._rl_error
    # A valid begin clears the error.
    assert _begin(p) is True
    assert p._rl_error is None


def test_place_begin_refuses_invalid_timing(make_panel):
    p = make_panel()
    assert _begin(p, dict(_NEW, period=4.0, duration=5.0)) is False
    assert p._rl_placing is None
    assert "Duration" in p._rl_error


def test_place_begin_refuses_malformed_spec(make_panel):
    p = make_panel()
    bad = dict(_NEW)
    del bad["radius"]
    assert _begin(p, bad) is False
    assert p._rl_placing is None
    assert "radius" in p._rl_error
    for raw in ("rl/place_begin:{not json", "rl/place_begin:[1, 2]",
                'rl/place_begin:' + json.dumps(dict(_NEW, color=5))):
        p._rl_error = None
        assert p.dispatch_event(raw) is False, raw
        assert p._rl_error, raw
    assert p._rl_placing is None


def test_place_begin_position_is_optional(make_panel):
    p = make_panel()
    spec = dict(_NEW)
    del spec["position"]
    assert _begin(p, spec) is True


def test_edit_keeps_name_and_restages(make_panel):
    p = make_panel()
    new = dict(_PORT, name="Renamed", color=(0.0, 0.0, 1.0),
               position=(-2.0, 0.5, 0.0))
    assert p.dispatch_event("rl/edit:" + json.dumps(
        {"name": "Port Nav", "spec": new})) is True
    staged = p._pending_running_light["Port Nav"]
    assert staged["name"] == "Port Nav"
    assert staged["color"] == (0.0, 0.0, 1.0)
    assert staged["position"] == (-2.0, 0.5, 0.0)
    assert "Renamed" not in p._pending_running_light
    assert len(p._undo_stack) == 1


def test_edit_refuses_invalid_and_unknown(make_panel):
    p = make_panel()
    assert p.dispatch_event("rl/edit:" + json.dumps(
        {"name": "Port Nav", "spec": dict(_PORT, radius=99.0)})) is False
    assert "Radius" in p._rl_error
    assert p.dispatch_event("rl/edit:" + json.dumps(
        {"name": "Nope", "spec": _PORT})) is False
    bad = dict(_PORT)
    del bad["color"]
    assert p.dispatch_event("rl/edit:" + json.dumps(
        {"name": "Port Nav", "spec": bad})) is False
    assert "color" in p._rl_error
    assert p.dispatch_event('rl/edit:{"name": "Port Nav"}') is False
    assert p._pending_running_light == {}
    assert p._undo_stack == []


def test_remove_pending_add_drops_it(make_panel, hull):
    p = hull.attach(make_panel())
    assert _begin(p) is True
    _click(p)
    p._pending_physical["Dorsal Nav"] = "nacelle"
    assert p.dispatch_event('rl/remove:{"name": "Dorsal Nav"}') is True
    assert "Dorsal Nav" not in p._pending_running_light
    assert "Dorsal Nav" not in p._pending_physical
    assert p._rl_selected is None


def test_remove_baked_stages_none(make_panel):
    p = make_panel()
    p.dispatch_event('rl/select:{"name": "Port Nav"}')
    assert p.dispatch_event('rl/remove:{"name": "Port Nav"}') is True
    assert p._pending_running_light == {"Port Nav": None}
    assert p._rl_selected is None
    assert p.dispatch_event('rl/remove:{"name": "Nope"}') is False
    assert p.dispatch_event("rl/remove:{bad") is False


def test_remove_other_light_keeps_selection(make_panel):
    p = make_panel()
    p.dispatch_event('rl/select:{"name": "Port Nav"}')
    assert p.dispatch_event('rl/remove:{"name": "Star Nav"}') is True
    assert p._rl_selected == "Port Nav"


def test_undo_removes_placed_light(make_panel, hull):
    p = hull.attach(make_panel())
    assert _begin(p) is True
    _click(p)
    assert "Dorsal Nav" in p._pending_running_light
    p.dispatch_event("undo")
    assert "Dorsal Nav" not in p._pending_running_light
    assert p._rl_spec("Dorsal Nav") is None
    assert p._rl_selected is None
    # Undo of an edit restores the previous colour and position.
    assert p.dispatch_event("rl/edit:" + json.dumps(
        {"name": "Port Nav", "spec": dict(_PORT, color=(0.0, 0.0, 1.0),
                                          position=(-3.0, 0.0, 0.0))})) is True
    p.dispatch_event("undo")
    spec = p._rl_spec("Port Nav")
    assert spec["color"] == _PORT["color"]
    assert spec["position"] == _PORT["position"]


def test_click_on_part_mesh_stages_physical_parent(make_panel, hull):
    p = hull.attach(make_panel())
    hull.hit = (_HIT_PB, _HIT_NB, 3)
    p._decal_shape_of_mesh = lambda mesh: "nacelle_geom" if mesh == 3 else ""
    p._decal_meshes = lambda iid: [
        {"mesh": 2, "name": "hull_geom", "node_chain": ["Scene Root"]},
        {"mesh": 3, "name": "nacelle_geom",
         "node_chain": ["Scene Root", "pylon", "nacelle", "nacelle_geom"]}]
    p._decal_part_names = lambda ship: {"pylon", "nacelle"}
    assert _begin(p) is True
    _click(p)
    assert p._pending_physical == {"Dorsal Nav": "nacelle"}
    p.dispatch_event("undo")
    assert p._pending_physical == {}


def test_click_on_unrigged_stages_no_parent(make_panel, hull):
    p = hull.attach(make_panel())
    hull.hit = (_HIT_PB, _HIT_NB, 2)
    p._decal_shape_of_mesh = lambda mesh: ""
    assert _begin(p) is True
    _click(p)
    assert "Dorsal Nav" in p._pending_running_light
    assert p._pending_physical == {}


def test_click_refused_while_mount_editing_locked(make_panel, hull):
    p = hull.attach(make_panel())
    assert _begin(p) is True
    p._mount_editing_enabled = lambda: False
    _click(p)
    assert p._pending_running_light == {}
    assert p._rl_placing is not None
    assert p._rl_error


def test_locked_refuses_place_edit_remove(make_panel):
    """Each verb succeeds unlocked (so the refusal below is the lock, not an
    unknown verb) and is refused while mount editing is disabled."""
    actions = ("rl/place_begin:" + json.dumps(_NEW),
               "rl/edit:" + json.dumps({"name": "Port Nav",
                                        "spec": dict(_PORT, radius=1.0)}),
               'rl/remove:{"name": "Star Nav"}')
    p = make_panel()
    for action in actions:
        assert p.dispatch_event(action) is True, action
    p = make_panel()
    p._mount_editing_enabled = lambda: False
    for action in actions:
        assert p.dispatch_event(action) is False, action
    assert p._pending_running_light == {}
    assert p._rl_placing is None


def test_payload_running_lights_block(make_panel):
    p = make_panel()
    block = _payload(p)["running_lights"]
    assert block == {
        "placing": None, "error": None, "hint": None,
        "next_name": "Running Light 1",
        "defaults": {"color": list(rle.DEFAULT_COLOR),
                     "radius": rle.DEFAULT_RADIUS,
                     "period": rle.DEFAULT_PERIOD,
                     "duration": rle.DEFAULT_DURATION},
        "ranges": {"radius": list(rle.RADIUS_RANGE),
                   "period": list(rle.PERIOD_RANGE),
                   "duration_min": rle.DURATION_MIN},
    }
    assert _begin(p, dict(_NEW, name="Running Light 1")) is True
    block = _payload(p)["running_lights"]
    assert block["placing"] == "Running Light 1"
    assert block["hint"] == ("Click the hull to place Running Light 1"
                             " · Esc cancels")
    assert _begin(p, dict(_NEW, name="Port Nav")) is False
    block = _payload(p)["running_lights"]
    assert "Port Nav" in block["error"]


def test_payload_repushes_on_placing_change(make_panel):
    p = make_panel()
    p.render_payload()
    assert p.render_payload() is None
    assert _begin(p) is True
    assert p.render_payload() is not None


def _with_templates(p, *props):
    """Attach non-subsystem templates to the viewed ship's property set and
    reopen, as a real ship carries them from `LoadPropertySet`."""
    pset = p._ship_getter().GetPropertySet()
    for prop in props:
        pset.AddToSet("Scene Root", prop)
    p.open()
    return p


def test_place_begin_refuses_non_subsystem_template_names(make_panel):
    """Every template shares one `FindByName` namespace: a light named
    after the Galaxy's "Shuttle Bay" object emitter (or its ship property,
    or a position/orientation) would replace that template on Save."""
    import App
    p = _with_templates(make_panel(),
                        App.ObjectEmitterProperty_Create("Shuttle Bay"),
                        App.ShipProperty_Create("Galaxy"),
                        App.PositionOrientationProperty_Create(
                            "ViewscreenForward"))
    for taken in ("Shuttle Bay", "Galaxy", "ViewscreenForward"):
        assert _begin(p, dict(_NEW, name=taken)) is False, taken
        assert p._rl_placing is None
        assert taken in p._rl_error
    assert _begin(p) is True


def test_removed_light_name_is_free_again(make_panel):
    """A baked light staged for removal is still in the property set, but
    its name is free: the property-set names never shadow the lights."""
    p = make_panel()
    assert p.dispatch_event('rl/remove:{"name": "Port Nav"}') is True
    assert _begin(p, dict(_NEW, name="Port Nav")) is True


@pytest.mark.parametrize("action", [
    "select_pin:0",                       # another row
    'rl/select:{"name": "Star Nav"}',     # a light row
    'rl/select:{"name": "Port Nav"}',     # the row already selected
    "set_tool:transform",                 # a tool switch
    "deselect",                           # an empty-space click
])
def test_other_selection_or_tool_cancels_placing(make_panel, hull, action):
    """Placing must not stay armed behind another selection or tool: the
    next viewport click would place a light nobody asked for."""
    p = hull.attach(make_panel())
    p.dispatch_event('rl/select:{"name": "Port Nav"}')
    assert _begin(p) is True
    assert p.dispatch_event(action) is True
    assert p._rl_placing is None
    assert _payload(p)["running_lights"]["placing"] is None
    # The next viewport click falls through to the pin pick.
    assert p._rl_click(100.0, 100.0, _VIEWPORT) is False
    assert "Dorsal Nav" not in p._pending_running_light


def test_overlay_and_view_toggles_keep_placing(make_panel, hull):
    """The Add modal closes (overlay:0) right after rl/place_begin, and a
    view toggle selects nothing: placing survives both."""
    p = hull.attach(make_panel())
    assert _begin(p) is True
    assert p.dispatch_event("overlay:0") is True
    assert p.dispatch_event("toggle_glow_regions") is True
    assert p._rl_placing is not None
    _click(p)
    assert "Dorsal Nav" in p._pending_running_light


def test_placed_light_opens_a_collapsed_group(make_panel, hull):
    """The new light is selected: it must not hide in a collapsed group."""
    p = hull.attach(make_panel())
    assert p._rl_group_expanded is False
    assert _begin(p) is True
    _click(p)
    assert p._rl_group_expanded is True
    group = [r for r in _payload(p)["subsystems"]
             if r.get("kind") == "rl_group"][0]
    assert group["expanded"] is True


def _remove(p, name):
    return p.dispatch_event("rl/remove:" + json.dumps({"name": name}))


def test_remove_light_with_baked_parent_unsets_it(make_panel):
    """A light saved earlier with an explicit parent keeps its
    SetPhysicalParent find-block unless the removal resets it: a later
    light of the same name would inherit the parent."""
    p = make_panel()
    p._physical_lights[0]["physical_parent"] = "left wing"     # baked
    p._undo_stack.clear()
    assert _remove(p, "Port Nav") is True
    assert p._pending_physical == {"Port Nav": None}
    assert p._pending_running_light == {"Port Nav": None}
    # One action, one undo step, restoring both.
    assert len(p._undo_stack) == 1
    assert p.dispatch_event("undo") is True
    assert p._pending_physical == {}
    assert p._pending_running_light == {}
    # Save emits the reset alongside the removal.
    assert _remove(p, "Port Nav") is True
    assert p.dispatch_event("save") is True
    _leaf, edits = make_panel.target.calls[-1]
    assert ("Port Nav", "__unset__", "SetPhysicalParent") in edits
    assert ("Port Nav", "__running_light__",
            {"spec": None, "new": False}) in edits


def test_remove_light_with_saved_parent_unsets_it(make_panel):
    p = make_panel()
    p._saved_physical["Star Nav"] = "right wing"     # saved this session
    assert _remove(p, "Star Nav") is True
    assert p._pending_physical == {"Star Nav": None}


def test_remove_light_without_committed_parent_stages_no_reset(make_panel):
    """Auto (no saved or baked parent): nothing in the file to reset; a
    merely staged parent is dropped."""
    p = make_panel()
    p._pending_physical["Port Nav"] = "left wing"    # staged, never saved
    assert _remove(p, "Port Nav") is True
    assert "Port Nav" not in p._pending_physical
    assert _remove(p, "Star Nav") is True
    assert "Star Nav" not in p._pending_physical
