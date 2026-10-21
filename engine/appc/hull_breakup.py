"""After plating wear lands: did it cut a piece off, and if so, what comes off.

The single hook for every wear site (combat in hull_wear, the AddDamage /
death-cascade and warp-core records in visible_damage and warp_core_breach,
internal_blast), so weapons, collisions and deaths all sever the same way.
Spec: docs/superpowers/specs/2026-09-11-breakable-hull-components-design.md
(the original carve-driven design) and the layered hull damage specs.

`after_wear` asks the native side (`host_io.hull_split_parts`) to break off
every PIECE the wear has cut from the main body -- the structure parts that
leave together, as one chunk (Ruling 4) -- hiding them on the parent and
instancing a chunk that draws only them. The check is not free, so it is
throttled per ship to `kBreakupCheckInterval`: wear that lands inside the
window marks the ship *pending* rather than being dropped, and `drain()`,
called once per frame from host_loop, runs the deferred check as soon as the
window has elapsed. A sever detected half a second late is invisible.

Rocks never sever this way (they crumble: engine.rocks.death), and an
articulated ship's parts leave through part_severance instead.
"""
import weakref

import engine.dev_mode as dev_mode
from engine import host_io
from engine.core import frame_profiler
from engine.appc import damage_geometry, debris_chunk
from engine.appc.math import TGPoint3

kBreakupCheckInterval = 0.5   # s; the full BFS is still the worst case

_last_wear_check: dict = {}   # id(ship) -> game time of last part check
_pending_wear: dict = {}      # id(ship) -> (ship, iid, ship_instances)
_severed: dict = {}           # id(ship) -> (weakref(ship), iid, {part, ...}) spawned
# iid -> (severed mask, {(x, y, z, scale): structure part label}): the
# per-frame `on_severed_part` labels. A label depends only on the instance and
# the authored rest point, so after a severance each light is labelled once
# per mask rather than every frame; a new severance (mask change) relabels.
# Dropped with the instance (`forget_instance`) and on mission swap (`reset`).
_part_labels: dict = {}


def _now():
    from engine.appc import damage_decals
    return damage_decals.current_game_time()


def after_wear(ship, iid, ship_instances=None, now=None):
    """Run after plating wear reaches `iid`'s store. No-op unless the ship may
    shed parts (a rock never does). Returns the DebrisChunks spawned by this
    call -- wear inside the throttle window returns [] here and is drained
    (and its spawns realized) later by drain()."""
    if iid is None or not damage_geometry.breakables_allowed_for(ship):
        return []
    from engine.rocks import rock as _rock
    if _rock.is_rock(ship):
        return []
    # An articulated ship's parts leave through part_severance. At rest it
    # carries no node overrides (identity ones are erased), so the native
    # articulation gate cannot see the rig: gate on it here, or the same
    # nacelle would sever twice.
    from engine.appc import articulation
    if articulation.parts_for_ship(ship):
        return []
    now = _now() if now is None else now
    key = id(ship)
    if now - _last_wear_check.get(key, -1e9) < kBreakupCheckInterval:
        _pending_wear[key] = (ship, iid, ship_instances)
        return []
    return _check_parts(ship, iid, now)


def drain(now=None):
    """Per frame: run the split for every ship that took wear inside its
    throttle window, once the window has elapsed."""
    now = _now() if now is None else now
    for key, (ship, iid, _si) in list(_pending_wear.items()):
        if now - _last_wear_check.get(key, -1e9) >= kBreakupCheckInterval:
            del _pending_wear[key]
            _check_parts(ship, iid, now)


def reset():
    _last_wear_check.clear(); _pending_wear.clear(); _severed.clear()
    _part_labels.clear()


def forget_instance(iid) -> None:
    """Drop `iid`'s cached part labels when its render instance is destroyed:
    a recycled id must not inherit a destroyed hull's labels."""
    _part_labels.pop(iid, None)


