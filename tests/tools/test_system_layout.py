"""Layout turns a survey into a map: bodies on orbits, anchors placed to
reproduce the original framing.

The anchor rule is the one with real content -- the original set records which
DIRECTION the artist had you looking to see the planet, and the anchor must
reproduce that bearing at the new, larger scale.
"""
import math

import pytest

from tools.systems.layout import LayoutTuning, _first_orbit_push, _norm, ambiguities, layout
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
    sun = [b for b in m.bodies if b.orbits is None][0]
    first_orbit = sun.radius_gu + t.first_orbit_clearance_gu
    d = [math.dist(m.body(f"Ona {i}").position_gu, (0.0, 0.0, 0.0)) for i in (1, 2, 3)]
    assert d[0] == pytest.approx(first_orbit)
    assert d[1] == pytest.approx(first_orbit + t.orbit_step_gu)
    assert d[2] == pytest.approx(first_orbit + 2 * t.orbit_step_gu)


def test_planets_are_resized_to_the_tuning():
    t = LayoutTuning()
    m = layout(_sys_one_planet_per_region(), t)
    # Ona 1's authored BC radius is 90.0 GU (see _sys_one_planet_per_region).
    assert m.body("Ona 1").radius_gu == pytest.approx(90.0 * t.planet_radius_scale)


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
    """The standoff factor is measured in planet radii, so doubling
    planet_radius_scale doubles the standoff distance even though the factor
    itself is unchanged."""
    s = _sys_one_planet_per_region()
    m1 = layout(s, LayoutTuning(planet_radius_scale=20.0))
    m2 = layout(s, LayoutTuning(planet_radius_scale=40.0))
    d1 = math.dist(m1.body("Ona 1").position_gu, m1.region("Ona1").anchor_gu)
    d2 = math.dist(m2.body("Ona 1").position_gu, m2.region("Ona1").anchor_gu)
    assert d2 == pytest.approx(2.0 * d1)


def test_region_radius_covers_its_bodies_and_its_content():
    t = LayoutTuning()
    s = _sys_one_planet_per_region()
    s.regions[2].content_extent_gu = 322.0
    m = layout(s, t)
    r = m.region("Ona3")
    body = m.body("Ona 3")
    surface = math.dist(body.position_gu, r.anchor_gu) + body.radius_gu
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


def test_framing_scale_one_reproduces_bc_apparent_size_exactly():
    """The radii cancel: standoff is measured in planet radii, so at
    framing_scale 1.0 the new angular size EQUALS BC's, not approximates it."""
    s = _sys_one_planet_per_region()
    m = layout(s, LayoutTuning(framing_scale=1.0))
    for region in s.regions:
        bc = region.bodies[0]
        d_bc = math.dist(bc.offset_gu, region.player_start_gu)
        want = 2.0 * math.atan(bc.radius_gu / d_bc)
        body = m.body(bc.name)
        d_new = math.dist(body.position_gu, m.region(region.set_name).anchor_gu)
        got = 2.0 * math.atan(body.radius_gu / d_new)
        assert got == pytest.approx(want, rel=1e-9), region.set_name


def test_apparent_size_is_independent_of_the_size_scale():
    """planet_radius_scale and framing_scale must not interact."""
    s = _sys_one_planet_per_region()
    angles = []
    for scale in (10.0, 20.0, 40.0):
        m = layout(s, LayoutTuning(planet_radius_scale=scale))
        body = m.body("Ona 1")
        d = math.dist(body.position_gu, m.region("Ona1").anchor_gu)
        angles.append(2.0 * math.atan(body.radius_gu / d))
    assert angles[1] == pytest.approx(angles[0], rel=1e-12)
    assert angles[2] == pytest.approx(angles[0], rel=1e-12)


