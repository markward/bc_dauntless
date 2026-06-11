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
COLLISION_DAMAGE_COEFF = 1.0     # KE -> hull-damage-points (calibrated in Task 7)
COLLISION_DECAY_TAU = 0.5        # collision-velocity overlay decay time constant (s)
COLLISION_FALLBACK_MASS = 1.0e4  # nominal mass for a ship reporting GetMass()==0


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
    if isinstance(obj, ShipClass):
        m = obj.GetMass()
        if m <= 0.0:
            m = COLLISION_FALLBACK_MASS
        inv_mass = 1.0 / m
        movable = True
        v = obj.GetVelocity()
    else:
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


def _respond_pair(a: "_Body", b: "_Body", dt: float, host, ship_instances):
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
    sum_r = a.radius + b.radius
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

    # KE impact damage routed through the existing weapons path.
    from engine.appc.combat import apply_hit
    damage = _ke_damage(inv_sum, v_rel)
    contact = TGPoint3(a.center.x + nx * a.radius,
                       a.center.y + ny * a.radius,
                       a.center.z + nz * a.radius)
    if a.is_movable:
        apply_hit(a.obj, damage, contact, source=b.obj,
                  normal=TGPoint3(nx, ny, nz),
                  host=host, ship_instances=ship_instances, weapon_type=None)
    if b.is_movable:
        apply_hit(b.obj, damage, contact, source=a.obj,
                  normal=TGPoint3(-nx, -ny, -nz),
                  host=host, ship_instances=ship_instances, weapon_type=None)

    return (a.obj, b.obj, contact, v_rel)
