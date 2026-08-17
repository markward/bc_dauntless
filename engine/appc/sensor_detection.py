"""Sensor-damage detection scaling + nebula tactical concealment.

A ship detects targets out to a range that scales linearly with its
sensor subsystem's condition, and detects nothing once the sensor is
offline (disabled at <= DisabledPercentage, or destroyed). Dense nebulae
further reduce effective range (CONCEAL_K) and break detection outright
above LOCK_BREAK_T, with per-pair hysteresis. Used by both the player
target list and the AI candidate-selection gate.

See docs/superpowers/specs/2026-06-10-sensor-damage-detection-scaling-design.md
"""

import weakref

import App
from engine.appc.subsystems import _is_offline, _get_xyz
from engine.appc import nebula_density as _nd
from engine.core.ids import implements

# Range used when a ship models no sensor subsystem or carries no
# BaseSensorRange hardpoint data. Preserves the player target list's
# historical 30000 GU reach and keeps sensor-less fixtures fully sighted.
FALLBACK_RANGE_GU = 30000.0

# ── Concealment constants ─────────────────────────────────────────────────────
CONCEAL_K = 0.9      # effective-range reduction at full density (0→no effect, 1→blind)
LOCK_BREAK_T = 0.28  # density above which detection fails outright. Matched to the
                     # field dials (gain 1.2 / floor 0.5 → peak density ≈ 0.5-0.66),
                     # so only the densest clump cores fully hide a ship.
HYSTERESIS = 0.08    # target must drop to T-HYSTERESIS (0.20) before re-detection

# ── The stage-4 sensing toggle (INTENTIONAL divergence from stock BC) ─────────
# ONE flag covering BOTH stage-4 sensing changes as a set. It does NOT mean
# "cloak"; it means "sensing is a contest of degrees rather than a set of
# absolutes". Turning it off restores how the game behaved before stage 4.
#
#   (1) CLOAK IS A RANGE CONTEST, not an absolute. In BC a cloaked ship is
#       undetectable at any range. Here cloak bubble = CLOAK_DETECTION_BASE_GU
#       (a flat 10 GU) plus CLOAK_RANGE_FACTOR (1%) of the observer's
#       *effective* sensor range, so a Galaxy's 2000 GU sensors reach 30 GU
#       against a cloaked contact — half its 60 GU phaser range, i.e. you must
#       be effectively on top of it. Because the percentage term scales
#       *effective* range (post condition and power), boosting sensor power
#       widens the bubble; wrecked sensors still remove it entirely (the flat
#       base never applies past the `r <= 0.0` guard below). The flat base was
#       added because a pure 1% bubble (20 GU on a Galaxy) played too small;
#       do not "improve" either number without a play-tested reason.
#
#   (2) NEBULA CONCEALMENT REACHES THE UI. perception.perceived_by (target list,
#       radar) routes through can_detect, so nebula-hidden contacts leave the
#       list instead of staying selectable-but-unshootable.
#
# Both are symmetric across the game: can_detect is also the AI
# candidate-selection gate and the FireScript firing gate, so AI ships gain the
# same capabilities and a cloaked attack run becomes detectable close in. That
# includes ACQUISITION, not just continued fire — StarbaseAttack.GetTargets
# reaches the candidate filter with no cloak skip of its own, so a station
# picks up a cloaked ship inside its (large) bubble. See the ⚠️ note above
# _observing_ship for the paths and the numbers.
#
# ⚠️ KNOWN WART IN THE OFF STATE — this is deliberate, do not "fix" it.
# With the flag False the UI ignores nebulae but can_detect keeps applying
# concealment unconditionally for weapons and AI (it always did, since long
# before stage 4). So the two surfaces disagree again: you can select a
# nebula-hidden target you cannot fire on. That inconsistency IS the
# pre-stage-4 behaviour, and restoring prior behaviour — warts included — is
# what an off switch is for. Making the off state internally consistent would
# mean disabling nebula concealment for weapons too, which is NOT prior
# behaviour and would be a third, unasked-for game. Pinned by
# tests/unit/test_nebula_hides_contacts_from_ui.py::
# test_weapons_still_apply_nebula_concealment_with_the_toggle_off.
#
# Deliberately code-only: there is no UI toggle. It exists so the changes can be
# exposed to users later if that is ever wanted.
ENHANCED_SENSOR_CONTEST = True
CLOAK_RANGE_FACTOR = 0.01
CLOAK_DETECTION_BASE_GU = 10.0  # flat bubble floor, added atop the CLOAK_RANGE_FACTOR
                                 # percentage; does NOT scale with sensor condition, so
                                 # damage compresses the bubble toward 10 GU rather than
                                 # toward zero (fully offline sensors still return False
                                 # via the `r <= 0.0` guard, ahead of this term).

