"""A part's rules are child NODES: Anchor, one {State} Transformation per
state, and Breakage (spec 2026-09-25 section 7).

Every test here asserts on what the CEF receives (`render_payload`'s
`model_parts` block), on the staged `_pending_part` spec, on what the writer
is handed, or on `ship._articulation_poses` -- the dict the mesh, the pins and
the derived-box queries all read. Never on a private helper's return alone.

Two fixture shapes, one factory:

* an UNRIGGED leaf (the default), so "left wing" starts with nothing authored
  and every Add action has something to do;
* the Bird of Prey leaf plus a ship that resolves to its rig, for the tests
  that need `articulation.force_part_pose` to find parts to pose.
"""
import copy
import json

import pytest

from engine.appc import articulation, part_pose
from engine.appc import hardpoint_override_writer as writer
from engine.appc.articulated_part import STATES
from engine.ui import ship_property_viewer as spv
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

UNRIGGED_LEAF = "spvnodetest"
RIGGED_LEAF = "birdofprey"

NO_ANCHOR_TOAST = "Add an anchor first — transformations swing around it"
ANCHOR_IN_USE_TOAST = "Remove the transformations first — they swing around the anchor"

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

# Three levels, as host_io.model_nodes reports a real hull: Scene Root's
# children are the part candidates, and the exporter plumbing beneath a part
# is not one.
_PART_NODES = [
    {"name": "left wing", "parent": "Scene Root", "candidate": True,
     "bounds_min": (-1.0, -0.5, -0.5), "bounds_max": (-0.1, 0.5, 0.5)},
    {"name": "__NDL_MultiMtl_Node", "parent": "left wing", "candidate": False,
     "bounds_min": (-1.0, -0.5, -0.5), "bounds_max": (-0.1, 0.5, 0.5)},
    {"name": "head", "parent": "Scene Root", "candidate": True,
     "bounds_min": (-0.1, 0.1, -0.1), "bounds_max": (0.1, 0.9, 0.1)},
]
LEFT_WING_BOX_CENTRE = (-0.55, 0.0, 0.0)


class _FakeSubsystem:
    def GetPosition(self):
        return (0.0, 0.0, 0.0)

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0


class _FakeShip:
    def __init__(self):
        self._hull = _FakeSubsystem()

    def GetHull(self):
        return self._hull

    def GetSensorSubsystem(self):
        return self._hull


class _RiggedShip(_FakeShip):
    """Resolves to the Bird of Prey rig (conftest's frozen fixture rig: both
    wings anchored, cruise/yellow/warp posed at +/-45 degrees, red unset)."""

    def __init__(self):
        super().__init__()
        self._articulation_leaf = RIGGED_LEAF
        self._articulation_poses = {}


class _Target:
    def __init__(self):
        self.calls = []

    def write(self, leaf, edits):
        self.calls.append((leaf, list(edits)))


@pytest.fixture
def make_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    target = _Target()
    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(d, emitters=[]) for d in _DESCRIPTORS])
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: target)

    def _make(leaf=UNRIGGED_LEAF, ship=None):
        monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda s: leaf)
        the_ship = ship if ship is not None else _FakeShip()
        p = ShipPropertyViewerPanel(ship_getter=lambda: the_ship)
        p.open()
        p._model_part_nodes = [dict(n) for n in _PART_NODES]
        return p, the_ship, target
    return _make


# ── payload readers ──────────────────────────────────────────────────────────

def _payload(p):
    p._last_pushed = None
    js = p.render_payload()
    prefix = "setShipPropertyViewer("
    assert js.startswith(prefix) and js.endswith(");"), js
    return json.loads(js[len(prefix):-2])


def _parts(p):
    return _payload(p)["model_parts"]


def _part_row(p, name):
    rows = [r for r in _parts(p)["rows"]
            if r["kind"] == "part" and r["name"] == name]
    assert len(rows) == 1, "exactly one row per part"
    return rows[0]


def _children(p, name):
    """The depth-1 rows that follow `name`'s part row, in display order."""
    rows = _parts(p)["rows"]
    out, inside = [], False
    for r in rows:
        if r["depth"] == 0:
            inside = (r["kind"] == "part" and r["name"] == name)
            continue
        if inside:
            out.append(r)
    return out


def _labels(p, name):
    return [r["label"] for r in _children(p, name)]


def _add_state(p, name, state):
    return p.dispatch_event(
        "part/add_state:" + json.dumps({"name": name, "state": state}))


def _select_node(p, name, kind):
    return p.dispatch_event(
        "part/select_node:" + json.dumps({"name": name, "kind": kind}))


def _remove(p, name, kind):
    return p.dispatch_event(
        "part/remove:" + json.dumps({"name": name, "kind": kind}))


# ── the tests ────────────────────────────────────────────────────────────────

