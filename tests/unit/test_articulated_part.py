"""An articulated part is a BC property template like any other.

That shape is not incidental: a hardpoint file is nothing but
`X = App.Something_Create(name); X.SetFoo(...); RegisterLocalTemplate(X)`,
and it is exactly what hardpoint_overrides.py already replays. Choosing it
means a modded ship can eventually carry its own rig in its own hardpoint
file, with no second format. See spec section 2.2.
"""
import pytest

import App
from engine.appc import articulated_part as ap
from engine.appc import part_pose as pp

STATES = ("cruise", "yellow", "red", "warp")


@pytest.fixture(autouse=True)
def _reset_articulated_part_and_local_templates():
    """Isolates every test in this file from the others AND from the rest of
    the suite: App.g_kModelPropertyManager is a session-wide singleton, and
    this project has a documented history of order-dependent failures."""
    ap.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    yield
    ap.reset()
    App.g_kModelPropertyManager.ClearLocalTemplates()


def test_the_name_IS_the_node_name():
    """One string, not two. It is the template name AND the NIF node name,
    and the same key find() already uses."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    assert p.GetName() == "left wing"


def test_an_unset_state_angle_is_zero():
    """Zero is the NIF pose, so an unauthored state means 'as modelled'
    rather than an error. Read via the pose surface -- `angle_for` is a
    legacy reader kept only for the SPV panel (spec 2026-09-25 section 7,
    not yet rewritten); everything else reads `pose_for`/`pose6_for`."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    for s in STATES:
        assert pp.is_identity(p.pose_for(s))
        assert p.pose6_for(s) is None


def test_state_angles_round_trip():
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetStateAngle("cruise", 45.0)
    p.SetStateAngle("red", 0.0)
    assert not pp.is_identity(p.pose_for("cruise"))
    assert pp.is_identity(p.pose_for("red"))
    assert pp.is_identity(p.pose_for("warp"))       # unset -> the NIF pose


def test_an_unknown_state_is_rejected():
    """A typo must not silently become a part that never moves."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    with pytest.raises(ValueError):
        p.SetStateAngle("REd", 45.0)


def test_detach_fraction_defaults_to_NOT_detachable():
    """Absent means 'does not come off', never 'comes off at 0.0'. Read via
    `break_fraction`, the new alias `SetDetachFraction` writes through to
    (spec section 3)."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    assert p.break_fraction is None
    p.SetDetachFraction(0.20)
    assert p.break_fraction == 0.20


def test_a_static_detachable_part_needs_no_extra_concept():
    """All angles zero plus a detach fraction is a breakable panel -- the
    BoP's 'head'. It must be expressible without a separate flag."""
    p = ap.ArticulatedPartProperty_Create("head")
    p.SetDetachFraction(0.20)
    assert all(pp.is_identity(p.pose_for(s)) for s in STATES)
    assert p.break_fraction == 0.20


def test_pivot_and_axis_feed_the_anchor_and_pose():
    """`SetPivot`/`SetAxis` are legacy setters; a state angle authored
    against them converts to an anchor and a rigid pose through the hinge
    (spec section 6), read via the pose surface."""
    p = ap.ArticulatedPartProperty_Create("left wing")
    p.SetPivot(-0.16, 0.0, 0.05)
    p.SetAxis(0.0, 1.0, 0.0)
    p.SetStateAngle("cruise", 45.0)
    assert p.anchor == (-0.16, 0.0, 0.05)
    assert not pp.is_identity(p.pose_for("cruise"))


# ---------------------------------------------------------------------------
# parts_for_leaf: a snapshot taken at load time, NOT a live query.
#
# TGModelPropertyManager._local is wiped by ClearLocalTemplates() on every
# ship load, so it only ever holds the most recently loaded ship's templates.
# A live parts_for_leaf would silently return whatever ship loaded last.
# ---------------------------------------------------------------------------

def test_parts_for_leaf_unrigged_ship_is_empty_tuple():
    """An unrigged ship is the overwhelmingly common case; it must cost
    nothing and never raise."""
    assert ap.parts_for_leaf("no_such_ship") == ()


def test_snapshot_for_leaf_captures_registered_parts():
    p = ap.ArticulatedPartProperty_Create("left wing")
    App.g_kModelPropertyManager.RegisterLocalTemplate(p)
    ap.snapshot_for_leaf("birdofprey")
    assert ap.parts_for_leaf("birdofprey") == (p,)


def test_snapshotting_a_second_leaf_does_not_disturb_the_first():
    """The one that matters: pins that the snapshot is per-leaf, not
    'whatever is in the manager right now' -- exactly the bug a live-query
    design would have had."""
    a = ap.ArticulatedPartProperty_Create("left wing")
    App.g_kModelPropertyManager.RegisterLocalTemplate(a)
    ap.snapshot_for_leaf("birdofprey")

    App.g_kModelPropertyManager.ClearLocalTemplates()
    b = ap.ArticulatedPartProperty_Create("wing")
    App.g_kModelPropertyManager.RegisterLocalTemplate(b)
    ap.snapshot_for_leaf("vorcha")

    assert ap.parts_for_leaf("birdofprey") == (a,)   # untouched by vorcha's snapshot
    assert ap.parts_for_leaf("vorcha") == (b,)


def test_reset_clears_all_snapshots():
    p = ap.ArticulatedPartProperty_Create("left wing")
    App.g_kModelPropertyManager.RegisterLocalTemplate(p)
    ap.snapshot_for_leaf("birdofprey")
    ap.reset()
    assert ap.parts_for_leaf("birdofprey") == ()


def test_snapshot_ignores_non_articulated_templates():
    """A plain subsystem property registered alongside a part must not be
    picked up -- the snapshot is type-filtered, not 'everything local'."""
    plain = App.HullProperty_Create("Hull")
    part = ap.ArticulatedPartProperty_Create("left wing")
    App.g_kModelPropertyManager.RegisterLocalTemplate(plain)
    App.g_kModelPropertyManager.RegisterLocalTemplate(part)
    ap.snapshot_for_leaf("birdofprey")
    assert ap.parts_for_leaf("birdofprey") == (part,)
