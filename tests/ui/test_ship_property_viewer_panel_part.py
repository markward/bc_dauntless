"""Panel-level integration for Task 7: selecting a model part makes it the
gizmo's transform target, angle/detach edits stage and save as `__part__`
writer edits, and previewing an articulated pose locks subsystem/light/
emitter editing -- gated in `_dispatch_event_inner` itself, not only by a
greyed-out DOM, so a stale action string can never slip an edit through.

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


def test_selecting_a_part_becomes_the_transform_target(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    assert p.dispatch_event("model_parts/select:left wing") is True
    assert p._active_transform_target() == ("part", "left wing")


def test_selecting_a_part_clears_subsystem_selection(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event("select_pin:0")
    assert p.selected_index == 0
    p.dispatch_event("model_parts/select:left wing")
    assert p.selected_index is None
    assert p._active_transform_target() == ("part", "left wing")


def test_selecting_a_subsystem_clears_the_part_selection(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event("model_parts/select:left wing")
    p.dispatch_event("select_pin:0")
    assert spv.selected_model_part() is None
    assert p._active_transform_target() == ("subsystem", 0)


def test_transform_gizmo_places_the_part_pivot(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.set_part_pivot("left wing", (-0.16, 0.0, 0.05))
    assert p._pending_part["left wing"]["pivot"] == (-0.16, 0.0, 0.05)
    assert p._target_pos_of(("part", "left wing")) == (-0.16, 0.0, 0.05)


def test_set_angle_action_stages_the_angle(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    ok = p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    assert ok is True
    assert p._pending_part["left wing"]["angles"]["cruise"] == 45.0


def test_set_angle_rejects_an_unknown_state(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    ok = p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"REd","degrees":45.0}')
    assert ok is False
    assert "left wing" not in p._pending_part


def test_set_detach_action_stages_fraction(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event(
        'part/set_detach:{"name":"head","detachable":true,"fraction":0.35}')
    assert p._pending_part["head"]["fraction"] == 0.35


def test_unchecking_detachable_clears_the_fraction(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event(
        'part/set_detach:{"name":"head","detachable":true,"fraction":0.35}')
    p.dispatch_event(
        'part/set_detach:{"name":"head","detachable":false,"fraction":0.35}')
    assert p._pending_part["head"]["fraction"] is None


def test_previewing_an_articulated_state_locks_mount_editing(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event("part/preview:cruise")
    assert p._mount_editing_enabled() is False
    # The Python side is the real gate: a select_pin: action must be refused
    # outright, not merely greyed out in the DOM.
    assert p.dispatch_event("select_pin:0") is False
    assert p.selected_index is None


def test_previewing_the_anchor_state_leaves_mount_editing_enabled(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event("part/preview:cruise")
    assert p._mount_editing_enabled() is False
    p.dispatch_event("part/preview:red")   # red is the BoP's NIF pose
    assert p._mount_editing_enabled() is True
    assert p.dispatch_event("select_pin:0") is True
    assert p.selected_index == 0


def test_angle_editing_stays_available_while_locked(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event("part/preview:cruise")
    assert p._mount_editing_enabled() is False
    ok = p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":30.0}')
    assert ok is True
    assert p._pending_part["left wing"]["angles"]["cruise"] == 30.0


def test_locked_mount_gizmo_verb_blocked_for_a_light_target(make_panel):
    """A mount selected BEFORE the lock engaged must still be refused --
    the lock is keyed on the ACTIVE TARGET's kind, not on when it was
    picked."""
    p, _holder, _target = make_panel
    _open_with_parts(p)
    assert p.dispatch_event("select_light:0") is True
    assert p._active_transform_target() == ("light", 0)
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event("part/preview:cruise")
    assert p._mount_editing_enabled() is False
    assert p.dispatch_event("mirror_element") is False
    assert 0 not in p._pending_light


def test_locked_mount_gizmo_verb_allowed_for_a_part_target(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event("model_parts/select:left wing")
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event("part/preview:cruise")
    assert p._mount_editing_enabled() is False
    assert p.dispatch_event("mirror_element") is True


def test_save_writes_a_part_edit(make_panel):
    p, _holder, target = make_panel
    _open_with_parts(p)
    p.set_part_pivot("left wing", (-0.16, 0.0, 0.05))
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event(
        'part/set_detach:{"name":"left wing","detachable":true,"fraction":0.2}')
    assert p.dispatch_event("save") is True
    assert target.calls, "write() was never called"
    leaf, edits = target.calls[-1]
    assert leaf == "birdofprey"
    part_edits = [e for e in edits if e[1] == "__part__"]
    assert len(part_edits) == 1
    name, _tag, calls = part_edits[0]
    assert name == "left wing"
    setters = [c[0] for c in calls]
    assert "SetPivot" in setters
    assert "SetStateAngle" in setters
    assert "SetDetachFraction" in setters
    # Saved edits keep driving the in-session state; pending clears.
    assert "left wing" not in p._pending_part
    assert p._saved_part["left wing"]["pivot"] == (-0.16, 0.0, 0.05)


def test_a_non_detachable_part_never_saves_a_detach_call(make_panel):
    p, _holder, target = make_panel
    _open_with_parts(p)
    p.set_part_pivot("head", (0.0, 0.0, 0.0))
    assert p.dispatch_event("save") is True
    leaf, edits = target.calls[-1]
    name, _tag, calls = [e for e in edits if e[1] == "__part__"][0]
    assert name == "head"
    assert all(c[0] != "SetDetachFraction" for c in calls)


# ---------------------------------------------------------------------------
# Mouse-driven gizmo interaction on a part target -- the ACTUAL Transform/
# Rotate tool drag path (_begin_axis_drag/_apply_axis_drag,
# _begin_ring_drag/_apply_ring_drag_angle, transform_gizmo()/rotate_gizmo()
# for the render-time origin), as distinct from the coord-panel/pipette path
# already covered by _set_transform_target_pos / _set_axis_absolute above.
# These previously crashed on a "part" target -- see task-7-report.md.
# ---------------------------------------------------------------------------
class _RotShip:
    """Just enough of a ship for transform_gizmo()/rotate_gizmo() to place an
    origin: identity world transform (no rotation/translation to account
    for), and no subsystems (build_descriptors degrades to [] for a ship
    with none of the GetHull/.../GetNumChildSubsystems getters)."""

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()   # identity


def _part_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "birdofprey")
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RotShip())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._model_part_nodes = list(_PART_NODES)
    p.dispatch_event("model_parts/select:left wing")
    return p


def test_transform_gizmo_and_axis_drag_move_the_part_pivot(monkeypatch):
    p = _part_panel(monkeypatch)
    p.dispatch_event("set_tool:transform")
    g = p.transform_gizmo()
    assert g is not None
    # The real BoP rig's authored pivot (conftest's self-healing snapshot of
    # hardpoint_overrides.py's "left wing" block), not a from-scratch zero --
    # proves the gizmo reads the BAKED spec, not just a staged one.
    baked_pivot = p._effective_part("left wing")["pivot"]
    assert g["origin"] == pytest.approx(baked_pivot)
    p._begin_axis_drag_for_test(axis=1, grab_param=0.0)
    p._apply_axis_drag(2.0)
    moved = (baked_pivot[0], baked_pivot[1] + 2.0, baked_pivot[2])
    assert p._effective_part("left wing")["pivot"] == pytest.approx(moved)
    assert p.transform_gizmo()["origin"] == pytest.approx(moved)


def test_rotate_gizmo_and_ring_drag_rotate_the_part_axis(monkeypatch):
    p = _part_panel(monkeypatch)
    p.dispatch_event("set_tool:rotate")
    g = p.rotate_gizmo()
    assert g is not None
    p._begin_ring_drag(2, 0.0)
    p._apply_ring_drag_angle(math.radians(90.0))
    ax = p._effective_part("left wing")["axis"]
    # +Y rotated +90 about +Z -> -X (right-handed) -- same identity used by
    # test_ship_property_viewer_panel_rotate.py's cylinder-light case.
    assert ax == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)


def test_rotate_copy_paste_roundtrips_the_part_axis(monkeypatch):
    p = _part_panel(monkeypatch)
    p.dispatch_event("set_tool:rotate")
    p.dispatch_event("rotate_copy")
    assert p.rotate_values()["can_paste"] is True
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 45.0}))
    p.dispatch_event("rotate_paste")
    assert p._effective_part("left wing")["axis"] == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-6)


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
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event("part/preview:cruise")
    assert p._mount_editing_enabled() is False


def test_mouse_drag_cannot_move_a_subsystem_selected_before_the_lock(monkeypatch):
    """The reviewer's exact repro: select_pin:1 -> part/set_angle cruise=45
    -> part/preview:cruise -- the SUBSYSTEM stays the active gizmo target
    (only model_parts/select: clears it), so the raw drag functions must
    refuse on their own."""
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


def test_part_target_remains_draggable_while_locked(monkeypatch):
    """The negative-space check: none of the above guards may over-fire and
    also block the PART itself -- that is how the hinge gets placed while
    previewing the very pose it's being placed for."""
    p = _part_panel(monkeypatch)
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event("part/preview:cruise")
    assert p._mount_editing_enabled() is False
    assert p._current_target_is_locked_mount() is False
    p.dispatch_event("set_tool:transform")
    baked_pivot = p._effective_part("left wing")["pivot"]
    p._begin_axis_drag_for_test(axis=1, grab_param=0.0)
    p._apply_axis_drag(2.0)
    moved = (baked_pivot[0], baked_pivot[1] + 2.0, baked_pivot[2])
    assert p._effective_part("left wing")["pivot"] == pytest.approx(moved)


