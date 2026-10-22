# engine/appc/visible_damage.py
"""BC visible-damage API -> Internal hull-damage records.

The SDK's pre-wreck `Damage*.py` scripts (authored by the original DamageTool)
call `pShip.AddObjectDamageVolume(x, y, z, influRad, strength)` — a body-frame
damage sphere — and `Effects.DeathExplosionDamage` calls the runtime sibling
`pShip.AddDamage(pEmitPos, fRadius, fDamage)`. `DamageableObject` routes both
here, and each becomes ONE Internal record in the hull's HullDamageStore
(`host_io.hull_damage_add`, kind 3): the plating fails inside-out around it,
torn through at the core with members and stripped plating around.

The record needs the ship->instance-id map, which only exists in the
host-loop tick. But the authored calls arrive during a mission's
`Initialize`, BEFORE the set's render instances are realized (the ship has no
`iid` yet). So we QUEUE each request and DRAIN it per-tick from `advance()`
once the ship's instance is realized — the same deferred pattern as the
warp-core breach's records (`engine/appc/warp_core_breach.py`). Authored
damage bypasses the combat path's eligibility gate (it is content, not beam
clutter) and emits all of a ship's volumes at once, within the frame budget.

The hole is sized by the volume's radius (floored at MIN_HOLE_RADIUS_GU, times
BC's DamageRadMod) under a cap that scales with `strength`; see ADD_DAMAGE_*.
"""
import time

import engine.dev_mode as dev_mode
from engine import host_io
from engine.core import frame_profiler
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.hit_feedback import _mesh_xyz

# Pending requests linger at most this long (game seconds) waiting for the
# ship's render instance to be realized, then drop — so a headless run, a culled
# ship, or a failed spawn never leaks an un-emittable entry.
MAX_PENDING_AGE = 5.0

# Per-frame time budget for emitting queued volumes (ms). A dying ship's SDK
# cascade can land 2-6 in one frame (when each was a voxel carve brush pass,
# ~5.7 ms each in Debug for a Sovereign: perf-register P-4, SIG-044; each is
# now a mesh probe plus a record). advance() always emits at least one, so the
# queue drains; the rest wait a frame or two, which the cascade's ~0.2 s blast
# spacing hides. Only the visible hole waits -- AddDamage's gameplay damage is
# applied when called.
CARVE_BUDGET_MS = 3.0

# Standoff (GU) for the surface-normal probe in `_mesh_normal`: the ray starts
# this far outside the sample point along the radial and casts twice as far
# back inward. Small and local on purpose -- a long cast from outside the
# bounding sphere would hit whatever hull piece happens to be in front (a
# nacelle occluding the saucer) rather than the surface actually being damaged.
NORMAL_PROBE_MARGIN_GU = 0.5

# Hole-radius floor (GU) for a volume: authored wrecks carry their own size,
# so a tiny influRad still leaves a visible hole (before DamageRadMod).
MIN_HOLE_RADIUS_GU = 0.25

# AddDamage hole size and wear (Ruling 5, 2026-10-21) -- a DELIBERATE
# departure from BC's fixed fRadius x 0.25 / 600, at Mark's request: death
# explosions read "all very even in size", and every 600 hole wore past deck
# break, so a dead hull showed straight through to its nacelles. The hole cap
# scales with strength / 600 inside [MIN, MAX]; below BLOW_THROUGH strength
# the wear tears into the rooms (ROOM_FRACTION of the way from breach to deck
# break, read from the live plating dials) and the decks hold; at or above it
# (the cascade's big tier, m >= 1.8 at 600) it is internal_blast.STRENGTH.
ADD_DAMAGE_HOLE_SCALE_MIN = 0.5
ADD_DAMAGE_HOLE_SCALE_MAX = 3.0
ADD_DAMAGE_ROOM_FRACTION = 0.7
ADD_DAMAGE_BLOW_THROUGH_STRENGTH = 1080.0

# Size multiplier on the VISIBLE half of AddDamage (queue_world_hole) while
# a `hole_scale` block is active -- the death cascade's blast size tier.
# AddDamage's gameplay half (combat.apply_hit) never sees it.
_hole_scale = 1.0


