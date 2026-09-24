"""Validator rules for a system map.

These are the failures that would otherwise surface as a broken mission weeks
later: a BC set with nowhere to live, regions nested inside one another, a
mission's staging waypoints no longer beside the body they were authored
against (see the design doc's "pins"), or a spawn point inside a planet.
"""
import pytest

from engine.systems import clouds as cloud_profiles
from engine.systems.map import Appearance, Body, Cloud, Region, SystemMap, Volume, available, load
from engine.systems.validate import Problem, validate


def _body(name, pos, radius=100.0, owner="Ona1", orbits="Ona"):
    return Body(name=name, display_name=name, radius_gu=radius, position_gu=pos,
                orbits=orbits, appearance=Appearance(), owner_region=owner)


def _valid() -> SystemMap:
    return SystemMap(
        system="Ona",
        bodies=[
            Body(name="Ona", display_name="Ona", radius_gu=5000.0,
                 position_gu=(0.0, 0.0, 0.0), orbits=None,
                 appearance=Appearance(), owner_region=None),
            _body("Ona 1", (0.0, 22000.0, 0.0), radius=1800.0, owner="Ona1"),
            _body("Ona 2", (0.0, 60000.0, 0.0), radius=1800.0, owner="Ona2"),
        ],
        regions=[
            Region("Ona1", (0.0, 18000.0, 0.0), 3000.0, ["Ona 1"]),
            Region("Ona2", (0.0, 56000.0, 0.0), 3000.0, ["Ona 2"]),
        ],
    )


def _slugs(problems):
    return sorted(p.rule for p in problems)


def _rules(problems):
    return [p.rule for p in problems]


def _cloud_map() -> SystemMap:
    """A valid map with ONE cloud: a pocket volume owned by region "Ona1"
    (mirroring BC's own authored nebula sphere, anchor + offset) plus a
    system-scale sphere "large" volume centred on the star, exactly the
    shape tools/systems/layout.py:_build_clouds produces for a
    "debris_shell" override.
    """
    m = _valid()
    m.region("Ona1").nebula = {
        "color": (0.5, 0.5, 0.5),
        "spheres": [(0.0, 1000.0, 0.0, 800.0)],
        "visibility_gu": 145.0,
        "sensor_density": 10.5,
        "damage_hull_per_s": 150.0,
        "damage_shield_per_s": 20.0,
        "extra_nebulae": 0,
    }
    pocket = Volume(
        shape="sphere",
        geometry={"center_gu": (0.0, 19000.0, 0.0), "radius_gu": 800.0},
        profile="debris",
        params=cloud_profiles.params_for("debris"),
        origin_region="Ona1",
    )
    large = Volume(
        shape="sphere",
        geometry={"center_gu": (0.0, 0.0, 0.0), "radius_gu": 25000.0},
        profile="mist",
        params=cloud_profiles.params_for("mist"),
        origin_region=None,
    )
    m.clouds = [Cloud(
        name="Ona Debris", display_name="Ona Debris", kind="debris_shell",
        color=(0.5, 0.5, 0.5), volumes=[pocket, large], regions=["Ona1"])]
    return m


def test_a_cloud_map_is_itself_valid():
    assert validate(_cloud_map()) == []


def test_a_valid_map_has_no_problems():
    assert validate(_valid()) == []


def test_region_coverage_flags_a_set_with_no_region():
    m = _valid()
    assert _slugs(validate(m, sdk_set_names=["Ona1", "Ona2", "Ona3"])) == ["region-coverage"]


def test_region_coverage_is_skipped_without_sdk_names():
    assert validate(_valid(), sdk_set_names=None) == []


def test_region_overlap_flags_a_neighbour_anchor_inside_a_radius():
    m = _valid()
    # Ona2's anchor is 38000 GU away; widen Ona1 past it.
    m.regions[0].radius_gu = 40000.0
    assert "region-overlap" in _slugs(validate(m))


def test_body_owner_flags_a_dangling_name():
    m = _valid()
    m.regions[0].body_names = ["Ona 9"]
    assert "body-owner" in _slugs(validate(m))


def test_body_owner_flags_a_back_reference_mismatch():
    m = _valid()
    m.body("Ona 1").owner_region = "Ona2"
    assert "body-owner" in _slugs(validate(m))


def test_body_engulfs_anchor_flags_a_planet_swallowing_its_own_spawn():
    m = _valid()
    # Ona 1 sits 4000 GU from its anchor; a 5000 GU radius swallows it.
    m.body("Ona 1").radius_gu = 5000.0
    assert "body-engulfs-anchor" in _slugs(validate(m))


