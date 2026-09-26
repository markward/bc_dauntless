"""Part articulation (BoP wings) — the parts a headless test can actually see.

What these CANNOT see: whether the pivots look right. That is the whole reason
the feature shipped as a spike with a dev key — the hinge points are invented,
and only live eyes settle them. These pin the contract around them: which
signal drives a ship's state, the rest-pose identity, and the geometry claim
the pivots were derived from. The easing lives in test_articulation_states.py
with the rest of the four-state model.
"""
import math

import pytest

from engine.appc import articulation, part_pose


# ── The rig itself ───────────────────────────────────────────────────────────

def test_only_the_bird_of_prey_has_a_rig():
    """One stock hull, deliberately. A second entry appearing here is a
    decision, not a refactor — every other hull must stay unarticulated."""
    assert articulation.rig_for("birdofprey")
    for other in ("galaxy", "sovereign", "warbird", "nebula", "akira"):
        assert articulation.rig_for(other) == (), other


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
    assert port.GetName() == "left wing"
    assert starboard.GetName() == "left wing01"
    assert port.anchor[0] == -starboard.anchor[0] != 0.0
    port6, star6 = port.pose6_for("cruise"), starboard.pose6_for("cruise")
    # The swing about Y (the ry Euler) is mirrored in SIGN ...
    assert port6[4] == pytest.approx(-star6[4])
    assert port6[4] != pytest.approx(0.0)
    # ... about the same hinge axis: neither pose has any X or Z rotation, so
    # the mirroring lives in the anchor and the swing sign alone.
    for p6 in (port6, star6):
        assert p6[3] == pytest.approx(0.0, abs=1e-9)
        assert p6[5] == pytest.approx(0.0, abs=1e-9)


def test_hinge_axis_is_fore_aft():
    """The wings sweep about the ship's Y (fore-aft) axis. A pivot's Y
    component is therefore inert — rotation about a line is unchanged by
    sliding the pivot along it — which is why tuning is two numbers per wing."""
    for part in articulation.rig_for("birdofprey"):
        for state in part.authored_states():
            pose = part.pose_for(state)
            # The fore-aft axis is left fixed by the rotation ...
            assert part_pose.apply_vector(pose, (0.0, 1.0, 0.0)) == \
                pytest.approx((0.0, 1.0, 0.0), abs=1e-12)
            # ... and sliding a point along it slides the image with it: the
            # anchor's Y component is inert.
            a = part_pose.apply(pose, (0.5, 0.0, -0.3))
            b = part_pose.apply(pose, (0.5, 0.7, -0.3))
            assert (b[0], b[1] - 0.7, b[2]) == pytest.approx(a, abs=1e-12)


# ── Which signal drives a ship (OQ-11) ─────────────────────────────
#
# The 0..1 `deflection_target` / `deflection_target_for` pair these tests used
# to drive is GONE: the four-state model replaced it, and nothing outside this
# file had called either since. The live question is `state_for`, whose main
# cases live in test_articulation_states.py; the EDGE cases below moved here
# with the deletion rather than being dropped with it.

class _Sig:
    """A ship for the signal test: an alert level and a target, nothing else."""

    def __init__(self, alert=None, target=None):
        from engine.appc.ships import ShipClass
        self._alert = ShipClass.RED_ALERT if alert is None else alert
        self._target = target

    def GetAlertLevel(self):
        return self._alert

    def GetTarget(self):
        return self._target


def _no_player(monkeypatch):
    import App
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: None,
                        raising=False)


def test_an_npc_target_may_be_a_NAME_not_an_object(monkeypatch):
    """SetTarget accepts a string name OR an object reference (ships.py:1581),
    and an unresolved name stays a string. Either counts as having a target."""
    _no_player(monkeypatch)
    assert articulation.state_for(_Sig(target="Enterprise")) == "red"


def test_a_ship_with_no_target_accessor_holds_its_cruise_pose(monkeypatch):
    """A prop or a test double need not implement GetTarget. Answering
    "cruise" keeps such an object in one pose rather than raising on the
    60 Hz tick."""
    _no_player(monkeypatch)

    class _Bare:
        pass

    assert articulation.state_for(_Bare()) == "cruise"


def test_an_unresolvable_player_does_not_raise(monkeypatch):
    """Game_GetCurrentGame is absent headlessly and during teardown. This runs
    on every rigged ship every tick, so it must degrade, not throw."""
    import App
    from engine.appc.articulated_part import STATES
    monkeypatch.delattr(App, "Game_GetCurrentGame", raising=False)
    assert articulation.state_for(_Sig(target=None)) in STATES


# ── Rotation resolution ──────────────────────────────────────────────────────

_IDENTITY_M16 = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def test_rest_pose_yields_the_identity_matrix():
    """The identity matrix is the signal the binding uses to ERASE the
    override rather than store one, which is what keeps the node-override map
    empty on a ship at rest. The BoP's "red" is unset, so it is the NIF pose
    and must convert to exactly that matrix."""
    part = articulation.rig_for("birdofprey")[0]
    pose = part.pose_for("red")
    assert part_pose.is_identity(pose)
    assert part_pose.matrix4_model(pose, articulation.MODEL_TO_SHIP) == \
        _IDENTITY_M16


