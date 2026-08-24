"""The projectile/ship broadphase in projectiles.update_all.

The bound exists purely for speed, so the only property that matters is that
it is CONSERVATIVE: it may reject pairs that would have missed, never a pair
that would have hit. A bound that is too small makes torpedoes silently pass
through ships, which is a gameplay bug that no test of the narrow phase would
catch — the narrow phase would simply never be asked.
"""
import pytest

from engine.appc import combat
from engine.appc.combat import SHIELD_ELLIPSOID_AXIS_SCALE


class _Ship:
    def __init__(self, radius, box=None):
        self._radius = radius
        self._shield_hull_box = box

    def GetRadius(self):
        return self._radius

    def GetScale(self):
        return 1.0


def test_bound_contains_the_hull_sphere():
    ship = _Ship(radius=4.0)
    assert combat.bubble_bound_radius(ship) >= 4.0


def test_bound_contains_the_whole_ellipsoid(monkeypatch):
    """Semi-axes are half-extents x sqrt(3); the bound must cover the largest."""
    half = (2.0, 5.0, 1.0)
    monkeypatch.setattr(combat, "_hull_box_for", lambda s: ((0.0, 0.0, 0.0), half))
    ship = _Ship(radius=1.0)
    expected = 5.0 * SHIELD_ELLIPSOID_AXIS_SCALE
    assert combat.bubble_bound_radius(ship) >= expected - 1e-9


def test_bound_accounts_for_an_off_centre_ellipsoid(monkeypatch):
    """Real hulls are off-centre — a Sovereign's model origin is ~7 GU off in
    Z. Ignoring the centre offset would under-bound by exactly that much and
    drop shots at the far end of the ship."""
    centre = (0.0, 0.0, 7.0)
    half = (2.0, 2.0, 2.0)
    monkeypatch.setattr(combat, "_hull_box_for", lambda s: (centre, half))
    ship = _Ship(radius=1.0)
    bound = combat.bubble_bound_radius(ship)
    assert bound >= 7.0 + 2.0 * SHIELD_ELLIPSOID_AXIS_SCALE - 1e-9


def test_bound_without_a_cached_box_is_still_conservative(monkeypatch):
    """No box => shield_bubble_entry returns None, but the bound must not
    shrink below what a box appearing later (realize ordering) would need."""
    monkeypatch.setattr(combat, "_hull_box_for", lambda s: None)
    ship = _Ship(radius=4.0)
    bound = combat.bubble_bound_radius(ship)
    assert bound >= 4.0 * SHIELD_ELLIPSOID_AXIS_SCALE


def test_bound_survives_a_ship_that_cannot_report_a_radius(monkeypatch):
    """Called inside a combat tick; a fake or half-built ship must not raise."""
    class _Broken:
        def GetRadius(self):
            raise RuntimeError("no radius")

    monkeypatch.setattr(combat, "_hull_box_for", lambda s: None)
    assert combat.bubble_bound_radius(_Broken()) >= 0.0