def test_add_anchor_starts_at_the_parts_box_centre(make_panel):
    p, _ship, _target = make_panel()
    assert _labels(p, "left wing") == [], "fixture: nothing authored yet"
    assert _part_row(p, "left wing")["has_anchor"] is False

    assert p.dispatch_event("part/add_anchor:left wing") is True

    assert p._pending_part["left wing"]["anchor"] == pytest.approx(
        LEFT_WING_BOX_CENTRE)
    kids = _children(p, "left wing")
    assert [k["label"] for k in kids] == ["Anchor"]
    assert kids[0]["kind"] == "anchor"
    assert kids[0]["part"] == "left wing"
    assert kids[0]["depth"] == 1
    assert kids[0]["value"] == pytest.approx(2.0), "the transition, default 2 s"
    row = _part_row(p, "left wing")
    assert row["has_anchor"] is True
    assert row["dirty"] is True
    assert _labels(p, "head") == [], "only the named part gains an anchor"

    # One anchor at most: a second Add is a no-op, even after it has moved.
    spec = dict(p._pending_part["left wing"])
    spec["anchor"] = (0.1, 0.2, 0.3)
    p._pending_part["left wing"] = spec
    p.dispatch_event("part/add_anchor:left wing")
    assert p._pending_part["left wing"]["anchor"] == (0.1, 0.2, 0.3)
    assert _labels(p, "left wing") == ["Anchor"]


def test_add_transformation_without_anchor_toasts_and_changes_nothing(make_panel):
    p, _ship, _target = make_panel()
    assert _parts(p)["toast"] is None, "no toast until something is refused"
    before = copy.deepcopy(p._pending_part)

    _add_state(p, "left wing", "warp")

    payload = _payload(p)
    parts = payload["model_parts"]
    assert parts["toast"] == NO_ANCHOR_TOAST
    assert "toast" not in payload, "the toast lives ONLY under model_parts"
    assert p._pending_part == before
    assert not any(r.get("label") == "Warp Transformation"
                   for r in parts["rows"])
    assert p._undo_stack == [], "a refusal is not an undoable edit"


def test_each_state_can_be_added_once(make_panel):
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")

    _add_state(p, "left wing", "warp")
    _add_state(p, "left wing", "warp")

    assert _labels(p, "left wing").count("Warp Transformation") == 1
    assert _labels(p, "left wing") == ["Anchor", "Warp Transformation"]
    assert p._pending_part["left wing"]["poses"] == {
        "warp": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)}, "a new pose is the NIF pose"
    assert _part_row(p, "left wing")["missing_states"] == [
        "cruise", "yellow", "red"]

    # Rows follow STATES order, not the order they were added in.
    _add_state(p, "left wing", "cruise")
    assert _labels(p, "left wing") == [
        "Anchor", "Cruising Transformation", "Warp Transformation"]
    warp_row = [k for k in _children(p, "left wing")
                if k["label"] == "Warp Transformation"][0]
    assert warp_row["kind"] == "state"
    assert warp_row["state"] == "warp"
    assert warp_row["part"] == "left wing"
    assert warp_row["depth"] == 1

    # A state outside STATES is refused outright.
    assert _add_state(p, "left wing", "REd") is False
    assert set(p._pending_part["left wing"]["poses"]) == {"cruise", "warp"}


def test_remove_anchor_with_poses_is_refused(make_panel):
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")
    _add_state(p, "left wing", "warp")
    anchor = p._pending_part["left wing"]["anchor"]

    _remove(p, "left wing", "anchor")

    parts = _parts(p)
    assert parts["toast"] == ANCHOR_IN_USE_TOAST
    assert p._pending_part["left wing"]["anchor"] == anchor
    assert _labels(p, "left wing") == ["Anchor", "Warp Transformation"]

    # Once the transformation is gone the anchor can go too.
    _remove(p, "left wing", "warp")
    assert _labels(p, "left wing") == ["Anchor"]
    _remove(p, "left wing", "anchor")
    assert p._pending_part["left wing"]["anchor"] is None
    assert _labels(p, "left wing") == []
    assert _part_row(p, "left wing")["has_anchor"] is False


def _rig_pose(name, state):
    part = next(q for q in articulation.rig_for(RIGGED_LEAF)
                if q.GetName() == name)
    return part_pose.pose_from6(part.pose6_for(state))


