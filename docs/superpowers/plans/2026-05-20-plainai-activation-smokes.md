# PlainAI Activation Smokes Implementation Plan (Slice F)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cover the 17 unported PlainAI bodies with per-script activation smoke tests. Each test verifies the script loads, configures via its required setters, and that one `Update()` call returns a valid `US_*` integer status — not a `_Stub` (silent crash absorption) and not an exception.

**Architecture:** One smoke test file per script under `tests/integration/test_<script>_smoke.py`. Each test instantiates the PlainAI via `App.PlainAI_Create + SetScriptModule + GetScriptInstance`, calls the SDK's `SetRequiredParams`-declared setters with minimal valid values, calls `Update()` once, and asserts the result is `isinstance(int)` and in `{US_ACTIVE, US_DONE, US_DORMANT, US_INVALID}`. Engine gaps surfaced by any test land as separate `feat(<module>): <what>` commits BEFORE the consuming test commit (Slices A–E pattern).

**Tech Stack:** Python 3, pytest, `_SDKFinder` SDK loader.

---

## Prerequisites

Confirm Slice E is merged: `git log --oneline | grep "Slice E"` should show `Merge: visible BasicAttack mission (Slice E)` at `6b37b81`.

Baseline tests once before starting:
```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q --ignore=tests/unit/test_hud_euler.py --ignore=tests/unit/test_phaser_damage_falloff.py --ignore=tests/unit/test_ship_alert_level.py 2>&1 | tail -3
```
Expected: 1267 passed.

## Worktree setup

Create `.claude/worktrees/plainai-smokes` on branch `worktree-plainai-smokes` off current main. SDK/game directories are gitignored — symlink them from the main repo. Always prefix bash with `unset VIRTUAL_ENV &&`.

## Engine-gap escalation pattern (carry-over)

**Trivial gaps:** fix inline as separate `feat(<module>): <what>` commits BEFORE the test commit they unblock.

**Novel gaps:** STOP and report.

The test commit must be test-only.

## Per-script setter table

Read from `SetRequiredParams` declarations in each SDK script:

| Script | Setter | Arg type |
|---|---|---|
| TriggerEvent | `SetEvent(pEvent)` | `TGEvent` instance |
| SelfDestruct | — (none) | |
| RunScript | `SetScriptModule(s)` + `SetFunction(s)` | strings |
| RunAction | `SetAction(idAction)` | int |
| Defensive | `SetEnemyName(s)` | string |
| Ram | `SetTargetObjectName(s)` | string |
| ManeuverLoop | — (none) | |
| EvilShuttleDocking | `SetObjectToDockWith(s)` | string |
| Flee | `SetFleeFromGroup(grp)` | `ObjectGroup` |
| TurnToOrientation | `SetObjectName(s)` | string |
| StarbaseAttack (PlainAI) | `SetTargets(grp)` | `ObjectGroup` |
| EvadeTorps (PlainAI) | — (none) | |
| CircleObject | `SetFollowObjectName(s)` + `SetNearFacingVector(v)` | string + `TGPoint3` |
| MoveToObjectSide | `SetObjectSide(v)` + `SetObjectName(s)` | `TGPoint3` + string |
| FollowWaypoints | `SetTargetWaypointName(s)` | string |
| FollowThroughWarp (PlainAI) | `SetFollowObjectName(s)` | string |
| Warp | — (none) | |

## File structure

| File | Purpose |
|---|---|
| `tests/integration/test_trigger_event_smoke.py` (new) | Task 1 |
| `tests/integration/test_self_destruct_smoke.py` (new) | Task 1 |
| `tests/integration/test_run_script_smoke.py` (new) | Task 1 |
| `tests/integration/test_run_action_smoke.py` (new) | Task 1 |
| `tests/integration/test_defensive_smoke.py` (new) | Task 2 |
| `tests/integration/test_ram_smoke.py` (new) | Task 2 |
| `tests/integration/test_maneuver_loop_smoke.py` (new) | Task 2 |
| `tests/integration/test_evil_shuttle_docking_smoke.py` (new) | Task 2 |
| `tests/integration/test_flee_smoke.py` (new) | Task 3 |
| `tests/integration/test_turn_to_orientation_smoke.py` (new) | Task 3 |
| `tests/integration/test_starbase_attack_plainai_smoke.py` (new) | Task 3 |
| `tests/integration/test_evade_torps_plainai_smoke.py` (new) | Task 3 |
| `tests/integration/test_circle_object_smoke.py` (new) | Task 4 |
| `tests/integration/test_move_to_object_side_smoke.py` (new) | Task 4 |
| `tests/integration/test_follow_waypoints_smoke.py` (new) | Task 4 |
| `tests/integration/test_follow_through_warp_plainai_smoke.py` (new) | Task 5 |
| `tests/integration/test_warp_smoke.py` (new) | Task 5 |
| `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md` (modify) | Task 6 |