# Per-(observer, target) latch: a broken lock needs a margin to re-acquire.
#
# WEAK ON BOTH SIDES, DELIBERATELY — do not "simplify" this back to a set of
# `(id(observer), id(target))` tuples. Raw ids do not keep their objects alive,
# so a dead pair's entry can be inherited by an unrelated new object that
# CPython allocates at the same address, silently granting it the easier
# `LOCK_BREAK_T - HYSTERESIS` re-acquisition threshold.
#
# HARDENING, NOT A LIVE-BUG FIX — be honest about which this is. A real
# `ShipClass` cannot hit that today, because every `TGObject` is strongly
# pinned for the process lifetime by `engine/core/ids.py`'s `_registry`
# (`unregister` has exactly one caller, `TGSequence`), so a ship's `id()` is
# never recycled while the game runs. The recycle is reachable for plain
# non-TGObject observers/targets — which is what the test fixtures are, and
# what tests/unit/test_concealment_latch_lifetime.py::
# test_a_recycled_id_cannot_inherit_a_stale_latch demonstrates. The weak keying
# also stops the latch depending on that registry pin for its correctness, and
# stops it from pinning dead ships itself the way a strong-keyed dict would.
_broken: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _latched(observer, target) -> bool:
    """True iff this pair's lock is currently broken."""
    try:
        targets = _broken.get(observer)
    except TypeError:
        # Not weak-referenceable (no engine object is like this today; guard so
        # an exotic caller degrades to "no hysteresis", never to a crash).
        return False
    return targets is not None and target in targets


def _set_latched(observer, target, broken: bool) -> None:
    """Record (or clear) this pair's broken-lock latch."""
    try:
        targets = _broken.get(observer)
        if broken:
            if targets is None:
                targets = weakref.WeakSet()
                _broken[observer] = targets
            targets.add(target)
        elif targets is not None:
            targets.discard(target)
    except TypeError:
        pass


def reset_concealment_state():
    """Clear per-(observer,target) lock-break latches.

    Called on mission swap (host_loop) so a new mission's ships don't inherit
    stale latches, and from tests/conftest.py's autouse
    `_reset_leakable_engine_globals` so one test's broken lock cannot leak into
    the next. Both, not either: the weak keying above stops a DEAD ship's entry
    being inherited, but a test that keeps its ships alive still needs the
    explicit clear."""
    _broken.clear()


def _cloak_subsystem(target):
    """The target's cloaking subsystem, or None if it has none.

    Resolves ``GetCloakingSubsystem`` via the target's *class*, not the
    instance: ``TGObject.__getattr__`` vends a truthy ``_Stub`` for any method
    a class doesn't define, so a plain ``target.GetCloakingSubsystem()`` on a
    non-ship (planet, station) returns a stub whose ``.IsCloaked()`` is also
    truthy — which would wrongly treat every planet as cloaked and hide it from
    the sensors. Only ShipClass defines the real method; everything else has no
    cloak.
    """
    getter = getattr(type(target), "GetCloakingSubsystem", None)
    if getter is None:
        return None
    try:
        cloak = getter(target)
    except Exception:
        return None
    return cloak if cloak is not None else None


def _game_time() -> float:
    """Current game time for drift_t sampling; falls back to 0.0 in tests."""
    try:
        return float(App.g_kTimerManager.GetGameTime())
    except Exception:
        return 0.0


def effective_sensor_range(ship) -> float:
    """Detection range (game units) for *ship* given its sensor condition.

    Full BaseSensorRange when undamaged, scaled linearly by condition
    percentage, and 0.0 once the sensor subsystem is offline (disabled or
    destroyed). Returns FALLBACK_RANGE_GU for ships that don't model a
    sensor subsystem or carry no BaseSensorRange.

    The capability probe is ``ids.implements``, NOT ``hasattr``:
    ``TGObject.__getattr__`` vends a truthy ``_Stub`` for any undefined method,
    so ``hasattr`` is vacuously True for every engine object and a non-ship
    used to get a ``_Stub`` back — which ``_is_offline`` then read as offline,
    silently answering 0.0 ("blind") instead of the documented fallback.
    """
    sensors = (ship.GetSensorSubsystem()
               if (ship is not None and implements(ship, "GetSensorSubsystem"))
               else None)
    if sensors is None:
        return FALLBACK_RANGE_GU
    if _is_offline(sensors):
        return 0.0
    base = sensors.GetBaseSensorRange()
    if base <= 0.0:
        return FALLBACK_RANGE_GU
    return base * sensors.GetConditionPercentage() * sensors.GetNormalPowerPercentage()


