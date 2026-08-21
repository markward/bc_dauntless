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
