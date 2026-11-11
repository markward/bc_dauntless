"""Strength assessment over plain ship views. Pure: no App imports."""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ShipView:
    name: str
    pos: tuple
    hull: float
    shield: float
    power: float
    wing_id: Optional[str] = None
    is_commander: bool = False
    target: Optional[str] = None
    faces: tuple = ()
    weapons_down: bool = False
    # Weakest single shield face; None reads as `shield` (the mean).
    weak_face: Optional[float] = None
    # A wing member falling back to recharge (its wing's fallback_since):
    # target picks pass over it while anything else is in reach.
    retiring: bool = False


def strength(v: ShipView) -> float:
    return v.power * v.hull * (0.5 + 0.5 * v.shield)


def dist(a, b) -> float:
    # The 3-vector case (every ship position) without the generator: the
    # same squares summed by sum() in the same order, so bit-identical.
    if len(a) == 3 and len(b) == 3:
        return math.sqrt(sum(((a[0] - b[0]) ** 2, (a[1] - b[1]) ** 2,
                              (a[2] - b[2]) ** 2)))
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def side_strength(views, anchor_pos, within_gu: float) -> float:
    return sum(strength(v) for v in views
               if dist(v.pos, anchor_pos) <= within_gu)


def weakest(views) -> Optional[ShipView]:
    views = list(views)
    if not views:
        return None
    return min(views, key=lambda v: (strength(v), v.name))


def fraction_beyond(member_views, anchor_pos, radius_gu: float) -> float:
    member_views = list(member_views)
    if not member_views:
        return 0.0
    n = sum(1 for v in member_views if dist(v.pos, anchor_pos) > radius_gu)
    return n / len(member_views)


def centroid(views) -> Optional[tuple]:
    views = list(views)
    if not views:
        return None
    n = len(views)
    return tuple(sum(v.pos[i] for v in views) / n for i in range(3))
