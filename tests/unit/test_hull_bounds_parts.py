"""Collision pieces know which articulated part they sit on.

A severed Bird of Prey wing is hidden by the renderer (a zero node override
collapses its subtree) but the SIM had no way to know, so the wing kept
colliding and kept absorbing narrow-phase hits from empty space.
"""
import pytest

from engine.appc import hull_bounds as hb
from engine.appc import part_severance as ps


class _Ship:
    """Minimal stand-in: hull_bounds only reads __dict__, the leaf and the
    world transform. A real ShipClass satisfies all three. Identity world
    transform, so body frame == world frame and a test can assert on
    hull_spheres_world without unwinding a rotation."""

    def __init__(self):
        self._articulation_leaf = "birdofprey"
        self._articulation_deflection = 0.0

    def GetArticulationDeflection(self):
        return self._articulation_deflection

    def GetWorldLocation(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        from engine.appc.math import TGMatrix3
        return TGMatrix3()

    def GetScale(self):
        return 1.0


def _nif(spheres):
    """Undo cache_hull_bound_spheres' NIF->ship factor, so a test can state
    the sphere it wants in SHIP units and have it survive the round trip."""
    from engine.host_loop import BC_MODEL_SCALE
    inv = 1.0 / BC_MODEL_SCALE
    return [(cx * inv, cy * inv, cz * inv, r * inv) for cx, cy, cz, r in spheres]


# A point deep inside PART_BOXES["birdofprey"]["left wing"] and inside no
# other box, so part_for_point attributes it outright rather than to None.
WING_PT = (-0.80, -0.20, -0.30)
# Deep inside the "birdofprey" body box ONLY -- unambiguous, not an overlap
# case. This is the brief's original literal value.
#
# UPDATED REASONING (fix round 2, restores the brief's original literal after
# a round-1 deviation). Round 1 found that this point is NOT in the
# wing/body overlap band the brief's comment describes: part_for_point
# resolves it outright to the concrete name "birdofprey" (the body box's own
# name), not None -- confirmed by tests/unit/test_part_severance.py's own
# comment for the equivalent x=0.0 case ("inside the BODY box only (not
# ambiguous)"). Round 1 worked around that by moving BODY_PT into the
# overlap band (x=0.20), which does raw-resolve to None, but that only
# exercises part_for_point's pre-existing ambiguity rule -- it would pass
# even without the movable-part narrowing below and so proves nothing about
# it.
#
# Round 2 adds that narrowing: cache_hull_bound_spheres now tags a piece
# with a part name ONLY if that part can actually move or detach (union of
# articulation.rig_for's nodes and articulation.detachable_for's keys) --
# "birdofprey" (the body) is neither, so a piece here is untagged (None) at
# the CACHE level even though part_for_point itself resolves it to a
# concrete name. Restoring the original literal makes this point do exactly
# what it is meant to: a representative, unambiguous BODY point that proves
# the narrowing, not the overlap rule, is what untags it. See
# test_a_boxed_but_INERT_part_is_not_tagged for the same idea pinned
# explicitly against "head".
BODY_PT = (0.0, -0.20, 0.05)
# Deep inside PART_BOXES["birdofprey"]["head"] and inside no other box.
# "head" is boxed (part_for_point resolves it) but neither rigged
# (articulation.rig_for has no "head" Part) nor detachable
# (articulation.detachable_for has no "head" key) -- the exact case the
# movable-part narrowing in cache_hull_bound_spheres exists for.
HEAD_PT = (0.0, 0.5, 0.0)


def test_the_fixture_points_attribute_as_this_file_assumes():
    """Guards every other test in this file. If PART_BOXES is ever re-authored
    these constants stop meaning what the tests below need them to mean, and
    those tests would pass vacuously instead of failing here.

    WING_PT resolves to a MOVABLE part outright. BODY_PT and HEAD_PT both
    resolve to concrete, unambiguous part names -- NOT None -- because
    part_for_point knows nothing about movability; it is
    cache_hull_bound_spheres' movable-part narrowing (not part_for_point)
    that turns "birdofprey" and "head" into None downstream. Asserting the
    raw resolution here, rather than `is None`, is what makes this guard
    actually pin something: an `is None` assertion on either would pass
    whether or not the movable-part narrowing below existed."""
    assert ps.part_for_point("birdofprey", WING_PT) == "left wing"
    assert ps.part_for_point("birdofprey", BODY_PT) == "birdofprey"
    assert ps.part_for_point("birdofprey", HEAD_PT) == "head"


def test_a_wing_piece_is_tagged_with_its_part():
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    (_c, _r, part), = ship.__dict__["_hull_bound_spheres"]
    assert part == "left wing"


def test_a_body_piece_is_tagged_None():
    """Unattributed is the safe answer and must stay the common one: a piece
    with no part behaves exactly as it did before this change.

    BODY_PT resolves via part_for_point to the concrete name "birdofprey"
    (see the guard test above) -- it is the movable-part narrowing in
    cache_hull_bound_spheres, not part_for_point's ambiguity rule, that
    untags it here, because the body can neither move nor detach."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*BODY_PT, 0.05)]))
    (_c, _r, part), = ship.__dict__["_hull_bound_spheres"]
    assert part is None


def test_a_boxed_but_INERT_part_is_not_tagged():
    """A part can be boxed (part_for_point resolves it) without being
    rigged or detachable -- "head" is exactly that case. Tagging it would
    put a piece on the part-transform path (a later task) and the detach
    check for no reason it could ever act on, since the head can neither
    move nor come off. This is the case the movable-part narrowing in
    cache_hull_bound_spheres exists for."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*HEAD_PT, 0.05)]))
    (_c, _r, part), = ship.__dict__["_hull_bound_spheres"]
    assert part is None


def test_a_severed_parts_pieces_leave_hull_spheres_world(monkeypatch):
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05), (*BODY_PT, 0.05)]))
    assert len(hb.hull_spheres_world(ship)) == 2
    monkeypatch.setattr(ps, "is_detached", lambda s, name: name == "left wing")
    assert len(hb.hull_spheres_world(ship)) == 1, (
        "the severed wing's piece must stop colliding")


