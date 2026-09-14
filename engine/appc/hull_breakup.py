"""After a carve lands: did it sever anything, and if so, what comes off.

The single hook for every carve emission site (combat in hit_feedback,
authored / cascade in visible_damage), so weapons, collisions and the death
cascade all sever the same way. Spec: docs/superpowers/specs/
2026-09-11-breakable-hull-components-design.md.

Connectivity is a full-lattice BFS, so it is not free: `after_carve` is
throttled per ship to `kBreakupCheckInterval`. A carve that lands inside the
window marks the ship *pending* rather than being dropped -- `drain()`,
called once per frame from host_loop, runs the deferred check as soon as the
window has elapsed. A sever detected half a second late is invisible; running
the BFS on every one of ten carves a second on eight ships is not.

The native side (`hull_split_detached`) also asks a cheap local question
before the BFS: after an instance's first check, a carve that its own
neighbourhood proves harmless -- see `voxel::hull_severance_local` -- skips
the full flood, and a check with no carve since the last one returns at
once. So the throttle here bounds the RATE; the native check bounds the
COST. Neither replaces the other.
"""
import engine.dev_mode as dev_mode
from engine import host_io
from engine.appc import damage_geometry, debris_chunk
from engine.appc.math import TGPoint3

kBreakupCheckInterval = 0.5   # s; the full BFS is still the worst case

_last_check: dict = {}        # id(ship) -> game time of last split
_pending: dict = {}           # id(ship) -> (ship, iid, ship_instances)


def _now():
    from engine.appc import damage_decals
    return damage_decals.current_game_time()


def after_carve(ship, iid, ship_instances=None, now=None):
    """Run after ANY carve on `iid`. No-op unless the ship may shed chunks.
    Returns the DebrisChunks spawned by this call -- a carve deferred by the
    throttle returns [] here and is drained (and its spawns realized) later
    by drain()."""
    if iid is None or not damage_geometry.breakables_allowed_for(ship):
        return []
    now = _now() if now is None else now
    key = id(ship)
    if now - _last_check.get(key, -1e9) < kBreakupCheckInterval:
        _pending[key] = (ship, iid, ship_instances)
        return []
    return _check(ship, iid, ship_instances, now)


def drain(now=None):
    """Per frame: run the split for every ship that took a carve inside its
    throttle window, once the window has elapsed."""
    now = _now() if now is None else now
    for key, (ship, iid, si) in list(_pending.items()):
        if now - _last_check.get(key, -1e9) >= kBreakupCheckInterval:
            del _pending[key]
            _check(ship, iid, si, now)


def reset():
    _last_check.clear(); _pending.clear()


def _check(ship, iid, ship_instances, now):
    """The actual split: connectivity, chunk spawns, bursts, subsystem kill.
    Always call with the throttle already cleared for `ship`."""
    _last_check[id(ship)] = now
    try:
        comps = host_io.hull_split_detached(iid, debris_chunk.kChunkMinCells)
    except Exception as _e:
        dev_mode.log_swallowed("hull_split_detached", _e)
        return []
    if not comps:
        return []

    main_cells = int(comps[0].get("main_body_cells", 0))
    total_cells = main_cells + sum(int(c["cells"]) for c in comps)
    parent_mass = float(ship.GetMass()) if hasattr(ship, "GetMass") else 1.0

    spawned = []
    for c in comps:
        _destroy_subsystems_inside(ship, c["bounds_min"], c["bounds_max"])
        if c.get("instance_id") is None:
            _burst(ship, iid, tuple(c["centroid"]))
            continue
        try:
            spawned.append(debris_chunk.spawn(
                c["instance_id"], ship, int(c["cells"]), tuple(c["centroid"]),
                float(c["radius_gu"]), parent_mass, total_cells))
        except Exception as _e:
            dev_mode.log_swallowed("debris_chunk.spawn", _e)
            # The native side created this instance BEFORE we got here.
            # With no body to own it, it would sit in the scene for the
            # rest of the mission -- outside the cap, the swap clear and
            # the collision system. Lazy import: engine.renderer binds the
            # host extension.
            try:
                from engine import renderer
                renderer.destroy_instance(c["instance_id"])
            except Exception as _e2:
                dev_mode.log_swallowed("orphaned chunk instance destroy", _e2)
    return spawned


def _destroy_subsystems_inside(ship, lo, hi):
    """A nacelle that has physically left the ship cannot remain a working
    warp engine: destroy every subsystem whose BODY-frame mount lies in the
    component's bounds (GU, body frame -- GetPosition() is already that).

    Destruction goes straight through SetCondition(0.0) (subsystems.py:571),
    the single state-change hook that fires _condition_changed() -- the
    destroyed-event source -- rather than through ship.DamageSystem."""
    it = getattr(ship, "_iter_subsystems", None)
    if it is None:
        from engine.appc.combat import _iter_subsystems as it_fn
        subs = it_fn(ship)
    else:
        subs = it()
    for sub in subs:
        pos = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if not isinstance(pos, TGPoint3):
            continue
        if (lo[0] <= pos.x <= hi[0] and lo[1] <= pos.y <= hi[1]
                and lo[2] <= pos.z <= hi[2]):
            try:
                if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
                    continue
                sub.SetCondition(0.0)
            except Exception as _e:
                dev_mode.log_swallowed("severed subsystem destroy", _e)


def _burst(ship, iid, centroid_gu):
    """Sub-floor component: the material is gone; show the existing breach
    VFX (debris, venting, rim) at its centroid rather than spawning a chunk
    instance for a handful of cells."""
    try:
        host_io.breach_burst(iid, centroid_gu, 0.1)
    except Exception as _e:
        dev_mode.log_swallowed("severed component burst", _e)
