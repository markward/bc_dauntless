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
own _update_power each tick: a class that overrides _update_power,
_wants_power or GetPowerWanted without opting in (_POWER_FREEZABLE True in the
providing class), the cloak (False), an instance-patched consumer, and an
engaged DRAWS_DIRECT_FROM_MAIN consumer. The instance-patch check runs at
BUILD time only: a patch applied to an already frozen consumer is not seen
until the program is next rebuilt. The tractor system opts in: idle it
is a frozen no-op, and its beams' _firing (ThawParentWakeField) thaws it.
Every value stays current every tick, so nothing reads a stale field. Spec:
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


class ThawParentWakeField(passive_state.WakeField):
    """A WakeField whose write also acts on the parent system's power program:
    the tractor beam's _firing is an input of TractorBeamSystem._wants_power.

    The WakeField part is unconditional. The parent is touched only when the
    value changes: a frozen parent thaws; otherwise a release (new value
    falsy) drops the plant's program so the next rebuild can freeze a
    released tractor. Equal-value writes (FireScript StopFiring, up to 5 Hz)
    leave the program alone.

    A phase-1 audit_step restores only the beam's own dict, so a _firing write
    during an audit step would thaw/invalidate the parent's program without
    restore. Unreachable today (a tractor beam at rest writes nothing); noted
    for future editors."""

    def __set__(self, obj, value) -> None:
        old = obj.__dict__.get(self._name)
        super().__set__(obj, value)
        if old == value:
            return
        parent = obj.GetParentSubsystem()
        if parent is None:
            return
        if parent.__dict__.get("_power_frozen"):
            thaw(parent)
        elif not value:
            invalidate(parent.GetParentShip())


_OVERRIDE_NAMES = ("_update_power", "_wants_power", "GetPowerWanted")
# Instance attributes that make a consumer's rules differ from its class's:
# the overridable methods, POWER_MODE, and the tractor's firing helper.
_INSTANCE_PATCHES = frozenset(_OVERRIDE_NAMES + ("POWER_MODE", "_any_child_firing"))
_class_call_op = {}


def class_is_call_op(cls) -> bool:
    """True when `cls`'s power rules are not the watched PoweredSubsystem ones:
    it sets _POWER_FREEZABLE False, or overrides _update_power / _wants_power /
    GetPowerWanted in a class that does not itself set _POWER_FREEZABLE True."""
    hit = _class_call_op.get(cls)
    if hit is None:
        from engine.appc.subsystems import PoweredSubsystem
        hit = not cls._POWER_FREEZABLE
        if not hit:
            for name in _OVERRIDE_NAMES:
                provider = next(k for k in cls.__mro__ if name in k.__dict__)
                if provider is PoweredSubsystem:
                    continue
                if provider.__dict__.get("_POWER_FREEZABLE") is not True:
                    hit = True
                    break
        _class_call_op[cls] = hit
    return hit


def _is_call_op(c) -> bool:
    if class_is_call_op(type(c)):
        return True
    d = c.__dict__
    for name in _INSTANCE_PATCHES:
        if name in d:
            return True
    # An engaged direct-from-main consumer steals from the main battery itself.
    return bool(c.DRAWS_DIRECT_FROM_MAIN and c._wants_power())


def _build(plant, consumers, dt) -> _Program:
    """Classify each consumer from the state the full pump just left."""
    ops = []
    calls = False
    for c in consumers:
        if _is_call_op(c):
            ops.append((c, None, False, None))
            calls = True
            continue
        base = c._normal_power * dt
        if not c._wants_power() or base <= 0.0:
            pass                                    # no op: nothing to draw
        elif c._power_wanted == 0.0:
            pass                                    # slider at 0: never drawn
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
