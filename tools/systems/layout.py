"""Turn a survey into a system map: bodies on orbits, anchors placed to
reproduce the original artist's framing.

THE ANCHOR RULE is the part with real content. The original set records, for
each body, which DIRECTION you looked to see it (the unit vector from that
set's Player Start to the body) and how far away it was. Distance is discarded
-- bodies are re-authored much larger, so the standoff comes from the new
radius -- but the DIRECTION is reproduced exactly: from the new anchor, the
primary body lies on the same bearing it did in BC.

Because a region's anchor is a translation only (never a rotation), and system
axes are the region's local axes, reproducing that bearing is simply
    anchor = primary_position - view_direction * standoff

With companions the anchor moves to the group centroid first, so a planet and
its moon frame you between them -- which is what "anchor between the two" means.

WHAT THIS CANNOT PRESERVE: lighting direction. Each BC set carries its own sun
at +-70000 GU in whatever direction suited that one map (Alioth1's at +X,
Alioth3's at -X, in nominally the same system). With one real sun at the
centre, light comes from wherever the region actually sits. Per-set suns are
discarded here on purpose.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from engine.systems import clouds as cloud_profiles
from engine.systems.map import Appearance, Body, Cloud, Region, SystemMap, Volume

_GOLDEN_ANGLE = 2.399963229728653

# Star colour by CLASS NAME, not texture. Exact values from the design
# brief's measured survey of the SDK, plus remnant_hot (see below).
#
# Keyed by class rather than by BC's texture basename because one class here
# is reachable only through a star override (overrides.star in a map's JSON,
# see layout()'s `star` argument) and no BC texture ever produces it:
# remnant_hot is Vesuvi's star, its core destabilised by a Kessok
# Solarformer in BC's own opening cutscene, leaving a small hot blue-white
# remnant rather than anything Sun_Create was ever called for. Texture
# lookups go through the separate _STAR_TEXTURE_CLASSES map below.
_STAR_CLASS_TABLE = {
    "yellow": (1.0, 0.85, 0.40),
    "red": (0.91, 0.35, 0.24),
    "red_orange": (0.94, 0.54, 0.24),
    "blue_white": (0.74, 0.84, 1.0),
    # Anything else, including BC's own default (no texture argument at all).
    "white": (1.0, 0.95, 0.80),
    # A system that authors no Sun_Create whatsoever (Belaruz, Vesuvi) --
    # the fallback absent any star override.
    "brown_dwarf": (0.42, 0.25, 0.18),
    # No BC texture produces this -- only a star override does (Vesuvi).
    "remnant_hot": (0.78, 0.86, 1.0),
}

# BC's authored Sun_Create base texture basename -> star class.
_STAR_TEXTURE_CLASSES = {
    "SunYellow.tga": "yellow",
    "SunRed.tga": "red",
    "SunRedOrange.tga": "red_orange",
    "SunBlueWhite.tga": "blue_white",
}


@dataclass
class LayoutTuning:
    planet_radius_scale: float = 20.0
    moon_radius_scale: float = 20.0
    sun_radius_scale: float = 2.0
    framing_scale: float = 2.0
    min_standoff_factor: float = 1.5
    max_standoff_factor: float = 12.0
    # Fallback star radius for a system that authors no Sun_Create at all
    # (Belaruz, Vesuvi) -- those become brown dwarfs, dim and smaller than
    # any real authored star.
    brown_dwarf_radius_gu: float = 2000.0
    # A MINIMUM, not a fixed distance: the innermost orbit sits at least this
    # far from the star's surface, and farther still when that would leave a
    # region's sphere reaching the star (see star_clearance_gu and the push
    # logic in layout()).
    first_orbit_clearance_gu: float = 30000.0
    orbit_step_gu: float = 26000.0
    region_margin_gu: float = 1500.0
    # Margin left between a region's sphere and the star's surface after the
    # corrective push in layout(), so the two end up clear rather than exactly
    # tangent.
    star_clearance_gu: float = 500.0
    # Fallback only: used when a region's BC geometry is degenerate (the
    # primary sits exactly on Player Start, so there is no distance/radius
    # ratio to derive a standoff from). See _standoff_factor.
    anchor_standoff_factor: float = 2.2
    moon_first_orbit_factor: float = 4.0
    moon_orbit_step_factor: float = 1.5
    # A key light this close to straight up or down carries no usable bearing
    # once flattened into the orbital plane. 0.999 is ~2.6 degrees, which
    # catches the eight regions whose forward is EXACTLY (0, 0, +/-1) -- an
    # untouched default -- while keeping the two genuinely-steep ones near 73
    # degrees, whose flattened bearing is still real.
    vertical_light_tol: float = 0.999
    # Bearings come from BC's lighting, so two regions in one system can share
    # one. When that happens the outer is pushed out in steps of this fraction
    # of orbit_step_gu until the two spheres clear each other.
    orbit_push_fraction: float = 0.25


def _norm(v) -> float:
    return math.sqrt(sum(c * c for c in v))


def _unit(v):
    n = _norm(v)
    if n <= 0.0:
        return (0.0, 1.0, 0.0)
    return tuple(c / n for c in v)


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _scale(v, k):
    return tuple(c * k for c in v)


def _orbit_position(index: int, first_orbit: float, t: LayoutTuning):
    """Fallback bearing only -- see _bearing(). A golden-angle spread puts a
    region SOMEWHERE, which is all that can be done for a region whose own
    lighting says nothing about where its star is."""
    r = first_orbit + t.orbit_step_gu * index
    a = _GOLDEN_ANGLE * index
    return (r * math.sin(a), r * math.cos(a), 0.0)


def _bearing(index: int, region, t: LayoutTuning):
    """Unit bearing from the star to this region, in the orbital plane.

    Taken from the region's own key light. BC's directional says which way the
    light travels -- from the star, toward the scene -- so placing the region
    along it puts the star exactly where the artists lit from, and their
    authored direction needs no correction at runtime.

    Two cases fall back to the golden-angle spread, and both are reported by
    ambiguities():

    - No directional at all. Does not occur in the 90 campaign regions, but a
      mod's set might.
    - A key light within `vertical_light_tol` of straight up or down, where the
      flattened bearing is noise rather than signal. Eight regions are affected
      and in every one the forward is EXACTLY (0, 0, +/-1) -- an untouched
      default the artists never rotated, not an authored direction. Two more
      sit around 73 degrees, steep but genuinely aimed, and those are used.
    """
    d = getattr(region, "key_light_dir", None)
    if d is not None and abs(d[2]) < t.vertical_light_tol:
        flat = math.sqrt(d[0] * d[0] + d[1] * d[1])
        if flat > 0.0:
            return (d[0] / flat, d[1] / flat, 0.0)
    a = _GOLDEN_ANGLE * index
    return (math.sin(a), math.cos(a), 0.0)


def _standoff_factor(primary, region, t) -> float:
    """How many NEW planet-radii the anchor sits back from the planet's centre.

    Derived from BC's own framing. The artist placed each planet at a distance
    that gave it a particular apparent size, and that varied per map -- Ona 2
    read close, Ona 1 distant. A single constant flattened all of it.

    Because the standoff is measured in radii, the planet's SIZE cancels out of
    the apparent angle: `planet_radius_scale` and `framing_scale` are
    independent knobs. At framing_scale 1.0 the result equals BC's apparent
    size exactly.

    Clamped at both ends. The floor keeps the anchor outside the planet; the
    cap exists because BC's most distant framing (Savoy 1: a 100 GU planet
    5041 GU away, 50:1) would otherwise throw the anchor far enough to pass the
    sun. Both clamps are reported by ambiguities() -- they override BC's intent.
    """
    r_bc = primary.radius_gu
    d_bc = _norm(_sub(primary.offset_gu, region.player_start_gu))
    if r_bc <= 0.0 or d_bc <= 0.0:
        return t.anchor_standoff_factor
    raw = (d_bc / r_bc) / t.framing_scale
    return min(max(raw, t.min_standoff_factor), t.max_standoff_factor)


def _ordered(s):
    """The regions that get an orbit, in orbital order.

    Only places BC's own CreateSystemMenu offers. An orphan still in the tree
    is not somewhere the player can go, and giving it a slot pushes every real
    place outward: Vesuvi1 is unlisted and was taking the innermost orbit at
    32,000 GU, displacing Vesuvi4 -- BC's FIRST listed place, and the system's
    dust cloud -- out to 58,000.

    It is the only such case across all 32 systems. Its set still exists and
    the survey still reads it; it simply is not a destination.
    """
    usable = [r for r in s.regions if getattr(r, "menu_listed", True)]
    numbered = [r for r in usable if r.ordinal is not None]
    unnumbered = [r for r in usable if r.ordinal is None]
    numbered.sort(key=lambda r: r.ordinal)
    return numbered + unnumbered


def _reach_estimate(region, t: LayoutTuning) -> float:
    """A CONSERVATIVE bound on how far this region reaches from its anchor.

    Used only to space orbits before the bodies exist. It must never
    UNDER-estimate -- an under-estimate lets two regions overlap, which
    validate()'s region-overlap rule then reports. Over-estimating only makes a
    system slightly roomier, so every term here is taken at its maximum.
    """
    primary, companions = _split(region)
    if primary is None:
        return region.content_extent_gu + t.region_margin_gu
    primary_radius = primary.radius_gu * t.planet_radius_scale
    furthest = primary_radius
    for j, c in enumerate(companions):
        distance = primary_radius * (t.moon_first_orbit_factor
                                     + t.moon_orbit_step_factor * j)
        furthest = max(furthest, distance + c.radius_gu * t.moon_radius_scale)
    standoff = _standoff_factor(primary, region, t) * primary_radius
    return max(standoff + furthest, region.content_extent_gu) + t.region_margin_gu


def _orbital_centres(ordered, first_orbit: float, t: LayoutTuning) -> list:
    """One orbital centre per region: BC's own bearing, at a radius that clears
    everything already placed.

    The bearing is not ours to choose (see _bearing), so two regions in one
    system can be lit from the same direction and land on the same line. The
    radius is ours, so that is what gives: push the outer one out until the two
    spheres are clear. Measured across all 32 systems this resolves every
    collision at a median cost of 1.03x the system's outermost radius.
    """
    step = t.orbit_step_gu * t.orbit_push_fraction
    placed, centres = [], []
    for index, region in enumerate(ordered):
        bearing = _bearing(index, region, t)
        reach = _reach_estimate(region, t)
        radius = first_orbit + t.orbit_step_gu * index
        while True:
            centre = _scale(bearing, radius)
            if all(_norm(_sub(centre, p)) >= reach + r for p, r in placed):
                break
            radius += step
        placed.append((centre, reach))
        centres.append(centre)
    return centres


def _split(region):
    """(primary, companions) -- the largest non-sun body wins."""
    planets = [b for b in region.bodies if not b.is_sun]
    if not planets:
        return None, []
    primary = max(planets, key=lambda b: b.radius_gu)
    return primary, [b for b in planets if b is not primary]


def _sun_radius(s, t: LayoutTuning) -> float:
    # Two systems (Belaruz, Vesuvi) build a MetaNebula and author no Sun_Create
    # at all -- sun_bc is 0.0 there, and brown_dwarf_radius_gu is the fallback.
    sun_bc = max(
        (b.radius_gu for region in s.regions for b in region.bodies if b.is_sun),
        default=0.0)
    return (sun_bc * t.sun_radius_scale) if sun_bc > 0.0 else t.brown_dwarf_radius_gu


def _sun_textures(s) -> list:
    return [b.base_texture for region in s.regions for b in region.bodies if b.is_sun]


def _classify_texture(texture: str) -> tuple:
    basename = texture.rsplit("/", 1)[-1] if texture else ""
    star_class = _STAR_TEXTURE_CLASSES.get(basename, "white")
    return star_class, _STAR_CLASS_TABLE[star_class]


def _star_appearance(s) -> tuple:
    """(star_class, color) for this system's star, from BC's authored sun
    texture(s). No Sun_Create at all (Belaruz, Vesuvi) -> brown dwarf. A
    system whose regions disagree on the texture takes the most common one;
    ambiguities() is where that disagreement gets reported, not here."""
    textures = _sun_textures(s)
    if not textures:
        return "brown_dwarf", _STAR_CLASS_TABLE["brown_dwarf"]
    chosen = Counter(textures).most_common(1)[0][0]
    return _classify_texture(chosen)


def _star_class_and_color(s, star) -> tuple:
    """(star_class, color) for this system's star -- a per-system `star`
    override (overrides.star in the map's JSON) wins outright over anything
    derived from BC's authored Sun_Create texture. An override with no
    explicit colour falls back to the class table, exactly like a BC-derived
    class does."""
    if star is not None:
        star_class = star["star_class"]
        color = star.get("color")
        if color is not None:
            return star_class, tuple(float(c) for c in color)
        return star_class, _STAR_CLASS_TABLE.get(star_class, _STAR_CLASS_TABLE["white"])
    return _star_appearance(s)


def _star_radius(s, t: LayoutTuning, star) -> float:
    """Sun radius: an override's radius_gu wins when given; an absent one
    leaves the derived radius (BC's authored sun, or the brown-dwarf
    fallback when there is none) alone."""
    if star is not None and star.get("radius_gu") is not None:
        return float(star["radius_gu"])
    return _sun_radius(s, t)


def _max_star_intrusion(m: SystemMap, star, t: LayoutTuning) -> float:
    """The largest amount, across all regions, by which a sphere reaches the
    star -- 0.0 if every region already clears it by at least star_clearance_gu.
    """
    return max(
        [0.0] + [
            r.radius_gu + star.radius_gu + t.star_clearance_gu - _norm(_sub(r.anchor_gu, star.position_gu))
            for r in m.regions
        ])


def _build_cloud_large_volume(kind: str, cloud: dict, members: list,
                              pocket_volumes: list) -> Volume | None:
    """The system-scale volume for a cloud with a declared `kind`. Ships
    inert (profile "mist", all-zero params) until that profile is tuned.

    `members` are the map's own placed Regions that carry a nebula -- anchors
    are FINAL by the time this runs (built after _place()'s region loop).
    `pocket_volumes` is this cloud's own pocket Volume list; only the
    "nebula_field" branch below ever reads it (to derive the lobe's axis
    from the first pocket's centre) -- a debris shell's radius comes
    straight from the member regions and never touches it, and a
    "nebula_field" override on a nebula authored with NO spheres (a
    MetaNebula_Create with no AddNebulaSphere call after it, per
    survey._nebula) has no pocket to point an axis at, so it emits no large
    volume rather than raising IndexError on an empty list.
    """
    mist = cloud_profiles.params_for("mist")
    if kind == "debris_shell":
        radius = max(_norm(r.anchor_gu) + r.radius_gu for r in members)
        return Volume(
            shape="sphere",
            geometry={"center_gu": (0.0, 0.0, 0.0), "radius_gu": radius},
            profile="mist", params=mist, origin_region=None)
    if kind == "nebula_field":
        if not pocket_volumes:
            return None
        geometry = dict(cloud.get("geometry", {}))
        geometry["axis"] = list(_unit(pocket_volumes[0].geometry["center_gu"]))
        return Volume(shape="lobe", geometry=geometry, profile="mist",
                      params=mist, origin_region=None)
    return None


def _build_clouds(m: SystemMap, cloud: dict | None) -> list:
    """The clouds a placed map carries, built from the regions' own
    (already-anchored) nebulae plus an optional per-system override.

    Only ever called from _place(), after its region loop, so every anchor
    here is final -- the pocket volumes below add the anchor to BC's
    set-local sphere, which is the entire reason a system-scale cloud can
    exist without a second source of truth (see the pinning test). No
    override -> pocket volumes only: losing BC's authored nebula because
    nobody declared a kind would be the worst failure mode here.
    """
    members = [r for r in m.regions if r.nebula is not None]
    if not members:
        return []

    volumes = []
    for region in members:
        # BC's own damage choice, not the override: the profile must be
        # derivable from data that cannot disagree with BC.
        profile = "debris" if region.nebula["damage_hull_per_s"] > 0 else "nebula"
        for sphere in region.nebula["spheres"]:
            # params_for() called PER SPHERE, not hoisted above this loop:
            # each Volume gets its OWN params dict. Hoisting it made every
            # pocket of a multi-sphere region alias one shared dict, so an
            # in-place mutation of one pocket's params (a later pass over
            # cloud.volumes) would silently apply to every sibling too.
            params = cloud_profiles.params_for(profile)
            x, y, z, radius = sphere
            volumes.append(Volume(
                shape="sphere",
                geometry={"center_gu": _add(region.anchor_gu, (x, y, z)),
                          "radius_gu": radius},
                profile=profile, params=params, origin_region=region.set_name))

    if cloud is not None:
        name, display_name, kind = cloud["name"], cloud["display_name"], cloud["kind"]
    else:
        name, display_name, kind = members[0].set_name, members[0].set_name, ""

    result = Cloud(
        name=name, display_name=display_name, kind=kind,
        color=members[0].nebula["color"], volumes=volumes,
        regions=[r.set_name for r in members])

    if cloud is not None:
        # The pocket centre is only ever needed by the "nebula_field" branch
        # (to derive the lobe's axis) -- NOT evaluated for "debris_shell",
        # and not evaluated at all when a nebula carries no spheres (a
        # MetaNebula_Create with no valid AddNebulaSphere call following it,
        # per survey._nebula). volumes[0] would previously raise IndexError
        # in that case even for "debris_shell", which never reads it.
        large = _build_cloud_large_volume(kind, cloud, members, volumes)
        if large is not None:
            result.volumes = result.volumes + [large]

    return [result]


def _first_orbit_push(s, t: LayoutTuning, pins, star=None, cloud=None) -> tuple[float, SystemMap]:
    """The corrective distance added to the first orbit, and the resulting map.

    `star` is the per-system star override dict (or None), threaded straight
    through to `_sun_radius`'s replacement, `_star_radius`, and to `_place`'s
    appearance choice -- it never changes the PUSH LOGIC itself, only the
    sun_radius the logic starts from. `cloud` is threaded the same way, straight
    through to `_place`'s cloud-building step -- the clouds built by the
    baseline and probe placements below are discarded along with the rest of
    those maps; only the FINAL placement's clouds survive, and their shell/lobe
    geometry is derived from that final placement's (possibly pushed) anchors.

    All 7 known offenders are the INNERMOST region of their system, and every
    orbit is `first_orbit + orbit_step_gu * i` -- so raising the first orbit
    moves every region outward by the same amount, which can fix the inner
    ones and can never create a new clip further out. A region's radius is
    `max(reach, content_extent) + margin`, where `reach` is measured from its
    OWN anchor -- moving the whole system outward changes neither term, so the
    radius is invariant under this adjustment.

    Deviation from the naive `target - dist(anchor, star)` estimate: that
    formula is only exact when the anchor sits exactly on the outward radial
    line the orbit centre moves along. In general the anchor is offset from
    that line by a fixed vector (the group centroid shift, the framing
    standoff), so raising first_orbit by the naive estimate under-corrects --
    measured live on 6 of the 7 real offenders, leaving 5-800 GU of intrusion
    after a "second pass" that was supposed to be a float-drift guard only.
    Because each region's anchor is an EXACT affine function of first_orbit
    (a rigid translation along a fixed per-region direction -- see
    _orbit_position), that direction can be measured exactly with one probe
    placement 1 GU further out, and the exact delta solved in closed form,
    rather than iterating the approximation. That probe plus the corrective
    placement is two extra `_place` calls beyond the baseline -- three in
    total, still bounded and not a loop -- and the guard pass on the final
    result now genuinely only catches floating-point drift.

    The push is computed from the UNPINNED framing, deliberately, and pins
    are only applied to the final, returned placement. A pin exists to hold
    ONE body at an authored offset from its own anchor; if the push amount
    depended on pins, adding or moving a pin could silently drag every
    OTHER region's bodies to a new position too, which is not what pinning
    a body means (see test_an_unpinned_body_in_the_same_region_is_not_moved).
    """
    sun_radius = _star_radius(s, t, star)
    base_first_orbit = sun_radius + t.first_orbit_clearance_gu
    m = _place(s, t, {}, base_first_orbit, sun_radius, star, cloud)
    star_body = next(b for b in m.bodies if b.orbits is None)
    if _max_star_intrusion(m, star_body, t) <= 0.0:
        push = 0.0
    else:
        worst = max(m.regions, key=lambda r: (
            r.radius_gu + star_body.radius_gu + t.star_clearance_gu
            - _norm(_sub(r.anchor_gu, star_body.position_gu))))
        probe = _place(s, t, {}, base_first_orbit + 1.0, sun_radius, star, cloud)
        probe_anchor = next(r.anchor_gu for r in probe.regions if r.set_name == worst.set_name)
        direction = _sub(probe_anchor, worst.anchor_gu)  # exact anchor shift per 1 GU of first_orbit

        target = worst.radius_gu + star_body.radius_gu + t.star_clearance_gu
        # worst.anchor_gu is used directly as the vector FROM THE STAR below
        # (a_dot_u, a_sq) -- valid only because _place() always puts the star
        # at the origin (see the Body appended at the top of _place()).
        a_dot_u = sum(a * u for a, u in zip(worst.anchor_gu, direction))
        u_sq = sum(u * u for u in direction)
        a_sq = sum(a * a for a in worst.anchor_gu)
        discriminant = a_dot_u * a_dot_u - u_sq * (a_sq - target * target)
        push = (-a_dot_u + math.sqrt(max(discriminant, 0.0))) / u_sq

    # Final placement: pins applied, at the (possibly pushed) first orbit.
    m = _place(s, t, pins, base_first_orbit + push, sun_radius, star, cloud)
    star_body = next(b for b in m.bodies if b.orbits is None)
    residual = _max_star_intrusion(m, star_body, t)
    if residual > 1e-6:
        raise ValueError(
            f"system {s.name!r}: pushed the first orbit out by {push:.1f} GU "
            f"but {residual:.6f} GU of intrusion remains in the final "
            f"(pinned) placement -- the reach/content_extent invariant this "
            f"fix relies on does not hold here")
    return push, m


def ambiguities(s, tuning: LayoutTuning | None = None, cloud: dict | None = None) -> list:
    t = tuning or LayoutTuning()
    notes = []
    for region in s.regions:
        primary_check, _ = _split(region)
        if primary_check is not None:
            r_bc = primary_check.radius_gu
            d_bc = _norm(_sub(primary_check.offset_gu, region.player_start_gu))
            if r_bc > 0.0 and d_bc > 0.0:
                raw = (d_bc / r_bc) / t.framing_scale
                if raw < t.min_standoff_factor:
                    notes.append(
                        f"{region.set_name}: {primary_check.name!r} standoff "
                        f"clamped to the MIN floor ({t.min_standoff_factor} "
                        f"radii) -- BC framed it closer than the floor allows")
                elif raw > t.max_standoff_factor:
                    notes.append(
                        f"{region.set_name}: {primary_check.name!r} standoff "
                        f"clamped to the MAX cap ({t.max_standoff_factor} "
                        f"radii) -- BC framed it farther than the cap allows")
        if (primary_check is not None
                and _norm(_sub(primary_check.offset_gu, region.player_start_gu)) <= 0.0):
            # _unit() falls back to +Y for a zero-length vector, which would
            # silently frame the region northward. Measured 2026-09-22: this
            # fires on 0 of the 90 real regions, so reaching it means the survey
            # failed to resolve a waypoint -- say so rather than guess.
            notes.append(
                f"{region.set_name}: {primary_check.name!r} sits exactly on "
                f"Player Start, so there is no original viewing direction -- "
                f"the anchor defaults to +Y and is probably wrong")
        if region.ordinal is None:
            notes.append(
                f"{region.set_name}: no trailing number, so its orbit order is a "
                f"guess -- set it in overrides")
        primary, companions = _split(region)
        for c in companions:
            if "moon" not in c.name.lower():
                notes.append(
                    f"{region.set_name}: {c.name!r} was demoted to a moon of "
                    f"{primary.name!r}, but its name does not say 'Moon' -- it may "
                    f"be a separate world needing its own orbit")
        # A set whose static file builds several MetaNebulae -- only the
        # first is ever placed (see survey._nebula); the rest are dropped, so
        # that must never happen silently.
        if region.nebula is not None and region.nebula.get("extra_nebulae", 0) > 0:
            notes.append(
                f"{region.set_name}: builds "
                f"{region.nebula['extra_nebulae']} additional nebula(e) beyond "
                f"the first -- only the first is placed, the rest are dropped")

    # An override that declares a `kind` neither construction rule recognises
    # silently degrades to a pockets-only cloud (see _build_cloud_large_volume
    # -- an unrecognised kind returns None and the caller just skips the large
    # volume). Losing the entire system-scale shell/lobe to a typo must not
    # be silent, same as construction rule 5's "no override" case already
    # isn't silent about keeping only the pockets.
    if (cloud is not None and any(r.nebula is not None for r in s.regions)
            and cloud.get("kind") not in ("debris_shell", "nebula_field")):
        notes.append(
            f"{s.name}: cloud kind {cloud.get('kind')!r} is not "
            f"'debris_shell' or 'nebula_field' -- no system-scale volume "
            f"will be built, the cloud ships with its BC pockets only")

    # A system whose regions disagree about the sun's texture takes the most
    # common one (see _star_appearance) -- that pick must never be silent.
    textures = _sun_textures(s)
    if len(set(textures)) > 1:
        counts = Counter(textures)
        chosen = counts.most_common(1)[0][0]
        notes.append(
            f"{s.name}: regions disagree on sun base texture "
            f"{dict(counts)} -- took the most common, {chosen!r}, for the "
            f"star's colour")

    # Report a pushed first orbit -- this changes numbers a human chose (the
    # first_orbit_clearance_gu the tuning specified), so it must never happen
    # silently. Uses no pins: ambiguities() reports on the SURVEY, before any
    # mission-staging pin is known.
    push, _m = _first_orbit_push(s, t, {})
    if push > 0.0:
        notes.append(
            f"{s.name}: first orbit pushed out by {push:.0f} GU beyond "
            f"first_orbit_clearance_gu -- a region's sphere would otherwise "
            f"have reached the star")
    return notes


def _place(s, t: LayoutTuning, pins, first_orbit: float, sun_radius: float,
           star=None, cloud=None) -> SystemMap:
    """Place bodies and regions given an already-decided first-orbit distance
    and sun radius. Pure function of its arguments -- called twice by
    _first_orbit_push() when a corrective push is needed, so it must not read
    or cache anything beyond what it is passed.

    `star` is the per-system star override dict (or None); it only changes
    the sun Body's appearance, never the placement geometry.

    `cloud` is the per-system cloud override dict (overrides.cloud, or None).
    Clouds are built LAST, after the region loop below, so every region's
    anchor_gu used here is final for THIS call -- when _first_orbit_push()
    calls _place() more than once, each call's clouds are anchored to that
    call's own (possibly pre-push) placement, and only the final call's map
    is the one the caller keeps.
    """
    m = SystemMap(system=s.name, generated={"tool": "gen_system_maps"})

    star_class, color = _star_class_and_color(s, star)
    m.bodies.append(Body(
        name=s.name, display_name=s.name, radius_gu=sun_radius,
        position_gu=(0.0, 0.0, 0.0), orbits=None,
        appearance=Appearance(kind="nif", model="", star_class=star_class, color=color),
        owner_region=None))

    ordered = _ordered(s)
    centres = _orbital_centres(ordered, first_orbit, t)
    for index, region in enumerate(ordered):
        centre = centres[index]
        primary, companions = _split(region)

        if primary is None:
            m.regions.append(Region(set_name=region.set_name, anchor_gu=centre,
                                    radius_gu=region.content_extent_gu + t.region_margin_gu,
                                    body_names=[], nebula=region.nebula))
            continue

        placed = []
        members = []

        primary_radius = primary.radius_gu * t.planet_radius_scale
        primary_body = Body(
            name=primary.name, display_name=primary.name,
            radius_gu=primary_radius, position_gu=centre, orbits=s.name,
            appearance=Appearance(kind="nif", model=primary.model),
            owner_region=region.set_name)
        m.bodies.append(primary_body)
        placed.append(primary.name)
        members.append(primary_body)

        for j, c in enumerate(companions):
            radius = c.radius_gu * t.moon_radius_scale
            # Keep each moon's original bearing from the primary, at a distance
            # scaled to the new primary radius.
            direction = _unit(_sub(c.offset_gu, primary.offset_gu))
            distance = primary_radius * (t.moon_first_orbit_factor
                                         + t.moon_orbit_step_factor * j)
            companion_body = Body(
                name=c.name, display_name=c.name, radius_gu=radius,
                position_gu=_add(centre, _scale(direction, distance)),
                orbits=primary.name,
                appearance=Appearance(kind="nif", model=c.model),
                owner_region=region.set_name)
            m.bodies.append(companion_body)
            placed.append(c.name)
            members.append(companion_body)

        # The anchor: the group's centroid, displaced back along the ORIGINAL
        # viewing direction by a standoff scaled to the new primary radius.
        # With one body the centroid IS the primary, so the primary's bearing
        # from the anchor is exactly the bearing BC gave it. With companions the
        # centroid shifts and the bearing is approximate -- which is the point:
        # "anchor between the two" frames the group, not just the planet.
        #
        # `members` holds the Body objects just created above directly, NOT a
        # by-name lookup through m.body() -- moon names collide across regions
        # (e.g. "Moon 1" appears in both Geble3 and Geble4), and m.body()
        # returns the first match in the whole map, which silently pulled in
        # a companion from a DIFFERENT region's group and blew up the anchor.
        view = _unit(_sub(primary.offset_gu, region.player_start_gu))
        centroid = tuple(
            sum(b.position_gu[axis] for b in members) / len(members) for axis in range(3))
        standoff = _standoff_factor(primary, region, t) * primary_radius
        anchor = _sub(centroid, _scale(view, standoff))

        # Pins: reposition a body to anchor + offset AFTER the anchor above is
        # computed from the pre-pin centroid, and do not recompute the anchor
        # afterwards. Moving a pinned body shifts the centroid, which would
        # shift the anchor, which would move the body again -- a fixed-point
        # problem. One pass is stable and sufficient: the centroid shift only
        # nudges this region's framing, while the pin itself ends up exact,
        # which is what validate()'s pin-respected rule checks. A pin naming a
        # region or body that does not exist here is ignored, silently --
        # validate() already reports all four malformed-pin cases, and
        # diagnosing in two places invites them to disagree about one map.
        for key, offset in pins.items():
            if not isinstance(key, str) or "/" not in key:
                continue
            pin_region, pin_body = key.split("/", 1)
            if pin_region != region.set_name:
                continue
            for b in members:
                if b.name == pin_body:
                    b.position_gu = _add(anchor, tuple(offset))
                    break

        reach = max(
            _norm(_sub(b.position_gu, anchor)) + b.radius_gu for b in members)
        m.regions.append(Region(
            set_name=region.set_name, anchor_gu=anchor,
            radius_gu=max(reach, region.content_extent_gu) + t.region_margin_gu,
            body_names=placed, nebula=region.nebula))

    # Built here, after every region's anchor above is final -- never earlier,
    # and never re-derived anywhere else.
    m.clouds = _build_clouds(m, cloud)

    return m


def layout(s, tuning: LayoutTuning | None = None, pins=None, star=None,
           cloud=None) -> SystemMap:
    t = tuning or LayoutTuning()
    pins = pins or {}
    _push, m = _first_orbit_push(s, t, pins, star, cloud)
    return m
