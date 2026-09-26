"""The SPV Move and Rotate gizmos author a part's Anchor and its State poses
(spec 2026-09-25 sections 2.3, 3, 7.3).

* The Anchor node is a Move target at the anchor; moving it sets the anchor
  and NEVER moves a pose (option A: poses are about the body origin).
* A {State} Transformation node is a Move and Rotate target at the POSED
  anchor. Move adds the body-frame drag delta to the pose translation; ring
  k rotates the pose about body axis e_k through the grab-time posed anchor.
* The part row and the Breakage node are no gizmo target at all.

Every edit is asserted on the staged `_pending_part` spec AND, for a pose,
on `ship._articulation_poses` -- the dict the mesh, the pins and the
derived-box queries all read -- so the preview is proven to follow the edit
immediately, not only the staged data.
"""
import copy
import json
import math

import pytest

from engine.appc import part_pose
from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui import ship_property_viewer as spv
from engine.ui.ship_property_viewer import OrbitCamera
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

UNRIGGED_LEAF = "spvgizmotest"

_LIGHT_REGION = {
    "shape": "Sphere", "position": (0.0, 0.0, 0.0),
    "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
    "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
    "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}

_DESCRIPTORS = [
    {
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "light": True, "light_region": dict(_LIGHT_REGION),
        "emitters": [],
    },
]

_PART_NODES = [
    {"name": "left wing", "parent": "Scene Root", "candidate": True,
     "bounds_min": (-1.0, -0.5, -0.5), "bounds_max": (-0.1, 0.5, 0.5)},
    {"name": "head", "parent": "Scene Root", "candidate": True,
     "bounds_min": (-0.1, 0.1, -0.1), "bounds_max": (0.1, 0.9, 0.1)},
]


class _FakeSubsystem:
    def GetPosition(self):
        return (0.0, 0.0, 0.0)

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0


class _Ship:
    """An unrigged hull at the world origin with an identity rotation, so
    world == body and a gizmo origin reads as the body-frame point."""

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


class _Target:
    def write(self, leaf, edits):
        pass


@pytest.fixture
def make_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(d, emitters=[]) for d in _DESCRIPTORS])
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda s: UNRIGGED_LEAF)

    def _make():
        ship = _Ship()
        p = ShipPropertyViewerPanel(ship_getter=lambda: ship)
        p.open()
        p._model_part_nodes = [dict(n) for n in _PART_NODES]
        p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
        return p, ship
    return _make


def _add_state(p, name, state):
    return p.dispatch_event(
        "part/add_state:" + json.dumps({"name": name, "state": state}))


def _select_node(p, name, kind):
    return p.dispatch_event(
        "part/select_node:" + json.dumps({"name": name, "kind": kind}))


def _set_anchor(p, name, anchor):
    spec = copy.deepcopy(p._effective_part(name))
    spec["anchor"] = tuple(anchor)
    p._pending_part[name] = spec


def _set_pose(p, name, state, p6):
    spec = copy.deepcopy(p._effective_part(name))
    spec["poses"][state] = tuple(p6)
    p._pending_part[name] = spec


def _pose6(p, name, state):
    return p._pending_part[name]["poses"][state]


def _assert_pose_close(a, b, eps=1e-9):
    (Ra, ta), (Rb, tb) = a, b
    for i in range(3):
        assert ta[i] == pytest.approx(tb[i], abs=eps)
        for j in range(3):
            assert Ra[i][j] == pytest.approx(Rb[i][j], abs=eps)


def _authored(make_panel, anchor=(-0.5, 0.0, 0.0), warp=None):
    """left wing with an anchor and a Warp Transformation."""
    p, ship = make_panel()
    assert p.dispatch_event("part/add_anchor:left wing") is True
    _set_anchor(p, "left wing", anchor)
    assert _add_state(p, "left wing", "warp") is True
    if warp is not None:
        _set_pose(p, "left wing", "warp", warp)
    return p, ship


# ── the tests ────────────────────────────────────────────────────────────────

