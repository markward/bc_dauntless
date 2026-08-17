"""Installs the sensor gate into the SDK's AI target-acquisition and firing paths.

Four monkey-patches over original-game code, plus the observer publication they
coordinate through:

  * ``ObjectGroup.GetActiveObjectTupleInSet`` — the candidate filter.
  * ``AI.Preprocessors.SelectTarget.FindGoodTarget`` — publishes the querying ship.
  * ``AI.PlainAI.StarbaseAttack.GetTargets`` — likewise.
  * ``AI.Preprocessors.FireScript.TargetVisible`` — the firing gate, which stock
    BC stubs to unconditionally 1 ("# For now, skip this check").

It owns NO detection rule of its own. Every verdict here is
``sensor_detection.can_detect``; this module only decides which SDK call sites
consult it and supplies the observer they lack. Split out of
sensor_detection.py, which needed "and also an SDK monkey-patch installer" to
describe itself.

TO INTERCEPT THE PREDICATE IN A TEST, PATCH ``ai_sensor_gate.can_detect``, not
``sensor_detection.can_detect``. The name is bound into this module's globals at
import (``from ... import can_detect``), where before the split the wrappers
resolved it out of sensor_detection's own globals, so patching it there no
longer reaches them. Patching the *flag* is unaffected and still belongs on
sensor_detection — ``can_detect`` reads ``ENHANCED_SENSOR_CONTEST`` at call
time, from its own module, and this module deliberately does not import it (see
tests/unit/test_ai_sensor_gate.py::
test_fire_script_cloak_gate_is_absolute_with_the_contest_off, which patches the
flag on sensor_detection precisely to assert the toggle was not cloned here).

⚠️ THE DEPENDENCY RUNS ONE WAY, and the split was made on that finding:
``observing`` / ``current_observing_ship`` moved HERE rather than staying with
the predicate because nothing in sensor_detection reads them — not
``can_detect``, not ``concealment_at``, not ``effective_sensor_range``, not
``clear_undetectable_player_lock``. Their only readers are the three wrappers
below. The observer global is machinery for reaching an SDK method that takes no
ship, not part of the detection rule. If a future change makes the predicate
observer-aware through this global, that is the signal to move the pair BACK,
because the arrow would then point the wrong way.

See docs/superpowers/specs/2026-06-10-sensor-damage-detection-scaling-design.md
"""

import App

from engine.appc.sensor_detection import can_detect

# ── AI candidate-selection gate ───────────────────────────────────────────────
# The SDK's SelectTarget.FindGoodTarget and StarbaseAttack.GetTargets both
# enumerate candidates via ObjectGroup.GetActiveObjectTupleInSet, which has no
# ship context. We stash the querying ship in a module global for the duration
# of each call (single-threaded Python -- safe) and have a wrapped
# GetActiveObjectTupleInSet consult it. Every other caller of that method
# (mission proximity checks, MissionLib's player scan, the player target list)
# runs with the global None and is unaffected; only SelectTarget.FindGoodTarget
# and StarbaseAttack.GetTargets publish an observer.
#
# ⚠️ THE TWO PUBLISHERS DO NOT BEHAVE THE SAME ABOUT CLOAK, and an earlier note
# here claimed they did. `SelectTarget.FindGoodTarget` carries its OWN absolute
# cloak skip downstream of this filter (sdk/Build/scripts/AI/Preprocessors.py:
# 1446), so no cloaked contact survives that path whatever this gate answers.
# `AI/PlainAI/StarbaseAttack.py::GetTargets` has NO such skip — it returns
# GetActiveObjectTupleInSet directly — so with ENHANCED_SENSOR_CONTEST on,
# STATIONS DO ACQUIRE CLOAKED SHIPS inside their bubble, from cold. Do not write
# "the AI cannot acquire a cloaked contact" anywhere; it is true of one path
# only. The bubble is CLOAK_DETECTION_BASE_GU plus CLOAK_RANGE_FACTOR of
# BaseSensorRange, and station hardpoints author large ones — fedstarbase
# 12000 GU and cardstarbase 5000, while the 18 of 52 hardpoint files that author
# no SetBaseSensorRange fall back to FALLBACK_RANGE_GU (30000), the largest
# bubble in the game. Multiply those by CLOAK_RANGE_FACTOR for the current
# figures; they are deliberately NOT restated here, because they move with every
# retune and the stale copies cost more to correct than the retune itself.
# Whether they are right is a TUNING question for the project owner and is
# deliberately NOT clamped here.
# Pinned by tests/unit/test_cloak_detection_contest.py's "AI ACQUISITION"
# section, which drives this filter directly.

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


def _best_detectable_candidate(select_target, ship):
    """Re-pick a target from the SENSOR-GATED enumeration, for the case where the
    SDK declined outright.

    Runs only inside `_gated_find`'s `observing(ship)` window, so
    `GetActiveObjectTupleInSet` is already filtered to what *ship* can detect —
    which, since stage 4, includes a cloaked contact inside its bubble. This is
    what the SDK's own loop throws away at
    sdk/Build/scripts/AI/Preprocessors.py:1444-1450 with an unconditional
    `if pCloakSystem.IsCloaked(): continue`.

    Scoring is the SDK's OWN `GetTargetRating`, and the dead/dying and
    skip-ourselves filters mirror its loop exactly. The ONLY rule that differs is
    cloak, which `can_detect` has already decided upstream. Do not add scoring or
    filtering of our own here — the point of the fallback shape is that the
    original selection logic stays the single source of ranking.

    Returns a NAME (as FindGoodTarget does), or None.
    """
    pSet = ship.GetContainingSet()
    group = getattr(select_target, "pTargetGroup", None)
    if pSet is None or group is None:
        return None

    own_id = ship.GetObjID()
    live = []
    for obj in group.GetActiveObjectTupleInSet(pSet):
        pDam = App.DamageableObject_Cast(obj)
        if pDam and (pDam.IsDead() or pDam.IsDying()):
            continue
        if obj.GetObjID() == own_id:
            continue
        live.append(obj)
    if not live:
        return None
    return max(live, key=select_target.GetTargetRating).GetName()


def _wrap_find_good_target(orig):
    """Wrap SelectTarget.FindGoodTarget (the candidate-enumeration method) so
    the querying ship is published as the current observer for the duration of
    the original call. FindGoodTarget calls ObjectGroup.GetActiveObjectTupleInSet,
    which the companion wrapper filters while an observer is published.

    ALSO supplies the acquisition half of the stage-4 cloak contest. The SDK path
    runs first and untouched, and its answer always wins — so uncloaked enemies
    keep their existing priority and ordinary engagements are unchanged. Only
    when it returns None do we re-pick (see `_best_detectable_candidate`), which
    is precisely the case its absolute cloak skip creates.

    ⚠️ NO ENHANCED_SENSOR_CONTEST CHECK BELONGS HERE, and its absence is load-
    bearing rather than an omission. With the flag off, `can_detect` rejects
    cloaked contacts at every range, so the gated enumeration hands the fallback
    nothing and stock BC's absolute behaviour returns on its own. Adding a flag
    check would give this module a detection rule of its own — exactly what the
    header disclaims. Pinned by tests/unit/test_ai_acquires_close_cloaked.py::
    test_contest_off_restores_absolute_cloak_with_no_flag_check_here.
    """

    def _gated_find(self):
        code_ai = getattr(self, "pCodeAI", None)
        ship = code_ai.GetShip() if code_ai is not None else None
        with observing(ship):
            name = orig(self)
            if name is not None or ship is None:
                return name
            return _best_detectable_candidate(self, ship)

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