def concealment_at(ship) -> float:
    """Max nebula density [0, 1] at *ship*'s position across the ship's set.

    Returns 0.0 if the ship is in no set or no nebulae are present. Sampled
    on demand using the current game time as drift_t so the CPU field matches
    the animated GPU field without needing host-loop reordering.

    Concealment is toggle-independent: it reads the density field regardless
    of any VFX or display setting.
    """
    # `implements`, not `hasattr` — see effective_sensor_range. (Both probes
    # answer the same today: ObjectClass, ShipClass and MetaNebula all really
    # define these two, and the plain-class test fakes define them too. The
    # switch removes the vacuous-True hazard rather than changing an answer.)
    pSet = ship.GetContainingSet() if implements(ship, "GetContainingSet") else None
    if pSet is None:
        return 0.0
    loc = ship.GetWorldLocation() if implements(ship, "GetWorldLocation") else None
    if loc is None:
        return 0.0
    t = _game_time()
    best = 0.0
    from engine.appc import contact_index
    for obj in contact_index.nebulae_in(pSet):
        neb = App.MetaNebula_Cast(obj)
        if neb is None:
            continue
        spheres = neb.GetNebulaSpheres()
        freq, gain, floor = neb.GetFbmDials()
        d = _nd.density(loc.x, loc.y, loc.z, spheres, neb.GetSeed(),
                        freq, gain, floor, drift_t=t * 0.01)
        if d > best:
            best = d
    return best


def is_hidden_by_cloak(target) -> bool:
    """True iff *target*'s cloaking subsystem currently reports IsCloaked().

    ⚠️ NOT A DETECTABILITY GATE, and its name is now a near-miss for what it's
    used for — read the whole docstring before reaching for it. Detectability
    is ONE rule, ``can_detect``, everywhere, and that rule is a range *contest*
    (ENHANCED_SENSOR_CONTEST / CLOAK_RANGE_FACTOR / CLOAK_DETECTION_BASE_GU
    above): a cloaked ship stays perceivable inside a flat 10 GU plus 1% of
    effective sensor range. So a True return from this function does NOT mean
    "invisible to everyone" or "absent from the target list" — a cloaked
    contact well inside its bubble is routinely BOTH perceivable and
    ``is_hidden_by_cloak`` at once. Do NOT reintroduce it as a detectability
    gate — reaching for it is how the UI drifted away from the weapons before
    stage 4, and it also bypasses the nebula concealment and the per-pair
    hysteresis latch that ``can_detect`` owns.

    Its production caller is ``engine.appc.perception.perceived_by``, which
    uses it for a narrower question than detectability: whether a contact that
    already cleared ``can_detect`` should read as a fuzzy sensor return —
    targetable at ship level but not by subsystem
    (``Contact.subsystems_targetable``). A cloaked ship gives you a rough
    contact, not a detailed scan of its subsystems, independent of how close
    that contact is. It also keeps its narrower, longer-standing test coverage
    as an "is this ship fully cloaked?" predicate
    (tests/unit/test_cloak_target_visibility.py).

    Gate on IsCloaked() (fully hidden), not IsTryingToCloak() — a mid-cloak ship
    stays visible until the fade completes. That much still matches
    ``can_detect`` and the SDK SelectTarget.FindGoodTarget."""
    cloak = _cloak_subsystem(target)
    return cloak is not None and bool(cloak.IsCloaked())


