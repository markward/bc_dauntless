"""Part articulation (BoP wings) — the parts a headless test can actually see.

What these CANNOT see: whether the pivots look right. That is the whole reason
the feature shipped as a spike with a dev key — the hinge points are invented,
and only live eyes settle them. These pin the contract around them: the
alert->pose mapping, the ease, the rest-pose identity, and the geometry claim
the pivots were derived from.
"""
import math

import pytest

from engine.appc import articulation


# ── The rig itself ───────────────────────────────────────────────────────────

def test_only_the_bird_of_prey_has_a_rig():
    """One stock hull, deliberately. A second entry appearing here is a
    decision, not a refactor — every other hull must stay unarticulated."""
    assert articulation.has_rig("birdofprey")
    for other in ("galaxy", "sovereign", "warbird", "nebula", "akira"):
        assert not articulation.has_rig(other), other


def test_rig_lookup_is_case_insensitive_and_none_safe():
    assert articulation.rig_for("BirdOfPrey") == articulation.rig_for("birdofprey")
    assert articulation.rig_for(None) == ()
    assert articulation.rig_for("") == ()


def test_the_two_wings_are_mirrored():
    """`left wing` is PORT and `left wing01` is STARBOARD — the 01 suffix is a
    3ds Max clone marker, not anatomy. Its geometry spans X +12.4..+102.6
    against the other's -102.6..-12.4. If these signs are ever made to match,
    both wings rotate the same way and the ship tips instead of spreading."""
    port, starboard = articulation.rig_for("birdofprey")
    assert port.node == "left wing"
    assert starboard.node == "left wing01"
    assert port.pivot[0] == -starboard.pivot[0] != 0.0
    assert port.angle_deg == -starboard.angle_deg != 0.0
    # Same hinge axis; the mirroring lives in the pivot and the angle SIGN.
    assert port.axis == starboard.axis


def test_hinge_axis_is_fore_aft():
    """The wings sweep about the ship's Y (fore-aft) axis. A pivot's Y
    component is therefore inert — rotation about a line is unchanged by
    sliding the pivot along it — which is why tuning is two numbers per wing."""
    for part in articulation.rig_for("birdofprey"):
        assert part.axis == (0.0, 1.0, 0.0)


# ── Alert level -> pose ──────────────────────────────────────────────────────

def test_red_alert_is_the_models_rest_pose():
    """0 = wings DOWN = armed = exactly how the NIF ships. This is what makes
    combat rendering byte-identical to an unarticulated hull."""
    from engine.appc.ships import ShipClass
    assert articulation.deflection_target(ShipClass.RED_ALERT) == 0.0


@pytest.mark.parametrize("level_name", ["GREEN_ALERT", "YELLOW_ALERT"])
def test_non_red_alert_raises_the_wings(level_name):
    from engine.appc.ships import ShipClass
    assert articulation.deflection_target(getattr(ShipClass, level_name)) == 1.0


# ── Easing ───────────────────────────────────────────────────────────────────

def test_ease_reaches_the_target_in_the_travel_time():
    dt = 1.0 / 60.0
    v = 0.0
    for _ in range(int(articulation.TRAVEL_SECONDS / dt) + 1):
        v = articulation.ease(v, 1.0, dt)
    assert v == 1.0


def test_ease_does_not_overshoot():
    """A step larger than the remaining gap must SNAP, not sail past — an
    overshoot would drive deflection out of [0,1] and past the authored angle."""
    assert articulation.ease(0.99, 1.0, 10.0) == 1.0
    assert articulation.ease(0.01, 0.0, 10.0) == 0.0


def test_ease_runs_both_ways():
    dt = 0.1
    assert articulation.ease(0.5, 1.0, dt) > 0.5
    assert articulation.ease(0.5, 0.0, dt) < 0.5


# ── Rotation resolution ──────────────────────────────────────────────────────

def test_rest_deflection_yields_zero_rotation():
    """theta == 0 is the signal the binding uses to ERASE the override rather
    than store an identity, which is what keeps the node-override map empty on
    a ship at rest."""
    part = articulation.rig_for("birdofprey")[0]
    _pivot, _axis, theta = articulation.rotation_for(part, 0.0)
    assert theta == 0.0


def test_full_deflection_matches_the_authored_angle():
    for part in articulation.rig_for("birdofprey"):
        _p, _a, theta = articulation.rotation_for(part, 1.0)
        assert theta == pytest.approx(math.radians(part.angle_deg))


def test_axis_is_normalised():
    part = articulation.Part(node="n", pivot=(0.0, 0.0, 0.0),
                             axis=(0.0, 3.0, 4.0), angle_deg=90.0)
    _p, axis, _t = articulation.rotation_for(part, 1.0)
    assert math.sqrt(sum(c * c for c in axis)) == pytest.approx(1.0)


def test_degenerate_axis_does_not_produce_nan():
    """A zero axis must fall back, not emit NaN — a NaN reaching the node
    transform would take the whole hull off screen, not just a wing."""
    part = articulation.Part(node="n", pivot=(0.0, 0.0, 0.0),
                             axis=(0.0, 0.0, 0.0), angle_deg=45.0)
    _p, axis, theta = articulation.rotation_for(part, 1.0)
    assert all(math.isfinite(c) for c in axis)
    assert math.isfinite(theta)


# ── The geometry claim behind the pivots ─────────────────────────────────────

def test_pivot_sits_inboard_of_the_wing_and_outboard_of_nothing():
    """The pivots were read off the model-space AABB of the real NIF:

        left wing     X[-102.58 -12.36]
        left wing01   X[  12.36 102.58]
        birdofprey    X[ -31.12  31.37]

    A hinge must sit at the wing ROOT — inboard of the wing's own inner edge
    is wrong (it would float in open space beside the hull), and outboard of
    it is wrong too (the wing would pivot about a point along its own span).
    |X| between the wing's inner edge and the body's half-width is the band
    that can be physically right. This test is the reason a future tuning pass
    cannot silently wander outside it."""
    wing_inner_x = 12.36
    body_half_width = 31.37
    for part in articulation.rig_for("birdofprey"):
        assert wing_inner_x <= abs(part.pivot[0]) <= body_half_width, part.node


@pytest.mark.parametrize("node,tip_x", [("left wing", -102.58),
                                        ("left wing01", 102.58)])
def test_full_deflection_lifts_the_wing_tip_towards_horizontal(node, tip_x):
    """~45 deg about the fore-aft axis should bring a tip at (|X|=102.6,
    Z=-71.25) up to roughly the pivot's own height — the 'flatter and wider'
    silhouette.

    This caught a real sign error on the first pass: rotating right-handed
    about +Y, a POSITIVE angle lifts the PORT wing and SINKS the starboard
    one, and the rig shipped with the two swapped (the starboard tip went
    -71 -> -110, straight down through where the hull is). Both wings are
    checked, because a test that only covered one would have passed on the
    half that happened to be right.
    """
    part = next(p for p in articulation.rig_for("birdofprey") if p.node == node)
    px, _py, pz = part.pivot
    tip_z = -71.25
    _p, _axis, theta = articulation.rotation_for(part, 1.0)

    # Rotate the tip about the +Y axis through the pivot. Right-handed about
    # +Y: x' = x cos + z sin, z' = -x sin + z cos.
    dx, dz = tip_x - px, tip_z - pz
    new_z = pz + (-dx * math.sin(theta) + dz * math.cos(theta))

    assert new_z > tip_z, "wing must rise, not sink"
    # Tip ends up near the hinge height rather than merely nudged.
    assert abs(new_z - pz) < abs(tip_z - pz) * 0.35