def test_a_bad_back_reference_does_not_mask_an_engulfed_anchor():
    """Two independent faults on one body must both be reported. A bookkeeping
    error about which region owns a body must never hide "you would spawn
    inside this planet" -- that is the hazard the validator exists for."""
    m = _valid()
    m.body("Ona 1").owner_region = "Ona2"      # back-reference mismatch
    m.body("Ona 1").radius_gu = 5000.0          # engulfs Ona1's anchor
    assert _slugs(validate(m)) == ["body-engulfs-anchor", "body-owner"]


def test_pin_respected_accepts_the_authored_offset():
    m = _valid()
    pins = {"Ona1/Ona 1": (0.0, 4000.0, 0.0)}   # matches 22000 - 18000
    assert validate(m, pins=pins) == []


def test_pin_respected_flags_a_moved_body():
    m = _valid()
    pins = {"Ona1/Ona 1": (0.0, 500.0, 0.0)}
    assert "pin-respected" in _slugs(validate(m, pins=pins))


def test_pin_respected_flags_a_malformed_key_instead_of_ignoring_it():
    """A pin key with no '/' cannot name a region+body pair. A pin that
    quietly does nothing is worse than no pin -- it looks like protection."""
    m = _valid()
    pins = {"Ona 1": (0.0, 4000.0, 0.0)}   # bare name, no region prefix
    assert "pin-respected" in _slugs(validate(m, pins=pins))


def test_pin_respected_is_judged_against_its_own_regions_body():
    """Two regions may each own a body called 'Moon 1' (Geble3/Geble4 do).
    A pin on one of them must be judged against ITS OWN region's body, even
    when the OTHER region's same-named body would satisfy the pin.

    Ona2's copy is appended FIRST so a naive by-name lookup that ignores
    `owner` (a regression to the old candidates[0] fallback) would resolve
    the pin to Ona2's copy -- which happens to sit exactly on the declared
    offset -- and wrongly report no problem. Ona1's own copy, 4000 GU
    further out, is what the pin must actually be judged against."""
    m = _valid()
    m.bodies.append(Body(name="Moon 1", display_name="Moon 1", radius_gu=100.0,
                         position_gu=(0.0, 56500.0, 0.0), orbits="Ona",
                         appearance=Appearance(), owner_region="Ona2"))
    m.region("Ona2").body_names.append("Moon 1")
    m.bodies.append(Body(name="Moon 1", display_name="Moon 1", radius_gu=100.0,
                         position_gu=(0.0, 22500.0, 0.0), orbits="Ona",
                         appearance=Appearance(), owner_region="Ona1"))
    m.region("Ona1").body_names.append("Moon 1")

    # The pin is declared on Ona1's copy, which sits 4500 GU from Ona1's
    # anchor (18000) -- not the declared 500 GU offset.
    pins = {"Ona1/Moon 1": (0.0, 500.0, 0.0)}
    assert "pin-respected" in _slugs(validate(m, pins=pins))


def test_orbit_target_flags_an_unknown_parent():
    m = _valid()
    m.body("Ona 1").orbits = "Nowhere"
    assert "orbit-target" in _slugs(validate(m))


def test_problems_carry_a_readable_detail():
    m = _valid()
    m.body("Ona 1").orbits = "Nowhere"
    problem = [p for p in validate(m) if p.rule == "orbit-target"][0]
    assert "Ona 1" in problem.detail and "Nowhere" in problem.detail


def test_body_overlap_flags_two_bodies_whose_surfaces_intersect():
    m = _valid()
    m.body("Ona 2").position_gu = (0.0, 24000.0, 0.0)   # 2000 GU from Ona 1
    assert "body-overlap" in _slugs(validate(m))


def test_body_overlap_accepts_bodies_that_merely_come_close():
    m = _valid()
    # Ona 1 r=1800 at y=22000; put Ona 2 r=1800 at y=25601 -> 3601 GU apart.
    m.body("Ona 2").position_gu = (0.0, 25601.0, 0.0)
    assert "body-overlap" not in _slugs(validate(m))


def test_anchor_inside_body_flags_an_anchor_swallowed_by_the_sun():
    """body-engulfs-anchor only checks a region's OWN bodies, so an anchor
    inside the sun would otherwise pass every rule."""
    m = _valid()
    m.regions[0].anchor_gu = (0.0, 100.0, 0.0)          # inside the r=5000 sun
    assert "anchor-inside-body" in _slugs(validate(m))