def test_a_severed_parts_pieces_leave_hull_spheres_near(monkeypatch):
    """hull_spheres_near is the one collisions.py and collision_avoidance.py
    actually call, and it has its own body-frame fast path — so it needs its
    own assertion, not the world variant's."""
    from engine.appc.math import TGPoint3
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05), (*BODY_PT, 0.05)]))
    here = TGPoint3(0.0, 0.0, 0.0)
    assert len(hb.hull_spheres_near(ship, here, 10.0)) == 2
    monkeypatch.setattr(ps, "is_detached", lambda s, name: name == "left wing")
    assert len(hb.hull_spheres_near(ship, here, 10.0)) == 1


def test_bound_radius_still_counts_a_severed_part(monkeypatch):
    """DELIBERATE. bound_radius is a gate that must ENCLOSE the pieces before
    a caller expands into them; over-stating it is safe, under-stating it
    lets a ship fly through geometry. Shrinking it on severance would also
    mean invalidating its memo on every detach. Left conservative on purpose
    — do not "fix" this."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    before = hb.bound_radius(ship)
    assert before > 0.0
    monkeypatch.setattr(ps, "is_detached", lambda s, name: True)
    assert hb.bound_radius(ship) == pytest.approx(before)


def test_an_unrigged_ship_tags_nothing():
    """The overwhelming majority of hulls. A ship with no rig must take
    exactly the path it took before parts existed."""
    ship = _Ship()
    ship._articulation_leaf = ""
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    (_c, _r, part), = ship.__dict__["_hull_bound_spheres"]
    assert part is None


# ── Mid-travel ───────────────────────────────────────────────────────────────

def test_a_wing_piece_moves_with_its_part_at_full_deflection():
    """The piece must sit where the wing is DRAWN. `part_transform_point` is
    the same Rodrigues hinge the renderer's node override uses, so the
    collision sphere and the drawn mesh agree by construction."""
    from engine.appc import articulation
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))

    ship._articulation_deflection = 0.0
    (rest, _r) = hb.hull_spheres_world(ship)[0]

    ship._articulation_deflection = 1.0
    (moved, _r2) = hb.hull_spheres_world(ship)[0]

    expected = articulation.part_transform_point(ship, WING_PT)
    assert (moved.x, moved.y, moved.z) != (rest.x, rest.y, rest.z)
    assert moved.x == pytest.approx(expected[0], abs=1e-6)
    assert moved.y == pytest.approx(expected[1], abs=1e-6)
    assert moved.z == pytest.approx(expected[2], abs=1e-6)


def test_an_untagged_piece_never_moves():
    """The common case, and the one that must stay byte-identical: a piece on
    no part is unaffected at any deflection."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*BODY_PT, 0.05)]))
    ship._articulation_deflection = 0.0
    (rest, _r) = hb.hull_spheres_world(ship)[0]
    ship._articulation_deflection = 1.0
    (same, _r2) = hb.hull_spheres_world(ship)[0]
    assert (same.x, same.y, same.z) == (rest.x, rest.y, rest.z)


def test_hull_spheres_near_ACCEPTS_a_piece_at_its_MOVED_position():
    """The half a weak test would miss. hull_spheres_near rejects in the
    ship's BODY frame before transforming out, so if the part transform were
    applied only to survivors, a moved piece would be rejected against its
    REST position and never returned at all."""
    from engine.appc import articulation
    from engine.appc.math import TGPoint3
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    ship._articulation_deflection = 1.0
    mx, my, mz = articulation.part_transform_point(ship, WING_PT)

    # A tight query centred on where the wing IS, too small to reach its rest
    # position. At identity world transform, body frame == world frame.
    got = hb.hull_spheres_near(ship, TGPoint3(mx, my, mz), 0.01)
    assert len(got) == 1, "a moved piece must be found where it is drawn"

    rest_only = hb.hull_spheres_near(ship, TGPoint3(*WING_PT), 0.01)
    assert rest_only == [], (
        "the piece's REST position must be empty once the wing has moved")