def test_selecting_a_transformation_poses_every_part_in_that_state_and_locks_mounts(
        make_panel):
    """A selected State node previews the WHOLE SHIP in that state (Mark,
    2026-09-26). REPLACES "poses only that part" -- the old assertion that
    the other wing stays at the NIF pose was changed by Mark's request, not
    weakened."""
    ship = _RiggedShip()
    p, _ship, _target = make_panel(leaf=RIGGED_LEAF, ship=ship)
    p6 = (0.0, 0.1, 0.0, 0.0, 30.0, 0.0)
    spec = copy.deepcopy(p._effective_part("left wing"))
    spec["poses"]["warp"] = p6
    p._pending_part["left wing"] = spec
    assert all(part_pose.is_identity(v)
               for v in ship._articulation_poses.values()), (
        "fixture: open() starts every part at the NIF pose")

    assert _select_node(p, "left wing", "warp") is True

    poses = ship._articulation_poses
    assert set(poses) == {"left wing", "left wing01"}
    assert poses["left wing"] == part_pose.pose_from6(p6)
    assert not part_pose.is_identity(_rig_pose("left wing01", "warp")), (
        "fixture: the other wing's baked warp pose is not the NIF pose")
    assert poses["left wing01"] == _rig_pose("left wing01", "warp"), (
        "the other wing is previewed in the same state")

    parts = _parts(p)
    assert parts["mount_editing_enabled"] is False
    assert parts["mount_editing_reason"] == (
        "Posing Warp Transformation on left wing — mount editing is locked")
    warp = [r for r in _children(p, "left wing") if r.get("state") == "warp"][0]
    assert warp["chosen"] is True
    assert _part_row(p, "left wing")["chosen"] is False

    # An EDIT to a mount is still refused while the State node is selected:
    # the lock guards editing, not selecting.
    radius_before = dict(p._pending_radius)
    assert p.dispatch_event('set_radius:{"i":0,"value":0.9}') is False
    assert p._pending_radius == radius_before
    assert poses["left wing"] == part_pose.pose_from6(p6), "still posed"


@pytest.mark.parametrize("action", [
    "select_pin:0", "select_light:0",
    'select_emitter:{"i":0,"j":0}',
])
def test_selecting_a_mount_under_a_state_node_leaves_the_pose(
        make_panel, action):
    """Ruling 17 (spec 7.3, "selecting anything else returns the part to
    the NIF pose"). FLIPPED from the plan's refusal: a mount click while a
    State node is selected first drops the State node -- the part returns
    to the NIF pose and the lock lifts -- and THEN selects the mount."""
    ship = _RiggedShip()
    p, _ship, _target = make_panel(leaf=RIGGED_LEAF, ship=ship)
    p6 = (0.0, 0.1, 0.0, 0.0, 30.0, 0.0)
    spec = copy.deepcopy(p._effective_part("left wing"))
    spec["poses"]["warp"] = p6
    p._pending_part["left wing"] = spec
    if action.startswith("select_emitter:"):
        p._pending_emitter[0] = [{
            "kind": "point", "position": (0.0, 0.5, 0.0),
            "color": (1.0, 1.0, 1.0), "intensity": 1.0, "radius": 0.1}]
    assert _select_node(p, "left wing", "warp") is True
    assert p._mount_editing_enabled() is False, "fixture: locked"

    assert p.dispatch_event(action) is True

    assert spv.selected_part_node() is None
    assert ship._articulation_poses["left wing"] == part_pose.IDENTITY
    assert p._mount_editing_enabled() is True
    parts = _parts(p)
    assert parts["mount_editing_enabled"] is True
    assert parts["mount_editing_reason"] is None
    if action.startswith("select_pin:"):
        assert p.selected_index == 0
    elif action.startswith("select_light:"):
        assert p._selected_light_index == 0
    else:
        assert p._selected_emitter == (0, 0)


def test_selecting_anything_else_returns_to_the_nif_pose(make_panel):
    ship = _RiggedShip()
    p, _ship, _target = make_panel(leaf=RIGGED_LEAF, ship=ship)

    def _posed():
        # BOTH wings: a State node previews every part (Mark, 2026-09-26).
        return all(not part_pose.is_identity(ship._articulation_poses[n])
                   for n in ("left wing", "left wing01"))

    def _all_nif():
        return all(v == part_pose.IDENTITY
                   for v in ship._articulation_poses.values())

    # Another node of the same part.
    _select_node(p, "left wing", "warp")
    assert _posed(), "fixture: the rig's warp pose is not the NIF pose"
    _select_node(p, "left wing", "anchor")
    assert _all_nif()
    parts = _parts(p)
    assert parts["mount_editing_enabled"] is True
    assert parts["mount_editing_reason"] is None

    # The part row itself.
    _select_node(p, "left wing", "warp")
    assert _posed()
    p.dispatch_event("model_parts/select:left wing")
    assert _all_nif()
    assert _part_row(p, "left wing")["chosen"] is True
    assert all(k["chosen"] is False for k in _children(p, "left wing"))

    # The Breakage node.
    if p._effective_part("left wing").get("break") is None:
        assert p.dispatch_event("part/make_breakable:left wing") is True
    assert p._part_node_exists("left wing", "breakage"), "fixture"
    _select_node(p, "left wing", "warp")
    assert _posed()
    _select_node(p, "left wing", "breakage")
    assert _all_nif()

    # Closing the viewer.
    _select_node(p, "left wing", "warp")
    assert _posed()
    p.close()
    assert _all_nif()


