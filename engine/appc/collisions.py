"""Per-frame collision detection + response for ships and space bodies.

Reuses the weapons-system collision/damage primitives: a sphere-overlap
broadphase, combat.apply_hit for impact damage (A), and a mass-weighted
impulse injected into a decaying per-object _collision_velocity overlay (B).
No rigid-body physics engine — the kinematic integrators are untouched; the
overlay is applied and decayed here, once per render frame, for every
collidable.

Spec: docs/superpowers/specs/2026-06-11-collision-response-design.md
"""
import math
from dataclasses import dataclass, replace

from engine.appc.math import TGPoint3
from engine.systems.frames import shifted as _shifted
from engine.appc.warp_state import is_ship_warping

# -- Tuning constants (single home; see spec §9) --
COLLISION_RESTITUTION = 0.2      # bounciness e; mostly inelastic crunch
COLLISION_DAMAGE_COEFF = 5.0     # KE -> hull-damage-points; calibrated against
                                 # Galaxy (mass 120, hull 15000, impulse 6.3 GU/s):
                                 # full-impulse planet ram ~79% hull (near-fatal),
                                 # head-on both-full ram >100% (kill), dock-bump
                                 # trivial. Tune in-engine by feel. See spec §9.
COLLISION_DECAY_TAU = 0.5        # collision-velocity overlay decay time constant (s)
COLLISION_FALLBACK_MASS = 1.0e4  # nominal mass for a ship reporting GetMass()==0
COLLISION_GRIND_COEFF = 2.5      # sustained-contact (abrasion) damage, in hull
                                 # points per (reduced-mass unit x GU of slip).
                                 # Calibrated so a Galaxy-class pair (mu = 60)
                                 # grinding at 0.5 GU/s of contact slip crosses
                                 # scenegraph::kHullCarveStrengthIso (150 --
                                 # the first visible hole) after ~2 s, and a
                                 # docking nudge at 0.05 GU/s takes ~20 s to do
                                 # the same. Distinct from COLLISION_DAMAGE_
                                 # COEFF because this is a work RATE (linear in
                                 # slip speed, scaled by dt), not the quadratic
                                 # kinetic energy of an impact.
COLLISION_RADIUS_SCALE = 0.8     # effective collision boundary as a fraction of
                                 # rA+rB: objects close 20% of the bounding-
                                 # sphere gap before a hit registers, compensating
                                 # for hulls sitting well inside their generous
                                 # bounding spheres (e.g. Galaxy saucer+nacelles)

# Broadphase spatial hash (see _candidate_pairs). Floor cell size in GU, so a
# set of tiny bodies (rock chunks) doesn't degenerate into a huge number of
# tiny cells; real conservativeness comes from 2x the largest radius in the
# set, which is always >= the largest overlap reach any pair in that set can
# have (see _candidate_pairs' docstring for the bound argument).
kBroadphaseMinCellGU = 4.0
_BROADPHASE = True

# Scuff decal size band (GU). The decal radius is the contact chord
# sqrt(2 * R_small * pen) clamped to this band; it is VISUAL ONLY and never
# feeds apply_hit's splash radius (which sets the subsystem catchment).
# Spec: docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md §3
# Band tightened after the 2026-09-20 live pass: [0.5, 4.0] read as a stamp
# bigger than a saucer (a Galaxy is ~±1.8 GU long) and, since ship-piece
# contacts chord to ~0.1-0.3 GU, the old minimum clamped every real hit UP.
SCUFF_RADIUS_MIN_GU = 0.1
SCUFF_RADIUS_MAX_GU = 0.5


def scuff_radius_gu(r_small: float, pen: float) -> float:
    """Chord of two overlapping spheres, from the smaller radius and the
    overlap depth, clamped to [SCUFF_RADIUS_MIN_GU, SCUFF_RADIUS_MAX_GU]."""
    chord = math.sqrt(max(0.0, 2.0 * r_small * pen))
    return min(SCUFF_RADIUS_MAX_GU, max(SCUFF_RADIUS_MIN_GU, chord))


# How far OUTSIDE a ship's contact boundary the hull trace starts (GU). Piece
# spheres sit at most a fraction of a GU outside the true hull, so 1 GU is
# safely clear of the mesh while staying far inside the other ship's reach.
SCUFF_TRACE_STANDOFF_GU = 1.0


def _trace_own_hull(ship_instances, body: "_Body", boundary, n_out, reach: float):
    """Refine a collision contact onto `body`'s OWN mesh. Returns (point, normal).

    `boundary` is this body's contact-boundary point facing the other ship
    (its piece surface, within piece slack of the real hull) and `n_out` the
    unit contact normal pointing OUT of this body. The ray starts
    SCUFF_TRACE_STANDOFF_GU outside the boundary and runs back INTO the body
    for `reach`, so it crosses the hull where the pieces actually touch.

    Live 2026-09-21: the trace used to start at the OTHER ship's body centre
    along the piece normal. A wing-tip-vs-saucer contact then traced from the
    warbird's centre, hundreds of model units from that wing, missed, and fell
    through to _resolve_hit_point's whole-body sphere entry -- ~1 GU off the
    hull on a 2x-inflated root sphere -- so a ship-sized scuff touched no
    fragment. A miss now anchors at the boundary itself (sphere_fallback off).
    """
    from engine.appc.combat import _resolve_hit_point
    s = SCUFF_TRACE_STANDOFF_GU
    origin = TGPoint3(boundary.x + n_out.x * s,
                      boundary.y + n_out.y * s,
                      boundary.z + n_out.z * s)
    into = TGPoint3(-n_out.x, -n_out.y, -n_out.z)
    pt, mesh_n = _resolve_hit_point(ship_instances, body.obj, origin, into,
                                    s + reach, boundary, sphere_fallback=False)
    return pt, (mesh_n if mesh_n is not None else n_out)