def test_anchor_node_is_a_move_target_at_the_anchor(make_panel):
    p, _ship = _authored(make_panel, anchor=(-0.4, 0.2, 0.1))
    p.dispatch_event("set_tool:transform")
    assert _select_node(p, "left wing", "anchor") is True

    assert p._active_transform_target() == ("part_anchor", "left wing")
    coords = p.transform_coords()
    assert (coords["x"], coords["y"], coords["z"]) == pytest.approx(
        (-0.4, 0.2, 0.1))
    g = p.transform_gizmo()
    assert g is not None
    assert g["origin"] == pytest.approx((-0.4, 0.2, 0.1))
    assert p._active_gizmo() == g

    # The anchor has no rotation and no size: no Rotate or Scale gizmo.
    p.dispatch_event("set_tool:rotate")
    assert p.rotate_values() is None
    assert p.rotate_gizmo() is None
    p.dispatch_event("set_tool:scale")
    assert p.scale_values() is None
    assert p.scale_gizmo() is None


def test_moving_the_anchor_node_sets_the_anchor(make_panel):
    p, _ship = _authored(make_panel, anchor=(-0.4, 0.2, 0.1))
    p.dispatch_event("set_tool:transform")
    _select_node(p, "left wing", "anchor")

    # A gizmo drag along body X.
    p._begin_axis_drag_for_test(0, 1.0)
    p._apply_axis_drag(1.25)
    p._end_axis_drag()
    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        (-0.15, 0.2, 0.1))

    # The coordinate stepper, copy/paste and mirror all edit the anchor too.
    assert p.dispatch_event(
        'coord_nudge:{"axis":2,"delta":0.05}') is True
    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        (-0.15, 0.2, 0.15))
    p.dispatch_event("coord_copy")
    p.dispatch_event("coord_mirror")
    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        (0.15, 0.2, 0.15))
    p.dispatch_event("coord_paste")
    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        (-0.15, 0.2, 0.15))
    p.dispatch_event("mirror_element")
    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        (0.15, 0.2, 0.15))

    # The drag is one undo step, like any other gizmo edit: five edits
    # (drag, nudge, mirror, paste, mirror -- copy stages nothing) undo to
    # the authored anchor.
    for _ in range(5):
        p.dispatch_event("undo")
    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        (-0.4, 0.2, 0.1))


def test_anchor_move_leaves_state_poses(make_panel):
    """Option A (spec 2.3): a pose is about the body ORIGIN, so moving the
    anchor changes only the swing between poses, never where a pose is."""
    warp = (0.02, -0.03, 0.04, 5.0, 30.0, -10.0)
    p, _ship = _authored(make_panel, anchor=(-0.5, 0.0, 0.0), warp=warp)
    p.dispatch_event("set_tool:transform")
    _select_node(p, "left wing", "anchor")

    p._begin_axis_drag_for_test(0, 0.0)
    p._apply_axis_drag(0.1)
    p._end_axis_drag()

    spec = p._pending_part["left wing"]
    assert spec["anchor"] == pytest.approx((-0.4, 0.0, 0.0))
    assert spec["poses"]["warp"] == warp, "the warp pose6 is untouched"

    p.dispatch_event('coord_nudge:{"axis":1,"delta":0.2}')
    assert p._pending_part["left wing"]["poses"]["warp"] == warp


