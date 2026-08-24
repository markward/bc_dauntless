"""Per-shape hull bounds — the pieces a hull is actually made of.

A BC model carries exactly one kind of structured bound data: an authored
bounding sphere per NiTriShape. There is no collision mesh in the files, and no
BC model authors the optional node-level bounding volume. So these spheres are
what a shape-aware collision test has to descend — which is consistent with the
original generating several contacts per collision and reducing them to the two
most separated (a single sphere pair could only ever produce one).

Why it matters: **concavity**. A starbase's docking bay is a void BETWEEN hull
pieces. Measured against the real geometry, `FinishedUndocking` leaves the ship
~125 GU from the starbase centre while the model-wide bound is ~150 GU — so with
one sphere the ship reads as *inside the station* for the whole flight out, and
`collision_avoidance` flags it every tick (its `_need_to_avoid` returns True
unconditionally for anything already within personal_space + radius). You cannot
steer out of something you are inside, so the evasive scorer picks an arbitrary
heading and commands full impulse. Against the pieces the bay is simply empty
space and none of that happens — no special case required.

Spheres are cached in world units at ``GetScale() == 1`` (raw NIF units times
BC_MODEL_SCALE, the same flat factor `_ship_world_matrix` applies), matching how
`_cache_shield_hull_box` stores the hull AABB. The ship's live position,
rotation and scale are applied on read.
"""
from engine.appc.math import TGPoint3

# Attribute name for the cache. Read via __dict__ everywhere below: a plain
# getattr on a TGObject returns a truthy _Stub for a missing attribute, which
# would sail past every "do we have bounds?" guard here.
_ATTR = "_hull_bound_spheres"


def cache_hull_bound_spheres(ship, spheres) -> None:
    """Store `spheres` — an iterable of ``(cx, cy, cz, radius)`` in raw model
    (NIF) units, as returned by the host's ``model_bounds()`` — on `ship`.

    Called once at realize time, alongside the shield hull box. Converted to
    world units at scale 1 here so readers never have to know about NIF units.
    """
    from engine.host_loop import BC_MODEL_SCALE
    s = BC_MODEL_SCALE
    ship.__dict__[_ATTR] = tuple(
        ((cx * s, cy * s, cz * s), r * s)
        for cx, cy, cz, r in spheres
        if r > 0.0
    )


def has_hull_bounds(ship) -> bool:
    """Whether `ship` has per-shape bounds to descend.

    False for anything whose model never realized — headless tests, a load
    failure, a set that has not been realized yet. Callers must fall back to
    their existing single-sphere behaviour rather than treat it as "no hull".
    """
    return bool(ship.__dict__.get(_ATTR))


def hull_spheres_world(ship) -> list:
    """`ship`'s hull pieces as ``[(TGPoint3 centre, radius), ...]`` in world
    space, or ``[]`` when it has none.

    Offsets are body-frame, so they are rotated by the ship's world rotation —
    without that every piece sits in the wrong place the moment a ship turns.
    Scale is applied to both centre and radius: DockWithStarbase shrinks the
    player to fit through the bay doors, and the pieces must shrink with it.
    """
    cached = ship.__dict__.get(_ATTR)
    if not cached:
        return []
    loc = ship.GetWorldLocation()
    R = ship.GetWorldRotation()
    scale = float(ship.GetScale())
    out = []
    for (cx, cy, cz), r in cached:
        v = TGPoint3(cx * scale, cy * scale, cz * scale)
        v.MultMatrixLeft(R)                    # body -> world
        out.append((TGPoint3(loc.x + v.x, loc.y + v.y, loc.z + v.z), r * scale))
    return out


