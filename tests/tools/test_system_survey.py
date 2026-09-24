"""The survey reads the real SDK. Ona is the reference case: three numbered
regions, one planet each, no moons, no pins.

Values here are read out of sdk/.../Systems/Ona/ -- if the SDK changes, these
change with it, which is the point: the survey must track the source of truth,
not a snapshot of it.
"""
import pytest

from engine.systems import clouds
from tools.systems import survey
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


def _staged(system, set_name):
    region = [r for r in survey_system(system).regions if r.set_name == set_name][0]
    return region.staged_points


def test_staged_points_carry_mission_content_with_its_source():
    """E5M2 and E6M4 stage a base and Galors in Prendel 3. Each staged point is
    (source label, waypoint name, set-local xyz), the label naming the file."""
    staged = _staged("Prendel", "Prendel3")
    by_key = {(label, name): xyz for label, name, xyz in staged}
    assert by_key[("Maelstrom/Episode5/E5M2/Prendel3_P", "Base Location")] == pytest.approx(
        (514.0, 6098.0, 35.0), abs=1.0)
    assert any(label == "Maelstrom/Episode6/E6M4/E6M4_Prendel3_P" and name == "Base Location"
               for label, name, _ in staged)


def test_staged_points_exclude_a_bodys_own_placement_point():
    """"Planet", "Moon1" and "Moon2" are where Prendel 3's bodies are placed --
    the bodies' own points, not content -- as is the far "Sun" waypoint. A
    region-module waypoint that is not a body's point (Player Start) stays."""
    own = {name for label, name, _ in _staged("Prendel", "Prendel3")
           if label == "Systems/Prendel/Prendel3"}
    assert "Player Start" in own
    assert not own & {"Planet", "Moon1", "Moon2", "Sun"}


def test_content_extent_and_staged_points_come_from_one_scan():
    """Ona3's only non-body content is mission staging, so its extent is exactly
    the furthest staged point -- extent and staged points cannot disagree."""
    import math
    staged = _staged("Ona", "Ona3")
    region = [r for r in survey_system("Ona").regions if r.set_name == "Ona3"][0]
    assert any(label.startswith("Maelstrom/") for label, _, _ in staged)
    assert region.content_extent_gu == pytest.approx(
        max(math.sqrt(sum(c * c for c in xyz)) for _, _, xyz in staged))


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


def test_nebula_captures_bcs_four_authored_numbers():
    """visibility and sensor density are MetaNebula_Create args 4 and 5;
    damage comes from the separate SetupDamage call."""
    text = (
        'pNebula = App.MetaNebula_Create(155.0 / 255.0, 90.0 / 255.0, '
        '185.0 / 255.0, 145.0, 10.5, "a.tga", "b.tga")\n'
        'pNebula.SetupDamage(150.0, 20.0)\n'
        'pNebula.AddNebulaSphere(0.0, 1500.0, 0.0, 1500.0)\n'
    )
    neb = survey._nebula(text)
    assert neb["visibility_gu"] == pytest.approx(145.0)
    assert neb["sensor_density"] == pytest.approx(10.5)
    assert neb["damage_hull_per_s"] == pytest.approx(150.0)
    assert neb["damage_shield_per_s"] == pytest.approx(20.0)


def test_absent_setup_damage_is_a_real_zero():
    """Belaruz 1 never calls SetupDamage. That is BC saying 'this cloud does no
    damage', not BC leaving a value unspecified."""
    text = ('pNebula = App.MetaNebula_Create(100.0 / 255.0, 99.0 / 255.0, '
            '146.0 / 255.0, 200.0, 6.5, "a.tga", "b.tga")\n'
            'pNebula.AddNebulaSphere(-17.1, 844.7, -30.3, 900.0)\n')
    neb = survey._nebula(text)
    assert neb["damage_hull_per_s"] == 0.0
    assert neb["damage_shield_per_s"] == 0.0


