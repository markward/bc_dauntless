"""Wing allies (spec 2026-11-09-wing-leaders-phase-d-design.md §2-§3): the
status each led wing publishes at the end of its brain tick, and the helpers
a wing uses to read its side's other wings. Pure: no App import."""
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
    return s.engaged and (s.ours < dials.get("reinforce_odds") * s.theirs
                          or s.decision in ("protect", "withdraw"))


def side_of(wing) -> str:
    return wing.side if wing.side is not None else str(id(wing.enemy_group))


def side_allies(wing, wings) -> tuple:
    side = side_of(wing)
    return tuple(sorted(
        (w.status for w in wings
         if w is not wing and w.status is not None and side_of(w) == side),
        key=lambda s: s.wing_id))
