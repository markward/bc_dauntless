"""Differential oracle: ProximityManager's two queries as they stood at
7b8e8438a, before the candidate cache (native proximity phase 1, Task 5).

A VERBATIM copy of ``_candidates``, ``_near_objects`` (with Task 1's check
skipping) and ``_line_objects`` from engine/appc/planet.py at that commit,
adapted only to be free functions over a manager (``self`` -> ``pm``) and
without the profiler scope. Do not "fix" anything here: it is the reference
the cached queries must equal by identity and order.
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


def near_objects(pm, point, radius):
    r2 = float(radius) * float(radius)
    px, py, pz = point.x, point.y, point.z
    from engine.appc.ai import ProximityCheck
    candidates_ = [o for o in candidates(pm)
                   if not isinstance(o, ProximityCheck)]
    from engine.appc.transform_store import get_store
    stored = [obj for obj in candidates_
              if proximity_table.location_is_stored(obj)]
    inside = {}
    if stored:
        flags = get_store().within_radius(
            [obj._xform for obj in stored], px, py, pz, r2)
        inside = {id(obj): f for obj, f in zip(stored, flags)}
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
        if dx * dx + dy * dy + dz * dz <= r2:
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
