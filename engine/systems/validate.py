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

from .profile import COLUMNS, clump_radius


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


def _sequence_field(m, name: str, problems: list) -> list:
    """`m.<name>` as a list, reporting rather than raising on anything else.

    The two list fields are the outermost thing validate() touches, and
    every loop over them was unguarded: `m.bodies = None` / `m.regions = None`
    raised TypeError out of `for x in m.<field>` before a single rule ran.
    "validate() never raises" is a named hard constraint of this file, so the
    entry points to it need the same guard-before-use treatment `_is_point3`
    gives a coordinate.

    A str is rejected even though it is iterable: iterating it yields
    characters, which then raise AttributeError on `.name` -- a different
    crash from the same fault. A tuple is accepted; it is a perfectly good
    sequence and not a fault worth reporting.
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


def _profile_problems(m) -> list:
    """Radial profile rules (spec: 'Validator rules'). Never raises."""
    prof = getattr(m, "profile", None)
    if prof is None or not getattr(prof, "rows", None):
        return []
    rows = prof.rows
    out = []
    ordered = rows[0].distance_gu == 0.0 and all(
        a.distance_gu <= b.distance_gu for a, b in zip(rows, rows[1:]))
    in_range = all(
        math.isfinite(getattr(r, c)) and 0.0 <= getattr(r, c) <= 1.0
        for r in rows for c in COLUMNS) and all(math.isfinite(r.distance_gu) for r in rows)
    if not (ordered and in_range):
        out.append(Problem("profile-rows-ordered",
                           f"{m.system}: rows must be sorted, start at 0 and hold "
                           f"finite values in 0-1"))
    if rows[-1].radiation != 0.0:
        out.append(Problem("profile-radiation-clears",
                           f"{m.system}: last row radiation {rows[-1].radiation} persists "
                           f"outward forever; it must be 0"))
    if (getattr(m, "overrides", None) or {}).get("profile") is not None:
        star = next((b for b in m.bodies if b.orbits is None), None)
        peak = max(rows, key=lambda r: r.nebula)
        for region in m.regions:
            neb = region.nebula
            if star is None or not neb or not neb.get("spheres"):
                continue
            R = clump_radius(region, star.position_gu)
            if peak.nebula > 0.0 and abs(peak.distance_gu - R) > region.radius_gu:
                out.append(Problem("profile-override-tracks-clump",
                                   f"{m.system}: override nebula peak at {peak.distance_gu:.0f} GU "
                                   f"but {region.set_name}'s clump is at {R:.0f} GU "
                                   f"(tolerance {region.radius_gu:.0f})"))
    return out


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

    if bc_radii is not None and radius_scale is not None:
        problems.extend(_radius_ratio_problems(
            m, bc_radii, radius_scale, _bc_scale_regions(regions, bad_regions)))

    if staged_points is not None and staged_clearance_gu is not None:
        problems.extend(_staged_clearance_problems(
            bodies, regions, bad_bodies, bad_regions, staged_points, staged_clearance_gu))

    if bc_offsets is not None:
        problems.extend(_bc_scale_position_problems(
            bodies, regions, bad_bodies, bad_regions, bc_offsets))

    problems.extend(_profile_problems(m))

    return problems