def test_duplicate_body_names_are_resolved_by_owning_region():
    """Two regions may each own a body called 'Moon 1' (Geble3/Geble4 do). A
    by-name dict silently keeps only the last, so the other region's body
    vanishes from every rule that looks bodies up by name."""
    m = _valid()
    # 4000 GU out from each planet -- clear of its 1800 GU radius (a closer
    # offset collides with the new body-overlap rule, which is not what this
    # test is checking).
    for owner, pos in (("Ona1", (0.0, 26000.0, 0.0)), ("Ona2", (0.0, 64000.0, 0.0))):
        m.bodies.append(Body(name="Moon 1", display_name="Moon 1", radius_gu=100.0,
                             position_gu=pos, orbits="Ona",
                             appearance=Appearance(), owner_region=owner))
        m.region(owner).body_names.append("Moon 1")
    assert validate(m) == []
    # Break only Ona2's copy; Ona1's must stay clean and the report must name
    # the right one.
    for b in m.bodies:
        if b.name == "Moon 1" and b.owner_region == "Ona2":
            b.owner_region = "Ona1"          # now mis-declared
    problems = validate(m)
    assert [p.rule for p in problems] == ["body-owner"]


def test_pin_respected_rejects_a_non_string_key():
    """A pin key that is not a string (e.g. an int) should be reported as a
    problem under the pin-respected rule, not allowed to raise TypeError."""
    m = _valid()
    pins = {123: (0.0, 4000.0, 0.0)}  # int key instead of string
    problems = validate(m, pins=pins)
    assert "pin-respected" in _slugs(problems)


def test_pin_respected_rejects_a_two_element_offset():
    """A pin offset that is only 2 elements (truncated to x and y) should be
    reported as a problem, not silently pass because zip truncates the
    comparison to two axes. Ona 1's true set-local offset is (0.0, 4000.0, 0.0).
    A malformed 2-element pin of (0.0, 4000.0) would pass if truncated."""
    m = _valid()
    pins = {"Ona1/Ona 1": (0.0, 4000.0)}  # 2 elements, not 3
    problems = validate(m, pins=pins)
    assert "pin-respected" in _slugs(problems)


def test_malformed_geometry_flags_a_two_element_position_gu():
    """A body whose position_gu is only 2 elements must be REPORTED, not
    silently accepted because `_dist`'s zip truncates every geometric
    comparison against it to 2D -- which would report a genuinely broken map
    as clean."""
    m = _valid()
    m.body("Ona 1").position_gu = (0.0, 22000.0)  # 2 elements, not 3
    problems = validate(m)
    assert "malformed-geometry" in _slugs(problems)
    assert validate(m) != []  # never silently clean


def test_malformed_geometry_flags_a_two_element_anchor_gu():
    """Same hazard, on a region's anchor_gu instead of a body's position_gu."""
    m = _valid()
    m.regions[0].anchor_gu = (0.0, 18000.0)  # 2 elements, not 3
    problems = validate(m)
    assert "malformed-geometry" in _slugs(problems)


def test_malformed_geometry_flags_non_numeric_coordinates():
    """A body with non-numeric coordinates must be reported, not raise
    TypeError out of a subtraction deep inside a geometric rule."""
    m = _valid()
    m.body("Ona 1").position_gu = ("a", "b", "c")
    problems = validate(m)  # must not raise
    assert "malformed-geometry" in _slugs(problems)


def test_malformed_geometry_does_not_raise_and_skips_the_bad_body():
    """validate()'s contract is absolute: it never raises. A malformed body
    must be excluded from the geometric rules that would otherwise crash on
    it (body-overlap, body-engulfs-anchor, anchor-inside-body, pin-respected)
    rather than merely reported and then still touched."""
    m = _valid()
    m.body("Ona 1").position_gu = ("a", "b", "c")
    pins = {"Ona1/Ona 1": (0.0, 4000.0, 0.0)}
    problems = validate(m, sdk_set_names=["Ona1", "Ona2"], pins=pins)  # must not raise
    assert "malformed-geometry" in _slugs(problems)


def test_pins_as_a_list_is_reported_not_raised():
    """`pins` itself may arrive malformed (a list instead of a dict). That
    must be one reported Problem, not an AttributeError out of `.items()`."""
    m = _valid()
    pins = [("Ona1/Ona 1", (0.0, 4000.0, 0.0))]  # list, not dict
    problems = validate(m, pins=pins)  # must not raise
    assert "pin-respected" in _slugs(problems)


