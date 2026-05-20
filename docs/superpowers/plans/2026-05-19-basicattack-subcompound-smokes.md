# BasicAttack Sub-Compound Smokes Implementation Plan (Slice D1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-sub-Compound activation smoke tests for the 6 sub-Compounds NonFedAttack/FedAttack splice in, so regressions bisect to a specific sub-Compound instead of just the parent. PlainAI body behaviour is explicitly deferred to D2.

**Architecture:** Six integration test files under `tests/integration/`, one per sub-Compound. Each test builds a minimal ship via the Slice B/C fixture pattern, calls the sub-Compound's `CreateAI(...)`, asserts the returned AI's immediate-child structure, and runs one or two `tick_ai` calls. Engine gaps surface as separate `feat(<module>): <what>` commits before each test commit, matching the Slice C bisect-friendly pattern. The only anticipated engine gap is `RandomAI` (sibling of existing `PriorityListAI`/`SequenceAI`).

**Tech Stack:** Python 3, pytest, `_SDKFinder` SDK loader, existing `tick_ai` driver from Slices A-C.

---

## Prerequisites

Confirm Slice C is merged: `git log --oneline | grep "BasicAttack Slice C"` should show `Merge: FireScript preprocessor (BasicAttack Slice C)` at `db1c608`.

Baseline tests once before starting:
```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q --ignore=tests/unit/test_hud_euler.py --ignore=tests/unit/test_phaser_damage_falloff.py --ignore=tests/unit/test_ship_alert_level.py 2>&1 | tail -3
```
Expected: 1257 passed.

## Worktree setup

Slice A/B/C each developed in isolated worktrees under `.claude/worktrees/`. Use the same pattern: create `.claude/worktrees/subcompound-smokes` on branch `worktree-subcompound-smokes` off current main. SDK and game directories are gitignored — symlink them from the main repo. Always prefix bash with `unset VIRTUAL_ENV &&`.

## File structure

| File | Purpose |
|---|---|
| `tests/integration/test_evade_torps_smoke.py` (new) | EvadeTorps activation smoke |
| `tests/integration/test_warp_before_death_smoke.py` (new) | WarpBeforeDeath activation smoke |
| `tests/integration/test_sweep_phasers_smoke.py` (new) | SweepPhasers activation smoke |
| `tests/integration/test_no_sensors_evasive_smoke.py` (new) | NoSensorsEvasive activation smoke (depends on new `RandomAI`) |
| `tests/integration/test_ico_move_smoke.py` (new) | ICOMove activation smoke (most elaborate Part) |
| `tests/integration/test_follow_through_warp_smoke.py` (new) | FollowThroughWarp activation smoke (full Compound) |
| `engine/appc/ai.py` (modify) | Add `RandomAI` class + `RandomAI_Create` factory (Task 4 prerequisite) |
| `App.py` (modify) | Re-export `RandomAI` + `RandomAI_Create` (Task 4 prerequisite) |
| `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md` (modify) | Close Slice D1; forward-ref D2/E (Task 7) |

## Engine-gap escalation pattern (carry-over from Slices B/C)

**Trivial single-line stubs:** fix inline as a separate `feat(<module>): <what>` commit BEFORE the test commit.

**Novel gaps:** STOP and report.

The test commit must be test-only.

---

## Task 1: EvadeTorps activation smoke

`EvadeTorps.CreateAI(pShip, sTorpSource=None, dKeywords={})` returns a `ConditionalAI` named "IncomingTorps" wrapping a `PlainAI` named "EvadeTorps". With the default flag `AvoidTorps` unset, the `EvalFunc` returns `US_DONE`.

**Files:**
- Test: `tests/integration/test_evade_torps_smoke.py` (new)

- [ ] **Step 1.1: Write the test file**

Create `tests/integration/test_evade_torps_smoke.py`:

```python
"""Activation smoke for AI.Compound.Parts.EvadeTorps.

SDK Parts/EvadeTorps.py: CreateAI(pShip, sTorpSource=None, dKeywords={})
returns a ConditionalAI named "IncomingTorps" wrapping a PlainAI named
"EvadeTorps". Default flags → EvalFunc returns US_DONE.

This is an activation smoke per Slice D1 spec — we don't exercise the
PlainAI Update body (D2 scope)."""
import pytest

import App
from engine.appc.ai import ConditionalAI, PlainAI
from engine.appc.ai_driver import tick_ai
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


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    return ours


def test_evade_torps_create_ai_returns_conditional_ai_wrapping_plain_ai():
    ours = _build_scene()
    import AI.Compound.Parts.EvadeTorps as evade_torps
    ai = evade_torps.CreateAI(ours)
    assert isinstance(ai, ConditionalAI), f"expected ConditionalAI, got {type(ai).__name__}"
    assert ai.GetName() == "IncomingTorps"
    contained = ai._contained_ai
    assert isinstance(contained, PlainAI), f"expected PlainAI contained, got {type(contained).__name__}"
    assert contained.GetName() == "EvadeTorps"


def test_evade_torps_tick_does_not_crash():
    ours = _build_scene()
    import AI.Compound.Parts.EvadeTorps as evade_torps
    ai = evade_torps.CreateAI(ours)
    # Default: AvoidTorps flag unset → EvalFunc returns DONE → no crash.
    tick_ai(ai, game_time=0.01)
```

- [ ] **Step 1.2: Run; expect pass or small engine gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_evade_torps_smoke.py -v`

Expected: 2 passed. If a gap surfaces (e.g., a missing `_AIScriptInstance` setter that the SDK init reaches), land it as a separate `feat(<module>): <what>` commit BEFORE the test commit.

- [ ] **Step 1.3: Commit**

```bash
git add tests/integration/test_evade_torps_smoke.py
git commit -m "test(ai): EvadeTorps sub-Compound activation smoke"
```

---

## Task 2: WarpBeforeDeath activation smoke

`WarpBeforeDeath.CreateAI(pShip, dKeywords, fFraction=0.1)` returns a `ConditionalAI` named "WarpOutBeforeDeath" wrapping a `PlainAI` named "WarpOut" (script module: "Warp"). Default flag `WarpOutBeforeDying` unset → `EvalFunc` returns `US_DONE`. Note this `CreateAI` takes `dKeywords` as a positional, not a keyword.

**Files:**
- Test: `tests/integration/test_warp_before_death_smoke.py` (new)

- [ ] **Step 2.1: Write the test file**

Create `tests/integration/test_warp_before_death_smoke.py`:

```python
"""Activation smoke for AI.Compound.Parts.WarpBeforeDeath.

SDK Parts/WarpBeforeDeath.py: CreateAI(pShip, dKeywords, fFraction=0.1)
returns a ConditionalAI named "WarpOutBeforeDeath" wrapping a PlainAI
named "WarpOut" (script module: "Warp"). Default flags → US_DONE."""
import pytest

import App
from engine.appc.ai import ConditionalAI, PlainAI
from engine.appc.ai_driver import tick_ai
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


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    return ours


def test_warp_before_death_create_ai_returns_conditional_ai_wrapping_warp_plain_ai():
    ours = _build_scene()
    import AI.Compound.Parts.WarpBeforeDeath as wbd
    ai = wbd.CreateAI(ours, {})
    assert isinstance(ai, ConditionalAI)
    assert ai.GetName() == "WarpOutBeforeDeath"
    contained = ai._contained_ai
    assert isinstance(contained, PlainAI)
    assert contained.GetName() == "WarpOut"


def test_warp_before_death_tick_does_not_crash():
    ours = _build_scene()
    import AI.Compound.Parts.WarpBeforeDeath as wbd
    ai = wbd.CreateAI(ours, {})
    tick_ai(ai, game_time=0.01)
```

- [ ] **Step 2.2: Run; expect pass or small engine gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_warp_before_death_smoke.py -v`
Expected: 2 passed.

- [ ] **Step 2.3: Commit**

```bash
git add tests/integration/test_warp_before_death_smoke.py
git commit -m "test(ai): WarpBeforeDeath sub-Compound activation smoke"
```

---

## Task 3: SweepPhasers activation smoke

`SweepPhasers.CreateAI(pShip, sTarget, fSpeed, dKeywords)` returns a `PriorityListAI` named "PriorityList" with 2 children: a `ConditionalAI` named "UseSideArcs" (priority 1) and a `PlainAI` named "PhaserSweep" (priority 2). The PlainAIs have `SetScriptInstance` setters called on them (`SetTargetObjectName`, `SetSweepPhasersDuringRun`, `SetSpeedFraction`, `SetPrimaryDirection`) which degrade to the `_AIScriptInstance` data-bag.

