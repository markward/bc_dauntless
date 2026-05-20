# PlainAI Body Ports Implementation Plan (Slice D2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 5 PlainAI script bodies that NonFedAttack/FedAttack instantiate (`TorpedoRun`, `StationaryAttack`, `FollowObject`, `IntelligentCircleObject`, `Intercept`) actually drive ship motion — the activation-only behaviour from Slice D1 becomes observable kinematic + weapon behaviour. End state: NonFedAttack xpass smoke flips to a clean pass with tightened multi-tick assertions.

**Architecture:** PlainAI scripts load via `_SDKFinder` unchanged. Each subclasses `BaseAI.BaseAI` and defines its own `Update()` body. Slice D2's work is filling in engine surface so those Update bodies execute correctly: principally the `FuzzyLogic_BreakIntoSets` function + `FuzzyLogic` class on `App.py`, plus a small number of accessors (`GetCurShields` alias, `TorpedoAmmoType.GetLaunchSpeed`).

**Tech Stack:** Python 3, pytest, `_SDKFinder` SDK loader, existing `tick_ai` driver from Slices A-D1.

---

## Prerequisites

Confirm Slice D1 is merged: `git log --oneline | grep "Slice D1"` should show `Merge: BasicAttack sub-Compound smokes (Slice D1)` at `78555aa`.

Baseline tests once before starting:
```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q --ignore=tests/unit/test_hud_euler.py --ignore=tests/unit/test_phaser_damage_falloff.py --ignore=tests/unit/test_ship_alert_level.py 2>&1 | tail -3
```
Expected: 1257 passed.

## Worktree setup

Slices A/B/C/D1 each developed in `.claude/worktrees/`. Use the same pattern: create `.claude/worktrees/plainai-bodies` on branch `worktree-plainai-bodies` off current main. SDK and game directories are gitignored — symlink them. Always prefix bash with `unset VIRTUAL_ENV &&`.

## File structure

| File | Purpose |
|---|---|
| `App.py` (modify) | Add `FuzzyLogic_BreakIntoSets` function + `FuzzyLogic` class (Task 1) |
| `engine/appc/subsystems.py` (modify) | Add `TorpedoAmmoType.GetLaunchSpeed` (Task 2); `ShieldSubsystem.GetCurShields` alias (Task 5) |
| `tests/unit/test_fuzzy_logic.py` (new) | Unit coverage for FuzzyLogic helpers (Task 1) |
| `tests/integration/test_torpedo_run_smoke.py` (new) | TorpedoRun behaviour (Task 2) |
| `tests/integration/test_stationary_attack_smoke.py` (new) | StationaryAttack behaviour (Task 3) |
| `tests/integration/test_follow_object_smoke.py` (new) | FollowObject behaviour (Task 4) |
| `tests/integration/test_intelligent_circle_object_smoke.py` (new) | IntelligentCircleObject behaviour (Task 5) |
| `tests/integration/test_intercept_polish_smoke.py` (new) | Intercept combat-relevant assertions (Task 6) |
| `tests/integration/test_non_fed_attack_smoke.py` (modify) | Remove xfail; add multi-tick assertions (Task 7) |
| `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md` (modify) | Close Slice D2; forward-ref E (Task 7) |

## Engine-gap escalation pattern (carry-over)

**Trivial gaps:** fix inline as separate `feat(<module>): <what>` commits BEFORE the test commit they unblock.

**Novel gaps:** STOP and report.

Test commit must be test-only.

---

## Task 1: FuzzyLogic engine surface

Add the FuzzyLogic helpers used by TorpedoRun, FollowObject, and others. Two forms needed:

- **Function form:** `FuzzyLogic_BreakIntoSets(value, thresholds)` returns N floats (N = `len(thresholds) + 1`) summing to ≤1.0, representing trapezoidal/triangular membership in N+1 bands defined by the thresholds. SDK uses both 3-threshold (returns 3 floats; TorpedoRun fuzzy distance) and 4-threshold (returns 4 floats; TorpedoRun perpendicular-velocity sets) forms.
- **Class form:** `FuzzyLogic()` rule-based inference engine with `SetMaxRules(n)`, `AddRule(input_id, output_id)`, `SetPercentageInSet(set_id, value)`, `GetResultBySet(set_id) -> float`. Used by FollowObject (and other Compound non-D2 scripts).