def test_region_reaches_star_flags_a_sphere_overlapping_the_sun():
    """anchor-inside-body misses this: the anchor stays outside the star while
    the region's SPHERE overlaps it. Under streaming, a region boundary would
    pass through a sun."""
    m = _valid()
    # The star is r=5000 at the origin; Ona1's radius is 3000.
    m.region("Ona1").anchor_gu = (0.0, 7000.0, 0.0)   # 7000 < 3000 + 5000
    assert "region-reaches-star" in _slugs(validate(m))


def test_region_reaches_star_accepts_a_region_that_merely_comes_close():
    m = _valid()
    m.region("Ona1").anchor_gu = (0.0, 8100.0, 0.0)   # 8100 > 3000 + 5000
    assert "region-reaches-star" not in _slugs(validate(m))


def test_region_reaches_star_is_skipped_when_a_map_has_no_star():
    m = _valid()
    m.bodies = [b for b in m.bodies if b.orbits is not None]
    assert "region-reaches-star" not in _slugs(validate(m))


def test_a_pocket_that_drifted_from_its_region_is_caught():
    m = _cloud_map()
    m.clouds[0].volumes[0].geometry["center_gu"] = (1.0, 2.0, 3.0)
    assert "cloud-volume-agrees-with-region" in _rules(validate(m))


def test_a_cloud_naming_a_region_that_does_not_exist_is_caught():
    m = _cloud_map()
    m.clouds[0].regions = ["Nowhere1"]
    assert "cloud-region-membership" in _rules(validate(m))


def test_a_region_with_a_nebula_and_no_cloud_is_caught():
    """The failure this rule exists for: a cloud silently dropped during
    regeneration, leaving BC's nebula stranded on the region."""
    m = _cloud_map()
    m.clouds = []
    assert "cloud-region-membership" in _rules(validate(m))


def test_a_pocket_outside_its_own_shell_is_caught():
    m = _cloud_map()
    shell = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    shell.geometry["radius_gu"] = 1.0
    assert "cloud-pocket-inside-cloud" in _rules(validate(m))


def test_tuned_bc_params_are_caught():
    """BC's numbers are not ours to change."""
    m = _cloud_map()
    pocket = [v for v in m.clouds[0].volumes if v.origin_region][0]
    pocket.params["damage_hull_per_s"] = 5.0
    assert "cloud-profile-matches-params" in _rules(validate(m))


def test_an_unknown_profile_is_a_problem_not_a_crash():
    m = _cloud_map()
    m.clouds[0].volumes[0].profile = "fog"
    assert "cloud-profile-matches-params" in _rules(validate(m))


@pytest.mark.parametrize("wreck", [
    lambda c: setattr(c.volumes[0], "geometry", None),
    lambda c: c.volumes[0].geometry.__setitem__("center_gu", (1.0, 2.0)),
    lambda c: c.volumes[0].geometry.__setitem__("radius_gu", "big"),
    lambda c: setattr(c, "volumes", [None]),
    lambda c: setattr(c, "regions", None),
])
def test_a_malformed_cloud_is_reported_never_raised(wreck):
    """validate()'s contract. Callers are a CLI printing every problem and a
    test naming every problem; a traceback serves neither."""
    m = _cloud_map()
    wreck(m.clouds[0])
    problems = validate(m)          # must not raise
    assert any(p.rule.startswith("cloud-") or p.rule == "malformed-geometry"
               for p in problems)


@pytest.mark.parametrize("field", ["bodies", "regions", "clouds"])
@pytest.mark.parametrize("junk", [None, 7, "bodies"])
def test_a_map_whose_list_field_is_not_a_list_is_reported_never_raised(field, junk):
    """The last remaining way to make validate() raise.

    `m.clouds = None` reached `for cl in m.clouds` and raised TypeError; so
    did `m.bodies` and `m.regions`, which have carried the same unguarded
    pattern since the file was written. A string is included because it IS
    iterable -- `for b in m.bodies` over "bodies" yields characters and then
    raises AttributeError on `.name`, which is a different crash from the
    same fault and must also be reported."""
    m = _cloud_map()
    setattr(m, field, junk)
    problems = validate(m)          # must not raise
    assert any(p.rule == "malformed-geometry" and field in p.detail
               for p in problems), _rules(problems)


@pytest.mark.parametrize("field", ["bodies", "regions", "clouds"])
def test_a_list_field_may_be_a_tuple(field):
    """A tuple is a perfectly good sequence of bodies/regions/clouds and is
    not itself a problem worth reporting -- same reasoning as
    _sphere_entries accepting a tuple of spheres."""
    m = _cloud_map()
    setattr(m, field, tuple(getattr(m, field)))
    assert validate(m) == []