## Shared test fixture pattern

Every smoke uses this shape. The fixture is repeated per file (not extracted to conftest) so each test stands alone; engine gaps in one fixture don't cascade across test files.

```python
"""Activation smoke for AI.PlainAI.<Script>.

Asserts the SDK script loads, configures via its required setters,
and Update() returns a valid US_* integer status. _Stub returns
(silent crash absorption) fail the isinstance(int) check; genuine
exceptions bubble through pytest."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


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
    """Ship at origin in set "S". Target ship (if needed) at (0, 100, 0)
    under the name "Target"."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    return pSet, ours
```

The per-script test body wires the PlainAI + configures setters + calls Update + asserts. Each task spells out the per-script bodies.

---

## Task 1: Tiny batch (4 scripts, ~310 LOC)

**Scripts:** TriggerEvent (69), SelfDestruct (70), RunScript (84), RunAction (88).

These have small bodies; likely surface "fire an event" / "run a callback" engine surface. Each test ~55-65 LOC. The test commit covers all 4 files together (single batch commit).

### Step 1.1: Create `tests/integration/test_trigger_event_smoke.py`

```python
"""Activation smoke for AI.PlainAI.TriggerEvent.

SDK requires SetEvent(pEvent). The script fires that event when
its Update runs."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.events import TGEvent
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_trigger_event_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("TriggerEvent")
    inst = plain.GetScriptInstance()
    evt = TGEvent(); evt.SetEventType(App.ET_MISSION_START)
    inst.SetEvent(evt)
    result = inst.Update()
    assert isinstance(result, int), (
        f"expected int, got {type(result).__name__} (likely _Stub)")
    assert result in _VALID_STATUS, f"unexpected status {result}"
```

### Step 1.2: Create `tests/integration/test_self_destruct_smoke.py`

```python
"""Activation smoke for AI.PlainAI.SelfDestruct.

SDK has no required setters. The script destroys the ship it's
attached to when Update fires."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_self_destruct_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("SelfDestruct")
    inst = plain.GetScriptInstance()
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 1.3: Create `tests/integration/test_run_script_smoke.py`

```python
"""Activation smoke for AI.PlainAI.RunScript.

SDK requires SetScriptModule(s) + SetFunction(s) — names a module + a
function to call. Point at a guaranteed-importable stub: App itself
has an Update-named member? No — point at a no-op helper. Easiest:
target a function that exists on the SDK's own MissionLib (App is
imported by every SDK module so referencing App.something is safe)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_run_script_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("RunScript")
    inst = plain.GetScriptInstance()
    # Point at any importable module+function pair. The SDK will
    # __import__() this and call getattr(mod, fn)(pShip).
    # `MissionLib.LogString` is a side-effect-free string log helper.
    inst.SetScriptModule("MissionLib")
    inst.SetFunction("LogString")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 1.4: Create `tests/integration/test_run_action_smoke.py`

```python
"""Activation smoke for AI.PlainAI.RunAction.

SDK requires SetAction(idAction) — an action ID. The script triggers
that action on the ship. Use 0 (a likely no-op ID; the engine's
TGAction registry returns None/Stub for unknown IDs)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_run_action_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("RunAction")
    inst = plain.GetScriptInstance()
    inst.SetAction(0)
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 1.5: Run the 4 smokes

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest \
  tests/integration/test_trigger_event_smoke.py \
  tests/integration/test_self_destruct_smoke.py \
  tests/integration/test_run_script_smoke.py \
  tests/integration/test_run_action_smoke.py -v
```
Expected: 4 passed. Each engine gap → separate `feat(...)` commit BEFORE the test commit. STOP if any gap requires multi-line logic.

### Step 1.6: Commit (test-only batch commit)

```bash
git add tests/integration/test_trigger_event_smoke.py \
        tests/integration/test_self_destruct_smoke.py \
        tests/integration/test_run_script_smoke.py \
        tests/integration/test_run_action_smoke.py