def test_pose_move_adds_to_the_translation(make_panel):
    """Fix round 1, ruling 15: the Move panel describes what is on screen --
    the POSED anchor, where the gizmo sits -- not the raw translation t.
    (Re-pointed from Task 8's raw-t display: the behaviour changed by
    ruling; this is not a weakening.) Dragging or nudging still adds the
    delta to t and leaves R alone, so q moves by exactly that delta."""
    warp = (0.1, 0.0, 0.0, 0.0, 30.0, 0.0)
    anchor = (-0.5, 0.0, 0.0)
    p, ship = _authored(make_panel, anchor=anchor, warp=warp)
    p.dispatch_event("set_tool:transform")
    assert _select_node(p, "left wing", "warp") is True
    assert p._mount_editing_enabled() is False, (
        "fixture: a selected state node locks the mounts")

    assert p._active_transform_target() == ("part_pose", "left wing", "warp")
    q = part_pose.apply(part_pose.pose_from6(warp), anchor)
    coords = p.transform_coords()
    assert (coords["x"], coords["y"], coords["z"]) == pytest.approx(q), (
        "the numeric panel shows the POSED anchor")
    assert p.transform_gizmo()["origin"] == pytest.approx(q), (
        "the gizmo sits at the POSED anchor")

    # A drag along body Z adds its delta to t; R is untouched. The mount
    # lock must not refuse it -- editing this very pose is the point.
    p._begin_axis_drag_for_test(2, 1.0)
    p._apply_axis_drag(1.05)
    p._end_axis_drag()
    want = (0.1, 0.0, 0.05, 0.0, 30.0, 0.0)
    assert _pose6(p, "left wing", "warp") == pytest.approx(want)
    assert ship._articulation_poses["left wing"] == part_pose.pose_from6(
        _pose6(p, "left wing", "warp")), "the preview follows the drag"

    # The stepper translates the pose too, and the preview follows.
    assert p.dispatch_event('coord_nudge:{"axis":1,"delta":-0.02}') is True
    want = (0.1, -0.02, 0.05, 0.0, 30.0, 0.0)
    assert _pose6(p, "left wing", "warp") == pytest.approx(want)
    assert ship._articulation_poses["left wing"] == part_pose.pose_from6(
        _pose6(p, "left wing", "warp"))
    assert p._pending_part["left wing"]["anchor"] == anchor, (
        "moving a pose never moves the anchor")

    # Undo returns the pose AND the preview.
    p.dispatch_event("undo")
    p.dispatch_event("undo")
    assert _pose6(p, "left wing", "warp") == pytest.approx(warp)
    assert ship._articulation_poses["left wing"] == part_pose.pose_from6(
        _pose6(p, "left wing", "warp"))


def test_move_panel_shows_the_posed_anchor_and_a_nudge_moves_it_exactly(
        make_panel):
    """Ruling 15 on a translated AND rotated pose: the panel shows q, a
    nudge moves q by exactly the nudge, and R does not change."""
    warp = (0.03, -0.02, 0.04, 12.0, 25.0, -8.0)
    anchor = (-0.16, 0.1, 0.05)
    p, ship = _authored(make_panel, anchor=anchor, warp=warp)
    p.dispatch_event("set_tool:transform")
    _select_node(p, "left wing", "warp")
    pose0 = part_pose.pose_from6(warp)
    q0 = part_pose.apply(pose0, anchor)
    c = p.transform_coords()
    assert (c["x"], c["y"], c["z"]) == pytest.approx(q0, abs=1e-12)

    assert p.dispatch_event('coord_nudge:{"axis":0,"delta":0.07}') is True

    pose1 = part_pose.pose_from6(_pose6(p, "left wing", "warp"))
    q1 = part_pose.apply(pose1, anchor)
    assert q1 == pytest.approx((q0[0] + 0.07, q0[1], q0[2]), abs=1e-12)
    for i in range(3):
        for j in range(3):
            assert pose1[0][i][j] == pytest.approx(pose0[0][i][j], abs=1e-12)
    c = p.transform_coords()
    assert (c["x"], c["y"], c["z"]) == pytest.approx(q1, abs=1e-12)
    _assert_pose_close(ship._articulation_poses["left wing"], pose1)


def test_coord_mirror_matches_the_action_row_mirror_on_a_pose(make_panel):
    warp = (0.1, 0.2, 0.3, 10.0, 20.0, 30.0)
    mirrored = (-0.1, 0.2, 0.3, 10.0, -20.0, -30.0)
    p, _ship = _authored(make_panel, warp=warp)
    p.dispatch_event("set_tool:transform")
    _select_node(p, "left wing", "warp")

    p.dispatch_event("coord_mirror")
    via_coord = _pose6(p, "left wing", "warp")
    _set_pose(p, "left wing", "warp", warp)
    p.dispatch_event("mirror_element")
    via_row = _pose6(p, "left wing", "warp")

    assert via_coord == pytest.approx(mirrored)
    assert via_row == pytest.approx(mirrored)


