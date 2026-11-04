"""Differential oracle: ProximityManager's two queries as they stood at
7b8e8438a, before the candidate cache (native proximity phase 1, Task 5).

A VERBATIM copy of ``_candidates``, ``_near_objects`` (with Task 1's check
skipping) and ``_line_objects`` from engine/appc/planet.py at that commit,
adapted only to be free functions over a manager (``self`` -> ``pm``) and
without the profiler scope. Do not "fix" anything here: it is the reference
the cached queries must equal by identity and order.

One deliberate change since (Task 7, ruling 4): ``near_objects`` uses BC's
size rule, keeping an object when its SURFACE is within the radius
(`|location - point| <= radius + max(GetRadius(), 0)`, a GetRadius() that
raises counting as 0). Its store-backed entries are still tested through
``within_radius``, now one call per entry with that entry's reach squared, so
it stays a different code path from the kernel the manager uses
(``near_indices_sized``). ``line_objects`` is unchanged.
"""
from engine.appc import proximity_table
from engine.appc.planet import _is_proximity_participant, _ProximityIteration


def candidates(pm):
    out = []
    seen = set()
    pSet = pm._set
    if pSet is not None:
        # Torpedoes never occupy space unless something gives one a
        # radius, so while none has, walk the set's non-torpedo index
        # (SetClass._non_torpedo): same members, same order, without
        # stepping through every torpedo in flight.
        from engine.appc.sets import SetClass
        from engine.appc import projectiles
        if isinstance(pSet, SetClass) and not projectiles.sized_torpedo_in(pSet):
            members = list(pSet._non_torpedo.values())
        else:
            try:
                members = pSet.GetObjectList()
            except Exception:
                members = ()
        for obj in members:
            if id(obj) not in seen and _is_proximity_participant(obj):
                seen.add(id(obj))
                out.append(obj)
    for obj in pm._objects:
        if id(obj) not in seen:
            seen.add(id(obj))
            out.append(obj)
    return out


def _reach(r, obj):
    try:
        rad = float(obj.GetRadius())
    except Exception:
        rad = 0.0
    return r + (rad if rad > 0.0 else 0.0)


def near_objects(pm, point, radius):
    r = float(radius)
    px, py, pz = point.x, point.y, point.z
    from engine.appc.ai import ProximityCheck
    candidates_ = [o for o in candidates(pm)
                   if not isinstance(o, ProximityCheck)]
    from engine.appc.transform_store import get_store
    stored = [obj for obj in candidates_
              if proximity_table.location_is_stored(obj)]
    inside = {}
    for obj in stored:
        reach = _reach(r, obj)
        f = get_store().within_radius([obj._xform], px, py, pz, reach * reach)
        inside[id(obj)] = f[0]
    result = []
    for obj in candidates_:
        f = inside.get(id(obj))
        if f is not None:
            if f:
                result.append(obj)
            continue
        loc = obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation") else None
        if loc is None:
            continue
        dx = loc.x - px
        dy = loc.y - py
        dz = loc.z - pz
        reach = _reach(r, obj)
        if dx * dx + dy * dy + dz * dz <= reach * reach:
            result.append(obj)
    return _ProximityIteration(result)


def line_objects(pm, start, end, radius):
    r = float(radius)
    ax, ay, az = start.x, start.y, start.z
    dx, dy, dz = end.x - ax, end.y - ay, end.z - az
    seg_len2 = dx * dx + dy * dy + dz * dz
    from engine.appc.ai import ProximityCheck
    result = []
    for obj in candidates(pm):
        if isinstance(obj, ProximityCheck):
            continue
        loc = obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation") else None
        if loc is None:
            continue
        px, py, pz = loc.x - ax, loc.y - ay, loc.z - az
        if seg_len2 <= 1e-12:
            # Degenerate leg (Intercept can ask for one when it is already
            # at its destination): a point query, not a division by zero.
            t = 0.0
        else:
            t = (px * dx + py * dy + pz * dz) / seg_len2
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        cx, cy, cz = px - t * dx, py - t * dy, pz - t * dz
        try:
            reach = r + float(obj.GetRadius())
        except Exception:
            reach = r
        if cx * cx + cy * cy + cz * cz <= reach * reach:
            result.append(obj)
    return _ProximityIteration(result)
