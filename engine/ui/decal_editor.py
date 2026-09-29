"""Pure-maths decal-placement editor for the Ship Property Viewer's Decals
pane. No GL or CEF imports — see
docs/superpowers/specs/2026-09-28-spv-decal-editing-design.md §3.

A `Placement` mirrors one `decals.json` entry: a ship-body-frame projector
box. `origin` is where mask corner (0, 0) sits; `u_axis` spans the mask
width (image right); `v_axis` spans the mask height (image DOWN); `normal`
is the outward-facing direction; `depth` is the slab half-thickness.

Chirality: a decal reads correctly from outside the hull iff
`(u_axis x v_axis) . normal < 0` (image-right x image-down points INTO the
surface). `place_at_hit` and `reposition` both construct their axes so this
holds by derivation, not by a post-hoc branch — see the module docstring of
`_place_axes` below.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Dict, Iterable, Optional, Tuple

Vec3 = Tuple[float, float, float]


# ---------------------------------------------------------------------------
# Vector helpers (plain tuples, no numpy — project convention, mirrors
# engine/ui/ship_property_viewer.py's _sub/_add/_scale/_cross/_dot/_norm).
# ---------------------------------------------------------------------------

def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _mag(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vec3, what: str = "vector") -> Vec3:
    """Unit vector along `a`. Raises ValueError (never returns NaN) if `a`
    is (numerically) the zero vector."""
    m = _mag(a)
    if m < 1e-9:
        raise ValueError(f"{what} has zero length")
    return _scale(a, 1.0 / m)


def _project_onto_plane(v: Vec3, n: Vec3) -> Vec3:
    """`v` with its component along unit vector `n` removed."""
    return _sub(v, _scale(n, _dot(v, n)))


def _projected_up(forward: Vec3, up: Vec3, n: Vec3) -> Vec3:
    """`forward` projected onto the plane perpendicular to unit `n`,
    normalised; falls back to `up` projected the same way if `forward`'s
    projection is (near-)degenerate (forward ~parallel to `n` — e.g. a hit
    on the bow or stern). Raises ValueError if both are degenerate."""
    proj = _project_onto_plane(forward, n)
    if _mag(proj) < 1e-3:
        proj = _project_onto_plane(up, n)
    m = _mag(proj)
    if m < 1e-9:
        raise ValueError(
            "cannot determine an up direction: ship_forward and ship_up "
            "are both parallel to the normal")
    return _scale(proj, 1.0 / m)


def _rotate_about_axis(v: Vec3, axis: Vec3, theta: float) -> Vec3:
    """Rodrigues' rotation of `v` about unit `axis` by `theta` radians,
    right-hand rule. Assumes `v` is perpendicular to `axis` (true of every
    u_axis/v_axis this module produces), which drops the `axis * (axis.v)`
    term of the general formula."""
    c, s = math.cos(theta), math.sin(theta)
    return _add(_scale(v, c), _scale(_cross(axis, v), s))


def _signed_angle(a: Vec3, b: Vec3, axis: Vec3) -> float:
    """Signed angle (radians) from unit vector `a` to unit vector `b`,
    both perpendicular to unit `axis`, right-hand rule about `axis`."""
    return math.atan2(_dot(_cross(a, b), axis), _dot(a, b))


def _place_axes(up_s: Vec3, n: Vec3) -> Tuple[Vec3, Vec3]:
    """(u_hat, v_hat): the unrolled, chirality-correct unit axes for a
    decal whose "up" (lettering top) is `up_s` and whose outward normal is
    `n`. v_hat = -up_s ("image down" is the opposite of "up"). u_hat is
    derived, not chosen: u_hat = normalise(up_s x n).

    Chirality proof: with up_s, n orthonormal, (up_s x n) x up_s reduces
    (vector triple product, up_s.n = 0, up_s.up_s = 1) to n, so
    u_hat x v_hat = normalise(up_s x n) x (-up_s) = -n, giving
    (u_hat x v_hat).n = -1 < 0 — chirality holds for ANY orthonormal
    (up_s, n), with no sign branch needed."""
    v_hat = _scale(up_s, -1.0)
    u_hat = _normalize(_cross(up_s, n), "u axis")
    return u_hat, v_hat


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Placement:
    """Mirrors one `decals.json` entry (`name` is the outer JSON key, not a
    field of the entry itself — see `to_json_entry`/`from_json_entry`).

    `mask` is the optional per-placement mask override (spec S2.4a): the
    filename stem of the PNG this placement projects, when it differs from
    `name` — several placements can share one mask this way. `""` means
    "use `name`"; read it through `mask_of`, never `p.mask` directly."""
    name: str
    origin: Vec3
    u_axis: Vec3
    v_axis: Vec3
    normal: Vec3
    depth: float
    shape: str = ""
    mask: str = ""


def place_at_hit(name: str, hit_point: Vec3, hit_normal: Vec3,
                  ship_forward: Vec3, ship_up: Vec3, ship_radius: float,
                  mask_aspect: float) -> Placement:
    """New decal centred on `hit_point`, facing `hit_normal`, sized off
    `ship_radius` (width = 0.25 * radius; height = width / mask_aspect;
    depth = 0.05 * width). The lettering's top points along `ship_forward`
    projected onto the plane perpendicular to the normal (falling back to
    `ship_up` near the bow/stern where forward is ~parallel to the
    normal)."""
    if ship_radius <= 0.0:
        raise ValueError("ship_radius must be positive")
    if mask_aspect <= 0.0:
        raise ValueError("mask_aspect must be positive")
    n = _normalize(hit_normal, "hit_normal")
    up_s = _projected_up(ship_forward, ship_up, n)
    u_hat, v_hat = _place_axes(up_s, n)

    width_ = 0.25 * ship_radius
    height_ = width_ / mask_aspect
    depth = 0.05 * width_

    u_axis = _scale(u_hat, width_)
    v_axis = _scale(v_hat, height_)
    origin = _sub(hit_point, _add(_scale(u_axis, 0.5), _scale(v_axis, 0.5)))
    return Placement(name=name, origin=origin, u_axis=u_axis, v_axis=v_axis,
                      normal=n, depth=depth, shape="")


def reposition(p: Placement, hit_point: Vec3, hit_normal: Vec3,
               ship_forward: Vec3, ship_up: Vec3) -> Placement:
    """Re-seat `p`'s centre and normal onto a new hit, keeping its width,
    height and depth. `ship_forward`/`ship_up` are needed (beyond the plan
    brief's 3-argument sketch) because the roll is defined relative to the
    projected ship "up", and that reference direction rotates with the
    normal — this function must recompute it at the new normal exactly as
    `place_at_hit` does, then re-apply the placement's *old* roll angle
    about the *new* normal so the decal doesn't silently re-level itself
    every time the mouse re-seats it.

    Both the OLD roll read and the NEW baseline use the same
    `_projected_up` fallback (`ship_up` when forward is ~parallel to the
    relevant normal) — a decal placed at the bow via `place_at_hit`'s
    fallback has to be repositionable onto an ordinary normal (and back)
    without `roll_angle` raising on the old, forward-parallel normal."""
    n = _normalize(hit_normal, "hit_normal")
    old_roll = roll_angle(p, ship_forward, ship_up)
    up_s = _projected_up(ship_forward, ship_up, n)
    u_hat0, v_hat0 = _place_axes(up_s, n)
    u_hat = _rotate_about_axis(u_hat0, n, old_roll)
    v_hat = _rotate_about_axis(v_hat0, n, old_roll)

    width_ = _mag(p.u_axis)
    height_ = _mag(p.v_axis)
    u_axis = _scale(u_hat, width_)
    v_axis = _scale(v_hat, height_)
    origin = _sub(hit_point, _add(_scale(u_axis, 0.5), _scale(v_axis, 0.5)))
    return replace(p, origin=origin, u_axis=u_axis, v_axis=v_axis, normal=n)


def move_uv(p: Placement, du: float, dv: float) -> Placement:
    """Translate `p` by `du`/`dv` model units along its own unit u/v
    directions. u_axis, v_axis, normal and depth are unchanged."""
    u_hat = _normalize(p.u_axis, "u_axis")
    v_hat = _normalize(p.v_axis, "v_axis")
    origin = _add(p.origin, _add(_scale(u_hat, du), _scale(v_hat, dv)))
    return replace(p, origin=origin)


def roll(p: Placement, radians: float) -> Placement:
    """Rotate `p`'s u_axis/v_axis about its normal by `radians`
    (right-hand rule), keeping the centre fixed."""
    axis = _normalize(p.normal, "normal")
    c = centre(p)
    u_axis = _rotate_about_axis(p.u_axis, axis, radians)
    v_axis = _rotate_about_axis(p.v_axis, axis, radians)
    origin = _sub(c, _add(_scale(u_axis, 0.5), _scale(v_axis, 0.5)))
    return replace(p, origin=origin, u_axis=u_axis, v_axis=v_axis)


def scale(p: Placement, factor: float) -> Placement:
    """Uniform scale of `p` about its centre (aspect preserved). `depth`
    scales with it too, since it is a spatial extent in the same units as
    u_axis/v_axis, not an independent field."""
    if factor <= 0.0:
        raise ValueError("factor must be positive")
    c = centre(p)
    u_axis = _scale(p.u_axis, factor)
    v_axis = _scale(p.v_axis, factor)
    origin = _sub(c, _add(_scale(u_axis, 0.5), _scale(v_axis, 0.5)))
    return replace(p, origin=origin, u_axis=u_axis, v_axis=v_axis,
                   depth=p.depth * factor)


def set_width(p: Placement, width: float, mask_aspect: float) -> Placement:
    """Resize `p` to `width` (height = width / mask_aspect) about its
    centre, keeping roll and normal. `depth` is left as-is — it is a
    separate numeric field in the panel, not derived from width here
    (unlike `place_at_hit`, which only sets it once at creation)."""
    if width <= 0.0:
        raise ValueError("width must be positive")
    if mask_aspect <= 0.0:
        raise ValueError("mask_aspect must be positive")
    u_hat = _normalize(p.u_axis, "u_axis")
    v_hat = _normalize(p.v_axis, "v_axis")
    c = centre(p)
    u_axis = _scale(u_hat, width)
    v_axis = _scale(v_hat, width / mask_aspect)
    origin = _sub(c, _add(_scale(u_axis, 0.5), _scale(v_axis, 0.5)))
    return replace(p, origin=origin, u_axis=u_axis, v_axis=v_axis)


def mask_of(p: Placement) -> str:
    """The mask filename stem `p` actually projects: `p.mask` when set,
    else `p.name` — the single place that resolves the S2.4a "several
    placements share a mask" default so no caller re-derives it."""
    return p.mask or p.name


def centre(p: Placement) -> Vec3:
    return _add(p.origin, _add(_scale(p.u_axis, 0.5), _scale(p.v_axis, 0.5)))


def set_centre(p: Placement, c: Vec3) -> Placement:
    """Move `p` so its centre is `c`. Axes, normal and depth unchanged."""
    return replace(p, origin=_sub(tuple(c), _add(_scale(p.u_axis, 0.5),
                                                 _scale(p.v_axis, 0.5))))


def width(p: Placement) -> float:
    return _mag(p.u_axis)


def roll_angle(p: Placement, ship_forward: Vec3,
                ship_up: Optional[Vec3] = None) -> float:
    """Signed angle (radians) between -v_hat (the decal's own "up") and a
    reference "up" direction, about the normal. Zero when the decal is
    unrolled (its "up" points exactly along the reference).

    The reference is `ship_forward` projected onto the plane perpendicular
    to the normal. If `ship_up` is given, a near-degenerate forward
    projection falls back to `ship_up` the same way `_projected_up` does
    (a bow/stern decal has normal ~parallel to ship_forward) — pass it
    whenever `p` might have been created or repositioned through that
    fallback, or this raises ValueError instead of silently reading
    garbage. Omitting `ship_up` keeps the strict forward-only behaviour
    for callers that know their decal isn't a fallback case."""
    n = _normalize(p.normal, "normal")
    if ship_up is not None:
        up_ref = _projected_up(ship_forward, ship_up, n)
    else:
        proj = _project_onto_plane(ship_forward, n)
        m = _mag(proj)
        if m < 1e-9:
            raise ValueError(
                "ship_forward is parallel to the decal normal: roll angle "
                "is undefined (pass ship_up for the fallback reference)")
        up_ref = _scale(proj, 1.0 / m)
    decal_up = _normalize(_scale(p.v_axis, -1.0), "v_axis")
    return _signed_angle(up_ref, decal_up, n)


def chirality_ok(p: Placement) -> bool:
    """True iff `p` reads correctly from outside the hull:
    (u_axis x v_axis) . normal < 0."""
    return _dot(_cross(p.u_axis, p.v_axis), p.normal) < 0.0


# ---------------------------------------------------------------------------
# JSON round-trip and name validation
# ---------------------------------------------------------------------------

def to_json_entry(p: Placement) -> Dict:
    """One `decals.json` "decals" entry (the value under `p.name`, not
    including the name itself). `shape` is omitted when empty. `mask` is
    omitted whenever it is empty OR equal to `p.name` — both mean "use
    `p.name`" (spec S2.4a), so an untouched placement round-trips without
    ever gaining a redundant `"mask"` key."""
    entry: Dict = {}
    if p.mask and p.mask != p.name:
        entry["mask"] = p.mask
    if p.shape:
        entry["shape"] = p.shape
    entry["origin"] = list(p.origin)
    entry["u_axis"] = list(p.u_axis)
    entry["v_axis"] = list(p.v_axis)
    entry["normal"] = list(p.normal)
    entry["depth"] = p.depth
    return entry


def _is_number(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def _json_vec3(d: Dict, key: str) -> Vec3:
    v = d[key]
    if not isinstance(v, (list, tuple)) or len(v) != 3 \
            or not all(_is_number(c) for c in v):
        raise ValueError(f"{key!r} is not three finite numbers")
    return tuple(v)


def from_json_entry(name: str, d: Dict) -> Placement:
    """Inverse of `to_json_entry`. A missing OR null `shape` reads as ""
    (unrestricted), exactly as `hull_decals.decals_for` treats it in game.
    A missing OR null `mask` likewise reads as "" (meaning "use `name`" —
    see `mask_of`).

    Strict: each vector must be three finite numbers, `depth` a finite
    number, and `shape`/`mask` each a string (or absent/null); anything
    else raises ValueError (KeyError for a missing field, TypeError for a
    non-dict) -- an entry the editor maths cannot work with is not a
    Placement. Values are NOT coerced (an int stays an int), so an
    untouched entry is written back as it was read."""
    shape = d.get("shape")
    if shape is not None and not isinstance(shape, str):
        raise ValueError("'shape' is not a string")
    mask = d.get("mask")
    if mask is not None and not isinstance(mask, str):
        raise ValueError("'mask' is not a string")
    if mask and valid_name(mask, ()) is not None:
        raise ValueError("'mask' is not a valid filename stem")
    depth = d["depth"]
    if not _is_number(depth):
        raise ValueError("'depth' is not a finite number")
    return Placement(
        name=name,
        origin=_json_vec3(d, "origin"),
        u_axis=_json_vec3(d, "u_axis"),
        v_axis=_json_vec3(d, "v_axis"),
        normal=_json_vec3(d, "normal"),
        depth=depth,
        shape="" if shape is None else shape,
        mask="" if mask is None else mask,
    )


_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def valid_name(name: str, existing: Iterable[str]) -> Optional[str]:
    """None if `name` is a usable, not-already-taken decal name; else an
    error string. Rejects empty names, path separators, `.`/`..` and any
    character outside [A-Za-z0-9_-] (one check covers all of those — none
    of them is in the allowed set), and duplicates existing names
    case-insensitively."""
    if not name:
        return "name cannot be empty"
    if not _VALID_NAME_RE.match(name):
        return "name may only contain letters, digits, '_' and '-'"
    lname = name.lower()
    for e in existing:
        if e.lower() == lname:
            return f"a decal named {name!r} already exists"
    return None
