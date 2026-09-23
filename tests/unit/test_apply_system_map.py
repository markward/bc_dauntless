"""Applying a system map's authored radius/position when a region's set is
created.

engine.systems.resolve answers which region a set belongs to; this module
(engine.systems.apply_map) does the substitution itself: each body the map
names for that region takes the map's radius and set-local position, the
same object BC placed -- nothing created, nothing deleted, no model swapped.
"""
import pytest

import App
from engine.appc.planet import Planet_Create, Sun, Sun_Create
from engine.systems import apply_map, resolve
from engine.systems.map import load


def _loc(obj):
    p = obj.GetWorldLocation()
    return (p.x, p.y, p.z)


def _add_planet(pSet, name, radius, at):
    p = Planet_Create(radius, "")
    p.SetTranslateXYZ(*at)
    pSet.AddObjectToSet(p, name)
    return p


def _fake_set_with_planet(name, radius, at):
    pSet = App.SetClass_Create()
    _add_planet(pSet, name, radius, at)
    return pSet


def _fake_set_with_sun(at, radius):
    pSet = App.SetClass_Create()
    sun = Sun_Create(radius)
    sun.SetTranslateXYZ(*at)
    pSet.AddObjectToSet(sun, "Sun")
    return pSet


def _only_sun(pSet):
    suns = [obj for obj in pSet._objects.values() if isinstance(obj, Sun)]
    assert len(suns) == 1, "expected exactly one Sun in the set"
    return suns[0]


def test_a_body_takes_the_maps_radius_and_set_local_position():
    """Ona 1's planet is 110 GU at 538 GU in BC, and 2,200 GU at ~6,000 GU
    here -- the same object, re-authored around the region's anchor."""
    pSet = _fake_set_with_planet("Ona 1", radius=110.0, at=(0.0, 538.0, 0.0))
    assert apply_map.apply_to_set(pSet, "Ona1") is True
    body = pSet.GetObject("Ona 1")
    m, r = resolve.for_set("Ona1")
    expected = tuple(a - b for a, b in zip(m.body("Ona 1").position_gu, r.anchor_gu))
    assert body.GetRadius() == pytest.approx(m.body("Ona 1").radius_gu)
    assert _loc(body) == pytest.approx(expected)


def test_a_set_that_is_not_a_region_is_untouched():
    pSet = _fake_set_with_planet("Whatever", radius=110.0, at=(0.0, 538.0, 0.0))
    assert apply_map.apply_to_set(pSet, "QuickBattle") is False
    assert pSet.GetObject("Whatever").GetRadius() == pytest.approx(110.0)


def test_an_existing_sun_is_moved_to_the_maps_star():
    pSet = _fake_set_with_sun(at=(70000.0, 0.0, 0.0), radius=4000.0)
    apply_map.apply_to_set(pSet, "Ona1")
    m, r = resolve.for_set("Ona1")
    star = m.body("Ona")
    assert _loc(_only_sun(pSet)) == pytest.approx(tuple(-c for c in r.anchor_gu))
    assert _only_sun(pSet).GetRadius() == pytest.approx(star.radius_gu)


def test_a_set_with_no_sun_gets_one():
    """Belaruz and Vesuvi author no Sun_Create and still light their scenes."""
    pSet = _fake_set_with_planet("Belaruz 2", radius=120.0, at=(0.0, 500.0, 0.0))
    apply_map.apply_to_set(pSet, "Belaruz2")
    sun = _only_sun(pSet)
    assert sun is not None
    assert sun.GetRadius() == pytest.approx(load("belaruz").body("Belaruz").radius_gu)


def test_a_body_the_map_does_not_name_is_left_alone():
    pSet = _fake_set_with_planet("Ona 1", radius=110.0, at=(0.0, 538.0, 0.0))
    _add_planet(pSet, "Mystery Rock", radius=40.0, at=(10.0, 20.0, 30.0))
    apply_map.apply_to_set(pSet, "Ona1")
    rock = pSet.GetObject("Mystery Rock")
    assert rock.GetRadius() == pytest.approx(40.0)
    assert _loc(rock) == pytest.approx((10.0, 20.0, 30.0))
