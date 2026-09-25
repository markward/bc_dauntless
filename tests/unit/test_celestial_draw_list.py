import pytest

import App
from engine.appc.sets import SetClass_Create
from engine.systems import celestial, resolve
from engine.systems import map as system_map
from tests.helpers.mapped_regions import load_region


def setup_function(_):
    App.g_kSetManager._sets.clear()


def test_every_non_star_body_of_the_system_in_view_coordinates():
    ona1 = load_region("Ona", "Ona1")
    m = system_map.load("ona")
    a1 = resolve.anchor_of("Ona1")
    got = {b.name: b for b in celestial.draw_list(ona1)}
    want = [b for b in m.bodies if b.orbits is not None]
    assert sorted(got) == sorted(b.name for b in want)
    for b in want:
        assert got[b.name].position == pytest.approx(
            tuple(p - a for p, a in zip(b.position_gu, a1)))
        assert got[b.name].radius_gu == b.radius_gu


def test_the_star_is_not_in_the_draw_list():
    ona1 = load_region("Ona", "Ona1")
    assert "Ona" not in {b.name for b in celestial.draw_list(ona1)}


def test_the_same_view_gives_the_same_list():
    ona1 = load_region("Ona", "Ona1")
    assert celestial.draw_list(ona1) == celestial.draw_list(ona1)


def test_an_unmapped_view_draws_nothing_from_a_map():
    qb = SetClass_Create()
    App.g_kSetManager.AddSet(qb, "QuickBattle")
    assert celestial.draw_list(qb) == ()
    assert celestial.draw_list(None) == ()


def test_viewing_from_a_sibling_region_shifts_by_the_anchor_difference():
    ona1, ona2 = load_region("Ona", "Ona1"), load_region("Ona", "Ona2")
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    b1 = {b.key: b for b in celestial.draw_list(ona1)}
    b2 = {b.key: b for b in celestial.draw_list(ona2)}
    assert b1.keys() == b2.keys()
    for k in b1:
        assert b1[k].position == pytest.approx(
            tuple(p + (x2 - x1) for p, x1, x2 in zip(b2[k].position, a1, a2)))


def test_draw_list_keys_bodies_by_owner_region():
    """Review Focus 5: Geble3 and Geble4 both have a body named "Moon 1"."""
    g = load_region("Geble", "Geble3")
    keys = [b.key for b in celestial.draw_list(g) if b.name == "Moon 1"]
    assert len(keys) == len(set(keys)) >= 2


def test_map_of_returns_the_cached_map_without_copying():
    import copy
    calls = []
    real = copy.deepcopy
    copy.deepcopy = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        resolve.map_of("Ona")
    finally:
        copy.deepcopy = real
    assert calls == []