# ---------------------------------------------------------------------------
# Fix round 1, Finding 2: the 'K' dev keybinding (engine/dev_keybindings.py)
# writes articulation.set_dev_override directly -- the lock must read that
# override live. (A shadow copy in ship_property_viewer, which only Preview
# would ever have written, has since been deleted outright.)
# ---------------------------------------------------------------------------
def test_the_K_dev_override_locks_mount_editing_without_touching_preview(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    from engine.appc import articulation
    articulation.set_dev_override("cruise")   # exactly what 'K' does, and
    # nothing else -- no panel event, no Preview click.
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
        self._articulation_angles = {}


def _angles(ship):
    return dict(ship._articulation_angles)


def test_opening_the_viewer_snaps_the_ship_to_the_ANCHOR_pose(make_panel):
    """Every part at angle 0 -- the frame a hardpoint mount is stored in."""
    from engine.appc import articulation
    p, holder, _target = make_panel
    holder["ship"] = _RiggedShip()
    holder["ship"]._articulation_angles = {
        part.GetName(): part.angle_for("cruise")
        for part in articulation.rig_for("birdofprey")}
    assert any(v for v in _angles(holder["ship"]).values()), "fixture check"

    _open_with_parts(p)

    assert _angles(holder["ship"]), "the rig must still be there"
    assert all(v == 0.0 for v in _angles(holder["ship"]).values()), (
        "opening the SPV must put the shared angle dict -- which the mesh, "
        "the pins and the derived-box queries all read -- at the anchor pose")


def test_previewing_a_state_snaps_the_ship_to_its_authored_angles(make_panel):
    """Preview has to MOVE the wings, not just set a lock and a highlight."""
    from engine.appc import articulation
    p, holder, _target = make_panel
    holder["ship"] = _RiggedShip()
    _open_with_parts(p)

    p.dispatch_event("part/preview:cruise")

    expected = {part.GetName(): part.angle_for("cruise")
                for part in articulation.rig_for("birdofprey")}
    assert _angles(holder["ship"]) == expected
    assert any(v != 0.0 for v in expected.values()), "fixture check"


def test_closing_the_viewer_leaves_the_angles_for_tick_ship_to_ease_home(
        make_panel):
    """Deliberately NOT a snap: the sim resumes on close and `tick_ship` eases
    the wings back over TRAVEL_SECONDS. This pins that close RELEASES the
    override without also jumping the pose."""
    from engine.appc import articulation
    p, holder, _target = make_panel
    holder["ship"] = _RiggedShip()
    _open_with_parts(p)
    p.dispatch_event("part/preview:cruise")
    posed = _angles(holder["ship"])

    p.close()

    assert articulation.dev_override() is None, "the override must be released"
    assert _angles(holder["ship"]) == posed, (
        "close must not snap the pose; tick_ship eases it home")


def test_close_clears_the_preview_lock(make_panel):
    p, _holder, _target = make_panel
    _open_with_parts(p)
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event("part/preview:cruise")
    assert p._mount_editing_enabled() is False
    p.close()
    assert p._mount_editing_enabled() is True
