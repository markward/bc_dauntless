"""The death check, at the tick boundary (spec
docs/superpowers/specs/2026-11-02-native-damage-design.md, rulings M3, M5,
R4, R5).

Every condition write -- ``DamageSystem``, ``DestroySystem``,
``SetCondition``, ``SetConditionPercentage``, severance -- reports itself
here (``note_write``) when it took a subsystem across 0 or left a critical
subsystem at 0. Nothing happens in the write. ``drain`` runs the check for
each noted write, in write order, at the boundary:

* the ship is invincible NOW -> nothing (M1, R5): no hull cascade, no breach
  arm, no death. E3M5's ``KillGonDev`` zeroes the hull and only then makes
  the derelict invincible, so a check inside the write would have killed it;
* else a >0 -> 0 crossing of the power plant arms the warp-core breach, of
  the hull schedules the subsystem cascade (objects._route_zero_crossing);
* then, if the subsystem is critical and STILL at 0, and the ship is neither
  dying nor dead, the death begins through the one death entry
  (``ship_death.begin``, a rock's ``rocks.death.begin``) with the write's
  killer.

Nothing is re-checked later: a ship that sat at a critical 0 while
invincible does not die when the flag clears, only at its next write that
leaves a critical subsystem at 0 (R4).

WHERE THE BOUNDARY IS. Live: the host's per-tick combat boundary, right
after the tick's effect-queue scope flushes (``host_loop._combat_tick_boundary``,
both switch states). A write outside the combat step (a script on a timer,
radiation, a collision) waits for the next one. A ``GameLoop`` run without
the host (the headless harness, tools) is its own boundary, at the end of
each tick (``GameLoop(owns_boundary=True)``, the default).

The pending list is ONE seam: native-damage Task 2 turns each entry into an
ordered ``ZERO_CROSS`` effect-queue entry carrying the same fields.
"""
#: Noted writes, oldest first: (ship, subsystem, crossed_zero, killer).
_pending: list = []


def note_write(ship, subsystem, before: float, killer=None) -> None:
    """A condition write on `subsystem` of `ship` happened, from `before`.
    Note it when it crossed >0 -> 0 or left a critical subsystem at 0."""
    if ship is None or subsystem is None:
        return
    after = subsystem.GetCondition()
    if after > 0.0:
        return
    crossed = before > 0.0
    from engine.appc.objects import _is_critical
    if not crossed and not _is_critical(subsystem):
        return
    _pending.append((ship, subsystem, crossed, killer))


def drain() -> None:
    """Run every noted check, in write order. A check whose death splashes
    another ship to 0 notes that write; it is checked in the same drain."""
    while _pending:
        batch = list(_pending)
        del _pending[:]
        for ship, subsystem, crossed, killer in batch:
            _check(ship, subsystem, crossed, killer)


def _check(ship, subsystem, crossed, killer) -> None:
    from engine.appc.objects import (_begin_death, _is_critical,
                                     _route_zero_crossing)
    from engine.core.ids import implements
    if implements(ship, "IsInvincible") and ship.IsInvincible():
        return
    _route_zero_crossing(ship, subsystem, crossed)
    if (subsystem.GetCondition() <= 0.0 and _is_critical(subsystem)
            and not ship.IsDying() and not ship.IsDead()):
        _begin_death(ship, killer)


def pending() -> list:
    """The noted writes not yet checked (tests, diagnostics)."""
    return list(_pending)


def reset() -> None:
    """Drop every pending check (mission swap, tests)."""
    del _pending[:]
