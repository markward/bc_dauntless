"""A part NOT in the ship's rig snapshot can still be drawn posed.

The SPV authors parts that no hardpoint file has registered yet -- the Bird
of Prey's `head`, or any part of an unrigged / modded hull. Selecting such a
part's {State} Transformation forces its pose by NAME into
`ship._articulation_poses`; every reader of a live pose then has to honour
that name even though `rig_for(leaf)` has never heard of it, or the author
sees mounts lock while the mesh stays at the NIF pose.

Which points belong to such a part is still decided by the DERIVED part
boxes (`part_for_point`), so only real model nodes are ever posed.
"""
import pytest

from engine.appc import articulation, part_pose, part_severance

LEAF = "freshparttest"          # no rig registered for this leaf
HEAD_BOX = ((-0.1, 0.1, -0.1), (0.1, 0.9, 0.1))
BODY_BOX = ((-0.3, -0.7, -0.13), (0.3, 0.29, 0.21))
INSIDE_HEAD = (0.0, 0.5, 0.0)
POSE = part_pose.pose_from6((0.0, 0.2, 0.1, 30.0, 0.0, 0.0))


class _Ship:
    def __init__(self):
        self._articulation_leaf = LEAF


class _Session:
    def __init__(self):
        self.ship_articulation = {}


@pytest.fixture
def boxes(monkeypatch):
    monkeypatch.setitem(articulation._derived_boxes, LEAF, {"head": HEAD_BOX, "body": BODY_BOX})
    assert articulation.rig_for(LEAF) == (), "fixture: the leaf has no rig"


@pytest.fixture
def pushes(monkeypatch):
    from engine import host_io
    seen = []
    monkeypatch.setattr(
        host_io, "set_instance_node_transform",
        lambda iid, node, m16: seen.append((iid, node, tuple(m16))))
    return seen


def test_force_part_pose_accepts_a_part_outside_the_rig(boxes):
    ship = _Ship()
    articulation.force_part_pose(ship, "head", POSE)
    assert ship._articulation_poses["head"] == POSE
    assert articulation.pose_for_part(ship, "head") == POSE


def test_forcing_the_NIF_pose_clears_a_fresh_part(boxes):
    ship = _Ship()
    articulation.force_part_pose(ship, "head", POSE)
    articulation.force_pose(ship, None)
    assert part_pose.is_identity(articulation.pose_for_part(ship, "head"))


def test_a_point_inside_the_fresh_parts_box_follows_it(boxes):
    ship = _Ship()
    assert articulation.part_transform_point(ship, INSIDE_HEAD) == INSIDE_HEAD
    articulation.force_part_pose(ship, "head", POSE)
    assert articulation.part_transform_point(ship, INSIDE_HEAD) == pytest.approx(
        part_pose.apply(POSE, INSIDE_HEAD))
    assert articulation.part_transform_vector(
        ship, (0.0, 0.0, 1.0), "head") == pytest.approx(
        part_pose.apply_vector(POSE, (0.0, 0.0, 1.0)))
    # A point on no box is untouched: only real model nodes are posed.
    assert articulation.part_transform_point(ship, (3.0, 3.0, 3.0)) == (
        3.0, 3.0, 3.0)


def test_a_posed_point_attributes_back_to_the_fresh_part(boxes):
    ship = _Ship()
    articulation.force_part_pose(ship, "head", POSE)
    posed = part_pose.apply(POSE, (0.0, 0.85, 0.0))
    assert part_severance.part_for_point(LEAF, posed) != "head", (
        "fixture: the posed point must have left the rest box")
    assert part_severance.part_for_live_point(ship, posed) == "head"
    assert part_severance.rest_point_for_live_point(ship, posed) == \
        pytest.approx((0.0, 0.85, 0.0))