def world_radius(obj) -> float:
    """An object's bounding radius as DRAWN, in GU: GetRadius() x GetScale().

    GetRadius() is SDK surface and stays UNSCALED -- missions read it, and
    the host sets it from the model at GetScale() == 1 -- but every ship and
    planet draws at GetRadius() x GetScale() (_ship_world_matrix /
    _apply_live_world_transform). E1M2 scales its asteroids 3-8.5x, so a raw
    GetRadius() collision let the player fly most of the way into a rock.

    A DebrisChunk is the exception: its GetRadius() is already its world size,
    and its GetScale() is the render scale of a SHARED model, not a size
    factor. The scale is read through the class (TGObject.__getattr__ vends a
    truthy _Stub for any unknown name) and a non-positive or unreadable scale
    counts as 1."""
    from engine.appc.debris_chunk import DebrisChunk
    r = float(obj.GetRadius())
    if isinstance(obj, DebrisChunk):
        return r
    fn = getattr(type(obj), "GetScale", None)
    if fn is None:
        return r
    try:
        s = float(fn(obj))
    except (TypeError, ValueError):
        return r
    return r * s if s > 0.0 and math.isfinite(s) else r


def _boundary_shrink(obj) -> float:
    """COLLISION_RADIUS_SCALE for anything shaped like a ship -- its hull sits
    well inside the bounding sphere -- and 1.0 for a rock, whose sphere IS
    its surface (rock-class final review)."""
    from engine.rocks.rock import is_rock
    return 1.0 if is_rock(obj) else COLLISION_RADIUS_SCALE


def contact_radius(obj) -> float:
    """The radius a collision actually registers at: world_radius x the
    object's boundary shrink. What _respond_pair's broad phase tests."""
    return world_radius(obj) * _boundary_shrink(obj)


def ghost_peer_gone(obj) -> bool:
    """Whether a ghosted pair member has left the world: a DebrisChunk no
    longer live, or anything dead or out of every set. Class-level lookups
    (TGObject.__getattr__ vends a truthy _Stub for unknown names)."""
    from engine.appc import debris_chunk
    if obj is None:
        return True
    if isinstance(obj, debris_chunk.DebrisChunk):
        return not any(c is obj for c in debris_chunk.live())
    dead = getattr(type(obj), "IsDead", None)
    from engine import dev_mode
    try:
        if dead is not None and dead(obj):
            return True
    except Exception as e:
        dev_mode.log_swallowed("ghost peer IsDead", e)
    from engine.systems import frames
    return frames.containing_set(obj) is None


def spheres_clear(a, b, margin: float) -> bool:
    """Whether `a` and `b`'s CONTACT spheres (contact_radius, what
    _respond_pair tests) are at least `margin` GU apart, compared in one
    frame. A pair in no common frame cannot collide, so it counts as clear."""
    from engine.systems import frames
    off = frames.offset_between(frames.containing_set(a), frames.containing_set(b))
    if off is None:
        return True
    pa = a.GetWorldLocation()
    pb = _shifted(b.GetWorldLocation(), off)
    dx, dy, dz = pb.x - pa.x, pb.y - pa.y, pb.z - pa.z
    reach = contact_radius(a) + contact_radius(b) + float(margin)
    return dx * dx + dy * dy + dz * dz >= reach * reach


@dataclass
class _Body:
    obj: object
    center: TGPoint3
    radius: float        # world_radius: GetRadius() x GetScale(). The
                         # broadphase buckets on this (never smaller than
                         # the contact radius, so it stays conservative).
    inv_mass: float
    is_movable: bool
    velocity: TGPoint3   # world thrust velocity + current overlay
    angular: TGPoint3    # WORLD-frame angular velocity (rad/s); zero for
                         # immovables. Body-frame at rest in ShipClass -- see
                         # _resolve_body for the rotation into world space.
    shrink: float = COLLISION_RADIUS_SCALE   # see _boundary_shrink

    @property
    def contact(self) -> float:
        """The contact radius: radius x shrink."""
        return self.radius * self.shrink


# b_offset for a pair in ONE set: B is already in A's coordinates.
_NO_OFFSET = (0.0, 0.0, 0.0)


# A pair across two regions of one star system (system-frames spec §1) is
# compared in A's set-local coordinates: B's positions are read with sign=+1
# (B-local -> A-local, frames.offset_between's convention), and a point handed
# back to B's own side -- a ray trace against B's mesh, a hit point on B's
# hull, A's location queried against B's pieces -- with sign=-1. A zero offset
# returns the point itself, so a same-set pair runs exactly today's arithmetic.
# The helper is frames.shifted, imported above as _shifted.


def _overlay_vec(obj):
    """Read-only: the object's collision overlay, or None if never collided.

    Must use obj.__dict__ lookup rather than getattr(obj, …, None) because
    TGObject.__getattr__ returns a truthy _Stub for any unknown attribute,
    which would prevent the None sentinel from ever being returned.
    """
    return obj.__dict__.get("_collision_velocity")


def _collisions_enabled(obj):
    """Whether this object takes part in collision resolution.

    Two independent gates, which COMPOSE (neither overrides the other):

    1. The SDK's per-object DamageableObject.SetCollisionsOn flag; default True.
       Same obj.__dict__ pattern as _overlay_vec: the flag is only ever set as
       an instance attribute, and getattr would hit TGObject.__getattr__'s
       truthy _Stub on objects that never had it set (e.g. Planet).

    2. Engine warp suppression: a ship in warp is non-collidable. Our flythrough
       flies the ship through populated sets at 100x max speed, where a contact
       is instantly lethal (_ke_damage is quadratic in closing speed) and the
       sphere broadphase can tunnel clean through a hull. BC never had this
       problem — it teleports the warping ship into an isolated warp set — so
       suppression restores BC's outcome, not a new behaviour.
       warp_state.is_ship_warping is isinstance(ShipClass)-guarded: do not
       inline it as a getattr probe, or every planet becomes non-collidable.
    """
    if not obj.__dict__.get("_collisions_on", True):
        return False
    return not is_ship_warping(obj)


_EMPTY_DISABLED = frozenset()


def _collision_disabled_ids(obj):
    """The set of peer ObjIDs this object has disabled collisions with via
    DamageableObject.EnableCollisionsWith, or an empty set. obj.__dict__ lookup
    (not getattr) to dodge TGObject.__getattr__'s truthy _Stub."""
    return obj.__dict__.get("_collision_disabled_ids", _EMPTY_DISABLED)


def _ensure_overlay(obj):
    """Get-or-create the mutable overlay vector (called only on impulse inject)."""
    cv = obj.__dict__.get("_collision_velocity")
    if cv is None:
        cv = TGPoint3(0.0, 0.0, 0.0)
        obj._collision_velocity = cv
    return cv


