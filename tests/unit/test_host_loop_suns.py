"""Tests for _iter_suns and _aggregate_suns in host_loop."""


def test_iter_suns_yields_sun_objects():
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_iter_suns_basic")
    try:
        suns = list(host_loop._iter_suns())
        assert pSun in suns
    finally:
        App.g_kSetManager.DeleteSet("_test_iter_suns_basic")


def test_iter_suns_skips_plain_planets():
    import App
    from engine.appc.planet import Sun_Create, Planet_Create
    from engine import host_loop

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)
    pPlanet = Planet_Create(170.0, "")
    pSet.AddObjectToSet(pSun, "Sun")
    pSet.AddObjectToSet(pPlanet, "Planet")
    App.g_kSetManager.AddSet(pSet, "_test_iter_suns_no_planet")
    try:
        suns = list(host_loop._iter_suns())
        assert pSun in suns
        assert pPlanet not in suns
    finally:
        App.g_kSetManager.DeleteSet("_test_iter_suns_no_planet")


def test_iter_suns_empty_set_contributes_nothing():
    import App
    from engine import host_loop

    before = set(id(s) for s in host_loop._iter_suns())
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "_test_iter_suns_empty")
    try:
        after = set(id(s) for s in host_loop._iter_suns())
        assert after == before
    finally:
        App.g_kSetManager.DeleteSet("_test_iter_suns_empty")


def test_aggregate_suns_returns_list():
    from engine import host_loop
    result = host_loop._aggregate_suns()
    assert isinstance(result, list)


def test_aggregate_suns_returns_empty_for_sun_with_no_texture():
    """A Sun with no texture is dropped by the aggregator; result is []."""
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)  # no texture
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_agg_suns_no_tex")
    try:
        result = host_loop._aggregate_suns()
        assert isinstance(result, list)
        # All descriptors are dicts, not Sun objects
        assert pSun not in result
    finally:
        App.g_kSetManager.DeleteSet("_test_agg_suns_no_tex")


def test_aggregate_suns_applies_astro_scale(tmp_path):
    """Sun position, radius, and corona_radius are all multiplied by ASTRO_SCALE."""
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop
    from engine.scale import ASTRO_SCALE
    import engine.host_loop as hl
    import pytest

    # Use a uniquely-named texture so we can filter out leftover suns from
    # other tests that may still be sitting in g_kSetManager.
    tex_rel = "data/Textures/UniqueSunForAstroScaleTest.tga"
    tex_abs = tmp_path / "game" / tex_rel
    tex_abs.parent.mkdir(parents=True)
    tex_abs.write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 2000.0, 0.0, tex_rel, "")
    pSun.SetTranslateXYZ(10.0, 20.0, 30.0)
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_agg_suns_astro_scale")

    original_root = hl.PROJECT_ROOT
    hl.PROJECT_ROOT = tmp_path
    try:
        result = host_loop._aggregate_suns()
    finally:
        hl.PROJECT_ROOT = original_root
        App.g_kSetManager.DeleteSet("_test_agg_suns_astro_scale")

    expected_tex = str(tex_abs.resolve())
    matches = [d for d in result if d["base_texture_path"] == expected_tex]
    assert len(matches) == 1
    d = matches[0]
    assert d["position"] == pytest.approx((10.0 * ASTRO_SCALE,
                                           20.0 * ASTRO_SCALE,
                                           30.0 * ASTRO_SCALE))
    assert d["radius"]        == pytest.approx(4000.0 * ASTRO_SCALE)
    assert d["corona_radius"] == pytest.approx((4000.0 + 2000.0) * ASTRO_SCALE)
