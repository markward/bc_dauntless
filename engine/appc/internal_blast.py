"""SPIKE (damage redesign): internal explosions.

A destroyed subsystem blows out from INSIDE the hull, but only where its blast
reaches the hull (Mark, 2026-10-20: a subsystem buried too deep shows
nothing). subsystems._condition_changed queues every DESTROYED transition
here; the host loop drains the queue per tick, because the emitters need the
ship -> render-instance map that only exists there. For each blast:

1. The sphere: the subsystem's world mount, radius = GetRadius() *
   RADIUS_SCALE (GU).
2. Exit points: rays cast from OUTSIDE the sphere back toward its centre find
   the hull surface along EXIT_DIRS; hits inside the sphere are where the
   blast breaks out. None -> contained: nothing is drawn at all.
3. At up to MAX_EXITS spread-out exit points: a persistent INTERNAL damage
   record (weapon class 3) ON THE HULL, whose wear is STRENGTH, so the
   plating shader fails the layers inside-out around it (opaque.frag
   plating_internal), plus a critical hit flash with torpedo sparks and a
   breach burst (debris + venting). The blast breaks out through the nearest
   hull with full force: the hole is larger the deeper the hull sits inside
   the sphere (hole_radius), never below HOLE_MIN of the blast. A record at
   the subsystem's centre was tried first and only ever grazed the hull --
   the hull sits near the sphere's edge, where its falloff is ~0.
Gameplay is untouched -- the subsystem is already destroyed.
"""
import math

import engine.dev_mode as dev_mode
from engine import host_io

RADIUS_SCALE = 1.4        # blast sphere = hardpoint radius x this
STRENGTH = 6.0            # wear at the centre (inner hull tears at 4.5)
MAX_EXITS = 3
HOLE_K = 1.1              # hole radius = blast radius x HOLE_K x sqrt(1 - d/R)...
HOLE_MIN = 0.35           # ...but never below this fraction of the blast radius
MAX_PENDING = 64
MAX_PENDING_AGE = 5.0     # s a blast waits for its ship's render instance
WEAPON_CLASS_INTERNAL = 3

_pending: list = []


def _exit_dirs():
    out = []
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            for z in (-1, 0, 1):
                if x or y or z:
                    n = math.sqrt(x * x + y * y + z * z)
                    out.append((x / n, y / n, z / n))
    return out


EXIT_DIRS = _exit_dirs()


def reset() -> None:
    _pending.clear()


def queue(sub) -> None:
    """Called on a subsystem's transition to DESTROYED."""
    ship = sub._climb_to_ship() if hasattr(sub, "_climb_to_ship") else None
    if ship is None:
        return
    if hasattr(ship, "GetHull") and ship.GetHull() is sub:
        return                                   # hull = ship death, not a blast
    if hasattr(ship, "IsDying") and ship.IsDying():
        return
    try:
        radius = float(sub.GetRadius()) * RADIUS_SCALE
    except Exception:
        return
    if radius <= 0.0:
        return
    if len(_pending) >= MAX_PENDING:
        _pending.pop(0)
    _pending.append({"ship": ship, "sub": sub, "radius": radius, "age": 0.0})


def advance(dt=0.0, ship_instances=None) -> None:
    if not _pending:
        return
    survivors = []
    for entry in _pending:
        iid = ship_instances.get(entry["ship"]) if ship_instances is not None else None
        if iid is None:
            entry["age"] += float(dt)
            if entry["age"] < MAX_PENDING_AGE:
                survivors.append(entry)
            continue
        try:
            _blast(entry, iid)
        except Exception as _e:
            dev_mode.log_swallowed("internal blast", _e)
    _pending[:] = survivors


def _body_dir_to_world(ship, d):
    rot = ship.GetWorldRotation() if hasattr(ship, "GetWorldRotation") else None
    if rot is None:
        return d
    c0, c1, c2 = rot.GetCol(0), rot.GetCol(1), rot.GetCol(2)
    return (c0.x * d[0] + c1.x * d[1] + c2.x * d[2],
            c0.y * d[0] + c1.y * d[1] + c2.y * d[2],
            c0.z * d[0] + c1.z * d[1] + c2.z * d[2])