def test_planets_keep_bcs_relative_sizes():
    """BC authored a 15x spread across 87 primaries. A flat radius threw it away."""
    s = SurveyedSystem(name="Alioth", regions=[
        SurveyedRegion(set_name="Alioth1", ordinal=1, bodies=[
            SurveyedBody("Alioth 1", 90.0, "a.nif", (0.0, 1000.0, 0.0), False)],
            content_extent_gu=0.0, player_start_gu=(0.0, -500.0, 0.0)),
        SurveyedRegion(set_name="Alioth6", ordinal=6, bodies=[
            SurveyedBody("Alioth 6", 360.0, "b.nif", (0.0, 1000.0, 0.0), False)],
            content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0)),
    ])
    m = layout(s, LayoutTuning(planet_radius_scale=20.0))
    assert m.body("Alioth 1").radius_gu == pytest.approx(1800.0)
    assert m.body("Alioth 6").radius_gu == pytest.approx(7200.0)


def test_moons_keep_bcs_relative_sizes():
    s = SurveyedSystem(name="Serris", regions=[SurveyedRegion(
        set_name="Serris3", ordinal=3,
        bodies=[
            SurveyedBody("Serris 3", 100.0, "p.nif", (0.0, 500.0, 0.0), False),
            SurveyedBody("Serris 3 Moon 1", 7.0, "m.nif", (0.0, 600.0, 0.0), False),
            SurveyedBody("Serris 3 Moon 2", 20.0, "m.nif", (0.0, 700.0, 0.0), False),
        ],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s, LayoutTuning(moon_radius_scale=20.0))
    assert m.body("Serris 3 Moon 1").radius_gu == pytest.approx(140.0)
    assert m.body("Serris 3 Moon 2").radius_gu == pytest.approx(400.0)


def test_the_sun_scales_from_bcs_authored_radius():
    s = _sys_one_planet_per_region()          # its suns are authored at 5000 GU
    m = layout(s, LayoutTuning(sun_radius_scale=2.0))
    sun = [b for b in m.bodies if b.orbits is None][0]
    assert sun.radius_gu == pytest.approx(10000.0)


def test_a_system_with_no_authored_sun_still_gets_one():
    """Belaruz and Vesuvi build a MetaNebula and no Sun_Create at all."""
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi5", ordinal=5,
        bodies=[SurveyedBody("Geki", 110.0, "g.nif", (0.0, 538.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    m = layout(s, LayoutTuning(brown_dwarf_radius_gu=9000.0))
    sun = [b for b in m.bodies if b.orbits is None][0]
    assert sun.radius_gu == pytest.approx(9000.0)


def test_the_first_orbit_clears_the_suns_surface():
    """first_orbit_clearance_gu is measured from the SUN'S SURFACE, so a bigger
    sun pushes every orbit out rather than swallowing the innermost planet."""
    s = _sys_one_planet_per_region()
    m = layout(s, LayoutTuning(sun_radius_scale=2.0,
                               first_orbit_clearance_gu=30000.0))
    sun = [b for b in m.bodies if b.orbits is None][0]
    innermost = math.dist(m.body("Ona 1").position_gu, (0.0, 0.0, 0.0))
    assert innermost == pytest.approx(sun.radius_gu + 30000.0)


def test_the_standoff_is_clamped_at_both_ends():
    """Savoy 1 is why the cap exists: BC put a 100 GU planet 5041 GU away, a
    50:1 ratio, which uncapped throws the anchor far enough to pass the sun."""
    def one(radius, distance, tuning):
        s = SurveyedSystem(name="X", regions=[SurveyedRegion(
            set_name="X1", ordinal=1,
            bodies=[SurveyedBody("P", radius, "p.nif", (0.0, distance, 0.0), False)],
            content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
        m = layout(s, tuning)
        return (math.dist(m.body("P").position_gu, m.region("X1").anchor_gu)
                / m.body("P").radius_gu)

    t = LayoutTuning(min_standoff_factor=1.5, max_standoff_factor=12.0,
                     framing_scale=2.0)
    assert one(100.0, 5041.0, t) == pytest.approx(12.0)     # Savoy 1, capped
    assert one(200.0, 400.0, t) == pytest.approx(1.5)       # very close, floored
    assert one(90.0, 600.4, t) == pytest.approx(600.4 / 90.0 / 2.0)  # untouched


def test_ambiguities_reports_every_clamped_region():
    """A clamp overrides BC's intent, so the art-direction pass must see it."""
    s = SurveyedSystem(name="Savoy", regions=[SurveyedRegion(
        set_name="Savoy1", ordinal=1,
        bodies=[SurveyedBody("Savoy 1", 100.0, "p.nif", (0.0, 5041.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    assert any("Savoy 1" in n and "clamp" in n.lower() for n in ambiguities(s))


def test_two_regions_may_share_a_bare_companion_name():
    """BC reuses bare companion names across regions of one system: Geble3 has
    'Moon 1' and 'Moon 2', Geble4 also has a 'Moon 1'. A by-name lookup then
    resolves to whichever body was built first, corrupting the other region's
    anchor centroid."""
    s = SurveyedSystem(name="Geble", regions=[
        SurveyedRegion(set_name="Geble3", ordinal=3, bodies=[
            SurveyedBody("Geble 3", 180.0, "p.nif", (484.0, 457.0, 570.0), False),
            SurveyedBody("Moon 1", 100.0, "m.nif", (-150.0, 97.0, -83.0), False),
        ], content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0)),
        SurveyedRegion(set_name="Geble4", ordinal=4, bodies=[
            SurveyedBody("Geble 4", 120.0, "p.nif", (250.0, -4000.0, 0.0), False),
            SurveyedBody("Moon 1", 50.0, "m.nif", (450.0, -4000.0, 0.0), False),
        ], content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0)),
    ])
    m = layout(s)
    moons = [b for b in m.bodies if b.name == "Moon 1"]
    assert len(moons) == 2, "both regions' moons must exist as distinct bodies"
    by_owner = {b.owner_region: b for b in moons}
    assert set(by_owner) == {"Geble3", "Geble4"}
    # Each moon must sit near ITS OWN region's planet, not the other's.
    for set_name in ("Geble3", "Geble4"):
        planet = [b for b in m.bodies
                  if b.owner_region == set_name and b.orbits == "Geble"][0]
        moon = by_owner[set_name]
        assert math.dist(moon.position_gu, planet.position_gu) < 20000.0, set_name
    # And each region's anchor must be near its own group, not the other's.
    # Geble4's own offsets (250, -4000, 0) genuinely hit the MAX standoff
    # clamp here -- the same clamp the real Geble4 hits in gen_system_maps.py
    # --check -- so the legitimate anchor can sit up to
    # max_standoff_factor * primary_radius_gu out (~28800 GU for this test's
    # 120 GU BC radius). The bug this guards against put the anchor ~75000 GU
    # away by borrowing the OTHER region's centroid, so a generous multiple
    # of the clamp still separates "correct but far" from "wrong region".
    t = LayoutTuning()
    for set_name in ("Geble3", "Geble4"):
        planet = [b for b in m.bodies
                  if b.owner_region == set_name and b.orbits == "Geble"][0]
        anchor = m.region(set_name).anchor_gu
        limit = t.max_standoff_factor * planet.radius_gu * 1.5
        assert math.dist(anchor, planet.position_gu) < limit, set_name


def test_a_pinned_body_lands_at_its_authored_offset_from_the_anchor():
    """A pin exists so a mission's staged ships stay beside the body they were
    authored beside. E5M2 parks a base and three Galors just past Prendel 3's
    Moon 2, so that moon must keep its set-local position exactly."""
    s = SurveyedSystem(name="Prendel", regions=[SurveyedRegion(
        set_name="Prendel3", ordinal=3,
        bodies=[
            SurveyedBody("Prendel 3", 360.0, "p.nif", (-1000.0, 1500.0, 0.0), False),
            SurveyedBody("Moon 1", 90.0, "m.nif", (-5000.0, 0.0, 0.0), False),
            SurveyedBody("Moon 2", 90.0, "m.nif", (400.0, 5000.0, 0.0), False),
        ],
        content_extent_gu=6368.0, player_start_gu=(0.0, 0.0, 0.0))])
    pins = {"Prendel3/Moon 2": (400.0, 5000.0, 0.0)}
    m = layout(s, pins=pins)
    anchor = m.region("Prendel3").anchor_gu
    moon = m.body("Moon 2")
    have = tuple(p - a for p, a in zip(moon.position_gu, anchor))
    assert have == pytest.approx((400.0, 5000.0, 0.0), abs=1e-6)


def test_an_unpinned_body_in_the_same_region_is_not_moved():
    """Pinning one companion must not disturb its siblings."""
    s = SurveyedSystem(name="Prendel", regions=[SurveyedRegion(
        set_name="Prendel3", ordinal=3,
        bodies=[
            SurveyedBody("Prendel 3", 360.0, "p.nif", (-1000.0, 1500.0, 0.0), False),
            SurveyedBody("Moon 1", 90.0, "m.nif", (-5000.0, 0.0, 0.0), False),
            SurveyedBody("Moon 2", 90.0, "m.nif", (400.0, 5000.0, 0.0), False),
        ],
        content_extent_gu=6368.0, player_start_gu=(0.0, 0.0, 0.0))])
    free = layout(s).body("Moon 1").position_gu
    pinned = layout(s, pins={"Prendel3/Moon 2": (400.0, 5000.0, 0.0)}).body("Moon 1")
    assert pinned.position_gu == pytest.approx(free)


def test_layout_ignores_a_pin_naming_something_that_does_not_exist():
    """validate() reports those; layout() must not also decide, or the two can
    disagree about the same map."""
    s = _sys_one_planet_per_region()
    m = layout(s, pins={"Nowhere/Ghost": (0.0, 0.0, 0.0),
                        "Ona1/Ghost": (0.0, 0.0, 0.0),
                        "malformed key": (0.0, 0.0, 0.0)})
    assert m.region("Ona1") is not None
    assert m.body("Ona 1") is not None


def test_a_pinned_map_passes_the_pin_rule_end_to_end():
    """The whole point: declare a pin, lay out, and validate() must be happy."""
    from engine.systems.validate import validate
    s = SurveyedSystem(name="Prendel", regions=[SurveyedRegion(
        set_name="Prendel3", ordinal=3,
        bodies=[
            SurveyedBody("Prendel 3", 360.0, "p.nif", (-1000.0, 1500.0, 0.0), False),
            SurveyedBody("Moon 2", 90.0, "m.nif", (400.0, 5000.0, 0.0), False),
        ],
        content_extent_gu=6368.0, player_start_gu=(0.0, 0.0, 0.0))])
    pins = {"Prendel3/Moon 2": (400.0, 5000.0, 0.0)}
    m = layout(s, pins=pins)
    assert validate(m, pins=pins) == []


def test_the_first_orbit_is_pushed_out_until_no_region_reaches_the_star():
    """Voltair 1's sphere contained its star's centre. The innermost orbit must
    move out far enough to clear it -- and every other orbit moves with it."""
    # content_extent_gu=30000.0, not a smaller value: with the region's own
    # reach only 7500 GU, a content_extent of 20000.0 yields a region radius
    # of 21500 GU, which clears the star (sun_radius 8000, clearance 500) at
    # the baseline first orbit with 3500 GU to spare -- _first_orbit_push()
    # returns push=0.0 for that input, so the test would pass even with the
    # push mechanism disabled. 30000.0 yields radius 31500, which genuinely
    # intrudes (by 6500 GU) and so genuinely exercises the code path this
    # test names. Same arithmetic as test_ambiguities_reports_a_pushed_first_orbit.
    s = SurveyedSystem(name="Tight", regions=[
        SurveyedRegion(set_name="Tight1", ordinal=1, bodies=[
            SurveyedBody("Sun", 4000.0, "", (-70000.0, 0.0, 0.0), True),
            SurveyedBody("Tight 1", 150.0, "p.nif", (0.0, 400.0, 0.0), False),
        ], content_extent_gu=30000.0, player_start_gu=(0.0, 0.0, 0.0)),
        SurveyedRegion(set_name="Tight2", ordinal=2, bodies=[
            SurveyedBody("Sun", 4000.0, "", (-70000.0, 0.0, 0.0), True),
            SurveyedBody("Tight 2", 150.0, "p.nif", (0.0, 400.0, 0.0), False),
        ], content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0)),
    ])
    t = LayoutTuning()
    push, _probe_m = _first_orbit_push(s, t, {})
    assert push > 0.0, "fixture must genuinely require a push, or this test cannot fail"
    m = layout(s, t)
    star = [b for b in m.bodies if b.orbits is None][0]
    for r in m.regions:
        gap = math.dist(r.anchor_gu, star.position_gu) - r.radius_gu - star.radius_gu
        assert gap > 0.0, f"{r.set_name} reaches the star by {-gap:.0f} GU"


def test_a_system_that_already_clears_its_star_is_not_moved():
    """The push must be corrective, not a blanket increase -- most systems are
    already clear and their numbers must not drift."""
    s = _sys_one_planet_per_region()
    t = LayoutTuning()
    m = layout(s, t)
    sun = [b for b in m.bodies if b.orbits is None][0]
    innermost = min(math.dist(b.position_gu, (0.0, 0.0, 0.0))
                    for b in m.bodies if b.orbits is not None)
    assert innermost == pytest.approx(sun.radius_gu + t.first_orbit_clearance_gu)


def test_the_star_takes_bcs_authored_colour():
    s = _sys_one_planet_per_region()
    for r in s.regions:
        for b in r.bodies:
            if b.is_sun:
                b.base_texture = "data/Textures/SunBlueWhite.tga"
    star = [b for b in layout(s).bodies if b.orbits is None][0]
    assert star.appearance.star_class == "blue_white"
    assert star.appearance.color == pytest.approx((0.74, 0.84, 1.0))


def test_a_sun_with_no_texture_is_white_not_unclassified():
    s = _sys_one_planet_per_region()          # its fixtures carry no texture
    star = [b for b in layout(s).bodies if b.orbits is None][0]
    assert star.appearance.star_class == "white"


def test_a_system_with_no_sun_gets_a_brown_dwarf():
    """Belaruz and Vesuvi author no Sun_Create at all."""
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi5", ordinal=5,
        bodies=[SurveyedBody("Geki", 110.0, "g.nif", (0.0, 538.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])
    t = LayoutTuning(brown_dwarf_radius_gu=2000.0)
    star = [b for b in layout(s, t).bodies if b.orbits is None][0]
    assert star.appearance.star_class == "brown_dwarf"
    assert star.radius_gu == pytest.approx(2000.0)


def test_a_regions_nebula_is_carried_into_the_map():
    s = SurveyedSystem(name="Vesuvi", regions=[SurveyedRegion(
        set_name="Vesuvi4", ordinal=4, bodies=[],
        content_extent_gu=1870.0, player_start_gu=(0.0, 0.0, 0.0),
        nebula={"color": (0.608, 0.353, 0.725),
                "spheres": [(0.0, 1500.0, 0.0, 1500.0)],
                "visibility_gu": 145.0, "sensor_density": 10.5,
                "damage_hull_per_s": 150.0, "damage_shield_per_s": 20.0,
                "extra_nebulae": 0})])
    region = layout(s).region("Vesuvi4")
    assert region.nebula["color"] == pytest.approx((0.608, 0.353, 0.725))
    assert region.nebula["spheres"][0][3] == pytest.approx(1500.0)


def test_ambiguities_reports_a_system_whose_suns_disagree():
    s = _sys_one_planet_per_region()
    suns = [b for r in s.regions for b in r.bodies if b.is_sun]
    suns[0].base_texture = "data/Textures/SunRed.tga"
    suns[1].base_texture = "data/Textures/SunBlueWhite.tga"
    suns[2].base_texture = "data/Textures/SunBlueWhite.tga"
    notes = ambiguities(s)
    assert any("colour" in n.lower() or "texture" in n.lower() for n in notes)


def test_ambiguities_reports_a_pushed_first_orbit():
    # content_extent_gu=30000.0, not the brief's 20000.0: with the region's
    # OWN reach only 7500 GU, a content_extent of 20000.0 yields a region
    # radius of 21500 GU, which clears the star (sun_radius 8000, clearance
    # 500) at the baseline first orbit with 3500 GU to spare -- verified via
    # _first_orbit_push(), which returns push=0.0 for that input. 30000.0
    # yields radius 31500, which genuinely intrudes (by 6500 GU) and so
    # genuinely exercises the code path this test names.
    s = SurveyedSystem(name="Tight", regions=[SurveyedRegion(
        set_name="Tight1", ordinal=1, bodies=[
            SurveyedBody("Sun", 4000.0, "", (-70000.0, 0.0, 0.0), True),
            SurveyedBody("Tight 1", 150.0, "p.nif", (0.0, 400.0, 0.0), False),
        ], content_extent_gu=30000.0, player_start_gu=(0.0, 0.0, 0.0))])
    assert any("first orbit" in n.lower() for n in ambiguities(s))


def _sunless(name="Vesuvi", set_name="Vesuvi5"):
    return SurveyedSystem(name=name, regions=[SurveyedRegion(
        set_name=set_name, ordinal=5,
        bodies=[SurveyedBody("Geki", 110.0, "g.nif", (0.0, 538.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))])


def test_a_star_override_wins_over_the_derived_class():
    m = layout(_sunless(), star={"star_class": "remnant_hot"})
    star = [b for b in m.bodies if b.orbits is None][0]
    assert star.appearance.star_class == "remnant_hot"
    assert star.appearance.color == pytest.approx((0.78, 0.86, 1.0))


def test_a_star_override_may_set_an_explicit_colour_and_radius():
    m = layout(_sunless(), star={"star_class": "white",
                                 "color": [1.0, 0.97, 0.93],
                                 "radius_gu": 8000.0})
    star = [b for b in m.bodies if b.orbits is None][0]
    assert star.appearance.color == pytest.approx((1.0, 0.97, 0.93))
    assert star.radius_gu == pytest.approx(8000.0)


def test_a_bigger_overridden_star_pushes_its_first_orbit_out():
    """first_orbit is measured from the star's SURFACE, so a larger star must
    carry every orbit outward rather than swallowing the innermost planet."""
    t = LayoutTuning()
    small = layout(_sunless())
    big = layout(_sunless(), star={"star_class": "white", "radius_gu": 8000.0})
    d_small = math.dist(small.body("Geki").position_gu, (0.0, 0.0, 0.0))
    d_big = math.dist(big.body("Geki").position_gu, (0.0, 0.0, 0.0))
    assert d_small == pytest.approx(t.brown_dwarf_radius_gu
                                    + t.first_orbit_clearance_gu)
    assert d_big == pytest.approx(8000.0 + t.first_orbit_clearance_gu)


def test_no_override_leaves_todays_behaviour_untouched():
    star = [b for b in layout(_sunless()).bodies if b.orbits is None][0]
    assert star.appearance.star_class == "brown_dwarf"


def _nebula_region(set_name="Vesuvi4", hull=150.0, shield=20.0,
                   vis=145.0, dens=10.5, spheres=((0.0, 1500.0, 0.0, 1500.0),)):
    return SurveyedRegion(
        set_name=set_name, ordinal=4, bodies=[], content_extent_gu=2067.0,
        player_start_gu=(0.0, 0.0, 0.0),
        nebula={"color": (0.61, 0.35, 0.73), "spheres": list(spheres),
                "visibility_gu": vis, "sensor_density": dens,
                "damage_hull_per_s": hull, "damage_shield_per_s": shield,
                "extra_nebulae": 0})


def test_no_nebula_anywhere_means_no_cloud():
    m = layout(SurveyedSystem(name="Ona", regions=[SurveyedRegion(
        set_name="Ona1", ordinal=1,
        bodies=[SurveyedBody("Ona 1", 120.0, "p.nif", (0.0, 500.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))]))
    assert m.clouds == []


def test_the_pocket_volume_sits_at_anchor_plus_bcs_offset():
    """The pinned volume. Its centre is the region's anchor plus BC's own
    set-local sphere -- that transform is the entire reason a system-scale
    cloud can exist without a second source of truth."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    m = layout(s, cloud={"name": "V", "display_name": "V", "kind": "debris_shell"})
    anchor = m.region("Vesuvi4").anchor_gu
    pocket = [v for v in m.clouds[0].volumes if v.origin_region == "Vesuvi4"][0]
    assert pocket.geometry["center_gu"] == pytest.approx(
        (anchor[0] + 0.0, anchor[1] + 1500.0, anchor[2] + 0.0))
    assert pocket.geometry["radius_gu"] == pytest.approx(1500.0)


def test_the_profile_comes_from_bcs_damage_not_from_the_override():
    s_hot = SurveyedSystem(name="Vesuvi", regions=[_nebula_region(hull=150.0)])
    s_cold = SurveyedSystem(name="Belaruz", regions=[
        _nebula_region(set_name="Belaruz1", hull=0.0, shield=0.0,
                       vis=200.0, dens=6.5)])
    hot = layout(s_hot, cloud={"name": "V", "display_name": "V",
                               "kind": "debris_shell"})
    cold = layout(s_cold, cloud={"name": "B", "display_name": "B",
                                 "kind": "nebula_field",
                                 "geometry": {"near_gu": 1.0, "far_gu": 2.0,
                                              "radius_gu": 3.0}})
    assert [v.profile for v in hot.clouds[0].volumes
            if v.origin_region][0] == "debris"
    assert [v.profile for v in cold.clouds[0].volumes
            if v.origin_region][0] == "nebula"

    # Crossed case: a "debris_shell" kind paired with BC's ZERO damage. An
    # implementation that (wrongly) read the profile off the override's
    # `kind` rather than the survey's damage would pass the two assertions
    # above unchanged -- this is the one that actually pins the ruling.
    s_crossed = SurveyedSystem(name="Crossed", regions=[
        _nebula_region(set_name="Crossed1", hull=0.0, shield=0.0)])
    crossed = layout(s_crossed, cloud={"name": "C", "display_name": "C",
                                       "kind": "debris_shell"})
    assert [v.profile for v in crossed.clouds[0].volumes
            if v.origin_region][0] == "nebula"


def test_the_shell_radius_is_derived_from_its_member_regions():
    """Not declared. The shell reaches exactly as far as the debris does."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    m = layout(s, cloud={"name": "V", "display_name": "V", "kind": "debris_shell"})
    region = m.region("Vesuvi4")
    expected = _norm(region.anchor_gu) + region.radius_gu
    shell = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    assert shell.shape == "sphere"
    assert shell.geometry["radius_gu"] == pytest.approx(expected)
    assert shell.geometry["center_gu"] == pytest.approx((0.0, 0.0, 0.0))


def test_the_large_volume_is_inert_until_mist_is_tuned():
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    m = layout(s, cloud={"name": "V", "display_name": "V", "kind": "debris_shell"})
    shell = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    assert shell.profile == "mist"
    assert all(value == 0.0 for value in shell.params.values())


def test_the_lobe_axis_points_at_bcs_pocket():
    s = SurveyedSystem(name="Belaruz", regions=[
        _nebula_region(set_name="Belaruz1", hull=0.0, shield=0.0)])
    m = layout(s, cloud={"name": "B", "display_name": "B", "kind": "nebula_field",
                         "geometry": {"near_gu": 20000.0, "far_gu": 220000.0,
                                      "radius_gu": 160000.0}})
    lobe = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    pocket = [v for v in m.clouds[0].volumes if v.origin_region][0]
    assert lobe.shape == "lobe"
    assert lobe.geometry["far_gu"] == pytest.approx(220000.0)
    centre = pocket.geometry["center_gu"]
    expected_axis = [c / _norm(centre) for c in centre]
    assert lobe.geometry["axis"] == pytest.approx(expected_axis)


def test_a_cloud_without_an_override_keeps_its_pockets():
    """Losing BC's authored data because nobody declared a kind would be the
    worst possible failure mode here."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    m = layout(s)
    assert len(m.clouds) == 1
    assert [v.origin_region for v in m.clouds[0].volumes] == ["Vesuvi4"]
    assert all(v.origin_region for v in m.clouds[0].volumes)


def test_a_set_with_several_nebulae_is_reported_as_ambiguous():
    s = SurveyedSystem(name="Multi5", regions=[_nebula_region()])
    s.regions[0].nebula["extra_nebulae"] = 3
    assert any("nebula" in a.lower() for a in ambiguities(s))


def test_the_shell_radius_reflects_the_pushed_anchor_not_the_pre_push_one():
    """_first_orbit_push() calls _place() twice when a push is needed -- once
    to discover the corrective push amount, once more (with pins applied) at
    the pushed first orbit. The cloud built by the FIRST call must not be the
    one that survives: its region anchors are the pre-push ones, so a shell
    radius derived from them would be too small once the push moves every
    region's anchor outward."""
    s = SurveyedSystem(name="Tight", regions=[
        SurveyedRegion(set_name="Tight1", ordinal=1, bodies=[
            SurveyedBody("Sun", 4000.0, "", (-70000.0, 0.0, 0.0), True),
            SurveyedBody("Tight 1", 150.0, "p.nif", (0.0, 400.0, 0.0), False),
        ], content_extent_gu=30000.0, player_start_gu=(0.0, 0.0, 0.0),
           nebula={"color": (0.61, 0.35, 0.73),
                   "spheres": [(0.0, 1500.0, 0.0, 1500.0)],
                   "visibility_gu": 145.0, "sensor_density": 10.5,
                   "damage_hull_per_s": 150.0, "damage_shield_per_s": 20.0,
                   "extra_nebulae": 0}),
    ])
    t = LayoutTuning()
    push, _probe_m = _first_orbit_push(s, t, {})
    assert push > 0.0, "fixture must genuinely require a push, or this test cannot fail"
    m = layout(s, t, cloud={"name": "T", "display_name": "T", "kind": "debris_shell"})
    region = m.region("Tight1")
    shell = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    expected = _norm(region.anchor_gu) + region.radius_gu
    assert shell.geometry["radius_gu"] == pytest.approx(expected)


def test_each_pocket_volume_gets_its_own_params_dict():
    """Two spheres in one region must not share a single params dict -- an
    in-place mutation to one pocket's params (a later pass over cloud.volumes)
    must not silently leak into its sibling pocket."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region(
        spheres=((0.0, 1500.0, 0.0, 1500.0), (500.0, 2000.0, 0.0, 800.0)))])
    m = layout(s, cloud={"name": "V", "display_name": "V", "kind": "debris_shell"})
    pockets = [v for v in m.clouds[0].volumes if v.origin_region]
    assert len(pockets) == 2
    assert pockets[0].params is not pockets[1].params
    pockets[0].params["visibility_gu"] = -1.0
    assert pockets[1].params["visibility_gu"] != -1.0


def test_a_nebula_with_no_spheres_still_yields_a_debris_shell():
    """A MetaNebula_Create with no AddNebulaSphere call after it (or none
    with exactly 4 arguments) survives survey._nebula as an empty spheres
    list. Building the shell must not crash on an empty pocket list -- the
    shell's radius never reads a pocket centre in the first place."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region(spheres=())])
    m = layout(s, cloud={"name": "V", "display_name": "V", "kind": "debris_shell"})
    assert len(m.clouds) == 1
    assert [v.origin_region for v in m.clouds[0].volumes] == [None]
    assert m.clouds[0].volumes[0].shape == "sphere"


def test_a_nebula_with_no_spheres_yields_no_lobe():
    """A "nebula_field" kind DOES need a pocket to point its axis at -- with
    none available, it must decline to build a large volume rather than
    raise IndexError on an empty pocket list."""
    s = SurveyedSystem(name="Belaruz", regions=[
        _nebula_region(set_name="Belaruz1", hull=0.0, shield=0.0, spheres=())])
    m = layout(s, cloud={"name": "B", "display_name": "B", "kind": "nebula_field",
                         "geometry": {"near_gu": 1.0, "far_gu": 2.0,
                                      "radius_gu": 3.0}})
    assert len(m.clouds) == 1
    assert m.clouds[0].volumes == []


def test_ambiguities_flags_an_unrecognised_cloud_kind():
    """A typo'd kind (e.g. a stray space) must not silently degrade to a
    pockets-only cloud with no error and no ambiguity row -- the same
    silent-degradation failure mode construction rule 5 exists to prevent."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    notes = ambiguities(s, cloud={"name": "V", "display_name": "V",
                                  "kind": "debris shell"})
    assert any("kind" in n.lower() for n in notes)


def test_ambiguities_does_not_flag_a_recognised_cloud_kind():
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    notes = ambiguities(s, cloud={"name": "V", "display_name": "V",
                                  "kind": "debris_shell"})
    assert notes == []
