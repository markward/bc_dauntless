"""Decal Copy/Paste and Mirror in the Ship Property Viewer (spec
docs/superpowers/specs/2026-09-29-spv-edit-target-refactor-design.md S5;
plan Task 6): decals are an `EditTarget` (`DecalTarget`) with clipboard kind
"decal" for Move, Rotate and Scale, and the action-row Mirror creates a new
`<mask>_N` placement reflected across the ship's centreline.
"""
import math

import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui import decal_editor
from engine.ui.decal_editor import centre, chirality_ok, mask_of
from engine.ui.ship_property_viewer import OrbitCamera
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from engine.ui.spv_decals_pane import BODY_FORWARD as FWD, BODY_UP as UP

UNRIGGED_LEAF = "spvdecalclipboardtest"
_ASPECT = {"pylon": 2.0, "wide": 4.0}


def _region(**kw):
    r = {"position": (0.0, 0.0, 0.0), "axis": (0.0, -1.0, 0.0),
         "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
         "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), "shape": "Sphere"}
    r.update(kw)
    return r


_DESCRIPTORS = [{
    "name": "SphereLight", "kind": "subsystem", "icon_id": 1,
    "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.4},
    "world_pos": (0.0, 0.0, 0.0), "parent_index": None, "light": True,
    "light_region": _region(position=(0.2, -0.4, 0.1), radius=(0.35,)),
    "emitters": [],
}]


def _placement(name, origin, u, v, n=(0.0, 0.0, 1.0), mask="", depth=2.0):
    return decal_editor.Placement(name=name, origin=origin, u_axis=u,
                                  v_axis=v, normal=n, depth=depth,
                                  shape="amb saucer:0", mask=mask)


# Chirality-OK ((u x v) . n < 0) placements, off the centreline.
_PYLON = _placement("pylon", (10.0, 30.0, 50.0), (40.0, 0.0, 0.0),
                    (0.0, -20.0, 0.0))
_PYLON_2 = decal_editor.roll(
    _placement("pylon_2", (-70.0, -10.0, 40.0), (20.0, 0.0, 0.0),
               (0.0, -10.0, 0.0), mask="pylon", depth=3.5), math.radians(25.0))
_WIDE = _placement("wide", (-60.0, 5.0, 40.0), (30.0, 0.0, 0.0),
                   (0.0, -15.0, 0.0))
# Centred on X = 0: its mirror lands on itself.
_CENTRELINE = _placement("keel", (-20.0, 0.0, -30.0), (40.0, 0.0, 0.0),
                         (0.0, 20.0, 0.0), n=(0.0, 0.0, -1.0))


class _FakeSubsystem:
    def GetPosition(self):
        return (0.0, 0.0, 0.0)

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0


class _Ship:
    def __init__(self):
        self._hull = _FakeSubsystem()
        self._articulation_leaf = UNRIGGED_LEAF
        self._articulation_poses = {}

    def GetHull(self):
        return self._hull

    def GetSensorSubsystem(self):
        return self._hull

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()


@pytest.fixture
def make_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(d, properties=dict(d["properties"]))
                      for d in _DESCRIPTORS])
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda s: UNRIGGED_LEAF)

    def _make(placements):
        ship = _Ship()
        p = ShipPropertyViewerPanel(ship_getter=lambda: ship)
        p.open()
        p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
        assert p.dispatch_event("decal-pane") is True
        p._decal_working = list(placements)
        p._decal_baseline = list(placements)
        p._decal_aspect = lambda mask: _ASPECT.get(mask, 2.0)
        p._undo_stack.clear()
        return p
    return _make


@pytest.fixture
def pane_with_two_decals(make_panel):
    return make_panel([_PYLON, _PYLON_2])


def _use_tool(p, tool):
    if p.active_tool != tool:
        assert p.dispatch_event("set_tool:" + tool) is True


def _select(p, name, tool="transform"):
    assert p.dispatch_event("decal-select:" + name) is True
    _use_tool(p, tool)