def _check_parts(ship, iid, now):
    """The structure-part split: native check, chunk spawns, subsystem kill.
    Always call with the wear throttle already cleared for `ship`."""
    _last_wear_check[id(ship)] = now
    try:
        with frame_profiler.scope("hb.split_parts"):
            parts = host_io.hull_split_parts(iid)
    except Exception as _e:
        dev_mode.log_swallowed("hull_split_parts", _e)
        return []
    if not parts:
        return []
    # The native side reports a part once (the parent's severed bits); this
    # guard keeps a part from ever spawning or killing twice on this side.
    # A weak reference (as debris_chunk keeps its origin ship): the record
    # must never keep a dead ship alive.
    entry = _severed.get(id(ship))
    if entry is None or entry[0]() is not ship or entry[1] != iid:
        entry = (weakref.ref(ship), iid, set())
        _severed[id(ship)] = entry
    done = entry[2]
    fresh = []
    for p in parts:
        members = {int(i) for i in p.get("parts", ())}
        if not members or members & done:
            # Native instanced a chunk for it before we got here: no body
            # will own it, so it must not stay in the scene.
            _destroy_orphan(p.get("instance_id"))
            continue
        done |= members
        fresh.append(p)
    if not fresh:
        return []

    total = int(fresh[0].get("total_voxels", 0))
    parent_mass = float(ship.GetMass()) if hasattr(ship, "GetMass") else 1.0
    comps = [{"instance_id": p.get("instance_id"), "cells": int(p["voxels"]),
              "centroid": p["centroid"], "bounds_min": p["bounds_min"],
              "bounds_max": p["bounds_max"], "radius_gu": p["radius_gu"],
              "parts": {int(i) for i in p["parts"]}}
             for p in fresh]
    spawned = []
    with frame_profiler.scope("hb.spawn"):
        _spawn_components(ship, iid, comps, parent_mass, total, spawned)
    return spawned


def _spawn_components(ship, iid, comps, parent_mass, total_cells, spawned):
    for c in comps:
        inside = _destroy_subsystems_inside(ship, c["bounds_min"],
                                            c["bounds_max"], iid, c.get("parts"))
        _silence_emitters_inside(ship, iid, c["bounds_min"], c["bounds_max"],
                                 c.get("parts"), inside)
        if c.get("instance_id") is None:
            _burst(ship, iid, tuple(c["centroid"]))
            continue
        try:
            spawned.append(debris_chunk.spawn(
                c["instance_id"], ship, int(c["cells"]), tuple(c["centroid"]),
                float(c["radius_gu"]), parent_mass, total_cells))
        except Exception as _e:
            dev_mode.log_swallowed("debris_chunk.spawn", _e)
            _destroy_orphan(c["instance_id"])


def _destroy_orphan(chunk_iid):
    """The native side created this chunk instance BEFORE we got here. With
    no body to own it, it would sit in the scene for the rest of the mission
    -- outside the cap, the swap clear and the collision system. Lazy
    import: engine.renderer binds the host extension."""
    if chunk_iid is None:
        return
    try:
        from engine import renderer
        renderer.destroy_instance(chunk_iid)
    except Exception as _e2:
        dev_mode.log_swallowed("orphaned chunk instance destroy", _e2)


def _destroy_subsystems_inside(ship, lo, hi, iid=None, parts=None):
    """A nacelle that has physically left the ship cannot remain a working
    warp engine: destroy every subsystem whose BODY-frame mount lies in the
    component's bounds (GU, body frame -- GetPosition() is already that), and
    return every subsystem inside (already-destroyed ones too: their particle
    emitters must still stop).

    A severed PIECE (`parts`, structure part indices) decides by the voxel
    label instead: its bounding box can reach over main-body mounts, so a
    mount whose voxel is labelled dies only when its part left with the
    piece. An unlabelled mount (-1: off the voxels, parts not ready) falls
    back to the bounds.

    Destruction goes straight through SetCondition(0.0) (subsystems.py:571),
    the single state-change hook that fires _condition_changed() -- the
    destroyed-event source -- rather than through ship.DamageSystem."""
    it = getattr(ship, "_iter_subsystems", None)
    if it is None:
        from engine.appc.combat import _iter_subsystems as it_fn
        subs = it_fn(ship)
    else:
        subs = it()
    inside = []
    for sub in subs:
        pos = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if not isinstance(pos, TGPoint3):
            continue
        if not _in_piece(ship, iid, (pos.x, pos.y, pos.z), lo, hi, parts):
            continue
        inside.append(sub)
        try:
            if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
                continue
            sub.SetCondition(0.0)
        except Exception as _e:
            dev_mode.log_swallowed("severed subsystem destroy", _e)
    return inside


def _in_piece(ship, iid, point, lo, hi, parts) -> bool:
    """Whether an authored body-frame point (SHIP units) left with the piece:
    its voxel label when it has one, else the piece's bounds (GAME units, so
    the point is scaled by the hull's `GetScale()` first, as
    `part_at_rest_point` does)."""
    label = part_at_rest_point(ship, iid, point) if parts else -1
    if label >= 0:
        return label in parts
    k = _ship_scale(ship)
    x, y, z = point[0] * k, point[1] * k, point[2] * k
    return (lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] and lo[2] <= z <= hi[2])


