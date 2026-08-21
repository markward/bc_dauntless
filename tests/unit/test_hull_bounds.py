"""Per-shape hull bounds — the pieces a hull is actually made of.

A BC model carries one authored bounding sphere per NiTriShape and nothing
else: no collision mesh, no node-level bounding volumes. Those spheres are what
a shape-aware collision test descends, and the reason it matters is CONCAVITY.

A starbase's docking bay is a void BETWEEN hull pieces. Measured against the
real geometry: FinishedUndocking leaves the ship ~125 GU from the starbase
centre while its model-wide bound is ~150 GU, so with a single sphere the ship
reads as *inside the station* the whole way out. collision_avoidance then flags
it every tick — `_need_to_avoid` returns True unconditionally for anything
already within personal_space + radius — and since you cannot steer out of
something you are inside, the evasive scorer picks an arbitrary heading and
commands AVOID_SAFE_SPEED (full impulse). Live symptom: undock from Starbase 12
and the ship is yanked around by an invisible obstacle, lurching to 3969 kph
and at one point moving back TOWARD the starbase.

Against the pieces there is no such problem and no special case: the bay is
empty space, so a ship parked in it is inside none of them.
"""
import pytest

from engine.appc.hull_bounds import (
    cache_hull_bound_spheres,
    hull_spheres_world,
    point_is_inside_hull,
)
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


def _ship_with_pieces(pieces):
    """`pieces` are (center, radius) in raw model (NIF) units."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    cache_hull_bound_spheres(ship, [(c[0], c[1], c[2], r) for c, r in pieces])
    return ship


def test_no_cached_bounds_yields_nothing():
    """A ship whose model never realized (headless, or a load failure) has no
    pieces. Callers must fall back, not see a phantom hull at the origin."""
    assert hull_spheres_world(ShipClass()) == []


def test_pieces_are_scaled_from_nif_units_into_world_units():
    """Cached at GetScale() == 1 in world units, the same NIF->world factor
    _ship_world_matrix uses, so they share a frame with GetRadius()."""
    from engine.host_loop import BC_MODEL_SCALE

    ship = _ship_with_pieces([((100.0, 0.0, 0.0), 50.0)])
    (center, radius), = hull_spheres_world(ship)

    assert center.x == pytest.approx(100.0 * BC_MODEL_SCALE)
    assert radius == pytest.approx(50.0 * BC_MODEL_SCALE)


def test_pieces_follow_the_ships_position():
    ship = _ship_with_pieces([((0.0, 0.0, 0.0), 100.0)])
    ship.SetTranslateXYZ(500.0, -20.0, 7.0)

    (center, _r), = hull_spheres_world(ship)

    assert (center.x, center.y, center.z) == pytest.approx((500.0, -20.0, 7.0))


def test_pieces_follow_the_ships_rotation():
    """Offsets are body-frame: a piece out along +X must swing with the hull,
    or every bound sits in the wrong place the moment a ship turns.

    Rotated via AlignToVectors, which is the only real setter — ShipClass has
    no SetRotation, so calling one would hit TGObject.__getattr__'s _Stub and
    silently leave the ship unrotated, passing this test for the wrong reason.
    The GetCol(0) assertion below is the guard against exactly that.
    """
    from engine.host_loop import BC_MODEL_SCALE

    ship = _ship_with_pieces([((100.0, 0.0, 0.0), 10.0)])
    # right = forward x up (column-vector, right-handed): forward -X, up +Z
    # puts body +X (GetCol(0)) along world +Y.
    ship.AlignToVectors(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    starboard = ship.GetWorldRotation().GetCol(0)
    assert (starboard.x, starboard.y, starboard.z) == pytest.approx((0.0, 1.0, 0.0),
                                                                    abs=1e-6)

    (center, _r), = hull_spheres_world(ship)

    assert center.x == pytest.approx(0.0, abs=1e-6)
    assert center.y == pytest.approx(100.0 * BC_MODEL_SCALE)


def test_pieces_scale_with_getscale():
    """DockWithStarbase shrinks the player to fit through the bay doors
    (SetScale(scale * 4.0 / GetRadius())); the pieces have to shrink with it."""
    from engine.host_loop import BC_MODEL_SCALE

    ship = _ship_with_pieces([((100.0, 0.0, 0.0), 50.0)])
    ship.SetScale(2.0)

    (center, radius), = hull_spheres_world(ship)

    assert center.x == pytest.approx(100.0 * BC_MODEL_SCALE * 2.0)
    assert radius == pytest.approx(50.0 * BC_MODEL_SCALE * 2.0)


# ── The concavity that a single sphere cannot express ────────────────────────

def _starbase_with_a_bay():
    """Two hull pieces either side of a gap. Anything in the gap is inside the
    model's overall bound but inside neither piece — a docking bay."""
    s = 1.0 / 0.01     # keep the arithmetic in round world units
    return _ship_with_pieces([
        ((0.0, 120.0 * s, 0.0), 40.0 * s),
        ((0.0, -120.0 * s, 0.0), 40.0 * s),
    ])


def test_a_point_in_the_bay_is_not_inside_the_hull():
    """THE case. The origin sits between the two pieces: well within any
    model-wide bound, inside neither piece."""
    assert point_is_inside_hull(_starbase_with_a_bay(), TGPoint3(0.0, 0.0, 0.0)) is False


def test_a_point_inside_a_piece_is_inside_the_hull():
    assert point_is_inside_hull(_starbase_with_a_bay(),
                                TGPoint3(0.0, 120.0, 0.0)) is True


def test_a_point_well_outside_everything_is_not_inside_the_hull():
    assert point_is_inside_hull(_starbase_with_a_bay(),
                                TGPoint3(0.0, 5000.0, 0.0)) is False


def test_a_ship_with_no_cached_pieces_is_never_inside():
    """Fail OPEN, not closed: with no bound data we must not claim the point is
    inside a hull we know nothing about — that would resurrect the very
    false-positive this replaces."""
    assert point_is_inside_hull(ShipClass(), TGPoint3(0.0, 0.0, 0.0)) is False