def _resolve_body(obj, position: TGPoint3 = None) -> "_Body":
    """Snapshot an object into a _Body. Ships are movable (inverse mass from
    GetMass, fallback when zero); planets/moons/suns are immovable. Velocity
    is the world thrust velocity plus any active collision overlay.

    `position`, when given, is a pre-fetched world location (from a bulk
    get_positions() call in resolve_collisions) — avoids one boundary
    crossing per object. Defaults to obj.GetWorldLocation() so direct callers
    (unit tests, collision_avoidance.py) are unaffected."""
    from engine.appc.ships import ShipClass
    from engine.appc.debris_chunk import DebrisChunk
    center = position if position is not None else obj.GetWorldLocation()
    radius = world_radius(obj)
    if isinstance(obj, (ShipClass, DebrisChunk)) and not obj.IsImmobile():
        m = obj.GetMass()
        if m <= 0.0:
            m = COLLISION_FALLBACK_MASS
        inv_mass = 1.0 / m
        movable = True
        v = obj.GetVelocity()
        # Contact-point velocity is v_cm + omega x r, and omega was missing
        # entirely: a ship spinning against another hull reported (0, 0, 0)
        # and never registered a collision at all. `_current_angular_velocity`
        # is BODY frame -- ship_motion._integrate_rotation post-multiplies the
        # delta (R . D), per CLAUDE.md's rotation convention -- so it has to be
        # rotated into world space before it can be crossed with a world-space
        # contact arm. obj.__dict__ lookup, not getattr: TGObject.__getattr__
        # hands back a truthy _Stub for any unknown attribute, which would slip
        # a non-vector into the cross product.
        cav = obj.__dict__.get("_current_angular_velocity")
        if cav is not None and (cav.x or cav.y or cav.z):
            w = TGPoint3(cav.x, cav.y, cav.z)
            w.MultMatrixLeft(obj.GetWorldRotation())
        else:
            w = TGPoint3(0.0, 0.0, 0.0)
    else:
        # Planets/moons/suns AND immobile ships (SetStatic / SetStationary):
        # fixed anchors. inv_mass 0 + zero velocity means the mover takes the
        # full de-penetration and impulse, exactly as it does against a planet.
        inv_mass = 0.0
        movable = False
        v = TGPoint3(0.0, 0.0, 0.0)
        w = TGPoint3(0.0, 0.0, 0.0)
    cv = _overlay_vec(obj)
    if cv is not None:
        v = v + cv
    return _Body(obj, center, radius, inv_mass, movable, v, w,
                 _boundary_shrink(obj))


def _ke_damage(inv_sum: float, v_rel: float) -> float:
    """KE-of-closing-speed damage: COEFF * 0.5 * mu * v_rel**2, mu = 1/inv_sum.

    Precondition: inv_sum > 0 (at least one body must be movable). The
    pair-response caller gates two-immovable pairs out before reaching here.
    """
    assert inv_sum > 0.0, "inv_sum must be > 0; two immovable bodies cannot collide"
    mu = 1.0 / inv_sum
    return COLLISION_DAMAGE_COEFF * 0.5 * mu * v_rel * v_rel


def _deepest_piece_overlap(obj_a, obj_b, b_offset=_NO_OFFSET):
    """Narrow-phase the pair against their authored hull pieces.

    Returns:
      * ``None``  — at least one side has no pieces; caller keeps the broad
        phase. This is the fallback for planets, asteroids and anything whose
        model has not realized.
      * ``()``    — both sides have pieces and none of them overlap: NOT a
        collision, however much the model-wide bounds intersect. This is also
        what a cull that leaves one side empty means: pieces exist, none are
        in range.
      * ``(centre_a, radius_a, centre_b, radius_b)`` — the most deeply
        overlapping pair, i.e. the one whose surfaces interpenetrate furthest.
        Deepest rather than first so the contact normal describes the dominant
        contact when several pieces meet at once.

    `b_offset` puts B in A's set-local coordinates (see _shifted); every
    returned centre, B's included, is in A's frame.
    """
    from engine.appc.hull_bounds import has_hull_bounds, hull_spheres_near
    # "No pieces" and "no pieces NEAR" are different answers — the first falls
    # back to the broad phase, the second is a definitive miss — so the
    # has_hull_bounds check has to come before the cull, not be inferred from
    # an empty result.
    if not has_hull_bounds(obj_a) or not has_hull_bounds(obj_b):
        return None
    # Each side is culled against the other's model-wide bound before anything
    # is transformed into world space. world_radius (GetRadius x GetScale) is
    # the scaled AABB corner distance, comfortably larger than any real
    # reach, so the cull cannot drop a pair the loop below would have found.
    # The pieces themselves are cached at GetScale() == 1 and hull_bounds
    # multiplies centre and radius by the live GetScale(), so they are
    # already in the same scaled space.
    # B's location into A's frame for A's cull; A's into B's for B's cull.
    pieces_a = hull_spheres_near(obj_a, _shifted(obj_b.GetWorldLocation(), b_offset),
                                 world_radius(obj_b))
    if not pieces_a:
        return ()
    pieces_b = hull_spheres_near(obj_b, _shifted(obj_a.GetWorldLocation(), b_offset, -1.0),
                                 world_radius(obj_a))
    if not pieces_b:
        return ()
    if b_offset != _NO_OFFSET:
        # B's pieces come back in B's frame; compare them in A's.
        pieces_b = [(_shifted(cb, b_offset), rb) for cb, rb in pieces_b]

    best = None
    best_pen = 0.0
    for ca, ra in pieces_a:
        for cb, rb in pieces_b:
            ddx = cb.x - ca.x
            ddy = cb.y - ca.y
            ddz = cb.z - ca.z
            d2 = ddx * ddx + ddy * ddy + ddz * ddz
            reach = (ra + rb) * COLLISION_RADIUS_SCALE
            if d2 >= reach * reach:
                continue
            pen = reach - math.sqrt(d2)
            if best is None or pen > best_pen:
                best_pen = pen
                best = (ca, ra, cb, rb)
    return best if best is not None else ()


