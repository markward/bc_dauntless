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
from dataclasses import dataclass

from engine.appc.math import TGPoint3

# -- Tuning constants (single home; see spec §9) --
COLLISION_RESTITUTION = 0.2      # bounciness e; mostly inelastic crunch
COLLISION_DAMAGE_COEFF = 5.0     # KE -> hull-damage-points; calibrated against
                                 # Galaxy (mass 120, hull 15000, impulse 6.3 GU/s):
                                 # full-impulse planet ram ~79% hull (near-fatal),
                                 # head-on both-full ram >100% (kill), dock-bump
                                 # trivial. Tune in-engine by feel. See spec §9.
COLLISION_DECAY_TAU = 0.5        # collision-velocity overlay decay time constant (s)
COLLISION_FALLBACK_MASS = 1.0e4  # nominal mass for a ship reporting GetMass()==0
COLLISION_RADIUS_SCALE = 0.8     # effective collision boundary as a fraction of
                                 # rA+rB: objects close 20% of the bounding-
                                 # sphere gap before a hit registers, compensating
                                 # for hulls sitting well inside their generous
                                 # bounding spheres (e.g. Galaxy saucer+nacelles)


@dataclass
class _Body:
    obj: object
    center: TGPoint3
    radius: float
    inv_mass: float
    is_movable: bool
    velocity: TGPoint3   # world thrust velocity + current overlay


def _overlay_vec(obj):
    """Read-only: the object's collision overlay, or None if never collided.

    Must use obj.__dict__ lookup rather than getattr(obj, …, None) because
    TGObject.__getattr__ returns a truthy _Stub for any unknown attribute,
    which would prevent the None sentinel from ever being returned.
    """
    return obj.__dict__.get("_collision_velocity")


def _collisions_enabled(obj):
    """Per-object DamageableObject.SetCollisionsOn flag; default True.

    Same obj.__dict__ pattern as _overlay_vec: the flag is only ever set as an
    instance attribute, and getattr would hit TGObject.__getattr__'s truthy
    _Stub on objects that never had it set (e.g. Planet)."""
    return obj.__dict__.get("_collisions_on", True)


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


def _resolve_body(obj) -> "_Body":
    """Snapshot an object into a _Body. Ships are movable (inverse mass from
    GetMass, fallback when zero); planets/moons/suns are immovable. Velocity
    is the world thrust velocity plus any active collision overlay."""
    from engine.appc.ships import ShipClass
    center = obj.GetWorldLocation()
    radius = obj.GetRadius()
    if isinstance(obj, ShipClass) and not obj.IsImmobile():
        m = obj.GetMass()
        if m <= 0.0:
            m = COLLISION_FALLBACK_MASS
        inv_mass = 1.0 / m
        movable = True
        v = obj.GetVelocity()
    else:
        # Planets/moons/suns AND immobile ships (SetStatic / SetStationary):
        # fixed anchors. inv_mass 0 + zero velocity means the mover takes the
        # full de-penetration and impulse, exactly as it does against a planet.
        inv_mass = 0.0
        movable = False
        v = TGPoint3(0.0, 0.0, 0.0)
    cv = _overlay_vec(obj)
    if cv is not None:
        v = v + cv
    return _Body(obj, center, radius, inv_mass, movable, v)


def _ke_damage(inv_sum: float, v_rel: float) -> float:
    """KE-of-closing-speed damage: COEFF * 0.5 * mu * v_rel**2, mu = 1/inv_sum.

    Precondition: inv_sum > 0 (at least one body must be movable). The
    pair-response caller gates two-immovable pairs out before reaching here.
    """
    assert inv_sum > 0.0, "inv_sum must be > 0; two immovable bodies cannot collide"
    mu = 1.0 / inv_sum
    return COLLISION_DAMAGE_COEFF * 0.5 * mu * v_rel * v_rel


