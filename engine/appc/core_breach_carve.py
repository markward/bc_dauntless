# engine/appc/core_breach_carve.py
"""Warp-core breach hull carve: one big growing voxel hole at the warp core.

warp_core_breach.detonate schedules a carve on the exploding ship; advance()
grows it over GROW_DURATION and emits it each tick via host.hull_carve_add at
the warp core's world position. The core sits inside the hull, so a carve there
punches a hole through and exposes the interior — the self-destruction the
breach AoE skips (it skips the source ship). Reuses the existing carve binding
and render pass; no native changes.

See docs/superpowers/specs/2026-06-20-warp-core-breach-hull-carve-design.md.
"""
import engine.dev_mode as dev_mode

GROW_DURATION            = 1.5   # seconds the hole grows to full size
# Carve radius as a fraction of the ship BOUNDING-SPHERE radius (GetRadius(),
# ~4 GU for a Galaxy). Kept small: the carve is a big hull WOUND, not the whole
# ship. The weapon-hit carves the renderer is built around are ~0.25-0.5 GU.
MAX_RADIUS_SHIP_FRACTION = 0.25
# Hard ceiling (GU). The breach render pass degenerates into a flat cross-section
# when a carve approaches the hull's smallest dimension (Galaxy thin axis ~0.67
# GU half-extent), so never let the carve grow into that regime regardless of
# ship size.
MAX_RADIUS_GU            = 1.2
MIN_RADIUS_GU            = 0.1   # floor so the first growing frame is visible

# Registry of in-progress core breaches: each entry is {"ship": ship, "age": float}.
_active: list[dict] = []


def schedule(ship) -> None:
    """Register a growing core-breach carve for `ship`. Idempotent per ship;
    no-op when the ship has no warp core (PowerSubsystem)."""
    if ship is None:
        return
    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return
    for entry in _active:
        if entry["ship"] is ship:
            return
    _active.append({"ship": ship, "age": 0.0})


def _ease_out(t: float) -> float:
    """Fast-then-settle growth curve, 0..1."""
    return 1.0 - (1.0 - t) * (1.0 - t)


def _carve_normal(ship, core_world):
    """World normal for rim orientation: from the ship centre through the core,
    falling back to the ship up axis when the core is at the centre."""
    from engine.appc.math import TGPoint3
    loc = ship.GetWorldLocation()
    dx = core_world.x - loc.x
    dy = core_world.y - loc.y
    dz = core_world.z - loc.z
    mag = (dx * dx + dy * dy + dz * dz) ** 0.5
    if mag > 1e-6:
        return TGPoint3(dx / mag, dy / mag, dz / mag)
    if hasattr(ship, "GetWorldRotation"):
        up = ship.GetWorldRotation().GetCol(2)
        return TGPoint3(up.x, up.y, up.z)
    return TGPoint3(0.0, 0.0, 1.0)


def advance(dt: float, host=None, ship_instances=None) -> None:
    """Grow + emit each active core-breach carve. Drops an entry when it reaches
    full size or its ship is no longer rendered. Raise-safe per entry."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        try:
            keep = _advance_one(entry, dt, host, ship_instances)
        except Exception as _e:
            dev_mode.log_swallowed("core breach carve advance", _e)
            keep = False
        if keep:
            survivors.append(entry)
    _active[:] = survivors


def _advance_one(entry, dt, host, ship_instances) -> bool:
    """Advance one entry; emit its carve. Returns True to keep it active, False
    to drop it (full size reached, or the ship is no longer rendered)."""
    ship = entry["ship"]
    entry["age"] += float(dt)
    t = min(1.0, entry["age"] / GROW_DURATION)

    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None or host is None or not hasattr(host, "hull_carve_add"):
        return False

    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return False

    from engine.appc.subsystems import subsystem_world_position
    from engine.appc import damage_decals
    core_world = subsystem_world_position(core, ship)
    radius_full = min(MAX_RADIUS_GU, MAX_RADIUS_SHIP_FRACTION * (
        ship.GetRadius() if hasattr(ship, "GetRadius") else 1.0))
    radius = max(MIN_RADIUS_GU, radius_full * _ease_out(t))
    normal = _carve_normal(ship, core_world)
    now = damage_decals.current_game_time()

    host.hull_carve_add(
        iid,
        (core_world.x, core_world.y, core_world.z),
        (normal.x, normal.y, normal.z),
        radius,
        now,
    )
    return t < 1.0   # drop once the full-size carve has been emitted


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
