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


def test_selecting_a_transformation_poses_only_that_part_and_locks_mounts(
        make_panel):
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
    assert poses["left wing01"] == part_pose.IDENTITY, (
        "the other wing stays at the NIF pose -- this part only")

    parts = _parts(p)
    assert parts["mount_editing_enabled"] is False
    assert parts["mount_editing_reason"] == (
        "Posing Warp Transformation on left wing — mount editing is locked")
    warp = [r for r in _children(p, "left wing") if r.get("state") == "warp"][0]
    assert warp["chosen"] is True
    assert _part_row(p, "left wing")["chosen"] is False

    assert p.dispatch_event("select_pin:0") is False
    assert p.selected_index is None


def test_selecting_anything_else_returns_to_the_nif_pose(make_panel):
    ship = _RiggedShip()
    p, _ship, _target = make_panel(leaf=RIGGED_LEAF, ship=ship)

    def _posed():
        return not part_pose.is_identity(ship._articulation_poses["left wing"])

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

    # Closing the viewer.
    _select_node(p, "left wing", "warp")
    assert _posed()
    p.close()
    assert _all_nif()


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
