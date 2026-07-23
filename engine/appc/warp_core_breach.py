# engine/appc/warp_core_breach.py
"""Warp-core breach: the dramatic VFX layer when a ship's Warp Core
(PowerSubsystem) condition crosses from >0 to 0.

Armed once per ship by the objects.py zero-crossing hook (direct core kill,
hull-death cascade, or a neighbour's breach). detonate() — driven from
advance() — spawns a shockwave ring + schedules a hull carve at the core's
world position. Each ship detonates at most once; chains from further arms
resolve in the same tick via the non-recursive drain loop.

It deals NO damage: BC has no special warp-core AoE. Collateral damage on death
is BC's faithful m_splashDamage (loadspacehelper sets it on every ship),
applied by engine.appc.splash_damage from ship_death.begin — which fires on
this same warp-core death (subsystems.py calls both arm() and ship_death.begin).
The earlier artistic AoE (centre damage = core max condition over 40 GU) was
removed in favour of that faithful mechanism.

See docs/superpowers/specs/2026-06-20-warp-core-breach-design.md.
"""
import engine.dev_mode as dev_mode

BREACH_RADIUS_GU       = 40.0  # shockwave ring max radius; tuned to the dramatic
                               # visual (was 1.3, then 4.0, then 20.0). ~7 km.

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


def advance(dt: float, ship_instances=None) -> None:
    """Drain the armed queue, detonating each ship. Non-recursive: a detonation
    may arm further ships (chains), which this while-loop picks up in the same
    tick. The _breached guard guarantees termination."""
    while _armed:
        ship = _armed.pop(0)
        if ship in _breached:
            continue
        _breached.add(ship)
        # Module-global lookup so tests can monkeypatch `detonate`.
        detonate(ship, ship_instances=ship_instances)


def detonate(ship, ship_instances=None) -> None:
    """Warp-core breach VFX at the core's world position: a shockwave ring +
    a hull carve. No damage (splash_damage owns collateral). Raise-safe."""
    from engine.appc.subsystems import subsystem_world_position

    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return
    centre = subsystem_world_position(core, ship)

    try:
        from engine.appc import shockwaves
        shockwaves.spawn(centre, BREACH_RADIUS_GU, shockwaves.SHOCKWAVE_LIFETIME)
    except Exception as _e:
        dev_mode.log_swallowed("spawn warp core shockwave", _e)

    try:
        from engine.appc import core_breach_carve
        core_breach_carve.schedule(ship)
    except Exception as _e:
        dev_mode.log_swallowed("schedule core breach carve", _e)


def reset() -> None:
    """Clear the armed queue and breached set (mission swap / test teardown)."""
    _armed.clear()
    _breached.clear()