# An integer too large for a float. JSON integers are UNBOUNDED, so this is
# reachable from a checked-in map file, not just from a constructed object:
# json.loads gives back a Python int of arbitrary size, and nothing between
# the file and validate() narrows it. 401 digits is comfortably past the
# ~1.8e308 float ceiling.
_TOO_BIG_FOR_FLOAT = int("9" * 401)


@pytest.mark.parametrize("wreck", [
    # Every path a 401-digit integer can reach validate() through from a FILE.
    # (body/region `radius_gu` are absent on purpose: from_json coerces those
    # with float() and so raises at LOAD time, which is a separate concern
    # from validate()'s never-raises contract.)
    lambda raw: raw["bodies"][1]["position_gu"].__setitem__(0, _TOO_BIG_FOR_FLOAT),
    lambda raw: raw["regions"][0]["anchor_gu"].__setitem__(0, _TOO_BIG_FOR_FLOAT),
    lambda raw: raw["regions"][0]["nebula"].__setitem__(
        "damage_hull_per_s", _TOO_BIG_FOR_FLOAT),
    lambda raw: raw["regions"][0]["nebula"]["spheres"][0].__setitem__(
        3, _TOO_BIG_FOR_FLOAT),
    lambda raw: raw["clouds"][0]["volumes"][0]["params"].__setitem__(
        "damage_hull_per_s", _TOO_BIG_FOR_FLOAT),
    lambda raw: raw["clouds"][0]["volumes"][0]["geometry"].__setitem__(
        "radius_gu", _TOO_BIG_FOR_FLOAT),
    lambda raw: raw["clouds"][0]["volumes"][1]["geometry"]["center_gu"].__setitem__(
        0, _TOO_BIG_FOR_FLOAT),
])
def test_an_int_too_large_for_a_float_is_reported_never_raised(tmp_path, wreck):
    """A number `_is_number` accepts but `float()` cannot convert.

    `_is_number` admits ANY int, and float(int) raises OverflowError above
    roughly 1.8e308. Every numeric guard in validate.py is therefore only as
    strong as the arithmetic downstream of it: `_dist` reaches math.sqrt and
    `_pocket_param_details` reaches math.isclose(float(...)), and both raise
    on such a value where the rule is supposed to REPORT.

    Driven from an actual JSON file, because that is the reachable path --
    JSON integers are unbounded, so a map on disk can carry one and nothing
    between `from_json` and `validate` narrows it.
    """
    import json
    from engine.systems.map import from_json, to_json

    raw = json.loads(to_json(_cloud_map()))
    wreck(raw)
    path = tmp_path / "wrecked.json"
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    m = from_json(path.read_text(encoding="utf-8"))
    problems = validate(m)          # must not raise
    assert problems != []
    assert all(isinstance(p, Problem) for p in problems)


def test_the_real_maps_validate_clean():
    for name in available():
        assert validate(load(name)) == [], name


# ---- fix round 1 --------------------------------------------------------

def test_a_lobe_shaped_pocket_is_reported_never_raised():
    """Finding 1 (Critical). A pocket (origin_region set) is always a
    sphere -- BC's authored nebula spheres are the only thing a pocket ever
    represents. A lobe pocket's geometry carries no center_gu, which both
    downstream checks read unconditionally; that must be REPORTED here,
    not left to raise TypeError out of zip(None, ...) deep inside them."""
    m = _cloud_map()
    pocket = m.clouds[0].volumes[0]
    pocket.shape = "lobe"
    pocket.geometry = {"axis": (0.0, 1.0, 0.0), "near_gu": 100.0,
                        "far_gu": 200.0, "radius_gu": 777.0}
    problems = validate(m)          # must not raise
    assert "malformed-geometry" in _rules(problems)


def test_a_non_string_origin_region_is_reported_not_silently_accepted():
    """Finding 2 (Important). origin_region must be null or a region-name
    string; anything else (an int, a list -- a regeneration bug) must be
    reported, not fall through the isinstance/elif chain unreported."""
    m = _cloud_map()
    m.clouds[0].volumes[0].origin_region = 5
    problems = validate(m)
    assert "cloud-region-membership" in _rules(problems)


