"""Reserve rules: who stays back, and when it commits. Pure: no App."""
from engine.wings import dials


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
                  enemies_in_reach, held_s):
    if lost_member:
        return "loss"
    if decision == "protect":
        return "protect"
    if primary_hull is not None and primary_hull < 0.3:
        return "finish"
    if enemies_in_reach >= 1 and ours >= 2.0 * theirs:
        return "advantage"
    if held_s >= dials.get("reserve_max_s"):
        return "timeout"
    return None
