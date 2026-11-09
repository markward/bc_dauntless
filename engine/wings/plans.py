"""Pure wing plans: target group, rejoin hysteresis, desperation rolls.

Spec 2026-11-09-wing-leaders-phase-a-design.md sections 7, 9, 10. No App imports.
"""
from engine.wings import assess, dials


def target_priorities(enemies, anchor, choice, km, player_target):
    enemies = list(enemies)
    if not enemies:
        return {}
    leash = dials.get("leash_gu")
    reach = [e for e in enemies if assess.dist(e.pos, anchor.pos) <= leash]
    if not reach and not any(e.name == player_target for e in enemies):
        nearest = min(enemies,
                      key=lambda e: (assess.dist(e.pos, anchor.pos), e.name))
        return {nearest.name: 3.0}
    names = {e.name for e in reach}  # may be empty if only player_target
    out = {n: km.get(n, 0.0) for n in names}
    primary = choice.primary if choice.primary in names else None
    secondaries = [s for s in choice.secondaries if s in names]
    # A listed ship in reach (km priority > 0: a protect / hunt target) is
    # the primary, the decision's primary stepping down to first secondary:
    # the listed ships stay what the side goes for, as km_targeting meant.
    listed = [e for e in reach if km.get(e.name, 0.0) > 0.0]
    if listed and (primary is None or km.get(primary, 0.0) <= 0.0):
        best = min(listed, key=lambda e: (-km[e.name],
                                          assess.dist(e.pos, anchor.pos),
                                          e.name))
        if primary is not None:
            secondaries = [primary] + secondaries
        primary = best.name
        secondaries = [s for s in secondaries if s != primary][:2]
    if player_target is not None and any(
            e.name == player_target for e in enemies):
        primary = player_target
        out.setdefault(primary, km.get(primary, 0.0))
        secondaries = [s for s in secondaries if s != primary]
    for s in secondaries:
        out[s] = max(1.5, km.get(s, 0.0))
    if primary is not None:
        out[primary] = max(3.0, km.get(primary, 0.0))
    return out


def leaderless_priorities(enemies, km):
    return {e.name: km.get(e.name, 0.0) for e in enemies}


def rejoin_flags(member_views, anchor, prev, gather, commander, player=None):
    leash = dials.get("leash_gu")
    set_at = leash + dials.get("leash_slack_gu")
    gather_gu = dials.get("regroup_gather_gu")
    out = {}
    for v in member_views:
        if v.name == commander or v.name == player:
            out[v.name] = False
            continue
        d = assess.dist(v.pos, anchor.pos)
        if d > set_at:
            flag = True
        elif d < leash:
            flag = False
        else:
            flag = bool(prev.get(v.name, False))
        if gather and d > gather_gu:
            flag = True
        out[v.name] = flag
    return out


def desperation(member_views, already, rng):
    limit = dials.get("desperate_hull")
    ram = dials.get("ram_chance")
    out = {}
    for v in sorted(member_views, key=lambda m: m.name):
        if v.hull < limit and not already.get(v.name):
            out[v.name] = "ram" if rng.random() < ram else "flee"
    return out