def test_coord_paste_refuses_across_part_kinds(make_panel):
    """Anchor <-> anchor and pose <-> pose only: a point copied from one
    kind means something else on the other. A refused paste changes
    nothing and leaves no undo entry."""
    warp = (0.1, 0.2, 0.3, 10.0, 20.0, 30.0)
    p, _ship = _authored(make_panel, anchor=(-0.4, 0.2, 0.1), warp=warp)
    p.dispatch_event("set_tool:transform")

    # anchor -> pose: refused.
    _select_node(p, "left wing", "anchor")
    p.dispatch_event("coord_copy")
    _select_node(p, "left wing", "warp")
    before = copy.deepcopy(p._pending_part)
    undo_len = len(p._undo_stack)
    p.dispatch_event("coord_paste")
    assert p._pending_part == before
    assert len(p._undo_stack) == undo_len

    # pose -> anchor: refused.
    p.dispatch_event("coord_copy")
    _select_node(p, "left wing", "anchor")
    before = copy.deepcopy(p._pending_part)
    p.dispatch_event("coord_paste")
    assert p._pending_part == before
    assert len(p._undo_stack) == undo_len

    # pose -> pose: allowed (onto another state of the part).
    _add_state(p, "left wing", "cruise")
    _select_node(p, "left wing", "cruise")
    p.dispatch_event("coord_paste")
    anchor = p._effective_part("left wing")["anchor"]
    q_warp = part_pose.apply(part_pose.pose_from6(warp), anchor)
    q_cruise = part_pose.apply(
        part_pose.pose_from6(_pose6(p, "left wing", "cruise")), anchor)
    assert q_cruise == pytest.approx(q_warp, abs=1e-12)

    # anchor -> anchor: allowed.
    _select_node(p, "left wing", "anchor")
    p.dispatch_event("coord_copy")
    p.dispatch_event('coord_nudge:{"axis":0,"delta":0.3}')
    p.dispatch_event("coord_paste")
    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        (-0.4, 0.2, 0.1))


def test_pose_ring_drag_rotates_about_the_posed_anchor(make_panel):
    anchor = (-0.16, 0.0, 0.05)
    p, ship = _authored(make_panel, anchor=anchor)
    assert _pose6(p, "left wing", "warp") == (0.0,) * 6, "identity pose"
    p.dispatch_event("set_tool:rotate")
    _select_node(p, "left wing", "warp")
    assert p.rotate_gizmo()["origin"] == pytest.approx(anchor)

    p._begin_ring_drag(1, 0.0)
    p._apply_ring_drag_angle(math.radians(45.0))
    p._end_axis_drag()

    got = part_pose.pose_from6(_pose6(p, "left wing", "warp"))
    _assert_pose_close(got, part_pose.hinge_pose(anchor, (0, 1, 0), 45.0))
    assert part_pose.apply(got, anchor) == pytest.approx(anchor, abs=1e-12), (
        "the posed anchor stays put")
    _assert_pose_close(ship._articulation_poses["left wing"], got)

    # The rotation is about the GRAB-time anchor from the GRAB-time pose:
    # a second frame of the same drag replaces the first, it does not add.
    p._begin_ring_drag(1, 0.0)
    p._apply_ring_drag_angle(math.radians(10.0))
    p._apply_ring_drag_angle(math.radians(20.0))
    p._end_axis_drag()
    got = part_pose.pose_from6(_pose6(p, "left wing", "warp"))
    _assert_pose_close(got, part_pose.hinge_pose(anchor, (0, 1, 0), 65.0))
    _assert_pose_close(ship._articulation_poses["left wing"], got)


