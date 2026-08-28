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
    """Real hulls are off-centre. A Sovereign's model origin is -6.98 NIF
    units in Z; the cached box is NIF x BC_MODEL_SCALE (0.01), so the real
    offset is 0.0698 GU. A Keldon's -81 NIF Y is the material one at 0.81 GU,
    against half-extents of roughly 1-5 GU. Ignoring the centre offset
    under-bounds by exactly that much and drops shots at the far end.

    Uses realistic magnitudes: the 7.0 this once carried is 100x too large
    (it read CLAUDE.md's NIF figure as GU) and made the case look far more
    lopsided than any real hull is."""
    centre = (0.0, 0.81, 0.0)
    half = (2.0, 2.0, 2.0)
    monkeypatch.setattr(combat, "_hull_box_for", lambda s: (centre, half))
    ship = _Ship(radius=1.0)
    bound = combat.bubble_bound_radius(ship)
    assert bound >= 0.81 + 2.0 * SHIELD_ELLIPSOID_AXIS_SCALE - 1e-9


def test_bound_without_a_cached_box_is_still_conservative(monkeypatch):
    """No box => shield_bubble_entry returns None, but the bound must not
    shrink below what a box appearing later (realize ordering) would need."""
    monkeypatch.setattr(combat, "_hull_box_for", lambda s: None)
    ship = _Ship(radius=4.0)
    bound = combat.bubble_bound_radius(ship)
    assert bound >= 4.0 * SHIELD_ELLIPSOID_AXIS_SCALE


def test_bound_survives_a_ship_that_cannot_report_a_radius(monkeypatch):
    """Called inside a combat tick; a fake or half-built ship must not raise.

    And the fallback must be INFINITE, not zero. A bound is only ever used to
    REJECT a pair, so the safe failure direction is "never reject": a zero
    bound culls the ship against every torpedo in the scene, silently, with no
    narrow test ever asked. `radius = 0.0` was the exactly-wrong default for a
    quantity whose docstring says it must never under-estimate.
    """
    class _Broken:
        def GetRadius(self):
            raise RuntimeError("no radius")

    monkeypatch.setattr(combat, "_hull_box_for", lambda s: None)
    assert combat.bubble_bound_radius(_Broken()) == float("inf")


def test_unreadable_radius_still_bounds_when_a_box_exists(monkeypatch):
    """The box branch must not quietly re-introduce a finite bound: max() with
    an infinite radius is still infinite, so the pair is never culled."""
    class _Broken:
        def GetRadius(self):
            raise RuntimeError("no radius")

    monkeypatch.setattr(combat, "_hull_box_for",
                        lambda s: ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))
    assert combat.bubble_bound_radius(_Broken()) == float("inf")


def test_an_infinite_bound_never_culls_in_the_broadphase():
    """End-to-end on the arithmetic the broadphase actually runs: an infinite
    bound makes `reach * reach` infinite, so no finite separation rejects."""
    bound = float("inf")
    seg_len = 3.0
    reach = bound + seg_len
    for d in (0.0, 1.0, 1e6, 1e30):
        assert not (d * d > reach * reach)


class _CountingShip:
    """Records every query update_all makes of it."""

    def __init__(self):
        self.calls = []

    def IsDead(self):
        self.calls.append("IsDead")
        return False

    def GetWorldLocation(self):
        self.calls.append("GetWorldLocation")
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)

    def GetRadius(self):
        self.calls.append("GetRadius")
        return 1.0

    def GetScale(self):
        self.calls.append("GetScale")
        return 1.0


def test_idle_scene_does_not_build_the_per_ship_cache():
    """With nothing in flight the per-ship cache has no reader, so building it
    is pure waste — and it is not cheap: per ship it is IsDead +
    GetWorldLocation + bubble_bound_radius (which itself reaches GetScale and
    GetRadius). At 100 ships that is ~500 subsystem-layer calls a tick, every
    tick, in an engine whose whole point here was to cut that number.
    """
    from engine.appc import projectiles

    assert not projectiles._active, "test needs an empty in-flight registry"
    ships = [_CountingShip() for _ in range(4)]
    hits = projectiles.update_all(1.0 / 60.0, ships)

    assert hits == []
    assert all(s.calls == [] for s in ships), [s.calls for s in ships]