class hole_scale:
    """`with hole_scale(m): ship.AddDamage(...)` scales the queued visible
    radius and strength by m; gameplay damage is untouched."""

    def __init__(self, m):
        self._m = float(m)
        self._prev = 1.0

    def __enter__(self):
        global _hole_scale
        self._prev = _hole_scale
        _hole_scale = self._m
        return self

    def __exit__(self, *exc):
        global _hole_scale
        _hole_scale = self._prev
        return False


def current_hole_scale() -> float:
    return _hole_scale


# Registry of not-yet-emitted volumes. Each entry:
#   {"ship", "kind": "body"|"world"|"scuff", "pt": (x, y, z), ..., "age": float}
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


def queue_world_hole(ship, pEmitPos, fRadius, fDamage=0.0) -> None:
    """Queue AddDamage's visible hole (DamageableObject.AddDamage, e.g.
    Effects.DeathExplosionDamage): once the ship's render instance exists it
    becomes ONE Internal hull-damage record at the world-space point, sized
    and worn by `_advance_one` (ADD_DAMAGE_*), posed-frame. `pEmitPos` is a point
    object (NiPoint3/TGPoint3 with .x/.y/.z); `fRadius` and `fDamage` are
    BC's radius and field strength, both scaled by an active `hole_scale`."""
    if ship is None or pEmitPos is None:
        return
    try:
        wp = (float(pEmitPos.x), float(pEmitPos.y), float(pEmitPos.z))
    except (AttributeError, TypeError):
        return
    _pending.append({
        "ship": ship, "kind": "world",
        "pt": wp, "influ": float(fRadius) * _hole_scale,
        "strength": float(fDamage) * _hole_scale, "age": 0.0,
    })


def queue_body_scuff(ship, x, y, z, radius_gu, tangent_body=(1.0, 0.0, 0.0),
                     intensity=1.0, dent=0.0) -> None:
    """Queue a collision-scuff DECAL (no damage record) at a body-frame point. Used by
    the developer Damage Preview mission to seed known scuffs for live tuning.
    `tangent_body` is the slip direction in the body frame; `dent` is the
    impact weight (1 crumples, 0 scrapes); realised through
    host_io.damage_decal_add once the ship's render instance exists."""
    if ship is None:
        return
    _pending.append({
        "ship": ship, "kind": "scuff",
        "pt": (float(x), float(y), float(z)),
        "radius": float(radius_gu), "intensity": float(intensity),
        "tangent": tuple(float(c) for c in tangent_body), "age": 0.0,
        "dent": float(dent),
    })


def clear_for(ship) -> None:
    """Drop a ship's not-yet-emitted volumes (DamageableObject.RemoveVisibleDamage).

    NOTE: clears only PENDING volumes. Clearing already-emitted records needs
    a native HullDamageStore clear binding (not yet implemented)."""
    _pending[:] = [e for e in _pending if e["ship"] is not ship]


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _pending.clear()


