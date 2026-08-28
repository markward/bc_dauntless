"""Re-caching a ship's hull pieces must not leave the derived bound behind.

`bound_radius` memoises its unscaled answer on the instance under a SECOND
attribute. Nothing changes a ship's pieces today (realize is idempotent), but
the memo and the pieces it is derived from live in different slots, so a
re-cache that writes one and not the other hands back a radius for geometry the
ship no longer has — and `collision_avoidance`'s convergence gate is only sound
while that radius encloses every piece.
"""
from engine.appc import hull_bounds as hb


class _Ship:
    def __init__(self, scale=1.0):
        self._scale = scale

    def GetScale(self):
        return self._scale


def _nif(spheres):
    """Undo cache_hull_bound_spheres' NIF->world factor, so the world-space
    numbers below are the ones under test."""
    from engine.host_loop import BC_MODEL_SCALE
    return [(cx / BC_MODEL_SCALE, cy / BC_MODEL_SCALE, cz / BC_MODEL_SCALE,
             r / BC_MODEL_SCALE) for cx, cy, cz, r in spheres]


def test_recaching_smaller_pieces_shrinks_the_bound_radius():
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(0.0, 0.0, 0.0, 100.0)]))
    assert hb.bound_radius(ship) == 100.0          # memoises

    hb.cache_hull_bound_spheres(ship, _nif([(0.0, 0.0, 0.0, 10.0)]))
    assert hb.bound_radius(ship) == 10.0, (
        "bound_radius answered from the memo of the PREVIOUS pieces")


def test_recaching_larger_pieces_grows_the_bound_radius():
    """The direction that matters for soundness: a stale SMALLER radius would
    gate away a protruding piece and the ship would fly through it."""
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(0.0, 0.0, 0.0, 10.0)]))
    assert hb.bound_radius(ship) == 10.0

    hb.cache_hull_bound_spheres(ship, _nif([(0.0, 40.0, 0.0, 2.0)]))
    assert hb.bound_radius(ship) == 42.0, (
        "bound_radius answered from the memo of the PREVIOUS pieces")


def test_the_bound_radius_still_encloses_every_piece_after_a_recache():
    ship = _Ship()
    hb.cache_hull_bound_spheres(ship, _nif([(0.0, 0.0, 0.0, 100.0)]))
    hb.bound_radius(ship)
    pieces = [(0.0, 0.0, 0.0, 1.0), (10.0, 0.0, 0.0, 2.0), (0.0, -3.0, 4.0, 0.5)]
    hb.cache_hull_bound_spheres(ship, _nif(pieces))
    r = hb.bound_radius(ship)
    for cx, cy, cz, pr in pieces:
        assert (cx * cx + cy * cy + cz * cz) ** 0.5 + pr <= r + 1e-9