def test_pose_ring_drag_pivots_on_the_posed_anchor_not_the_rest_anchor(
        make_panel):
    """With a translated pose the ring pivots where the anchor is DRAWN."""
    anchor = (-0.16, 0.0, 0.05)
    warp = (0.0, 0.1, 0.0, 0.0, 0.0, 0.0)
    p, _ship = _authored(make_panel, anchor=anchor, warp=warp)
    p.dispatch_event("set_tool:rotate")
    _select_node(p, "left wing", "warp")
    q = part_pose.apply(part_pose.pose_from6(warp), anchor)

    p._begin_ring_drag(2, 0.0)
    p._apply_ring_drag_angle(math.radians(30.0))
    p._end_axis_drag()

    got = part_pose.pose_from6(_pose6(p, "left wing", "warp"))
    assert part_pose.apply(got, anchor) == pytest.approx(q, abs=1e-12)
    R30, _t = part_pose.hinge_pose(q, (0, 0, 1), 30.0)
    for i in range(3):
        for j in range(3):
            assert got[0][i][j] == pytest.approx(R30[i][j], abs=1e-12)


def _euler_matches(pose, rx, ry, rz):
    want = part_pose.euler_to_matrix(rx, ry, rz)
    for i in range(3):
        for j in range(3):
            assert pose[0][i][j] == pytest.approx(want[i][j], abs=1e-9)


def test_rotate_values_show_and_edit_the_euler_angles(make_panel):
    """Fix round 1, ruling 14: a numeric rotate edit sets that Euler angle
    and holds the POSED ANCHOR fixed, so t changes with it. (Re-pointed
    from Task 8's 'only rz changes, t kept' -- the behaviour changed by
    ruling; this is not a weakening.)"""
    warp = (0.1, 0.2, 0.3, 10.0, 20.0, 30.0)
    p, ship = _authored(make_panel, warp=warp)
    anchor = p._effective_part("left wing")["anchor"]
    q0 = part_pose.apply(part_pose.pose_from6(warp), anchor)
    p.dispatch_event("set_tool:rotate")
    _select_node(p, "left wing", "warp")

    rv = p.rotate_values()
    assert [f["label"] for f in rv["fields"]] == ["X", "Y", "Z"]
    assert [f["value"] for f in rv["fields"]] == pytest.approx(
        [10.0, 20.0, 30.0])
    assert _payload(p)["rotate_values"]["fields"][2]["value"] == pytest.approx(
        30.0)

    assert p.dispatch_event('rotate_nudge:{"axis":2,"delta":5}') is True
    got = part_pose.pose_from6(_pose6(p, "left wing", "warp"))
    _euler_matches(got, 10.0, 20.0, 35.0)
    assert part_pose.apply(got, anchor) == pytest.approx(q0, abs=1e-9)
    assert [f["value"] for f in p.rotate_values()["fields"]] == pytest.approx(
        [10.0, 20.0, 35.0])
    assert ship._articulation_poses["left wing"] == part_pose.pose_from6(
        _pose6(p, "left wing", "warp")), "the preview follows the edit"

    # Copy / paste carry the three angles between poses.
    assert p.rotate_values()["can_paste"] is False
    p.dispatch_event("rotate_copy")
    assert p.rotate_values()["has_clipboard"] is True
    assert p.rotate_values()["can_paste"] is True
    p.dispatch_event('rotate_nudge:{"axis":0,"delta":-10}')
    assert _pose6(p, "left wing", "warp")[3] == pytest.approx(0.0)
    p.dispatch_event("rotate_paste")
    got = part_pose.pose_from6(_pose6(p, "left wing", "warp"))
    _euler_matches(got, 10.0, 20.0, 35.0)
    assert part_pose.apply(got, anchor) == pytest.approx(q0, abs=1e-9)


