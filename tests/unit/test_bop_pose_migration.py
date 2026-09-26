"""The committed Bird of Prey rig is in the new format and moves exactly as
the old hinge did (spec 2026-09-25 §6)."""
import math

import pytest

from engine.appc import hardpoint_overrides, part_pose as pp
from engine.appc.articulated_part import ArticulatedPartProperty

OLD = {  # the pre-migration hinge rig, the reference
    "left wing": ((-0.16, 0.0, 0.05), 45.0),
    "left wing01": ((0.16, 0.0, 0.05), -45.0),
}
AXIS = (0.0, 1.0, 0.0)


def _parts():
    import App
    mgr = App.g_kModelPropertyManager
    mgr.ClearLocalTemplates()
    try:
        hardpoint_overrides.apply("birdofprey")
        return {p.GetName(): p for p in getattr(mgr, "_local", {}).values()
                if isinstance(p, ArticulatedPartProperty)}
    finally:
        mgr.ClearLocalTemplates()


def test_the_committed_file_uses_only_the_new_calls():
    import inspect
    src = inspect.getsource(hardpoint_overrides._birdofprey)
    for legacy in ("SetPivot", "SetAxis", "SetStateAngle", "SetDetachFraction"):
        assert legacy not in src, legacy


@pytest.mark.parametrize("name", sorted(OLD))
def test_every_state_lands_where_the_old_hinge_put_it(name):
    pivot, cruise_deg = OLD[name]
    part = _parts()[name]
    assert part.anchor == pytest.approx(pivot)
    samples = [(-1.0, 0.45, -0.67), (1.0, 0.45, -0.67), (0.3, -0.2, 0.1)]
    for state, deg in (("cruise", cruise_deg), ("yellow", cruise_deg),
                       ("warp", cruise_deg), ("red", 0.0)):
        ref = pp.hinge_pose(pivot, AXIS, deg)
        for x in samples:
            assert pp.apply(part.pose_for(state), x) == pytest.approx(
                pp.apply(ref, x), abs=1e-9), (name, state)


@pytest.mark.parametrize("name", sorted(OLD))
def test_midway_to_cruise_is_the_old_half_angle(name):
    pivot, cruise_deg = OLD[name]
    part = _parts()[name]
    mid = pp.interpolate(pp.IDENTITY, part.pose_for("cruise"), part.anchor, 0.5)
    ref = pp.hinge_pose(pivot, AXIS, cruise_deg / 2.0)
    x = (math.copysign(1.0, pivot[0]), 0.45, -0.67)
    assert pp.apply(mid, x) == pytest.approx(pp.apply(ref, x), abs=1e-9)


def test_both_wings_still_break_at_twenty_percent_in_two_seconds():
    parts = _parts()
    for name in OLD:
        assert parts[name].break_fraction == pytest.approx(0.20)
        assert parts[name].transition_seconds == 2.0
