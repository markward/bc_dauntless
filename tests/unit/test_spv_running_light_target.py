"""`RunningLightTarget` -- the running-light edit adapter (spec
docs/superpowers/specs/2026-10-22-spv-running-lights-design.md S3.2, S5):
Move, coord Copy/Paste against the "mount" kinds, Mirror Element (a new
named twin, its physical parent re-derived), the Pipette, the mount lock,
inert Rotate/Scale and the selected-light sphere.

Built on the Task 7 pane fixture (`make_panel`: one subsystem "Sub" at
(0.5, 1.0, -0.25), two baked lights "Port Nav" / "Star Nav")."""
import json

from engine.appc import running_light_dials
from engine.ui.ship_property_viewer_panel import SUBSYS_SPHERE_COLOR
from engine.ui.spv_edit_targets import RunningLightTarget
from tests.ui.test_spv_running_lights_pane import (  # noqa: F401 (fixture)
    _BOW, _PORT, _STAR, make_panel)

_SUB_POS = (0.5, 1.0, -0.25)


def _select(p, name):
    assert p.dispatch_event("rl/select:" + json.dumps({"name": name})) is True


def test_selected_light_has_running_light_adapter(make_panel):
    p = make_panel()
    _select(p, "Port Nav")
    t = p._edit_target()
    assert isinstance(t, RunningLightTarget)
    assert t.kind == "running_light"
    assert t.key == ("running_light", "Port Nav")
    assert t.coord_kind() == "mount"
    assert t.position() == _PORT["position"]


def test_move_stages_position(make_panel):
    p = make_panel()
    _select(p, "Port Nav")
    assert p.dispatch_event(
        'coord_nudge:{"axis": 0, "delta": 0.5}') is True
    assert p._pending_running_light["Port Nav"] == dict(
        _PORT, position=(-0.5, 0.5, 0.0))
    assert p.dispatch_event('coord_set:{"axis": 2, "value": 1.25}') is True
    assert p._rl_spec("Port Nav")["position"] == (-0.5, 0.5, 1.25)
    assert len(p._undo_stack) == 2
    # A gizmo axis drag, from the grab-time position.
    t = p._edit_target()
    origin, axes = t.gizmo_frame()
    assert origin == (-0.5, 0.5, 1.25)
    assert len(axes) == 3
    t.axis_drag_begin(1, 10.0)
    t.axis_drag_apply(10.75)
    assert p._rl_spec("Port Nav")["position"] == (-0.5, 1.25, 1.25)
    # The look and the other light are untouched.
    assert p._rl_spec("Port Nav")["color"] == _PORT["color"]
    assert p._rl_spec("Star Nav") == _STAR


def test_coord_paste_between_light_and_subsystem(make_panel):
    p = make_panel()
    assert p.dispatch_event("select_pin:0") is True
    assert p.dispatch_event("coord_copy") is True
    _select(p, "Star Nav")
    assert p.dispatch_event("coord_paste") is True
    assert p._rl_spec("Star Nav")["position"] == _SUB_POS
    # ...and back: a light's coordinate pastes onto a subsystem.
    _select(p, "Port Nav")
    assert p.dispatch_event("coord_copy") is True
    assert p.dispatch_event("select_pin:0") is True
    assert p.dispatch_event("coord_paste") is True
    assert p._effective_pos(0) == _PORT["position"]


def test_coord_mirror_hidden_and_inert(make_panel):
    p = make_panel()
    _select(p, "Port Nav")
    t = p._edit_target()
    assert t.payload_extras("coord") == {"can_mirror": False}
    assert p.dispatch_event("coord_mirror") is True
    assert p._pending_running_light == {}


def test_mirror_creates_named_twin_and_selects_it(make_panel):
    p = make_panel(lights=(_PORT,))
    _select(p, "Port Nav")
    p._undo_stack.clear()
    assert p.dispatch_event("mirror_element") is True
    assert p._rl_selected == "Star Nav"
    assert p._rl_spec("Star Nav") == dict(
        _PORT, name="Star Nav", position=(1.0, 0.5, 0.0))
    assert p._rl_spec("Port Nav") == _PORT
    assert p._pending_physical == {}
    # One dispatch, one undo step: Undo removes the twin.
    assert len(p._undo_stack) == 1
    assert p.dispatch_event("undo") is True
    assert p._rl_spec("Star Nav") is None


def test_mirror_twin_name_avoids_taken_names(make_panel):
    p = make_panel()                        # "Star Nav" already exists
    _select(p, "Port Nav")
    assert p.dispatch_event("mirror_element") is True
    new = p._rl_selected
    assert new not in ("Port Nav", "Star Nav")
    assert p._rl_spec(new)["position"] == (1.0, 0.5, 0.0)
    assert p._rl_spec("Star Nav") == _STAR


def test_mirror_derives_parent_when_source_explicit(make_panel):
    p = make_panel(lights=(_PORT,))
    p._physical_lights[0]["physical_parent"] = "left wing"   # baked
    seen = []

    def _auto(point):
        seen.append(tuple(point))
        return "right wing"
    p._physical_auto_part = _auto
    _select(p, "Port Nav")
    assert p.dispatch_event("mirror_element") is True
    assert seen == [(1.0, 0.5, 0.0)]
    assert p._pending_physical == {"Star Nav": "right wing"}


def test_mirror_derives_parent_from_pending_source(make_panel):
    p = make_panel(lights=(_PORT,))
    p._pending_physical["Port Nav"] = "left wing"
    p._physical_auto_part = lambda point: "right wing"
    _select(p, "Port Nav")
    assert p.dispatch_event("mirror_element") is True
    assert p._pending_physical["Star Nav"] == "right wing"