def advance(dt=0.0, ship_instances=None, budget_ms=CARVE_BUDGET_MS,
            clock=time.perf_counter) -> None:
    """Emit queued volumes for any ship whose render instance is now realized,
    in queue order, until `budget_ms` is spent (always at least one); keep the
    rest -- unrealized ones age out after MAX_PENDING_AGE, budget-held ones
    never age. Raise-safe per entry."""
    if not _pending:
        return
    start = clock()
    emitted = False
    survivors = []
    for entry in _pending:
        realized = (ship_instances is not None
                    and ship_instances.get(entry["ship"]) is not None)
        if realized and emitted and (clock() - start) * 1000.0 >= budget_ms:
            survivors.append(entry)
            continue
        try:
            keep = _advance_one(entry, float(dt), ship_instances)
        except Exception as _e:
            dev_mode.log_swallowed("visible damage advance", _e)
            keep = False
        if realized:
            emitted = True
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

    if entry.get("kind") == "scuff":
        world_pt, normal = _resolve(dict(entry, kind="body"), ship, iid)
        if world_pt is None:
            return False
        # Anchor at the hull SURFACE, not the authored (interior) point: a
        # real collision decal is anchored at _resolve_hit_point's mesh point
        # (combat.py), and the authored body point sits 0.1-0.3 GU below the
        # surface like any other AddObjectDamageVolume sphere -- see
        # _mesh_probe. Take BOTH the point and normal when the trace
        # succeeds; keep the authored point + radial-normal guess otherwise
        # (headless / no instance -- the existing scuff tests exercise this).
        mesh_pt, mesh_normal = _mesh_probe(iid, world_pt, normal, ship)
        if mesh_normal is not None:
            normal = mesh_normal
        if mesh_pt is not None:
            world_pt = mesh_pt
        tx, ty, tz = entry["tangent"]
        tangent = _body_dir_to_world(ship, tx, ty, tz)
        from engine.appc import damage_decals
        host_io.damage_decal_add(
            iid,
            _mesh_xyz(ship, world_pt),
            (normal.x, normal.y, normal.z),
            entry["radius"], entry["intensity"],
            damage_decals.WEAPON_CLASS_SCUFF,
            damage_decals.current_game_time(),
            world_tangent=(tangent.x, tangent.y, tangent.z),
            dent=entry.get("dent", 0.0),
        )
        return False

    with frame_profiler.scope("vd.resolve"):
        world_pt, normal = _resolve(entry, ship, iid)
    if world_pt is None:
        return False

    from engine.appc import internal_blast, plating_dials
    strength = entry["strength"]
    # The volume's own size, floored and scaled by BC's DamageRadMod, capped
    # near BC's 0.30 GU largest hole times strength relative to BC's 600
    # "major hull breach"; see ADD_DAMAGE_* above for the wear (a deliberate
    # departure, Ruling 5).
    floor = max(MIN_HOLE_RADIUS_GU, entry["influ"]) * _radius_mod(ship)
    rel = max(ADD_DAMAGE_HOLE_SCALE_MIN,
              min(ADD_DAMAGE_HOLE_SCALE_MAX, strength / 600.0))
    hole = min(floor, internal_blast.ADD_DAMAGE_MAX_HOLE_GU * rel)
    if strength < ADD_DAMAGE_BLOW_THROUGH_STRENGTH:
        dials = plating_dials.current()
        breach = dials["breach_wear"]
        wear = breach + ADD_DAMAGE_ROOM_FRACTION * (dials["deck_break_wear"] - breach)
    else:
        wear = internal_blast.STRENGTH
    # An authored DamageTool volume (kind "body") is REST-frame content: it
    # probes the rest skin and is attributed in rest space by the binding
    # (rest_frame). AddDamage ("world") lands at posed-time points: it probes
    # the pose as drawn and is attributed to the posed part (layered damage
    # phase 4 §2.1).
    authored = entry["kind"] == "body"
    mesh_pt, mesh_normal = _mesh_probe(iid, world_pt, normal, ship, rest_pose=authored)
    if mesh_pt is not None:
        world_pt = mesh_pt
    if mesh_normal is not None:
        normal = mesh_normal
    host_io.hull_damage_add(iid, _mesh_xyz(ship, world_pt),
                            (normal.x, normal.y, normal.z), hole, wear, 3,
                            rest_frame=authored)
    # A dying ship sheds parts like a fighting one: the cascade's wear asks
    # for the part check as combat wear does.
    from engine.appc import hull_breakup
    with frame_profiler.scope("vd.after_wear"):
        hull_breakup.after_wear(ship, iid, ship_instances)
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
        mesh = _mesh_normal(iid, world_pt, radial, ship)
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


