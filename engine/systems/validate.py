"""System-map validation.

Every rule here exists because breaking it would surface as a broken MISSION
rather than as a broken map: a BC set with nowhere to live, regions nested
inside one another, a mission's staging waypoints no longer beside the body
they were authored against (see the design doc's "pins"), or a spawn point
inside a planet.

validate() returns a list of Problems -- empty means valid. It never raises:
callers are a CLI that wants to print them all and a test that wants to name
them all.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .clouds import PROFILES, params_for


@dataclass
class Problem:
    rule: str
    detail: str


def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _is_number(x) -> bool:
    """True if x is a number this file's arithmetic can actually survive.

    Being an int or a float is not enough. Python ints are UNBOUNDED, and
    `float()` on one above roughly 1.8e308 raises OverflowError -- so a value
    that passes a bare isinstance check can still blow up the moment a rule
    touches it. Both of this file's numeric consumers do exactly that:
    `_dist` reaches `math.sqrt`, and `_pocket_param_details` reaches
    `math.isclose(float(...))`. Either raises where the rule is supposed to
    REPORT, which breaks validate()'s one hard contract.

    That is reachable from a FILE, not just from a constructed object: JSON
    integers are unbounded, so a checked-in map can carry a 401-digit
    `damage_hull_per_s` or coordinate and nothing between `from_json` and
    `validate` narrows it.

    Non-finite floats (inf, nan) are rejected for the same reason in
    reverse: they convert fine and then poison every comparison downstream
    silently instead of loudly. A number has to be finite AND convertible.
    """
    if not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except (OverflowError, ValueError):
        return False


def _is_point3(v) -> bool:
    """True if v is a sequence of exactly 3 numbers -- a well-formed GU point.

    `_dist` above uses `zip`, which silently truncates to the shorter side: a
    2-element vector paired against a 3-element one compares only x and y and
    reports the map clean. Catching that here, before any geometric rule runs,
    is the difference between a malformed map raising deep inside a distance
    calculation and it being reported by name.

    Delegates the per-coordinate test to `_is_number` rather than repeating
    an inline isinstance check, so the unconvertible-int and non-finite
    guards above cover coordinates too -- `position_gu` and `anchor_gu` are
    the shortest route from a map file into `math.sqrt`.
    """
    try:
        return len(v) == 3 and all(_is_number(c) for c in v)
    except TypeError:
        return False


def _resolve(by_name: dict, name: str, owner: str | None = None):
    """Look up a body by name, preferring the candidate owned by `owner`.

    BC's own display names are not unique across a system -- e.g. Geble3 and
    Geble4 both name a companion "Moon 1". A plain name->body dict silently
    keeps whichever body happened to be added last, which then reports a
    spurious body-owner mismatch for every OTHER region that also has a body
    of that name. Group by name and disambiguate by owner_region instead.
    """
    candidates = by_name.get(name, [])
    if not candidates:
        return None
    if owner is not None:
        for b in candidates:
            if b.owner_region == owner:
                return b
    return candidates[0]


def _looks_like_volume(v) -> bool:
    """True if v carries every attribute a Volume must have.

    A cloud's `volumes` list is exactly as exposed to malformed input as the
    map's own bodies/regions -- a stray `None` in the list (a dropped item
    during regeneration) must be reported, not raise AttributeError the
    first time `.geometry` is touched.
    """
    return v is not None and all(
        hasattr(v, attr)
        for attr in ("shape", "geometry", "profile", "params", "origin_region"))


def _volume_geometry_ok(v) -> bool:
    """True if v.geometry is well-formed for its own shape.

    Mirrors `_is_point3`'s job for bodies/regions: every rule below that
    does arithmetic on a volume's geometry (matching a pocket against its
    region, testing a pocket against the cloud's large volume) is unguarded,
    so a non-dict geometry, a 2-element center_gu, or a non-numeric radius
    must be caught HERE, before any of that arithmetic runs.
    """
    g = getattr(v, "geometry", None)
    if not isinstance(g, dict):
        return False
    if v.shape == "sphere":
        return _is_point3(g.get("center_gu")) and _is_number(g.get("radius_gu"))
    if v.shape == "lobe":
        return (_is_point3(g.get("axis"))
                and _is_number(g.get("near_gu"))
                and _is_number(g.get("far_gu"))
                and _is_number(g.get("radius_gu")))
    return False


def _volume_extent(v) -> float:
    """A single number to compare candidate "large" volumes by size.

    Only ever called on a geometry-OK volume with origin_region is None.
    A sphere's extent is its radius; a lobe carries no radius that alone
    bounds it (see _pocket_inside_large), so its reach from the star is
    `far_gu` -- the furthest distance along its axis the volume extends.
    """
    g = v.geometry
    if v.shape == "sphere":
        return float(g.get("radius_gu", 0.0))
    if v.shape == "lobe":
        return float(g.get("far_gu", 0.0))
    return 0.0


_PARAM_KEYS = ("visibility_gu", "sensor_density",
               "damage_hull_per_s", "damage_shield_per_s")


def _pocket_param_details(v, region) -> list:
    """Why pocket volume `v`'s params disagree with its region's own survey.

    This is the INDEPENDENT half of cloud-profile-matches-params. A pocket's
    params are written by tools/systems/layout.py from
    clouds.params_for(profile), so comparing them back against that same
    table is a tautology: it cannot fail for a generated map. The region's
    `nebula` dict is the other end of the survey -- BC's own four numbers,
    read out of the set's static-placement script -- and that is what a
    pocket must agree with.

    The concrete failure this catches, with real BC data: Multi6_S.py
    authors MetaNebula_Create(..., 75.0, 0.5, ...) + SetupDamage(1.0). If
    such a set became a region, layout would classify it `debris` (hull > 0)
    and stamp Vesuvi's 145 / 10.5 / 150 / 20 onto its pocket -- a 150x
    hull-damage error the table comparison calls clean.

    Returns a list of human-readable reasons; empty means agreement. Never
    raises: a missing region, a region with no nebula, and a non-numeric
    number on either side are all REPORTED, per validate()'s contract.
    """
    if region is None:
        return [f"origin_region {v.origin_region!r} names no region in this map, "
                f"so its params cannot be checked against BC's authored numbers"]
    nebula = region.nebula
    if not isinstance(nebula, dict):
        return [f"region {region.set_name!r} carries no nebula ({nebula!r}), so "
                f"this pocket has no authored numbers to agree with"]
    params = v.params
    if not isinstance(params, dict):
        return [f"params {params!r} is not a dict"]
    if set(params) != set(_PARAM_KEYS):
        return [f"params keys {sorted(params)} -- expected exactly "
                f"{sorted(_PARAM_KEYS)}"]

    details = []

    # The pocket's profile NAME, tied to the same authored number layout
    # derives it from (tools/systems/layout.py:_build_clouds: `debris` when
    # damage_hull_per_s > 0, `nebula` otherwise). Comparing params against
    # the region checks the numbers but leaves the label free, so without
    # this a pocket relabelled "mist" while keeping BC's 145/10.5/150/20
    # validates clean -- a check the old table comparison did have, because
    # a "mist" label demanded mist's four zeros.
    hull = nebula.get("damage_hull_per_s")
    if _is_number(hull):
        want_profile = "debris" if hull > 0 else "nebula"
        if v.profile != want_profile:
            details.append(
                f"profile is {v.profile!r}, but region {region.set_name!r} "
                f"authored damage_hull_per_s {hull!r}, which makes it "
                f"{want_profile!r}")

    for key in _PARAM_KEYS:
        authored = nebula.get(key)
        if key == "damage_shield_per_s" and authored is None:
            # BC called SetupDamage with a SINGLE argument: it authored no
            # shield rate at all. None is not zero (see survey._nebula) --
            # there is nothing to compare here, so skip the key rather than
            # inventing a 0.0 to compare against.
            continue
        have = params.get(key)
        if not _is_number(authored) or not _is_number(have):
            details.append(
                f"{key}: pocket has {have!r}, region {region.set_name!r} "
                f"authored {authored!r} -- both must be numbers")
        elif not math.isclose(float(have), float(authored),
                              rel_tol=1e-9, abs_tol=0.0):
            details.append(
                f"{key}: pocket has {have!r} but region {region.set_name!r} "
                f"authored {authored!r}")
    return details


def _sphere_entries(region) -> list:
    """The region's own authored nebula spheres as (sx, sy, sz, sr) tuples,
    filtering out anything malformed. `spheres` may arrive as a tuple as
    readily as a list -- there is nothing in the data model that requires
    a list specifically, so accepting either costs nothing and a bare
    tuple is not itself a problem worth reporting.
    """
    spheres = region.nebula.get("spheres") if isinstance(region.nebula, dict) else None
    if not isinstance(spheres, (list, tuple)):
        return []
    return [tuple(s) for s in spheres
            if isinstance(s, (list, tuple)) and len(s) == 4
            and all(_is_number(x) for x in s)]


def _match_pockets_to_region(pockets, region) -> tuple:
    """Bijection between pocket volumes and the region's authored spheres.

    Each sphere is consumed by AT MOST ONE pocket -- matched by radius
    (within 1e-6 relative) and then checked at region.anchor_gu + that
    sphere's offset, same as before. Without consumption, two spheres of
    equal radius at different positions let a pocket sitting on EITHER one
    "match" every time the loop re-scans the full sphere list, so a second
    pocket duplicated onto the first sphere would silently pass and the
    second sphere would never be reported missing -- the exact drift this
    rule exists to catch, on both ends: a duplicated pocket AND a dropped
    sphere.

    Returns (unmatched_pockets, unmatched_spheres).
    """
    if not _is_point3(region.anchor_gu):
        return list(pockets), []
    remaining = _sphere_entries(region)
    unmatched_pockets = []
    for v in pockets:
        center = v.geometry.get("center_gu")
        radius = v.geometry.get("radius_gu")
        match_index = None
        for i, (sx, sy, sz, sr) in enumerate(remaining):
            if not math.isclose(radius, sr, rel_tol=1e-6):
                continue
            expected = tuple(a + o for a, o in zip(region.anchor_gu, (sx, sy, sz)))
            tolerance = 1e-6 * max(1.0, _dist(expected, (0.0, 0.0, 0.0)))
            if _dist(center, expected) <= tolerance:
                match_index = i
                break
        if match_index is None:
            unmatched_pockets.append(v)
        else:
            remaining.pop(match_index)
    return unmatched_pockets, remaining


def _pocket_inside_large(v, large, origin) -> bool:
    """True if pocket volume v lies inside the cloud's large volume.

    Only ever called with both v and large already geometry-OK, so no
    further type guards are needed here.

    A sphere large volume: the ordinary contains-a-sphere test -- centre
    distance plus the pocket's own radius against the large radius.

    A lobe carries no explicit centre. By construction (see
    tools/systems/layout.py:_build_cloud_large_volume) its spine is the ray
    from the system's star (`origin`, the map's own star body -- (0, 0, 0)
    when the map has none) outward along `axis`, spanning [near_gu, far_gu],
    with `radius_gu` as a CONSTANT lateral radius the whole way: a
    capsule/cylinder around that ray, not a taper. That is the simplest
    shape consistent with the three authored numbers -- no taper rate is
    stored anywhere -- and it is the choice documented in the design brief
    as a decision, not a recovered fact: both real lobes in the checked-in
    maps clear it by a wide margin (the axial band and the lateral radius
    are each an order of magnitude bigger than the pocket they contain), so
    a tighter model would still pass them; a materially looser one would
    risk missing a real drift.
    """
    pocket_center = v.geometry.get("center_gu")
    pocket_radius = v.geometry.get("radius_gu")
    if large.shape == "sphere":
        center = large.geometry.get("center_gu")
        radius = large.geometry.get("radius_gu")
        return _dist(pocket_center, center) + pocket_radius <= radius + 1e-6
    if large.shape == "lobe":
        axis = large.geometry.get("axis")
        near = large.geometry.get("near_gu")
        far = large.geometry.get("far_gu")
        radius = large.geometry.get("radius_gu")
        axis_len = math.sqrt(sum(a * a for a in axis))
        if axis_len == 0.0:
            return True   # degenerate axis -- can't judge, don't false-flag
        unit_axis = tuple(a / axis_len for a in axis)
        rel = tuple(p - o for p, o in zip(pocket_center, origin))
        t = sum(r * u for r, u in zip(rel, unit_axis))
        proj = tuple(t * u for u in unit_axis)
        perp = math.sqrt(sum((r - p) ** 2 for r, p in zip(rel, proj)))
        return (near - pocket_radius <= t <= far + pocket_radius
                and perp + pocket_radius <= radius + 1e-6)
    return True   # unknown shape -- geometry_ok already excludes this


def _sequence_field(m, name: str, problems: list) -> list:
    """`m.<name>` as a list, reporting rather than raising on anything else.

    The three list fields are the outermost thing validate() touches, and
    every loop over them was unguarded: `m.clouds = None` raised TypeError
    out of `for cl in m.clouds` before a single rule ran, and `m.bodies` /
    `m.regions` carried the identical pattern. "validate() never raises" is
    a named hard constraint of this file, so the entry points to it need the
    same guard-before-use treatment `_is_point3` gives a coordinate.

    A str is rejected even though it is iterable: iterating it yields
    characters, which then raise AttributeError on `.name` -- a different
    crash from the same fault. A tuple is accepted; it is a perfectly good
    sequence and not a fault worth reporting (same reasoning as
    `_sphere_entries` accepting a tuple of spheres).
    """
    value = getattr(m, name, None)
    if isinstance(value, (list, tuple)):
        return list(value)
    problems.append(Problem(
        "malformed-geometry",
        f"map field {name!r} is {value!r} -- must be a list"))
    return []


def _bc_scale_regions(regions, bad_regions) -> set:
    """Names of the regions whose bodies keep BC's size and place (see
    tools/systems/layout._encircled)."""
    return {r.set_name for r in regions
            if r.set_name not in bad_regions and getattr(r, "bc_scale", False) is True}


def _radius_ratio_problems(m, bc_radii: dict, radius_scale: float,
                           bc_scale_regions: set) -> list:
    """Every mapped body is exactly radius_scale x the radius BC authored --
    or exactly BC's radius (scale 1) in a bc_scale region.

    Only orbit DISTANCE is a layout knob that moves between regenerations;
    body size is BC's radius times one scale. A regeneration that breaks this
    for one body has changed what the player sees without anyone asking.
    Region-scoped: BC display names collide within a system (Geble3 and Geble4
    both name a "Moon 1"), so match name AND owner_region, never name alone.
    """
    problems = []
    for (region_name, body_name), bc_radius in sorted(bc_radii.items()):
        body = next((b for b in m.bodies
                     if b.name == body_name and b.owner_region == region_name), None)
        if body is None:
            continue
        scale = 1.0 if region_name in bc_scale_regions else radius_scale
        want = scale * bc_radius
        if not math.isclose(body.radius_gu, want, rel_tol=1e-9, abs_tol=1e-9):
            problems.append(Problem(
                rule="radius-ratio",
                detail=f"{region_name}/{body_name}: map radius {body.radius_gu} GU "
                       f"is not {scale} x BC's {bc_radius} = {want} GU"))
    return problems


def _bc_scale_position_problems(bodies, regions, bad_bodies, bad_regions,
                                bc_offsets: dict) -> list:
    """A bc_scale region's bodies sit at exactly anchor + BC's set-local
    offset -- the planet a mission's content surrounds has not moved.

    Region-scoped like radius-ratio: match name AND owner_region.
    """
    problems = []
    anchors = {r.set_name: r.anchor_gu for r in regions
               if r.set_name in _bc_scale_regions(regions, bad_regions)}
    for (region_name, body_name), offset in sorted(bc_offsets.items()):
        anchor = anchors.get(region_name)
        if anchor is None:
            continue
        body = next((b for b in bodies if id(b) not in bad_bodies
                     and b.name == body_name and b.owner_region == region_name), None)
        if body is None:
            continue
        local = tuple(p - a for p, a in zip(body.position_gu, anchor))
        if _dist(local, offset) > 1e-6:
            problems.append(Problem(
                "bc-scale-position",
                f"{region_name}/{body_name}: set-local position {local} is not "
                f"BC's offset {tuple(offset)} -- a bc_scale region keeps BC's place"))
    return problems


def _staged_clearance_problems(bodies, regions, bad_bodies, bad_regions,
                               staged_points, clearance_gu: float) -> list:
    """No body a region owns has its surface within `clearance_gu` of a point
    content is staged at in that region -- a ship staged there would spawn in,
    or skimming, a planet. Points are set-local (region anchor + xyz).

    Region-scoped: BC display names collide across regions (Geble3 and Geble4
    both have a "Moon 1"), so a region's bodies are those whose owner_region
    is that region, never a by-name lookup.
    """
    problems = []
    # A bc_scale region's clearances are BC's own (content as close as 176 GU
    # off Alioth 6's surface), so the rule does not apply there.
    skip = bad_regions | _bc_scale_regions(regions, bad_regions)
    anchors = {r.set_name: r.anchor_gu for r in regions if r.set_name not in skip}
    for region_name in sorted(staged_points):
        anchor = anchors.get(region_name)
        if anchor is None:
            continue
        owned = [b for b in bodies
                 if b.owner_region == region_name and id(b) not in bad_bodies]
        for label, xyz in staged_points[region_name]:
            if not _is_point3(xyz):
                problems.append(Problem(
                    "staged-clearance",
                    f"{region_name}: staged point from {label!r} is malformed: {xyz!r}"))
                continue
            for b in owned:
                local = tuple(p - a for p, a in zip(b.position_gu, anchor))
                clearance = _dist(local, xyz) - b.radius_gu
                if clearance < clearance_gu - 1e-6:
                    problems.append(Problem(
                        "staged-clearance",
                        f"{region_name}/{b.name}: surface is {clearance:.0f} GU from "
                        f"content staged at set-local {tuple(xyz)} by {label!r} "
                        f"-- must clear it by {clearance_gu:.0f} GU"))
    return problems


def validate(m, *, sdk_set_names=None, pins=None, bc_radii=None, radius_scale=None,
             staged_points=None, staged_clearance_gu=None, bc_offsets=None) -> list:
    """Validate a SystemMap, returning a list of Problems (empty == valid).

    `sdk_set_names` and `pins` gate the region-coverage and pin-respected
    rules as before. `bc_radii` and `radius_scale` gate the radius-ratio
    rule -- it only runs when BOTH are given. `bc_radii` is a
    `{(region_set_name, body_name): bc_radius_gu}` mapping (see
    `tools.systems.survey.bc_radii`); `radius_scale` is the single scale
    every mapped body's radius must equal `bc_radius_gu * radius_scale` to
    (see `tools.systems.layout.LayoutTuning`).

    `staged_points` and `staged_clearance_gu` gate the staged-clearance rule
    -- it only runs when BOTH are given. `staged_points` is
    `{region_set_name: [(source_label, set-local xyz), ...]}` (built from
    `tools.systems.survey.SurveyedRegion.staged_points`). It skips
    bc_scale regions, and radius-ratio expects scale 1 in them.

    `bc_offsets` gates the bc-scale-position rule: a
    `{(region_set_name, body_name): BC set-local offset}` mapping (see
    `tools.systems.survey.bc_offsets`); a bc_scale region's bodies must sit
    at exactly anchor + that offset.
    """
    problems = []
    bodies = _sequence_field(m, "bodies", problems)
    regions = _sequence_field(m, "regions", problems)
    clouds = _sequence_field(m, "clouds", problems)

    by_name: dict = {}
    for b in bodies:
        by_name.setdefault(b.name, []).append(b)

    # malformed-geometry runs FIRST. Every rule below does arithmetic on
    # position_gu / anchor_gu (subtraction, zip, distance) with no guard of
    # its own -- a non-numeric coordinate raises deep inside a geometric rule
    # instead of being reported by name, and a 2-element vector doesn't raise
    # at all: `zip` truncates it, silently flattening every geometric check
    # to 2D and reporting a broken map as clean. Bodies and regions flagged
    # here are excluded (by identity / by set_name) from every rule after
    # this one that touches their geometry, so nothing downstream crashes or
    # gets misjudged on bad input.
    bad_bodies: set = set()
    bad_regions: set = set()
    for b in bodies:
        if not _is_point3(b.position_gu):
            bad_bodies.add(id(b))
            problems.append(Problem(
                "malformed-geometry",
                f"body {b.name!r} has a malformed position_gu {b.position_gu!r} "
                f"-- must be a sequence of exactly 3 numbers"))
    for r in regions:
        if not _is_point3(r.anchor_gu):
            bad_regions.add(r.set_name)
            problems.append(Problem(
                "malformed-geometry",
                f"region {r.set_name!r} has a malformed anchor_gu {r.anchor_gu!r} "
                f"-- must be a sequence of exactly 3 numbers"))

    if sdk_set_names is not None:
        have = {r.set_name for r in regions}
        for name in sdk_set_names:
            if name not in have:
                problems.append(Problem(
                    "region-coverage",
                    f"BC set {name!r} has no region in system {m.system!r}"))

    for r in regions:
        if r.set_name in bad_regions:
            continue
        for other in regions:
            if other is r:
                continue
            if other.set_name in bad_regions:
                continue
            if _dist(r.anchor_gu, other.anchor_gu) < r.radius_gu:
                problems.append(Problem(
                    "region-overlap",
                    f"region {r.set_name!r} (radius {r.radius_gu:.0f} GU) "
                    f"contains the anchor of {other.set_name!r}"))

    for r in regions:
        for name in r.body_names:
            body = _resolve(by_name, name, owner=r.set_name)
            if body is None:
                problems.append(Problem(
                    "body-owner",
                    f"region {r.set_name!r} names body {name!r}, which does not exist"))
                continue
            if body.owner_region != r.set_name:
                problems.append(Problem(
                    "body-owner",
                    f"body {name!r} is listed by region {r.set_name!r} but its "
                    f"owner_region is {body.owner_region!r}"))
            # NO `continue` here. A bad back-reference is a bookkeeping
            # error; engulfing the anchor is "you would spawn inside a
            # planet". They are independent, and the geometry is measured
            # against the LISTING region's anchor either way, so a body can
            # and must report both. Only the dangling-name branch above
            # continues -- there, there is no body left to measure. (Bad
            # geometry is its own third, independent branch: malformed-
            # geometry already reported it, so the geometric check here is
            # simply skipped rather than crashing on it.)
            if (id(body) not in bad_bodies and r.set_name not in bad_regions
                    and body.radius_gu >= _dist(body.position_gu, r.anchor_gu)):
                problems.append(Problem(
                    "body-engulfs-anchor",
                    f"body {name!r} (radius {body.radius_gu:.0f} GU) reaches the "
                    f"anchor of region {r.set_name!r}"))

    for i, a in enumerate(bodies):
        if id(a) in bad_bodies:
            continue
        for b in bodies[i + 1:]:
            if id(b) in bad_bodies:
                continue
            if _dist(a.position_gu, b.position_gu) <= a.radius_gu + b.radius_gu:
                problems.append(Problem(
                    "body-overlap",
                    f"body {a.name!r} (radius {a.radius_gu:.0f} GU) and body "
                    f"{b.name!r} (radius {b.radius_gu:.0f} GU) have intersecting "
                    f"surfaces"))

    for r in regions:
        if r.set_name in bad_regions:
            continue
        # Bodies the region itself owns are already covered by
        # body-engulfs-anchor above; this rule exists for everything ELSE
        # (most importantly the sun, which no region owns) so it is scoped to
        # bodies outside r's own listing to avoid double-reporting the same
        # fault under two slugs. Excluded by IDENTITY of the resolved body
        # (not by name) so a name collision elsewhere in the map (two
        # regions both with a companion called "Moon 1") can't exclude the
        # WRONG region's body from this check.
        own_bodies = {id(_resolve(by_name, name, owner=r.set_name))
                      for name in r.body_names}
        for b in bodies:
            if id(b) in own_bodies or id(b) in bad_bodies:
                continue
            if b.radius_gu >= _dist(b.position_gu, r.anchor_gu):
                problems.append(Problem(
                    "anchor-inside-body",
                    f"anchor of region {r.set_name!r} falls inside body "
                    f"{b.name!r} (radius {b.radius_gu:.0f} GU), which does not "
                    f"belong to that region -- body-engulfs-anchor only checks "
                    f"a region's own bodies"))

    # region-reaches-star: no *anchor* is ever inside a star (that would be
    # anchor-inside-body's job), but a region's SPHERE can still overlap the
    # star it orbits while its centre stays outside -- under streaming, that
    # region's boundary would pass through the sun. The star is identified by
    # `orbits is None`, never by name; skip the rule entirely when a map has
    # none (two systems build a MetaNebula and author no star at all).
    star = next((b for b in bodies if b.orbits is None), None)
    if star is not None and id(star) not in bad_bodies:
        for r in regions:
            if r.set_name in bad_regions:
                continue
            if _dist(r.anchor_gu, star.position_gu) <= r.radius_gu + star.radius_gu:
                problems.append(Problem(
                    "region-reaches-star",
                    f"region {r.set_name!r} (radius {r.radius_gu:.0f} GU) "
                    f"reaches star {star.name!r} (radius {star.radius_gu:.0f} GU)"))

    if pins is not None and not hasattr(pins, "items"):
        problems.append(Problem(
            "pin-respected",
            f"pins must be a mapping of \"Region/Body\" to offset, got "
            f"{type(pins).__name__}"))
    elif pins is not None:
        anchors = {r.set_name: r.anchor_gu for r in regions}
        for key, want_offset in pins.items():
            # Pin keys are "<region>/<body>", not a bare body name. BC reuses
            # bare companion names across regions of one system (Geble3 and
            # Geble4 both name a "Moon 1"; Itari3/5/8 each do), so a bare name
            # cannot identify which body a pin protects -- and silently
            # picking whichever candidate turns up first is worse than no
            # pin at all, because it *looks* like protection. Body names
            # themselves may contain spaces but never a slash, so splitting
            # on the FIRST '/' is unambiguous.
            if not isinstance(key, str):
                problems.append(Problem(
                    "pin-respected",
                    f"pin key {key!r} is not a string"))
                continue
            try:
                if len(want_offset) != 3 or not all(isinstance(x, (int, float)) for x in want_offset):
                    raise ValueError()
            except (TypeError, ValueError):
                problems.append(Problem(
                    "pin-respected",
                    f"pin offset for key {key!r} must be a sequence of 3 numbers, "
                    f"got {want_offset!r}"))
                continue
            if "/" not in key:
                problems.append(Problem(
                    "pin-respected",
                    f"pin key {key!r} is not \"Region/Body\" -- missing a '/'"))
                continue
            region_name, body_name = key.split("/", 1)
            if region_name not in anchors:
                problems.append(Problem(
                    "pin-respected",
                    f"pin {key!r} names region {region_name!r}, which does "
                    f"not exist in this map"))
                continue
            body = _resolve(by_name, body_name, owner=region_name)
            if body is None or body.owner_region != region_name:
                problems.append(Problem(
                    "pin-respected",
                    f"pin {key!r} names body {body_name!r}, but no body of "
                    f"that name is owned by region {region_name!r}"))
                continue
            if region_name in bad_regions or id(body) in bad_bodies:
                # malformed-geometry already reported this region's anchor
                # or this body's position; computing a set-local offset from
                # either would just repeat the same crash or truncation this
                # rule exists to avoid.
                continue
            anchor = anchors[region_name]
            have = tuple(p - a for p, a in zip(body.position_gu, anchor))
            if _dist(have, want_offset) > 1.0:
                problems.append(Problem(
                    "pin-respected",
                    f"pinned body {key!r} sits at set-local {have} but the "
                    f"mission stages content at {tuple(want_offset)}"))

    for b in bodies:
        if b.orbits is not None and b.orbits not in by_name:
            problems.append(Problem(
                "orbit-target",
                f"body {b.name!r} orbits {b.orbits!r}, which is not in this map"))

    # ---- cloud rules ---------------------------------------------------
    # cloud-volume-agrees-with-region, cloud-region-membership,
    # cloud-pocket-inside-cloud, cloud-profile-matches-params.
    #
    # A cloud rides alongside a map's bodies and regions and its own
    # geometry is exactly as exposed to malformed input as theirs, so it
    # gets the same guard-before-arithmetic treatment: a structurally
    # broken cloud/volume is reported under malformed-geometry or
    # cloud-region-membership, and every geometric rule below just skips
    # whatever it cannot trust rather than touching it.
    #
    # `star` and `bad_bodies` were already computed above for
    # region-reaches-star; a lobe's spine originates at the system's star,
    # which every checked-in map places at (0, 0, 0) -- falling back to the
    # literal origin when a map has no star at all (two systems build a
    # MetaNebula and author no star), matching the star-less branch above.
    star_origin = (0.0, 0.0, 0.0)
    if star is not None and id(star) not in bad_bodies and _is_point3(star.position_gu):
        star_origin = star.position_gu

    regions_by_name = {r.set_name: r for r in regions}
    region_cloud_count: dict = {}
    pockets_by_region: dict = {}   # region set_name -> [pocket Volume, ...]

    for cl in clouds:
        cloud_name = getattr(cl, "name", "?")

        regions_list = getattr(cl, "regions", None)
        if not isinstance(regions_list, list):
            problems.append(Problem(
                "cloud-region-membership",
                f"cloud {cloud_name!r} has a malformed regions field "
                f"{regions_list!r} -- must be a list of region names"))
            regions_list = []
        for name in regions_list:
            if not isinstance(name, str) or name not in regions_by_name:
                problems.append(Problem(
                    "cloud-region-membership",
                    f"cloud {cloud_name!r} names region {name!r}, which "
                    f"does not exist in system {m.system!r}"))
                continue
            region_cloud_count[name] = region_cloud_count.get(name, 0) + 1

        volumes_list = getattr(cl, "volumes", None)
        if not isinstance(volumes_list, list):
            problems.append(Problem(
                "malformed-geometry",
                f"cloud {cloud_name!r} has a malformed volumes field "
                f"{volumes_list!r} -- must be a list of volumes"))
            volumes_list = []

        large = None            # (extent, Volume) -- the biggest origin_region=None volume
        good_volumes = []       # volumes with trustworthy geometry
        for v in volumes_list:
            if not _looks_like_volume(v):
                problems.append(Problem(
                    "malformed-geometry",
                    f"cloud {cloud_name!r} has a malformed volume entry {v!r}"))
                continue

            geometry_ok = _volume_geometry_ok(v)
            if not geometry_ok:
                problems.append(Problem(
                    "malformed-geometry",
                    f"cloud {cloud_name!r} volume (shape {v.shape!r}, "
                    f"origin_region {v.origin_region!r}) has malformed "
                    f"geometry {v.geometry!r}"))

            # cloud-profile-matches-params, in two halves.
            #
            # The profile NAME must always be one we know -- "fog" is a
            # typo whichever kind of volume carries it.
            try:
                want_params = params_for(v.profile)
            except (KeyError, TypeError):
                want_params = None
                problems.append(Problem(
                    "cloud-profile-matches-params",
                    f"cloud {cloud_name!r} volume has unknown profile "
                    f"{v.profile!r} -- known profiles are {sorted(PROFILES)}"))

            # The NUMBERS are compared against whichever independent source
            # the volume has. A pocket has one: the region it was derived
            # from, whose `nebula` holds BC's own authored four. The large
            # volume has none -- no region, no BC original -- so the profile
            # table is the only thing it can be held to, and holding it
            # there is what stops `mist`'s zeros being quietly tuned.
            if isinstance(v.origin_region, str):
                for detail in _pocket_param_details(
                        v, regions_by_name.get(v.origin_region)):
                    problems.append(Problem(
                        "cloud-profile-matches-params",
                        f"cloud {cloud_name!r} pocket for region "
                        f"{v.origin_region!r} -- {detail}"))
            elif want_params is not None and v.params != want_params:
                problems.append(Problem(
                    "cloud-profile-matches-params",
                    f"cloud {cloud_name!r} volume with profile "
                    f"{v.profile!r} has params {v.params!r}, expected "
                    f"{want_params!r}"))

            if not geometry_ok:
                continue
            if isinstance(v.origin_region, str):
                # A pocket is always a sphere -- BC's own authored nebula
                # spheres are the only thing a pocket ever represents (see
                # tools/systems/layout.py:_build_clouds). Both downstream
                # checks (agrees-with-region, inside-the-large-volume) read
                # geometry["center_gu"] on the pocket side unconditionally,
                # which a lobe's geometry does not carry -- that must be
                # reported here, before either check ever runs, not left to
                # surface as a TypeError out of `zip(None, ...)`.
                if v.shape != "sphere":
                    problems.append(Problem(
                        "malformed-geometry",
                        f"cloud {cloud_name!r} pocket volume for region "
                        f"{v.origin_region!r} has shape {v.shape!r} -- a "
                        f"pocket must be a sphere"))
                else:
                    pockets_by_region.setdefault(v.origin_region, []).append(v)
                    good_volumes.append(v)
            elif v.origin_region is None:
                extent = _volume_extent(v)
                if large is None or extent > large[0]:
                    large = (extent, v)
                good_volumes.append(v)
            else:
                # A malformed origin_region type (not None, not a string) --
                # the same failure class the `regions` field guard above
                # reports, just on a single volume's back-reference instead
                # of the cloud's own listing. Silently accepting it would
                # bless a regeneration bug that writes an int or a list
                # there instead of a region name.
                problems.append(Problem(
                    "cloud-region-membership",
                    f"cloud {cloud_name!r} volume has a malformed "
                    f"origin_region {v.origin_region!r} -- must be null or "
                    f"a region name string"))

        # cloud-pocket-inside-cloud: skipped when the cloud has no large
        # volume. That is a legitimate state -- a system whose override
        # declares no `kind` still gets a cloud carrying BC's authored
        # pockets, deliberately, so BC's data is never silently lost.
        if large is not None:
            _, large_volume = large
            for v in good_volumes:
                if not isinstance(v.origin_region, str):
                    continue
                if not _pocket_inside_large(v, large_volume, star_origin):
                    problems.append(Problem(
                        "cloud-pocket-inside-cloud",
                        f"cloud {cloud_name!r} pocket for region "
                        f"{v.origin_region!r} is not inside the cloud's "
                        f"large volume"))

    for r in regions:
        if r.nebula is not None:
            count = region_cloud_count.get(r.set_name, 0)
            if count != 1:
                problems.append(Problem(
                    "cloud-region-membership",
                    f"region {r.set_name!r} carries a nebula but is listed "
                    f"by {count} cloud(s) -- expected exactly 1"))

            # cloud-volume-agrees-with-region, the bijection half: matched
            # GLOBALLY across every cloud's pockets for this region (not
            # per-cloud), so a pocket and its region are compared exactly
            # once no matter which cloud carries it. A sphere consumed by
            # no pocket (BC's data silently dropped) and a pocket matching
            # no remaining sphere (drifted, or a duplicate piled onto a
            # sphere another pocket already claimed) are both reported.
            unmatched_pockets, unmatched_spheres = _match_pockets_to_region(
                pockets_by_region.get(r.set_name, []), r)
            for v in unmatched_pockets:
                problems.append(Problem(
                    "cloud-volume-agrees-with-region",
                    f"pocket volume for region {r.set_name!r} does not sit "
                    f"at region.anchor_gu + any of its authored sphere "
                    f"offsets"))
            for sphere in unmatched_spheres:
                problems.append(Problem(
                    "cloud-volume-agrees-with-region",
                    f"region {r.set_name!r} authored a nebula sphere "
                    f"{sphere!r} with no matching cloud pocket volume"))

    if bc_radii is not None and radius_scale is not None:
        problems.extend(_radius_ratio_problems(
            m, bc_radii, radius_scale, _bc_scale_regions(regions, bad_regions)))

    if staged_points is not None and staged_clearance_gu is not None:
        problems.extend(_staged_clearance_problems(
            bodies, regions, bad_bodies, bad_regions, staged_points, staged_clearance_gu))

    if bc_offsets is not None:
        problems.extend(_bc_scale_position_problems(
            bodies, regions, bad_bodies, bad_regions, bc_offsets))

    return problems
