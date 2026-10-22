# engine/appc/warp_core_breach.py
"""Warp-core breach: the dramatic VFX layer when a ship's Warp Core
(PowerSubsystem) condition crosses from >0 to 0.

Armed once per ship by the objects.py zero-crossing hook (direct core kill,
hull-death cascade, or a neighbour's breach). detonate() — driven from
advance() — spawns a shockwave ring and starts the hull wound: three Internal
hull-damage records growing at the core (t = 0, 0.5, 1.0 s; 0.4, 0.7, 1.0 x
R, R = clamp(0.25 x GetRadius(), 0.1, 1.2) GU, wear 10), then the part check.
The core sits inside the hull, so they tear it open from within — the
self-destruction the breach AoE skips (it skips the source ship). Each ship
detonates at most once; chains from further arms resolve in the same tick via
the non-recursive drain loop.

It deals NO damage: BC has no special warp-core AoE. Collateral damage on death
is BC's faithful m_splashDamage (loadspacehelper sets it on every ship),
applied by engine.appc.splash_damage from ship_death.begin — which fires on
this same warp-core death (subsystems.py calls both arm() and ship_death.begin).
The earlier artistic AoE (centre damage = core max condition over 40 GU) was
removed in favour of that faithful mechanism.

See docs/superpowers/specs/2026-06-20-warp-core-breach-design.md.
"""
import engine.dev_mode as dev_mode
from engine import host_io

BREACH_RADIUS_GU       = 40.0  # shockwave ring max radius; tuned to the dramatic
                               # visual (was 1.3, then 4.0, then 20.0). ~7 km.

# The hull wound: (seconds after detonation, fraction of R) per Internal
# record. R is a fraction of the ship's BOUNDING-SPHERE radius (GetRadius(),
# ~4 GU for a Galaxy): a big wound, not the whole ship.
CORE_RECORDS = ((0.0, 0.4), (0.5, 0.7), (1.0, 1.0))
CORE_RADIUS_SHIP_FRACTION = 0.25
CORE_RADIUS_MIN_GU = 0.1       # a tiny hull still shows a wound
CORE_RADIUS_MAX_GU = 1.2       # never the whole hull, whatever its size
CORE_WEAR = 10.0               # torn through at the core (internal_blast.STRENGTH)
_INTERNAL = 3                  # HullDamageStore kind: Internal

_armed: list = []      # ships queued to detonate (FIFO)
# Holds the ship objects themselves (not id()) so that CPython's id-reuse cannot
# cause a freshly-spawned ship to be silently skipped if it lands on a recycled
# address. Identity/strong-ref semantics match how _armed already uses `is`.
_breached: set = set()
# Growing wounds: {"ship", "age": s since detonation, "next": index into
# CORE_RECORDS}. Dropped once the last record lands or the ship stops
# rendering.
_growing: list = []


def arm(ship) -> None:
    """Queue `ship` to detonate. Idempotent: a ship already queued or already
    breached is ignored. This is the single-fire guarantee."""
    if ship is None or ship in _breached:
        return
    if any(s is ship for s in _armed):
        return
    _armed.append(ship)


def advance(dt: float, ship_instances=None) -> None:
    """Grow every wound already open by `dt`, then drain the armed queue,
    detonating each ship (a fresh wound lays its first record at once).
    Non-recursive: a detonation may arm further ships (chains), which this
    while-loop picks up in the same tick. The _breached guard guarantees
    termination."""
    _grow(float(dt), ship_instances)
    while _armed:
        ship = _armed.pop(0)
        if ship in _breached:
            continue
        _breached.add(ship)
        # Module-global lookup so tests can monkeypatch `detonate`.
        detonate(ship, ship_instances=ship_instances)


def detonate(ship, ship_instances=None) -> None:
    """Warp-core breach VFX at the core's world position: a shockwave ring +
    the hull wound. No damage (splash_damage owns collateral). Raise-safe."""
    from engine.appc.subsystems import subsystem_world_position

    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return
    centre = subsystem_world_position(core, ship)

    try:
        from engine.appc import shockwaves
        from engine.systems import frames
        shockwaves.spawn(centre, BREACH_RADIUS_GU, shockwaves.SHOCKWAVE_LIFETIME,
                         pSet=frames.containing_set(ship))
    except Exception as _e:
        dev_mode.log_swallowed("spawn warp core shockwave", _e)

    try:
        entry = {"ship": ship, "age": 0.0, "next": 0}
        if _emit_due(entry, ship_instances):
            _growing.append(entry)
    except Exception as _e:
        dev_mode.log_swallowed("start warp core wound", _e)


def core_radius_gu(ship) -> float:
    """R: the full wound radius, a clamped fraction of the ship's radius."""
    r = ship.GetRadius() if hasattr(ship, "GetRadius") else 1.0
    return max(CORE_RADIUS_MIN_GU,
               min(CORE_RADIUS_MAX_GU, CORE_RADIUS_SHIP_FRACTION * float(r)))


def _grow(dt: float, ship_instances) -> None:
    """Age every open wound and lay the records now due. Raise-safe per
    entry."""
    if not _growing:
        return
    survivors = []
    for entry in _growing:
        entry["age"] += dt
        try:
            keep = _emit_due(entry, ship_instances)
        except Exception as _e:
            dev_mode.log_swallowed("grow warp core wound", _e)
            keep = False
        if keep:
            survivors.append(entry)
    _growing[:] = survivors


def _emit_due(entry, ship_instances) -> bool:
    """Lay every record of `entry` whose time has come. True while records
    remain; False once the last has landed (and the part check has run) or
    the ship is not rendered / has no core."""
    ship = entry["ship"]
    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None:
        return False
    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return False
    from engine.appc.subsystems import subsystem_world_position
    from engine.appc.hit_feedback import _mesh_xyz
    core_world = subsystem_world_position(core, ship)
    normal = _core_normal(ship, core_world)
    big_r = core_radius_gu(ship)
    # The core sits in the ship's own set coordinates; the record speaks the
    # renderer's view coordinates (hit_feedback._mesh_xyz).
    point = _mesh_xyz(ship, core_world)
    while (entry["next"] < len(CORE_RECORDS)
           and CORE_RECORDS[entry["next"]][0] <= entry["age"] + 1e-6):
        fraction = CORE_RECORDS[entry["next"]][1]
        host_io.hull_damage_add(iid, point, (normal.x, normal.y, normal.z),
                                big_r * fraction, CORE_WEAR, _INTERNAL)
        entry["next"] += 1
    if entry["next"] < len(CORE_RECORDS):
        return True
    from engine.appc import hull_breakup
    hull_breakup.after_wear(ship, iid, ship_instances)
    return False


def _core_normal(ship, core_world):
    """World normal for the wound: from the ship centre through the core,
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


def reset() -> None:
    """Clear the armed queue, breached set and open wounds (mission swap /
    test teardown)."""
    _armed.clear()
    _breached.clear()
    _growing.clear()
