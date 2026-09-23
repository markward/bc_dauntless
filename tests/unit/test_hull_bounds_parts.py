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
# In the band where the body box and a wing box overlap by design (wing roots
# are embedded in the hull, |x| in [0.1236, 0.3112]), so part_for_point can't
# pick one and returns None. That is the safe, common answer.
#
# DEVIATION FROM THE BRIEF: the brief states BODY_PT = (0.0, -0.20, 0.05).
# That point is inside ONLY the "birdofprey" body box (unambiguous), so
# part_for_point("birdofprey", (0.0, -0.20, 0.05)) returns "birdofprey", not
# None -- verified against the current PART_BOXES and confirmed by
# tests/unit/test_part_severance.py's own comment ("inside the BODY box only
# (not ambiguous)") for the equivalent x=0.0 case. Moving to x=0.20 (already
# the value test_part_severance.py uses for this exact ambiguous-overlap
# case) makes the point land in both the body and left-wing01 boxes, which is
# what the surrounding comment -- and every test below -- actually needs.
BODY_PT = (0.20, -0.20, 0.05)


def test_the_fixture_points_attribute_as_this_file_assumes():
    """Guards every other test in this file. If PART_BOXES is ever re-authored
    these two constants stop meaning what the tests below need them to mean,
    and those tests would pass vacuously instead of failing here."""
    assert ps.part_for_point("birdofprey", WING_PT) == "left wing"
    assert ps.part_for_point("birdofprey", BODY_PT) is None


def test_a_wing_piece_is_tagged_with_its_part():
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*WING_PT, 0.05)]))
    (_c, _r, part), = ship.__dict__["_hull_bound_spheres"]
    assert part == "left wing"


def test_a_body_piece_is_tagged_None():
    """Unattributed is the safe answer and must stay the common one: a piece
    with no part behaves exactly as it did before this change."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(*BODY_PT, 0.05)]))
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