git commit -m "test(ai): PlainAI activation smokes (Tiny batch: TriggerEvent, SelfDestruct, RunScript, RunAction)"
```

---

## Task 2: Medium-A batch (4 scripts, ~630 LOC)

**Scripts:** Defensive (206), Ram (138), ManeuverLoop (152), EvilShuttleDocking (137).

### Step 2.1: Create `tests/integration/test_defensive_smoke.py`

```python
"""Activation smoke for AI.PlainAI.Defensive.

SDK requires SetEnemyName(s)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_defensive_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    enemy = ShipClass(); enemy.SetTranslateXYZ(0, 100, 0)
    enemy._hull = HullSubsystem("H"); enemy._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(enemy, "Enemy")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("Defensive")
    inst = plain.GetScriptInstance()
    inst.SetEnemyName("Enemy")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 2.2: Create `tests/integration/test_ram_smoke.py`

```python
"""Activation smoke for AI.PlainAI.Ram.

SDK requires SetTargetObjectName(s)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_ram_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    # Ram likely reads pShip.GetImpulseEngineSubsystem().GetMaxSpeed().
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, 200, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("Ram")
    inst = plain.GetScriptInstance()
    inst.SetTargetObjectName("Target")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 2.3: Create `tests/integration/test_maneuver_loop_smoke.py`

```python
"""Activation smoke for AI.PlainAI.ManeuverLoop.

SDK has no required setters. Drives random drift maneuvers — used by
the NoSensorsEvasive sub-Compound."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_maneuver_loop_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("ManeuverLoop")
    inst = plain.GetScriptInstance()
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 2.4: Create `tests/integration/test_evil_shuttle_docking_smoke.py`

```python
"""Activation smoke for AI.PlainAI.EvilShuttleDocking.

SDK requires SetObjectToDockWith(s) — a target to dock with."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_evil_shuttle_docking_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, 50, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("EvilShuttleDocking")
    inst = plain.GetScriptInstance()
    inst.SetObjectToDockWith("Target")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 2.5: Run the 4 smokes

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest \
  tests/integration/test_defensive_smoke.py \
  tests/integration/test_ram_smoke.py \
  tests/integration/test_maneuver_loop_smoke.py \
  tests/integration/test_evil_shuttle_docking_smoke.py -v
```
Expected: 4 passed. Engine gaps → separate `feat(...)` commits.

### Step 2.6: Commit

```bash
git add tests/integration/test_defensive_smoke.py \
        tests/integration/test_ram_smoke.py \
        tests/integration/test_maneuver_loop_smoke.py \
        tests/integration/test_evil_shuttle_docking_smoke.py
git commit -m "test(ai): PlainAI activation smokes (Medium-A: Defensive, Ram, ManeuverLoop, EvilShuttleDocking)"
```

---

## Task 3: Medium-B batch (4 scripts, ~770 LOC)

**Scripts:** Flee (190), TurnToOrientation (181), StarbaseAttack (PlainAI, 170), EvadeTorps (PlainAI, 229).

### Step 3.1: Create `tests/integration/test_flee_smoke.py`

```python
"""Activation smoke for AI.PlainAI.Flee.

SDK requires SetFleeFromGroup(grp) — an ObjectGroup of pursuers."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_flee_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    pursuer = ShipClass(); pursuer.SetTranslateXYZ(0, 100, 0)
    pursuer._hull = HullSubsystem("H"); pursuer._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(pursuer, "Pursuer")

    grp = ObjectGroup(); grp.AddName("Pursuer")
    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("Flee")
    inst = plain.GetScriptInstance()
    inst.SetFleeFromGroup(grp)
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 3.2: Create `tests/integration/test_turn_to_orientation_smoke.py`

```python
"""Activation smoke for AI.PlainAI.TurnToOrientation.

SDK requires SetObjectName(s) — the object whose orientation to copy."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_turn_to_orientation_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    other = ShipClass(); other.SetTranslateXYZ(0, 100, 0)
    other._hull = HullSubsystem("H"); other._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(other, "Other")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("TurnToOrientation")
    inst = plain.GetScriptInstance()
    inst.SetObjectName("Other")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 3.3: Create `tests/integration/test_starbase_attack_plainai_smoke.py`

Filename uses `_plainai_` suffix to disambiguate from the `Compound/StarbaseAttack` Compound (which isn't ported yet but might be added later).

```python
"""Activation smoke for AI.PlainAI.StarbaseAttack (the PlainAI body,
not the Compound of the same name).

SDK requires SetTargets(grp) — an ObjectGroup of starbase targets."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_starbase_attack_plainai_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    starbase = ShipClass(); starbase.SetTranslateXYZ(0, 200, 0)
    starbase._hull = HullSubsystem("H"); starbase._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(starbase, "Starbase")

    grp = ObjectGroup(); grp.AddName("Starbase")
    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("StarbaseAttack")
    inst = plain.GetScriptInstance()
    inst.SetTargets(grp)
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 3.4: Create `tests/integration/test_evade_torps_plainai_smoke.py`

Filename uses `_plainai_` suffix to distinguish from `tests/integration/test_evade_torps_smoke.py` (the Slice D1 Compound sub-Part smoke).

```python
"""Activation smoke for AI.PlainAI.EvadeTorps (the PlainAI body,
not the Compound sub-Part of the same name).