def test_single_argument_setup_damage_leaves_the_shield_rate_unknown():
    """Multi6 calls SetupDamage(1.0). One argument means BC did not author a
    shield rate -- which is NOT the same as authoring zero."""
    text = ('pNebula = App.MetaNebula_Create(0.125, 0.125, 0.75, 75.0, 0.5, '
            '"a.tga", "b.tga")\n'
            'pNebula.SetupDamage(1.0)\n'
            'pNebula.AddNebulaSphere(50.0, 150.0, 150.0, 250.0)\n')
    neb = survey._nebula(text)
    assert neb["damage_hull_per_s"] == pytest.approx(1.0)
    assert neb["damage_shield_per_s"] is None


def test_spheres_belong_to_their_own_nebula():
    """THE BUG THIS TASK EXISTS FOR. Multi5 builds four MetaNebulae in one
    file. Collecting every AddNebulaSphere in the file gives the first nebula
    all thirteen spheres and a radius spanning the whole set."""
    text = (
        'pNebula = App.MetaNebula_Create(0.125, 0.75, 0.125, 143.0, 0.5, "a", "b")\n'
        'pNebula.AddNebulaSphere(200.0, 0.0, 0.0, 200.0)\n'
        'pNebula = App.MetaNebula_Create(0.75, 0.75, 0.125, 143.0, 0.5, "a", "b")\n'
        'pNebula.AddNebulaSphere(310.0, -125.0, -125.0, 150.0)\n'
        'pNebula.AddNebulaSphere(230.0, 125.0, 125.0, 150.0)\n'
    )
    neb = survey._nebula(text)
    assert len(neb["spheres"]) == 1
    assert neb["spheres"][0] == pytest.approx((200.0, 0.0, 0.0, 200.0))
    assert neb["extra_nebulae"] == 1


def test_damage_of_a_later_nebula_does_not_leak_onto_the_first():
    """Same scoping rule, applied to SetupDamage rather than spheres."""
    text = (
        'pNebula = App.MetaNebula_Create(0.1, 0.2, 0.3, 100.0, 1.0, "a", "b")\n'
        'pNebula.AddNebulaSphere(0.0, 0.0, 0.0, 50.0)\n'
        'pNebula = App.MetaNebula_Create(0.4, 0.5, 0.6, 100.0, 1.0, "a", "b")\n'
        'pNebula.SetupDamage(999.0, 999.0)\n'
    )
    neb = survey._nebula(text)
    assert neb["damage_hull_per_s"] == 0.0


def test_the_real_vesuvi_and_belaruz_scripts_parse_as_expected():
    """Guards the parser against the actual game files, not a hand-written
    approximation of them."""
    vesuvi4 = [r for r in survey_system("Vesuvi").regions
               if r.set_name == "Vesuvi4"][0]
    assert vesuvi4.nebula["damage_hull_per_s"] == pytest.approx(150.0)
    assert vesuvi4.nebula["damage_shield_per_s"] == pytest.approx(20.0)
    assert vesuvi4.nebula["visibility_gu"] == pytest.approx(145.0)
    assert vesuvi4.nebula["sensor_density"] == pytest.approx(10.5)
    assert vesuvi4.nebula["extra_nebulae"] == 0

    belaruz1 = [r for r in survey_system("Belaruz").regions
                if r.set_name == "Belaruz1"][0]
    assert belaruz1.nebula["damage_hull_per_s"] == 0.0
    assert belaruz1.nebula["damage_shield_per_s"] == 0.0
    assert belaruz1.nebula["sensor_density"] == pytest.approx(6.5)
    assert belaruz1.nebula["visibility_gu"] == pytest.approx(200.0)


