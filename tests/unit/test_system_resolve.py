"""Resolve a set name to the system and region it belongs to.

Thirty-two checked-in system maps place BC's original sets as regions
anchored in a single coordinate space per system. A set absent from every
map (bridge, QuickBattle arenas, the seven single-set multiplayer systems)
must resolve to nothing so its caller behaves exactly as today.
"""
from engine.systems import resolve
from engine.systems.map import available, load


def test_a_region_resolves_to_its_system_and_region():
    m, r = resolve.for_set("Ona1")
    assert m.system == "Ona"
    assert r.set_name == "Ona1"
    assert r.anchor_gu != (0.0, 0.0, 0.0)


def test_every_region_of_every_map_resolves():
    """The index must cover the whole tree, not just the systems a test names."""
    for name in available():
        m = load(name)
        for r in m.regions:
            got = resolve.for_set(r.set_name)
            assert got is not None, r.set_name
            assert got[0].system == m.system


def test_a_set_that_is_not_a_region_resolves_to_nothing():
    for name in ("bridge", "QuickBattle", "Multi5", "", "ona1"):
        assert resolve.for_set(name) is None


def test_regions_of_lists_the_whole_system():
    assert sorted(resolve.regions_of("Ona")) == ["Ona1", "Ona2", "Ona3"]
    assert resolve.regions_of("Nowhere") == []


def test_vesuvi_has_three_regions_and_the_cloud_is_innermost():
    """Vesuvi1 is an orphan BC never lists and the layout no longer places it.
    Vesuvi4 -- the dust cloud -- is BC's first listed place and must be first."""
    import math
    names = resolve.regions_of("Vesuvi")
    assert names == ["Vesuvi4", "Vesuvi5", "Vesuvi6"]
    m = load("vesuvi")
    first = m.region("Vesuvi4")
    assert all(math.dist(first.anchor_gu, (0, 0, 0))
               <= math.dist(m.region(n).anchor_gu, (0, 0, 0)) for n in names)


def test_system_of_returns_system_name_only():
    assert resolve.system_of("Ona1") == "Ona"
    assert resolve.system_of("bridge") is None


def test_reset_cache_allows_rebuilding_the_index():
    resolve.for_set("Ona1")
    resolve.reset_cache()
    m, r = resolve.for_set("Ona1")
    assert m.system == "Ona"