def test_the_render_sync_pushes_a_fresh_part_and_clears_it(boxes, pushes):
    from engine import host_loop
    session, ship = _Session(), _Ship()
    articulation.force_part_pose(ship, "head", POSE)

    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes == [(7, "head", tuple(
        part_pose.matrix4_model(POSE, articulation.MODEL_TO_SHIP)))]
    pushes.clear()

    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes == [], "a settled pose must not re-push"

    # Releasing the pose drops the name from the dict; the change guard must
    # still cover it and push the identity, or the head stays drawn posed.
    articulation.force_pose(ship, None)
    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes == [(7, "head", tuple(
        part_pose.matrix4_model(part_pose.IDENTITY,
                                articulation.MODEL_TO_SHIP)))]
    pushes.clear()
    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes == [], "the released identity must not re-push every frame"


def test_a_severed_fresh_part_is_not_pushed(boxes, pushes, monkeypatch):
    from engine import host_loop
    monkeypatch.setattr(part_severance, "is_detached",
                        lambda s, node: node == "head")
    ship = _Ship()
    articulation.force_part_pose(ship, "head", POSE)
    host_loop._sync_ship_articulation(_Session(), ship, 7)
    assert pushes == []


def test_an_unrigged_ship_with_no_forced_pose_is_untouched(boxes, pushes):
    from engine import host_loop
    session, ship = _Session(), _Ship()
    host_loop._sync_ship_articulation(session, ship, 7)
    assert pushes == []
    assert session.ship_articulation == {}
    assert not hasattr(ship, "_articulation_poses")


# ── force_state_poses: the SPV's whole-state preview ─────────────────────────
#
# Selecting a State node previews EVERY part in that state (Mark,
# 2026-09-26), so the forcing helper takes {name: pose} and must honour fresh
# (non-rig) names exactly as force_part_pose does (Ruling 10).

POSE_B = part_pose.pose_from6((0.05, -0.1, 0.0, 0.0, -25.0, 10.0))


def test_force_state_poses_poses_every_named_part_including_fresh_ones(boxes):
    ship = _Ship()
    articulation.force_state_poses(ship, {"head": POSE, "body": POSE_B})
    assert ship._articulation_poses == {"head": POSE, "body": POSE_B}
    assert articulation.pose_for_part(ship, "head") == POSE
    assert articulation.pose_for_part(ship, "body") == POSE_B
    assert set(articulation.posed_part_names(ship)) == {"head", "body"}


def test_force_state_poses_drops_a_previously_forced_name(boxes):
    """A part forced by the LAST preview but absent from this one returns to
    the NIF pose -- the dict is rebuilt, not merged."""
    ship = _Ship()
    articulation.force_state_poses(ship, {"head": POSE, "body": POSE_B})
    articulation.force_state_poses(ship, {"body": POSE_B})
    assert part_pose.is_identity(articulation.pose_for_part(ship, "head"))
    assert articulation.pose_for_part(ship, "body") == POSE_B


def test_force_state_poses_puts_unnamed_rig_parts_at_the_nif_pose(monkeypatch):
    from engine.appc import articulated_part as ap
    wing = ap.ArticulatedPartProperty_Create("left wing")
    wing.SetAnchor(0.0, 0.0, 0.0)
    wing.SetStatePose("warp", 0.0, 0.0, 0.0, 0.0, 45.0, 0.0)
    monkeypatch.setattr(articulation, "rig_for",
                        lambda leaf: (wing,) if leaf == LEAF else ())
    ship = _Ship()
    ship._articulation_transitions = {"left wing": object()}
    articulation.force_state_poses(ship, {"head": POSE})
    assert ship._articulation_poses == {"left wing": part_pose.IDENTITY,
                                        "head": POSE}
    assert ship._articulation_transitions == {}, "in-flight swings dropped"


def test_the_render_sync_pushes_every_state_posed_part(boxes, pushes):
    from engine import host_loop
    ship = _Ship()
    articulation.force_state_poses(ship, {"head": POSE, "body": POSE_B})
    host_loop._sync_ship_articulation(_Session(), ship, 7)
    assert sorted(pushes) == sorted([
        (7, "head", tuple(part_pose.matrix4_model(
            POSE, articulation.MODEL_TO_SHIP))),
        (7, "body", tuple(part_pose.matrix4_model(
            POSE_B, articulation.MODEL_TO_SHIP))),
    ])
