"""Resolve a set name to the system and region it belongs to.

Thirty-two checked-in system maps place BC's original sets as regions
anchored in a single coordinate space per system. A set absent from every
map (bridge, QuickBattle arenas, the seven single-set multiplayer systems)
must resolve to nothing so its caller behaves exactly as today.
"""
import json

from engine.systems import map as system_map
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


def test_for_set_returns_copies_a_caller_cannot_use_to_poison_the_index():
    """A field reassignment on the returned Region must never leak into a
    later caller's lookup of the same set -- the concrete failure mode is
    Task 5's per-frame `m, r = resolve.for_set(name); r.anchor_gu = adjusted`
    poisoning every subsequent lookup for the rest of the process."""
    _, first = resolve.for_set("Ona1")
    original = first.anchor_gu
    first.anchor_gu = (999.0, 999.0, 999.0)
    _, second = resolve.for_set("Ona1")
    assert second.anchor_gu == original
    assert second.anchor_gu != (999.0, 999.0, 999.0)


def test_reset_cache_allows_rebuilding_the_index(tmp_path, monkeypatch):
    """Construct the case where a test would see stale data without
    reset_cache actually clearing it: point at one maps/ dir, resolve a set,
    repoint map_dir at a dir with a DIFFERENT answer for the same set name,
    and show the old answer persists until reset_cache() is called."""
    maps_a = tmp_path / "maps_a"
    maps_a.mkdir()
    (maps_a / "ona.json").write_text(json.dumps({
        "system": "Ona",
        "regions": [{"set_name": "Ona1", "anchor_gu": [1.0, 2.0, 3.0],
                      "radius_gu": 10.0}],
    }), encoding="utf-8")
    maps_b = tmp_path / "maps_b"
    maps_b.mkdir()
    (maps_b / "ona.json").write_text(json.dumps({
        "system": "Ona",
        "regions": [{"set_name": "Ona1", "anchor_gu": [9.0, 9.0, 9.0],
                      "radius_gu": 20.0}],
    }), encoding="utf-8")

    try:
        monkeypatch.setattr(system_map, "map_dir", lambda: maps_a)
        resolve.reset_cache()
        _, r = resolve.for_set("Ona1")
        assert r.anchor_gu == (1.0, 2.0, 3.0)

        # Repoint at a dir with a different answer. Without reset_cache the
        # stale entry built from maps_a must still be what for_set returns.
        monkeypatch.setattr(system_map, "map_dir", lambda: maps_b)
        _, r = resolve.for_set("Ona1")
        assert r.anchor_gu == (1.0, 2.0, 3.0)

        resolve.reset_cache()
        _, r = resolve.for_set("Ona1")
        assert r.anchor_gu == (9.0, 9.0, 9.0)
    finally:
        # Never leave the fake index cached for a later test once map_dir
        # reverts to the real maps/ directory at fixture teardown.
        resolve.reset_cache()
