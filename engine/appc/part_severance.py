"""Appendage severance — a named part shears off once it has absorbed its share.

Phase 2a of `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md`.

WHY THIS EXISTS, rather than leaving severance to voxel connectivity. Measured
live: a Bird of Prey's wing cannot be shot off. Connectivity runs on the UNION
of body and wing, and the wing root is EMBEDDED in the hull — at the wing's
narrowest slab (|x| 0.225) the body itself still reaches |x| 0.228. The first
genuinely wing-only cross-section is 39x32 model units, which needs two
maximum-size carves (30 units across) placed precisely side by side, and they
would not even merge — the merge radius is ~9 units. So the weak point is both
invisible and, in practice, unhittable.

That made the mechanic unusable: a player shoots the wing, and the wing is the
one place that can never detach it. So severance of APPENDAGES is attributed
and threshold-based here, while the HULL keeps voxel connectivity
(`hull_breakup`) for emergent chunks. Neither replaces the other.

WHAT A PART TOTAL IS. Damage attributed to a part is an ATTRIBUTION, not a
second HP pool: the hit does its normal hull damage as well. The total only
decides when the part gives way. It is cumulative and never decays — chip at a
wing across a whole battle and it still comes off.
"""

from __future__ import annotations

import engine.dev_mode as dev_mode
from engine.appc import articulation


# A point inside exactly one part box resolves to that part. Otherwise the
# nearest box must be this many times closer than the runner-up, or the hit is
# unattributed (the body). Same rule and same constant the hardpoint->part
# assignment uses, so the two never disagree about what "on the wing" means.
ATTRIBUTION_MARGIN = 5.0

# ⚠️ TWO UNIT SYSTEMS MEET IN THIS MODULE. Getting them confused is not a
# hypothetical: it shipped, and attribution never fired once.
#
#   * `articulation.PART_BOXES` and subsystem `GetPosition()` are in SHIP units
#     (what hardpoint files author: a BoP wingtip is x = 1.008).
#   * `host_io.world_to_body` returns the body frame in MODEL units -- it
#     inverts the instance world matrix, which carries BC_MODEL_SCALE, so the
#     SAME wingtip comes back as x = 100.8.
#
# One is 100x the other. A model-units point tested against a ship-units box
# lands nowhere near it and silently attributes to nothing, which is
# indistinguishable from "the player missed".
#
# So: `part_for_point` is the SHIP-units primitive, and `record_hit` converts
# on the way in. Anything else calling part_for_point must already hold ship
# units -- `_destroy_subsystems_on_part` does, which is exactly why the
# subsystem half worked while the damage half never did.
MODEL_TO_SHIP = 0.01          # = BC_MODEL_SCALE (host_loop). Multiply a
                               # MODEL-units value by this to reach SHIP units
                               # -- record_hit does exactly that, below.


def _distance_to_box(point, box) -> float:
    """Euclidean distance from `point` to an AABB; 0.0 when inside."""
    (lo, hi) = box
    total = 0.0
    for i in range(3):
        if point[i] < lo[i]:
            d = lo[i] - point[i]
        elif point[i] > hi[i]:
            d = point[i] - hi[i]
        else:
            continue
        total += d * d
    return total ** 0.5


def part_for_point(leaf, point):
    """Which part a body-frame point in SHIP UNITS belongs to, or None.

    ⚠️ SHIP units, not model units -- see MODEL_TO_SHIP above. A caller holding
    a `world_to_body` result must scale it first; `record_hit` does.

    None means "unattributed", which is the safe answer: an unattributed hit
    behaves exactly as it did before this module existed.

    Inside exactly one box wins outright. Inside SEVERAL is ambiguous and
    resolves to None -- and that case is the norm near the hull, because a BoP's
    wing boxes overlap the body box by design (the roots are embedded). Outside
    every box, the nearest wins only by a decisive margin.
    """
    boxes = articulation.part_boxes_for(leaf)
    if not boxes:
        return None
    dists = sorted((_distance_to_box(point, b), n) for n, b in boxes.items())
    inside = [n for d, n in dists if d == 0.0]
    if len(inside) == 1:
        return inside[0]
    if len(inside) > 1:
        return None                      # ambiguous: overlapping boxes
    if len(dists) == 1:
        return dists[0][1]
    (best_d, best), (next_d, _next) = dists[0], dists[1]
    if best_d <= 0.0 or next_d >= best_d * ATTRIBUTION_MARGIN:
        return best
    return None


def _totals(ship) -> dict:
    """The ship's per-part damage totals, created on first use."""
    t = getattr(ship, "_part_damage", None)
    if t is None:
        t = {}
        try:
            ship._part_damage = t
        except Exception:  # noqa: BLE001 - a test double may reject attribute set
            return {}
    return t


def detached_parts(ship) -> set:
    """Names of parts already shed by `ship`."""
    d = getattr(ship, "_parts_detached", None)
    if d is None:
        d = set()
        try:
            ship._parts_detached = d
        except Exception:  # noqa: BLE001
            return set()
    return d


def is_detached(ship, part_name) -> bool:
    return part_name in detached_parts(ship)