def _contact_point_velocity(body: "_Body", cx: float, cy: float, cz: float):
    """Rigid-body velocity of the material point at (cx, cy, cz):
    ``v_cm + omega x r``, with ``r`` the arm from the body's centre.

    Returns v_cm unchanged for a body with no angular velocity, so a
    non-rotating pair is arithmetically identical to the pre-omega code.
    """
    w = body.angular
    if not (w.x or w.y or w.z):
        return body.velocity.x, body.velocity.y, body.velocity.z
    rx, ry, rz = cx - body.center.x, cy - body.center.y, cz - body.center.z
    return (body.velocity.x + w.y * rz - w.z * ry,
            body.velocity.y + w.z * rx - w.x * rz,
            body.velocity.z + w.x * ry - w.y * rx)


def _grind_contact(a: "_Body", b: "_Body", cx, cy, cz, nx, ny, nz,
                   inv_sum: float, dt: float, ship_instances=None,
                   scuff_radius: float | None = None,
                   boundary_b=None, reach: float = 0.0,
                   b_offset=_NO_OFFSET) -> None:
    """Abrasion damage for a contact that is not closing.

    Physically this is friction work: force times sliding distance. We have no
    contact force, so reduced mass stands in for it, and the distance is the
    slip travelled this frame. Hence LINEAR in speed and scaled by dt -- unlike
    the impact channel, which is the quadratic kinetic energy of a collision.

    The speed used is the contact-point relative velocity with the RECEDING
    part of its normal component removed: sliding counts, and so does a part
    swinging inward under rotation, but two hulls bouncing apart do not get
    charged for separating.

    Emits no event and applies no impulse -- see the caller. Routes as
    weapon_type "collision" with the slip direction as the scuff tangent.
    `scuff_radius` is the decal's visual size in GU; None (the default) is
    passed straight through to `apply_hit`'s `decal_radius`, which then falls
    back to the weapon radius -- NOT a radius-0 decal.

    Every position here -- the contact, `boundary_b`, and `b.center` -- is in
    A's set-local frame (the caller passes B's A-frame view). `b_offset` is
    only used to hand B's trace back to B's own frame.
    """
    if not (dt > 0.0):
        return
    ax, ay, az = _contact_point_velocity(a, cx, cy, cz)
    bx, by, bz = _contact_point_velocity(b, cx, cy, cz)
    rvx, rvy, rvz = bx - ax, by - ay, bz - az
    v_n = rvx * nx + rvy * ny + rvz * nz
    tx, ty, tz = rvx - v_n * nx, rvy - v_n * ny, rvz - v_n * nz
    approach = -v_n if v_n < 0.0 else 0.0
    slip = math.sqrt(tx * tx + ty * ty + tz * tz + approach * approach)
    if slip <= 0.0:
        return
    mu = 1.0 / inv_sum
    damage = COLLISION_GRIND_COEFF * mu * slip * dt
    if damage <= 0.0:
        return

    # Scuff tangent: the slip direction itself, sign per ship (each hull's
    # scratch runs the way the OTHER hull moved across it). No slip (pure
    # approach, no tangential component) -> None; the ring derives one.
    tlen = math.sqrt(tx * tx + ty * ty + tz * tz)
    if tlen > 1e-6:
        tan_a = TGPoint3(tx / tlen, ty / tlen, tz / tlen)
        tan_b = TGPoint3(-tx / tlen, -ty / tlen, -tz / tlen)
    else:
        tan_a = tan_b = None

    # Land each ship's abrasion on ITS OWN MESH, exactly as the impact path
    # does: trace from just outside this ship's contact boundary back into it
    # (_trace_own_hull) and carve at the mesh surface with the MESH normal;
    # a miss anchors at the boundary. BC bounding spheres are 5-22x too loose
    # (docs/engine and hull_bounds.py), so anything deposited at a sphere
    # surface sits off the hull entirely, and the centre-to-centre line is
    # not the local surface normal -- the scoop would be both mis-placed and
    # mis-oriented, which reads live as a hole with nothing behind it.
    from engine.appc.combat import apply_hit
    contact = TGPoint3(cx, cy, cz)
    n_ab = TGPoint3(nx, ny, nz)
    n_ba = TGPoint3(-nx, -ny, -nz)
    if boundary_b is None:
        boundary_b = contact
    if a.is_movable:
        pt_a, n_a = _trace_own_hull(ship_instances, a, contact, n_ab, reach)
        apply_hit(a.obj, damage, pt_a, source=b.obj, normal=n_a,
                  ship_instances=ship_instances, weapon_type="collision",
                  hit_tangent=tan_a, decal_radius=scuff_radius, decal_dent=0.0,
                  bypass_shields=True)
    if b.is_movable:
        pt_b, n_b = _trace_own_hull(ship_instances, b,
                                    _shifted(boundary_b, b_offset, -1.0), n_ba, reach)
        apply_hit(b.obj, damage, pt_b, source=a.obj, normal=n_b,
                  ship_instances=ship_instances, weapon_type="collision",
                  hit_tangent=tan_b, decal_radius=scuff_radius, decal_dent=0.0,
                  bypass_shields=True)