def _mesh_probe(iid, world_pt, radial, ship=None, rest_pose=False):
    """Ray-trace the true hull surface near `world_pt`, along `radial`.

    Returns `(surface_point, surface_normal)` as TGPoint3s, or `(None, None)`
    if unobtainable (no instance, no radial, miss, or a raised trace). Holds
    the trace logic shared by `_mesh_normal` (normal only -- see its
    docstring for why the normal matters) and `_advance_one` (point AND
    normal, so a scuff decal or a damage record anchors at the visible skin
    rather than the authored point, which sits inside the hull like any other
    AddObjectDamageVolume sphere).

    `rest_pose`: probe the model's REST geometry, not the pose it is drawn at
    -- an authored DamageTool volume is rest-frame content, so on a ship with
    a part posed it must anchor on the rest skin and keep rest coordinates
    (layered damage phase 4 §2.1).
    """
    if iid is None or radial is None:
        return None, None
    # `world_pt` is in the ship's own set coordinates; the trace speaks the
    # renderer's view coordinates. In, and the surface point back out.
    from engine.systems import frames
    to_view = frames.view_offset(frames.containing_set(ship))
    q = frames.shifted(world_pt, to_view)
    try:
        origin = (q.x + radial.x * NORMAL_PROBE_MARGIN_GU,
                  q.y + radial.y * NORMAL_PROBE_MARGIN_GU,
                  q.z + radial.z * NORMAL_PROBE_MARGIN_GU)
        direction = (-radial.x, -radial.y, -radial.z)
        if rest_pose:
            hit = host_io.ray_trace_mesh(iid, origin, direction,
                                         NORMAL_PROBE_MARGIN_GU * 2.0,
                                         rest_pose=True)
        else:
            hit = host_io.ray_trace_mesh(iid, origin, direction,
                                         NORMAL_PROBE_MARGIN_GU * 2.0)
    except Exception as _e:
        dev_mode.log_swallowed("probe hull surface point/normal", _e)
        return None, None
    if not hit:
        return None, None
    (px, py, pz), (nx, ny, nz), _t = hit
    normal = TGPoint3(float(nx), float(ny), float(nz))
    if normal.Unitize() <= 1e-6:
        return None, None
    return (frames.shifted(TGPoint3(float(px), float(py), float(pz)),
                           to_view, -1.0), normal)


def _mesh_normal(iid, world_pt, radial, ship=None):
    """The TRUE hull surface normal at `world_pt`, or None if unobtainable.

    `_outward_normal`'s radial-from-centre guess is nearly TANGENTIAL on a wide
    flat structure -- a Galaxy saucer sits ~2 GU off the axis but only ~0.3 GU
    above centre, so the radial direction is almost horizontal where the real
    surface normal is almost vertical, and the record is oriented by it.

    The combat path never had this problem -- it passes ray_trace's mesh
    normal (hit_feedback.py). This gives the AddDamage path the same quality
    of normal: stand off along the radial and cast back inward, taking the
    first hit. ray_trace flips its normal against the incoming ray, so the
    result is outward-facing, matching the convention decals and records use.

    Raise-safe and miss-safe: the caller keeps the radial guess, because an
    approximate hole beats none (authored wrecks must still appear headless,
    where there is no instance to trace against).

    Thin wrapper over `_mesh_probe`; the point half of the probe is unused
    here.
    """
    return _mesh_probe(iid, world_pt, radial, ship)[1]


def _outward_normal(world_pt, loc, ship):
    """Unit vector from the ship centre toward `world_pt`; ship-up at the centre.

    Fallback only for world volumes -- see `_mesh_normal` for why a real surface
    normal is worth the ray cast. Still the primary path for BODY-frame authored
    volumes, whose points sit inside the hull rather than on its surface, so
    there is no surface to probe."""
    n = TGPoint3(world_pt.x - loc.x, world_pt.y - loc.y, world_pt.z - loc.z)
    if n.Unitize() <= 1e-6:
        return _ship_up(ship)
    return n


def _body_dir_to_world(ship, x, y, z) -> TGPoint3:
    """Rotate a body-frame direction into world space via `R = ship.
    GetWorldRotation()` (`v_world = R . v_body`, CLAUDE.md's column-vector
    convention), or return it unrotated when the ship exposes no real
    `TGMatrix3` rotation (legacy test fakes / headless). Shared "rotate a
    body vector through GetWorldRotation if it is a TGMatrix3" guard --
    `_resolve`'s body-frame offset keeps its own copy (a slightly different
    shape: it also folds the outward-normal fallback), left alone here."""
    v = TGPoint3(x, y, z)
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            v.MultMatrixLeft(rot)
    return v


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
