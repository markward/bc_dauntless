"""Protect rules: damage rate, threat, guards. Pure: no App imports."""

from engine.wings import dials
from engine.wings.assess import dist


def damage_rate(hist, now, window_s):
    pts = [(t, s) for t, s in hist if now - t <= window_s]
    if len(pts) < 2:
        return 0.0
    oldest, newest = pts[0][1], pts[-1][1]
    if oldest <= 0:
        return 0.0
    return max(0.0, (oldest - newest) / oldest)


def attackers_of(name, enemies, reach_center, reach_gu):
    return [e for e in enemies
            if e.target == name and dist(e.pos, reach_center) <= reach_gu]


def threatened(protectees, rates, enemies, anchor):
    reach = dials.get("engage_gu")
    best = None
    for p in protectees:
        rate = rates.get(p.name, 0.0)
        n = len(attackers_of(p.name, enemies, anchor.pos, reach))
        if rate >= dials.get("heavy_fire_frac") or n >= dials.get("heavy_fire_attackers"):
            key = (-rate, -n, p.name)
            if best is None or key < best[0]:
                best = (key, p)
    return best[1] if best else None


def pick_guards(members, protectee, exclude, strength_frac):
    count = int(dials.get("guard_count"))
    if len(members) >= 6:
        count = max(count, 2)
    cands = [m for m in members
             if m.name not in exclude and m.name != protectee.name
             and strength_frac.get(m.name, 0.0) >= 0.6]
    cands.sort(key=lambda m: (dist(m.pos, protectee.pos), m.name))
    return [m.name for m in cands[:count]]


def guard_point(protectee_pos, attacker_pos):
    d = dist(attacker_pos, protectee_pos)
    if d <= 1e-9:
        return tuple(protectee_pos)
    step = min(dials.get("interpose_gu"), 0.5 * d)
    return tuple(p + (a - p) / d * step
                 for p, a in zip(protectee_pos, attacker_pos))
