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


def strength(v: ShipView) -> float:
    return v.power * v.hull * (0.5 + 0.5 * v.shield)


def dist(a, b) -> float:
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
