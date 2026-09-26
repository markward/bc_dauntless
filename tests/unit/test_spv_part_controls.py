"""Authoring a part, and the lock that stops you authoring a mount through
the wrong pose.

The lock is the feature. Its failure mode without one is silent and invisible:
a wingtip cannon authored ~0.9 ship units out, discovered only in combat. A
banner relies on the author reading it.

THE LOCK LIVES ON THE PANEL. These tests used to drive a second, module-level
copy (`ship_property_viewer.preview_part_state` / `mount_editing_enabled`)
that no production code ever called -- and because nothing wrote its
`_part_preview_locked` global, `mount_editing_enabled()` answered True
forever, with five green assertions standing behind it. It has been deleted;
`test_there_is_no_module_level_twin_of_the_lock` keeps it deleted. The real
lock is `ShipPropertyViewerPanel._mount_lock_state_and_reason`, computed live
from two things: a selected {State} Transformation node, and
`articulation.dev_override()` (the 'K' dev keybinding) together with the
rig's current poses. (The Preview buttons that used to drive the override are
gone -- spec 2026-09-25 section 7.5.)
"""
import json

import pytest

from engine.ui import ship_property_viewer as spv
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

# BOTH wings. The K arm of the lock reads every part of the rig, so a
# fixture that can only stage one of them cannot express "every pose is the
# NIF pose" -- see test_a_state_whose_poses_are_all_identity_is_not_a_lock.
_PART_NODES = [
    {"name": "left wing", "parent": "Scene Root", "candidate": True,
     "bounds_min": (-1.0, -0.5, -0.5), "bounds_max": (-0.1, 0.5, 0.5)},
    {"name": "left wing01", "parent": "Scene Root", "candidate": True,
     "bounds_min": (0.1, -0.5, -0.5), "bounds_max": (1.0, 0.5, 0.5)},
]


class _FakeSubsystem:
    def GetPosition(self):
        return (0.0, 0.0, 0.0)

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0


class _FakeShip:
    def GetHull(self):
        return _FakeSubsystem()

    def GetSensorSubsystem(self):
        return _FakeSubsystem()


@pytest.fixture
def panel(monkeypatch):
    """An opened panel on the Bird of Prey rig (conftest's frozen fixture:
    both wings posed at +/-45 degrees in cruise/yellow/warp, red unset -- the
    NIF pose)."""
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: [])
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: None)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "birdofprey")
    p = ShipPropertyViewerPanel(ship_getter=_FakeShip)
    p.open()
    p._model_part_nodes = list(_PART_NODES)
    return p


def _force(state):
    """Exactly what the 'K' dev keybinding does, and nothing else."""
    from engine.appc import articulation
    articulation.set_dev_override(state)


def _payload_lock(p):
    p._last_pushed = None
    js = p.render_payload()
    parts = json.loads(js[len("setShipPropertyViewer("):-2])["model_parts"]
    return parts["mount_editing_enabled"], parts["mount_editing_reason"]


def test_forcing_the_NIF_pose_state_leaves_editing_ENABLED(panel):
    """Red is unset in the BoP rig -- the NIF pose -- so forcing it moves
    nothing and must not lock anything."""
    _force("red")
    assert panel._mount_lock_state_and_reason() == (False, None)
    assert _payload_lock(panel) == (True, None)


def test_forcing_an_ARTICULATED_state_DISABLES_mount_editing(panel):
    """THE POINT."""
    _force("cruise")
    assert panel._mount_lock_state_and_reason()[0] is True
    assert panel._mount_editing_enabled() is False
    assert _payload_lock(panel)[0] is False


def test_selecting_a_state_transformation_DISABLES_mount_editing(panel):
    """The panel's own arm of the lock: the part is drawn posed."""
    assert panel.dispatch_event(
        'part/select_node:{"name":"left wing","kind":"cruise"}') is True
    enabled, reason = _payload_lock(panel)
    assert enabled is False
    assert reason == (
        "Posing Cruising Transformation on left wing — mount editing is locked")


def test_the_lock_names_its_reason(panel):
    """A disabled control with no explanation reads as a bug."""
    _force("cruise")
    assert panel._mount_lock_state_and_reason()[1]
    assert _payload_lock(panel)[1]