def _mag(v):
    return math.sqrt(sum(c * c for c in v))


# ── Copy / Paste ─────────────────────────────────────────────────────────────

def test_decal_coord_copy_paste_moves_centre(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon")
    p.dispatch_event("coord_copy")
    assert p._coord_clipboard[0] == "decal"
    _select(p, "pylon_2")
    assert p.transform_coords()["can_paste"] is True
    before = p._decal_by_name("pylon_2")
    p.dispatch_event("coord_paste")
    after = p._decal_by_name("pylon_2")
    assert centre(after) == pytest.approx(centre(p._decal_by_name("pylon")))
    # Only the centre moves: axes, normal and depth are the target's own.
    assert (after.u_axis, after.v_axis, after.normal, after.depth) == (
        before.u_axis, before.v_axis, before.normal, before.depth)


def test_decal_scale_paste_is_aspect_locked(make_panel):
    p = make_panel([_PYLON, _WIDE])            # pylon 2:1, wide 4:1
    _select(p, "pylon", "scale")
    p.dispatch_event("scale_copy")
    assert p._scale_clipboard == ("decal", (40.0, 2.0))
    _select(p, "wide", "scale")
    assert p.scale_values()["can_paste"] is True
    c0 = centre(p._decal_by_name("wide"))
    p.dispatch_event("scale_paste")
    w = p._decal_by_name("wide")
    assert decal_editor.width(w) == pytest.approx(40.0)
    assert _mag(w.u_axis) / _mag(w.v_axis) == pytest.approx(4.0)
    assert w.depth == pytest.approx(2.0)
    assert centre(w) == pytest.approx(c0)


def test_decal_rotate_paste_copies_roll(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon_2", "rotate")
    p.dispatch_event("rotate_copy")
    assert p._rotate_clipboard[0] == "decal"
    _select(p, "pylon", "rotate")
    assert p.rotate_values()["can_paste"] is True
    p.dispatch_event("rotate_paste")
    src, dst = p._decal_by_name("pylon_2"), p._decal_by_name("pylon")
    assert decal_editor.roll_angle(dst, FWD, UP) == pytest.approx(
        decal_editor.roll_angle(src, FWD, UP))
    assert centre(dst) == pytest.approx(centre(_PYLON))


@pytest.mark.parametrize("verb,tool", [("coord", "transform"),
                                       ("scale", "scale"),
                                       ("rotate", "rotate")])
def test_decal_paste_refused_onto_light_and_vice_versa(make_panel, verb, tool):
    p = make_panel([_PYLON])
    # decal -> light
    _select(p, "pylon", tool)
    p.dispatch_event(verb + "_copy")
    assert p.dispatch_event("select_light:0") is True
    _use_tool(p, tool)
    light_before = p._effective_light(0)
    payload = {"transform": p.transform_coords, "scale": p.scale_values,
               "rotate": p.rotate_values}[tool]()
    assert payload is None or payload["can_paste"] is False
    p.dispatch_event(verb + "_paste")
    assert p._effective_light(0) == light_before
    # light -> decal (a Sphere light has no rotation: a stale decal
    # clipboard must still not paste back as a light's value)
    p.dispatch_event(verb + "_copy")
    _select(p, "pylon", tool)
    clip = {"coord": p._coord_clipboard, "scale": p._scale_clipboard,
            "rotate": p._rotate_clipboard}[verb]
    if clip is not None and clip[0] != "decal":
        payload = {"transform": p.transform_coords, "scale": p.scale_values,
                   "rotate": p.rotate_values}[tool]()
        assert payload["can_paste"] is False
    p.dispatch_event(verb + "_paste")
    assert p._decal_by_name("pylon") == _PYLON


def test_a_light_coord_clipboard_is_refused_by_a_decal(make_panel):
    p = make_panel([_PYLON])
    assert p.dispatch_event("select_light:0") is True
    _use_tool(p, "transform")
    p.dispatch_event("coord_copy")
    assert p._coord_clipboard[0] == "mount"
    _select(p, "pylon")
    assert p.transform_coords()["can_paste"] is False
    p.dispatch_event("coord_paste")
    assert p._decal_by_name("pylon") == _PYLON


# ── Mirror ───────────────────────────────────────────────────────────────────

def test_decal_mirror_creates_readable_copy_sharing_mask(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon")
    p.dispatch_event("mirror_element")
    new = p._decal_by_name("pylon_3")
    src = p._decal_by_name("pylon")
    assert src == _PYLON
    assert mask_of(new) == "pylon" and chirality_ok(new)
    assert new.shape == src.shape and new.depth == src.depth
    cs, cn = centre(src), centre(new)
    assert cn == pytest.approx((-cs[0], cs[1], cs[2]))
    assert new.normal == pytest.approx((-src.normal[0],) + src.normal[1:])
    assert decal_editor.width(new) == pytest.approx(decal_editor.width(src))
    assert p._decal_selected == "pylon_3"


def test_decal_mirror_of_a_rolled_decal_mirrors_the_roll(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon_2")
    p.dispatch_event("mirror_element")
    src, new = p._decal_by_name("pylon_2"), p._decal_by_name("pylon_3")
    assert chirality_ok(new)
    cs = centre(src)
    assert centre(new) == pytest.approx((-cs[0], cs[1], cs[2]))
    # Reflecting across X = 0 reverses the roll about the (reflected) normal.
    assert decal_editor.roll_angle(new, FWD, UP) == pytest.approx(
        -decal_editor.roll_angle(src, FWD, UP))


def test_decal_mirror_on_centreline_is_readable_and_not_degenerate(make_panel):
    p = make_panel([_CENTRELINE])
    _select(p, "keel")
    p.dispatch_event("mirror_element")
    assert [d.name for d in p._decal_working] == ["keel", "keel_2"]
    new = p._decal_by_name("keel_2")
    assert chirality_ok(new)
    assert mask_of(new) == "keel"
    assert decal_editor.width(new) == pytest.approx(40.0)
    assert _mag(new.v_axis) == pytest.approx(20.0)
    assert _mag(new.normal) == pytest.approx(1.0)
    assert centre(new) == pytest.approx(centre(_CENTRELINE))


def test_decal_mirror_refused_at_16(make_panel):
    many = [_placement("d%d" % k, (float(k), 0.0, 10.0), (4.0, 0.0, 0.0),
                       (0.0, -2.0, 0.0)) for k in range(16)]
    p = make_panel(many)
    _select(p, "d3")
    p.dispatch_event("mirror_element")
    assert len(p._decal_working) == 16
    assert p._decal_error
    assert p._decal_selected == "d3"
    assert not p._undo_stack


def test_the_coord_and_rotate_mirror_leave_a_decal_alone(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon")
    p.dispatch_event("coord_mirror")
    _use_tool(p, "rotate")
    p.dispatch_event("rotate_mirror")
    assert p._decal_working == [_PYLON, _PYLON_2]
    assert not p._undo_stack


def test_decal_panels_say_mirror_is_not_offered(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon")
    assert p.transform_coords()["can_mirror"] is False
    _use_tool(p, "rotate")
    assert p.rotate_values()["can_mirror"] is False


# ── Undo ─────────────────────────────────────────────────────────────────────

def test_each_paste_and_mirror_is_one_undo_step(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon")
    p.dispatch_event("coord_copy")
    _use_tool(p, "scale")
    p.dispatch_event("scale_copy")
    _use_tool(p, "rotate")
    p.dispatch_event("rotate_copy")
    assert not p._undo_stack                    # Copy is not an edit
    _select(p, "pylon_2")
    states = [list(p._decal_working)]
    for tool, action in (("transform", "coord_paste"),
                         ("scale", "scale_paste"),
                         ("rotate", "rotate_paste"),
                         ("transform", "mirror_element")):
        _use_tool(p, tool)
        n = len(p._undo_stack)
        p.dispatch_event(action)
        assert len(p._undo_stack) == n + 1, action
        assert p._decal_working != states[-1], action
        states.append(list(p._decal_working))
    for expected in reversed(states[:-1]):
        p.dispatch_event("undo")
        assert p._decal_working == expected


def test_pasting_a_decal_onto_itself_changes_nothing(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon_2")
    for tool, verb in (("transform", "coord"), ("scale", "scale"),
                       ("rotate", "rotate")):
        _use_tool(p, tool)
        p.dispatch_event(verb + "_copy")
        p.dispatch_event(verb + "_paste")
    assert p._decal_working == [_PYLON, _PYLON_2]
    assert not p._undo_stack


def test_pipette_still_never_arms_on_a_decal(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon")
    p.dispatch_event("pipette")
    assert p._pipette_armed is False


def test_decal_mirror_clears_reposition_and_error(pane_with_two_decals):
    p = pane_with_two_decals
    _select(p, "pylon")
    p._decal_reposition = True
    p._decal_error = "stale"
    p._edit_target().mirror()
    assert p._decal_selected == "pylon_3"
    assert p._decal_reposition is False
    assert p._decal_error is None


def test_pipette_arming_is_the_adapters_call(make_panel):
    from engine.ui.spv_edit_targets import edit_target_for_key
    p = make_panel([_PYLON])
    arms = {k[0]: edit_target_for_key(p, k).pipette_arms()
            for k in (("subsystem", 0), ("light", 0), ("emitter", 0, 0),
                      ("part_anchor", "wing"), ("part_pose", "wing", "red"),
                      ("decal", "pylon"))}
    assert arms == {"subsystem": True, "light": True, "emitter": True,
                    "part_anchor": False, "part_pose": False, "decal": False}


# ── Gizmo handle restriction (EditTarget.grab_allowed) ───────────────────────

@pytest.mark.parametrize("tool,allowed", [("transform", {0, 1}),
                                          ("rotate", {2}),
                                          ("scale", {0, 1, 2})])
def test_decal_grab_allowed_is_the_adapters_call(make_panel, tool, allowed):
    """Move grabs only the u/v arrows, Rotate only the ring about the
    normal, Scale any handle -- asked of the adapter, not the panel."""
    from engine.ui.spv_edit_targets import edit_target_for_key
    p = make_panel([_PYLON])
    t = edit_target_for_key(p, ("decal", "pylon"))
    assert {h for h in range(3) if t.grab_allowed(tool, h)} == allowed


def test_decal_move_drag_first_frame_does_not_jump(make_panel):
    """A decal Move drag starts from the decal's own gizmo origin, not the
    last mount drag's (or (0,0,0)): applying the drag at the grab cursor
    leaves the decal's centre where it was."""
    from engine.ui.ship_property_viewer import axis_drag_param, gizmo_length
    p = make_panel([_PYLON])
    fb = lambda: (800, 600)
    # A mount Move drag leaves a stale _axis_grab_origin behind.
    assert p.dispatch_event("select_light:0") is True
    _use_tool(p, "transform")
    p._begin_axis_drag_for_test(0, 0.0)
    p._axis_drag = None
    _select(p, "pylon")
    g = p._active_gizmo()
    assert g is not None
    assert tuple(p._axis_grab_origin) != pytest.approx(tuple(g["origin"]))
    # Grab the u arrow at a cursor on its shaft, then apply at that cursor.
    x, y = 400.0, 300.0
    L = gizmo_length(p.camera)
    t_grab = axis_drag_param(x, y, g["origin"], g["axes"][0], L, p.camera, fb())
    p._begin_axis_drag(0, t_grab)
    t_now = axis_drag_param(x, y, p._axis_grab_origin, g["axes"][0], L,
                            p.camera, fb())
    p._apply_axis_drag(t_now)
    assert centre(p._decal_by_name("pylon")) == pytest.approx(centre(_PYLON))
