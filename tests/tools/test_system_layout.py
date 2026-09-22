"""Layout turns a survey into a map: bodies on orbits, anchors placed to
reproduce the original framing.

The anchor rule is the one with real content -- the original set records which
DIRECTION the artist had you looking to see the planet, and the anchor must
reproduce that bearing at the new, larger scale.
"""
import math

import pytest

from tools.systems.layout import LayoutTuning, ambiguities, layout
from tools.systems.survey import SurveyedBody, SurveyedRegion, SurveyedSystem


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _sys_one_planet_per_region():
    return SurveyedSystem(
        name="Ona",
        regions=[
            SurveyedRegion(
                set_name=f"Ona{i}", ordinal=i,
                bodies=[
                    SurveyedBody(f"Ona {i}", 90.0, f"m{i}.nif", offset, False),
                    SurveyedBody("Sun", 5000.0, "sun.nif", (-70000.0, 0.0, 0.0), True),
                ],
                content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))
            for i, offset in enumerate(
                [(-97.183075, 591.702881, -7.431804),
                 (158.69548, 369.396637, 54.861767),
                 (5.948907, 506.339661, -93.216759)], start=1)
        ],
    )


def test_every_region_becomes_a_region_in_the_map():
    m = layout(_sys_one_planet_per_region())
    assert [r.set_name for r in m.regions] == ["Ona1", "Ona2", "Ona3"]


def test_exactly_one_sun_at_the_origin_owned_by_no_region():
    m = layout(_sys_one_planet_per_region())
    suns = [b for b in m.bodies if b.orbits is None]
    assert len(suns) == 1
    assert suns[0].position_gu == (0.0, 0.0, 0.0)
    assert suns[0].owner_region is None
    assert suns[0].name == "Ona"


def test_per_set_suns_are_discarded_not_carried_over():
    # BC gives each set its own sun at +-70000 GU in a different direction
    # (Ona1's at -X, Ona3's at +X, in nominally the same system). None of them
    # survives: the only star is the one at the centre, named for the system.
    m = layout(_sys_one_planet_per_region())
    assert not any(b.name == "Sun" for b in m.bodies)
    assert [b.name for b in m.bodies if b.orbits is None] == ["Ona"]


def test_orbits_increase_with_the_region_ordinal():
    t = LayoutTuning()
    m = layout(_sys_one_planet_per_region(), t)
    d = [math.dist(m.body(f"Ona {i}").position_gu, (0.0, 0.0, 0.0)) for i in (1, 2, 3)]
    assert d[0] == pytest.approx(t.first_orbit_gu)
    assert d[1] == pytest.approx(t.first_orbit_gu + t.orbit_step_gu)
    assert d[2] == pytest.approx(t.first_orbit_gu + 2 * t.orbit_step_gu)


def test_planets_are_resized_to_the_tuning():
    t = LayoutTuning()
    m = layout(_sys_one_planet_per_region(), t)
    assert m.body("Ona 1").radius_gu == pytest.approx(t.planet_radius_gu)


def test_anchor_reproduces_the_original_viewing_direction():
    """The artist put Ona 1 mostly +Y of Player Start. From the new anchor the
    planet must lie in that same direction."""
    s = _sys_one_planet_per_region()
    m = layout(s)
    region = m.region("Ona1")
    planet = m.body("Ona 1")
    original = _unit(s.regions[0].bodies[0].offset_gu)
    now = _unit(tuple(p - a for p, a in zip(planet.position_gu, region.anchor_gu)))
    assert now == pytest.approx(original, abs=1e-6)


def test_anchor_standoff_scales_with_the_new_planet_radius():
    t = LayoutTuning(anchor_standoff_factor=3.0)
    m = layout(_sys_one_planet_per_region(), t)
    d = math.dist(m.body("Ona 1").position_gu, m.region("Ona1").anchor_gu)
    assert d == pytest.approx(3.0 * t.planet_radius_gu)


def test_region_radius_covers_its_bodies_and_its_content():
    t = LayoutTuning()
    s = _sys_one_planet_per_region()
    s.regions[2].content_extent_gu = 322.0
    m = layout(s, t)
    r = m.region("Ona3")
    surface = math.dist(m.body("Ona 3").position_gu, r.anchor_gu) + t.planet_radius_gu
    assert r.radius_gu >= surface + t.region_margin_gu - 1e-6
    assert r.radius_gu >= 322.0