def hull_spheres_near(ship, center, radius) -> list:
    """`ship`'s hull pieces that reach within `radius` of world point `center`,
    as ``[(TGPoint3 centre, radius), ...]``. Empty when it has no pieces, or
    when none of them are near — callers that need to tell those two apart ask
    `has_hull_bounds` first.

    Same answer as filtering `hull_spheres_world`, arrived at cheaply. A hull
    decomposes into up to `kMaxHullBoundLeaves` pieces (128; a FedStarbase uses
    all of them), and the per-piece cost that matters is the matrix multiply
    and TGPoint3 that put a piece in world space — not the compare that
    follows. So the rejection happens FIRST, in the ship's own body frame: one
    inverse transform of the query point, then plain arithmetic per piece, and
    only survivors are transformed out.

    The inverse is the transpose, which is exact because a ship's world
    rotation is orthonormal (`AlignToVectors` builds an orthonormal basis).
    Being a rigid transform it also preserves distance, so the body-frame
    compare and the world-frame one accept exactly the same pieces.
    """
    cached = ship.__dict__.get(_ATTR)
    if not cached:
        return []
    loc = ship.GetWorldLocation()
    R = ship.GetWorldRotation()
    scale = float(ship.GetScale())
    m = R._m
    # World -> body: R^T · (center - loc). Row-major, so R^T's rows are R's
    # columns, and each component is a column dotted with the offset.
    dx, dy, dz = center.x - loc.x, center.y - loc.y, center.z - loc.z
    qx = m[0][0] * dx + m[1][0] * dy + m[2][0] * dz
    qy = m[0][1] * dx + m[1][1] * dy + m[2][1] * dz
    qz = m[0][2] * dx + m[1][2] * dy + m[2][2] * dz

    out = []
    for (cx, cy, cz), r in cached:
        # Body-frame piece centre at the ship's live scale.
        sx, sy, sz = cx * scale, cy * scale, cz * scale
        ex, ey, ez = sx - qx, sy - qy, sz - qz
        reach = radius + r * scale
        if ex * ex + ey * ey + ez * ez > reach * reach:
            continue
        v = TGPoint3(sx, sy, sz)
        v.MultMatrixLeft(R)                    # body -> world
        out.append((TGPoint3(loc.x + v.x, loc.y + v.y, loc.z + v.z), r * scale))
    return out


def point_is_inside_hull(ship, point) -> bool:
    """Whether `point` (world space) lies inside any of `ship`'s hull pieces.

    Fails OPEN — a ship with no cached bounds returns False. Claiming a point
    is inside a hull we have no data for would resurrect exactly the
    false-positive this exists to remove.
    """
    for center, radius in hull_spheres_world(ship):
        dx = point.x - center.x
        dy = point.y - center.y
        dz = point.z - center.z
        if (dx * dx + dy * dy + dz * dz) <= radius * radius:
            return True
    return False


_BOUND_R_ATTR = "_hull_bound_radius_unscaled"


def bound_radius(ship) -> float:
    """Radius about ``ship``'s origin that CONTAINS every cached hull piece,
    at the ship's current scale. 0.0 when it has no pieces.

    Exists so a caller can gate on the whole body before expanding it into
    pieces. That gate is only sound if the radius really encloses them, and
    ``GetRadius()`` does NOT: the host only calls ``SetRadius`` from the model
    AABB ``if ship.GetRadius() <= 0.0`` (host_loop realize), so a ship whose
    hardpoint script authored a radius keeps the AUTHORED one, which has no
    guaranteed relationship to the model geometry the pieces come from. A
    protruding nacelle outside an under-sized authored radius would be gated
    away, and the ship would fly through it.

    max(|centre| + r) over the pieces, which is exact rather than approximate.
    Memoised unscaled on the instance (pieces never change after caching) and
    multiplied by the live GetScale() per call, so a rescaled ship stays right.
    """
    cached = ship.__dict__.get(_ATTR)
    if not cached:
        return 0.0
    r_unscaled = ship.__dict__.get(_BOUND_R_ATTR)
    if r_unscaled is None:
        r_unscaled = 0.0
        for (cx, cy, cz), r in cached:
            reach = (cx * cx + cy * cy + cz * cz) ** 0.5 + r
            if reach > r_unscaled:
                r_unscaled = reach
        ship.__dict__[_BOUND_R_ATTR] = r_unscaled
    try:
        return r_unscaled * float(ship.GetScale())
    except Exception:
        return r_unscaled