def test_clearing_the_forced_state_restores_editing(panel):
    _force("cruise")
    assert panel._mount_editing_enabled() is False
    _force(None)
    assert panel._mount_lock_state_and_reason() == (False, None)


def test_part_editing_stays_available_while_locked(panel):
    """You must be able to tune the very part you are looking at. The panel
    states this by what it REFUSES: a part action is not a locked mount
    action, so it still dispatches while a state node holds the lock."""
    panel.dispatch_event('part/select_node:{"name":"left wing","kind":"cruise"}')
    assert panel._mount_editing_enabled() is False
    action = 'part/set_transition:{"name":"left wing","seconds":3.0}'
    assert panel._is_locked_mount_action(action) is False
    assert panel.dispatch_event(action) is True
    assert panel._pending_part["left wing"]["transition"] == 3.0
    assert panel.dispatch_event(
        'part/set_break:{"name":"left wing","percent":30}') is True
    assert panel._pending_part["left wing"]["break"] == pytest.approx(0.30)


def test_a_state_whose_poses_are_all_identity_is_not_a_lock(panel):
    """'Articulated' means a non-NIF pose, not 'the state has a pose'. A
    ship whose cruise pose equals its NIF pose must stay editable under the
    'K' override.

    Every part of the rig is re-posed to identity, not just one: the lock
    reads the WHOLE rig, so the second wing's baked 45 degrees would keep it
    on -- which is correct, and is checked first so this cannot pass by the
    lock simply ignoring 'K'."""
    from engine.appc import articulation
    _force("cruise")
    assert panel._mount_lock_state_and_reason()[0] is True, (
        "fixture: the baked cruise poses are articulated")
    for part in articulation.parts_for_leaf("birdofprey"):
        spec = dict(panel._effective_part(part.GetName()))
        spec["poses"] = dict(spec["poses"], cruise=(0.0,) * 6)
        panel._pending_part[part.GetName()] = spec
    assert panel._mount_lock_state_and_reason() == (False, None)
    assert _payload_lock(panel) == (True, None)


def test_there_is_no_module_level_twin_of_the_lock():
    """A second `mount_editing_enabled()` with the obvious name, no
    production writer and therefore a permanently-open lock is worse than no
    API at all: the next control wired to it is unguarded, and green tests
    say otherwise. Keep it deleted."""
    dead = ("preview_part_state", "mount_editing_enabled",
            "mount_editing_reason", "part_preview_state",
            "angle_editing_enabled", "reset_part_preview",
            "_part_preview_state", "_part_preview_locked",
            "_part_preview_reason")
    present = [n for n in dead if hasattr(spv, n)]
    assert present == [], (
        "engine.ui.ship_property_viewer still exposes a dead copy of the "
        "mount lock: %r -- the live one is "
        "ShipPropertyViewerPanel._mount_lock_state_and_reason" % (present,))


def test_part_edits_reach_the_save_list():
    edits = spv.part_save_edits({
        "left wing": {"anchor": (-0.16, 0.0, 0.05), "transition": 2.0,
                      "poses": {"cruise": (0.0, 0.0, 0.0, 0.0, 45.0, 0.0)},
                      "break": 0.20},
    })
    assert edits == [("left wing", "__part__", [
        ("SetAnchor", (-0.16, 0.0, 0.05)),
        ("SetTransitionSeconds", (2.0,)),
        ("SetStatePose", ("cruise", 0.0, 0.0, 0.0, 0.0, 45.0, 0.0)),
        ("SetBreakFraction", (0.20,)),
    ])]


def test_a_spec_with_nothing_to_say_emits_no_edit_at_all():
    """A spec with everything absent must not round-trip as an empty
    (name, "__part__", []) block written to disk. The transition alone says
    nothing: it belongs to the anchor, and there is none."""
    edits = spv.part_save_edits({
        "left wing": {"anchor": None, "transition": 2.0, "poses": {},
                      "break": None},
    })
    assert edits == []


def test_an_unbreakable_part_emits_NO_break_call():
    """Absent must stay absent -- emitting SetBreakFraction(0.0) would make
    the part shear at once."""
    edits = spv.part_save_edits({
        "head": {"anchor": (0.0, 0.0, 0.0), "transition": 2.0, "poses": {},
                 "break": None},
    })
    calls = edits[0][2]
    assert [c[0] for c in calls] == ["SetAnchor", "SetTransitionSeconds"]
