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
    return isinstance(x, (int, float))


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


def _pocket_matches_region(v, region) -> bool:
    """True if pocket volume v sits at region.anchor_gu + one of the
    region's own authored nebula spheres.

    The matching sphere is chosen by RADIUS (within 1e-6 relative) -- a
    region can carry more than one sphere, and radius is the one field BC
    authored that a pocket volume carries verbatim. Position is then
    checked against that specific sphere's offset, so a pocket that has
    drifted from its anchor (the anti-drift guard this rule exists for) is
    caught even though its radius still matches.
    """
    spheres = region.nebula.get("spheres") if isinstance(region.nebula, dict) else None
    if not isinstance(spheres, list) or not _is_point3(region.anchor_gu):
        return False
    center = v.geometry.get("center_gu")
    radius = v.geometry.get("radius_gu")
    for sphere in spheres:
        if not (isinstance(sphere, (list, tuple)) and len(sphere) == 4
                and all(_is_number(x) for x in sphere)):
            continue
        sx, sy, sz, sr = sphere
        if not math.isclose(radius, sr, rel_tol=1e-6):
            continue
        expected = tuple(a + o for a, o in zip(region.anchor_gu, (sx, sy, sz)))
        tolerance = 1e-6 * max(1.0, _dist(expected, (0.0, 0.0, 0.0)))
        if _dist(center, expected) <= tolerance:
            return True
    return False


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

    regions_by_name = {r.set_name: r for r in m.regions}
    region_cloud_count: dict = {}

    for cl in m.clouds:
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

            try:
                want_params = params_for(v.profile)
            except (KeyError, TypeError):
                problems.append(Problem(
                    "cloud-profile-matches-params",
                    f"cloud {cloud_name!r} volume has unknown profile "
                    f"{v.profile!r} -- known profiles are {sorted(PROFILES)}"))
            else:
                if v.params != want_params:
                    problems.append(Problem(
                        "cloud-profile-matches-params",
                        f"cloud {cloud_name!r} volume with profile "
                        f"{v.profile!r} has params {v.params!r}, expected "
                        f"{want_params!r}"))

            if not geometry_ok:
                continue
            if isinstance(v.origin_region, str):
                region = regions_by_name.get(v.origin_region)
                if region is not None and region.nebula is not None:
                    if not _pocket_matches_region(v, region):
                        problems.append(Problem(
                            "cloud-volume-agrees-with-region",
                            f"cloud {cloud_name!r} pocket volume for region "
                            f"{v.origin_region!r} does not sit at "
                            f"region.anchor_gu + its authored sphere offset"))
                good_volumes.append(v)
            elif v.origin_region is None:
                extent = _volume_extent(v)
                if large is None or extent > large[0]:
                    large = (extent, v)
                good_volumes.append(v)
            # else: a malformed origin_region type -- nothing further to
            # check against it; the volume is neither a trustworthy pocket
            # nor a trustworthy large-volume candidate.

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

    for r in m.regions:
        if r.nebula is not None:
            count = region_cloud_count.get(r.set_name, 0)
            if count != 1:
                problems.append(Problem(
                    "cloud-region-membership",
                    f"region {r.set_name!r} carries a nebula but is listed "
                    f"by {count} cloud(s) -- expected exactly 1"))

    return problems