def _respond_pair(a: "_Body", b: "_Body", ship_instances=None, dt: float = 0.0,
                  b_offset=_NO_OFFSET):
    """Resolve one body pair. On an approaching overlap: inject a
    mass-weighted impulse into each movable body's overlay, de-penetrate
    positions, and apply KE damage via combat.apply_hit. Returns the
    (a.obj, b.obj, contact_point, v_rel) tuple if they collided, else None.

    The `v_rel < 0` (approaching) gate is the debounce: once the impulse
    reverses relative velocity, later frames read receding and do nothing
    while the spheres still overlap (spec §5).

    `b_offset` is frames.offset_between(set of a, set of b): the pair maths
    runs in A's set-local coordinates, so every read of B's position adds it
    and everything handed back to B's own side (its hull trace, its hit
    point) subtracts it. The RETURNED contact is in A's frame; each
    ET_OBJECT_COLLISION event carries the point in its DESTINATION's own
    frame (see _emit_object_collision). Zero (the same set) takes today's
    path on the same objects."""
    if b_offset != _NO_OFFSET:
        b = replace(b, center=_shifted(b.center, b_offset))   # B, seen from A
    dx = b.center.x - a.center.x
    dy = b.center.y - a.center.y
    dz = b.center.z - a.center.z
    dist2 = dx * dx + dy * dy + dz * dz
    # Effective boundary is scaled below the raw bounding-sphere sum so hulls
    # visually close most of the gap before the hit registers (spec §4) --
    # per body: a rock's shrink is 1.0 (see _boundary_shrink).
    sum_r = a.contact + b.contact
    if dist2 >= sum_r * sum_r:
        return None
    dist = math.sqrt(dist2)
    if dist < 1e-9:
        return None  # concentric: degenerate normal, skip

    # NARROW PHASE. Everything above is a broad phase against one sphere round
    # each whole model, which for a BC hull is both generous (the AABB corner
    # distance) and unable to express concavity — a starbase's docking bay is a
    # void between structures. Responding on that alone made a ship that is
    # visibly clear of a station register a hit: hull ticking down while parked,
    # range readout at 0.00 km because the surface distance had gone negative.
    #
    # When BOTH sides carry authored per-shape bounds, re-run the test against
    # the pieces and take the deepest-overlapping pair as the real contact. One
    # side lacking them (planets, asteroids, anything unrealized) falls back to
    # the broad-phase answer: we cannot descend a hierarchy only one side has,
    # and failing open there would switch collisions off for most of the game.
    narrowed = _deepest_piece_overlap(a.obj, b.obj, b_offset)
    if narrowed is not None:
        if not narrowed:
            return None  # pieces exist on both sides and none of them touch
        pa, ra, pb, rb = narrowed
        ndx, ndy, ndz = pb.x - pa.x, pb.y - pa.y, pb.z - pa.z
        ndist = math.sqrt(ndx * ndx + ndy * ndy + ndz * ndz)
        if ndist < 1e-9:
            return None
        dist = ndist
        sum_r = ra + rb
        nx, ny, nz = ndx / ndist, ndy / ndist, ndz / ndist
        # Contact point: on the surface of A's overlapping piece, facing B.
        cx, cy, cz = pa.x + nx * ra, pa.y + ny * ra, pa.z + nz * ra
    else:
        nx, ny, nz = dx / dist, dy / dist, dz / dist
        eff_ra = a.contact
        cx, cy, cz = (a.center.x + nx * eff_ra,
                      a.center.y + ny * eff_ra,
                      a.center.z + nz * eff_ra)

    # Scuff decal size from the contact geometry (visual only; see scuff_radius_gu).
    if narrowed:
        r_small = min(ra, rb)
    else:
        r_small = min(a.contact, b.contact)
    pen = sum_r - dist
    scuff_r = scuff_radius_gu(r_small, pen)
    # Each ship's contact BOUNDARY point (its piece surface facing the other):
    # a's is the contact itself; b's sits `pen` back along the normal. These
    # are what the hull traces start from and fall back to (_trace_own_hull).
    # Deliberately NOT the whole-body sphere surface, which after the piece
    # narrow phase can sit ~1 GU off the hull.
    boundary_a = TGPoint3(cx, cy, cz)
    boundary_b = TGPoint3(cx - nx * pen, cy - ny * pen, cz - nz * pen)
    trace_reach = 2.0 * sum_r

    # Closing speed along the normal (negative = approaching). CENTRE-OF-MASS
    # velocity only, deliberately: this drives the impulse and the debounce,
    # and the impulse can only change LINEAR velocity. Feeding a rotating
    # body's contact-point velocity in here would re-fire the impulse every
    # frame -- nothing it does can reduce omega -- and fling the pair apart.
    rvx = b.velocity.x - a.velocity.x
    rvy = b.velocity.y - a.velocity.y
    rvz = b.velocity.z - a.velocity.z
    v_rel = rvx * nx + rvy * ny + rvz * nz

    # Slip direction for the scuff: relative velocity with its normal part
    # removed. Dead-on (no slip) -> None; the ring derives a perpendicular.
    tvx, tvy, tvz = rvx - v_rel * nx, rvy - v_rel * ny, rvz - v_rel * nz
    tlen = math.sqrt(tvx * tvx + tvy * tvy + tvz * tvz)
    if tlen > 1e-6:
        tan_a = TGPoint3(tvx / tlen, tvy / tlen, tvz / tlen)    # how b moves across a
        tan_b = TGPoint3(-tvx / tlen, -tvy / tlen, -tvz / tlen) # how a moves across b
    else:
        tan_a = tan_b = None

    inv_sum = a.inv_mass + b.inv_mass
    if inv_sum <= 0.0:
        return None  # two immovables

    if v_rel >= 0.0:
        # Receding or resting. No impulse, no de-penetration, and NO EVENT --
        # _emit_object_collision must stay on the impact path, because
        # MissionLib.FriendlyFireCollisionHandler turns one into a game over
        # and a grind would post it every frame.
        #
        # But contact with relative motion still abrades, which the bare
        # `return None` here missed: 120 frames of pressing into a hull
        # registered exactly ONE hit, because the first frame's impulse flips
        # the pair to receding and every later frame bailed. A ship grinding
        # by rotation never even got that, since omega was absent from the
        # velocity entirely.
        _grind_contact(a, b, cx, cy, cz, nx, ny, nz, inv_sum, dt,
                       ship_instances, scuff_r, boundary_b, trace_reach,
                       b_offset)
        return None

    # Mass-weighted impulse magnitude.
    j = -(1.0 + COLLISION_RESTITUTION) * v_rel / inv_sum
    if a.is_movable:
        cva = _ensure_overlay(a.obj)
        cva.x -= j * a.inv_mass * nx
        cva.y -= j * a.inv_mass * ny
        cva.z -= j * a.inv_mass * nz
    if b.is_movable:
        cvb = _ensure_overlay(b.obj)
        cvb.x += j * b.inv_mass * nx
        cvb.y += j * b.inv_mass * ny
        cvb.z += j * b.inv_mass * nz

    # Positional de-penetration, split by inverse mass.
    pen = sum_r - dist
    if a.is_movable:
        s = pen * a.inv_mass / inv_sum
        p = a.obj.GetTranslate()
        a.obj.SetTranslateXYZ(p.x - nx * s, p.y - ny * s, p.z - nz * s)
    if b.is_movable:
        # B is read and written in its OWN set's coordinates: the push is a
        # displacement, and (p + off + n*s) - off == p + n*s, so the offset
        # cancels exactly rather than being added and rounded back out.
        s = pen * b.inv_mass / inv_sum
        p = b.obj.GetTranslate()
        b.obj.SetTranslateXYZ(p.x + nx * s, p.y + ny * s, p.z + nz * s)

    # Every collision event is posted BEFORE the impact damage. Order, not
    # damage, is what this changes: event dispatch is synchronous, so a lethal
    # hit applied first runs the victim's ET_OBJECT_EXPLODING handlers ahead
    # of its collision events.
    #
    # ET_PLANET_COLLISION (chunks included, see the emitter): E1M2 otherwise
    # counts an asteroid that struck Haven as a player kill (ObjectDestroyed
    # -> AsteroidDestroyed) and PlanetCollision finds it already gone -- the
    # Haven-hit / MissionLost beat never fires. Inference, not RE: BC routes
    # planet contact through its own handler on this event
    # (ShipClass::PlanetCollisionHandler), so the event cannot trail a death
    # it may itself cause.
    #
    # ET_CLOAKED_COLLISION / ET_OBJECT_COLLISION, same reasoning: a lethal
    # asteroid -> Facility strike in E1M2 used to explode the asteroid first,
    # so ObjectCollision's AsteroidHitStation beat never saw the contact.
    contact = boundary_a
    _emit_planet_collision(a.obj, b.obj)

    # No ET_OBJECT_COLLISION / ET_CLOAKED_COLLISION when either party is a
    # detached hull chunk (the impulse and damage still land).
    # MissionLib.FriendlyFireCollisionHandler does ObjectClass_Cast on both
    # parties and calls .GetName() on the result OUTSIDE its try -- a
    # DebrisChunk is not an ObjectClass, casts to None, and every
    # friendly-fire mission would traceback on the first chunk strike. The
    # cloaked-collision line ("we hit a cloaked ship") is equally wrong for
    # debris. Lazy import, as _resolve_body does.
    from engine.appc.debris_chunk import DebrisChunk
    if not (isinstance(a.obj, DebrisChunk) or isinstance(b.obj, DebrisChunk)):
        # A cloaked hull is still physically present: BC fires
        # ET_CLOAKED_COLLISION when something rams one
        # (HelmMenuHandlers.CloakedCollision plays a line).
        _emit_cloaked_collision(a.obj, b.obj)
        _emit_object_collision(a.obj, b.obj, contact, abs(j), b_offset)

    # KE impact damage routed through the existing weapons path. Each ship's
    # hit lands on its OWN hull: _trace_own_hull traces from just outside that
    # ship's contact boundary back into it, refining point + normal to the
    # mesh (host present) exactly as the weapons path does, and anchors at
    # the boundary itself on a miss or headless. `contact` (a's boundary) is
    # the nominal point returned for tests/debugging.
    from engine.appc.combat import apply_hit
    damage = _ke_damage(inv_sum, v_rel)
    n_ab = TGPoint3(nx, ny, nz)
    n_ba = TGPoint3(-nx, -ny, -nz)
    if a.is_movable:
        pt_a, n_a = _trace_own_hull(ship_instances, a, boundary_a, n_ab, trace_reach)
        apply_hit(a.obj, damage, pt_a, source=b.obj, normal=n_a,
                  ship_instances=ship_instances, weapon_type="collision",
                  hit_tangent=tan_a, decal_radius=scuff_r, decal_dent=1.0,
                  bypass_shields=True)  # kinetic impact: AddDamage primitive, skips shields
    if b.is_movable:
        pt_b, n_b = _trace_own_hull(ship_instances, b,
                                    _shifted(boundary_b, b_offset, -1.0), n_ba, trace_reach)
        apply_hit(b.obj, damage, pt_b, source=a.obj, normal=n_b,
                  ship_instances=ship_instances, weapon_type="collision",
                  hit_tangent=tan_b, decal_radius=scuff_r, decal_dent=1.0,
                  bypass_shields=True)  # kinetic impact: AddDamage primitive, skips shields

    return (a.obj, b.obj, contact, v_rel)