def can_detect(observer, target, *, dist_sq_gu=None,
               apply_concealment=True) -> bool:
    """True iff *observer* can detect *target* within its effective sensor
    range, accounting for nebula tactical concealment.

    Detection fails outright when the target's concealment exceeds
    LOCK_BREAK_T. A broken lock latches (per-pair hysteresis) until
    concealment drops to LOCK_BREAK_T - HYSTERESIS. When below the
    threshold, effective range is reduced by (1 - CONCEAL_K * concealment).

    BOTH optional parameters are KEYWORD-ONLY, deliberately. ``bool`` is a
    subclass of ``int``, so the natural misreading ``can_detect(a, b, False)``
    would bind ``dist_sq_gu=False`` — and ``False <= r * r`` is True for any
    positive range, a silent always-detect that no assertion would catch. The
    bare ``*`` makes that a TypeError at the call site
    (tests/unit/test_sensor_detection.py::
    test_can_detect_refuses_positional_optional_arguments). Do not remove it
    for brevity.

    *apply_concealment* False skips the nebula gate entirely — no density
    sample, no latch mutation, no range scaling — leaving range + cloak +
    distance. It exists for ONE caller: ``perception.perceived_by`` passes
    ``ENHANCED_SENSOR_CONTEST`` through it, so that with the stage-4 toggle off
    the target list and radar get the pre-stage-4 rule back. Weapons and AI pass
    nothing and keep concealment unconditionally, which is what they did before
    stage 4 — see the ⚠️ wart note on ENHANCED_SENSOR_CONTEST above for why the
    off state is deliberately asymmetric. Do NOT reach for this to "skip the
    expensive bit": the sample is the rule.

    *dist_sq_gu* is the SQUARED observer→target centre distance in game units.
    Pass it only when the caller has already derived that exact number for its
    own reasons; when None (every caller but one) it is computed here, so the
    default behaviour is unchanged. The one caller that supplies it is
    ``engine.appc.perception.perceived_by``, which computes it for the Contact
    record it builds — recomputing it here would restore a duplicate derivation
    one stage after five of them were consolidated. A wrong value silently
    produces a wrong detection answer, so do NOT pass an approximation, a
    cached value from a previous frame, or a surface distance.
    """
    # ── Cloak gate ────────────────────────────────────────────────────────
    # Stock BC: a fully cloaked target is undetectable — the SDK SelectTarget
    # drops a contact on ET_CLOAK_COMPLETED. Here (ENHANCED_SENSOR_CONTEST)
    # cloak instead shrinks effective range to CLOAK_DETECTION_BASE_GU (a flat
    # 10 GU floor) plus CLOAK_RANGE_FACTOR of it, applied after
    # effective_sensor_range so the percentage term scales with condition and
    # power while the flat term does not. Mid-cloak (CLOAKING) stays fully
    # visible until the transition finishes, so gate on IsCloaked(), not
    # IsTryingToCloak().
    cloak = _cloak_subsystem(target)
    cloaked = cloak is not None and bool(cloak.IsCloaked())
    if cloaked and not ENHANCED_SENSOR_CONTEST:
        return False

    r = effective_sensor_range(observer)
    if r <= 0.0:
        return False
    if cloaked:
        r = CLOAK_DETECTION_BASE_GU + r * CLOAK_RANGE_FACTOR

    # ── Nebula concealment gate ───────────────────────────────────────────
    if apply_concealment:
        conceal = concealment_at(target)
        thresh = LOCK_BREAK_T - (HYSTERESIS if _latched(observer, target)
                                 else 0.0)
        if conceal >= thresh:
            _set_latched(observer, target, True)
            return False
        _set_latched(observer, target, False)
        # Scale range by the concealment factor (no-op when conceal == 0).
        r = r * (1.0 - CONCEAL_K * conceal)

    if dist_sq_gu is None:
        ox, oy, oz = _get_xyz(observer)
        tx, ty, tz = _get_xyz(target)
        dx, dy, dz = tx - ox, ty - oy, tz - oz
        dist_sq_gu = dx * dx + dy * dy + dz * dz
    return dist_sq_gu <= (r * r)


def clear_undetectable_player_lock(player) -> None:
    """Drop *player*'s weapon lock once its target stops being detectable.

    AI ships re-select through SelectTarget, which drops a contact its sensors
    can no longer see. The player has no such preprocessor, so without this the
    lock outlives the contact: the target list empties (its gate consults the
    sensors) while the reticle stays welded to a ship you can neither see nor
    fire on. Live-reported at 0% sensor power, 2026-08-06.

    Gates on ``can_detect`` — the same predicate the firing chokepoint uses
    (host_loop.py:907) — so lock and fire agree by construction. It subsumes
    the cloak-only ``is_hidden_by_cloak`` check this replaced (cloak is its
    first gate) and additionally covers dead/unpowered sensors, effective
    range, and nebula concealment. Sensors at 0% power land here via
    ``effective_sensor_range``'s GetNormalPowerPercentage() factor, which
    collapses range to 0.0 whether or not the subsystem reports _is_offline.

    Clearing the target also silences the weapons: FireWeapons no-ops with no
    target.
    """
    if player is None:
        return
    target = player.GetTarget()
    if target is None:
        return
    if not can_detect(player, target):
        player.SetTarget(None)


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
# BaseSensorRange, and station hardpoints author large ones (fedstarbase
# 12000 GU -> 130 GU, cardstarbase 5000 -> 60, and the 18 of 52 hardpoint files
# that author no SetBaseSensorRange fall back to FALLBACK_RANGE_GU -> 310 GU).
# Whether those numbers are right is a TUNING question for the project owner
# and is deliberately NOT clamped here.
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
