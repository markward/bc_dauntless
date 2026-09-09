"""Push BC's authored damage-volume resolution to the hull-volume baker.

`ShipProperty.SetDamageResolution` is authored per ship in every hardpoint file
-- Shuttle 6, Akira 8, Galaxy 10, Warbird 12, stations 15 -- and copied onto the
ship by `ShipClass` property application. Until now nothing read it.

It is NOT a cell size: it is a per-ship detail RATIO (Shuttle 6, Akira 8,
Galaxy 10, Warbird 12, stations 15). The native baker (`HullVolumeCache::get`)
derives the actual bake cell size, in model units, as `authored_res / quality`,
where quality is a global fidelity multiplier -- see
`native/src/voxel/include/voxel/hull_volume_cache.h`. It is also finer than
what BC itself shipped (Galaxy 10 vs a baked 15, Akira 8
vs 15, Warbird 12 vs 25) -- and the Warbird, the worst mismatch in the fleet, is
exactly the ship whose breaches were seen cutting into nothing.

See docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md
"""
from engine import renderer as _renderer

__all__ = ["push_resolution", "prewarm_field"]


def push_resolution(ship, iid) -> bool:
    """Send `ship`'s authored resolution for instance `iid`.

    Returns True only when a positive resolution was actually pushed. A ship
    that never had one keeps the native default rather than being handed 0.0,
    which the baker would divide by.

    A missing/non-numeric GetDamageResolution is a data problem on the ship,
    not an engine fault, and is swallowed (returns False). A failure from the
    renderer call itself -- a stale .so missing the binding, a broken pybind
    arg type -- is NOT swallowed here: it propagates so the caller can log it.
    Both host_loop call sites wrap this call in their own
    try/except + dev_mode.log_swallowed, which is the intended visibility
    mechanism for that class of failure; catching it here too would silently
    disable that logging forever, indistinguishable from "no ship authored a
    resolution".
    """
    getter = getattr(ship, "GetDamageResolution", None)
    if getter is None:
        return False
    try:
        resolution = float(getter())
    except (TypeError, ValueError):
        return False
    if not resolution > 0.0:
        return False
    _renderer.hull_volume_set_resolution(iid, resolution)
    return True


def prewarm_field(iid) -> None:
    """Force this instance's hull damage field to bake now, at spawn time.

    Design spec §4 puts the bake "on first use of a hull, during model
    load" -- without a pre-warm call, nothing runs `HullVolumeCache::get`
    until the FIRST `hull_carve_add` deposit against that hull, which
    happens mid-combat. That bake is a full NIF re-parse, voxelization, a
    distance transform, and up to a ~2.4 MB `.dhv` write: spec-measured at
    57ms (Galor) to 192ms (Warbird) -- 4-12 dropped frames the first time
    the player hits each new hull class. Calling this right after
    `push_resolution`, at spawn, moves that cost to mission load instead,
    matching the spec.

    No-op (not an error) when no authored resolution has been pushed for
    this hull -- there is nothing to bake at the native default.

    Same error contract as `push_resolution`: a real failure from the
    renderer call itself (a stale .so missing the binding, a broken pybind
    arg type) is NOT swallowed here -- it propagates so the caller can log
    it. Both host_loop call sites wrap this call in their own
    try/except + dev_mode.log_swallowed, exactly as they already do for
    push_resolution, so a prewarm failure can never block a spawn.
    """
    _renderer.hull_volume_prewarm(iid)
