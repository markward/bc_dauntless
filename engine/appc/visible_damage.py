# engine/appc/visible_damage.py
"""BC visible-damage API -> hull-carve renderer.

The SDK's pre-wreck `Damage*.py` scripts (authored by the original DamageTool)
call `pShip.AddObjectDamageVolume(x, y, z, influRad, strength)` — a body-frame
damage sphere — and `Effects.DeathExplosionDamage` calls the runtime sibling
`pShip.AddDamage(pEmitPos, fRadius, fDamage)`. `DamageableObject` routes both
here.

The carve emitter (`host_io.hull_carve_add`) needs the ship->instance-id map,
which only exists in the host-loop tick. But the authored
calls arrive during a mission's `Initialize`, BEFORE the set's render instances
are realized (the ship has no `iid` yet). So we QUEUE each request and DRAIN it
per-tick from `advance()` once the ship's instance is realized — the same
deferred pattern as `engine/appc/core_breach_carve.py`. Authored damage bypasses
the combat path's eligibility gate and emit throttle (it is content, not beam
clutter) and emits all of a ship's volumes at once.

`strength` (Gap 2) is accepted for call-shape fidelity but unused here; only the
sphere position + radius drive a Gap-1 carve.

See docs/engine/damagetool-and-hull-damage-gaps.md.
"""
import engine.dev_mode as dev_mode
from engine import host_io
from engine.appc.math import TGPoint3, TGMatrix3

# Pending requests linger at most this long (game seconds) waiting for the
# ship's render instance to be realized, then drop — so a headless run, a culled
# ship, or a failed spawn never leaks an un-emittable entry.
MAX_PENDING_AGE = 5.0

# Standoff (GU) for the surface-normal probe in `_mesh_normal`: the ray starts
# this far outside the sample point along the radial and casts twice as far
# back inward. Small and local on purpose -- a long cast from outside the
# bounding sphere would hit whatever hull piece happens to be in front (a
# nacelle occluding the saucer) rather than the surface actually being carved.
NORMAL_PROBE_MARGIN_GU = 0.5

# Registry of not-yet-emitted volumes. Each entry:
#   {"ship", "kind": "body"|"world", "pt": (x, y, z), "radius": float, "age": float}
_pending: list[dict] = []


def queue_body_volume(ship, x, y, z, influRad, strength=0.0) -> None:
    """Queue an authored body-frame damage sphere (SDK AddObjectDamageVolume).
    `influRad` is the metaball influence radius (merge proximity + size floor);
    `strength` is the BC field strength (300/600) that also accumulates with
    nearby combat damage."""
    if ship is None:
        return
    _pending.append({
        "ship": ship, "kind": "body",
        "pt": (float(x), float(y), float(z)),
        "influ": float(influRad), "strength": float(strength), "age": 0.0,
    })


