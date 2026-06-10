"""Sensor-damage detection scaling.

A ship detects targets out to a range that scales linearly with its
sensor subsystem's condition, and detects nothing once the sensor is
offline (disabled at <= DisabledPercentage, or destroyed). Used by both
the player target list and the AI candidate-selection gate.

See docs/superpowers/specs/2026-06-10-sensor-damage-detection-scaling-design.md
"""

from engine.appc.subsystems import _is_offline, _get_xyz

# Range used when a ship models no sensor subsystem or carries no
# BaseSensorRange hardpoint data. Preserves the player target list's
# historical 30000 GU reach and keeps sensor-less fixtures fully sighted.
FALLBACK_RANGE_GU = 30000.0


def effective_sensor_range(ship) -> float:
    """Detection range (game units) for *ship* given its sensor condition.

    Full BaseSensorRange when undamaged, scaled linearly by condition
    percentage, and 0.0 once the sensor subsystem is offline (disabled or
    destroyed). Returns FALLBACK_RANGE_GU for ships that don't model a
    sensor subsystem or carry no BaseSensorRange.
    """
    sensors = (ship.GetSensorSubsystem()
               if (ship is not None and hasattr(ship, "GetSensorSubsystem"))
               else None)
    if sensors is None:
        return FALLBACK_RANGE_GU
    if _is_offline(sensors):
        return 0.0
    base = sensors.GetBaseSensorRange()
    if base <= 0.0:
        return FALLBACK_RANGE_GU
    return base * sensors.GetConditionPercentage()


def can_detect(observer, target) -> bool:
    """True iff *observer* can detect *target* within its effective sensor
    range. False when the observer is blind (range 0)."""
    r = effective_sensor_range(observer)
    if r <= 0.0:
        return False
    ox, oy, oz = _get_xyz(observer)
    tx, ty, tz = _get_xyz(target)
    dx, dy, dz = tx - ox, ty - oy, tz - oz
    return (dx * dx + dy * dy + dz * dz) <= (r * r)


# ── AI candidate-selection gate ───────────────────────────────────────────────
# The SDK's SelectTarget.UpdateTargetInfo enumerates candidates via
# ObjectGroup.GetActiveObjectTupleInSet, which has no ship context. We stash the
# querying ship in a module global for the duration of an UpdateTargetInfo call
# (single-threaded Python -- safe) and have a wrapped GetActiveObjectTupleInSet
# consult it. Every other caller of that method runs with the global None and is
# unaffected.

_observing_ship = None


def current_observing_ship():
    """The ship whose sensors gate the in-flight candidate enumeration, or
    None when no AI target selection is active."""
    return _observing_ship


class observing:
    """Context manager that marks *ship* as the current sensor observer for
    the duration of a candidate enumeration. Nestable; restores the prior
    observer (or None) on exit, including on exception."""

    def __init__(self, ship):
        self._ship = ship
        self._prev = None

    def __enter__(self):
        global _observing_ship
        self._prev = _observing_ship
        _observing_ship = self._ship
        return self

    def __exit__(self, *exc):
        global _observing_ship
        _observing_ship = self._prev
        return False


def _wrap_active_tuple(orig):
    """Wrap ObjectGroup.GetActiveObjectTupleInSet so that, while an observer
    ship is published, its result is filtered to objects that observer can
    detect. No-op (identity passthrough) when no observer is set."""

    def _gated_active(self, pSet):
        result = orig(self, pSet)
        observer = current_observing_ship()
        if observer is None:
            return result
        return tuple(obj for obj in result if can_detect(observer, obj))

    _gated_active._sensor_gated = True
    return _gated_active


def _wrap_update_target_info(orig):
    """Wrap SelectTarget.UpdateTargetInfo so the querying ship is published as
    the current observer for the duration of the original call."""

    def _gated_update(self, dEndTime):
        code_ai = getattr(self, "pCodeAI", None)
        ship = code_ai.GetShip() if code_ai is not None else None
        with observing(ship):
            return orig(self, dEndTime)

    _gated_update._sensor_gated = True
    return _gated_update


def install_ai_sensor_gate() -> None:
    """Idempotently install the two-part AI sensor gate: wrap
    ObjectGroup.GetActiveObjectTupleInSet (candidate filter) and
    SelectTarget.UpdateTargetInfo (observer publisher). Safe to call repeatedly
    and safe when the SDK AI package is unavailable."""
    from engine.appc.objects import ObjectGroup
    if not getattr(ObjectGroup.GetActiveObjectTupleInSet, "_sensor_gated", False):
        ObjectGroup.GetActiveObjectTupleInSet = _wrap_active_tuple(
            ObjectGroup.GetActiveObjectTupleInSet
        )

    try:
        import AI.Preprocessors as _pp
    except ImportError:
        # Pure-unit context without the SDK AI tree. The ObjectGroup patch is
        # still live and exercised directly via observing(); the SelectTarget
        # wrap installs on a later call once the SDK is importable.
        return
    if not getattr(_pp.SelectTarget.UpdateTargetInfo, "_sensor_gated", False):
        _pp.SelectTarget.UpdateTargetInfo = _wrap_update_target_info(
            _pp.SelectTarget.UpdateTargetInfo
        )
