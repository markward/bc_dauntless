# engine/appc/warp_core_breach.py
"""Warp-core breach: a catastrophic explosion when a ship's Warp Core
(PowerSubsystem) condition crosses from >0 to 0.

Armed once per ship by the objects.py zero-crossing hook (direct core kill,
hull-death cascade, or a neighbour's breach). detonate() — driven from
advance() — deals weapon-style area damage to every ship within
BREACH_RADIUS_GU of the core's world position, with NO allegiance filter, by
reusing combat.apply_hit (shields/hull/subsystem-splash/decals/sparks/audio
all fire). Chains resolve in the same tick via a non-recursive drain loop;
each ship detonates at most once.

See docs/superpowers/specs/2026-06-20-warp-core-breach-design.md.
"""
import engine.dev_mode as dev_mode

BREACH_DAMAGE_FACTOR   = 1.0   # centre damage = factor * core max condition
BREACH_RADIUS_GU       = 4.0   # shared AoE damage radius AND shockwave ring max
                               # radius; tuned to the dramatic visual (was 1.3)

_armed: list = []      # ships queued to detonate (FIFO)
# Holds the ship objects themselves (not id()) so that CPython's id-reuse cannot
# cause a freshly-spawned ship to be silently skipped if it lands on a recycled
# address. Identity/strong-ref semantics match how _armed already uses `is`.
_breached: set = set()


def arm(ship) -> None:
    """Queue `ship` to detonate. Idempotent: a ship already queued or already
    breached is ignored. This is the single-fire guarantee."""
    if ship is None or ship in _breached:
        return
    if any(s is ship for s in _armed):
        return
    _armed.append(ship)


def advance(dt: float, host=None, ship_instances=None) -> None:
    """Drain the armed queue, detonating each ship. Non-recursive: a detonation
    may arm further ships (chains), which this while-loop picks up in the same
    tick. The _breached guard guarantees termination."""
    while _armed:
        ship = _armed.pop(0)
        if ship in _breached:
            continue
        _breached.add(ship)
        # Module-global lookup so tests can monkeypatch `detonate`.
        detonate(ship, host=host, ship_instances=ship_instances)


def detonate(ship, host=None, ship_instances=None) -> None:
    """Massive explosion at the warp core's world position: weapon-style AoE
    damage to every ship in BREACH_RADIUS_GU + a shockwave ring VFX. Raise-safe."""
    from engine.appc import combat
    from engine.appc.subsystems import subsystem_world_position
    from engine.appc.ship_iter import iter_ships

    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return
    centre = subsystem_world_position(core, ship)
    magnitude = BREACH_DAMAGE_FACTOR * float(core.GetMaxCondition())

    try:
        from engine.appc import shockwaves
        shockwaves.spawn(centre, BREACH_RADIUS_GU, shockwaves.SHOCKWAVE_LIFETIME)
    except Exception as _e:
        dev_mode.log_swallowed("spawn warp core shockwave", _e)

    for target in list(iter_ships()):
        if target is ship:
            continue
        loc = target.GetWorldLocation()
        dx = centre.x - loc.x
        dy = centre.y - loc.y
        dz = centre.z - loc.z
        d = (dx * dx + dy * dy + dz * dz) ** 0.5
        r_tgt = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
        w = combat._splash_weight(r_tgt, BREACH_RADIUS_GU, d)
        if w <= 0.0:
            continue
        point, normal = _impact_point(target, centre, host, ship_instances)
        try:
            combat.apply_hit(
                target, magnitude * w, point, source=ship,
                normal=normal, host=host, ship_instances=ship_instances,
                weapon_type="torpedo", splash_radius=BREACH_RADIUS_GU,
            )
        except Exception as _e:
            dev_mode.log_swallowed("warp core breach apply_hit", _e)


def _impact_point(target, centre, host, ship_instances):
    """Return (point, normal) on `target`'s hull, traced from `centre` toward
    the target centre. Falls back to the sphere-facing point (normal None)
    when no host/renderer instance is available (headless / tests)."""
    from engine.appc.math import TGPoint3
    from engine.appc.combat import _resolve_hit_point
    loc = target.GetWorldLocation()
    dx = loc.x - centre.x
    dy = loc.y - centre.y
    dz = loc.z - centre.z
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5
    r_tgt = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
    if dist <= 1e-6:
        # Blast centre coincides with the target centre — hit its centre.
        return TGPoint3(loc.x, loc.y, loc.z), None
    inv = 1.0 / dist
    direction = TGPoint3(dx * inv, dy * inv, dz * inv)
    origin = TGPoint3(centre.x, centre.y, centre.z)
    fallback = TGPoint3(loc.x - direction.x * r_tgt,
                        loc.y - direction.y * r_tgt,
                        loc.z - direction.z * r_tgt)
    return _resolve_hit_point(host, ship_instances, target,
                              origin, direction, dist + r_tgt, fallback)


def reset() -> None:
    """Clear the armed queue and breached set (mission swap / test teardown)."""
    _armed.clear()
    _breached.clear()