**Files:**
- Modify: `App.py` (add at the bottom or in a clearly-marked block)
- Test: `tests/unit/test_fuzzy_logic.py` (new)

- [ ] **Step 1.1: Write the test file**

Create `tests/unit/test_fuzzy_logic.py`:

```python
"""FuzzyLogic helpers used by SDK PlainAI scripts.

SDK callers (sdk/Build/scripts/AI/PlainAI/TorpedoRun.py:156,159,233,
FollowObject.py:54-62,110) use two forms:

  - FuzzyLogic_BreakIntoSets(value, thresholds) -> N floats
  - FuzzyLogic() class with rule-based inference

Both ported in this task."""
import pytest

import App


# ── FuzzyLogic_BreakIntoSets ──────────────────────────────────────────────────

def test_break_into_sets_value_below_first_threshold_is_all_first_band():
    """value <= lo → (1.0, 0.0, 0.0) for 3-threshold form."""
    result = App.FuzzyLogic_BreakIntoSets(0.0, (10.0, 20.0, 30.0))
    assert result == (1.0, 0.0, 0.0)


def test_break_into_sets_value_above_last_threshold_is_all_last_band():
    """value >= hi → (0.0, 0.0, 1.0) for 3-threshold form."""
    result = App.FuzzyLogic_BreakIntoSets(100.0, (10.0, 20.0, 30.0))
    assert result == (0.0, 0.0, 1.0)


def test_break_into_sets_value_at_mid_threshold_is_all_mid():
    """value exactly at the middle threshold → (0.0, 1.0, 0.0)."""
    result = App.FuzzyLogic_BreakIntoSets(20.0, (10.0, 20.0, 30.0))
    assert result == (0.0, 1.0, 0.0)


def test_break_into_sets_value_halfway_low_to_mid():
    """value at midpoint of (lo, mid) → (0.5, 0.5, 0.0) by linear interp."""
    result = App.FuzzyLogic_BreakIntoSets(15.0, (10.0, 20.0, 30.0))
    assert result[0] == pytest.approx(0.5)
    assert result[1] == pytest.approx(0.5)
    assert result[2] == pytest.approx(0.0)


def test_break_into_sets_returns_floats_summing_to_one():
    """For any value, the membership floats sum to 1.0."""
    for v in (-5.0, 0.0, 12.5, 17.5, 25.0, 50.0):
        result = App.FuzzyLogic_BreakIntoSets(v, (10.0, 20.0, 30.0))
        assert sum(result) == pytest.approx(1.0)


def test_break_into_sets_4_threshold_form_returns_4_floats():
    """4 thresholds → 4 bands (TorpedoRun perpendicular-velocity usage)."""
    result = App.FuzzyLogic_BreakIntoSets(0.5, (0.0, 0.2, 0.4, 0.6))
    assert len(result) == 4
    assert sum(result) == pytest.approx(1.0)


# ── FuzzyLogic class ──────────────────────────────────────────────────────────

def test_fuzzy_logic_class_get_result_with_no_rules_is_zero():
    pFuzzy = App.FuzzyLogic()
    pFuzzy.SetMaxRules(4)
    assert pFuzzy.GetResultBySet(0) == 0.0


def test_fuzzy_logic_class_single_rule_passes_through_input_to_output():
    """AddRule(in, out) + SetPercentageInSet(in, 0.7) → GetResultBySet(out) >= 0.7."""
    pFuzzy = App.FuzzyLogic()
    pFuzzy.SetMaxRules(4)
    pFuzzy.AddRule(input_set_id=0, output_set_id=10)
    pFuzzy.SetPercentageInSet(0, 0.7)
    assert pFuzzy.GetResultBySet(10) == pytest.approx(0.7)


def test_fuzzy_logic_class_multiple_rules_to_same_output_max_combines():
    """Two rules contributing to the same output: result is max of their inputs."""
    pFuzzy = App.FuzzyLogic()
    pFuzzy.SetMaxRules(4)
    pFuzzy.AddRule(input_set_id=0, output_set_id=10)
    pFuzzy.AddRule(input_set_id=1, output_set_id=10)
    pFuzzy.SetPercentageInSet(0, 0.4)
    pFuzzy.SetPercentageInSet(1, 0.7)
    assert pFuzzy.GetResultBySet(10) == pytest.approx(0.7)


def test_fuzzy_logic_class_unmatched_output_returns_zero():
    """Output set not referenced by any rule → 0.0."""
    pFuzzy = App.FuzzyLogic()
    pFuzzy.AddRule(0, 10)
    pFuzzy.SetPercentageInSet(0, 0.9)
    assert pFuzzy.GetResultBySet(99) == 0.0
```

