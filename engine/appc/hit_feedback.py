"""Damage-impact feedback dispatch.

Called from engine.appc.combat.apply_hit after damage is routed. Classifies
the impact into SHIELD / HULL / CRITICAL based on the per-stage absorbed
amounts and any subsystem state transition this tick, then fans out to the
mutually-exclusive visual (shield_hit OR hit_vfx.spawn), per-tier audio,
and (player-only) camera shake.

Severity rule (spec §3.1):
- CRITICAL iff a non-hull subsystem flipped state this tick.
- SHIELD iff shields absorbed > 0 and nothing else absorbed anything.
- HULL otherwise.

The WeaponHitEvent broadcast in apply_hit is unchanged; dispatch runs
before it, and dispatch failures are swallowed so a renderer-binding
crash never suppresses mission-side event handlers.
"""
from enum import IntEnum


class Severity(IntEnum):
    SHIELD = 0
    HULL = 1
    CRITICAL = 2


def classify(*, absorbed_shields: float, absorbed_subsystem: float,
             absorbed_hull: float, sub_transition,
             subsystem, hull) -> Severity:
    """Pure function. Tested separately from dispatch."""
    if sub_transition is not None and subsystem is not None and subsystem is not hull:
        return Severity.CRITICAL
    if absorbed_shields > 0.0 and absorbed_subsystem == 0.0 and absorbed_hull == 0.0:
        return Severity.SHIELD
    return Severity.HULL


# dispatch(...) is implemented in Task 7. Until then a no-op stub keeps
# apply_hit's call site importable.
def dispatch(*args, **kwargs) -> None:
    """Stub — replaced in Task 7."""
    return None
