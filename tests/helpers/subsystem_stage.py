"""Tick the native subsystem stage over explicit ships (phase 6 Task 8).

The shield, power, cloak and repair pieces are native only
(engine/appc/native_subsystems.py, native/src/combat/src/subsystem_step.cc):
there is no Python ``Update`` to call. A test that drove one directly ticks
the real native stage over its own ships instead, through
``native_subsystems._step_set`` -- the per-set session the stage opens --
so no roster patching and no set membership is needed.

The ships must be real registered ``ShipClass`` rows. A bare subsystem gets
one around it with ``ship_for`` (a bare ``ShipClass()``, no default
subsystems, the subsystem in its typed slot). A piece the mirror cannot
run is SKIPPED by the stage (subsystem_step.h THE SKIPS); ``tick_subsystems``
fails on any skip, so a test cannot pass by silently running nothing.
"""
from engine.core.loop import TICK_DELTA


def tick_subsystems(ships, dt: float = TICK_DELTA, ticks: int = 1,
                    allow_skips: bool = False) -> None:
    """`ticks` stages of `dt` over `ships` (a list, roster order), exactly
    as the game's stage runs one set. Raises AssertionError when a piece
    was skipped, unless `allow_skips`."""
    from engine.appc import native_combat, native_subsystems
    assert native_combat._enabled, (
        "the native mirror is not live (native_combat.configure())")
    ships = list(ships)
    before = native_subsystems.skip_counts()
    for _ in range(ticks):
        native_subsystems._step_set(ships, dt)
    after = native_subsystems.skip_counts()
    if not allow_skips and after != before:
        raise AssertionError(
            "the native subsystem stage skipped pieces it could not run: "
            "%r (subsystem_step.h THE SKIPS)" % (after,))


def ship_for(sub, name: str = "Test Ship"):
    """The ShipClass `sub` is on, or a bare new one holding it in its typed
    slot (a consumer of any other kind joins its powered consumers)."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import (CloakingSubsystem, PowerSubsystem,
                                        RepairSubsystem, ShieldSubsystem)
    ship = sub.GetParentShip() if hasattr(sub, "GetParentShip") else None
    if isinstance(ship, ShipClass):
        return ship
    ship = ShipClass()
    ship.SetName(name)
    if isinstance(sub, PowerSubsystem):
        ship.SetPowerSubsystem(sub)
    elif isinstance(sub, ShieldSubsystem):
        ship.SetShieldSubsystem(sub)
    elif isinstance(sub, CloakingSubsystem):
        ship.SetCloakingSubsystem(sub)
    elif isinstance(sub, RepairSubsystem):
        ship.SetRepairSubsystem(sub)
    else:
        ship.AddPoweredConsumer(sub)
    return ship


def tick_subsystem(sub, dt: float = TICK_DELTA, ticks: int = 1,
                   allow_skips: bool = False) -> None:
    """tick_subsystems over the ship `sub` is on (ship_for)."""
    tick_subsystems([ship_for(sub)], dt, ticks, allow_skips)
