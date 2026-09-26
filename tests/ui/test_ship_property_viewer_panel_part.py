"""Panel-level integration for the Model Parts pane: selecting a part (row
or node) is exclusive with mount selection, the part ROW and its Breakage
node are NOT a gizmo target (the Anchor and State nodes are -- covered in
test_spv_part_gizmos.py), part edits stage and save as `__part__` writer edits, and posing a part locks
subsystem/light/emitter editing -- gated in `_dispatch_event_inner` itself,
not only by a greyed-out DOM, so a stale action string can never slip an edit
through. The node actions themselves are covered in test_spv_part_nodes.py.

Fixture mirrors test_ship_property_viewer_save_persistence.py.
"""
import json
import math

import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui import ship_property_viewer as spv
from engine.ui.ship_property_viewer import OrbitCamera
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

_DEFAULT_LIGHT_REGION = {
    "shape": "Sphere", "position": (0.0, 0.0, 0.0),
    "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
    "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
    "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}

_FAKE_DESCRIPTORS = [
    {
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
        "light": True, "light_region": dict(_DEFAULT_LIGHT_REGION),
        "emitters": [],
    },
    {
        "name": "Aft Impulse", "kind": "subsystem",
        "properties": {"position": (2.0, 0.0, 0.0), "radius": 0.5},
        "world_pos": (2.0, 0.0, 0.0), "parent_index": None,
        "light": False, "light_region": dict(_DEFAULT_LIGHT_REGION),
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


class _FakeShip:
    def __init__(self):
        self._hull = _FakeSubsystem()
        self._sensors = _FakeSubsystem()

    def GetHull(self):
        return self._hull

    def GetSensorSubsystem(self):
        return self._sensors


class _Target:
    """Captures every write() call instead of touching a real file."""

    def __init__(self):
        self.calls = []

    def write(self, leaf, edits):
        self.calls.append((leaf, list(edits)))


@pytest.fixture
def make_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod

    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(d, emitters=[dict(e) for e in d["emitters"]])
                      for d in _FAKE_DESCRIPTORS])
    target = _Target()
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: target)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "birdofprey")

    holder = {"ship": _FakeShip()}
    panel = ShipPropertyViewerPanel(ship_getter=lambda: holder["ship"])
    return panel, holder, target


def _open_with_parts(p):
    p.open()
    p._model_part_nodes = list(_PART_NODES)


def _select_node(p, name, kind):
    return p.dispatch_event(
        "part/select_node:" + json.dumps({"name": name, "kind": kind}))


def test_a_part_row_or_breakage_node_is_never_a_transform_target(make_panel):
    """Selecting a part row, or its Breakage node, leaves no transform
    target, so no gizmo is drawn and no Transform/Rotate/Scale panel
    appears. (The Anchor and State nodes ARE gizmo targets since the
    part-node gizmos landed -- test_spv_part_gizmos.py.)"""
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event("part/add_anchor:head")
    p.dispatch_event('part/add_state:{"name":"head","state":"warp"}')
    p.dispatch_event("part/make_breakable:head")
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    for tool in ("transform", "rotate", "scale"):
        p.active_tool = tool
        assert p.dispatch_event("model_parts/select:head") is True
        assert p._active_transform_target() is None
        assert p._active_gizmo() is None
        for kind in ("breakage",):
            assert _select_node(p, "head", kind) is True, kind
            assert p._active_transform_target() is None
            assert p._active_gizmo() is None
            assert p.transform_coords() is None
            assert p.rotate_values() is None
            assert p.scale_values() is None