def _emit_object_collision(obj_a, obj_b, contact, force,
                           b_offset=_NO_OFFSET) -> None:
    """Post ET_OBJECT_COLLISION — one event per object, source/destination
    swapped.

    That pairing is SDK ground truth, not a guess: MissionLib.py:3906 states
    "Only need to check either the source or the destination, since there's an
    event sent for each", and FriendlyFireCollisionHandler reads
    GetDestination() as the ship that collided and GetSource() as what it hit.
    A single event would silently work for whichever object happened to be the
    destination and never fire for the other.

    `force` is the impulse magnitude (GetCollisionForce; the reference records
    it as the magnitude of a vector). Points: the narrow phase resolves a pair
    down to one deepest contact, so there is exactly one point today — the
    event applies BC's two-most-separated reduction on whatever it is given, so
    this stays correct if that ever yields a real manifold.

    `contact` is in A's set-local frame. Each event's point is in its
    DESTINATION's own set-local coordinates -- Effects.CollisionEffect places
    an explosion at GetPoint(i) in the destination's GetContainingSet() -- so
    B's event gets the contact shifted back by `b_offset` (identity when zero,
    so a same-set pair posts the one contact to both).

    Posted BEFORE the impact damage (see _respond_pair). Raise-safe, like
    _emit_cloaked_collision: a failure here must not abort collision
    response, which has already mutated positions by this point and still
    has the damage to apply.
    """
    import App
    from engine import dev_mode
    for dest, source, point in ((obj_a, obj_b, contact),
                                (obj_b, obj_a, _shifted(contact, b_offset, -1.0))):
        try:
            evt = App.CollisionEvent_Create()
            evt.SetEventType(App.ET_OBJECT_COLLISION)
            evt.SetSource(source)
            evt.SetDestination(dest)
            evt.SetPoints([point])
            evt.SetCollisionForce(force)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("emit ET_OBJECT_COLLISION", _e)


