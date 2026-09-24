"""Authoring a part, and the lock that stops you authoring a mount through
the wrong pose.

The lock is the feature. Its failure mode without one is silent and invisible:
a wingtip cannon authored ~0.9 ship units out, discovered only in combat. A
banner relies on the author reading it.
"""
import pytest

from engine.ui import ship_property_viewer as spv


def test_previewing_the_anchor_state_leaves_editing_ENABLED():
    """Red is the BoP's NIF pose, so previewing it changes nothing and must
    not lock anything."""
    spv.preview_part_state("red", angles={"red": 0.0, "cruise": 45.0})
    assert spv.mount_editing_enabled() is True


def test_previewing_an_ARTICULATED_state_DISABLES_mount_editing():
    """THE POINT."""
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 45.0})
    assert spv.mount_editing_enabled() is False


def test_the_lock_names_its_reason():
    """A disabled control with no explanation reads as a bug."""
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 45.0})
    assert spv.mount_editing_reason()


def test_clearing_the_preview_restores_editing():
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 45.0})
    spv.preview_part_state(None, angles={})
    assert spv.mount_editing_enabled() is True


def test_angle_editing_stays_available_while_locked():
    """You must be able to tune the very angle you are looking at."""
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 45.0})
    assert spv.angle_editing_enabled() is True


def test_a_state_whose_angles_are_all_zero_is_not_a_lock():
    """'Articulated' means a non-zero angle, not 'a state was selected'. A
    ship whose cruise pose equals its NIF pose must stay editable."""
    spv.preview_part_state("cruise", angles={"red": 0.0, "cruise": 0.0})
    assert spv.mount_editing_enabled() is True


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


def test_a_non_detachable_part_emits_NO_detach_call():
    """Absent must stay absent -- emitting SetDetachFraction(0.0) would make
    every part shear instantly."""
    edits = spv.part_save_edits({
        "head": {"pivot": (0.0, 0.0, 0.0), "axis": (0.0, 1.0, 0.0),
                 "angles": {}, "fraction": None},
    })
    calls = edits[0][2]
    assert all(c[0] != "SetDetachFraction" for c in calls)
