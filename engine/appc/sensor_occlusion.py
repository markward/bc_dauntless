"""Does a major rock block the line of sight from A to B?
(sensor continuity/occlusion spec, roadmap decision 7)

A major rock is a RockClass in A's set whose SCALED radius
(rocks.rock.effective_radius -- never GetRadius() alone, which ignores
SetScale) is at least the `min_blocker_radius_gu` dial. The test is the
segment between the two centres against each rock's sphere; A and B are never
their own occluders. A rock whose sphere contains the observer's centre or the
target's centre does not occlude that pair either: that ship is BESIDE the
rock, not behind it (final review fix 1 -- the segment would otherwise start
inside the sphere and every direction would read blocked). Planets, suns,
ships and minor/near-band rocks never occlude; fields between ships never
occlude.

Cost: can_detect has a dozen callers, some per frame and per torpedo, so
answers are cached per set, per (A, B), for the current game time, and each
set's list of major rocks is cached per game time AND per bucket size -- a rock
added or removed within the same tick (tests, spawns, breakups) changes the
bucket size and invalidates it. Both caches are keyed per set (final review fix
5), so callers alternating between sets in one tick do not thrash each other.
Never raises: a failure answers "not blocked" and is logged.

`begin_tick(now_gt)` (controller ruling) records the sensor manager's own
tick time and folds it into BOTH cache signatures alongside App's game time.
Production already advances App's game time every sim tick, so this changes
no observable behaviour there -- but tests/integration drive
`sensor_contacts.tick(player, now_gt)` (which calls `begin_tick` first thing;
see Task 4) with a STATIC App game time while moving rocks or ships between
ticks, and App time alone would then never invalidate either cache on a move.
"""
import weakref

import App
import engine.dev_mode as dev_mode
from engine.appc import sensor_dials

# set -> (signature, {(id(a), id(b)): bool}); signature = (game_time,
# tick_time, major-rock count) for that set.
_pair_cache: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_rock_cache: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_tick_time = None                # last begin_tick() value; None until first call


def begin_tick(now_gt: float) -> None:
    """Record the manager's own tick time for this tick. See the module
    docstring for why this is folded into the cache signatures rather than
    relying on App's game time alone."""
    global _tick_time
    _tick_time = float(now_gt)


def reset() -> None:
    global _tick_time
    _pair_cache.clear()
    _rock_cache.clear()
    _tick_time = None


def _now() -> float:
    try:
        return float(App.g_kUtopiaModule.GetGameTime())
    except Exception:
        return 0.0


def _major_rocks(pset, now):
    """(rock, x, y, z, r) for every major rock in *pset*, cached per tick and
    per bucket size."""
    from engine.appc import contact_index
    from engine.appc.subsystems import _get_xyz
    from engine.rocks.rock import RockClass, effective_radius
    ships = contact_index.ships_in(pset)
    min_r = sensor_dials.get("min_blocker_radius_gu")
    sig = (now, _tick_time, len(ships), min_r)
    hit = _rock_cache.get(pset)
    if hit is not None and hit[0] == sig:
        return hit[1]
    rocks = []
    for s in ships:
        if isinstance(s, RockClass):
            r = effective_radius(s)
            if r >= min_r:
                x, y, z = _get_xyz(s)
                rocks.append((s, x, y, z, r))
    rocks = tuple(rocks)
    _rock_cache[pset] = (sig, rocks)
    return rocks


def _segment_hits(ax, ay, az, bx, by, bz, cx, cy, cz, r) -> bool:
    dx, dy, dz = bx - ax, by - ay, bz - az
    seg2 = dx * dx + dy * dy + dz * dz
    px, py, pz = cx - ax, cy - ay, cz - az
    t = 0.0 if seg2 <= 1e-12 else (px * dx + py * dy + pz * dz) / seg2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    qx, qy, qz = px - t * dx, py - t * dy, pz - t * dz
    return qx * qx + qy * qy + qz * qz < r * r


def _contains(x, y, z, cx, cy, cz, r) -> bool:
    dx, dy, dz = x - cx, y - cy, z - cz
    return dx * dx + dy * dy + dz * dz < r * r


def blocked(observer, target) -> bool:
    try:
        pset = observer.GetContainingSet()
        if pset is None:
            return False
        now = _now()
        rocks = _major_rocks(pset, now)
        if not rocks:
            return False
        key_sig = (now, _tick_time, len(rocks))
        entry = _pair_cache.get(pset)
        if entry is None or entry[0] != key_sig:
            entry = (key_sig, {})
            _pair_cache[pset] = entry
        pairs = entry[1]
        pair = (id(observer), id(target))
        hit = pairs.get(pair)
        if hit is not None:
            return hit
        from engine.appc.subsystems import _get_xyz
        ax, ay, az = _get_xyz(observer)
        bx, by, bz = _get_xyz(target)
        answer = False
        for rock, cx, cy, cz, r in rocks:
            if rock is observer or rock is target:
                continue
            if (_contains(ax, ay, az, cx, cy, cz, r)
                    or _contains(bx, by, bz, cx, cy, cz, r)):
                continue          # beside the rock, not behind it
            if _segment_hits(ax, ay, az, bx, by, bz, cx, cy, cz, r):
                answer = True
                break
        pairs[pair] = answer
        return answer
    except Exception as e:
        dev_mode.log_swallowed("sensor_occlusion.blocked", e)
        return False