def _emit_planet_collision(obj_a, obj_b) -> None:
    """Broadcast ET_PLANET_COLLISION when exactly one party is a Planet (moons
    and suns included: Sun subclasses Planet, and iter_collidables already
    treats both as the same immovable anchor). Source = the planet,
    destination = the object that struck it; ONE event per contact, on the
    same impact-only path as ET_OBJECT_COLLISION, so a resting grind is
    silent. Two planets never reach here (two immovables return early).

    Evidence is SDK usage only -- the stbc-reference MCP was unavailable:
    E1M2.PlanetCollision (E1M2.py:1308), the event's only SDK consumer, reads
    Planet_Cast(GetSource()) and ShipClass_Cast(GetDestination()). BC's own
    ShipClass::PlanetCollisionHandler (registered on this event in the
    decompile) is unreconstructed; we post the event, we do not model what
    that handler does. A DebrisChunk destination is safe: E1M2's
    ShipClass_Cast gives None and it returns. Raise-safe."""
    import App
    from engine.appc.planet import Planet
    from engine import dev_mode
    a_planet, b_planet = isinstance(obj_a, Planet), isinstance(obj_b, Planet)
    if a_planet == b_planet:
        return
    planet, other = (obj_a, obj_b) if a_planet else (obj_b, obj_a)
    try:
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_PLANET_COLLISION)
        evt.SetSource(planet)
        evt.SetDestination(other)
        App.g_kEventManager.AddEvent(evt)
    except Exception as _e:
        dev_mode.log_swallowed("emit ET_PLANET_COLLISION", _e)


def _emit_cloaked_collision(obj_a, obj_b) -> None:
    """Broadcast ET_CLOAKED_COLLISION when either party to a collision is a
    cloaked or cloaking ship.  Raise-safe; the source is the cloaked ship."""
    import App
    for cloaked, other in ((obj_a, obj_b), (obj_b, obj_a)):
        # ⚠️ SCOUTED 2026-08-10 — LIVE BUG, highest-priority row found while
        # scouting the heatmap. This fires ET_CLOAKED_COLLISION for EVERY
        # collision involving a non-ship.
        #
        # `getattr(instance, "GetCloakingSubsystem", None)` never returns None:
        # TGObject.__getattr__ vends a truthy `_Stub` for any method the class
        # does not define. So on a Planet/asteroid/station the chain is
        #   getter is None      -> False (it is a _Stub)
        #   cloak is None       -> False (calling a _Stub yields a _Stub)
        #   not IsTryingToCloak -> False (the _Stub is truthy)
        # and the event fires. HelmMenuHandlers.CloakedCollision then plays a
        # "we hit a cloaked ship" line for ramming a planet.
        #
        # THE FIX IS ALREADY WRITTEN ELSEWHERE: resolve through the *class*, as
        # engine/appc/sensor_detection.py:42-56 does —
        #   getter = getattr(type(cloaked), "GetCloakingSubsystem", None)
        # Only ShipClass defines the real method (ships.py:992); everything else
        # then correctly yields None. Apply that form here.
        #
        # Provenance: this site — not sensor_detection.py — is what produced
        # docs/stub_heatmap.md ranks 45/46 (`Planet.GetCloakingSubsystem` and
        # the chained `.IsTryingToCloak`, 324 hits each). The chained attr is
        # this loop's signature. Those two rows were dated markedResolvedOn
        # 2026-08-09 on the strength of the sensor_detection fix; that
        # attribution was WRONG and the dates have been reverted.
        getter = getattr(cloaked, "GetCloakingSubsystem", None)
        if getter is None:
            continue
        try:
            cloak = getter()
        except Exception:
            continue
        if cloak is None or not cloak.IsTryingToCloak():
            continue
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_CLOAKED_COLLISION)
            evt.SetSource(cloaked)
            evt.SetDestination(other)
            App.g_kEventManager.AddEvent(evt)
        except Exception:
            pass
        return  # one event per collision is enough


def _apply_overlay_all(objects, dt: float) -> None:
    """Consume each object's collision overlay: displace by overlay*dt and
    decay the overlay toward zero. Objects that never collided have no
    _collision_velocity attribute and are skipped (byte-identical).

    Reads the overlay via _overlay_vec (obj.__dict__ lookup) rather than
    getattr(..., None): TGObject.__getattr__ returns a truthy stub for unknown
    attributes, so getattr would never see the None sentinel."""
    decay = math.exp(-dt / COLLISION_DECAY_TAU)
    for o in objects:
        cv = _overlay_vec(o)
        if cv is None or not (cv.x or cv.y or cv.z):
            continue
        p = o.GetTranslate()
        o.SetTranslateXYZ(p.x + cv.x * dt, p.y + cv.y * dt, p.z + cv.z * dt)
        cv.x *= decay
        cv.y *= decay
        cv.z *= decay


