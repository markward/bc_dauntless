"""The power draw program: PowerSubsystem._pump_consumers without re-running
the consumers whose demand is steady.

The plant changes state every tick while anything draws, so it is never
skipped. What steady demand makes a no-op is each consumer's _update_power:
re-deriving the same demand and writing the same four output fields. Here a
consumer whose demand inputs are watched (FrozenField on PoweredSubsystem) and
whose draw was met in full is FROZEN, and the plant repeats only its draw
through the same PowerSubsystem._draw, in attach order. A short draw records
through the same PoweredSubsystem._record_draw _update_power uses. A consumer
whose rules read more than its own watched fields stays a CALL op and runs its
own _update_power each tick: the cloak (_POWER_FREEZABLE False) and any
DRAWS_DIRECT_FROM_MAIN consumer (the tractor, whose _wants_power reads its
emitters' firing state). Every value stays current every tick, so nothing
reads a stale field. Spec:
docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md §4, §8
"Phase 2 as planned".

The program lives in plant.__dict__["_passive_power"], so the audit's snapshot
of the plant covers it. It is dropped by any write to a frozen consumer's
watched field (thaw), by any change to the ship's subsystems
(ShipClass._attach_subsystem, ShipSubsystem.AddChildSubsystem), and once an
unmet call op is met again (so it can freeze); a mismatched tick length or
consumer count also means a full pump.
"""
from engine.appc import passive_state

_counts = {"program_ticks": 0, "full_ticks": 0, "frozen": 0, "thawed": 0}
# True while the audit's reference run (_pump_consumers) rewrites frozen
# fields: those thaws are undone by the audit's restore and are not counted.
_in_reference = False


class FrozenField:
    """Data descriptor with no __get__: reads stay plain instance-dict reads,
    every write (even of an equal value) thaws a frozen consumer."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        if obj.__dict__.get("_power_frozen"):
            obj._passive_power_thaw()


class _Program:
    __slots__ = ("dt", "n", "ops", "total")

    def __init__(self, dt, n, ops, total):
        self.dt = dt
        self.n = n
        self.ops = ops          # [(consumer, wanted, mode, base)] or
                                # [(consumer, None, unmet, None)] for a call op
        self.total = total      # None when any op is a call op


def counts() -> dict:
    return dict(_counts)


def reset() -> None:
    global _in_reference
    _in_reference = False
    for k in _counts:
        _counts[k] = 0


def drop(plant) -> None:
    """Forget `plant`'s program, if it has one. Tolerates anything."""
    d = getattr(plant, "__dict__", None)
    if d is not None and d.get("_passive_power") is not None:
        d["_passive_power"] = None


def invalidate(ship) -> None:
    """Drop the program of `ship`'s current plant. Tolerates None, doubles and
    ships with no plant."""
    if ship is None:
        return
    get = getattr(ship, "GetPowerSubsystem", None)
    if get is None:
        return
    drop(get())


def thaw(consumer) -> None:
    consumer.__dict__["_power_frozen"] = False
    if not _in_reference:
        _counts["thawed"] += 1
    invalidate(consumer.GetParentShip())


def _build(plant, consumers, dt) -> _Program:
    """Classify each consumer from the state the full pump just left."""
    ops = []
    calls = False
    for c in consumers:
        cls = type(c)
        if not cls._POWER_FREEZABLE or c.DRAWS_DIRECT_FROM_MAIN:
            ops.append((c, None, False, None))
            calls = True
            continue
        base = c._normal_power * dt
        if not c._wants_power() or base <= 0.0:
            pass                                    # no op: nothing to draw
        elif c._power_received == c._power_wanted:
            ops.append((c, c._power_wanted, c.POWER_MODE, base))
        else:
            ops.append((c, None, True, None))       # an unmet draw
            calls = True
            continue
        c.__dict__["_power_frozen"] = True
        _counts["frozen"] += 1
    total = None if calls else plant._sum_wanted(consumers)
    return _Program(dt, len(consumers), ops, total)


def _run(program, plant, consumers, dt) -> None:
    draw = plant._draw
    for c, wanted, mode, base in program.ops:
        if wanted is not None:
            got = draw(wanted, mode)
            if got != wanted:
                c._record_draw(wanted, got, base)   # thaws c: drops the program
        else:
            c._update_power(dt, plant)
            # An unmet draw that is met again can freeze: rebuild next tick.
            if mode and c._power_received == c._power_wanted:
                drop(plant)
    total = program.total
    plant._power_wanted_total = (total if total is not None
                                 else plant._sum_wanted(consumers))
    _counts["program_ticks"] += 1


def _reference(plant, dt) -> None:
    global _in_reference
    _in_reference = True
    try:
        plant._pump_consumers(dt)
    finally:
        _in_reference = False


def pump(plant, dt: float) -> None:
    """PowerSubsystem._pump_consumers, through the program when one is held."""
    ship = plant.GetParentShip()
    consumers = getattr(ship, "_powered_consumers", None) if ship is not None else None
    if not consumers:
        return
    d = plant.__dict__
    program = d.get("_passive_power")
    if program is None or program.dt != dt or program.n != len(consumers):
        # Unfreeze quietly first: the full pump rewrites every consumer, and
        # those writes are not thaws (the program is already gone).
        for c in consumers:
            if c.__dict__.get("_power_frozen"):
                c.__dict__["_power_frozen"] = False
        plant._pump_consumers(dt)
        _counts["full_ticks"] += 1
        d["_passive_power"] = _build(plant, consumers, dt)
        return
    if passive_state.audit_enabled():
        passive_state.audit_compare(
            [plant, *consumers], lambda: _reference(plant, dt),
            lambda: _run(program, plant, consumers, dt))
    else:
        _run(program, plant, consumers, dt)