@pytest.mark.parametrize("source", ["baked", "staged", "saved"])
def test_the_other_parts_state_pose_comes_from_its_effective_spec(
        make_panel, source):
    """Selecting part A's Warp node poses part B at B's EFFECTIVE warp pose,
    wherever it lives: baked in the rig, staged this session, or saved this
    session."""
    ship = _RiggedShip()
    p, _ship, _target = make_panel(leaf=RIGGED_LEAF, ship=ship)
    want = _rig_pose("left wing01", "warp")
    if source != "baked":
        p6b = (0.02, -0.03, 0.01, 5.0, -40.0, 12.0)
        spec = copy.deepcopy(p._effective_part("left wing01"))
        spec["poses"]["warp"] = p6b
        if source == "staged":
            p._pending_part["left wing01"] = spec
        else:
            p._saved_part["left wing01"] = spec
        want = part_pose.pose_from6(p6b)

    assert _select_node(p, "left wing", "warp") is True

    assert ship._articulation_poses["left wing01"] == want
    assert ship._articulation_poses["left wing"] == _rig_pose(
        "left wing", "warp")


def test_a_part_with_no_pose_for_that_state_stays_at_the_nif_pose(make_panel):
    """Red is unset on the fixture rig: give ONLY the left wing a Red pose,
    and add a fresh part (head) posed only in Cruise. Selecting the left
    wing's Red node poses the left wing alone -- the other wing (a rig part)
    and the head (a fresh part) have no Red pose, so they stay at the NIF
    pose."""
    ship = _RiggedShip()
    p, _ship, _target = make_panel(leaf=RIGGED_LEAF, ship=ship)
    assert "red" not in p._effective_part("left wing01")["poses"], "fixture"
    assert _add_state(p, "left wing", "red") is True
    red6 = (0.0, 0.05, 0.0, 0.0, 20.0, 0.0)
    spec = copy.deepcopy(p._pending_part["left wing"])
    spec["poses"]["red"] = red6
    p._pending_part["left wing"] = spec
    p.dispatch_event("part/add_anchor:head")
    _add_state(p, "head", "cruise")
    spec = copy.deepcopy(p._pending_part["head"])
    spec["poses"]["cruise"] = (0.0, 0.1, 0.0, 15.0, 0.0, 0.0)
    p._pending_part["head"] = spec

    assert _select_node(p, "left wing", "red") is True

    poses = ship._articulation_poses
    assert poses["left wing"] == part_pose.pose_from6(red6)
    assert poses.get("left wing01", part_pose.IDENTITY) == part_pose.IDENTITY
    assert poses.get("head", part_pose.IDENTITY) == part_pose.IDENTITY

    # ...while the head's Cruise node poses the head AND both rig wings.
    assert _select_node(p, "head", "cruise") is True
    poses = ship._articulation_poses
    assert not part_pose.is_identity(poses["head"])
    assert poses["left wing"] == _rig_pose("left wing", "cruise")
    assert poses["left wing01"] == _rig_pose("left wing01", "cruise")


def test_editing_the_selected_pose_keeps_every_other_part_posed(make_panel):
    """An edit re-posts the whole state: the other parts stay posed while
    the selected one moves -- a stepper, a gizmo drag (no dispatch) and an
    undo alike."""
    ship = _RiggedShip()
    p, _ship, _target = make_panel(leaf=RIGGED_LEAF, ship=ship)
    other = _rig_pose("left wing01", "warp")
    assert _select_node(p, "left wing", "warp") is True
    before = ship._articulation_poses["left wing"]

    assert p.dispatch_event('rotate_nudge:{"axis":2,"delta":7.5}') is True

    poses = ship._articulation_poses
    assert poses["left wing01"] == other, "the other wing stays posed"
    assert poses["left wing"] != before
    assert poses["left wing"] == part_pose.pose_from6(
        p._pending_part["left wing"]["poses"]["warp"])

    # A path that bypasses dispatch_event (a gizmo drag stages directly).
    p6 = (0.01, 0.02, 0.03, 1.0, 2.0, 3.0)
    p._stage_part_pose("left wing", "warp", p6)
    assert ship._articulation_poses["left wing"] == part_pose.pose_from6(p6)
    assert ship._articulation_poses["left wing01"] == other

    p.dispatch_event("undo")
    assert ship._articulation_poses["left wing01"] == other


