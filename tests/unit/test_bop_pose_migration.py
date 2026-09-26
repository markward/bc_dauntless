"""The legacy hinge format converts to anchor + state poses exactly (spec
2026-09-25 §6), and the committed hardpoint file is in the new format.

This file pins the CONVERSION, not what anyone has authored since. The
exact-value checks run against a FROZEN copy of the pre-migration Bird of
Prey block (`LEGACY_BOP_BLOCK`, verbatim from `_birdofprey` before commit
97140bc3: SetPivot/SetAxis/SetStateAngle/SetDetachFraction, +/-45 degrees,
pivots (-/+0.16, 0, 0.05), 20%). It is executed against a recording `App`,
never read from the live `engine/appc/hardpoint_overrides.py` -- that file
holds live SPV authoring (the BoP's wing angles are Mark's to change), and a
mechanism test coupled to authored data breaks every time someone authors
(the same defect `tests/conftest.py`'s `bop_fixture_rig` and
`tests/unit/test_authored_part_data.py` already fixed once).

Only one check reads the live file: it must use the new calls alone.
"""
import math

import pytest

from engine.appc import hardpoint_overrides, part_pose as pp
from engine.appc import articulated_part

OLD = {  # the pre-migration hinge rig, the reference
    "left wing": ((-0.16, 0.0, 0.05), 45.0),
    "left wing01": ((0.16, 0.0, 0.05), -45.0),
}
AXIS = (0.0, 1.0, 0.0)

# Verbatim from `git show 97140bc3^:engine/appc/hardpoint_overrides.py`.
# FROZEN: never edit to track authoring.
LEGACY_BOP_BLOCK = '''
if hasattr(App, "ArticulatedPartProperty_Create"):
    left_wing = App.ArticulatedPartProperty_Create("left wing")
    left_wing.SetPivot(-0.16, 0.0, 0.05)
    left_wing.SetAxis(0.0, 1.0, 0.0)
    left_wing.SetStateAngle("cruise", 45.0)
    left_wing.SetStateAngle("yellow", 45.0)
    left_wing.SetStateAngle("warp", 45.0)
    left_wing.SetDetachFraction(0.2)
    App.g_kModelPropertyManager.RegisterLocalTemplate(left_wing)
if hasattr(App, "ArticulatedPartProperty_Create"):
    left_wing01 = App.ArticulatedPartProperty_Create("left wing01")
    left_wing01.SetPivot(0.16, 0.0, 0.05)
    left_wing01.SetAxis(0.0, 1.0, 0.0)
    left_wing01.SetStateAngle("cruise", -45.0)
    left_wing01.SetStateAngle("yellow", -45.0)
    left_wing01.SetStateAngle("warp", -45.0)
    left_wing01.SetDetachFraction(0.2)
    App.g_kModelPropertyManager.RegisterLocalTemplate(left_wing01)
'''


class _RecordingManager:
    def __init__(self):
        self.registered = {}

    def RegisterLocalTemplate(self, template):
        self.registered[template.GetName()] = template


class _RecordingApp:
    def __init__(self):
        self.g_kModelPropertyManager = _RecordingManager()
        self.ArticulatedPartProperty_Create = \
            articulated_part.ArticulatedPartProperty_Create


def _legacy_parts():
    """The frozen legacy block, loaded exactly as a hardpoint file is."""
    app = _RecordingApp()
    exec(LEGACY_BOP_BLOCK, {"App": app})
    return app.g_kModelPropertyManager.registered


def _migrated_parts():
    """The legacy parts re-authored through the NEW calls from what the
    conversion reads out (`anchor`, `pose6_for`, `transition_seconds`,
    `break_fraction`) -- the shape the migration wrote to the file."""
    out = {}
    for name, old in _legacy_parts().items():
        p = articulated_part.ArticulatedPartProperty(name)
        p.SetAnchor(*old.anchor)
        p.SetTransitionSeconds(old.transition_seconds)
        for state in old.authored_states():
            p.SetStatePose(state, *old.pose6_for(state))
        p.SetBreakFraction(old.break_fraction)
        out[name] = p
    return out


_SOURCES = {"legacy": _legacy_parts, "migrated": _migrated_parts}


def test_the_committed_file_uses_only_the_new_calls():
    import inspect
    src = inspect.getsource(hardpoint_overrides._birdofprey)
    for legacy in ("SetPivot", "SetAxis", "SetStateAngle", "SetDetachFraction"):
        assert legacy not in src, legacy


def test_the_frozen_block_really_is_the_legacy_format():
    for new in ("SetAnchor", "SetStatePose", "SetBreakFraction",
                "SetTransitionSeconds"):
        assert new not in LEGACY_BOP_BLOCK, new
    assert sorted(_legacy_parts()) == sorted(OLD)


@pytest.mark.parametrize("source", sorted(_SOURCES))
@pytest.mark.parametrize("name", sorted(OLD))
def test_every_state_lands_where_the_old_hinge_put_it(name, source):
    pivot, cruise_deg = OLD[name]
    part = _SOURCES[source]()[name]
    assert part.anchor == pytest.approx(pivot)
    samples = [(-1.0, 0.45, -0.67), (1.0, 0.45, -0.67), (0.3, -0.2, 0.1)]
    for state, deg in (("cruise", cruise_deg), ("yellow", cruise_deg),
                       ("warp", cruise_deg), ("red", 0.0)):
        ref = pp.hinge_pose(pivot, AXIS, deg)
        for x in samples:
            assert pp.apply(part.pose_for(state), x) == pytest.approx(
                pp.apply(ref, x), abs=1e-9), (name, state)


@pytest.mark.parametrize("source", sorted(_SOURCES))
@pytest.mark.parametrize("name", sorted(OLD))
def test_midway_to_cruise_is_the_old_half_angle(name, source):
    pivot, cruise_deg = OLD[name]
    part = _SOURCES[source]()[name]
    mid = pp.interpolate(pp.IDENTITY, part.pose_for("cruise"), part.anchor, 0.5)
    ref = pp.hinge_pose(pivot, AXIS, cruise_deg / 2.0)
    x = (math.copysign(1.0, pivot[0]), 0.45, -0.67)
    assert pp.apply(mid, x) == pytest.approx(pp.apply(ref, x), abs=1e-9)


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_both_wings_still_break_at_twenty_percent_in_two_seconds(source):
    parts = _SOURCES[source]()
    for name in OLD:
        assert parts[name].break_fraction == pytest.approx(0.20)
        assert parts[name].transition_seconds == 2.0