def test_the_largest_body_becomes_the_planet_and_the_rest_moons():
    s = SurveyedSystem(name="Beol", regions=[SurveyedRegion(
        set_name="Beol1", ordinal=1,
        bodies=[
            SurveyedBody("Beol 1", 185.0, "p.nif", (35.0, -274.9, -206.6), False),
            SurveyedBody("Beol 1 Moon 1", 110.0, "m.nif", (726.9, -540.7, -246.6), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s)
    assert m.body("Beol 1").orbits == "Beol"
    assert m.body("Beol 1 Moon 1").orbits == "Beol 1"


def test_a_moon_keeps_its_relative_size():
    s = SurveyedSystem(name="Beol", regions=[SurveyedRegion(
        set_name="Beol1", ordinal=1,
        bodies=[
            SurveyedBody("Beol 1", 200.0, "p.nif", (0.0, 500.0, 0.0), False),
            SurveyedBody("Big Moon", 100.0, "m.nif", (0.0, 900.0, 0.0), False),
            SurveyedBody("Small Moon", 25.0, "m.nif", (0.0, 700.0, 0.0), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s)
    assert m.body("Big Moon").radius_gu > m.body("Small Moon").radius_gu


def test_ambiguities_flags_a_companion_that_is_not_named_moon():
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi5", ordinal=5,
        bodies=[
            SurveyedBody("Geki", 110.0, "a.nif", (0.0, 500.0, 0.0), False),
            SurveyedBody("Inyo", 85.0, "b.nif", (0.0, 700.0, 0.0), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    notes = ambiguities(s)
    assert any("Inyo" in n for n in notes)


def test_moon_spacing_is_tunable_not_hardcoded():
    s = SurveyedSystem(name="Beol", regions=[SurveyedRegion(
        set_name="Beol1", ordinal=1,
        bodies=[
            SurveyedBody("Beol 1", 200.0, "p.nif", (0.0, 500.0, 0.0), False),
            SurveyedBody("Beol 1 Moon 1", 100.0, "m.nif", (0.0, 900.0, 0.0), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    near = layout(s, LayoutTuning(moon_first_orbit_factor=2.0))
    far = layout(s, LayoutTuning(moon_first_orbit_factor=8.0))
    d_near = math.dist(near.body("Beol 1 Moon 1").position_gu,
                       near.body("Beol 1").position_gu)
    d_far = math.dist(far.body("Beol 1 Moon 1").position_gu,
                      far.body("Beol 1").position_gu)
    assert d_far == pytest.approx(4.0 * d_near)


def test_ambiguities_flags_a_body_sitting_on_player_start():
    """A body coincident with Player Start has no viewing direction, so the
    anchor would silently default to +Y. Measured against the real SDK on
    2026-09-22 this happens in 0 of 90 regions -- so if it ever fires, the
    survey failed to resolve a waypoint and must say so, not guess."""
    s = SurveyedSystem(name="Broken", regions=[SurveyedRegion(
        set_name="Broken1", ordinal=1,
        bodies=[SurveyedBody("Ghost", 90.0, "g.nif", (0.0, 0.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    notes = ambiguities(s)
    assert any("Ghost" in n and "Player Start" in n for n in notes)


def test_ambiguities_flags_an_unnumbered_region():
    s = SurveyedSystem(name="Starbase12", regions=[SurveyedRegion(
        set_name="Starbase12", ordinal=None, bodies=[],
        content_extent_gu=100.0, player_start_gu=(0.0, 0.0, 0.0))])
    assert any("Starbase12" in n for n in ambiguities(s))


def test_a_bodiless_region_still_gets_an_anchor_and_a_radius():
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi4", ordinal=4, bodies=[],
        content_extent_gu=1870.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s)
    r = m.region("Vesuvi4")
    assert r.radius_gu >= 1870.0
    assert r.anchor_gu != (0.0, 0.0, 0.0)


def test_the_generated_map_validates():
    from engine.systems.validate import validate
    m = layout(_sys_one_planet_per_region())
    assert validate(m, sdk_set_names=["Ona1", "Ona2", "Ona3"]) == []
