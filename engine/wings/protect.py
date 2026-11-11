"""Protect rules: damage rate, threat, guards. Pure: no App imports."""

from engine.wings import dials
from engine.wings.assess import dist, strength
from engine.wings.rotate import weak_face


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


def threatened(protectees, rates, enemies, anchor, strict=()):
    """The most threatened protectee, or None. A protectee with no attacker
    in reach is never threatened, whatever its damage rate (rocks, green
    alert, a fight past engage_gu): there is nobody to turn on.

    Heavy fire: heavy_fire_frac lost in the window, or heavy_fire_attackers
    on it. A `strict` protectee (an ordinary wing member) needs real
    danger instead: heavy_fire_frac lost AND under protect_member_frac of
    its strength. In a big brawl some member always met heavy fire, so
    protect held the wing all fight and no flank ever ran (Mark's C play
    test 2, 2026-11-10). The player and listed protect ships keep heavy
    fire."""
    reach = dials.get("engage_gu")
    heavy = dials.get("heavy_fire_frac")
    best = None
    for p in protectees:
        rate = rates.get(p.name, 0.0)
        n = len(attackers_of(p.name, enemies, anchor.pos, reach))
        if n == 0:
            continue
        if p.name in strict:
            frac = strength(p) / p.power if p.power > 0 else 0.0
            hit = rate >= heavy and frac < dials.get("protect_member_frac")
        else:
            hit = rate >= heavy or n >= dials.get("heavy_fire_attackers")
        if hit:
            key = (-rate, -n, p.name)
            if best is None or key < best[0]:
                best = (key, p)
    return best[1] if best else None


def pick_guards(members, protectee, exclude, strength_frac, prev=()):
    """Guard names for `protectee`. Eligible: not excluded, not the
    protectee, strength fraction >= 0.6 and weakest shield face at or above
    rotate_out_shield (a ship due to fall back never guards). `prev` are the
    current guards of the SAME protectee: each still eligible keeps its slot
    (incumbency, so a guard that left the crowd to reach its point is not
    replaced by a wingmate now nearer); only vacancies go to the nearest."""
    count = int(dials.get("guard_count"))
    if count >= 1 and len(members) >= 6:
        count = max(count, 2)
    out = dials.get("rotate_out_shield")
    cands = [m for m in members
             if m.name not in exclude and m.name != protectee.name
             and strength_frac.get(m.name, 0.0) >= 0.6
             and weak_face(m) >= out]
    cands.sort(key=lambda m: (dist(m.pos, protectee.pos), m.name))
    keep = [m.name for m in cands if m.name in prev][:count]
    fill = [m.name for m in cands if m.name not in keep]
    return keep + fill[:count - len(keep)]


def guard_point(protectee_pos, attacker_pos):
    d = dist(attacker_pos, protectee_pos)
    if d <= 1e-9:
        return tuple(protectee_pos)
    step = min(dials.get("interpose_gu"), 0.5 * d)
    return tuple(p + (a - p) / d * step
                 for p, a in zip(protectee_pos, attacker_pos))