**Files:**
- Test: `tests/integration/test_sweep_phasers_smoke.py` (new)

- [ ] **Step 3.1: Write the test file**

Create `tests/integration/test_sweep_phasers_smoke.py`:

```python
"""Activation smoke for AI.Compound.Parts.SweepPhasers.

SDK Parts/SweepPhasers.py: CreateAI(pShip, sTarget, fSpeed, dKeywords)
returns a PriorityListAI named "PriorityList" with 2 children:
ConditionalAI("UseSideArcs", priority 1) and PlainAI("PhaserSweep",
priority 2)."""
import pytest

import App
from engine.appc.ai import PriorityListAI, ConditionalAI, PlainAI
from engine.appc.ai_driver import tick_ai
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


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); pSet.AddObjectToSet(target, "Target")
    return ours, target


def test_sweep_phasers_create_ai_returns_priority_list_with_two_children():
    ours, _target = _build_scene()
    import AI.Compound.Parts.SweepPhasers as sweep
    ai = sweep.CreateAI(ours, "Target", 0.75, {})
    assert isinstance(ai, PriorityListAI)
    assert ai.GetName() == "PriorityList"
    # _ais is a list of (priority, ai) tuples for PriorityListAI.
    assert len(ai._ais) == 2
    names = [child.GetName() for _prio, child in ai._ais]
    assert "UseSideArcs" in names
    assert "PhaserSweep" in names


def test_sweep_phasers_tick_does_not_crash():
    ours, _target = _build_scene()
    import AI.Compound.Parts.SweepPhasers as sweep
    ai = sweep.CreateAI(ours, "Target", 0.75, {})
    tick_ai(ai, game_time=0.01)
```

- [ ] **Step 3.2: Run; expect pass or small engine gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_sweep_phasers_smoke.py -v`
Expected: 2 passed.

- [ ] **Step 3.3: Commit**

```bash
git add tests/integration/test_sweep_phasers_smoke.py
git commit -m "test(ai): SweepPhasers sub-Compound activation smoke"
```

---

## Task 4: NoSensorsEvasive activation smoke (with RandomAI port)

`NoSensorsEvasive.CreateAI(pShip)` returns a `ConditionalAI` named "SensorsDisabled" wrapping a `SequenceAI` named "LoopForever" wrapping a `RandomAI` named "Random" with 4 PlainAI(`ManeuverLoop`) children (`DriftUp`, `DriftDown`, `DriftRight`, `DriftLeft`).

**This task introduces `RandomAI`** — sibling of `PriorityListAI` and `SequenceAI`, currently absent from the engine. Land it as a separate `feat(...)` commit BEFORE the test commit.

**Files:**
- Modify: `engine/appc/ai.py` (add RandomAI class + RandomAI_Create factory)
- Modify: `App.py` (re-export RandomAI + RandomAI_Create)
- Test: `tests/integration/test_no_sensors_evasive_smoke.py` (new)

- [ ] **Step 4.1: Write the test file**

Create `tests/integration/test_no_sensors_evasive_smoke.py`:

```python
"""Activation smoke for AI.Compound.Parts.NoSensorsEvasive.

SDK Parts/NoSensorsEvasive.py: CreateAI(pShip) returns
ConditionalAI("SensorsDisabled") wrapping SequenceAI("LoopForever")
wrapping RandomAI("Random") with 4 PlainAI(ManeuverLoop) children."""
import pytest

import App
from engine.appc.ai import (
    ConditionalAI, SequenceAI, RandomAI, PlainAI,
)
from engine.appc.ai_driver import tick_ai
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


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    return ours


def test_no_sensors_evasive_create_ai_returns_expected_tree():
    ours = _build_scene()
    import AI.Compound.Parts.NoSensorsEvasive as nse
    ai = nse.CreateAI(ours)
    assert isinstance(ai, ConditionalAI)
    assert ai.GetName() == "SensorsDisabled"
    loop = ai._contained_ai
    assert isinstance(loop, SequenceAI)
    assert loop.GetName() == "LoopForever"
    random_ai = loop._ais[0]
    assert isinstance(random_ai, RandomAI)
    assert random_ai.GetName() == "Random"
    assert len(random_ai._ais) == 4
    leaf_names = [c.GetName() for c in random_ai._ais]
    assert set(leaf_names) == {"DriftUp", "DriftDown", "DriftRight", "DriftLeft"}
    for c in random_ai._ais:
        assert isinstance(c, PlainAI)