def test_rotate_nudge_holds_the_posed_anchor(make_panel):
    """Six +5 degree clicks on a translated + rotated pose: the hinge point
    does not slide (the review measured ~0.09 ship units of drift when the
    stepper rotated about the ship origin)."""
    warp = (0.05, -0.04, 0.02, 15.0, -30.0, 40.0)
    p, ship = _authored(make_panel, anchor=(-0.16, 0.0, 0.05), warp=warp)
    anchor = p._effective_part("left wing")["anchor"]
    q0 = part_pose.apply(part_pose.pose_from6(warp), anchor)
    p.dispatch_event("set_tool:rotate")
    _select_node(p, "left wing", "warp")

    for _ in range(6):
        assert p.dispatch_event('rotate_nudge:{"axis":1,"delta":5}') is True
    got = part_pose.pose_from6(_pose6(p, "left wing", "warp"))
    _euler_matches(got, 15.0, 0.0, 40.0)
    assert part_pose.apply(got, anchor) == pytest.approx(q0, abs=1e-9)
    _assert_pose_close(ship._articulation_poses["left wing"], got)


def test_rotate_paste_holds_the_posed_anchor(make_panel):
    p, _ship = _authored(make_panel, anchor=(-0.16, 0.0, 0.05),
                         warp=(0.0, 0.0, 0.0, 30.0, 0.0, 0.0))
    _add_state(p, "left wing", "cruise")
    cruise = (0.05, -0.04, 0.02, 15.0, -30.0, 40.0)
    _set_pose(p, "left wing", "cruise", cruise)
    anchor = p._effective_part("left wing")["anchor"]
    q0 = part_pose.apply(part_pose.pose_from6(cruise), anchor)
    p.dispatch_event("set_tool:rotate")
    _select_node(p, "left wing", "warp")
    p.dispatch_event("rotate_copy")
    _select_node(p, "left wing", "cruise")

    p.dispatch_event("rotate_paste")

    got = part_pose.pose_from6(_pose6(p, "left wing", "cruise"))
    _euler_matches(got, 30.0, 0.0, 0.0)
    assert part_pose.apply(got, anchor) == pytest.approx(q0, abs=1e-9)


def test_mirror_reflects_a_pose_across_ship_x(make_panel):
    warp = (0.1, 0.2, 0.3, 10.0, 20.0, 30.0)
    mirrored = (-0.1, 0.2, 0.3, 10.0, -20.0, -30.0)
    p, ship = _authored(make_panel, warp=warp)
    p.dispatch_event("set_tool:rotate")
    _select_node(p, "left wing", "warp")

    p.dispatch_event("rotate_mirror")
    assert _pose6(p, "left wing", "warp") == pytest.approx(mirrored)
    assert ship._articulation_poses["left wing"] == part_pose.pose_from6(
        _pose6(p, "left wing", "warp"))

    # The action-row Mirror reflects the whole pose ONCE (not tx twice).
    _set_pose(p, "left wing", "warp", warp)
    p.dispatch_event("mirror_element")
    assert _pose6(p, "left wing", "warp") == pytest.approx(mirrored)

    # Reflecting really is a reflection: the mirrored pose draws the
    # X-reflected point wherever the original draws a point.
    x = (0.3, -0.2, 0.1)
    a = part_pose.apply(part_pose.pose_from6(warp), x)
    b = part_pose.apply(part_pose.pose_from6(mirrored), (-x[0], x[1], x[2]))
    assert b == pytest.approx((-a[0], a[1], a[2]), abs=1e-12)

    # An anchor mirrors x -> -x.
    _select_node(p, "left wing", "anchor")
    anchor = p._effective_part("left wing")["anchor"]
    p.dispatch_event("mirror_element")
    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        (-anchor[0], anchor[1], anchor[2]))


def test_a_part_row_or_breakage_node_has_no_gizmo(make_panel):
    p, _ship = _authored(make_panel, warp=(0.1, 0.0, 0.0, 0.0, 30.0, 0.0))
    p.dispatch_event("part/make_breakable:left wing")
    for tool in ("transform", "rotate", "scale"):
        p.active_tool = tool
        assert p.dispatch_event("model_parts/select:left wing") is True
        assert p._active_transform_target() is None, tool
        assert p._active_gizmo() is None, tool
        assert p.transform_coords() is None
        assert p.rotate_values() is None
        assert p.scale_values() is None
        assert _select_node(p, "left wing", "breakage") is True
        assert spv.selected_part_node() == ("left wing", "breakage")
        assert p._active_transform_target() is None, tool
        assert p._active_gizmo() is None, tool
        assert p.transform_coords() is None
        assert p.rotate_values() is None
        assert p.scale_values() is None
    assert _payload(p)["has_selection"] is False