def _silence_emitters_inside(ship, iid, lo, hi, parts, inside_subs):
    """Stop every particle controller still emitting from the piece that
    left: from one of `inside_subs`, or from `ship` at a body point inside
    the piece. The structure-part twin of
    `part_severance._silence_emitters_on`, with both of its legs (identity on
    `_emit_from`; position on `_emit_pos`, since every real hull emitter is
    attached to the SHIP) and the same inside-test as the subsystem kill
    (`_in_piece`), so a subsystem and its smoke cannot disagree.

    `_emit_pos` is body-frame MODEL units (`host_io.world_to_body`'s
    output); scaled to SHIP units before the test, as part_severance does.
    Best-effort: the piece has already gone."""
    try:
        from engine.appc import particles
        live = particles.active()
    except Exception as _e:
        dev_mode.log_swallowed("severed piece emitter silence", _e)
        return
    if not live:
        return
    from engine.appc.part_severance import MODEL_TO_SHIP
    dead = {id(s) for s in inside_subs}
    for c in list(live):
        try:
            emit_from = getattr(c, "_emit_from", None)
            if id(emit_from) in dead:
                c.stop_emitting()
                continue
            if emit_from is not ship:
                continue
            pos = getattr(c, "_emit_pos", None)
            if pos is None:
                continue
            if hasattr(pos, "x"):
                point = (pos.x, pos.y, pos.z)
            elif isinstance(pos, (tuple, list)) and len(pos) == 3:
                point = tuple(pos)
            else:
                continue
            point = tuple(float(v) * MODEL_TO_SHIP for v in point)
            if _in_piece(ship, iid, point, lo, hi, parts):
                c.stop_emitting()
        except Exception as _e:
            dev_mode.log_swallowed("severed piece emitter silence", _e)


def part_at_rest_point(ship, iid, point) -> int:
    """The structure part whose voxel holds an AUTHORED body-frame point of
    `ship` -- a hardpoint mount (`GetPosition()`), a light's rest position --
    or -1 (off the voxels, parts not detected yet, stale id, headless).

    Authored points are SHIP units: unscaled, model units x BC_MODEL_SCALE.
    `structure_part_at` takes GAME units and divides by the instance's
    model->GU scale, which also carries the ship's `GetScale()`; so the point
    is scaled by it on the way in (identity for an unscaled hull). The one
    test for "is this point on that part": subsystem kill, emitter silencing
    and `host_loop._part_pose_at`'s lights all use it, so they agree."""
    k = _ship_scale(ship)
    try:
        return int(host_io.structure_part_at(
            iid, (point[0] * k, point[1] * k, point[2] * k)))
    except Exception as _e:
        dev_mode.log_swallowed("structure_part_at", _e)
        return -1


def _ship_scale(ship) -> float:
    try:
        s = float(ship.GetScale())
    except Exception:
        return 1.0
    return s if s > 0.0 else 1.0


def severed_mask(iid) -> int:
    """`iid`'s severed structure parts (`host_io.instance_severed_parts`),
    0 when none, for a stale id, or a host without the binding -- a
    per-frame reader must never raise out of the frame."""
    if iid is None:
        return 0
    try:
        return int(host_io.instance_severed_parts(iid))
    except Exception as _e:
        dev_mode.log_swallowed("instance_severed_parts", _e)
        return 0


def on_severed_part(ship, iid, point, mask=None) -> bool:
    """Whether an authored body-frame point of `ship` (SHIP units, rest
    pose) sits on a structure part that has broken off. `mask` is
    `severed_mask(iid)` when the caller already holds it (read once per ship
    per frame); an intact hull answers without labelling the point, and a
    severed one labels each point once per mask (`_part_labels`)."""
    if mask is None:
        mask = severed_mask(iid)
    if not mask:
        return False
    mask = int(mask)
    cached = _part_labels.get(iid)
    if cached is None or cached[0] != mask:
        cached = (mask, {})
        _part_labels[iid] = cached
    labels = cached[1]
    key = (float(point[0]), float(point[1]), float(point[2]),
           _ship_scale(ship))
    label = labels.get(key)
    if label is None:
        label = part_at_rest_point(ship, iid, point)
        labels[key] = label
    return 0 <= label < 32 and bool((mask >> label) & 1)


def _burst(ship, iid, centroid_gu):
    """Sub-floor component: the material is gone; show the existing breach
    VFX (debris, venting, rim) at its centroid rather than spawning a chunk
    instance for a handful of cells."""
    try:
        host_io.breach_burst(iid, centroid_gu, 0.1)
    except Exception as _e:
        dev_mode.log_swallowed("severed component burst", _e)