def _lobe_cloud_map() -> SystemMap:
    """A valid map with a LOBE-shaped large volume, mirroring the shape
    tools/systems/layout.py:_build_clouds produces for a "nebula_field"
    override (axis derived from the pocket's own centre, as Belaruz's real
    map does). Exists because _cloud_map()'s large volume is a sphere, so
    the lobe branch of _pocket_inside_large was never exercised by any
    test before this fix round -- a `return True` stub there passed the
    whole suite.
    """
    m = _valid()
    m.region("Ona1").nebula = {
        "color": (0.5, 0.5, 0.5),
        "spheres": [(0.0, 1000.0, 0.0, 800.0)],
        "visibility_gu": 200.0,
        "sensor_density": 6.5,
        "damage_hull_per_s": 0.0,
        "damage_shield_per_s": 0.0,
        "extra_nebulae": 0,
    }
    pocket = Volume(
        shape="sphere",
        geometry={"center_gu": (0.0, 19000.0, 0.0), "radius_gu": 800.0},
        profile="nebula",
        params=cloud_profiles.params_for("nebula"),
        origin_region="Ona1",
    )
    large = Volume(
        shape="lobe",
        geometry={"axis": (0.0, 1.0, 0.0), "near_gu": 5000.0,
                  "far_gu": 40000.0, "radius_gu": 5000.0},
        profile="mist",
        params=cloud_profiles.params_for("mist"),
        origin_region=None,
    )
    m.clouds = [Cloud(
        name="Ona Nebula", display_name="Ona Nebula", kind="nebula_field",
        color=(0.5, 0.5, 0.5), volumes=[pocket, large], regions=["Ona1"])]
    return m


def test_a_lobe_cloud_map_is_itself_valid():
    assert validate(_lobe_cloud_map()) == []


def test_a_pocket_pushed_past_the_lobes_far_end_is_caught():
    """Finding 3 (Important), axial case. The pocket's position and its
    region's authored sphere are moved TOGETHER so cloud-volume-agrees-
    with-region stays clean -- isolating the axial failure this test is
    actually checking."""
    m = _lobe_cloud_map()
    pocket = m.clouds[0].volumes[0]
    pocket.geometry["center_gu"] = (0.0, 48000.0, 0.0)   # t=48000 > far(40000)+radius(800)
    m.region("Ona1").nebula["spheres"] = [(0.0, 30000.0, 0.0, 800.0)]
    problems = _rules(validate(m))
    assert "cloud-pocket-inside-cloud" in problems
    assert "cloud-volume-agrees-with-region" not in problems


def test_a_pocket_pushed_off_the_lobes_axis_is_caught():
    """Finding 3 (Important), perpendicular case. Same isolation trick as
    the axial test above, but offset sideways instead of further out."""
    m = _lobe_cloud_map()
    pocket = m.clouds[0].volumes[0]
    pocket.geometry["center_gu"] = (6000.0, 19000.0, 0.0)   # perp=6000 > radius(5000)
    m.region("Ona1").nebula["spheres"] = [(6000.0, 1000.0, 0.0, 800.0)]
    problems = _rules(validate(m))
    assert "cloud-pocket-inside-cloud" in problems
    assert "cloud-volume-agrees-with-region" not in problems


def test_a_region_listed_by_two_clouds_is_caught():
    """Finding 4 (Important). The != 1 check also covers 2+, not just 0 --
    a region duplicated into two clouds -- which nothing exercised before
    this fix round."""
    m = _cloud_map()
    duplicate = Cloud(name="Duplicate Cloud", display_name="Duplicate Cloud",
                       kind="debris_shell", color=(0.5, 0.5, 0.5),
                       volumes=[], regions=["Ona1"])
    m.clouds.append(duplicate)
    assert "cloud-region-membership" in _rules(validate(m))


def test_two_equal_radius_pockets_on_one_sphere_leave_the_other_sphere_unmatched():
    """Finding 5 (promoted Minor). Two spheres of EQUAL radius at different
    positions: without consuming a sphere once matched, a duplicate pocket
    parked on sphere A would independently "match" A every time (the old,
    non-bijective algorithm always rescans the full list), and sphere B
    would never be reported missing."""
    m = _cloud_map()
    m.region("Ona1").nebula["spheres"] = [
        (0.0, 1000.0, 0.0, 800.0),   # sphere A -- both pockets target this
        (0.0, 4000.0, 0.0, 800.0),   # sphere B -- same radius, no pocket claims it
    ]
    original = m.clouds[0].volumes[0]
    duplicate = Volume(
        shape="sphere", geometry=dict(original.geometry),
        profile=original.profile, params=dict(original.params),
        origin_region=original.origin_region)
    m.clouds[0].volumes.insert(1, duplicate)
    assert "cloud-volume-agrees-with-region" in _rules(validate(m))


