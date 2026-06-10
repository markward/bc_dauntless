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
# The SDK's SelectTarget.FindGoodTarget and StarbaseAttack.GetTargets both
# enumerate candidates via ObjectGroup.GetActiveObjectTupleInSet, which has no
# ship context. We stash the querying ship in a module global for the duration
# of each call (single-threaded Python -- safe) and have a wrapped
# GetActiveObjectTupleInSet consult it. Every other caller of that method
# (mission proximity checks, MissionLib's player scan, the player target list)
# runs with the global None and is unaffected; only SelectTarget.FindGoodTarget
# and StarbaseAttack.GetTargets publish an observer.

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


def _wrap_find_good_target(orig):
    """Wrap SelectTarget.FindGoodTarget (the candidate-enumeration method) so
    the querying ship is published as the current observer for the duration of
    the original call. FindGoodTarget calls ObjectGroup.GetActiveObjectTupleInSet,
    which the companion wrapper filters while an observer is published."""

    def _gated_find(self):
        code_ai = getattr(self, "pCodeAI", None)
        ship = code_ai.GetShip() if code_ai is not None else None
        with observing(ship):
            return orig(self)

    _gated_find._sensor_gated = True
    return _gated_find


def _wrap_get_targets(orig):
    """Wrap StarbaseAttack.GetTargets (an offensive target-acquisition method)
    so the querying ship — passed as the pShip argument — is published as the
    current observer while it enumerates candidates via
    ObjectGroup.GetActiveObjectTupleInSet."""

    def _gated_get_targets(self, pShip):
        with observing(pShip):
            return orig(self, pShip)

    _gated_get_targets._sensor_gated = True
    return _gated_get_targets


def _gated_fire_script_target_visible(self, pTarget):
    """Replacement for FireScript.TargetVisible, which stock BC stubs to
    unconditionally return 1 ("# For now, skip this check").

    FireScript is the firing preprocessor used by FedAttack / NonFedAttack /
    CloakAttack etc.; it resolves its target by name (bypassing the candidate-
    enumeration gate) and fires every ~0.2s. Without a sensor gate here, a ship
    whose sensors are damaged/offline keeps firing at an already-locked target.

    Gate firing on the firing ship's sensor reach: a ship can only engage a
    target it can actually detect (can_detect, which scales range by sensor
    condition and returns False when the sensor is offline). When the firing
    ship can't be resolved (non-ship AI / legacy fixtures), default to visible
    so firing is never broken for cases this gate doesn't model.
    """
    code_ai = getattr(self, "pCodeAI", None)
    ship = code_ai.GetShip() if code_ai is not None else None
    self.bTargetVisible = 1 if (ship is None or can_detect(ship, pTarget)) else 0
    return self.bTargetVisible


_gated_fire_script_target_visible._sensor_gated = True


def install_ai_sensor_gate() -> None:
    """Idempotently install the AI sensor gate: wrap
    ObjectGroup.GetActiveObjectTupleInSet (candidate filter),
    SelectTarget.FindGoodTarget / StarbaseAttack.GetTargets (observer
    publishers for target selection), and replace FireScript.TargetVisible
    (the firing/engagement gate). Safe to call repeatedly and safe when the
    SDK AI package is unavailable."""
    from engine.appc.objects import ObjectGroup
    if not getattr(ObjectGroup.GetActiveObjectTupleInSet, "_sensor_gated", False):
        ObjectGroup.GetActiveObjectTupleInSet = _wrap_active_tuple(
            ObjectGroup.GetActiveObjectTupleInSet
        )

    try:
        import AI.Preprocessors as _pp
    except ImportError:
        # Pure-unit context without the SDK AI tree. The ObjectGroup patch is
        # still live (exercised directly via observing()); the FindGoodTarget
        # wrap is simply absent here. Production installs this from the host
        # bootstrap, where AI.Preprocessors is importable, so the wrap lands.
        return
    if not getattr(_pp.SelectTarget.FindGoodTarget, "_sensor_gated", False):
        _pp.SelectTarget.FindGoodTarget = _wrap_find_good_target(
            _pp.SelectTarget.FindGoodTarget
        )

    # Gate the actual firing path. FireScript.TargetVisible is a no-op stub in
    # stock BC; replace it so a ship that can't detect its target stops firing.
    if not getattr(_pp.FireScript.TargetVisible, "_sensor_gated", False):
        _pp.FireScript.TargetVisible = _gated_fire_script_target_visible

    try:
        import AI.PlainAI.StarbaseAttack as _sba
    except ImportError:
        return
    if not getattr(_sba.StarbaseAttack.GetTargets, "_sensor_gated", False):
        _sba.StarbaseAttack.GetTargets = _wrap_get_targets(
            _sba.StarbaseAttack.GetTargets
        )