def _candidate_pairs(positions, radii, sets):
    """Index pairs (i < k) that could touch, in the same order the old
    all-pairs nested loop produced (sorted).

    Same set: a uniform spatial hash. The cell size is
    ``max(kBroadphaseMinCellGU, 2 x the largest radius in that set)`` -- any
    pair that can overlap is at most ``ra + rb <= 2 * rmax`` apart (rmax the
    largest radius in the set), so such a pair's cells differ by at most one
    step on each axis and the 3x3x3 neighbourhood always covers it. `radii`
    here is each body's whole-model bounding radius as drawn (world_radius:
    GetRadius() x GetScale()), the same quantity _respond_pair's broad phase
    and _deepest_piece_overlap's culls both key off (the per-body boundary
    shrink is <= 1, so it only ever SHRINKS the effective reach from there),
    so bucketing on it stays conservative.

    Different sets: always a candidate -- resolve_collisions' own
    frames.offset_between check decides afterwards whether the pair is even
    comparable, exactly as it did before broadphase existed.

    A non-finite coordinate (NaN or +-inf) cannot be floor-divided into a
    cell index -- `int(nan // cell)` raises ValueError, `int(inf // cell)`
    raises OverflowError, and the old all-pairs loop never crashed on either
    (a NaN/inf distance compare just evaluates to a normal True/False). Such
    a body is pulled out of the grid and paired against every other body in
    its set instead: conservative (a superset of whatever the grid would
    have found had the position been sane), and it can never silently drop a
    pair the old loop would have reached."""
    n = len(positions)
    if not _BROADPHASE:
        return [(i, k) for i in range(n) for k in range(i + 1, n)]
    by_set: dict = {}
    for i, s in enumerate(sets):
        by_set.setdefault(s, []).append(i)
    pairs = set()
    for idxs in by_set.values():
        if len(idxs) < 2:
            continue
        finite_idxs = []
        nonfinite_idxs = []
        for i in idxs:
            p = positions[i]
            if math.isfinite(p[0]) and math.isfinite(p[1]) and math.isfinite(p[2]):
                finite_idxs.append(i)
            else:
                nonfinite_idxs.append(i)
        cell = max(kBroadphaseMinCellGU, 2.0 * max(radii[i] for i in idxs))
        grid: dict = {}
        for i in finite_idxs:
            p = positions[i]
            key = (int(p[0] // cell), int(p[1] // cell), int(p[2] // cell))
            grid.setdefault(key, []).append(i)
        for (cx, cy, cz), members in grid.items():
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        other = grid.get((cx + dx, cy + dy, cz + dz))
                        if not other:
                            continue
                        for i in members:
                            for k in other:
                                if i < k:
                                    pairs.add((i, k))
        for i in nonfinite_idxs:
            for k in idxs:
                if i != k:
                    pairs.add((min(i, k), max(i, k)))
    keys = list(by_set.keys())
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            for i in by_set[keys[a]]:
                for k in by_set[keys[b]]:
                    pairs.add((min(i, k), max(i, k)))
    return sorted(pairs)


def resolve_collisions(objects, ship_instances=None, dt: float = 0.0):
    """Snapshot every object into a _Body and resolve all unordered pairs.
    Returns the list of collision tuples from _respond_pair (for tests /
    debugging). De-penetration mutates positions in place; with n small and
    overlaps rare, later pairs reading slightly stale centres self-corrects
    next frame (spec §4).

    Positions for the initial snapshot are fetched in one bulk call — nothing
    between the old per-object GetWorldLocation() reads and this point writes
    any object's transform (_apply_overlay_all, which does write positions,
    already ran in tick_collisions before objects reached here; de-penetration
    inside _respond_pair happens strictly after every body is snapshotted), so
    hoisting the reads to a single batch changes only the number of boundary
    crossings, not the values observed."""
    from engine.appc.transform_store import get_store
    from engine.systems import frames
    objects = list(objects)
    # Only store-backed objects (ObjectClass allocates `_xform` in __init__)
    # go through the bulk fetch. A DebrisChunk keeps its own TGPoint3 and
    # has no slot -- reading `o._xform` on one raised AttributeError here,
    # inside tick_collisions, which host_loop.run() does not guard, so the
    # first severed chunk took the whole frame loop down. __dict__ probe,
    # not hasattr: TGObject.__getattr__ vends a truthy _Stub for any unknown
    # name, which would hand get_positions a non-handle.
    stored = [o for o in objects if "_xform" in o.__dict__]
    positions = get_store().get_positions([o._xform for o in stored])
    by_id = {id(o): TGPoint3(*p) for o, p in zip(stored, positions)}
    bodies = [_resolve_body(o, by_id.get(id(o))) for o in objects]
    sets = [frames.containing_set(o) for o in objects]
    # offset_between resolved once per distinct (set_a, set_b) per call, not
    # once per object PAIR (~2 us each, and pairs grow quadratically with the
    # collidables Plan 3 adds) -- the projectiles.update_all per-call cache.
    offsets: dict = {}
    hits = []
    pos_list = [(b.center.x, b.center.y, b.center.z) for b in bodies]
    radii = [b.radius for b in bodies]   # world_radius, read once in _resolve_body; >= the contact radius _respond_pair tests
    for i, k in _candidate_pairs(pos_list, radii, sets):
        a_obj, b_obj = bodies[i].obj, bodies[k].obj
        # Different frames never interact: a planet left standing in the
        # set you warped out of is not where your ship is, whatever the
        # numbers say. One frame (the same set, or two regions of one
        # system) compares in A's set-local coordinates.
        key = (sets[i], sets[k])
        if key in offsets:
            b_offset = offsets[key]
        else:
            b_offset = offsets[key] = frames.offset_between(*key)
        if b_offset is None:
            continue
        # Per-pair mask (DamageableObject.EnableCollisionsWith). Symmetric:
        # either side disabling the other exempts the pair.
        if (b_obj.GetObjID() in _collision_disabled_ids(a_obj)
                or a_obj.GetObjID() in _collision_disabled_ids(b_obj)):
            continue
        hit = _respond_pair(bodies[i], bodies[k], ship_instances, dt,
                            b_offset=b_offset)
        if hit is not None:
            hits.append(hit)
    return hits


def iter_collidables():
    """Yield every collidable across all active sets: ships and asteroids
    (ShipClass) plus planets/moons/suns (Planet). isinstance filtering (not
    hasattr) is required — set membership includes _NamedStub objects whose
    __getattr__ answers True to any hasattr probe (see ship_iter.py)."""
    import App
    from engine.appc.ship_iter import iter_set_objects
    from engine.appc.ships import ShipClass
    from engine.appc.planet import Planet
    for pSet in App.g_kSetManager._sets.values():
        for obj in iter_set_objects(pSet):
            if isinstance(obj, (ShipClass, Planet)) and obj.GetRadius() > 0.0:
                yield obj
    # Detached hull chunks are bodies too: they can be struck and can
    # strike. Not ShipClass on purpose -- see debris_chunk.py.
    from engine.appc import debris_chunk
    for chunk in debris_chunk.live():
        yield chunk


def tick_collisions(dt: float, ship_instances=None):
    """Per-frame entry point: consume overlays for every collidable, then
    detect + resolve all overlapping pairs. Returns the list of collision
    tuples. Call once per render frame after motion + player input have run.

    When the dev-only Disable Collisions toggle is active, existing knockback
    overlays still decay (above) but no new pair is detected or resolved, so
    impulse, de-penetration, and collision damage are all suppressed. An
    object with SetCollisionsOn(0) gets the same treatment individually: it is
    excluded from pair resolution but its existing overlay still plays out."""
    objects = list(iter_collidables())
    _apply_overlay_all(objects, dt)
    from engine.dev_combat_cheats import disable_collisions_active
    if disable_collisions_active():
        return []
    return resolve_collisions([o for o in objects if _collisions_enabled(o)],
                              ship_instances=ship_instances, dt=dt)
