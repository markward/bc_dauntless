# engine/appc/subsystem_cascade.py
"""Hull-death subsystem cascade: zero every subsystem CASCADE_DELAY seconds
after the hull reaches 0.

This is BC's "destroy broken systems" behaviour. Zeroing the warp core during
the cascade drives its condition across 0, which the objects.py zero-crossing
hook turns into a warp_core_breach.arm(ship). Gated by the SDK-faithful
ship.IsDestroyBrokenSystems() flag (default ON) so a mission's
SetDestroyBrokenSystems(0) derelict keeps its subsystems.

See docs/superpowers/specs/2026-06-20-warp-core-breach-design.md.
"""
import engine.dev_mode as dev_mode

CASCADE_DELAY = 1.5  # seconds from hull-0 to all-subsystems-0

# Registry of pending cascades: each entry is {"ship": ship, "time_left": float}.
_active: list[dict] = []


def _destroy_broken_systems(ship) -> bool:
    """Honour ship.IsDestroyBrokenSystems(); default ON when absent (fakes).

    Uses ids.implements(), NOT hasattr(): a real ShipClass that had no such
    method still answered hasattr() truthily via the TGObject _Stub, so
    bool(ship.IsDestroyBrokenSystems()) was ALWAYS True and every
    SetDestroyBrokenSystems(0) opt-out (E3M2's derelict Warbird) was silently
    ignored. See docs/stub_heatmap.md / project_ship_motion_drift_stub_bug.
    """
    from engine.core.ids import implements
    if not implements(ship, "IsDestroyBrokenSystems"):
        return True
    return bool(ship.IsDestroyBrokenSystems())


def schedule(ship) -> None:
    """Register a CASCADE_DELAY-second cascade for `ship`. Idempotent and
    gated by the SDK flag: a ship that opts out (SetDestroyBrokenSystems(0))
    or is already scheduled is ignored."""
    if ship is None or not _destroy_broken_systems(ship):
        return
    for entry in _active:
        if entry["ship"] is ship:
            return
    _active.append({"ship": ship, "time_left": CASCADE_DELAY})


def advance(dt: float) -> None:
    """Tick every pending cascade; on expiry, zero all subsystems. Prunes."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        entry["time_left"] -= dt
        if entry["time_left"] > 0.0:
            survivors.append(entry)
            continue
        _fire(entry["ship"])
    _active[:] = survivors


def _fire(ship) -> None:
    """DestroySystem every subsystem on `ship` (hull + warp core + leaves),
    each at most once. Raise-safe — a cascade failure must not kill the tick."""
    try:
        seen = set()
        targets = []
        for getter in ("GetHull", "GetPowerSubsystem"):
            if hasattr(ship, getter):
                s = getattr(ship, getter)()
                if s is not None and id(s) not in seen:
                    seen.add(id(s))
                    targets.append(s)
        from engine.appc.combat import _iter_subsystems
        for s in _iter_subsystems(ship):
            if s is not None and id(s) not in seen:
                seen.add(id(s))
                targets.append(s)
        for s in targets:
            if hasattr(ship, "DestroySystem"):
                ship.DestroySystem(s)
    except Exception as _e:
        dev_mode.log_swallowed("subsystem cascade fire", _e)


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
