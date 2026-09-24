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
from `articulation.dev_override()` (written by BOTH the panel's Preview
buttons and the 'K' dev keybinding) and the rig's current angles.
"""
import pytest

from engine.ui import ship_property_viewer as spv
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

# BOTH wings. The lock reads the largest angle across the WHOLE rig, so a
# fixture that can only stage one of them cannot express "every angle is
# zero" -- see test_a_state_whose_angles_are_all_zero_is_not_a_lock.
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
    """An opened panel whose BoP rig has one articulated part staged at
    cruise 45 / red 0 -- the real Bird of Prey shape."""
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: [])
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: None)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "birdofprey")
    p = ShipPropertyViewerPanel(ship_getter=_FakeShip)
    p.open()
    p._model_part_nodes = list(_PART_NODES)
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":45.0}')
    p.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"red","degrees":0.0}')
    return p


def test_previewing_the_anchor_state_leaves_editing_ENABLED(panel):
    """Red is the BoP's NIF pose, so previewing it changes nothing and must
    not lock anything."""
    panel.dispatch_event("part/preview:red")
    assert panel._mount_lock_state_and_reason() == (False, None)


def test_previewing_an_ARTICULATED_state_DISABLES_mount_editing(panel):
    """THE POINT."""
    panel.dispatch_event("part/preview:cruise")
    assert panel._mount_lock_state_and_reason()[0] is True
    assert panel._mount_editing_enabled() is False


def test_the_lock_names_its_reason(panel):
    """A disabled control with no explanation reads as a bug."""
    panel.dispatch_event("part/preview:cruise")
    assert panel._mount_lock_state_and_reason()[1]


def test_clearing_the_preview_restores_editing(panel):
    panel.dispatch_event("part/preview:cruise")
    assert panel._mount_editing_enabled() is False
    panel.dispatch_event("part/preview:")          # deselect -> no forced state
    assert panel._mount_lock_state_and_reason() == (False, None)


def test_angle_editing_stays_available_while_locked(panel):
    """You must be able to tune the very angle you are looking at. The panel
    states this by what it REFUSES: a part action is not a locked mount
    action, so it still dispatches."""
    panel.dispatch_event("part/preview:cruise")
    assert panel._mount_editing_enabled() is False
    assert panel._is_locked_mount_action(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":30.0}'
    ) is False
    assert panel.dispatch_event(
        'part/set_angle:{"name":"left wing","state":"cruise","degrees":30.0}'
    ) is True
    assert panel._pending_part["left wing"]["angles"]["cruise"] == 30.0


def test_a_state_whose_angles_are_all_zero_is_not_a_lock(panel):
    """'Articulated' means a non-zero angle, not 'a state was selected'. A
    ship whose cruise pose equals its NIF pose must stay editable.

    Every part of the rig is zeroed, not just the staged one: the lock reads
    the LARGEST angle across the whole rig, so the second wing's baked 45
    would keep it on -- which is correct, and is why the module-level twin's
    caller-supplied `angles` dict was the wrong shape for this question."""
    from engine.appc import articulation
    for part in articulation.parts_for_leaf("birdofprey"):
        panel.dispatch_event(
            'part/set_angle:{"name":"%s","state":"cruise","degrees":0.0}'
            % part.GetName())
    panel.dispatch_event("part/preview:cruise")
    assert panel._mount_lock_state_and_reason() == (False, None)


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
        "left wing": {"pivot": (-0.16, 0.0, 0.05), "axis": (0.0, 1.0, 0.0),
                      "angles": {"cruise": 45.0}, "fraction": 0.20},
    })
    assert edits
    name, verb, calls = edits[0]
    assert name == "left wing"
    assert verb == "__part__"
    setters = [c[0] for c in calls]
    assert "SetPivot" in setters and "SetStateAngle" in setters
    assert "SetDetachFraction" in setters


def test_a_spec_with_nothing_to_say_emits_no_edit_at_all():
    """Not reachable from the panel today (every staging path sets at least
    one field), but a spec with everything absent must not round-trip as an
    empty (name, "__part__", []) block written to disk."""
    edits = spv.part_save_edits({
        "left wing": {"pivot": None, "axis": None, "angles": {}, "fraction": None},
    })
    assert edits == []


def test_a_non_detachable_part_emits_NO_detach_call():
    """Absent must stay absent -- emitting SetDetachFraction(0.0) would make
    every part shear instantly."""
    edits = spv.part_save_edits({
        "head": {"pivot": (0.0, 0.0, 0.0), "axis": (0.0, 1.0, 0.0),
                 "angles": {}, "fraction": None},
    })
    calls = edits[0][2]
    assert all(c[0] != "SetDetachFraction" for c in calls)