def _respond_pair(a: "_Body", b: "_Body", ship_instances=None):
    """Resolve one body pair. On an approaching overlap: inject a
    mass-weighted impulse into each movable body's overlay, de-penetrate
    positions, and apply KE damage via combat.apply_hit. Returns the
    (a.obj, b.obj, contact_point, v_rel) tuple if they collided, else None.

    The `v_rel < 0` (approaching) gate is the debounce: once the impulse
    reverses relative velocity, later frames read receding and do nothing
    while the spheres still overlap (spec §5)."""
    dx = b.center.x - a.center.x
    dy = b.center.y - a.center.y
    dz = b.center.z - a.center.z
    dist2 = dx * dx + dy * dy + dz * dz
    # Effective boundary is scaled below the raw bounding-sphere sum so hulls
    # visually close most of the gap before the hit registers (spec §4).
    sum_r = (a.radius + b.radius) * COLLISION_RADIUS_SCALE
    if dist2 >= sum_r * sum_r:
        return None
    dist = math.sqrt(dist2)
    if dist < 1e-9:
        return None  # concentric: degenerate normal, skip
    nx, ny, nz = dx / dist, dy / dist, dz / dist

    # Closing speed along the normal (negative = approaching).
    rvx = b.velocity.x - a.velocity.x
    rvy = b.velocity.y - a.velocity.y
    rvz = b.velocity.z - a.velocity.z
    v_rel = rvx * nx + rvy * ny + rvz * nz
    if v_rel >= 0.0:
        return None  # receding / resting: debounce

    inv_sum = a.inv_mass + b.inv_mass
    if inv_sum <= 0.0:
        return None  # two immovables

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
        s = pen * b.inv_mass / inv_sum
        p = b.obj.GetTranslate()
        b.obj.SetTranslateXYZ(p.x + nx * s, p.y + ny * s, p.z + nz * s)

    # KE impact damage routed through the existing weapons path. Each ship's
    # hit lands on its OWN hull: trace from the other body's centre into this
    # ship along the contact line so combat._resolve_hit_point refines the
    # contact point + surface normal to the mesh (host present) exactly as the
    # weapons path does, falling back to the bounding-sphere surface + the
    # geometric normal when headless. `contact` (a's sphere surface) is the
    # nominal point returned for tests/debugging and the A-side fallback.
    from engine.appc.combat import apply_hit, _resolve_hit_point
    damage = _ke_damage(inv_sum, v_rel)
    # Fallback contact sits on the SCALED sphere surface (where the collision
    # actually registered); mesh refinement overrides it when a host is present.
    eff_ra = a.radius * COLLISION_RADIUS_SCALE
    contact = TGPoint3(a.center.x + nx * eff_ra,
                       a.center.y + ny * eff_ra,
                       a.center.z + nz * eff_ra)
    if a.is_movable:
        pt_a, mesh_n_a = _resolve_hit_point(
            ship_instances, a.obj,
            b.center, TGPoint3(-nx, -ny, -nz), dist, contact)
        apply_hit(a.obj, damage, pt_a, source=b.obj,
                  normal=(mesh_n_a if mesh_n_a is not None else TGPoint3(nx, ny, nz)),
                  ship_instances=ship_instances, weapon_type=None,
                  bypass_shields=True)  # kinetic impact: AddDamage primitive, skips shields
    if b.is_movable:
        eff_rb = b.radius * COLLISION_RADIUS_SCALE
        fb_b = TGPoint3(b.center.x - nx * eff_rb,
                        b.center.y - ny * eff_rb,
                        b.center.z - nz * eff_rb)
        pt_b, mesh_n_b = _resolve_hit_point(
            ship_instances, b.obj,
            a.center, TGPoint3(nx, ny, nz), dist, fb_b)
        apply_hit(b.obj, damage, pt_b, source=a.obj,
                  normal=(mesh_n_b if mesh_n_b is not None else TGPoint3(-nx, -ny, -nz)),
                  ship_instances=ship_instances, weapon_type=None,
                  bypass_shields=True)  # kinetic impact: AddDamage primitive, skips shields

    # A cloaked hull is still physically present: BC fires ET_CLOAKED_COLLISION
    # when something rams one (HelmMenuHandlers.CloakedCollision plays a line).
    _emit_cloaked_collision(a.obj, b.obj)

    return (a.obj, b.obj, contact, v_rel)


def _emit_cloaked_collision(obj_a, obj_b) -> None:
    """Broadcast ET_CLOAKED_COLLISION when either party to a collision is a
    cloaked or cloaking ship.  Raise-safe; the source is the cloaked ship."""
    import App
    for cloaked, other in ((obj_a, obj_b), (obj_b, obj_a)):
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


def resolve_collisions(objects, ship_instances=None):
    """Snapshot every object into a _Body and resolve all unordered pairs.
    Returns the list of collision tuples from _respond_pair (for tests /
    debugging). De-penetration mutates positions in place; with n small and
    overlaps rare, later pairs reading slightly stale centres self-corrects
    next frame (spec §4)."""
    bodies = [_resolve_body(o) for o in objects]
    hits = []
    for i in range(len(bodies)):
        for k in range(i + 1, len(bodies)):
            a_obj, b_obj = bodies[i].obj, bodies[k].obj
            # Per-pair mask (DamageableObject.EnableCollisionsWith). Symmetric:
            # either side disabling the other exempts the pair.
            if (b_obj.GetObjID() in _collision_disabled_ids(a_obj)
                    or a_obj.GetObjID() in _collision_disabled_ids(b_obj)):
                continue
            hit = _respond_pair(bodies[i], bodies[k], ship_instances)
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
                              ship_instances=ship_instances)
