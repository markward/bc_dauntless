"""Reserve rules: who stays back, and when it commits. Pure: no App."""
from engine.wings import dials
from engine.wings.assess import dist


def pick_reserve(views, commander, players, min_wing):
    pool = [v for v in views if v.name not in players]
    if len(pool) < min_wing:
        return None
    cands = [v for v in pool if v.name != commander]
    if not cands:
        return None
    return min(cands, key=lambda v: (-(v.hull + v.shield), v.power,
                                     v.name)).name


def commit_reason(*, lost_member, decision, primary_hull, ours, theirs,
                  enemies_in_reach, held_s, protect_damaged=False):
    """`protect_damaged`: the protectee is losing strength (heavy_fire_frac
    in the window). A protect on attacker count alone keeps the reserve:
    in a Quick Battle that fires at first contact (C play test)."""
    if lost_member:
        return "loss"
    if decision == "protect" and protect_damaged:
        return "protect"
    if primary_hull is not None and primary_hull < 0.3:
        return "finish"
    if enemies_in_reach >= 1 and ours >= 2.0 * theirs:
        return "advantage"
    if held_s >= dials.get("reserve_max_s"):
        return "timeout"
    return None


def hold_point(anchor_pos, reserve_pos, centroid, reserve_gu):
    """reserve_gu farther from the enemy centroid than the anchor, on the
    reserve's own bearing from it. A point on the anchor's bearing swings
    round with a commander circling the enemy -- faster than any ship of
    the wing at the reserve's range -- so the reserve chased it and drifted
    in front (Task 6). The anchor itself while there was never an enemy;
    on the anchor's bearing when the reserve sits on the centroid."""
    d_anchor = dist(anchor_pos, centroid)
    if d_anchor <= 1e-9:
        return tuple(anchor_pos)
    r = dist(reserve_pos, centroid)
    if r <= 1e-9:
        reserve_pos, r = anchor_pos, d_anchor
    return tuple(c + (p - c) / r * (d_anchor + reserve_gu)
                 for p, c in zip(reserve_pos, centroid))
