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


@dataclass
class Problem:
    rule: str
    detail: str


def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _is_point3(v) -> bool:
    """True if v is a sequence of exactly 3 numbers -- a well-formed GU point.

    `_dist` above uses `zip`, which silently truncates to the shorter side: a
    2-element vector paired against a 3-element one compares only x and y and
    reports the map clean. Catching that here, before any geometric rule runs,
    is the difference between a malformed map raising deep inside a distance
    calculation and it being reported by name.
    """
    try:
        return len(v) == 3 and all(isinstance(c, (int, float)) for c in v)
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


def validate(m, *, sdk_set_names=None, pins=None) -> list:
    problems = []
    by_name: dict = {}
    for b in m.bodies:
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
    for b in m.bodies:
        if not _is_point3(b.position_gu):
            bad_bodies.add(id(b))
            problems.append(Problem(
                "malformed-geometry",
                f"body {b.name!r} has a malformed position_gu {b.position_gu!r} "
                f"-- must be a sequence of exactly 3 numbers"))
    for r in m.regions:
        if not _is_point3(r.anchor_gu):
            bad_regions.add(r.set_name)
            problems.append(Problem(
                "malformed-geometry",
                f"region {r.set_name!r} has a malformed anchor_gu {r.anchor_gu!r} "
                f"-- must be a sequence of exactly 3 numbers"))

    if sdk_set_names is not None:
        have = {r.set_name for r in m.regions}
        for name in sdk_set_names:
            if name not in have:
                problems.append(Problem(
                    "region-coverage",
                    f"BC set {name!r} has no region in system {m.system!r}"))

    for r in m.regions:
        if r.set_name in bad_regions:
            continue
        for other in m.regions:
            if other is r:
                continue
            if other.set_name in bad_regions:
                continue
            if _dist(r.anchor_gu, other.anchor_gu) < r.radius_gu:
                problems.append(Problem(
                    "region-overlap",
                    f"region {r.set_name!r} (radius {r.radius_gu:.0f} GU) "
                    f"contains the anchor of {other.set_name!r}"))

    for r in m.regions:
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

    for i, a in enumerate(m.bodies):
        if id(a) in bad_bodies:
            continue
        for b in m.bodies[i + 1:]:
            if id(b) in bad_bodies:
                continue
            if _dist(a.position_gu, b.position_gu) <= a.radius_gu + b.radius_gu:
                problems.append(Problem(
                    "body-overlap",
                    f"body {a.name!r} (radius {a.radius_gu:.0f} GU) and body "
                    f"{b.name!r} (radius {b.radius_gu:.0f} GU) have intersecting "
                    f"surfaces"))

    for r in m.regions:
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
        for b in m.bodies:
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
    star = next((b for b in m.bodies if b.orbits is None), None)
    if star is not None and id(star) not in bad_bodies:
        for r in m.regions:
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
        anchors = {r.set_name: r.anchor_gu for r in m.regions}
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

    for b in m.bodies:
        if b.orbits is not None and b.orbits not in by_name:
            problems.append(Problem(
                "orbit-target",
                f"body {b.name!r} orbits {b.orbits!r}, which is not in this map"))

    return problems
