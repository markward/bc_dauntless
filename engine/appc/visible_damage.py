# engine/appc/visible_damage.py
"""BC visible-damage API -> hull-carve renderer.

The SDK's pre-wreck `Damage*.py` scripts (authored by the original DamageTool)
call `pShip.AddObjectDamageVolume(x, y, z, influRad, strength)` — a body-frame
damage sphere — and `Effects.DeathExplosionDamage` calls the runtime sibling
`pShip.AddDamage(pEmitPos, fRadius, fDamage)`. `DamageableObject` routes both
here.

The carve emitter (`host.hull_carve_add`) needs the renderer `host` and the
ship->instance-id map, which only exist in the host-loop tick. But the authored
calls arrive during a mission's `Initialize`, BEFORE the set's render instances
are realized (the ship has no `iid` yet). So we QUEUE each request and DRAIN it
per-tick from `advance()` once the ship's instance is realized — the same
deferred pattern as `engine/appc/core_breach_carve.py`. Authored damage bypasses
the combat path's eligibility gate and emit throttle (it is content, not beam
clutter) and emits all of a ship's volumes at once.

`strength` (Gap 2) is accepted for call-shape fidelity but unused here; only the
sphere position + radius drive a Gap-1 carve.

See docs/original_game_reference/engine/damagetool-and-hull-damage-gaps.md.
"""
import engine.dev_mode as dev_mode
from engine.appc.math import TGPoint3, TGMatrix3

# Pending requests linger at most this long (game seconds) waiting for the
# ship's render instance to be realized, then drop — so a headless run, a culled
# ship, or a failed spawn never leaks an un-emittable entry.
MAX_PENDING_AGE = 5.0

# Registry of not-yet-emitted volumes. Each entry:
#   {"ship", "kind": "body"|"world", "pt": (x, y, z), "radius": float, "age": float}
_pending: list[dict] = []


def queue_body_volume(ship, x, y, z, influRad, strength=0.0) -> None:
    """Queue an authored body-frame damage sphere (SDK AddObjectDamageVolume).
    `strength` is accepted for fidelity but unused in Gap 1."""
    if ship is None:
        return
    _pending.append({
        "ship": ship, "kind": "body",
        "pt": (float(x), float(y), float(z)),
        "radius": float(influRad), "age": 0.0,
    })


def queue_world_carve(ship, pEmitPos, fRadius, fDamage=0.0) -> None:
    """Queue a runtime world-space carve (DamageableObject.AddDamage, e.g.
    Effects.DeathExplosionDamage). `fDamage` is unused in Gap 1; `pEmitPos` is a
    world-space point object (NiPoint3/TGPoint3 with .x/.y/.z)."""
    if ship is None or pEmitPos is None:
        return
    try:
        wp = (float(pEmitPos.x), float(pEmitPos.y), float(pEmitPos.z))
    except (AttributeError, TypeError):
        return
    _pending.append({
        "ship": ship, "kind": "world",
        "pt": wp, "radius": float(fRadius), "age": 0.0,
    })


def clear_for(ship) -> None:
    """Drop a ship's not-yet-emitted volumes (DamageableObject.RemoveVisibleDamage).

    NOTE: clears only PENDING volumes. Clearing already-emitted carves needs a
    native HullCarveField::clear() + a `hull_carve_clear` binding (not yet
    implemented — Gap-1 follow-up)."""
    _pending[:] = [e for e in _pending if e["ship"] is not ship]


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _pending.clear()


def advance(dt=0.0, host=None, ship_instances=None) -> None:
    """Emit queued volumes for any ship whose render instance is now realized;
    keep the rest until they realize or age out. Raise-safe per entry."""
    if not _pending:
        return
    survivors = []
    for entry in _pending:
        try:
            keep = _advance_one(entry, float(dt), host, ship_instances)
        except Exception as _e:
            dev_mode.log_swallowed("visible damage advance", _e)
            keep = False
        if keep:
            survivors.append(entry)
    _pending[:] = survivors


def _advance_one(entry, dt, host, ship_instances) -> bool:
    """Emit one entry if its ship is realized (returns False -> drop it), else
    age it and keep it until MAX_PENDING_AGE."""
    ship = entry["ship"]
    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None or host is None or not hasattr(host, "hull_carve_add"):
        entry["age"] += dt
        return entry["age"] < MAX_PENDING_AGE

    world_pt, normal = _resolve(entry, ship)
    if world_pt is None:
        return False

    from engine.appc.hull_carve import MIN_CARVE_RADIUS_GU
    from engine.appc import damage_decals
    radius = max(MIN_CARVE_RADIUS_GU, entry["radius"]) * _radius_mod(ship)
    now = damage_decals.current_game_time()
    host.hull_carve_add(
        iid,
        (world_pt.x, world_pt.y, world_pt.z),
        (normal.x, normal.y, normal.z),
        radius,
        now,
    )
    return False   # emitted once -> drop


def _resolve(entry, ship):
    """Return (world_point, outward_normal) as TGPoint3s, or (None, None) when
    the ship carries no world transform."""
    if not hasattr(ship, "GetWorldLocation"):
        return None, None
    loc = ship.GetWorldLocation()
    px, py, pz = entry["pt"]

    if entry["kind"] == "world":
        world_pt = TGPoint3(px, py, pz)
        return world_pt, _outward_normal(world_pt, loc, ship)

    # Body frame: world = loc + R . (x, y, z); NO scale (BC stores authored
    # volumes in world units relative to the ship centre, like subsystem mounts
    # — see subsystems.subsystem_world_position).
    offset = TGPoint3(px, py, pz)
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            offset.MultMatrixLeft(rot)
    world_pt = TGPoint3(loc.x + offset.x, loc.y + offset.y, loc.z + offset.z)
    normal = TGPoint3(offset.x, offset.y, offset.z)   # outward radial
    if normal.Unitize() <= 1e-6:
        normal = _ship_up(ship)
    return world_pt, normal


def _outward_normal(world_pt, loc, ship):
    """Unit vector from the ship centre toward `world_pt`; ship-up at the centre."""
    n = TGPoint3(world_pt.x - loc.x, world_pt.y - loc.y, world_pt.z - loc.z)
    if n.Unitize() <= 1e-6:
        return _ship_up(ship)
    return n


def _ship_up(ship):
    """Ship world-up (R.GetCol(2)), or world +Z when unavailable."""
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if hasattr(rot, "GetCol"):
            up = rot.GetCol(2)
            return TGPoint3(up.x, up.y, up.z)
    return TGPoint3(0.0, 0.0, 1.0)


def _radius_mod(ship) -> float:
    """Per-ship visible-damage radius multiplier (SetVisibleDamageRadiusModifier),
    defaulting to 1.0. Guards against the TGObject _Stub fallback."""
    try:
        m = float(getattr(ship, "_vis_dmg_radius_mod", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return m if m > 0.0 else 1.0