def test_a_region_with_two_spheres_and_only_one_pocket_is_caught():
    """Finding 5 (promoted Minor), the cardinality half: a region with TWO
    authored spheres but only one pocket volume must report the dropped
    sphere, not validate clean because the one pocket present happens to
    match one of the two."""
    m = _cloud_map()
    m.region("Ona1").nebula["spheres"] = [
        (0.0, 1000.0, 0.0, 800.0),
        (0.0, 4000.0, 0.0, 500.0),
    ]
    assert "cloud-volume-agrees-with-region" in _rules(validate(m))


def test_sphere_list_may_be_a_tuple_not_just_a_list():
    """Trivial fold-in: region.nebula["spheres"] being a tuple rather than
    a list is not itself a problem worth reporting."""
    m = _cloud_map()
    m.region("Ona1").nebula["spheres"] = tuple(m.region("Ona1").nebula["spheres"])
    assert validate(m) == []


def test_a_pocket_whose_params_disagree_with_its_regions_survey_is_caught():
    """cloud-profile-matches-params must compare a pocket against its own
    REGION's authored numbers, not against the same profile table that
    stamped them.

    layout.py sets a pocket's params from clouds.params_for(profile); a rule
    that then compares those params against clouds.PROFILES can never fail
    for a generated map. The genuinely independent source is the region's
    own surveyed nebula.

    The numbers below are real BC data: Multi6_S.py authors
    MetaNebula_Create(..., 75.0, 0.5, ...) + SetupDamage(1.0). If such a set
    ever became a region, layout would classify it `debris` (hull > 0) and
    stamp Vesuvi's 145 / 10.5 / 150 / 20 onto it -- a 150x hull-damage error
    that a table-only comparison validates clean.
    """
    m = _cloud_map()
    m.region("Ona1").nebula.update({
        "visibility_gu": 75.0,
        "sensor_density": 0.5,
        "damage_hull_per_s": 1.0,
        "damage_shield_per_s": None,
    })
    problems = validate(m)
    assert "cloud-profile-matches-params" in _rules(problems)
    assert any("damage_hull_per_s" in p.detail for p in problems
               if p.rule == "cloud-profile-matches-params")


def test_an_absent_shield_rate_is_skipped_not_compared_against_zero():
    """`damage_shield_per_s` is None when BC called SetupDamage with a single
    argument: no shield rate was authored, so there is nothing to compare.
    None is not zero -- survey._nebula draws that distinction deliberately --
    so the key is skipped, and the other three are still compared."""
    m = _cloud_map()
    m.region("Ona1").nebula["damage_shield_per_s"] = None
    assert validate(m) == []


def test_the_large_volume_is_still_checked_against_the_profile_table():
    """The large volume has no region, so the table is the only source it
    can be compared against -- that half of the rule is unchanged."""
    m = _cloud_map()
    large = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    large.params["visibility_gu"] = 900.0
    assert "cloud-profile-matches-params" in _rules(validate(m))


def test_a_pocket_whose_region_has_no_nebula_is_reported_not_raised():
    m = _cloud_map()
    m.region("Ona1").nebula = None
    problems = validate(m)      # must not raise
    assert "cloud-profile-matches-params" in _rules(problems)


def test_a_pocket_whose_region_is_missing_is_reported_not_raised():
    m = _cloud_map()
    m.clouds[0].volumes[0].origin_region = "Nowhere1"
    problems = validate(m)      # must not raise
    assert "cloud-profile-matches-params" in _rules(problems)


def test_a_pocket_whose_regions_numbers_are_non_numeric_is_reported_not_raised():
    m = _cloud_map()
    m.region("Ona1").nebula["sensor_density"] = "thick"
    problems = validate(m)      # must not raise
    assert "cloud-profile-matches-params" in _rules(problems)


def test_a_pockets_profile_name_must_match_its_regions_damage():
    """The half the region comparison alone does not cover.

    Comparing params against the region checks the NUMBERS. It does not tie
    the pocket's `profile` STRING to anything, so relabelling a pocket
    "mist" while leaving BC's 145/10.5/150/20 in place validated clean --
    a check the old table comparison did have, because a "mist" label
    demanded mist's four zeros.

    The rule mirrors tools/systems/layout.py:_build_clouds, which derives
    the profile from BC's own damage choice: `debris` when the region's
    damage_hull_per_s > 0, `nebula` otherwise.
    """
    m = _cloud_map()                       # region authors hull 150 -> debris
    m.clouds[0].volumes[0].profile = "mist"
    problems = validate(m)
    assert "cloud-profile-matches-params" in _rules(problems)
    assert any("profile" in p.detail for p in problems
               if p.rule == "cloud-profile-matches-params")


