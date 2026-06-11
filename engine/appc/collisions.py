"""Per-frame collision detection + response for ships and space bodies.

Reuses the weapons-system collision/damage primitives: a sphere-overlap
broadphase, combat.apply_hit for impact damage (A), and a mass-weighted
impulse injected into a decaying per-object _collision_velocity overlay (B).
No rigid-body physics engine — the kinematic integrators are untouched; the
overlay is applied and decayed here, once per render frame, for every
collidable.

Spec: docs/superpowers/specs/2026-06-11-collision-response-design.md
"""
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
