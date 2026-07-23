# engine/appc/splash_damage.py
"""Faithful death-explosion splash damage.

When a destructible object explodes, BC's engine deals its m_splashDamage
(+0x154) as collateral to every object within m_splashDamageRadius (+0x158) of
it — set on every ship by loadspacehelper.py:100 (MaxCondition*0.1 at radius*2)
and overridden by missions (E7M1 freighters at 1000, E3M2 probe at 1500).

`apply(ship)` is fired once at the death moment (ship_death.begin, and the
lifetime-expiry path). It reuses combat.apply_hit — an explosion damage
primitive, so it BYPASSES SHIELDS (like AddDamage) and applies to EVERY ship in
range with NO allegiance filter (an exploding hull does not pick sides). The
source ship is skipped.

The falloff curve (linear via combat._splash_weight) is our best-effort model:
BC's exact application law lives in the DEFERRED DamageableObject::update()
(DamageableObject.md sec 4.4) and is not reconstructed, but the splash AMOUNT
and RADIUS are the ship's real authored values.

This replaces the earlier artistic AoE that hung off the warp-core breach; the
breach now only spawns its VFX (shockwave ring + hull carve).
"""
import engine.dev_mode as dev_mode


def apply(ship, ship_instances=None) -> None:
    """Deal `ship`'s splash damage to every other ship within its splash
    radius. Raise-safe; a no-op when the object carries no splash."""
    if ship is None:
        return
    amount = float(ship.GetSplashDamage()) if hasattr(ship, "GetSplashDamage") else 0.0
    radius = float(ship.GetSplashDamageRadius()) if hasattr(ship, "GetSplashDamageRadius") else 0.0
    if amount <= 0.0 or radius <= 0.0:
        return

    from engine.appc import combat
    from engine.appc.ship_iter import iter_ships

    centre = ship.GetWorldLocation()
    for target in list(iter_ships()):
        if target is ship:
            continue
        loc = target.GetWorldLocation()
        dx = centre.x - loc.x
        dy = centre.y - loc.y
        dz = centre.z - loc.z
        d = (dx * dx + dy * dy + dz * dz) ** 0.5
        r_tgt = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
        w = combat._splash_weight(r_tgt, radius, d)
        if w <= 0.0:
            continue
        point, normal = _impact_point(target, centre, ship_instances)
        try:
            combat.apply_hit(
                target, amount * w, point, source=ship,
                normal=normal, ship_instances=ship_instances,
                weapon_type="torpedo", splash_radius=radius,
                bypass_shields=True,  # explosion: AddDamage primitive, skips shields
            )
        except Exception as _e:
            dev_mode.log_swallowed("splash damage apply_hit", _e)


def _impact_point(target, centre, ship_instances):
    """Return (point, normal) on `target`'s hull, traced from the blast centre
    toward the target centre. Falls back to the sphere-facing point (normal
    None) when no renderer instance is available (headless / tests)."""
    from engine.appc.math import TGPoint3
    from engine.appc.combat import _resolve_hit_point
    loc = target.GetWorldLocation()
    dx = loc.x - centre.x
    dy = loc.y - centre.y
    dz = loc.z - centre.z
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5
    r_tgt = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
    if dist <= 1e-6:
        return TGPoint3(loc.x, loc.y, loc.z), None
    inv = 1.0 / dist
    direction = TGPoint3(dx * inv, dy * inv, dz * inv)
    origin = TGPoint3(centre.x, centre.y, centre.z)
    fallback = TGPoint3(loc.x - direction.x * r_tgt,
                        loc.y - direction.y * r_tgt,
                        loc.z - direction.z * r_tgt)
    return _resolve_hit_point(ship_instances, target,
                              origin, direction, dist + r_tgt, fallback)