def test_scale_is_inert_on_part_nodes(make_panel):
    p, _ship = _authored(make_panel, warp=(0.1, 0.0, 0.0, 0.0, 30.0, 0.0))
    for kind in ("anchor", "warp"):
        _select_node(p, "left wing", kind)
        # Selecting the node activates Move (ruling 16), so pick Scale AFTER
        # it -- else the checks below would pass for want of the tool.
        p.active_tool = "scale"
        before = copy.deepcopy(p._pending_part)
        assert p.scale_values() is None
        assert p.scale_gizmo() is None
        p.dispatch_event('scale_nudge:{"index":0,"delta":0.1}')
        p.dispatch_event("scale_copy")
        p.dispatch_event("scale_paste")
        p.dispatch_event("scale_uniform")
        assert p._pending_part == before
        # The pipette copies mount aspects; it never arms on a part node.
        p.dispatch_event("pipette")
        assert p._pipette_armed is False


def _payload(p):
    p._last_pushed = None
    js = p.render_payload()
    prefix = "setShipPropertyViewer("
    assert js.startswith(prefix) and js.endswith(");"), js
    return json.loads(js[len(prefix):-2])


# ── final-review follow-ups (rulings 16 and 18) ─────────────────────────────

class _OffsetShip(_Ship):
    """A hull away from the world origin, turned 90 degrees about Z, so a
    gizmo origin that forgot the body->world step would be caught."""

    def GetWorldLocation(self):
        return TGPoint3(3.0, -2.0, 1.0)

    def GetWorldRotation(self):
        m = TGMatrix3()
        m.MakeZRotation(math.radians(90.0))
        return m


@pytest.mark.parametrize("tool", [None, "rotate", "scale"])
def test_selecting_an_anchor_node_shows_the_move_gizmo_as_its_marker(
        make_panel, tool):
    """Ruling 16 (spec 7.3 'anchor marker'): the Move gizmo IS the marker,
    so selecting an Anchor node activates Move from any other tool -- else
    nothing at all is drawn at the anchor."""
    p, ship = _authored(make_panel, anchor=(-0.4, 0.2, 0.1))
    p.active_tool = tool
    offset = _OffsetShip()
    p._ship_getter = lambda: offset
    assert _select_node(p, "left wing", "anchor") is True

    assert p.active_tool == "transform"
    g = p.transform_gizmo()
    assert g is not None
    assert g["origin"] == pytest.approx(
        spv.world_from_body(offset, (-0.4, 0.2, 0.1)))
    assert g["origin"] != pytest.approx((-0.4, 0.2, 0.1)), (
        "fixture: world differs from body")


@pytest.mark.parametrize("tool", [None, "scale"])
def test_selecting_a_state_node_shows_the_move_gizmo_at_the_posed_anchor(
        make_panel, tool):
    warp = (0.03, -0.02, 0.04, 12.0, 25.0, -8.0)
    anchor = (-0.16, 0.1, 0.05)
    p, _ship = _authored(make_panel, anchor=anchor, warp=warp)
    p.active_tool = tool
    offset = _OffsetShip()
    p._ship_getter = lambda: offset
    assert _select_node(p, "left wing", "warp") is True

    assert p.active_tool == "transform"
    q = part_pose.apply(part_pose.pose_from6(warp), anchor)
    g = p.transform_gizmo()
    assert g is not None
    assert g["origin"] == pytest.approx(spv.world_from_body(offset, q))