def test_a_harmless_pocket_may_not_be_labelled_debris():
    """The other direction: a region BC authored no damage for is `nebula`,
    and labelling its pocket `debris` must be caught even though the two
    profiles differ on every number (so the params check would catch it too
    -- here the params are moved with the label to isolate the NAME)."""
    m = _cloud_map()
    m.region("Ona1").nebula["damage_hull_per_s"] = 0.0
    m.region("Ona1").nebula["damage_shield_per_s"] = 0.0
    m.region("Ona1").nebula["visibility_gu"] = 200.0
    m.region("Ona1").nebula["sensor_density"] = 6.5
    m.clouds[0].volumes[0].params = cloud_profiles.params_for("nebula")
    # Numbers now agree with the region; only the LABEL is wrong.
    assert m.clouds[0].volumes[0].profile == "debris"
    problems = validate(m)
    assert "cloud-profile-matches-params" in _rules(problems)
    assert any("profile" in p.detail for p in problems
               if p.rule == "cloud-profile-matches-params")


def test_a_correctly_labelled_harmless_pocket_is_clean():
    """The positive case of the rule above -- relabelling in step with the
    region's authored damage is exactly what layout.py does, and must not
    be reported."""
    m = _cloud_map()
    m.region("Ona1").nebula.update({
        "visibility_gu": 200.0, "sensor_density": 6.5,
        "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0,
    })
    m.clouds[0].volumes[0].profile = "nebula"
    m.clouds[0].volumes[0].params = cloud_profiles.params_for("nebula")
    assert validate(m) == []


# ---- radius-ratio ---------------------------------------------------------

def _radius_map(radius_p=1900.0) -> SystemMap:
    """A minimal, otherwise-clean map: one star, one region "R1" owning one
    body "P" -- the same shape as _valid(), trimmed to a single region so
    the radius-ratio tests can assert an EXACT problem list."""
    return SystemMap(
        system="R",
        bodies=[
            Body(name="Sun", display_name="Sun", radius_gu=5000.0,
                 position_gu=(0.0, 0.0, 0.0), orbits=None,
                 appearance=Appearance(), owner_region=None),
            _body("P", (0.0, 22000.0, 0.0), radius=radius_p, owner="R1", orbits="Sun"),
        ],
        regions=[
            Region("R1", (0.0, 18000.0, 0.0), 3000.0, ["P"]),
        ],
    )


def test_radius_ratio_rule_flags_a_body_off_the_scale():
    # A body whose map radius is 19x its BC radius, not 20x.
    m = _radius_map(radius_p=1900.0)
    probs = validate(m, bc_radii={("R1", "P"): 100.0}, radius_scale=20.0)
    assert [p.rule for p in probs] == ["radius-ratio"]
    assert "R1/P" in probs[0].detail


def test_radius_ratio_rule_accepts_the_exact_scale():
    m = _radius_map(radius_p=2000.0)
    assert [p for p in validate(m, bc_radii={("R1", "P"): 100.0}, radius_scale=20.0)
            if p.rule == "radius-ratio"] == []


def test_radius_ratio_rule_is_off_without_inputs():
    m = _radius_map(radius_p=1900.0)
    assert [p for p in validate(m) if p.rule == "radius-ratio"] == []


def test_radius_ratio_rule_is_region_scoped():
    """Body names collide across regions (Geble3 and Geble4 both have a
    "Moon 1"). The lookup must match name AND owner_region."""
    m = SystemMap(
        system="R",
        bodies=[
            Body(name="Sun", display_name="Sun", radius_gu=5000.0,
                 position_gu=(0.0, 0.0, 0.0), orbits=None,
                 appearance=Appearance(), owner_region=None),
            _body("Moon 1", (0.0, 22000.0, 0.0), radius=2000.0, owner="R1", orbits="Sun"),
            _body("Moon 1", (0.0, 60000.0, 0.0), radius=600.0, owner="R2", orbits="Sun"),
        ],
        regions=[
            Region("R1", (0.0, 18000.0, 0.0), 3000.0, ["Moon 1"]),
            Region("R2", (0.0, 56000.0, 0.0), 3000.0, ["Moon 1"]),
        ],
    )
    probs = validate(m, bc_radii={("R1", "Moon 1"): 100.0, ("R2", "Moon 1"): 30.0},
                     radius_scale=20.0)
    assert [p for p in probs if p.rule == "radius-ratio"] == []