def test_full_deflection_matches_the_authored_angle():
    """The cruise pose is a 45-degree swing about the fore-aft hinge through
    the anchor -- the pose equivalent of the old full-deflection angle."""
    for part in articulation.rig_for("birdofprey"):
        ry = part.pose6_for("cruise")[4]
        assert abs(ry) == pytest.approx(45.0)
        want = part_pose.hinge_pose(part.anchor, (0.0, 1.0, 0.0), ry)
        got = part.pose_for("cruise")
        for x in [(1.0, 0.45, -0.67), (-1.0, 0.0, -0.7), (0.0, 0.0, 0.0)]:
            assert part_pose.apply(got, x) == pytest.approx(
                part_pose.apply(want, x), abs=1e-12)


def _legacy_part(axis):
    from engine.appc.articulated_part import ArticulatedPartProperty
    p = ArticulatedPartProperty("n")
    p.SetPivot(0.0, 0.0, 0.0)
    p.SetAxis(*axis)
    p.SetStateAngle("cruise", 90.0)
    return p


def test_axis_is_normalised():
    """A legacy hinge authored with a non-unit axis converts to a proper
    rotation (orthonormal, det +1), not a scaled one."""
    R, _t = _legacy_part((0.0, 3.0, 4.0)).pose_for("cruise")
    for i in range(3):
        col = [R[r][i] for r in range(3)]
        assert math.sqrt(sum(c * c for c in col)) == pytest.approx(1.0)
    # The axis itself is fixed by the rotation.
    assert part_pose.apply_vector((R, _t), (0.0, 0.6, 0.8)) == \
        pytest.approx((0.0, 0.6, 0.8))


def test_degenerate_axis_does_not_produce_nan():
    """A zero axis must fall back, not emit NaN — a NaN reaching the node
    transform would take the whole hull off screen, not just a wing."""
    pose = _legacy_part((0.0, 0.0, 0.0)).pose_for("cruise")
    m16 = part_pose.matrix4_model(pose, articulation.MODEL_TO_SHIP)
    assert all(math.isfinite(c) for c in m16)


def test_pivot_is_in_ship_units():
    """The pivot must share units with the derived per-part boxes
    (articulation.part_boxes_for) and subsystem mounts, which are SHIP units
    (a BoP wingtip is x = 1.008, not 100.8). It used to be in MODEL units,
    which is the same confusion that made part attribution silently never
    fire — see part_severance.MODEL_TO_SHIP."""
    port, starboard = articulation.rig_for("birdofprey")
    assert starboard.anchor[0] == pytest.approx(0.16)
    assert port.anchor[0] == pytest.approx(-0.16)
    assert starboard.anchor[2] == pytest.approx(0.05)
    # Inside the authored wing box, which is also ship units.
    box = articulation.part_boxes_for("birdofprey")["left wing01"]
    assert box[0][0] <= starboard.anchor[0] <= box[1][0]