def test_mirror_leaves_auto_when_derivation_finds_no_part(make_panel):
    p = make_panel(lights=(_PORT,))
    p._physical_lights[0]["physical_parent"] = "left wing"
    p._physical_auto_part = lambda point: None   # unrigged
    _select(p, "Port Nav")
    assert p.dispatch_event("mirror_element") is True
    assert "Star Nav" not in p._pending_physical


def test_mirror_leaves_auto_when_source_auto(make_panel):
    p = make_panel(lights=(_PORT,))
    p._physical_auto_part = lambda point: "right wing"
    _select(p, "Port Nav")
    assert p.dispatch_event("mirror_element") is True
    assert p._rl_selected == "Star Nav"
    assert p._pending_physical == {}


def test_pipette_light_to_light_copies_look_and_position(make_panel):
    p = make_panel(lights=(_PORT, _BOW))
    _select(p, "Port Nav")
    assert p.dispatch_event("pipette") is True
    assert p._pipette_armed is True
    assert p.dispatch_event('rl/select:{"name": "Bow Nav"}') is True
    assert p._pipette_armed is False
    assert p._rl_selected == "Port Nav"            # selection unchanged
    assert p._rl_spec("Port Nav") == dict(_BOW, name="Port Nav")
    assert p._rl_spec("Bow Nav") == _BOW
    assert len(p._undo_stack) == 1


def test_pipette_light_to_subsystem_copies_position_only(make_panel):
    p = make_panel()
    assert p.dispatch_event("select_pin:0") is True
    radius = p._edit_target().get_scale()
    assert p.dispatch_event("pipette") is True
    assert p.dispatch_event('rl/select:{"name": "Port Nav"}') is True
    assert p._pipette_armed is False
    assert p.selected_index == 0
    assert p._rl_selected is None
    assert p._effective_pos(0) == _PORT["position"]
    assert p._edit_target().get_scale() == radius


def test_pipette_subsystem_to_light_copies_position_only(make_panel):
    p = make_panel()
    _select(p, "Star Nav")
    assert p.dispatch_event("pipette") is True
    assert p.dispatch_event("select_pin:0") is True
    assert p._rl_selected == "Star Nav"
    assert p._rl_spec("Star Nav") == dict(_STAR, position=_SUB_POS)


def test_pipette_light_to_emitter_copies_position_only(make_panel):
    """An emitter carries a colour too, but a light's look is not an
    emitter's (color, intensity): only the position crosses."""
    p = make_panel()
    t = RunningLightTarget(p, ("running_light", "Port Nav"))

    class _EmitterLike:
        kind = "emitter"

        def colour(self):
            return ((1.0, 1.0, 1.0), 1.0)

        def position(self):
            return (0.0, 0.0, 0.0)
    assert t.pipette_fields_from(_EmitterLike()) == ("position",)
    from engine.ui.spv_edit_targets import EmitterTarget
    e = EmitterTarget(p, ("emitter", 0, 0))
    assert e.pipette_fields_from(t) == ("position",)


def test_locked_refuses_rl_actions(make_panel):
    p = make_panel()
    _select(p, "Port Nav")
    p._mount_editing_enabled = lambda: False
    t = p._edit_target()
    assert t.locked is True
    assert p.dispatch_event('rl/select:{"name": "Star Nav"}') is False
    assert p._rl_selected == "Port Nav"
    for action in ('rl/place_begin:' + json.dumps(_BOW),
                   'rl/edit:' + json.dumps({"name": "Port Nav",
                                            "spec": _PORT}),
                   'rl/remove:{"name": "Port Nav"}',
                   'coord_nudge:{"axis": 0, "delta": 0.5}',
                   "mirror_element", "pipette"):
        assert p.dispatch_event(action) is False, action
    assert p._pending_running_light == {}
    assert p._pipette_armed is False


def test_rotate_and_scale_inert(make_panel):
    p = make_panel()
    _select(p, "Port Nav")
    t = p._edit_target()
    assert t.rotate_kind() is None and t.rotate_spec() is None
    assert t.scale_kind() is None and t.scale_spec() is None
    assert p._rotate_edit_target() is None
    assert p._scale_edit_target() is None
    p.dispatch_event('rotate_nudge:{"index": 0, "delta": 15.0}')
    p.dispatch_event('scale_nudge:{"index": 0, "delta": 0.5}')
    p.dispatch_event("rotate_mirror")
    assert p._pending_running_light == {}


def test_look_round_trip_never_touches_name_or_position(make_panel):
    p = make_panel(lights=(_PORT, _BOW))
    t = RunningLightTarget(p, ("running_light", "Port Nav"))
    assert t.colour() == _PORT
    t.set_colour(_BOW)
    assert p._rl_spec("Port Nav") == dict(
        _BOW, name="Port Nav", position=_PORT["position"])
    t.set_colour(None)                       # a vanished source: no-op
    assert p._rl_spec("Port Nav")["color"] == _BOW["color"]


def test_selected_light_shows_selection_sphere(make_panel):
    p = make_panel(lights=(_PORT, _BOW))
    assert p.selected_subsystem_sphere() is None
    size = running_light_dials.current()["size_gu_per_radius"]
    _select(p, "Bow Nav")
    sph = p.selected_subsystem_sphere()
    assert sph["center"] == _BOW["position"]
    assert sph["radius"] == max(3.0 * size * _BOW["radius"], 0.05)
    assert sph["color"] == SUBSYS_SPHERE_COLOR
    # A tiny light still gets a visible sphere.
    _select(p, "Port Nav")
    assert p.selected_subsystem_sphere()["radius"] == max(
        3.0 * size * _PORT["radius"], 0.05)
    # A subsystem keeps its own sphere.
    assert p.dispatch_event("select_pin:0") is True
    assert p.selected_subsystem_sphere()["radius"] == 0.3