def test_a_state_previews_every_fresh_part_and_the_render_sync_pushes_each(
        make_panel, monkeypatch):
    """Fresh (non-rig) parts preview together too (Ruling 10), and the
    render sync pushes a matrix for every posed name."""
    from engine import host_io, host_loop
    ship = _UnriggedShip()
    p, _ship, _target = make_panel(ship=ship)
    assert articulation.rig_for(UNRIGGED_LEAF) == (), "fixture: no rig"
    want = {"head": (0.0, 0.1, 0.05, 20.0, 0.0, 0.0),
            "left wing": (0.02, 0.0, -0.01, 0.0, 30.0, -10.0)}
    for name, p6 in want.items():
        p.dispatch_event("part/add_anchor:" + name)
        _add_state(p, name, "warp")
        spec = copy.deepcopy(p._pending_part[name])
        spec["poses"]["warp"] = p6
        p._pending_part[name] = spec

    assert _select_node(p, "head", "warp") is True

    assert ship._articulation_poses == {
        n: part_pose.pose_from6(p6) for n, p6 in want.items()}
    seen = []
    monkeypatch.setattr(
        host_io, "set_instance_node_transform",
        lambda iid, node, m16: seen.append((node, tuple(m16))))
    session = type("S", (), {"ship_articulation": {}})()
    host_loop._sync_ship_articulation(session, ship, 3)
    assert sorted(seen) == sorted(
        (n, tuple(part_pose.matrix4_model(part_pose.pose_from6(p6),
                                          articulation.MODEL_TO_SHIP)))
        for n, p6 in want.items())


def test_breakage_is_edited_as_a_percentage(make_panel):
    p, _ship, _target = make_panel()
    assert _part_row(p, "left wing")["breakable"] is False

    assert p.dispatch_event("part/make_breakable:left wing") is True
    kids = _children(p, "left wing")
    assert [k["label"] for k in kids] == ["Breakage"]
    assert kids[0]["kind"] == "breakage"
    assert kids[0]["value"] == pytest.approx(20.0)
    assert p._pending_part["left wing"]["break"] == pytest.approx(0.20)
    assert _part_row(p, "left wing")["breakable"] is True

    p.dispatch_event(
        'part/set_break:{"name":"left wing","percent":35}')
    assert p._pending_part["left wing"]["break"] == pytest.approx(0.35)
    assert _children(p, "left wing")[0]["value"] == pytest.approx(35.0)

    for bad in (0, 150, -5):
        assert p.dispatch_event(
            'part/set_break:{"name":"left wing","percent":%s}' % bad) is False
        assert p._pending_part["left wing"]["break"] == pytest.approx(0.35)

    # 100% is the top of the range, not outside it.
    p.dispatch_event('part/set_break:{"name":"left wing","percent":100}')
    assert p._pending_part["left wing"]["break"] == pytest.approx(1.0)

    # Make Breakable is hidden once present; dispatched anyway, it is a no-op.
    p.dispatch_event("part/make_breakable:left wing")
    assert p._pending_part["left wing"]["break"] == pytest.approx(1.0)


def test_transition_seconds_must_be_positive(make_panel):
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")

    p.dispatch_event('part/set_transition:{"name":"left wing","seconds":3.5}')
    assert p._pending_part["left wing"]["transition"] == pytest.approx(3.5)
    assert _children(p, "left wing")[0]["value"] == pytest.approx(3.5)

    for bad in (0, -1.0):
        assert p.dispatch_event(
            'part/set_transition:{"name":"left wing","seconds":%s}' % bad
        ) is False
        assert p._pending_part["left wing"]["transition"] == pytest.approx(3.5)