def queue_world_carve(ship, pEmitPos, fRadius, fDamage=0.0) -> None:
    """Queue a runtime world-space carve (DamageableObject.AddDamage, e.g.
    Effects.DeathExplosionDamage). `pEmitPos` is a world-space point object
    (NiPoint3/TGPoint3 with .x/.y/.z); `fDamage` is the BC field strength."""
    if ship is None or pEmitPos is None:
        return
    try:
        wp = (float(pEmitPos.x), float(pEmitPos.y), float(pEmitPos.z))
    except (AttributeError, TypeError):
        return
    _pending.append({
        "ship": ship, "kind": "world",
        "pt": wp, "influ": float(fRadius), "strength": float(fDamage), "age": 0.0,
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


def advance(dt=0.0, ship_instances=None) -> None:
    """Emit queued volumes for any ship whose render instance is now realized;
    keep the rest until they realize or age out. Raise-safe per entry."""
    if not _pending:
        return
    survivors = []
    for entry in _pending:
        try:
            keep = _advance_one(entry, float(dt), ship_instances)
        except Exception as _e:
            dev_mode.log_swallowed("visible damage advance", _e)
            keep = False
        if keep:
            survivors.append(entry)
    _pending[:] = survivors


def _advance_one(entry, dt, ship_instances) -> bool:
    """Emit one entry if its ship is realized (returns False -> drop it), else
    age it and keep it until MAX_PENDING_AGE."""
    ship = entry["ship"]
    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None:
        entry["age"] += dt
        return entry["age"] < MAX_PENDING_AGE

    world_pt, normal = _resolve(entry, ship, iid)
    if world_pt is None:
        return False

    from engine.appc.hull_carve import MIN_CARVE_RADIUS_GU
    from engine.appc import damage_decals
    influ = entry["influ"]
    strength = entry["strength"]
    # Authored / runtime carves carry their own size: a floor (so the wreck is
    # visible at spawn regardless of the strength curve) plus the strength, which
    # also accumulates with nearby combat damage in the C++ field.
    rad_mod = _radius_mod(ship)
    floor = max(MIN_CARVE_RADIUS_GU, influ) * rad_mod
    now = damage_decals.current_game_time()
    # Carve sizes are absolute; the only per-ship scale is BC's DamageRadMod
    # (applied to both the authored `floor` and the strength curve). The authored
    # `floor` still guarantees the wreck's visible size.
    host_io.hull_carve_add(
        iid,
        (world_pt.x, world_pt.y, world_pt.z),
        (normal.x, normal.y, normal.z),
        influ,
        strength,
        now,
        floor,
        rad_mod,
    )
    return False   # emitted once -> drop


def _resolve(entry, ship, iid=None):
    """Return (world_point, outward_normal) as TGPoint3s, or (None, None) when
    the ship carries no world transform."""
    if not hasattr(ship, "GetWorldLocation"):
        return None, None
    loc = ship.GetWorldLocation()
    px, py, pz = entry["pt"]

    if entry["kind"] == "world":
        world_pt = TGPoint3(px, py, pz)
        radial = _outward_normal(world_pt, loc, ship)
        mesh = _mesh_normal(iid, world_pt, radial)
        return world_pt, (radial if mesh is None else mesh)

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


def _mesh_normal(iid, world_pt, radial):
    """The TRUE hull surface normal at `world_pt`, or None if unobtainable.

    WHY THIS MATTERS MORE THAN IT LOOKS. The shader's carve is an OBLATE built
    around this normal (opaque.frag): the full lateral radius `r`, but only
    `kDepthFactor * r` (0.45) along the normal itself. So the normal decides
    which way the hole is squashed and how deep it cuts.

    `_outward_normal`'s radial-from-centre guess is nearly TANGENTIAL on a wide
    flat structure -- a Galaxy saucer sits ~2 GU off the axis but only ~0.3 GU
    above centre, so the radial direction is almost horizontal where the real
    surface normal is almost vertical. That lays the oblate's shallow axis ALONG
    the hull, cutting a narrow slot across the plate instead of a broad shallow
    crater through it, and leaves the hole up to 55% narrower in that direction.
    The same normal also aims `carve_has_backing`'s inward probe (frame.cc), so a
    wrong one can drop the carve outright.

    The combat path never had this problem -- it passes ray_trace's mesh normal
    and skips the carve entirely when it only has a sphere-entry fallback
    (hit_feedback.py). This gives the AddDamage path the same quality of normal:
    stand off along the radial and cast back inward, taking the first hit.
    ray_trace flips its normal against the incoming ray, so the result is
    outward-facing, matching the convention decals and carves already use.

    Raise-safe and miss-safe: the caller keeps the radial guess, because an
    approximate carve beats no carve (authored wrecks must still appear
    headless, where there is no instance to trace against).
    """
    if iid is None or radial is None:
        return None
    try:
        origin = (world_pt.x + radial.x * NORMAL_PROBE_MARGIN_GU,
                  world_pt.y + radial.y * NORMAL_PROBE_MARGIN_GU,
                  world_pt.z + radial.z * NORMAL_PROBE_MARGIN_GU)
        hit = host_io.ray_trace_mesh(
            iid, origin, (-radial.x, -radial.y, -radial.z),
            NORMAL_PROBE_MARGIN_GU * 2.0)
    except Exception as _e:
        dev_mode.log_swallowed("probe carve surface normal", _e)
        return None
    if not hit:
        return None
    nx, ny, nz = hit[1]
    normal = TGPoint3(float(nx), float(ny), float(nz))
    return None if normal.Unitize() <= 1e-6 else normal


def _outward_normal(world_pt, loc, ship):
    """Unit vector from the ship centre toward `world_pt`; ship-up at the centre.

    Fallback only for world carves -- see `_mesh_normal` for why a real surface
    normal is worth the ray cast. Still the primary path for BODY-frame authored
    volumes, whose points sit inside the hull rather than on its surface, so
    there is no surface to probe."""
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
