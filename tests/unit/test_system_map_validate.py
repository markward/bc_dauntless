"""Validator rules for a system map.

These are the failures that would otherwise surface as a broken mission weeks
later: a BC set with nowhere to live, regions nested inside one another, a
mission's staging waypoints no longer beside the body they were authored
against (see the design doc's "pins"), or a spawn point inside a planet.
"""
import pytest

from engine.systems.map import Appearance, Body, Region, SystemMap, available, load
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


@pytest.mark.parametrize("field", ["bodies", "regions"])
@pytest.mark.parametrize("junk", [None, 7, "bodies"])
def test_a_map_whose_list_field_is_not_a_list_is_reported_never_raised(field, junk):
    """The last remaining way to make validate() raise.

    `m.bodies` and `m.regions` both raised TypeError when replaced with a
    non-list, from the same unguarded `for x in m.<field>` pattern. A string
    is included because it IS iterable -- `for b in m.bodies` over "bodies"
    yields characters and then raises AttributeError on `.name`, which is a
    different crash from the same fault and must also be reported."""
    m = _valid()
    setattr(m, field, junk)
    problems = validate(m)          # must not raise
    assert any(p.rule == "malformed-geometry" and field in p.detail
               for p in problems), _rules(problems)


@pytest.mark.parametrize("field", ["bodies", "regions"])
def test_a_list_field_may_be_a_tuple(field):
    """A tuple is a perfectly good sequence of bodies/regions and is
    not itself a problem worth reporting -- same reasoning as
    _sphere_entries accepting a tuple of spheres."""
    m = _valid()
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
])
def test_an_int_too_large_for_a_float_is_reported_never_raised(tmp_path, wreck):
    """A number `_is_number` accepts but `float()` cannot convert.

    `_is_number` admits ANY int, and float(int) raises OverflowError above
    roughly 1.8e308. Every numeric guard in validate.py is therefore only as
    strong as the arithmetic downstream of it: `_dist` reaches math.sqrt,
    which raises on such a value where the rule is supposed to REPORT.

    Driven from an actual JSON file, because that is the reachable path --
    JSON integers are unbounded, so a map on disk can carry one and nothing
    between `from_json` and `validate` narrows it.
    """
    import json
    from engine.systems.map import from_json, to_json

    raw = json.loads(to_json(_valid()))
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


# ---- staged-clearance -----------------------------------------------------
# _radius_map's body "P" (radius 1900) sits at set-local (0, 4000, 0) in R1.

def test_staged_clearance_rule_flags_content_near_a_body():
    m = _radius_map()
    probs = validate(m, staged_points={"R1": [("Maelstrom/T/R1_P", (0.0, 1500.0, 0.0))]},
                     staged_clearance_gu=1000.0)
    assert [p.rule for p in probs] == ["staged-clearance"]
    assert "R1/P" in probs[0].detail and "Maelstrom/T/R1_P" in probs[0].detail


def test_staged_clearance_rule_accepts_content_that_clears():
    m = _radius_map()
    assert validate(m, staged_points={"R1": [("Maelstrom/T/R1_P", (0.0, 0.0, 0.0))]},
                    staged_clearance_gu=1000.0) == []


def test_staged_clearance_rule_is_off_without_inputs():
    m = _radius_map()
    inside = {"R1": [("Maelstrom/T/R1_P", (0.0, 4000.0, 0.0))]}
    assert validate(m) == []
    assert validate(m, staged_points=inside) == []
    assert validate(m, staged_clearance_gu=1000.0) == []


def test_staged_clearance_rule_is_region_scoped():
    """Content staged in R2 is judged against R2's "Moon 1" only, never R1's
    same-named body -- even at R1's Moon 1's set-local spot."""
    m = SystemMap(
        system="R",
        bodies=[
            Body(name="Sun", display_name="Sun", radius_gu=5000.0,
                 position_gu=(0.0, 0.0, 0.0), orbits=None,
                 appearance=Appearance(), owner_region=None),
            _body("Moon 1", (0.0, 22000.0, 0.0), radius=2000.0, owner="R1", orbits="Sun"),
            _body("Moon 1", (0.0, 60000.0, 600.0), radius=600.0, owner="R2", orbits="Sun"),
        ],
        regions=[
            Region("R1", (0.0, 18000.0, 0.0), 3000.0, ["Moon 1"]),
            Region("R2", (0.0, 56000.0, 0.0), 3000.0, ["Moon 1"]),
        ],
    )
    # R1's Moon 1 is at set-local (0, 4000, 0); R2's at (0, 4000, 600).
    near_r1_only = [("Maelstrom/T/X_P", (0.0, 4000.0, -2500.0))]
    assert validate(m, staged_points={"R2": near_r1_only}, staged_clearance_gu=1000.0) == []
    probs = validate(m, staged_points={"R1": near_r1_only}, staged_clearance_gu=1000.0)
    assert [p.rule for p in probs] == ["staged-clearance"]
    assert "R1/Moon 1" in probs[0].detail


# ---- bc_scale regions: an encircled planet keeps BC's size and place --------
# _radius_map's body "P" sits at set-local (0, 4000, 0) in R1.

def _bc_scale_map(radius_p=100.0) -> SystemMap:
    m = _radius_map(radius_p=radius_p)
    m.region("R1").bc_scale = True
    return m