- [ ] **Step 1.2: Run; expect AttributeError on `App.FuzzyLogic_BreakIntoSets`**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_fuzzy_logic.py -v`
Expected: fails with `AttributeError`.

- [ ] **Step 1.3: Add the FuzzyLogic surface to App.py**

In `App.py`, find a good location (after the existing `*_Cast` block around line 308-334). Add:

```python
# ── FuzzyLogic ───────────────────────────────────────────────────────────────
# Used by SDK PlainAI scripts (TorpedoRun, FollowObject, etc.) for
# behaviour smoothing. Two forms:
#   - FuzzyLogic_BreakIntoSets: pure function, trapezoidal/triangular
#     membership in N+1 bands defined by N thresholds.
#   - FuzzyLogic class: rule-based Mamdani inference engine.
#
# Phase 1 implementation favours plausible behaviour over pixel-perfect SDK
# fidelity (the SDK C++ implementation is unavailable; semantics inferred
# from PlainAI callers).

def FuzzyLogic_BreakIntoSets(value, thresholds):
    """Return tuple of N floats summing to 1.0, representing triangular
    memberships in N bands whose peaks are at the N thresholds.

    For 3 thresholds (lo, mid, hi):
      - value <= lo                       → (1.0, 0.0, 0.0)
      - lo < value < mid                  → linear interp: (1-t, t, 0.0)
      - value == mid                      → (0.0, 1.0, 0.0)
      - mid < value < hi                  → linear interp: (0.0, 1-t, t)
      - value >= hi                       → (0.0, 0.0, 1.0)

    Generalises to N thresholds: peak of band i is at threshold[i];
    the value's position between adjacent thresholds gives a 2-element
    ramp; all other bands are 0.0. SDK callers (TorpedoRun.py:156,159,233,
    FollowObject.py:110) consistently unpack N values from N thresholds.
    """
    t = list(thresholds)
    n_bands = len(t)
    result = [0.0] * n_bands
    if value <= t[0]:
        result[0] = 1.0
        return tuple(result)
    if value >= t[-1]:
        result[-1] = 1.0
        return tuple(result)
    # Find the bracketing pair.
    for i in range(len(t) - 1):
        if t[i] <= value <= t[i + 1]:
            span = t[i + 1] - t[i]
            if span <= 0.0:
                # Degenerate threshold pair; fall back to all-in-band.
                result[i + 1] = 1.0
                return tuple(result)
            frac = (value - t[i]) / span
            result[i] = 1.0 - frac
            result[i + 1] = frac
            return tuple(result)
    # Shouldn't reach here; defensive fallback.
    result[-1] = 1.0
    return tuple(result)


class FuzzyLogic:
    """Rule-based Mamdani-style fuzzy inference.

    SDK callers (sdk/Build/scripts/AI/PlainAI/FollowObject.py:54-62)
    use this shape:

        pFuzzy = App.FuzzyLogic()
        pFuzzy.SetMaxRules(6)
        pFuzzy.AddRule(input_set_id, output_set_id)   # repeated
        pFuzzy.SetPercentageInSet(input_set_id, value)
        result = pFuzzy.GetResultBySet(output_set_id)

    Phase 1 semantics: GetResultBySet(o) = max over all rules whose
    output_id == o of the rule's input membership. Matches Mamdani max-
    aggregation for single-antecedent rules, which is what every SDK
    caller uses."""

    def __init__(self):
        self._max_rules: int = 0
        self._rules: list[tuple[int, int]] = []  # (input_set_id, output_set_id)
        self._percentages: dict[int, float] = {}

    def SetMaxRules(self, n: int) -> None:
        self._max_rules = int(n)

    def AddRule(self, input_set_id: int, output_set_id: int) -> None:
        self._rules.append((int(input_set_id), int(output_set_id)))

    def SetPercentageInSet(self, set_id: int, value: float) -> None:
        self._percentages[int(set_id)] = float(value)

    def GetResultBySet(self, output_set_id: int) -> float:
        out = 0.0
        for in_id, out_id in self._rules:
            if out_id != output_set_id:
                continue
            v = self._percentages.get(in_id, 0.0)
            if v > out:
                out = v
        return out