def test_save_emits_only_the_new_calls_and_round_trips(make_panel):
    p, _ship, target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")
    _add_state(p, "left wing", "warp")
    p.dispatch_event("part/make_breakable:left wing")
    anchor = tuple(p._pending_part["left wing"]["anchor"])

    assert p.dispatch_event("save") is True

    assert target.calls, "write() was never called"
    leaf, edits = target.calls[-1]
    assert leaf == UNRIGGED_LEAF
    part_edits = [e for e in edits if e[1] == "__part__"]
    assert part_edits == [("left wing", "__part__", [
        ("SetAnchor", anchor),
        ("SetTransitionSeconds", (2.0,)),
        ("SetStatePose", ("warp", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        ("SetBreakFraction", (0.2,)),
    ])]
    setters = [c[0] for c in part_edits[0][2]]
    for legacy in ("SetPivot", "SetAxis", "SetStateAngle", "SetDetachFraction"):
        assert legacy not in setters

    # What the writer emits reads back as the same calls.
    calls = part_edits[0][2]
    models = {}
    writer.set_part(models, leaf, "left wing", calls)
    again = writer.read_models_from_source(writer.emit(models))
    assert again[leaf]["__parts__"]["left wing"] == [
        (s, tuple(a)) for (s, a) in calls]

    # Saved edits keep driving the pane; nothing is pending any more.
    assert p._pending_part == {}
    assert _labels(p, "left wing") == [
        "Anchor", "Warp Transformation", "Breakage"]
    assert _part_row(p, "left wing")["dirty"] is False


def test_every_part_edit_is_undoable(make_panel):
    p, _ship, _target = make_panel()

    def _spec():
        return copy.deepcopy(p._pending_part)

    edits = [
        "part/add_anchor:left wing",
        'part/add_state:{"name":"left wing","state":"warp"}',
        "part/make_breakable:left wing",
        'part/set_break:{"name":"left wing","percent":40}',
        'part/set_transition:{"name":"left wing","seconds":4.0}',
        'part/remove:{"name":"left wing","kind":"warp"}',
        'part/remove:{"name":"left wing","kind":"breakage"}',
    ]
    history = []
    for action in edits:
        history.append(_spec())
        assert p.dispatch_event(action) is True, action
        assert _spec() != history[-1], "fixture: %s changed nothing" % action

    for action, before in reversed(list(zip(edits, history))):
        p.dispatch_event("undo")
        assert _spec() == before, "undo of %s" % action

    assert p._pending_part == {}
    assert _labels(p, "left wing") == []


# ── fix round 1 ──────────────────────────────────────────────────────────────

class _UnriggedShip(_FakeShip):
    """Resolves to a leaf with NO rig snapshot: every part is fresh."""

    def __init__(self):
        super().__init__()
        self._articulation_leaf = UNRIGGED_LEAF


def test_a_fresh_part_previews_posed(make_panel, monkeypatch):
    """A part no hardpoint file has rigged yet must still be DRAWN posed when
    its State Transformation is selected -- the mounts lock, so the mesh has
    to move too."""
    from engine import host_io, host_loop
    ship = _UnriggedShip()
    p, _ship, _target = make_panel(ship=ship)
    assert articulation.rig_for(UNRIGGED_LEAF) == (), "fixture: no rig"
    p.dispatch_event("part/add_anchor:head")
    _add_state(p, "head", "warp")
    p6 = (0.0, 0.1, 0.05, 20.0, 0.0, 0.0)
    spec = copy.deepcopy(p._pending_part["head"])
    spec["poses"]["warp"] = p6
    p._pending_part["head"] = spec

    assert _select_node(p, "head", "warp") is True

    assert ship._articulation_poses["head"] == part_pose.pose_from6(p6)
    seen = []
    monkeypatch.setattr(
        host_io, "set_instance_node_transform",
        lambda iid, node, m16: seen.append((node, tuple(m16))))
    session = type("S", (), {"ship_articulation": {}})()
    host_loop._sync_ship_articulation(session, ship, 3)
    assert seen == [("head", tuple(part_pose.matrix4_model(
        part_pose.pose_from6(p6), articulation.MODEL_TO_SHIP)))]


def _roundtrip(models, edits, leaf):
    for name, _tag, calls in edits:
        writer.set_part(models, leaf, name, calls)
    text = writer.emit(models)
    return text, writer.read_models_from_source(text)


def test_emptying_a_baked_part_deletes_its_block(make_panel):
    """Removing every node of a part the file already carries must persist
    as a DELETION, or the block comes straight back on reload."""
    from engine.appc.articulated_part import STATES
    p, _ship, target = make_panel(leaf=RIGGED_LEAF, ship=_RiggedShip())
    baked = p._effective_part("left wing")
    for state in STATES:
        if state in baked["poses"]:
            _remove(p, "left wing", state)
    _remove(p, "left wing", "anchor")
    _remove(p, "left wing", "breakage")
    assert _labels(p, "left wing") == [], "fixture: every node removed"

    assert p.dispatch_event("save") is True
    _leaf, edits = target.calls[-1]
    part_edits = [e for e in edits if e[1] == "__part__"]
    assert part_edits == [("left wing", "__part__", [])]

    # The file as it stood carries the block; the save deletes it.
    models = {}
    writer.set_part(models, RIGGED_LEAF, "left wing",
                    [("SetAnchor", (-0.16, 0.0, 0.05)),
                     ("SetBreakFraction", (0.2,))])
    writer.set_part(models, RIGGED_LEAF, "left wing01",
                    [("SetBreakFraction", (0.2,))])
    text, again = _roundtrip(models, part_edits, RIGGED_LEAF)
    assert '"left wing"' not in text
    assert set(again[RIGGED_LEAF]["__parts__"]) == {"left wing01"}


def test_a_fresh_part_added_then_removed_leaves_no_block(make_panel):
    p, _ship, target = make_panel()
    p.dispatch_event("part/add_anchor:head")
    _remove(p, "head", "anchor")
    assert p.dispatch_event("save") is True
    _leaf, edits = target.calls[-1]
    part_edits = [e for e in edits if e[1] == "__part__"]
    assert part_edits == [("head", "__part__", [])]
    text, again = _roundtrip({}, part_edits, UNRIGGED_LEAF)
    assert "ArticulatedPartProperty_Create" not in text
    assert "__parts__" not in again.get(UNRIGGED_LEAF, {})


# ── popups + auto-select (2026-09-26, supersedes the inline fields) ─────────
#
# A part's attributes are set in popups (Add/Edit Anchor, Make Breakable/Edit
# Breakage, the Add State Transformation picker) rather than inline fields
# on the tree rows, and every add selects the node it made.

def _picker(p):
    return _parts(p)["add_state_picker"]


def test_add_anchor_with_seconds_selects_the_anchor_under_move(make_panel):
    p, _ship, _target = make_panel()
    p.active_tool = "scale"
    p.selected_index = 0

    assert p.dispatch_event("part/add_anchor:" + json.dumps(
        {"name": "left wing", "seconds": 3.25})) is True

    spec = p._pending_part["left wing"]
    assert spec["anchor"] == pytest.approx(LEFT_WING_BOX_CENTRE)
    assert spec["transition"] == pytest.approx(3.25)
    assert _children(p, "left wing")[0]["value"] == pytest.approx(3.25)
    assert spv.selected_part_node() == ("left wing", "anchor")
    assert _children(p, "left wing")[0]["chosen"] is True
    assert p.active_tool == "transform", "the Move gizmo IS the anchor marker"
    assert p.selected_index is None, "a node selection clears the mount one"
    assert p._selected_light_index is None
    assert p._selected_emitter is None


def test_add_anchor_bare_form_defaults_to_two_seconds(make_panel):
    p, _ship, _target = make_panel()
    assert p.dispatch_event("part/add_anchor:head") is True
    assert p._pending_part["head"]["transition"] == pytest.approx(2.0)
    assert spv.selected_part_node() == ("head", "anchor")


@pytest.mark.parametrize("bad", [0, -1.0, "x", None])
def test_add_anchor_refuses_a_bad_transition(make_panel, bad):
    p, _ship, _target = make_panel()
    assert p.dispatch_event("part/add_anchor:" + json.dumps(
        {"name": "left wing", "seconds": bad})) is False
    assert p._pending_part == {}
    assert spv.selected_part_node() is None


def test_make_breakable_with_percent_selects_the_breakage(make_panel):
    p, _ship, _target = make_panel()
    p.selected_index = 0

    assert p.dispatch_event("part/make_breakable:" + json.dumps(
        {"name": "left wing", "percent": 35})) is True

    assert p._pending_part["left wing"]["break"] == pytest.approx(0.35)
    assert spv.selected_part_node() == ("left wing", "breakage")
    kids = _children(p, "left wing")
    assert [k["label"] for k in kids] == ["Breakage"]
    assert kids[0]["chosen"] is True
    assert kids[0]["value"] == pytest.approx(35.0)
    assert p.selected_index is None


def test_make_breakable_bare_form_defaults_to_twenty_percent(make_panel):
    p, _ship, _target = make_panel()
    assert p.dispatch_event("part/make_breakable:head") is True
    assert p._pending_part["head"]["break"] == pytest.approx(0.20)
    assert spv.selected_part_node() == ("head", "breakage")


@pytest.mark.parametrize("bad", [0, 150, -5, "x"])
def test_make_breakable_refuses_a_bad_percent(make_panel, bad):
    p, _ship, _target = make_panel()
    assert p.dispatch_event("part/make_breakable:" + json.dumps(
        {"name": "left wing", "percent": bad})) is False
    assert p._pending_part == {}


def test_add_state_selects_and_poses_that_state(make_panel):
    ship = _UnriggedShip()
    ship._articulation_poses = {}
    p, _ship, _target = make_panel(ship=ship)
    p.dispatch_event("part/add_anchor:head")

    assert _add_state(p, "head", "warp") is True

    assert spv.selected_part_node() == ("head", "warp")
    warp = [k for k in _children(p, "head") if k.get("state") == "warp"][0]
    assert warp["chosen"] is True
    assert ship._articulation_poses["head"] == part_pose.pose_from6(
        p._pending_part["head"]["poses"]["warp"])
    assert p.active_tool == "transform"


def test_begin_add_state_without_an_anchor_toasts_and_opens_nothing(make_panel):
    p, _ship, _target = make_panel()
    assert _picker(p) is None, "closed by default"

    assert p.dispatch_event("part/begin_add_state:left wing") is True

    parts = _parts(p)
    assert parts["toast"] == NO_ANCHOR_TOAST
    assert parts["add_state_picker"] is None
    assert p._pending_part == {}
    assert p._undo_stack == []
    assert p._overlay_open is False


def test_begin_add_state_lists_the_missing_states_in_order(make_panel):
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")
    _add_state(p, "left wing", "yellow")
    undo_depth = len(p._undo_stack)

    assert p.dispatch_event("part/begin_add_state:left wing") is True

    assert _picker(p) == {"name": "left wing",
                          "states": ["cruise", "red", "warp"]}
    assert _parts(p)["toast"] is None
    assert len(p._undo_stack) == undo_depth, "opening the picker is not an edit"
    # The picker is an overlay: the 3D view must not orbit/pick under it.
    assert p._overlay_open is True

    assert _add_state(p, "left wing", "red") is True
    assert _picker(p) is None, "add_state closes the picker"
    assert p._overlay_open is False
    assert spv.selected_part_node() == ("left wing", "red")


def test_cancel_add_state_closes_the_picker_staging_nothing(make_panel):
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")
    before = copy.deepcopy(p._pending_part)
    undo_depth = len(p._undo_stack)
    p.dispatch_event("part/begin_add_state:left wing")
    assert _picker(p) is not None

    assert p.dispatch_event("part/cancel_add_state") is True

    assert _picker(p) is None
    assert p._pending_part == before
    assert len(p._undo_stack) == undo_depth
    assert p._overlay_open is False


def test_the_picker_blocks_viewport_input_even_after_overlay_0(make_panel):
    """The JS closes the context menu (overlay:0) around opening the picker;
    whatever order those arrive in, the 3D view stays blocked while the
    Python-driven picker is showing."""
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")
    p.dispatch_event("part/begin_add_state:left wing")
    p.dispatch_event("overlay:0")
    assert p._viewport_input_blocked() is True
    p.dispatch_event("part/cancel_add_state")
    assert p._viewport_input_blocked() is False


def test_esc_closes_the_picker_not_the_panel(make_panel):
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")
    p.dispatch_event("part/begin_add_state:left wing")

    p.handle_key_esc()

    assert p._visible is True
    payload = _payload(p)
    assert payload["model_parts"]["add_state_picker"] is None
    assert payload["close_overlays"] is True
    assert "left wing" in p._pending_part, "ESC keeps staged edits"


def test_the_picker_closes_on_reopen(make_panel):
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")
    p.dispatch_event("part/begin_add_state:left wing")
    p.close()
    p.open()
    p._model_part_nodes = [dict(n) for n in _PART_NODES]
    assert _picker(p) is None


@pytest.mark.parametrize("add, kind", [
    ("part/add_anchor:left wing", "anchor"),
    ('part/make_breakable:{"name":"left wing","percent":40}', "breakage"),
])
def test_each_add_is_one_undo_step_that_drops_its_selection(make_panel, add, kind):
    p, _ship, _target = make_panel()
    assert p.dispatch_event(add) is True
    assert spv.selected_part_node() == ("left wing", kind)
    assert len(p._undo_stack) == 1

    p.dispatch_event("undo")

    assert p._pending_part == {}
    assert _labels(p, "left wing") == []
    assert spv.selected_part_node() is None, "nothing selected that is gone"
    assert all(r["chosen"] is False for r in _children(p, "left wing"))


def test_add_state_is_one_undo_step_that_drops_its_selection(make_panel):
    ship = _UnriggedShip()
    ship._articulation_poses = {}
    p, _ship, _target = make_panel(ship=ship)
    p.dispatch_event("part/add_anchor:head")
    p.dispatch_event("part/begin_add_state:head")
    depth = len(p._undo_stack)
    _add_state(p, "head", "cruise")
    assert len(p._undo_stack) == depth + 1
    assert spv.selected_part_node() == ("head", "cruise")

    p.dispatch_event("undo")

    assert "cruise" not in p._pending_part["head"]["poses"]
    assert spv.selected_part_node() is None
    assert ship._articulation_poses.get("head", part_pose.IDENTITY) == \
        part_pose.IDENTITY, "back at the NIF pose"


@pytest.mark.parametrize("bad", [
    "part/add_state:{not json",
    'part/add_state:{"name":"no such part","state":"warp"}',
    'part/add_state:{"name":"left wing","state":"REd"}',
])
def test_an_invalid_add_state_still_closes_the_picker(make_panel, bad):
    """The JS hides the picker locally the moment Add is clicked, without
    overlay:0 -- so a REFUSED add_state must close it too, or an invisible
    picker keeps blocking the 3D view until ESC."""
    p, _ship, _target = make_panel()
    p.dispatch_event("part/add_anchor:left wing")
    p.dispatch_event("part/begin_add_state:left wing")
    assert _picker(p) is not None, "fixture: picker open"
    before = copy.deepcopy(p._pending_part)

    assert p.dispatch_event(bad) is False

    assert _picker(p) is None
    assert p._viewport_input_blocked() is False
    assert p._pending_part == before
