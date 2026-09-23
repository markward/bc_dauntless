"""An articulated part is a BC property template like any other.

That shape is not incidental: a hardpoint file is nothing but
`X = App.Something_Create(name); X.SetFoo(...); RegisterLocalTemplate(X)`,
and it is exactly what hardpoint_overrides.py already replays. Choosing it
means a modded ship can eventually carry its own rig in its own hardpoint
file, with no second format. See spec section 2.2.
"""
import pytest

from engine.appc import articulated_part as ap

STATES = ("cruise", "yellow", "red", "warp")


def test_the_name_IS_the_node_name():
    """One string, not two. It is the template name AND the NIF node name,
    and the same key find() already uses."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    assert p.GetName() == "left wing"


def test_an_unset_state_angle_is_zero():
    """Zero is the NIF pose, so an unauthored state means 'as modelled'
    rather than an error."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    for s in STATES:
        assert p.angle_for(s) == 0.0


def test_state_angles_round_trip():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetStateAngle("cruise", 45.0)
    p.SetStateAngle("red", 0.0)
    assert p.angle_for("cruise") == 45.0
    assert p.angle_for("red") == 0.0
    assert p.angle_for("warp") == 0.0


def test_an_unknown_state_is_rejected():
    """A typo must not silently become a part that never moves."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    with pytest.raises(ValueError):
        p.SetStateAngle("REd", 45.0)


def test_detach_fraction_defaults_to_NOT_detachable():
    """Absent means 'does not come off', never 'comes off at 0.0'."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    assert p.detach_fraction is None
    p.SetDetachFraction(0.20)
    assert p.detach_fraction == 0.20


def test_a_static_detachable_part_needs_no_extra_concept():
    """All angles zero plus a detach fraction is a breakable panel -- the
    BoP's 'head'. It must be expressible without a separate flag."""
    p = ap.ArticulatedPartProperty_Create("head")
    p.SetDetachFraction(0.20)
    assert all(p.angle_for(s) == 0.0 for s in STATES)
    assert p.detach_fraction == 0.20


def test_pivot_and_axis_round_trip():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetPivot(-0.16, 0.0, 0.05)
    p.SetAxis(0.0, 1.0, 0.0)
    assert p.pivot == (-0.16, 0.0, 0.05)
    assert p.axis == (0.0, 1.0, 0.0)