SDK has no required setters. Drives evasive maneuvers when torps
are tracked as incoming."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_evade_torps_plainai_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("EvadeTorps")
    inst = plain.GetScriptInstance()
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 3.5: Run + commit

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest \
  tests/integration/test_flee_smoke.py \
  tests/integration/test_turn_to_orientation_smoke.py \
  tests/integration/test_starbase_attack_plainai_smoke.py \
  tests/integration/test_evade_torps_plainai_smoke.py -v
```
Expected: 4 passed.

```bash
git add tests/integration/test_flee_smoke.py \
        tests/integration/test_turn_to_orientation_smoke.py \
        tests/integration/test_starbase_attack_plainai_smoke.py \
        tests/integration/test_evade_torps_plainai_smoke.py
git commit -m "test(ai): PlainAI activation smokes (Medium-B: Flee, TurnToOrientation, StarbaseAttack PlainAI, EvadeTorps PlainAI)"
```

---

## Task 4: Large-A batch (3 scripts, ~880 LOC)

**Scripts:** CircleObject (259), MoveToObjectSide (309), FollowWaypoints (311).

### Step 4.1: Create `tests/integration/test_circle_object_smoke.py`

```python
"""Activation smoke for AI.PlainAI.CircleObject.

SDK requires SetFollowObjectName(s) + SetNearFacingVector(v: TGPoint3)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_circle_object_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    center = ShipClass(); center.SetTranslateXYZ(0, 100, 0)
    center._hull = HullSubsystem("H"); center._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(center, "Center")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("CircleObject")
    inst = plain.GetScriptInstance()
    inst.SetFollowObjectName("Center")
    side = App.TGPoint3(); side.SetXYZ(1.0, 0.0, 0.0)
    inst.SetNearFacingVector(side)
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 4.2: Create `tests/integration/test_move_to_object_side_smoke.py`

```python
"""Activation smoke for AI.PlainAI.MoveToObjectSide.

SDK requires SetObjectSide(v: TGPoint3) + SetObjectName(s)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_move_to_object_side_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    obj = ShipClass(); obj.SetTranslateXYZ(0, 100, 0)
    obj._hull = HullSubsystem("H"); obj._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(obj, "Object")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("MoveToObjectSide")
    inst = plain.GetScriptInstance()
    side = App.TGPoint3(); side.SetXYZ(1.0, 0.0, 0.0)
    inst.SetObjectSide(side)
    inst.SetObjectName("Object")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 4.3: Create `tests/integration/test_follow_waypoints_smoke.py`

```python
"""Activation smoke for AI.PlainAI.FollowWaypoints.

SDK requires SetTargetWaypointName(s). The script flies a waypoint
path."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_follow_waypoints_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    # FollowWaypoints reads a Waypoint placeable by name. The minimal
    # stand-in is to point at an Object (any non-None resolution) in the
    # set — the Update body is defensive against not-yet-arrived
    # waypoints. If a real Waypoint instance is required, the engine
    # gap surfaces here and lands as a separate feat() commit.
    other = ShipClass(); other.SetTranslateXYZ(0, 100, 0)
    other._hull = HullSubsystem("H"); other._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(other, "WP1")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("FollowWaypoints")
    inst = plain.GetScriptInstance()
    inst.SetTargetWaypointName("WP1")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 4.4: Run + commit

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest \
  tests/integration/test_circle_object_smoke.py \
  tests/integration/test_move_to_object_side_smoke.py \
  tests/integration/test_follow_waypoints_smoke.py -v
```
Expected: 3 passed.

```bash
git add tests/integration/test_circle_object_smoke.py \
        tests/integration/test_move_to_object_side_smoke.py \
        tests/integration/test_follow_waypoints_smoke.py
git commit -m "test(ai): PlainAI activation smokes (Large-A: CircleObject, MoveToObjectSide, FollowWaypoints)"
```

---

## Task 5: Large-B batch (2 scripts, ~750 LOC)

**Scripts:** FollowThroughWarp (PlainAI body, 281), Warp (468).

These are the heaviest single PlainAI bodies — Warp is the biggest at 468 LOC, and FollowThroughWarp threads in-system warp follow logic. Most likely to surface engine surface gaps.