def test_radius_ratio_expects_scale_one_in_a_bc_scale_region():
    assert [p for p in validate(_bc_scale_map(100.0), bc_radii={("R1", "P"): 100.0},
                                radius_scale=20.0) if p.rule == "radius-ratio"] == []
    probs = validate(_bc_scale_map(2000.0), bc_radii={("R1", "P"): 100.0}, radius_scale=20.0)
    assert [p.rule for p in probs] == ["radius-ratio"]
    assert "R1/P" in probs[0].detail


def test_staged_clearance_skips_a_bc_scale_region():
    inside = {"R1": [("Maelstrom/T/R1_P", (0.0, 3950.0, 0.0))]}
    assert validate(_radius_map(), staged_points=inside, staged_clearance_gu=1000.0) != []
    assert validate(_bc_scale_map(), staged_points=inside, staged_clearance_gu=1000.0) == []


def test_bc_scale_position_rule_accepts_a_body_at_anchor_plus_bc_offset():
    assert validate(_bc_scale_map(), bc_offsets={("R1", "P"): (0.0, 4000.0, 0.0)}) == []


def test_bc_scale_position_rule_flags_a_body_off_its_bc_offset():
    probs = validate(_bc_scale_map(), bc_offsets={("R1", "P"): (0.0, 4000.001, 0.0)})
    assert [p.rule for p in probs] == ["bc-scale-position"]
    assert "R1/P" in probs[0].detail


def test_bc_scale_position_rule_ignores_a_region_that_is_not_bc_scale():
    assert validate(_radius_map(), bc_offsets={("R1", "P"): (0.0, 1000.0, 0.0)}) == []


def test_bc_scale_position_rule_is_region_scoped():
    """Body names collide across regions; match name AND owner_region."""
    m = SystemMap(
        system="R",
        bodies=[
            Body(name="Sun", display_name="Sun", radius_gu=5000.0,
                 position_gu=(0.0, 0.0, 0.0), orbits=None,
                 appearance=Appearance(), owner_region=None),
            _body("Moon 1", (0.0, 22000.0, 0.0), radius=2000.0, owner="R1", orbits="Sun"),
            _body("Moon 1", (0.0, 57000.0, 0.0), radius=30.0, owner="R2", orbits="Sun"),
        ],
        regions=[
            Region("R1", (0.0, 18000.0, 0.0), 3000.0, ["Moon 1"]),
            Region("R2", (0.0, 56000.0, 0.0), 3000.0, ["Moon 1"], bc_scale=True),
        ],
    )
    assert validate(m, bc_offsets={("R1", "Moon 1"): (0.0, 4000.0, 0.0),
                                   ("R2", "Moon 1"): (0.0, 1000.0, 0.0)}) == []


# ---- profile rules --------------------------------------------------------

from engine.systems.profile import Profile, ProfileRow
from engine.systems.validate import _profile_problems


def _pm(rows, overrides=None, regions=None):
    return SystemMap(system="T", bodies=[Body("Sun", "Sun", 100.0, (0.0, 0.0, 0.0))],
               regions=regions or [], overrides=overrides or {},
               profile=Profile(rows=rows))


def _profile_rules(m):
    return sorted({p.rule for p in _profile_problems(m)})


def test_ordered_profile_is_clean():
    assert _profile_rules(_pm([ProfileRow(0.0, radiation=1.0), ProfileRow(300.0)])) == []


def test_none_profile_is_clean():
    m = _pm([])
    m.profile = None
    assert _profile_rules(m) == []


def test_unsorted_first_nonzero_or_out_of_range_rows_are_problems():
    assert _profile_rules(_pm([ProfileRow(10.0)])) == ["profile-rows-ordered"]
    assert _profile_rules(_pm([ProfileRow(0.0), ProfileRow(50.0), ProfileRow(20.0)])) == ["profile-rows-ordered"]
    assert _profile_rules(_pm([ProfileRow(0.0, dust=1.5)])) == ["profile-rows-ordered"]
    assert _profile_rules(_pm([ProfileRow(0.0, nebula=float("nan"))])) == ["profile-rows-ordered"]


def test_radiation_in_the_last_row_is_a_problem():
    assert _profile_rules(_pm([ProfileRow(0.0), ProfileRow(10.0, radiation=0.1)])) == [
        "profile-radiation-clears"]


def test_radiation_near_the_star_is_fine():
    assert _profile_rules(_pm([ProfileRow(0.0, radiation=1.0), ProfileRow(300.0)])) == []


def _cloud_region(anchor_y):
    return Region("C1", (0.0, anchor_y, 0.0), 2000.0,
                  nebula={"spheres": [(0.0, 0.0, 0.0, 500.0)]})


def test_override_near_clump_is_clean():
    rows = [ProfileRow(0.0), ProfileRow(100000.0, nebula=1.0), ProfileRow(200000.0)]
    m = _pm(rows, overrides={"profile": {"rows": []}}, regions=[_cloud_region(101000.0)])
    assert _profile_rules(m) == []


def test_override_far_from_clump_is_a_problem():
    rows = [ProfileRow(0.0), ProfileRow(100000.0, nebula=1.0), ProfileRow(200000.0)]
    m = _pm(rows, overrides={"profile": {"rows": []}}, regions=[_cloud_region(150000.0)])
    assert _profile_rules(m) == ["profile-override-tracks-clump"]
