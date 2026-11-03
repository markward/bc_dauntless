"""The death check, at the tick boundary (spec
docs/superpowers/specs/2026-11-02-native-damage-design.md, rulings M3, M5,
R4, R5; controller rulings R7, R9).

Every condition write -- ``DamageSystem``, ``DestroySystem``,
``SetCondition``, ``SetConditionPercentage``, severance -- reports itself
here (``note_write``) when it took a subsystem across 0 or left a critical
subsystem at 0, by emitting a ``ZERO_CROSS`` effect-queue entry AT THE WRITE,
in emission order with the hit's other entries (R7). Nothing happens in the
write. Delivery (``_check``) runs the check at the boundary:

* the ship is invincible NOW -> nothing (M1, R5): no hull cascade, no breach
  arm, no death. E3M5's ``KillGonDev`` zeroes the hull and only then makes
  the derelict invincible, so a check inside the write would have killed it;
* the subsystem is no longer at 0 NOW -> nothing (ruling I1): the crossing
  is decided at the boundary like the death, so a hull dipped to 0 and
  restored before it (QB ``sim_restore``, ``repair_ship_fully``) neither
  cascades nor dies;
* else a >0 -> 0 crossing of the power plant arms the warp-core breach, of
  the hull schedules the subsystem cascade (objects._route_zero_crossing);
* then, unless the ship is dying or dead, the death begins through the one
  death entry (``ship_death.begin``, a rock's ``rocks.death.begin``) with the
  write's killer when the subsystem is critical, or is the ship's targetable
  power plant, destroyed (a breach destroys the ship).

Because ZERO_CROSS is emitted at the write, the killing hit's death -- its
ET_OBJECT_EXPLODING -- is delivered before that hit's own ET_WEAPON_HIT
(event-inventory rule R2).

The destroyed-plant trigger (``PowerSubsystem._trigger_breach``, from
``GameLoop.tick``) is the same seam (R9): ``note_breach`` emits a crossing
ZERO_CROSS for the plant, so there is one death path.

Nothing is re-checked later: a ship that sat at a critical 0 while
invincible does not die when the flag clears, only at its next write that
leaves a critical subsystem at 0 (R4).

WHERE THE BOUNDARY IS: ``effect_queue.boundary`` (THE DAMAGE KINDS there).
Outside the tick scope a ZERO_CROSS is held until it.
"""


def note_write(ship, subsystem, before: float, killer=None) -> None:
    """A condition write on `subsystem` of `ship` happened, from `before`.
    Emit ZERO_CROSS when it crossed >0 -> 0 or left a critical subsystem at
    0."""
    if ship is None or subsystem is None:
        return
    after = subsystem.GetCondition()
    if after > 0.0:
        return
    crossed = before > 0.0
    from engine.appc.objects import _is_critical
    if not crossed and not _is_critical(subsystem):
        return
    from engine.appc import effect_queue
    effect_queue.emit(effect_queue.ZERO_CROSS, ship, subsystem, crossed,
                      killer)


def note_breach(ship, plant) -> None:
    """The destroyed-plant trigger (R9): the plant's crossing, checked at the
    boundary like any write's."""
    from engine.appc import effect_queue
    effect_queue.emit(effect_queue.ZERO_CROSS, ship, plant, True, None)


def _check(ship, subsystem, crossed, killer) -> None:
    """ZERO_CROSS's delivery: the check, as of now."""
    from engine.appc.objects import (_begin_death, _is_critical,
                                     _route_zero_crossing)
    from engine.core.ids import implements
    if implements(ship, "IsInvincible") and ship.IsInvincible():
        return
    if subsystem.GetCondition() > 0.0:
        return              # restored before the boundary (ruling I1)
    _route_zero_crossing(ship, subsystem, crossed)
    if ship.IsDying() or ship.IsDead():
        return
    if _is_critical(subsystem) or _is_breached_plant(ship, subsystem):
        _begin_death(ship, killer)


def _is_breached_plant(ship, subsystem) -> bool:
    """`subsystem` is `ship`'s targetable power plant, destroyed: "Reaching
    0% causes a warp-core breach and destroys the ship" (manual p.16), so it
    kills even when the hardpoint leaves the plant non-critical (a drydock's,
    GenericTemplate's)."""
    from engine.appc.objects import _is_targetable
    from engine.core.ids import implements
    if not implements(ship, "GetPowerSubsystem"):
        return False
    return (subsystem is ship.GetPowerSubsystem()
            and _is_targetable(subsystem)
            and bool(subsystem.IsDestroyed()))