### Step 5.1: Create `tests/integration/test_follow_through_warp_plainai_smoke.py`

Filename uses `_plainai_` suffix to distinguish from `tests/integration/test_follow_through_warp_smoke.py` (the Slice D1 Compound smoke).

```python
"""Activation smoke for AI.PlainAI.FollowThroughWarp (the PlainAI
body, not the Compound of the same name).

SDK requires SetFollowObjectName(s). The script follows a target
through warp transitions."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_follow_through_warp_plainai_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, 200, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("FollowThroughWarp")
    inst = plain.GetScriptInstance()
    inst.SetFollowObjectName("Target")
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 5.2: Create `tests/integration/test_warp_smoke.py`

```python
"""Activation smoke for AI.PlainAI.Warp (the largest unported
PlainAI at 468 LOC).

SDK has no required setters in SetRequiredParams. The script drives
in-system warp transitions."""
import pytest

import App
from engine.appc.ai import PlainAI_Create, ArtificialIntelligence
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
)


_VALID_STATUS = (
    ArtificialIntelligence.US_ACTIVE,
    ArtificialIntelligence.US_DONE,
    ArtificialIntelligence.US_DORMANT,
    ArtificialIntelligence.US_INVALID,
)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_warp_update_returns_valid_status():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours._hull = HullSubsystem("H")
    ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    # Warp script reads pShip.GetWarpEngineSubsystem(); seed it.
    ours._warp_engine_subsystem = WarpEngineSubsystem("WES")
    pSet.AddObjectToSet(ours, "Ours")

    plain = PlainAI_Create(ours, "TestAI")
    plain.SetScriptModule("Warp")
    inst = plain.GetScriptInstance()
    result = inst.Update()
    assert isinstance(result, int)
    assert result in _VALID_STATUS
```

### Step 5.3: Run + commit

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest \
  tests/integration/test_follow_through_warp_plainai_smoke.py \
  tests/integration/test_warp_smoke.py -v
```
Expected: 2 passed. This batch is most likely to surface engine gaps; each → separate `feat(...)` commit before the test commit.

```bash
git add tests/integration/test_follow_through_warp_plainai_smoke.py \
        tests/integration/test_warp_smoke.py
git commit -m "test(ai): PlainAI activation smokes (Large-B: FollowThroughWarp PlainAI, Warp)"
```

---

## Task 6: Close the deferred doc

Mark Slice F ✅ in `docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`.

### Step 6.1: Find the BasicAttack roadmap section

Look for the section added by Slice A and progressively updated through D2/E. It currently ends with the Slice E closure paragraph.

### Step 6.2: Append the Slice F closure paragraph

Add a new bullet AFTER the Slice E closure:

```markdown
### Follow-up after BasicAttack — PlainAI activation coverage

- **Slice F**: ✅ done in [PlainAI activation smokes plan](../plans/2026-05-20-plainai-activation-smokes.md). 17 unported PlainAI bodies now have per-script activation smoke tests verifying their `Update()` returns a valid `US_*` integer status (catches both genuine exceptions AND silent `_Stub` absorption). Kinematic correctness for these 17 scripts remains explicitly deferred — they activate but their motion/combat output isn't asserted. Future per-script behaviour tests land when a mission needs the specific PlainAI to drive a particular behaviour.
```

### Step 6.3: Run final focused regression sweep

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit tests/integration --continue-on-collection-errors -q -k "select or fire or condition or builder_ai or event_manager or object_group or proximity or ai_driver or ai_primitives or torpedo_run or stationary_attack or follow_object or intelligent_circle or intercept or non_fed or fed_attack or fuzzy or evade_torps or warp or sweep or sensors or ico_move or follow_through or m3gameflow or trigger_event or self_destruct or run_script or run_action or defensive or ram or maneuver_loop or evil_shuttle or flee or turn_to_orientation or starbase_attack or circle_object or move_to_object or follow_waypoints" 2>&1 | tail -3
```
Expected: green (modulo pre-existing native-binding collection errors).

### Step 6.4: Commit

```bash
git add docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md
git commit -m "docs(deferred): close Slice F (PlainAI activation coverage)"
```

---

## Out of scope (deferred to future)

- **Kinematic correctness** of the 17 scripts covered here. Smoke proves Update completes and returns a sensible status; doesn't assert speed setpoints or turn vectors.
- **Conditions, Preprocessors, Compounds** — each has its own future slice path.
- **Tactical-brain depth** in BasicAttack ports — Slice C deferred CheckGoodShot etc.
- **Weapon VFX rendering** — Phase 2 renderer work.

These remain documented in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
