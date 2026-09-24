"""The Bird of Prey's authored numbers survive the move to templates.

Migration, not rewrite: identical pivots, axes and detach fraction, so day-one
behaviour is verifiable rather than merely plausible. The ONE deliberate change
is that bounding boxes now come from the mesh (spec section 2.5).
"""
from engine.appc import articulation
from engine.appc.articulated_part import STATES


def test_the_bop_rig_survives_the_move():
    parts = {p.GetName(): p for p in articulation.parts_for_leaf("birdofprey")}
    assert set(parts) >= {"left wing", "left wing01"}

    port, star = parts["left wing"], parts["left wing01"]
    assert port.pivot == (-0.16, 0.0, 0.05)
    assert star.pivot == (0.16, 0.0, 0.05)
    assert port.axis == (0.0, 1.0, 0.0)
    assert star.axis == (0.0, 1.0, 0.0)


def test_the_wing_angle_SIGNS_are_preserved():
    """REGRESSION GUARD. The signs were swapped once during the spike: +45 on
    the starboard wing SANK the tip instead of raising it, and only a test
    against the real tip coordinate caught it."""
    parts = {p.GetName(): p for p in articulation.parts_for_leaf("birdofprey")}
    assert parts["left wing"].angle_for("cruise") == 45.0
    assert parts["left wing01"].angle_for("cruise") == -45.0


def test_red_alert_is_the_NIF_pose():
    """Zero rotation, because the BoP's NIF is modelled wings-down. This is
    what makes Red the anchor for this ship -- no declaration needed."""
    for p in articulation.parts_for_leaf("birdofprey"):
        assert p.angle_for("red") == 0.0


def test_both_wings_shear_at_twenty_percent():
    parts = {p.GetName(): p for p in articulation.parts_for_leaf("birdofprey")}
    assert parts["left wing"].detach_fraction == 0.20
    assert parts["left wing01"].detach_fraction == 0.20


def test_the_hardcoded_dicts_are_GONE():
    """The whole point of the migration. Leaving them would give two sources
    of truth that silently disagree."""
    assert not hasattr(articulation, "_RIGS")
    assert not hasattr(articulation, "PART_BOXES")
    assert not hasattr(articulation, "DETACHABLE")
