"""Wing allies (spec 2026-11-09-wing-leaders-phase-d-design.md §2-§3): the
status each led wing publishes at the end of its brain tick, and the helpers
a wing uses to read its side's other wings. Pure: no App import."""
import math
from dataclasses import dataclass
from typing import Optional

from engine.wings import dials


@dataclass(frozen=True)
class WingStatus:
    wing_id: str
    side: str
    anchor: tuple
    strength_frac: float
    ours: float
    theirs: float
    enemy_centroid: Optional[tuple]
    engaged: bool
    decision: Optional[str]


def in_trouble(s: WingStatus) -> bool:
    """Engaged, and losing on odds, withdrawing, or protecting while the
    odds are close. Protect is the commonest engaged decision (fix wave
    I1: 66-94 % of engaged ticks), so on its own it is no trouble."""
    if not s.engaged:
        return False
    if s.ours < dials.get("reinforce_odds") * s.theirs:
        return True
    if s.decision == "withdraw":
        return True
    return (s.decision == "protect"
            and s.ours < dials.get("reinforce_close_odds") * s.theirs)


def side_of(wing) -> str:
    return wing.side if wing.side is not None else str(id(wing.enemy_group))


def side_allies(wing, wings) -> tuple:
    side = side_of(wing)
    return tuple(sorted(
        (w.status for w in wings
         if w is not wing and w.status is not None and side_of(w) == side),
        key=lambda s: s.wing_id))


# Hold-point geometry (spec §5-§6). Plain 3-tuples in GU; dials read at use.

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _along(p, d, length):
    """p + d * length / |d|, or p when d has no length."""
    n = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    if n <= 0.0:
        return tuple(float(x) for x in p)
    k = length / n
    return (p[0] + d[0] * k, p[1] + d[1] * k, p[2] + d[2] * k)


def _any_perp(axis):
    """A vector perpendicular to `axis` (any, deterministic): axis crossed
    with the world axis it is least aligned with. A zero axis: +X."""
    ax = [abs(c) for c in axis]
    if max(ax) <= 0.0:
        return (1.0, 0.0, 0.0)
    i = ax.index(min(ax))
    e = [0.0, 0.0, 0.0]
    e[i] = 1.0
    x, y, z = axis
    return (y * e[2] - z * e[1], z * e[0] - x * e[2], x * e[1] - y * e[0])


def screen_point(ally_anchor, enemy_centroid) -> tuple:
    """ally + unit(centroid - ally) * min(screen_gu, half the gap)."""
    d = _sub(enemy_centroid, ally_anchor)
    gap = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    return _along(ally_anchor, d, min(dials.get("screen_gu"), 0.5 * gap))


def flank_point(our_anchor, ally_anchor, centroid) -> tuple:
    """C + unit(perp) * flank_gu: perp is (our - C) less its component along
    (ally - C), so we come in on our own side of the enemy's flank. Shorter
    than 1 GU (we are dead behind the ally): any perpendicular."""
    axis = _sub(ally_anchor, centroid)
    rel = _sub(our_anchor, centroid)
    aa = axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2]
    k = ((rel[0] * axis[0] + rel[1] * axis[1] + rel[2] * axis[2]) / aa
         if aa > 0.0 else 0.0)
    perp = (rel[0] - k * axis[0], rel[1] - k * axis[1], rel[2] - k * axis[2])
    if math.sqrt(perp[0] ** 2 + perp[1] ** 2 + perp[2] ** 2) < 1.0:
        perp = _any_perp(axis)
    return _along(centroid, perp, dials.get("flank_gu"))


def lure_point(our_anchor, f_anchor) -> tuple:
    """F + unit(our - F) * feint_stop_gu: just short of F, on our side."""
    return _along(f_anchor, _sub(our_anchor, f_anchor),
                  dials.get("feint_stop_gu"))


def _unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n)


def formation_points(hold_point, toward, n, spread_gu) -> list:
    """The hold formation (spec §5): index 0 is the hold point itself (the
    commander's); the other n - 1 sit evenly spaced on a ring of radius
    spread_gu about it, in the plane perpendicular to toward - hold_point
    (any perpendicular plane when the two coincide)."""
    if n <= 0:
        return []
    hp = tuple(float(x) for x in hold_point)
    axis = _sub(toward, hp)
    if max(abs(c) for c in axis) <= 0.0:
        u, v = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    else:
        w = _unit(axis)
        u = _unit(_any_perp(w))
        v = (w[1] * u[2] - w[2] * u[1], w[2] * u[0] - w[0] * u[2],
             w[0] * u[1] - w[1] * u[0])
    out = [hp]
    k = n - 1
    for i in range(k):
        a = 2.0 * math.pi * i / k
        c, s = math.cos(a) * spread_gu, math.sin(a) * spread_gu
        out.append(tuple(hp[j] + u[j] * c + v[j] * s for j in range(3)))
    return out
