"""The survey reads the real SDK. Ona is the reference case: three numbered
regions, one planet each, no moons, no pins.

Values here are read out of sdk/.../Systems/Ona/ -- if the SDK changes, these
change with it, which is the point: the survey must track the source of truth,
not a snapshot of it.
"""
import pytest

from tools.systems.survey import survey_system, system_names


def test_ona_has_three_numbered_regions():
    ona = survey_system("Ona")
    assert [r.set_name for r in ona.regions] == ["Ona1", "Ona2", "Ona3"]
    assert [r.ordinal for r in ona.regions] == [1, 2, 3]


def test_ona_regions_each_hold_one_planet_and_one_sun():
    ona = survey_system("Ona")
    for r in ona.regions:
        planets = [b for b in r.bodies if not b.is_sun]
        suns = [b for b in r.bodies if b.is_sun]
        assert len(planets) == 1, r.set_name
        assert len(suns) == 1, r.set_name


def test_ona1_planet_is_read_with_its_authored_offset_and_model():
    ona = survey_system("Ona")
    r = [x for x in ona.regions if x.set_name == "Ona1"][0]
    planet = [b for b in r.bodies if not b.is_sun][0]
    assert planet.name == "Ona 1"
    assert planet.radius_gu == pytest.approx(90.0)
    assert planet.model == "data/models/environment/RedPlanet.nif"
    assert planet.offset_gu == pytest.approx((-97.183075, 591.702881, -7.431804))


def test_each_ona_region_uses_a_different_planet_model():
    ona = survey_system("Ona")
    models = sorted(b.model for r in ona.regions for b in r.bodies if not b.is_sun)
    assert models == [
        "data/models/environment/RedPlanet.nif",
        "data/models/environment/SulfurPlanet.nif",
        "data/models/environment/TanGasPlanet.nif",
    ]


def test_ona_player_starts_are_at_the_set_origin():
    ona = survey_system("Ona")
    for r in ona.regions:
        assert r.player_start_gu == pytest.approx((0.0, 0.0, 0.0)), r.set_name


def test_content_extent_excludes_bodies_and_includes_mission_placements():
    ona = survey_system("Ona")
    by_name = {r.set_name: r for r in ona.regions}
    # Ona1 and Ona2 have nothing but Player Start at the origin.
    assert by_name["Ona1"].content_extent_gu == pytest.approx(0.0, abs=1.0)
    # Ona3 is staged by E6M1_Ona3_P (Keldon starts ~300 GU out); the 515 GU
    # planet and the 70000 GU sun must NOT count.
    assert 250.0 < by_name["Ona3"].content_extent_gu < 600.0


def test_system_names_covers_the_campaign_and_excludes_utils():
    names = system_names()
    assert "Ona" in names and "Vesuvi" in names and "Alioth" in names
    assert "Utils" not in names
    assert names == sorted(names)


def test_regions_without_bodies_survey_cleanly():
    """Two shapes must not raise: Vesuvi1 has no _S file at all, and Vesuvi4's
    _S file builds a MetaNebula and no Planet or Sun."""
    vesuvi = survey_system("Vesuvi")
    names = {r.set_name for r in vesuvi.regions}
    assert {"Vesuvi1", "Vesuvi4"} <= names
    for set_name in ("Vesuvi1", "Vesuvi4"):
        region = [r for r in vesuvi.regions if r.set_name == set_name][0]
        assert region.bodies == [], set_name


def test_sun_textures_are_surveyed():
    """BC's Sun_Create carries the texture that gives a star its colour."""
    ona = survey_system("Ona")
    suns = [b for r in ona.regions for b in r.bodies if b.is_sun]
    assert suns, "Ona authors suns"
    assert all(s.base_texture.endswith("SunRed.tga") for s in suns), \
        [s.base_texture for s in suns]


def test_a_sun_with_no_texture_argument_surveys_as_empty_not_missing():
    """Itari calls Sun_Create with only three arguments -- BC's own default,
    not a parse failure."""
    itari = survey_system("Itari")
    suns = [b for r in itari.regions for b in r.bodies if b.is_sun]
    assert suns
    assert all(s.base_texture == "" for s in suns)


def test_nebulae_are_surveyed_with_colour_and_spheres():
    vesuvi = survey_system("Vesuvi")
    v4 = [r for r in vesuvi.regions if r.set_name == "Vesuvi4"][0]
    assert v4.nebula is not None
    r, g, b = v4.nebula["color"]
    assert (round(r, 3), round(g, 3), round(b, 3)) == (0.608, 0.353, 0.725)
    assert len(v4.nebula["spheres"]) == 1
    x, y, z, radius = v4.nebula["spheres"][0]
    assert (x, y, z) == pytest.approx((0.0, 1500.0, 0.0))
    assert radius == pytest.approx(1500.0)


def test_a_region_with_no_nebula_surveys_as_none():
    ona = survey_system("Ona")
    assert all(r.nebula is None for r in ona.regions)
