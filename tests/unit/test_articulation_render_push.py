"""Articulated part node overrides follow the SIM pose, per change (phase 3a).

The node overrides are what the mesh trace reads for a posed part, so they
must be written when `ship._articulation_poses` changes -- on the sim tick
(`articulation.tick_ship`) or at an SPV event edge (`_store_forced`) -- not
once per render frame from `_sync_instance_transforms`. The articulation
module calls `pose_sink.notify(ship)`; the host installs the sink, which
pushes through `host_loop._sync_ship_articulation` (its change guard is
unchanged, so a notify that changes nothing pushes nothing).
"""
import inspect
import re

import pytest

from engine import host_io, host_loop
from engine.appc import articulated_part as ap
from engine.appc import articulation, part_pose, part_severance, pose_sink
from engine.core.native_transform_buffer import NativeTransformBuffer
from tests.unit.test_render_transform_binding import _FakeRenderer, _Obj

LEAF = "renderpushtest"
IID = 7


def _part():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetAnchor(0.0, 0.0, 0.0)
    p.SetTransitionSeconds(2.0)
    p.SetStatePose("cruise", 0.0, 0.0, 0.0, 0.0, 90.0, 0.0)
    return p


class _Ship:
    def __init__(self, state="cruise"):
        self.state = state
        self._articulation_leaf = LEAF


class _Session:
    def __init__(self, ship):
        self.ship_instances = {ship: IID}
        self.ship_articulation = {}


@pytest.fixture
def rig(monkeypatch):
    part = _part()
    monkeypatch.setattr(articulation, "rig_for",
                        lambda leaf: (part,) if leaf == LEAF else ())
    monkeypatch.setattr(articulation, "state_for", lambda ship: ship.state)
    return part


@pytest.fixture
def pushes(monkeypatch):
    seen = []
    monkeypatch.setattr(
        host_io, "set_instance_node_transform",
        lambda iid, node, m16: seen.append((iid, node, tuple(m16))))
    return seen


@pytest.fixture
def wired():
    """Install the host's sink against a fake session."""
    def _wire(ship):
        session = _Session(ship)
        pose_sink.set(lambda s: host_loop._push_articulation(session, s))
        return session
    yield _wire
    pose_sink.reset()


def _m16(pose):
    return tuple(part_pose.matrix4_model(pose, articulation.MODEL_TO_SHIP))


def test_tick_ship_pushes_a_moving_part_through_the_sink(rig, pushes, wired):
    ship = _Ship()
    wired(ship)
    articulation.tick_ship(ship, 0.5)
    assert pushes == [(IID, "left wing",
                       _m16(articulation.pose_for_part(ship, "left wing")))]


def test_a_settled_ship_ticks_without_a_push(rig, pushes, wired):
    ship = _Ship()
    wired(ship)
    articulation.tick_ship(ship, 5.0)       # reaches the cruise pose
    assert len(pushes) == 1
    for _ in range(5):
        articulation.tick_ship(ship, 1.0 / 60.0)
    assert len(pushes) == 1, "a settled ship must not re-push"


def test_force_part_pose_pushes_and_release_pushes_identity_once(
        rig, pushes, wired):
    ship = _Ship()
    wired(ship)
    pose = part_pose.pose_from6((0.0, 0.2, 0.1, 30.0, 0.0, 0.0))
    articulation.force_part_pose(ship, "head", pose)
    assert (IID, "head", _m16(pose)) in pushes
    pushes.clear()
    articulation.force_pose(ship, None)
    assert pushes.count((IID, "head", _m16(part_pose.IDENTITY))) == 1
    pushes.clear()
    articulation.force_pose(ship, None)
    assert pushes == [], "the released identity must push only once"


def test_a_severed_part_is_not_pushed(rig, pushes, wired, monkeypatch):
    monkeypatch.setattr(part_severance, "is_detached",
                        lambda s, node: node == "left wing")
    ship = _Ship()
    wired(ship)
    articulation.tick_ship(ship, 0.5)
    assert pushes == []


def test_no_sink_is_a_no_op(rig, pushes):
    ship = _Ship()
    articulation.tick_ship(ship, 0.5)
    articulation.force_pose(ship, None)
    assert pushes == []


def test_a_raising_sink_never_breaks_the_tick(rig):
    def _boom(ship):
        raise RuntimeError("sink failed")
    pose_sink.set(_boom)
    try:
        ship = _Ship()
        articulation.tick_ship(ship, 0.5)
        articulation.force_pose(ship, None)
    finally:
        pose_sink.reset()


def test_render_sync_no_longer_pushes_articulation(rig, pushes, monkeypatch):
    monkeypatch.setattr(host_io, "set_instance_transform_slot",
                        lambda *a: True)
    monkeypatch.setattr(host_io, "set_instance_sim_source", lambda *a: True)
    player = _Obj()
    player._articulation_leaf = LEAF
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = IID
    session.player = player
    articulation.force_part_pose(
        player, "left wing", part_pose.pose_from6((0, 0, 0, 0, 45.0, 0)))
    host_loop._sync_instance_transforms(
        _FakeRenderer(), session, player, NativeTransformBuffer(), 0.5,
        game_time=1.0, model_scale=2.0)
    assert pushes == []


def test_realize_pushes_the_current_pose_once():
    """Both realize sites push the ship's current pose right after its sim
    source, so a ship that articulated before it was realized is drawn (and
    traced) posed from its first frame."""
    src = inspect.getsource(host_loop)
    calls = [m.start() for m in re.finditer(r"^\s+_mark_sim_source\(", src,
                                            re.MULTILINE)]
    assert len(calls) == 2, "expected exactly two realize sites"
    for at in calls:
        nxt = src[at:].splitlines()[1].strip()
        assert nxt.startswith("_sync_ship_articulation("), nxt


def test_push_articulation_skips_an_unrealized_ship(rig, pushes):
    ship = _Ship()
    session = _Session(_Ship())
    articulation.force_pose(ship, "cruise")
    host_loop._push_articulation(session, ship)
    assert pushes == []