def test_selecting_a_part_clears_subsystem_selection(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event("select_pin:0")
    assert p.selected_index == 0
    p.dispatch_event("model_parts/select:left wing")
    assert p.selected_index is None
    assert p._active_transform_target() is None


def test_selecting_a_part_node_clears_subsystem_selection(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event("select_light:0")
    assert p._selected_light_index == 0
    assert _select_node(p, "left wing", "anchor") is True
    assert p._selected_light_index is None
    assert spv.selected_part_node() == ("left wing", "anchor")


def test_selecting_a_subsystem_clears_the_part_selection(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    _select_node(p, "left wing", "anchor")
    p.dispatch_event("select_pin:0")
    assert spv.selected_model_part() is None
    assert spv.selected_part_node() is None
    assert p._active_transform_target() == ("subsystem", 0)


def test_add_state_rejects_an_unknown_state(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event("part/add_anchor:head")
    ok = p.dispatch_event('part/add_state:{"name":"head","state":"REd"}')
    assert ok is False
    assert p._pending_part["head"]["poses"] == {}


def test_removing_breakage_makes_the_part_unbreakable(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event("part/make_breakable:head")
    p.dispatch_event('part/set_break:{"name":"head","percent":35}')
    assert p._pending_part["head"]["break"] == pytest.approx(0.35)
    p.dispatch_event('part/remove:{"name":"head","kind":"breakage"}')
    assert p._pending_part["head"]["break"] is None


def test_forcing_an_articulated_state_locks_mount_editing(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    from engine.appc import articulation
    articulation.set_dev_override("cruise")    # 'K'; the rig's cruise is 45
    assert p._mount_editing_enabled() is False
    # The Python side is the real gate: a select_pin: action must be refused
    # outright, not merely greyed out in the DOM.
    assert p.dispatch_event("select_pin:0") is False
    assert p.selected_index is None


def test_leaving_a_state_node_unlocks_mount_editing(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    _select_node(p, "left wing", "cruise")
    assert p._mount_editing_enabled() is False
    assert p.dispatch_event("select_pin:0") is False
    _select_node(p, "left wing", "anchor")
    assert p._mount_editing_enabled() is True
    assert p.dispatch_event("select_pin:0") is True
    assert p.selected_index == 0


def test_part_editing_stays_available_while_locked(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    _select_node(p, "left wing", "cruise")
    assert p._mount_editing_enabled() is False
    assert p.dispatch_event(
        'part/add_state:{"name":"left wing","state":"red"}') is True
    assert "red" in p._pending_part["left wing"]["poses"]


def test_locked_mount_gizmo_verb_blocked_for_a_light_target(make_panel):
    """A mount selected BEFORE the lock engaged must still be refused --
    the lock is keyed on the ACTIVE TARGET's kind, not on when it was
    picked. (Selecting a state node clears the light, so the lock that can
    coexist with a selected light is the 'K' override's.)"""
    p, _holder, _target = make_panel
    _open_with_parts(p)
    assert p.dispatch_event("select_light:0") is True
    assert p._active_transform_target() == ("light", 0)
    from engine.appc import articulation
    articulation.set_dev_override("cruise")
    assert p._mount_editing_enabled() is False
    assert p.dispatch_event("mirror_element") is False
    assert 0 not in p._pending_light


def test_save_writes_a_part_edit(make_panel):
    p, _holder, target = make_panel
    _open_with_parts(p)
    p.dispatch_event("part/add_anchor:head")
    p.dispatch_event('part/add_state:{"name":"head","state":"cruise"}')
    p.dispatch_event("part/make_breakable:head")
    assert p.dispatch_event("save") is True
    assert target.calls, "write() was never called"
    leaf, edits = target.calls[-1]
    assert leaf == "birdofprey"
    part_edits = [e for e in edits if e[1] == "__part__"]
    assert len(part_edits) == 1
    name, _tag, calls = part_edits[0]
    assert name == "head"
    assert [c[0] for c in calls] == [
        "SetAnchor", "SetTransitionSeconds", "SetStatePose", "SetBreakFraction"]
    # Saved edits keep driving the in-session state; pending clears.
    assert "head" not in p._pending_part
    assert p._saved_part["head"]["anchor"] == pytest.approx((0.0, 0.5, 0.0))


def test_an_unbreakable_part_never_saves_a_break_call(make_panel):
    p, _holder, target = make_panel
    _open_with_parts(p)
    p.dispatch_event("part/add_anchor:head")
    assert p.dispatch_event("save") is True
    leaf, edits = target.calls[-1]
    name, _tag, calls = [e for e in edits if e[1] == "__part__"][0]
    assert name == "head"
    assert all(c[0] not in ("SetBreakFraction", "SetDetachFraction")
               for c in calls)


class _RotShip:
    """Just enough of a ship for transform_gizmo()/rotate_gizmo() to place an
    origin: identity world transform (no rotation/translation to account
    for)."""

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()   # identity


# ---------------------------------------------------------------------------
# Fix round 1, Finding 1: the mouse-driven gizmo drag path bypassed the lock
# entirely. _dispatch_event_inner only gates ACTION STRINGS; the reviewer's
# repro drove the raw drag functions directly (as the real per-frame mouse
# input does) and found a locked subsystem stayed fully draggable.
# ---------------------------------------------------------------------------
def _subsystem_panel(monkeypatch, light=False):
    import engine.ui.ship_property_viewer_panel as mod

    def _build(ship):
        out = []
        for d in _FAKE_DESCRIPTORS:
            row = dict(d, emitters=[dict(e) for e in d["emitters"]])
            if light:
                row["light"] = True
                row["light_region"] = {
                    "shape": "Cylinder", "position": tuple(row["properties"]["position"]),
                    "axis": (0.0, -1.0, 0.0), "radius": (0.3,),
                    "extent": (-2.0, 2.0), "scale": (0.25, 0.25, 0.25),
                }
            out.append(row)
        return out

    monkeypatch.setattr(mod, "build_descriptors", _build)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "birdofprey")
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RotShip())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._model_part_nodes = list(_PART_NODES)
    return p


def _lock_via_left_wing_cruise(p):
    """Engage the lock WITHOUT touching the mount selection: the 'K'
    override on a state whose rig poses are articulated (the BoP's cruise
    is 45 degrees). Selecting a state node would also lock, but it clears
    the mount selection first, so it cannot express these repros."""
    from engine.appc import articulation
    articulation.set_dev_override("cruise")
    assert p._mount_editing_enabled() is False


def test_mouse_drag_cannot_move_a_subsystem_selected_before_the_lock(monkeypatch):
    """The reviewer's exact repro, re-pointed at the 'K' lock: a subsystem
    selected before the lock stays the active gizmo target, so the raw drag
    functions must refuse on their own."""
    p = _subsystem_panel(monkeypatch)
    p.dispatch_event("select_pin:0")
    assert p._active_transform_target() == ("subsystem", 0)
    _lock_via_left_wing_cruise(p)
    before = p._effective_pos(0)
    p.dispatch_event("set_tool:transform")
    p._begin_axis_drag_for_test(axis=0, grab_param=0.0)
    p._apply_axis_drag(0.9)
    assert p._effective_pos(0) == before
    assert p._pending_pos == {}


def test_gizmo_input_refuses_to_begin_a_drag_on_a_locked_mount(monkeypatch):
    """The press-edge refusal in _handle_gizmo_input itself: a real gizmo
    exists (transform_gizmo() is non-None -- this is not "no gizmo to
    grab"), but the press must not start a drag at all while the target is
    a locked mount."""
    p = _subsystem_panel(monkeypatch)
    p.dispatch_event("select_pin:0")
    p.dispatch_event("set_tool:transform")
    assert p.transform_gizmo() is not None
    _lock_via_left_wing_cruise(p)
    assert p._current_target_is_locked_mount() is True
    consumed = p._handle_gizmo_input(400.0, 300.0, True, False, 1.0,
                                     lambda: (800, 600))
    assert consumed is False
    assert p._axis_drag is None


def test_apply_axis_drag_refuses_even_when_the_lock_engages_mid_gesture(monkeypatch):
    """Defence in depth, independent of _handle_gizmo_input's press-edge
    refusal: the drag BEGINS while unlocked (a legitimate grab), then the
    lock engages before the next per-frame apply call -- _apply_axis_drag's
    own guard must stop it from continuing."""
    p = _subsystem_panel(monkeypatch)
    p.dispatch_event("select_pin:0")
    p.dispatch_event("set_tool:transform")
    p._begin_axis_drag_for_test(axis=0, grab_param=0.0)   # begins UNLOCKED
    _lock_via_left_wing_cruise(p)                         # locks mid-gesture
    before = p._effective_pos(0)
    p._apply_axis_drag(0.9)
    assert p._effective_pos(0) == before


def test_ring_drag_cannot_rotate_a_locked_light_mount(monkeypatch):
    """Same repro, Rotate tool + a Cylinder light target (its `axis` is a
    mount-editing surface exactly like a subsystem's position)."""
    p = _subsystem_panel(monkeypatch, light=True)
    p.dispatch_event("select_light:0")
    assert p._active_transform_target() == ("light", 0)
    _lock_via_left_wing_cruise(p)
    before = p._effective_light(0)["axis"]
    p.dispatch_event("set_tool:rotate")
    p._begin_ring_drag(2, 0.0)
    p._apply_ring_drag_angle(math.radians(90.0))
    assert p._effective_light(0)["axis"] == before


# ---------------------------------------------------------------------------
# Fix round 1, Finding 2: the 'K' dev keybinding (engine/dev_keybindings.py)
# writes articulation.set_dev_override directly -- the lock must read that
# override live. (A shadow copy in ship_property_viewer, which only Preview
# would ever have written, has since been deleted outright.)
# ---------------------------------------------------------------------------
def test_the_K_dev_override_locks_mount_editing_without_touching_preview(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    from engine.appc import articulation
    articulation.set_dev_override("cruise")   # exactly what 'K' does, and
    # nothing else -- no panel event. The rig's baked cruise is 45 degrees.
    assert p._mount_editing_enabled() is False
    locked, reason = p._mount_lock_state_and_reason()
    assert locked is True
    assert reason


# ---------------------------------------------------------------------------
# The EVENT EDGES that apply the forced pose. `set_dev_override` alone only
# changes what the next `tick_ship` would ease toward -- and the SPV freezes
# the sim, so there is no next tick. Without these the viewer showed a stale
# pose and Preview moved nothing.
# ---------------------------------------------------------------------------

class _RiggedShip(_FakeShip):
    """A `_FakeShip` that resolves to the Bird of Prey rig."""

    def __init__(self):
        super().__init__()
        self._articulation_leaf = "birdofprey"
        self._articulation_poses = {}


def _poses(ship):
    return dict(ship._articulation_poses)


def test_opening_the_viewer_snaps_the_ship_to_the_ANCHOR_pose(make_panel):
    """Every part at the identity (NIF) pose -- the frame a hardpoint mount
    is stored in."""
    from engine.appc import articulation, part_pose
    p, holder, _target = make_panel
    holder["ship"] = _RiggedShip()
    holder["ship"]._articulation_poses = {
        part.GetName(): part.pose_for("cruise")
        for part in articulation.rig_for("birdofprey")}
    assert any(not part_pose.is_identity(v)
               for v in _poses(holder["ship"]).values()), "fixture check"

    _open_with_parts(p)

    assert _poses(holder["ship"]), "the rig must still be there"
    assert all(v == part_pose.IDENTITY
               for v in _poses(holder["ship"]).values()), (
        "opening the SPV must put the shared pose dict -- which the mesh, "
        "the pins and the derived-box queries all read -- at the anchor pose")


def test_selecting_a_state_node_snaps_that_part_to_its_authored_pose(
        make_panel):
    """Selecting a {State} Transformation has to MOVE the part, not just set
    a lock and a highlight -- and only that part."""
    from engine.appc import articulation, part_pose
    p, holder, _target = make_panel
    holder["ship"] = _RiggedShip()
    _open_with_parts(p)
    p._model_part_nodes.append(
        {"name": "left wing01", "parent": "Scene Root", "candidate": True,
         "bounds_min": (0.1, -0.5, -0.5), "bounds_max": (1.0, 0.5, 0.5)})

    assert _select_node(p, "left wing01", "cruise") is True

    part = next(q for q in articulation.rig_for("birdofprey")
                if q.GetName() == "left wing01")
    want = part_pose.pose_from6(part.pose6_for("cruise"))
    assert not part_pose.is_identity(want), "fixture check"
    poses = _poses(holder["ship"])
    assert poses["left wing01"] == want
    assert poses["left wing"] == part_pose.IDENTITY


def test_closing_the_viewer_returns_the_rig_to_the_NIF_pose(make_panel):
    """Spec section 7.3: closing the SPV returns a previewed part to the NIF
    pose -- the pose the viewer opened in -- and releases the 'K' override,
    so `tick_ship` eases the rig from there once the sim resumes."""
    from engine.appc import articulation, part_pose
    p, holder, _target = make_panel
    holder["ship"] = _RiggedShip()
    _open_with_parts(p)
    _select_node(p, "left wing", "cruise")
    assert not part_pose.is_identity(_poses(holder["ship"])["left wing"]), (
        "fixture check")
    articulation.set_dev_override("cruise")

    p.close()

    assert articulation.dev_override() is None, "the override must be released"
    assert all(v == part_pose.IDENTITY
               for v in _poses(holder["ship"]).values())


def test_close_clears_the_lock(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    _select_node(p, "left wing", "cruise")
    assert p._mount_editing_enabled() is False
    p.close()
    assert spv.selected_part_node() is None
    assert p._mount_editing_enabled() is True