def test_no_sensors_evasive_tick_does_not_crash():
    ours = _build_scene()
    import AI.Compound.Parts.NoSensorsEvasive as nse
    ai = nse.CreateAI(ours)
    tick_ai(ai, game_time=0.01)
```

- [ ] **Step 4.2: Run; expect `ImportError` on `RandomAI` from engine + `AttributeError: App.RandomAI_Create`**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_no_sensors_evasive_smoke.py -v`

- [ ] **Step 4.3: Add `RandomAI` to engine/appc/ai.py**

Find the `SequenceAI` class in `engine/appc/ai.py` (around line 440). Add a sibling class right after it:

```python
class RandomAI(ArtificialIntelligence):
    """SDK App.py:5019 — sibling of PriorityListAI/SequenceAI.

    Phase 1 behavior: deterministic — picks `_ais[0]` for Update. Real
    random selection is deferred to D2 / behavior-layer slices."""

    def __init__(self, pShip=None, name: str = ""):
        super().__init__(pShip, name)
        self._ais: list = []

    def AddAI(self, ai) -> None:
        """SDK Appc.RandomAI_AddAI — append a child AI."""
        self._ais.append(ai)


def RandomAI_Create(pShip, name: str = "") -> RandomAI:
    """SDK App.py:Appc.RandomAI_Create — factory."""
    return RandomAI(pShip, name)
```

- [ ] **Step 4.4: Re-export from App.py**

Find the existing `PriorityListAI_Create` re-export in `App.py` (around line 110). Add `RandomAI` and `RandomAI_Create` to the same `from engine.appc.ai import (...)` block.

The existing block currently looks like:
```python
from engine.appc.ai import (
    ConditionScript, ConditionScript_Create, ConditionScript_Cast,
    PlainAI, PlainAI_Create, PlainAI_Cast,
    PriorityListAI, PriorityListAI_Create, PriorityListAI_Cast,
    SequenceAI, SequenceAI_Create, SequenceAI_Cast,
    ...
```

Add `RandomAI, RandomAI_Create` in the same block. The exact location of the import block can be confirmed by grepping `from engine.appc.ai import` in `App.py`.

- [ ] **Step 4.5: Run tests to verify pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_no_sensors_evasive_smoke.py -v`
Expected: 2 passed.

- [ ] **Step 4.6: Run regression**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q --ignore=tests/unit/test_hud_euler.py --ignore=tests/unit/test_phaser_damage_falloff.py --ignore=tests/unit/test_ship_alert_level.py 2>&1 | tail -3`
Expected: 1257+ passed (the existing AI-related tests should not regress from adding RandomAI).

- [ ] **Step 4.7: Commit engine surface**

```bash
git add engine/appc/ai.py App.py
git commit -m "feat(ai): RandomAI primitive (sibling of PriorityListAI/SequenceAI)"
```

- [ ] **Step 4.8: Commit test**

```bash
git add tests/integration/test_no_sensors_evasive_smoke.py
git commit -m "test(ai): NoSensorsEvasive sub-Compound activation smoke"
```

---

## Task 5: ICOMove activation smoke

`ICOMove.CreateAI(pShip, sTarget, dKeywords, fForwardBias=0.0)` returns a `PriorityListAI` named "ICOMovePriorities" with 3 children: `ConditionalAI("UseShields")` (priority 1), `ConditionalAI("UseSideWeapons_2")` (priority 2), `PlainAI("ICO_MoveNoWeaponsNoShields")` (priority 3). 4 PlainAI(`IntelligentCircleObject`) instances appear in the tree.

**Files:**
- Test: `tests/integration/test_ico_move_smoke.py` (new)

- [ ] **Step 5.1: Write the test file**

Create `tests/integration/test_ico_move_smoke.py`:

```python
"""Activation smoke for AI.Compound.Parts.ICOMove.

SDK Parts/ICOMove.py: CreateAI(pShip, sTarget, dKeywords, fForwardBias=0.0)
returns PriorityListAI("ICOMovePriorities") with 3 children:
ConditionalAI("UseShields") priority 1, ConditionalAI("UseSideWeapons_2")
priority 2, PlainAI("ICO_MoveNoWeaponsNoShields") priority 3.

Most elaborate Part — nested PriorityListAI/ConditionalAI structure
with 4 PlainAI(IntelligentCircleObject) leaf instances."""
import pytest

import App
from engine.appc.ai import PriorityListAI, ConditionalAI, PlainAI
from engine.appc.ai_driver import tick_ai
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


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); pSet.AddObjectToSet(target, "Target")
    return ours, target


def test_ico_move_create_ai_returns_priority_list_with_three_children():
    ours, _target = _build_scene()
    import AI.Compound.Parts.ICOMove as ico
    ai = ico.CreateAI(ours, "Target", {})
    assert isinstance(ai, PriorityListAI)
    assert ai.GetName() == "ICOMovePriorities"
    assert len(ai._ais) == 3
    children_by_name = {c.GetName(): c for _prio, c in ai._ais}
    assert "UseShields" in children_by_name
    assert isinstance(children_by_name["UseShields"], ConditionalAI)
    assert "UseSideWeapons_2" in children_by_name
    assert isinstance(children_by_name["UseSideWeapons_2"], ConditionalAI)
    assert "ICO_MoveNoWeaponsNoShields" in children_by_name
    assert isinstance(children_by_name["ICO_MoveNoWeaponsNoShields"], PlainAI)


def test_ico_move_tick_does_not_crash():
    ours, _target = _build_scene()
    import AI.Compound.Parts.ICOMove as ico
    ai = ico.CreateAI(ours, "Target", {})
    tick_ai(ai, game_time=0.01)
```

- [ ] **Step 5.2: Run; expect pass or small engine gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_ico_move_smoke.py -v`

Likely gaps: `_AIScriptInstance.SetFollowObjectName`, `SetShieldAndWeaponImportance`, `SetForwardBias` should already degrade via the `_AIScriptInstance.__getattr__` setter generator. Verify; if any setter crashes, that's a real engine gap — fix as a small `feat(...)` commit first.

- [ ] **Step 5.3: Commit**

```bash
git add tests/integration/test_ico_move_smoke.py
git commit -m "test(ai): ICOMove sub-Compound activation smoke"
```

---

## Task 6: FollowThroughWarp activation smoke

`FollowThroughWarp.CreateAI(pShip, sTarget, bWarpBlindly=0, **dKeywords)` returns a `SequenceAI` named "FollowThroughWarpSequence" wrapping 3 nested `ConditionalAI`s (outermost: "TargetExistsInWrongSet", middle: "CheckStarbase12", innermost: "CheckMissionWarping") wrapping a `PlainAI` named "WarpFollow" (script module: "FollowThroughWarp").

The `**dKeywords` unpacking and `dict.has_key(...)` calls in the SDK source rely on the conftest Py2 fixups landed in Slices A and C.

**Files:**
- Test: `tests/integration/test_follow_through_warp_smoke.py` (new)

- [ ] **Step 6.1: Write the test file**

Create `tests/integration/test_follow_through_warp_smoke.py`:

```python
"""Activation smoke for AI.Compound.FollowThroughWarp.

SDK FollowThroughWarp.py: CreateAI(pShip, sTarget, bWarpBlindly=0,
**dKeywords) returns SequenceAI("FollowThroughWarpSequence") wrapping
3 nested ConditionalAIs (outermost "TargetExistsInWrongSet", middle
"CheckStarbase12", innermost "CheckMissionWarping") around PlainAI
("WarpFollow", script module "FollowThroughWarp")."""
import pytest

import App
from engine.appc.ai import SequenceAI, ConditionalAI, PlainAI
from engine.appc.ai_driver import tick_ai
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


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); pSet.AddObjectToSet(target, "Target")
    return ours, target