def _max_hull(ship) -> float:
    """Ship's MAX hull condition, or 0.0 when it has none."""
    getter = getattr(ship, "GetHull", None)
    hull = getter() if getter is not None else None
    if hull is None:
        return 0.0
    try:
        return float(hull.GetMaxCondition())
    except Exception:  # noqa: BLE001
        return 0.0


def record_hit(ship, iid, body_point_model, absorbed_hull: float):
    """Attribute `absorbed_hull` to whichever part the hit landed on.

    `body_point_model` is a `host_io.world_to_body` result: body frame, MODEL
    units. It is converted to ship units here -- see MODEL_TO_SHIP. Taking the
    raw conversion output (rather than asking callers to scale) keeps the unit
    knowledge in the one module that owns the boxes.

    `iid` is the ship's render instance, passed in rather than looked up — the
    same shape `hull_breakup.after_carve` uses. None is fine (headless): the
    sim-side detach still happens, only the visuals are skipped.

    Returns the part name that just SHEARED OFF, or None. Callers that do not
    care about the return value can ignore it; the detach itself is applied by
    `sever`, which this calls.

    Cheap for the overwhelming majority of ships: a hull with no authored
    detachable parts returns on a dict lookup before any geometry is touched.
    """
    if absorbed_hull <= 0.0:
        return None
    leaf = articulation.leaf_for(ship)
    thresholds = articulation.detachable_for(leaf)
    if not thresholds:
        return None
    point = tuple(c * MODEL_TO_SHIP for c in body_point_model)
    part = part_for_point(leaf, point)
    if part is None or part not in thresholds:
        return None
    if is_detached(ship, part):
        return None
    totals = _totals(ship)
    totals[part] = totals.get(part, 0.0) + float(absorbed_hull)
    limit = _max_hull(ship) * float(thresholds[part])
    _report_progress(ship, part, totals[part], limit)
    if limit > 0.0 and totals[part] >= limit:
        return sever(ship, iid, part)
    return None


# Quarters already announced, per (ship, part). Attribution is invisible from
# the outside -- a wing that never accumulates looks exactly like a player who
# keeps missing -- and that ambiguity cost two live sessions. So under
# --developer it says so, at 25% steps rather than per hit.
_announced: dict = {}


def _report_progress(ship, part, total: float, limit: float) -> None:
    if limit <= 0.0 or not dev_mode.is_enabled():
        return
    quarter = int(min(4.0, (total / limit) * 4.0))
    if quarter <= 0:
        return
    key = (id(ship), part)
    if _announced.get(key, 0) >= quarter:
        return
    _announced[key] = quarter
    print("[severance] %s: %.0f/%.0f (%d%%)"
          % (part, total, limit, int(total / limit * 100)))


def damage_on(ship, part_name) -> float:
    """Damage attributed to `part_name` so far."""
    return float(_totals(ship).get(part_name, 0.0))


def sever(ship, iid, part_name):
    """Detach `part_name` from `ship`. Returns the part name, or None if it
    was already gone.

    Ordering matters and is deliberate:
      1. mark detached FIRST, so anything re-entrant (a subsystem destruction
         event that lands another hit) cannot sever the same part twice;
      2. destroy its subsystems -- the cannon on a wing dies with the wing;
      3. hand off to the renderer, which hides the part and spawns the chunk.

    Step 3 is best-effort: a headless run has no renderer, and a part that is
    gone from the sim but still drawn is a far better failure than an exception
    unwinding through combat.
    """
    if is_detached(ship, part_name):
        return None
    detached_parts(ship).add(part_name)
    _destroy_subsystems_on_part(ship, part_name)
    try:
        from engine.appc import part_detach_render
        part_detach_render.detach(ship, iid, part_name)
    except Exception as _e:  # noqa: BLE001
        dev_mode.log_swallowed("part detach render", _e)
    return part_name


def _destroy_subsystems_on_part(ship, part_name) -> None:
    """Destroy every subsystem whose mount lies on `part_name`.

    Mirrors `hull_breakup._destroy_subsystems_inside`: condition straight to
    zero through the normal subsystem-damage path, so the usual events fire. A
    disruptor cannon that has physically left the ship cannot keep firing.
    """
    leaf = articulation.leaf_for(ship)
    it = getattr(ship, "_iter_subsystems", None)
    if it is None:
        try:
            from engine.appc.combat import _iter_subsystems as it_fn
        except Exception:  # noqa: BLE001
            return
        subs = it_fn(ship)
    else:
        subs = it()
    for sub in list(subs or []):
        try:
            pos = sub.GetPosition()
            point = (pos.GetX(), pos.GetY(), pos.GetZ())
        except Exception:  # noqa: BLE001 - not a mounted subsystem
            continue
        if part_for_point(leaf, point) != part_name:
            continue
        try:
            sub.SetCondition(0.0)
        except Exception as _e:  # noqa: BLE001
            dev_mode.log_swallowed("severed part subsystem destroy", _e)


def reset_ship(ship) -> None:
    """Forget a ship's part damage and detachments (mission swap / respawn)."""
    _announced.pop((id(ship), None), None)
    for key in [k for k in _announced if k[0] == id(ship)]:
        _announced.pop(key, None)
    for attr in ("_part_damage", "_parts_detached"):
        try:
            setattr(ship, attr, None)
        except Exception:  # noqa: BLE001
            pass