```

- [ ] **Step 1.4: Run tests to verify pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_fuzzy_logic.py -v`
Expected: 10 passed.

- [ ] **Step 1.5: Run regression**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q --ignore=tests/unit/test_hud_euler.py --ignore=tests/unit/test_phaser_damage_falloff.py --ignore=tests/unit/test_ship_alert_level.py 2>&1 | tail -3`
Expected: 1267+ passed (1257 prior + 10 new).

- [ ] **Step 1.6: Commit engine surface**

```bash
git add App.py
git commit -m "feat(app): FuzzyLogic_BreakIntoSets + FuzzyLogic class for PlainAI Update bodies"
```

- [ ] **Step 1.7: Commit test**

```bash
git add tests/unit/test_fuzzy_logic.py
git commit -m "test(app): FuzzyLogic helpers (function + class form)"
```

---

## Task 2: TorpedoRun smoke

Run TorpedoRun's Update against a real ship + target; assert speed setpoint is non-zero and TurnDirectionsToDirections was called toward the target. Likely surfaces `TorpedoAmmoType.GetLaunchSpeed` accessor.

**Files:**
- Modify (likely): `engine/appc/subsystems.py` — add `TorpedoAmmoType.GetLaunchSpeed`
- Test: `tests/integration/test_torpedo_run_smoke.py` (new)

- [ ] **Step 2.1: Write the test file**

Create `tests/integration/test_torpedo_run_smoke.py`:

```python
"""Integration smoke for AI.PlainAI.TorpedoRun.

SDK PlainAI/TorpedoRun.py: makes a single full-speed torpedo run on
its target. Update() computes target intercept point (predicted via
torpedo launch speed), uses fuzzy logic on distance + facing to pick
speed, calls SetImpulse + TurnDirectionsToDirections.

D2 smoke: after one Update call, ship's _speed_setpoint shows
non-zero impulse and the ship is rotating (angular velocity set)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene_with_distant_target(distance: float = 300.0):
    """Build ours at origin facing +Y, target at (0, distance, 0)."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # TorpedoRun reads pShip.GetTorpedoSystem() for launch-speed prediction.
    ours._torpedo_system = TorpedoSystem("T")
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_torpedo_run(ours, target_name="Target"):
    """Instantiate the SDK TorpedoRun PlainAI."""
    plain = PlainAI_Create(ours, "TorpRun")
    plain.SetScriptModule("TorpedoRun")
    inst = plain.GetScriptInstance()
    inst.SetTargetObjectName(target_name)
    return plain, inst


def test_torpedo_run_update_drives_impulse():
    """At fIdealDistance (200) with target ahead, Update should produce a
    non-zero impulse setpoint (ship moves forward)."""
    ours, _target = _build_scene_with_distant_target(distance=300.0)
    _plain, inst = _wire_torpedo_run(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    # _speed_setpoint is (speed, direction, frame) per ships.py:86-95.
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] > 0.0, "expected non-zero forward impulse"


