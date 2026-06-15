"""Tests for Sun data storage and aggregate_suns_for_renderer."""
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


def test_sun_create_stores_radius():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(4000.0, 4000.0, 500.0)
    assert s.GetRadius() == 4000.0


def test_sun_create_stores_atmosphere_thickness():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(4000.0, 2500.0, 500.0)
    assert s.GetAtmosphereRadius() == 2500.0


def test_sun_create_stores_damage_per_sec():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(4000.0, 4000.0, 500.0)
    assert s.GetEnvironmentalHullDamage() == 500.0


def test_sun_create_stores_base_texture():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(1000.0, 1000.0, 500.0, "data/Textures/SunRed.tga", "")
    assert s.GetModelPath() == "data/Textures/SunRed.tga"


def test_sun_create_default_empty_texture():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(4000.0, 4000.0, 500.0)
    assert s.GetModelPath() == ""


def test_aggregate_empty_sets_returns_empty():
    from engine.appc.planet import aggregate_suns_for_renderer
    assert aggregate_suns_for_renderer(PROJECT_ROOT, []) == []


def test_aggregate_set_with_no_suns_returns_empty():
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Planet_Create
    pSet = App.SetClass_Create()
    pPlanet = Planet_Create(170.0, "data/models/environment/GreenPurplePlanet.nif")
    pSet.AddObjectToSet(pPlanet, "Planet")
    result = aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert result == []


def test_aggregate_uses_default_texture_when_none_specified():
    """Sun_Create with no texture falls back to SunBase.tga (BC engine default)."""
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)  # no texture arg
    pSet.AddObjectToSet(pSun, "Sun")
    result = aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    # SunBase.tga is present in game/data/Textures/ so the sun should be included
    assert len(result) == 1
    assert result[0]["base_texture_path"].endswith("SunBase.tga")


def test_aggregate_drops_unresolvable_texture_with_warning(capsys):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0, "data/Textures/DoesNotExist.tga", "")
    pSet.AddObjectToSet(pSun, "Sun")
    result = aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert result == []
    assert "DoesNotExist.tga" in capsys.readouterr().out


def test_aggregate_unresolvable_texture_warning_fires_once(capsys):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0, "data/Textures/DoesNotExist.tga", "")
    pSet.AddObjectToSet(pSun, "Sun")
    aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    capsys.readouterr()
    aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert capsys.readouterr().out == ""


def test_aggregate_drops_sun_with_zero_radius_silently(capsys):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(0.0, 0.0, 0.0, "data/Textures/SunBase.tga", "")
    pSet.AddObjectToSet(pSun, "Sun")
    result = aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert result == []
    assert capsys.readouterr().out == ""


def test_aggregate_returns_correct_descriptor(tmp_path):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    tex = tmp_path / "game" / "data" / "Textures" / "SunBase.tga"
    tex.parent.mkdir(parents=True)
    tex.write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0, "data/Textures/SunBase.tga", "")
    # No PlaceObjectByName — sun stays at origin (0,0,0)
    pSet.AddObjectToSet(pSun, "Sun")

    result = aggregate_suns_for_renderer(tmp_path, [pSet])
    assert len(result) == 1
    d = result[0]
    assert d["position"] == (0.0, 0.0, 0.0)
    assert d["radius"] == 4000.0
    assert d["base_texture_path"] == str(tex.resolve())
    assert d["corona_radius"] == pytest.approx(4400.0)   # radius * 1.1


def test_aggregate_corona_radius_is_1_1x_radius(tmp_path):
    """corona_radius is body_radius * 1.1, independent of atmosphere_thickness.

    atmosphere_thickness is a gameplay parameter (AI keep-out radius) — not
    a visual size. See docs/superpowers/specs/2026-05-28-sun-render-fidelity-design.md.
    """
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    tex = tmp_path / "game" / "data" / "Textures" / "SunBase.tga"
    tex.parent.mkdir(parents=True)
    tex.write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    # atmosphere_thickness=2500.0 is intentionally != radius to prove it has
    # no effect on the corona size.
    pSun = Sun_Create(1000.0, 2500.0, 0.0, "data/Textures/SunBase.tga", "")
    pSet.AddObjectToSet(pSun, "Sun")

    result = aggregate_suns_for_renderer(tmp_path, [pSet])
    assert result[0]["corona_radius"] == pytest.approx(1100.0)   # 1000 * 1.1


def test_aggregate_collects_suns_from_multiple_sets(tmp_path):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    tex = tmp_path / "game" / "data" / "Textures" / "SunBase.tga"
    tex.parent.mkdir(parents=True)
    tex.write_bytes(b"FAKE")

    pSet1 = App.SetClass_Create()
    pSun1 = Sun_Create(1000.0, 1000.0, 500.0, "data/Textures/SunBase.tga", "")
    pSet1.AddObjectToSet(pSun1, "Sun1")

    pSet2 = App.SetClass_Create()
    pSun2 = Sun_Create(4000.0, 4000.0, 500.0, "data/Textures/SunBase.tga", "")
    pSet2.AddObjectToSet(pSun2, "Sun2")

    result = aggregate_suns_for_renderer(tmp_path, [pSet1, pSet2])
    assert len(result) == 2
    radii = {d["radius"] for d in result}
    assert radii == {1000.0, 4000.0}