def _world_to_body(ship, v):
    rot = ship.GetWorldRotation()
    c0, c1, c2 = rot.GetCol(0), rot.GetCol(1), rot.GetCol(2)
    return (c0.x * v[0] + c0.y * v[1] + c0.z * v[2],
            c1.x * v[0] + c1.y * v[1] + c1.z * v[2],
            c2.x * v[0] + c2.y * v[1] + c2.z * v[2])


def hole_radius(blast_radius: float, dist: float) -> float:
    """Hole opened at an exit point `dist` from the blast centre (GU)."""
    depth = max(0.0, 1.0 - dist / blast_radius)
    return blast_radius * max(HOLE_MIN, HOLE_K * math.sqrt(depth))


def find_exits(iid, centre, radius, dirs_world):
    """Hull points inside the blast sphere, nearest first, at most MAX_EXITS,
    at least half a radius apart. `centre` in mesh (view) coordinates.
    Returns [(point, normal, dist_from_centre)]."""
    hits = []
    span = 2.0 * radius
    for d in dirs_world:
        origin = (centre[0] + d[0] * span, centre[1] + d[1] * span, centre[2] + d[2] * span)
        try:
            hit = host_io.ray_trace_mesh(iid, origin, (-d[0], -d[1], -d[2]), span)
        except Exception:
            hit = None
        if hit is None:
            continue
        p, n, _ = hit
        r = math.dist(p, centre)
        if r <= radius:
            hits.append((p, n, r))
    hits.sort(key=lambda h: h[2])
    chosen = []
    for h in hits:
        if all(math.dist(h[0], c[0]) >= 0.5 * radius for c in chosen):
            chosen.append(h)
        if len(chosen) >= MAX_EXITS:
            break
    return chosen


def _blast(entry, iid) -> None:
    from engine.appc.subsystems import subsystem_world_position
    from engine.appc.hit_feedback import _mesh_xyz, Severity
    from engine.appc import damage_decals, hit_vfx
    from engine.appc.math import TGPoint3
    from engine.systems import frames

    ship, sub, radius = entry["ship"], entry["sub"], entry["radius"]
    centre_set = subsystem_world_position(sub, ship)
    centre = _mesh_xyz(ship, centre_set)
    dirs = [_body_dir_to_world(ship, d) for d in EXIT_DIRS]
    exits = find_exits(iid, centre, radius, dirs)
    name = sub.GetName() if hasattr(sub, "GetName") else "?"
    if not exits:
        print("[internal-blast] %s contained (radius %.2f GU): no hull in reach"
              % (name, radius))
        return

    now = damage_decals.current_game_time()
    ship_loc = ship.GetWorldLocation()
    pset = frames.containing_set(ship)
    for p, n, dist in exits:
        host_io.damage_decal_add(iid, p, n, hole_radius(radius, dist), 1.0,
                                 WEAPON_CLASS_INTERNAL, now, dent=STRENGTH)
        p_set = TGPoint3(centre_set.x + (p[0] - centre[0]),
                         centre_set.y + (p[1] - centre[1]),
                         centre_set.z + (p[2] - centre[2]))
        body_gu = _world_to_body(ship, (p_set.x - ship_loc.x, p_set.y - ship_loc.y,
                                        p_set.z - ship_loc.z))
        conv = host_io.world_to_body(iid, p, n)
        body_point, body_normal = conv if conv is not None else (None, None)
        hit_vfx.spawn(p_set, normal=TGPoint3(n[0], n[1], n[2]), severity=Severity.CRITICAL,
                      instance_id=iid if body_point is not None else None,
                      body_point=body_point, body_normal=body_normal,
                      weapon_kind=1, spark_count=60 if body_point is not None else 0,
                      pSet=pset)
        host_io.breach_burst(iid, body_gu, radius * 0.5)
    print("[internal-blast] %s blew out at %d point(s), radius %.2f GU, holes %s GU"
          % (name, len(exits), radius,
             ", ".join("%.2f" % hole_radius(radius, d) for _, _, d in exits)))