def test_the_bc_profiles_match_what_the_sdk_actually_says():
    """engine/systems/clouds.py claims debris and nebula are BC's numbers,
    verbatim. This is the only test that can prove it: it reads the real game
    scripts and compares. If it fails, either someone tuned a constant that is
    not ours to tune, or the survey parser drifted."""
    vesuvi4 = [r for r in survey_system("Vesuvi").regions
               if r.set_name == "Vesuvi4"][0]
    belaruz1 = [r for r in survey_system("Belaruz").regions
                if r.set_name == "Belaruz1"][0]
    for region, profile in ((vesuvi4, "debris"), (belaruz1, "nebula")):
        expected = clouds.params_for(profile)
        for key in expected:
            assert region.nebula[key] == pytest.approx(expected[key]), \
                f"{profile}.{key} does not match {region.set_name}"


# ── The key directional light, and BC's own menu listing ────────────────────
# A region's BEARING from its star is derived from BC's key light, so that the
# light the artists authored already points at the star. Today the generator
# spreads regions on a golden angle, which puts the star a median 80.7 deg from
# where BC lit the scene -- and up to 178.8 deg, directly behind it.

def test_the_key_light_is_the_brightest_directional():
    """A region may author several directionals -- a key and softer fills.
    Only the brightest says where the artists put the star."""
    text = (
        'kThis = App.LightPlacement_Create("Fill", sSetName, None)\n'
        'kForward = App.TGPoint3()\n'
        'kForward.SetXYZ(1.000000, 0.000000, 0.000000)\n'
        'kThis.ConfigDirectionalLight(1.000000, 1.000000, 1.000000, 0.300000)\n'
        'kThis = App.LightPlacement_Create("Key", sSetName, None)\n'
        'kForward = App.TGPoint3()\n'
        'kForward.SetXYZ(0.000000, 1.000000, 0.000000)\n'
        'kThis.ConfigDirectionalLight(0.600000, 0.600000, 0.800000, 0.700000)\n'
    )
    assert survey._key_light(text) == pytest.approx((0.0, 1.0, 0.0))


def test_the_key_light_is_returned_normalised():
    text = ('kForward = App.TGPoint3()\n'
            'kForward.SetXYZ(3.000000, 4.000000, 0.000000)\n'
            'kThis.ConfigDirectionalLight(1.0, 1.0, 1.0, 0.5)\n')
    assert survey._key_light(text) == pytest.approx((0.6, 0.8, 0.0))


def test_a_region_with_no_directional_light_has_no_key_light():
    assert survey._key_light(
        'kThis.ConfigAmbientLight(1.000000, 1.000000, 1.000000, 0.250000)\n') is None


def test_the_real_regions_carry_their_authored_key_light():
    """Belaruz 1 holds the brightest directional in the game: pure white at
    full strength, pointing +Y."""
    b1 = [r for r in survey_system("Belaruz").regions
          if r.set_name == "Belaruz1"][0]
    assert b1.key_light_dir == pytest.approx((0.0, 1.0, 0.0), abs=1e-3)

    v5 = [r for r in survey_system("Vesuvi").regions
          if r.set_name == "Vesuvi5"][0]
    assert v5.key_light_dir is not None
    assert abs(sum(c * c for c in v5.key_light_dir) - 1.0) < 1e-6


def test_menu_listing_marks_the_places_bc_actually_offers():
    """Vesuvi1 is an orphan: still in the tree, never listed. It must not take
    an orbital slot ahead of Vesuvi4, BC's first listed place."""
    vesuvi = {r.set_name: r.menu_listed for r in survey_system("Vesuvi").regions}
    assert vesuvi["Vesuvi1"] is False
    assert vesuvi["Vesuvi4"] is True and vesuvi["Vesuvi5"] is True


def test_a_single_place_system_lists_its_only_place():
    """CreateSystemMenu("Riha", "Systems.Riha.Riha1") passes a default and no
    list at all. The default IS the place -- reading only the tail arguments
    marks every single-place system unlisted, which it is not."""
    riha = {r.set_name: r.menu_listed for r in survey_system("Riha").regions}
    assert riha["Riha1"] is True