def test_follow_through_warp_create_ai_returns_expected_tree():
    ours, _target = _build_scene()
    import AI.Compound.FollowThroughWarp as ftw
    ai = ftw.CreateAI(ours, "Target")
    assert isinstance(ai, SequenceAI)
    assert ai.GetName() == "FollowThroughWarpSequence"
    # Outermost ConditionalAI inside the sequence.
    outer = ai._ais[0]
    assert isinstance(outer, ConditionalAI)
    assert outer.GetName() == "TargetExistsInWrongSet"
    # Walk to the innermost PlainAI.
    middle = outer._contained_ai
    assert isinstance(middle, ConditionalAI)
    assert middle.GetName() == "CheckStarbase12"
    inner = middle._contained_ai
    assert isinstance(inner, ConditionalAI)
    assert inner.GetName() == "CheckMissionWarping"
    leaf = inner._contained_ai
    assert isinstance(leaf, PlainAI)
    assert leaf.GetName() == "WarpFollow"


def test_follow_through_warp_tick_does_not_crash():
    ours, _target = _build_scene()
    import AI.Compound.FollowThroughWarp as ftw
    ai = ftw.CreateAI(ours, "Target")
    tick_ai(ai, game_time=0.01)
```

- [ ] **Step 6.2: Run; expect pass or small engine gaps**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_follow_through_warp_smoke.py -v`
Expected: 2 passed.

If `**dKeywords` or `dict.has_key(...)` in the SDK source crashes, that's a conftest-fixup gap (Py2 idiom not handled). Investigate — Slice A's `_fix_py2_syntax` handled `.has_key` and Slice C added `_FixDictKeysIter`. Should be fine.

- [ ] **Step 6.3: Commit**

```bash
git add tests/integration/test_follow_through_warp_smoke.py
git commit -m "test(ai): FollowThroughWarp Compound activation smoke"
```

---

## Task 7: Update deferred AI-runtime doc

Close Slice D1; forward-ref D2 (PlainAI bodies) and E.

**Files:**
- Modify: `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`

- [ ] **Step 7.1: Update the Slice C/D section**

In `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`, find the section "Follow-up after BuilderAI + ConditionScript (Slice A complete)". Update the Slice D bullet (which currently reads):

```markdown
- **Slice D**: PlainAI sub-graphs that FedAttack/NonFedAttack splice in (`TorpRun`, `StationaryAttack`, `TurnToAttack`, `SweepPhasers`, `ICOMove`, `WarpBeforeDeath`, `EvadeTorps`).
```

Replace with:

```markdown
- **Slice D1**: ✅ done in [BasicAttack sub-Compound smokes plan](../plans/2026-05-19-basicattack-subcompound-smokes.md). Per-sub-Compound activation smokes for the 6 sub-Compounds NonFedAttack/FedAttack splice in: EvadeTorps, WarpBeforeDeath, SweepPhasers, NoSensorsEvasive (added RandomAI primitive), ICOMove, FollowThroughWarp. Activation only — PlainAI Update body behaviour is D2 scope.
- **Slice D2**: PlainAI body ports for the 5 PlainAI scripts NonFedAttack/FedAttack instantiate: `TorpedoRun` (~239 LOC), `StationaryAttack` (~143), `IntelligentCircleObject` (~392), `FollowObject` (~182), Intercept polish. Makes sub-Compounds actually drive ship behaviour instead of just activating.
```

- [ ] **Step 7.2: Run focused regression sweep**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit tests/integration --continue-on-collection-errors -q -k "select or fire or condition or builder_ai or event_manager or object_group or proximity or ai_driver or ai_primitives or evade or warp or sweep or sensors or ico_move or follow_through or non_fed" 2>&1 | tail -3`
Expected: green (modulo pre-existing native-binding collection errors).

- [ ] **Step 7.3: Commit**

```bash
git add docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md
git commit -m "docs(deferred): close Slice D1 + forward-ref D2/E"
```

---

## Out of scope (deferred to D2, E)

- Real `Update` behaviour of `TorpedoRun`, `StationaryAttack`, `IntelligentCircleObject`, `FollowObject`. Slice D2.
- `Intercept` polish (Slice A landed an initial port; gaps may exist). Slice D2.
- Real `Condition` ports beyond Slice A's two (`ConditionExists`, `ConditionInRange`). Lazy fallback continues to cover others. Slice E or whenever a mission needs a specific Condition.
- Tightening the NonFedAttack xpass test. Slice E.
- `RandomAI` real random selection (Phase 1 deterministic stub picks `_ais[0]`). Slice D2 or behavior layer.

These remain noted in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