def test_the_pose_is_ship_units_and_the_matrix_is_model_units():
    """The pose carries SHIP units; `matrix4_model` is the one place they
    become MODEL units for the node matrix."""
    part = articulation.rig_for("birdofprey")[1]
    _R, t = part.pose_for("cruise")
    assert 0.0 < max(abs(c) for c in t) < 1.0, \
        "a ship-units hinge offset is ~0.1, not ~10"
    m16 = part_pose.matrix4_model(part.pose_for("cruise"),
                                  articulation.MODEL_TO_SHIP)
    assert m16[12:15] == pytest.approx(
        tuple(c / articulation.MODEL_TO_SHIP for c in t))


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
    cannot silently wander outside it. Bounds are in SHIP units (model / 100),
    matching the part anchor since Task 1 of the hardpoint-parenting plan."""
    wing_inner_x = 12.36 * articulation.MODEL_TO_SHIP
    body_half_width = 31.37 * articulation.MODEL_TO_SHIP
    for part in articulation.rig_for("birdofprey"):
        assert wing_inner_x <= abs(part.anchor[0]) <= body_half_width, part.GetName()


@pytest.mark.parametrize("node,tip_x", [("left wing", -1.0258),
                                        ("left wing01", 1.0258)])
def test_full_deflection_lifts_the_wing_tip_towards_horizontal(node, tip_x):
    """~45 deg about the fore-aft axis should bring a tip at (|X|=1.0258,
    Z=-0.7125) up to roughly the pivot's own height — the 'flatter and wider'
    silhouette. Tip coordinates are SHIP units, matching the now-ship-unit
    pivot.

    This caught a real sign error on the first pass: rotating right-handed
    about +Y, a POSITIVE angle lifts the PORT wing and SINKS the starboard
    one, and the rig shipped with the two swapped (the starboard tip went
    -71 -> -110, straight down through where the hull is). Both wings are
    checked, because a test that only covered one would have passed on the
    half that happened to be right.
    """
    part = next(p for p in articulation.rig_for("birdofprey")
                if p.GetName() == node)
    _px, _py, pz = part.anchor
    tip_z = -0.7125
    # The authored "cruise" pose IS the full swing.
    new_z = part_pose.apply(part.pose_for("cruise"), (tip_x, 0.0, tip_z))[2]

    assert new_z > tip_z, "wing must rise, not sink"
    # Tip ends up near the hinge height rather than merely nudged.
    assert abs(new_z - pz) < abs(tip_z - pz) * 0.35


# ── Units ────────────────────────────────────────────────────────────────────

def test_the_conversion_constant_matches_BC_MODEL_SCALE():
    """`articulation.MODEL_TO_SHIP` is BC_MODEL_SCALE, duplicated rather than
    imported from `part_severance.MODEL_TO_SHIP` (or from host_loop) on
    purpose: this module and part_severance each convert a DIFFERENT
    ship-units value across the SAME model/ship boundary at their own single
    call site, and neither imports the other's conversion module for it. Do
    not "fix" that by having one import the other's constant — pin this test
    instead, so if host_loop's BC_MODEL_SCALE ever moves, this fails loudly
    rather than the wing pivot going quietly stale relative to the hull it
    is authored against. Mirrors
    test_part_severance.py::test_the_conversion_constant_matches_BC_MODEL_SCALE."""
    from engine import host_loop
    assert articulation.MODEL_TO_SHIP == pytest.approx(host_loop.BC_MODEL_SCALE)


# ── part_transform_point ─────────────────────────────────────────────────────

class _PosedShip:
    """Minimal stand-in: a leaf and a per-part pose map is all the
    transform needs (`part_transform_point` reads `pose_for_part`, which is
    backed ONLY by `ship._articulation_poses`). `deflection` here is a test
    convenience: the fraction of the way from the NIF pose to the authored
    "cruise" pose along the part's swing (`part_pose.interpolate`), matching
    what this file's fixtures actually describe (0 = rest, 1 = fully
    swung)."""

    def __init__(self, deflection, leaf="birdofprey"):
        self._articulation_leaf = leaf
        self._articulation_poses = {
            p.GetName(): part_pose.interpolate(
                part_pose.IDENTITY, p.pose_for("cruise"), p.anchor,
                deflection)
            for p in articulation.rig_for(leaf)
        }


def test_transform_is_identity_at_rest():
    """Deflection 0 is the model's authored pose. Every consumer of this must
    be byte-identical to not calling it at all."""
    p = (0.8, 0.0, -0.4)
    assert articulation.part_transform_point(_PosedShip(0.0), p) == p


def test_a_wing_point_rises_with_the_wing():
    """The starboard wingtip is the Star Cannon's mount. At full deflection it
    must follow the wing, not stay at the rest position — that gap is the live
    bug this plan fixes (~150 m on a BoP)."""
    rest = (1.008, 0.450, -0.670)
    moved = articulation.part_transform_point(_PosedShip(1.0), rest)
    assert moved[2] > rest[2], "the mount must rise with the wing"
    assert moved[1] == pytest.approx(rest[1]), "Y is the hinge axis: unchanged"
    # It moves a long way — this is why the un-parented mount was so visibly wrong.
    dist = sum((moved[i] - rest[i]) ** 2 for i in range(3)) ** 0.5
    assert dist > 0.5


def test_a_body_point_never_moves():
    """The body is not an articulated part. A warp-core mount must be
    untouched at any deflection."""
    p = (0.0, -0.33, 0.0)
    assert articulation.part_transform_point(_PosedShip(1.0), p) == p


def test_an_unrigged_ship_is_untouched():
    p = (0.8, 0.0, -0.4)
    assert articulation.part_transform_point(_PosedShip(1.0, "galaxy"), p) == p


def test_the_two_wings_mirror():
    port = articulation.part_transform_point(_PosedShip(1.0), (-1.008, 0.45, -0.67))
    star = articulation.part_transform_point(_PosedShip(1.0), (1.008, 0.45, -0.67))
    assert port[0] == pytest.approx(-star[0])
    assert port[2] == pytest.approx(star[2])


def test_a_detached_part_does_not_transform_its_point():
    """REGRESSION (finding C1b). A severed wing has no mount to follow — its
    mount point must stay put rather than follow a pose the wing no
    longer has. Mirrors the C1a fix in host_loop._sync_ship_articulation:
    both consult part_severance.is_detached, so a mount and the mesh it once
    sat on never disagree about whether the wing is still there."""
    from engine.appc import part_severance as ps

    ship = _PosedShip(1.0)
    rest = (1.008, 0.450, -0.670)
    ps.detached_parts(ship).add("left wing01")
    assert articulation.part_transform_point(ship, rest) == rest
