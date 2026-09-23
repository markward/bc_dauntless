"""Per-piece hull bounds — the pieces a hull is actually made of.

The pieces are DERIVED, not authored. `compute_model_bounds`
(native/src/renderer/aabb.cc:141) pools the triangles of the WHOLE model into
one soup — deliberately not one soup per mesh, because "a BC mesh is a material
group, not a spatial one" (three of FedStarbase's five shapes each span the
entire station) — then median-splits it along the longest axis of the centroid
spread into at most `kMaxHullBoundLeaves` (128) leaves, and bounds each leaf
with a sphere about its AABB centre.

So these are NOT "an authored bounding sphere per NiTriShape", which is what
this docstring used to claim. BC models carry no collision mesh, and none of
them authors the optional node-level bounding volume; the decomposition here is
ours, computed from the triangle soup at load. That it is spatial rather than
per-mesh is the whole point — a per-mesh split would leave the void under a
starbase's mushroom cap claimed by geometry nowhere near it, which is exactly
the concavity case below.

Descending pieces is also consistent with the original generating several
contacts per collision and reducing them to the two most separated (a single
sphere pair could only ever produce one).

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
import math

from engine.appc.math import TGPoint3

# Attribute name for the cache. Read via __dict__ everywhere below: a plain
# getattr on a TGObject returns a truthy _Stub for a missing attribute, which
# would sail past every "do we have bounds?" guard here.
_ATTR = "_hull_bound_spheres"

# Where bound_radius memoises its unscaled answer. Declared here, next to the
# pieces it is derived from, because the two must be written and cleared
# together — see cache_hull_bound_spheres.
_BOUND_R_ATTR = "_hull_bound_radius_unscaled"


def cache_hull_bound_spheres(ship, spheres) -> None:
    """Store `spheres` — an iterable of ``(cx, cy, cz, radius)`` in raw model
    (NIF) units, as returned by the host's ``model_bounds()`` — on `ship`.

    Called once at realize time, alongside the shield hull box. Converted to
    world units at scale 1 here so readers never have to know about NIF units.

    Drops `bound_radius`'s memo, which is derived from these pieces but lives
    in a different slot: writing one without the other would answer a
    soundness-critical question about geometry the ship no longer has.

    Each piece is tagged with the articulated part its CENTRE falls on, or
    None. `part_for_point` returns None wherever the part boxes overlap —
    which is most of the hull by design, since a BoP's wing boxes swallow the
    body box at the roots — so the tag is a minority case, and None keeps the
    piece behaving exactly as it did before parts existed.

    The tag is further restricted to parts that can actually MOVE or DETACH
    (the union of `articulation.rig_for`'s node names and
    `articulation.detachable_for`'s keys) — see the comment at the tagging
    site for why.
    """
    from engine.host_loop import BC_MODEL_SCALE
    from engine.appc import articulation
    from engine.appc.part_severance import part_for_point
    s = BC_MODEL_SCALE
    # Attribution is computed ONCE here, never per tick: the pieces and the
    # part boxes are both rest-pose and neither ever changes after load.
    leaf = articulation.leaf_for(ship)
    # A tag means "this piece can move or come off" -- not merely "nearest
    # some named box". PART_BOXES carries boxes (e.g. "head", the body box
    # itself) that are boxed for attribution purposes but neither rigged nor
    # detachable, so tagging them would be a no-op forever in both readers
    # AND in the (later) part-transform call each reader makes for a
    # non-None tag. hull_spheres_near's per-piece cost that matters is that
    # transform, done BEFORE its distance reject -- untagging inert boxes
    # here keeps them out of that path on every narrow-phase pair, forever,
    # rather than paying a Python call per body piece for a tag that can
    # never fire.
    movable = {p.node for p in articulation.rig_for(leaf)}
    movable.update(articulation.detachable_for(leaf))
    out = []
    for cx, cy, cz, r in spheres:
        if r <= 0.0:
            continue
        c = (cx * s, cy * s, cz * s)
        part = part_for_point(leaf, c) if leaf else None
        if part not in movable:
            part = None
        out.append((c, r * s, part))
    ship.__dict__[_ATTR] = tuple(out)
    ship.__dict__.pop(_BOUND_R_ATTR, None)


def hull_piece_count(ship) -> int:
    """How many pieces `ship` carries (0 = none cached). Diagnostics only."""
    return len(ship.__dict__.get(_ATTR) or ())


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
    from engine.appc.part_severance import is_detached
    from engine.appc import articulation
    out = []
    for (cx, cy, cz), r, part in cached:
        if part is not None and is_detached(ship, part):
            continue                           # severed: no longer collides
        if part is not None:
            # Body frame, ship units, in and out. Identity at rest and for an
            # unrigged hull, so an untagged piece costs one None compare.
            cx, cy, cz = articulation.part_transform_point(ship, (cx, cy, cz))
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

    A piece tagged with an articulated part is moved into that part's live
    pose FIRST, before the reject — see tests/unit/test_hull_bounds_parts.py::
    test_hull_spheres_near_ACCEPTS_a_piece_at_its_MOVED_position. Untagged
    pieces, which are the overwhelming majority on every hull and all of them
    on an unrigged one, take exactly the path they took before.
    """
    cached = ship.__dict__.get(_ATTR)
    if not cached:
        return []
    loc = ship.GetWorldLocation()
    R = ship.GetWorldRotation()
    scale = float(ship.GetScale())
    # World -> body: R^T · (center - loc). Row-major, so R^T's rows are R's
    # columns, and each component is a column dotted with the offset.
    dx, dy, dz = center.x - loc.x, center.y - loc.y, center.z - loc.z
    qx = R.m00 * dx + R.m10 * dy + R.m20 * dz
    qy = R.m01 * dx + R.m11 * dy + R.m21 * dz
    qz = R.m02 * dx + R.m12 * dy + R.m22 * dz

    from engine.appc.part_severance import is_detached
    from engine.appc import articulation
    out = []
    for (cx, cy, cz), r, part in cached:
        if part is not None and is_detached(ship, part):
            continue                           # severed: no longer collides
        if part is not None:
            # BEFORE the reject below, not after: the compare happens in the
            # ship's body frame, so a moved piece tested at its REST centre
            # would be rejected and never returned.
            cx, cy, cz = articulation.part_transform_point(ship, (cx, cy, cz))
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


def _rig_parts_by_name(ship, cached) -> dict:
    """{part name: articulation.Part} for `ship`, or {} when no cached piece
    carries a tag.

    The empty-dict early out is what keeps every unrigged hull — and every
    rigged one whose pieces all landed on the body — off the import and the
    rig lookup entirely, on the one call that fills the memo.
    """
    if not any(part is not None for _c, _r, part in cached):
        return {}
    from engine.appc import articulation
    return {p.node: p for p in articulation.rig_for(articulation.leaf_for(ship))}


def _travel_reach(part, centre) -> float:
    """Largest |centre| the piece reaches at ANY deflection in [0, 1], with
    `centre` the piece's REST centre in body frame, ship units.

    The hinge sweeps the centre along a circular arc: a fixed circle centre
    `A` (the pivot plus whatever part of the offset lies ALONG the axis,
    which never moves) plus a rotating radius `w` (the part perpendicular to
    the axis, whose length is constant). So

        |p(theta)|^2 = |A|^2 + |w|^2 + 2 * (A_perp . w(theta))

    which is sinusoidal in theta. Its peak — `w` swung into line with
    `A_perp` — is the largest value on the FULL circle, but it is only
    reachable if it falls inside the arc the part actually travels. Hence:
    both endpoints always, plus the aligned peak when `phi`, the signed
    angle from `w` to `A_perp` about the axis, lies between 0 and the full
    travel angle.

    Right-handed about the axis, matching the rest of the engine: `phi` uses
    atan2(axis . (w x A_perp), w . A_perp), so rotating `w` by +phi about the
    axis is what lines it up.
    """
    pivot, axis, theta = _part_rotation(part)
    best = max(_norm(centre), _norm(_point_at(part, centre)))
    if theta == 0.0:
        return best
    ax, ay, az = axis
    vx, vy, vz = centre[0] - pivot[0], centre[1] - pivot[1], centre[2] - pivot[2]
    along = ax * vx + ay * vy + az * vz
    wx, wy, wz = vx - ax * along, vy - ay * along, vz - az * along
    cx = pivot[0] + ax * along
    cy = pivot[1] + ay * along
    cz = pivot[2] + az * along
    a_along = ax * cx + ay * cy + az * cz
    px, py, pz = cx - ax * a_along, cy - ay * a_along, cz - az * a_along
    dot = wx * px + wy * py + wz * pz
    kx, ky, kz = wy * pz - wz * py, wz * px - wx * pz, wx * py - wy * px
    phi = math.atan2(ax * kx + ay * ky + az * kz, dot)
    inside = (0.0 <= phi <= theta) if theta > 0.0 else (theta <= phi <= 0.0)
    if inside:
        w = (wx * wx + wy * wy + wz * wz) ** 0.5
        p = (px * px + py * py + pz * pz) ** 0.5
        peak = (cx * cx + cy * cy + cz * cz) + w * w + 2.0 * p * w
        best = max(best, peak ** 0.5)
    return best


def _norm(p) -> float:
    return (p[0] * p[0] + p[1] * p[1] + p[2] * p[2]) ** 0.5


def _part_rotation(part):
    """(pivot, unit axis, theta) for `part` at FULL deflection."""
    from engine.appc import articulation
    return articulation.rotation_for(part, 1.0)


def _point_at(part, centre):
    """`centre` at FULL deflection of `part` — ship state never consulted."""
    from engine.appc import articulation
    return articulation.point_at_deflection(part, centre, 1.0)


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

    max(|centre| + r) over the pieces. For an UNTAGGED piece — every piece on
    an unrigged hull, and the overwhelming majority on a rigged one — that is
    exactly the old arithmetic, to the float.

    A TAGGED piece MOVES, so its rest centre is not its furthest reach. The
    radius therefore encloses such a piece AT EVERY POINT IN ITS TRAVEL:
    `_travel_reach` maximises |centre| over the whole 0->1 arc the part's
    hinge sweeps it through, analytically, not just at the two ends (the far
    point of an arc can fall mid-travel — see
    tests/unit/test_hull_bounds_parts.py::WING_MID_TRAVEL_PT, where the
    endpoints understate by 1.3%).

    That replaces this docstring's older "over-stating is safe, under-stating
    is not" reasoning, which was written before pieces articulated and was
    being used to justify a rest-pose-only maximum. The asymmetry is still
    true — but a rest-only maximum UNDER-states a deflected wing, which is
    the unsafe direction: a Bird of Prey with its wings down pokes outside
    its own gate, and `collision_avoidance` can drop a pair whose wings
    really do reach.

    STILL ONE MEMO, computed once. Deliberately NOT a function of the ship's
    live deflection: making it so would defeat the memo and put trigonometry
    in the narrow phase, for a gate that only has to enclose.

    Memoised unscaled on the instance (pieces never change after caching) and
    multiplied by the live GetScale() per call, so a rescaled ship stays right.

    Counts a SEVERED part's pieces too — shrinking it on severance would mean
    invalidating this memo on every detach, and a gate is allowed to be
    generous. Pinned by tests/unit/test_hull_bounds_parts.py::
    test_bound_radius_still_counts_a_severed_part.
    """
    cached = ship.__dict__.get(_ATTR)
    if not cached:
        return 0.0
    r_unscaled = ship.__dict__.get(_BOUND_R_ATTR)
    if r_unscaled is None:
        parts = _rig_parts_by_name(ship, cached)
        r_unscaled = 0.0
        for (cx, cy, cz), r, part in cached:
            p = parts.get(part)
            if p is None:
                reach = (cx * cx + cy * cy + cz * cz) ** 0.5 + r
            else:
                reach = _travel_reach(p, (cx, cy, cz)) + r
            if reach > r_unscaled:
                r_unscaled = reach
        ship.__dict__[_BOUND_R_ATTR] = r_unscaled
    try:
        return r_unscaled * float(ship.GetScale())
    except Exception:
        return r_unscaled