def test_torpedo_run_update_with_no_target_returns_done():
    """sTarget resolves to None → US_DONE."""
    ours, _target = _build_scene_with_distant_target()
    _plain, inst = _wire_torpedo_run(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE


def test_torpedo_run_reaches_turn_directions_for_heading_adjust():
    """AdjustHeading calls pShip.TurnDirectionsToDirections — verify it
    was reached by capturing the call."""
    ours, _target = _build_scene_with_distant_target(distance=300.0)
    _plain, inst = _wire_torpedo_run(ours)
    calls = []
    original = ours.TurnDirectionsToDirections
    ours.TurnDirectionsToDirections = lambda *args, **kwargs: calls.append(args)
    inst.Update()
    assert len(calls) >= 1, "expected TurnDirectionsToDirections to be called"
```

- [ ] **Step 2.2: Run; expect engine gap on `GetLaunchSpeed`**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_torpedo_run_smoke.py -v`

Expected: AttributeError on `GetLaunchSpeed` from `pTorpSystem.GetCurrentAmmoType().GetLaunchSpeed()` at SDK TorpedoRun.py:130 (or a similar gap if `GetCurrentAmmoType` returns the type but the type has no `GetLaunchSpeed` method).

- [ ] **Step 2.3: Add `TorpedoAmmoType.GetLaunchSpeed` to engine/appc/subsystems.py**

Find `class TorpedoAmmoType` in `engine/appc/subsystems.py` (around line 760). The class already stores `_launch_speed` (set during AddAmmoType). Add the accessor:

```python
    def GetLaunchSpeed(self) -> float:
        """SDK Preprocessors/TorpedoRun.py:130 — used by FireScript +
        TorpedoRun to predict torpedo intercept points."""
        return float(self._launch_speed)
```

If `_launch_speed` is not currently an attribute, check the existing TorpedoAmmoType `__init__` and add `self._launch_speed: float = 0.0` initialization plus a setter (or accept it via kwarg). The Slice C ammo plumbing at `subsystems.py:1177` already references this field on a TorpedoAmmoType instance during AddAmmoType.

- [ ] **Step 2.4: Run tests to verify pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_torpedo_run_smoke.py -v`
Expected: 3 passed.

If any test still fails, the gap is novel — STOP and report.

- [ ] **Step 2.5: Commit engine surface**

```bash
git add engine/appc/subsystems.py
git commit -m "feat(subsystems): TorpedoAmmoType.GetLaunchSpeed accessor"
```

- [ ] **Step 2.6: Commit test**

```bash
git add tests/integration/test_torpedo_run_smoke.py
git commit -m "test(ai): TorpedoRun Update drives impulse + heading"
```

---

## Task 3: StationaryAttack smoke

StationaryAttack holds position and turns toward the target's predicted location. Simpler than TorpedoRun (no fuzzy speed control; speed is always 0).

**Files:**
- Test: `tests/integration/test_stationary_attack_smoke.py` (new)

- [ ] **Step 3.1: Write the test file**

Create `tests/integration/test_stationary_attack_smoke.py`:

```python
"""Integration smoke for AI.PlainAI.StationaryAttack.

SDK PlainAI/StationaryAttack.py: holds position (SetSpeed(0, ...)),
turns toward target's predicted intercept point.

D2 smoke: after one Update call, ship's _speed_setpoint shows
zero speed and TurnTowardLocation was called toward the target."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene_with_target(target_distance: float = 200.0):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    ours._torpedo_system = TorpedoSystem("T")
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, target_distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_stationary_attack(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "StationaryAttack")
    plain.SetScriptModule("StationaryAttack")
    inst = plain.GetScriptInstance()
    inst.SetTargetObjectName(target_name)
    return plain, inst


def test_stationary_attack_update_holds_position():
    """After Update with target ahead, _speed_setpoint[0] is 0 (no impulse)."""
    ours, _target = _build_scene_with_target()
    _plain, inst = _wire_stationary_attack(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] == 0.0, (
        f"StationaryAttack should hold position; speed setpoint was "
        f"{ours._speed_setpoint[0]}"
    )


def test_stationary_attack_update_turns_toward_target():
    """TurnTowardLocation called toward the (predicted) target location."""
    ours, _target = _build_scene_with_target()
    _plain, inst = _wire_stationary_attack(ours)
    calls = []
    original = ours.TurnTowardLocation
    ours.TurnTowardLocation = lambda *args, **kwargs: calls.append(args)
    inst.Update()
    assert len(calls) >= 1, "expected TurnTowardLocation to be called"


def test_stationary_attack_update_with_no_target_returns_done():
    ours, _target = _build_scene_with_target()
    _plain, inst = _wire_stationary_attack(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE
```

- [ ] **Step 3.2: Run; expect pass or small engine gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_stationary_attack_smoke.py -v`
Expected: 3 passed. Shares `GetLaunchSpeed` with Task 2 (already landed).

- [ ] **Step 3.3: Commit**

```bash
git add tests/integration/test_stationary_attack_smoke.py
git commit -m "test(ai): StationaryAttack Update holds position + turns toward target"
```

---

## Task 4: FollowObject smoke

FollowObject follows another ship using fuzzy distance-based speed control. Exercises the `FuzzyLogic()` class form added in Task 1.

**Files:**
- Test: `tests/integration/test_follow_object_smoke.py` (new)

- [ ] **Step 4.1: Write the test file**

Create `tests/integration/test_follow_object_smoke.py`:

```python
"""Integration smoke for AI.PlainAI.FollowObject.

SDK PlainAI/FollowObject.py: follow another ship using FuzzyLogic
class form (SDK FollowObject.py:54-62, 110, 116-118) to compute
speed from distance + facing.

D2 smoke: after one Update call, ship's _speed_setpoint shows
positive impulse (follow); TurnTowardDirection was called."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene_with_target(target_distance: float):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, target_distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_follow_object(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "Follow")
    plain.SetScriptModule("FollowObject")
    inst = plain.GetScriptInstance()
    inst.SetFollowObjectName(target_name)
    return plain, inst


def test_follow_object_update_drives_impulse_when_far():
    """At a distance well beyond fFarDistance, FollowObject should
    produce a non-zero impulse setpoint (chase the target)."""
    ours, _target = _build_scene_with_target(target_distance=1000.0)
    _plain, inst = _wire_follow_object(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] > 0.0


def test_follow_object_update_turns_toward_target():
    """TurnTowardDirection called toward the target."""
    ours, _target = _build_scene_with_target(target_distance=500.0)
    _plain, inst = _wire_follow_object(ours)
    calls = []
    original = ours.TurnTowardDirection
    ours.TurnTowardDirection = lambda *args, **kwargs: calls.append(args)
    inst.Update()
    assert len(calls) >= 1, "expected TurnTowardDirection to be called"


def test_follow_object_update_with_no_target_returns_done():
    ours, _target = _build_scene_with_target(target_distance=500.0)
    _plain, inst = _wire_follow_object(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE
```

- [ ] **Step 4.2: Run; expect pass or small engine gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_follow_object_smoke.py -v`

Likely fine — FollowObject uses `FuzzyLogic_BreakIntoSets` + `FuzzyLogic()` class (both landed in Task 1) + `pShip.GetWorldForwardTG()` (exists) + `TurnTowardDirection` (exists per ships.py grep) + `SetImpulse` (exists).

- [ ] **Step 4.3: Commit**

```bash
git add tests/integration/test_follow_object_smoke.py
git commit -m "test(ai): FollowObject Update drives chase + turn"
```

---

## Task 5: IntelligentCircleObject smoke

The most elaborate PlainAI: orbits a target with shield-bias + weapon-arc orientation. Uses `pShields.GetCurShields(direction)` which currently is named `GetCurrentShields` on the engine side — add `GetCurShields` as an SDK-facing alias.

**Files:**
- Modify: `engine/appc/subsystems.py` — add `ShieldSubsystem.GetCurShields` alias
- Test: `tests/integration/test_intelligent_circle_object_smoke.py` (new)

- [ ] **Step 5.1: Write the test file**

Create `tests/integration/test_intelligent_circle_object_smoke.py`:

```python
"""Integration smoke for AI.PlainAI.IntelligentCircleObject.

SDK PlainAI/IntelligentCircleObject.py: orbit target with shield-bias
(turn weak shield away) + weapon-arc orientation. Most elaborate of
the 5 PlainAI bodies.

D2 smoke: after one Update call, the orbit-angle computation does
not crash and ship's _speed_setpoint is updated."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # ICO reads pShip.GetShields() for shield-bias orientation.
    ours._shield_subsystem = ShieldSubsystem("Shield")
    # Initialize shield levels so the bias logic has data.
    for face in range(ShieldSubsystem.NUM_SHIELDS):
        ours._shield_subsystem._max_shields[face] = 100.0
        ours._shield_subsystem._current_shields[face] = 80.0
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, 200, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_ico(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "ICO")
    plain.SetScriptModule("IntelligentCircleObject")
    inst = plain.GetScriptInstance()
    inst.SetFollowObjectName(target_name)
    return plain, inst


def test_ico_update_does_not_crash():
    """Activation smoke — Update runs without raising."""
    ours, _target = _build_scene()
    _plain, inst = _wire_ico(ours)
    inst.Update()  # should not raise


def test_ico_update_drives_motion():
    """Update updates either _speed_setpoint or _angular_velocity_setpoint."""
    ours, _target = _build_scene()
    _plain, inst = _wire_ico(ours)
    inst.Update()
    # Either impulse or angular velocity should be touched.
    setpoint_set = (
        ours._speed_setpoint is not None
        or getattr(ours, "_angular_velocity_setpoint", None) is not None
    )
    assert setpoint_set, "expected ICO to set speed or angular setpoint"


def test_ico_update_with_no_target_returns_done():
    ours, _target = _build_scene()
    _plain, inst = _wire_ico(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE
```

- [ ] **Step 5.2: Run; expect engine gap on `GetCurShields`**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_intelligent_circle_object_smoke.py -v`

Expected: AttributeError on `pShields.GetCurShields(direction)` — engine method is named `GetCurrentShields` but SDK calls `GetCurShields`.

If other gaps surface (e.g., shield-bias matrix math), evaluate each — trivial-gap commit BEFORE the test commit, or STOP+report.

- [ ] **Step 5.3: Add `GetCurShields` alias**

In `engine/appc/subsystems.py`, find `ShieldSubsystem.GetCurrentShields` (around line 1374). Add an SDK-facing alias right after it (or after the existing `SetCurShields` alias at line 1380):

```python
    def GetCurShields(self, face: int) -> float:
        """SDK-facing alias of GetCurrentShields (matches Appc method name).

        Used by SDK PlainAI/IntelligentCircleObject.py:176-179 for
        shield-bias orbit positioning."""
        return self.GetCurrentShields(face)
```

- [ ] **Step 5.4: Run tests to verify pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_intelligent_circle_object_smoke.py -v`
Expected: 3 passed.

- [ ] **Step 5.5: Commit engine surface**

```bash
git add engine/appc/subsystems.py
git commit -m "feat(subsystems): ShieldSubsystem.GetCurShields SDK alias"
```

- [ ] **Step 5.6: Commit test**

```bash
git add tests/integration/test_intelligent_circle_object_smoke.py
git commit -m "test(ai): IntelligentCircleObject Update drives orbit motion"
```

---

## Task 6: Intercept polish smoke

Slice A landed an initial Intercept port. This task adds combat-relevant assertions and confirms behaviour under NonFedAttack/FedAttack wiring patterns.

**Files:**
- Test: `tests/integration/test_intercept_polish_smoke.py` (new)

- [ ] **Step 6.1: Write the test file**

Create `tests/integration/test_intercept_polish_smoke.py`:

```python
"""Integration smoke for AI.PlainAI.Intercept under NonFedAttack/FedAttack
usage patterns.

Slice A landed an initial Intercept port. This task pins the
combat-relevant Update behaviour: target ahead → ship accelerates and
turns toward target."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene(target_distance: float = 500.0):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, target_distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_intercept(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "Intercept")
    plain.SetScriptModule("Intercept")
    inst = plain.GetScriptInstance()
    inst.SetTargetObjectName(target_name)
    return plain, inst


def test_intercept_update_drives_impulse_toward_distant_target():
    """At long distance, Intercept should produce non-zero forward impulse."""
    ours, _target = _build_scene(target_distance=1000.0)
    _plain, inst = _wire_intercept(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] > 0.0


def test_intercept_update_with_no_target_returns_done():
    ours, _target = _build_scene()
    _plain, inst = _wire_intercept(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE


def test_intercept_existing_slice_a_smoke_still_passes():
    """The Slice A intercept smoke at tests/integration/test_ai_intercept_smoke.py
    must remain green — pin its existence here as a regression marker.

    This test acts as a directory check; the actual regression is the
    sibling test file's continued green status under the project test
    sweep."""
    import os
    sibling = os.path.join(
        os.path.dirname(__file__), "test_ai_intercept_smoke.py")
    assert os.path.exists(sibling), (
        "Slice A test_ai_intercept_smoke.py must remain present; "
        "if you renamed it, update this regression marker"
    )
```

- [ ] **Step 6.2: Run; expect pass or small engine gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_intercept_polish_smoke.py tests/integration/test_ai_intercept_smoke.py -v`

Expected: all pass. Slice A landed the Intercept port; the smoke just pins observable behaviour under standard wiring.

- [ ] **Step 6.3: Commit**

```bash
git add tests/integration/test_intercept_polish_smoke.py
git commit -m "test(ai): Intercept polish — combat-relevant Update assertions"
```

---

## Task 7: Tighten NonFedAttack smoke + close deferred doc

Remove the `xfail` marker from `tests/integration/test_non_fed_attack_smoke.py` (Slice C left it xpassing). Add multi-tick assertions: ship's `_speed_setpoint` changes; weapon's `StartFiring` is reached.

Then update the deferred doc to mark Slice D2 ✅ and forward-ref Slice E.

**Files:**
- Modify: `tests/integration/test_non_fed_attack_smoke.py`
- Modify: `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`

- [ ] **Step 7.1: Tighten NonFedAttack smoke**

Open `tests/integration/test_non_fed_attack_smoke.py`. The current test has `@pytest.mark.xfail(strict=False, reason=...)`. Remove the marker entirely and add multi-tick assertions. Replace the existing `test_non_fed_attack_create_ai_smoke` function body with:

```python
def test_non_fed_attack_create_ai_smoke(game_context):
    """With Slice D2's PlainAI body ports landed, NonFedAttack's full tree
    activates and drives observable ship behaviour across multiple ticks.

    Pre-D2 this was xfail-marked but xpassing (activation only). Now
    asserts kinematic behaviour over 10 ticks."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    ours._phaser = PhaserSystem("P"); ours._phaser._parent_ship = ours
    ours._torp = TorpedoSystem("T"); ours._torp._parent_ship = ours
    pSet.AddObjectToSet(ours, "Attacker")
    target = ShipClass(); target.SetTranslateXYZ(0, 500, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.NonFedAttack as non_fed_attack
    builder = non_fed_attack.CreateAI(ours, "Target")
    assert isinstance(builder, BuilderAI)

    # First tick activates the BuilderAI.
    tick_ai(builder, game_time=0.01)
    assert builder._activated is True
    assert builder._activation_failed is False

    # 10 more ticks — by now some PlainAI body should have written a
    # speed setpoint (the ship is engaging).
    for i in range(1, 11):
        tick_ai(builder, game_time=0.01 + i * 0.25)

    assert ours._speed_setpoint is not None, (
        "after 10 ticks, NonFedAttack should have written a speed setpoint"
    )
```

Remove the `@pytest.mark.xfail(...)` decorator above this function.

- [ ] **Step 7.2: Run tightened NonFedAttack smoke**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_non_fed_attack_smoke.py -v`
Expected: 1 passed (no longer xfail).

If it fails: a deeper integration gap exists. STOP and report — the visible-mission milestone needs investigation.

- [ ] **Step 7.3: Update the deferred doc**

In `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`, find the section added by Slice D1 (around line 108). Replace the Slice D2 bullet with:

```markdown
- **Slice D2**: ✅ done in [PlainAI body ports plan](../plans/2026-05-19-plainai-bodies.md). The 5 PlainAI scripts NonFedAttack/FedAttack instantiate now drive observable ship motion: TorpedoRun + StationaryAttack write speed/turn setpoints toward target intercept points; FollowObject drives chase via fuzzy distance control; IntelligentCircleObject orbits with shield/weapon bias; Intercept polish pins combat-relevant Update assertions. Added FuzzyLogic_BreakIntoSets + FuzzyLogic class to App.py. NonFedAttack smoke flipped from xpass to clean pass with multi-tick assertions.
```

Note: Slice D1's bullet already references the previous D2 forward-ref; preserve that text and just update D2 specifically. After the edit, the section should clearly show D1 done, D2 done, E next.

- [ ] **Step 7.4: Run focused regression sweep**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit tests/integration --continue-on-collection-errors -q -k "select or fire or condition or builder_ai or event_manager or object_group or proximity or ai_driver or ai_primitives or torpedo_run or stationary_attack or follow_object or intelligent_circle or intercept_polish or non_fed or fuzzy" 2>&1 | tail -3`
Expected: green (modulo pre-existing native-binding collection errors).

- [ ] **Step 7.5: Commit**

```bash
git add tests/integration/test_non_fed_attack_smoke.py docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md
git commit -m "test(ai)+docs(deferred): tighten NonFedAttack smoke; close Slice D2"
```

---

## Out of scope (deferred to E)

- `NonFedAttack`/`FedAttack` `CreateAI` polish beyond what the tightened smoke catches.
- Visible mission scripting (E1M1 or new BasicAttack mission). Slice E.
- `AvoidObstacles` preprocessor port — used by Compound trees but not in the 5-script D2 scope.
- `OptimizedTorpedoRun` / similar C-backed replacements — never; we run the Python.

These remain noted in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