def test_selecting_a_state_node_keeps_rotate_whose_gizmo_is_the_marker(
        make_panel):
    """Rotate already draws its rings at the posed anchor, so a State node
    selected under Rotate keeps Rotate (posing a part is mostly rotating
    it); the marker requirement is met either way."""
    warp = (0.03, -0.02, 0.04, 12.0, 25.0, -8.0)
    anchor = (-0.16, 0.1, 0.05)
    p, _ship = _authored(make_panel, anchor=anchor, warp=warp)
    p.dispatch_event("set_tool:rotate")
    assert _select_node(p, "left wing", "warp") is True
    assert p.active_tool == "rotate"
    q = part_pose.apply(part_pose.pose_from6(warp), anchor)
    assert p.rotate_gizmo()["origin"] == pytest.approx(q)


def test_breakage_node_does_not_switch_the_tool(make_panel):
    p, _ship = _authored(make_panel)
    p.dispatch_event("part/make_breakable:left wing")
    p.active_tool = "scale"
    assert _select_node(p, "left wing", "breakage") is True
    assert p.active_tool == "scale"


def test_anchor_gizmo_verbs_leave_every_state_pose_byte_unchanged(make_panel):
    """Option A (spec 2.3), the central invariant: a pose is about the body
    ORIGIN, so paste / coord-mirror / action-row mirror on the ANCHOR never
    rewrite a pose -- not even by a float round-trip."""
    warp = (0.02, -0.03, 0.04, 5.0, 30.0, -10.0)
    cruise = (-0.01, 0.05, 0.0, -7.5, 0.0, 22.0)
    p, _ship = _authored(make_panel, anchor=(-0.5, 0.1, 0.0), warp=warp)
    _add_state(p, "left wing", "cruise")
    _set_pose(p, "left wing", "cruise", cruise)
    p.dispatch_event("set_tool:transform")
    _select_node(p, "left wing", "anchor")
    assert p._active_transform_target() == ("part_anchor", "left wing")

    def _poses_unchanged():
        poses = p._effective_part("left wing")["poses"]
        assert poses["warp"] == warp
        assert poses["cruise"] == cruise

    p.dispatch_event("coord_copy")
    p.dispatch_event('coord_nudge:{"axis":0,"delta":0.2}')
    anchor_before = p._effective_part("left wing")["anchor"]
    p.dispatch_event("coord_paste")
    assert p._effective_part("left wing")["anchor"] != anchor_before, (
        "fixture: the paste really moved the anchor")
    _poses_unchanged()

    anchor_before = p._effective_part("left wing")["anchor"]
    p.dispatch_event("coord_mirror")
    assert p._effective_part("left wing")["anchor"] != anchor_before
    _poses_unchanged()

    anchor_before = p._effective_part("left wing")["anchor"]
    p.dispatch_event("mirror_element")
    assert p._effective_part("left wing")["anchor"] != anchor_before
    _poses_unchanged()


def test_transform_coords_can_paste_is_kind_aware(make_panel):
    """Ruling 18: like scale_values / rotate_values, the Move panel's
    can_paste is true only when the clipboard's kind matches the target's
    -- the Paste button must not offer a paste the dispatcher refuses."""
    warp = (0.1, 0.2, 0.3, 10.0, 20.0, 30.0)
    p, _ship = _authored(make_panel, anchor=(-0.4, 0.2, 0.1), warp=warp)
    p.dispatch_event("set_tool:transform")
    _select_node(p, "left wing", "anchor")
    c = p.transform_coords()
    assert c["has_clipboard"] is False and c["can_paste"] is False

    p.dispatch_event("coord_copy")
    c = p.transform_coords()
    assert c["has_clipboard"] is True and c["can_paste"] is True
    assert _payload(p)["transform_coords"]["can_paste"] is True

    _select_node(p, "left wing", "warp")
    c = p.transform_coords()
    assert c["has_clipboard"] is True and c["can_paste"] is False
    assert _payload(p)["transform_coords"]["can_paste"] is False

    # A mount target is a third kind.
    p.dispatch_event("select_pin:0")
    assert p._active_transform_target() == ("subsystem", 0)
    assert p.transform_coords()["can_paste"] is False
    p.dispatch_event("coord_copy")
    assert p.transform_coords()["can_paste"] is True
