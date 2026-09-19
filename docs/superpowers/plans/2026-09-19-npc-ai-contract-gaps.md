# NPC AI Contract Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 15 ranked behaviour gaps in `docs/engine/npc-ai-contract-review-2026-09-19.md` so every SDK AI doctrine, leaf behaviour and condition that BC runs behaves the same way under Dauntless.

**Architecture:** Three seams. (1) The `App` shim gains the six undefined names the SDK scripts call (`TGPoint3_GetRandomUnitVector`, three `*_Cast` functions, one geometry helper, `TGCondition_Cast`), each a pure function over classes that already exist. (2) Two event families gain engine producers (ObjectGroup membership, object deletion) and one existing producer gains its missing state attach (`SetWarpSequence`), all posted through `App.g_kEventManager` to the SDK's own handlers. (3) The AI tick gains a per-node exception guard, and the FireScript wrapper gains the two things BC's native node had that its Python body assumes (`GetChildTargets`, `OptimizedFireScript` identity). No renderer or C++ changes; Python only.

**Tech Stack:** Python 3.11, pytest, the real SDK scripts loaded through `tests/conftest.py`'s `_SDKFinder`.

**Spec:** `docs/engine/npc-ai-contract-review-2026-09-19.md` (§2 ranked table is the requirement list; §4 is the test-writing rule).

## Global Constraints

- **Every test asserts a behaviour, never just a status.** Spec §4: status-only smoke tests are how every gap here survived. Each task's test must fail with the fix removed; the step that proves it is not optional.
- **Never grep `def <Name>(` to decide surface exists**; grep the bare name across `App.py engine/`. `hasattr(App, name)` is always true — test with `isinstance(v, App._NamedStub)`.
- **Real SDK classes in tests**, not doubles. SDK scripts are at the path `engine.paths.sdk_scripts()` resolves; `tests/conftest.py` already puts them on the import path so `import Conditions.ConditionInRange` and `plain.SetScriptModule("Flee")` work.
- **Shared checkout.** Stage with explicit pathspecs only. Never `git add -A`, `git stash`, `git checkout --`, `git restore`, `git clean`, `git reset --hard`. Subagents included.
- **Test gate before the final commit of the plan:** `scripts/check_tests.sh`. Per task, run the named tests plus `tests/unit/test_ai_*.py tests/unit/test_condition_*.py`.
- **Dev-mode diagnostics use `print()`**, never `logging.*` — no handler is configured anywhere in `engine/`.
- `App.py` re-exports engine symbols; a new function lives in the owning `engine/appc/*.py` module and is imported into `App.py` (see how `PulseWeaponSystem_Cast` at `App.py:634` is defined in place because it needs `App`'s namespace — either pattern is fine, match the neighbour).
- Game units throughout: 1 GU = 175 m. Never name a variable `*_m`.
- After every task, run the full AI subset: `uv run pytest tests/unit/test_ai_*.py tests/unit/test_condition_*.py tests/integration/test_fed_attack_smoke.py tests/integration/test_non_fed_attack_smoke.py -q -p no:cacheprovider`.

---

## File map

| File | Responsibility in this plan |
|---|---|
| `engine/appc/math.py` | `TGPoint3_GetRandomUnitVector`, `TGGeomUtils_LineSphereIntersection` |
| `App.py` | export the two above; `PhaserBank_Cast`, `PulseWeaponProperty_Cast`, `WeaponSystem_Cast`, `TGCondition_Cast` |
| `engine/appc/weapon_subsystems.py` | `WeaponSystem.IsInTargetList` |
| `engine/appc/ai.py` | `TGCondition` registered in the id registry; `OptimizedFireScript` docstring refresh |
| `engine/core/ids.py` | `allocate_id()` so a non-`TGObject` can join the registry |
| `engine/appc/timers.py` | `AddTimer` returns the timer id |
| `engine/appc/ai_driver.py` | `_run_script_step` guard; SelectTarget event hooks in `_ensure_select_target_initialized` |
| `engine/appc/ai_optimized.py` | `GetChildTargets` on the FireScript wrapper; wrapper is an `OptimizedFireScript` |
| `engine/appc/objects.py` | `ObjectGroup` live registry + `broadcast_membership`; `broadcast_object_deleted` |
| `engine/appc/sets.py` | call the two broadcasts from add/remove/delete |
| `engine/appc/ship_death.py` | deletion broadcast + AI teardown on death |
| `engine/host_loop.py` | deletion broadcast in the `_delete_me` sweep |
| `engine/appc/warp.py` | `WarpSequence.Play/Completed` attach/detach on the warp engine |
| `docs/engine/aieditor-ai-surface-and-gaps.md`, `docs/stub_heatmap.md`, `docs/engine/event-emitter-gaps.md`, `docs/engine/npc-ai-contract-review-2026-09-19.md` | close-out edits |

Shared test scaffolding used by several tasks (copy it into each test file; do not create a shared helper module — the existing tests all inline it):

```python
import pytest
import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _set(name="S"):
    pSet = App.SetClass_Create(); pSet.SetName(name)
    App.g_kSetManager._sets[name] = pSet
    return pSet


def _ship(pSet, name, x=0.0, y=0.0, z=0.0, max_speed=120.0):
    s = ShipClass(); s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    s._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    s._impulse_engine_subsystem.SetMaxSpeed(max_speed)
    pSet.AddObjectToSet(s, name)
    return s
```

---

### Task 1: `TGPoint3_GetRandomUnitVector` (spec #1)

**Files:**
- Modify: `engine/appc/math.py:416-432` (append after the `TGPoint3_GetModel*` block)
- Modify: `App.py` (the import line that brings `TGPoint3_GetModelForward` in from `engine.appc.math` — add the new name beside it)
- Test: `tests/unit/test_random_unit_vector.py`, `tests/integration/test_flee_two_pursuers_turns.py`

**Interfaces:**
- Produces: `App.TGPoint3_GetRandomUnitVector() -> TGPoint3` — a uniformly distributed unit vector, fresh object per call.

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/test_random_unit_vector.py
"""App.TGPoint3_GetRandomUnitVector — heatmap rank 1 (80,805 hits).
Undefined, every call returned a truthy _NamedStub whose .x/.y/.z were
stubs, so Flee/EvadeTorps/Warp/AvoidObstacles scored every random
candidate as the zero vector."""
import math
import App
from engine.appc.math import TGPoint3


def test_is_real_surface_not_a_stub():
    assert not isinstance(App.TGPoint3_GetRandomUnitVector, App._NamedStub)


def test_returns_a_unit_tgpoint3():
    v = App.TGPoint3_GetRandomUnitVector()
    assert isinstance(v, TGPoint3)
    assert abs(math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) - 1.0) < 1e-6


def test_successive_calls_differ_and_cover_every_octant():
    seen = set()
    for _ in range(400):
        v = App.TGPoint3_GetRandomUnitVector()
        seen.add((v.x > 0, v.y > 0, v.z > 0))
    assert len(seen) == 8, "not uniformly distributed over the sphere"


def test_each_call_is_a_fresh_object():
    a = App.TGPoint3_GetRandomUnitVector()
    b = App.TGPoint3_GetRandomUnitVector()
    assert a is not b
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_random_unit_vector.py -q -p no:cacheprovider`
Expected: FAIL — `test_is_real_surface_not_a_stub` asserts False; the others raise on stub arithmetic.

- [ ] **Step 3: Implement**

In `engine/appc/math.py`, after `TGPoint3_GetModelLeft`:

```python
import random as _random

_unit_vector_rng = _random.Random()


def TGPoint3_GetRandomUnitVector() -> TGPoint3:
    """Uniform random unit vector (Marsaglia). SDK callers:
    AI/PlainAI/Flee.py:115, EvadeTorps.py:172, Warp.py:367,
    AI/Preprocessors.py:1904 (AvoidObstacles). Each draws N candidates and
    scores them, so the distribution must cover the whole sphere — a
    biased draw would bias every flee/evade heading."""
    while True:
        a = _unit_vector_rng.uniform(-1.0, 1.0)
        b = _unit_vector_rng.uniform(-1.0, 1.0)
        s = a * a + b * b
        if 0.0 < s < 1.0:
            break
    k = 2.0 * math.sqrt(1.0 - s)
    return TGPoint3(a * k, b * k, 1.0 - 2.0 * s)
```

(`math` is already imported at the top of `math.py`; check and add if not.) In `App.py`, find the line importing `TGPoint3_GetModelForward` from `engine.appc.math` and add `TGPoint3_GetRandomUnitVector` to that import list.

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `uv run pytest tests/unit/test_random_unit_vector.py -q -p no:cacheprovider`
Expected: 4 passed.

- [ ] **Step 5: Write the failing behaviour test (Flee with two pursuers)**

```python
# tests/integration/test_flee_two_pursuers_turns.py
"""A ship fleeing TWO pursuers must change heading.

With one pursuer Flee.py:106-109 takes the exact opposite direction, so the
old status-only smoke passed. With two or more, Flee.py:115 draws random
candidates via App.TGPoint3_GetRandomUnitVector; undefined, every candidate
was a stub, TurnTowardDirection got the zero vector and returned early, and
the ship charged straight ahead at full impulse forever."""
import math
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem
from engine.core.loop import GameLoop, TICK_RATE


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _ship(pSet, name, x, y, z):
    s = ShipClass(); s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    s._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    s._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(s, name)
    return s


def _forward(ship):
    v = TGPoint3(0.0, 1.0, 0.0)
    v.MultMatrixLeft(ship.GetWorldRotation())
    return v


def test_fleeing_two_pursuers_accumulates_heading_change():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = _ship(pSet, "Ours", 0, 0, 0)
    # Two pursuers on opposite flanks: their mean direction is ~zero, so the
    # single-pursuer "exact opposite" shortcut cannot apply and the random
    # candidate draw is the only path to a heading.
    _ship(pSet, "P1", 300, 0, 0)
    _ship(pSet, "P2", -300, 50, 0)

    grp = ObjectGroup(); grp.AddName("P1"); grp.AddName("P2")
    plain = PlainAI_Create(ours, "Flee")
    plain.SetScriptModule("Flee")
    plain.GetScriptInstance().SetFleeFromGroup(grp)
    ours.SetAI(plain)

    loop = GameLoop()
    travelled = 0.0
    previous = _forward(ours)
    for _ in range(10):
        loop.advance(TICK_RATE * 1)
        now = _forward(ours)
        dot = previous.x * now.x + previous.y * now.y + previous.z * now.z
        travelled += math.acos(max(-1.0, min(1.0, dot)))
        previous = now

    assert travelled > 0.3, (
        f"fleeing ship never turned: {travelled:.3f} rad of total travel — "
        "Flee's random candidate draw is inert")
```

- [ ] **Step 6: Prove the behaviour test is sensitive**

Temporarily comment out the `TGPoint3_GetRandomUnitVector` name in the `App.py` import (edit, do NOT use git to revert later). Run: `uv run pytest tests/integration/test_flee_two_pursuers_turns.py -q -p no:cacheprovider`
Expected: FAIL with `travelled` ≈ 0.000. Restore the import line by editing it back; confirm with `git diff App.py` that only the intended addition remains.

- [ ] **Step 7: Run both tests to verify they pass**

Run: `uv run pytest tests/unit/test_random_unit_vector.py tests/integration/test_flee_two_pursuers_turns.py tests/integration/test_flee_smoke.py tests/integration/test_evade_torps_smoke.py tests/integration/test_warp_smoke.py tests/integration/test_pursuers_avoid_each_other.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/math.py App.py tests/unit/test_random_unit_vector.py tests/integration/test_flee_two_pursuers_turns.py
git commit -m "feat(ai): TGPoint3_GetRandomUnitVector — Flee/EvadeTorps/Warp/AvoidObstacles candidate draws are real

Heatmap rank 1 (80,805 hits). Undefined, every random candidate was a
truthy stub scoring as the zero vector; a ship fleeing two pursuers never
turned and an NPC warp with an obstacle ahead sat at speed 0 forever.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `PhaserBank_Cast` (spec #2)

**Files:**
- Modify: `App.py` (beside `PulseWeapon_Cast` at `App.py:622`)
- Test: `tests/unit/test_phaser_bank_cast.py`

**Interfaces:**
- Produces: `App.PhaserBank_Cast(obj) -> PhaserBank | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_phaser_bank_cast.py
"""App.PhaserBank_Cast — heatmap ranks 7-10/61 (23,864 hits).

Two SDK consumers, both silently wrong without it:
  * AI/PlainAI/PhaserSweep.py:52 builds lpPhaserBanks from the cast; a
    stub's CalculateRoughDirection().Dot() is a stub, `stub > fSweepDot`
    is False, so the sweep never picked a bank and always nosed onto the
    target.
  * Conditions/ConditionInPhaserFiringArc.py:173 — stub.CanFire() and
    stub.CanHit() are truthy, so the condition read TRUE forever and
    FedAttack's TorpsReadyAndNotInEnemyFiringArc branch was permanently
    dormant."""
import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc.weapon_subsystems import PhaserSystem, PhaserBank, TorpedoSystem
import pytest


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_cast_is_real_and_type_checks():
    assert not isinstance(App.PhaserBank_Cast, App._NamedStub)
    bank = PhaserBank("Fwd")
    assert App.PhaserBank_Cast(bank) is bank
    assert App.PhaserBank_Cast(PhaserSystem("P")) is None
    assert App.PhaserBank_Cast(TorpedoSystem("T")) is None
    assert App.PhaserBank_Cast(None) is None


def _ship_with_forward_bank(pSet, name, x, y, z):
    """Same bank authoring as tests/unit/test_phaser_can_hit.py::_forward_bank,
    on a real ShipClass: forward-facing, ±50° width, 100 GU range."""
    from engine.appc.math import TGPoint3
    from engine.appc.properties import PhaserProperty
    s = ShipClass(); s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    phasers = PhaserSystem("P"); phasers._parent_ship = s
    bank = PhaserBank("Fwd"); bank._parent_ship = s
    prop = PhaserProperty("Fwd")
    prop.SetPosition(0.0, 0.0, 0.0)
    prop.SetOrientation(TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetArcWidthAngles(-0.872665, 0.872665)
    prop.SetArcHeightAngles(-0.052360, 1.047198)
    prop.SetMaxDamageDistance(100.0)
    bank.SetProperty(prop)
    phasers.AddChildSubsystem(bank)
    s._phaser = phasers
    pSet.AddObjectToSet(s, name)
    return s, bank


def test_condition_in_phaser_firing_arc_reads_false_out_of_arc():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    enemy, bank = _ship_with_forward_bank(pSet, "Enemy", 0, 0, 0)
    ours = ShipClass(); ours.SetTranslateXYZ(0, -2000, 0)   # dead astern of Enemy
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    # Precondition: the real bank says the point astern is NOT hittable.
    assert bank.CanHit(ours.GetWorldLocation()) == 0

    cond = ConditionScript_Create(
        "Conditions.ConditionInPhaserFiringArc", "ConditionInPhaserFiringArc",
        "Ours", "Enemy")
    cond.SetActive()
    assert cond._instance is not None, cond._init_error
    cond._instance.CheckState()
    assert cond.GetStatus() == 0, (
        "condition reads in-arc for a target the bank cannot hit — "
        "PhaserBank_Cast handed back a truthy stub")
```

The bank authoring is copied from `tests/unit/test_phaser_can_hit.py` (verified real: `PhaserProperty.SetArcWidthAngles` at `properties.py:489`, `ShipSubsystem.AddChildSubsystem` at `subsystems.py:984`). The condition's constructor arguments are `(pCodeCondition, sOurShip, sTarget, ...)` per `tests/unit/test_condition_external_functions.py:260` — confirm the third positional in the SDK file before writing the `ConditionScript_Create` line.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_phaser_bank_cast.py -q -p no:cacheprovider`
Expected: FAIL — first test on the `_NamedStub` assert, second with status 1.

- [ ] **Step 3: Implement**

In `App.py` after `PulseWeapon_Cast`:

```python
def PhaserBank_Cast(obj):
    """SDK AI/PlainAI/PhaserSweep.py:52 and
    Conditions/ConditionInPhaserFiringArc.py:173 —
    `pBank = App.PhaserBank_Cast(pSystem.GetChildSubsystem(i))`.
    Was undefined: a truthy _NamedStub made the sweep never pick a bank and
    the arc condition read TRUE for every target (heatmap ranks 7-10/61)."""
    try:
        from engine.appc.weapon_subsystems import PhaserBank
    except ImportError:
        return None
    return obj if isinstance(obj, PhaserBank) else None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_phaser_bank_cast.py tests/integration/test_sweep_phasers_smoke.py tests/integration/test_fed_attack_smoke.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add App.py tests/unit/test_phaser_bank_cast.py
git commit -m "feat(ai): PhaserBank_Cast — PhaserSweep picks banks, InPhaserFiringArc reads real arcs

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `PulseWeaponProperty_Cast` (spec #3)

**Files:**
- Modify: `App.py` (beside `ShieldProperty_Cast` at `App.py:492`)
- Test: `tests/unit/test_pulse_weapon_property_cast.py`

**Interfaces:**
- Produces: `App.PulseWeaponProperty_Cast(obj) -> PulseWeaponProperty | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pulse_weapon_property_cast.py
"""App.PulseWeaponProperty_Cast — heatmap ranks 83-88.

Conditions/ConditionPulseReady.py:139 does
`App.PulseWeaponProperty_Cast(pWeapon.GetProperty()).GetOrientationForward()`
and dots it against the wanted direction. A stub dots to 0, `0 >= 0.66` is
False, every weapon is excluded, lpCachedWeapons stays empty and the
condition reads FALSE forever — so every NonFedAttack ship
(NonFedAttack.py:272,545) never took its pulse-ready branch."""
import pytest

import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.properties import PulseWeaponProperty, ShieldProperty
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc.weapon_subsystems import PulseWeaponSystem, PulseWeapon


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_cast_is_real_and_type_checks():
    assert not isinstance(App.PulseWeaponProperty_Cast, App._NamedStub)
    prop = PulseWeaponProperty("Cannon")
    assert App.PulseWeaponProperty_Cast(prop) is prop
    assert App.PulseWeaponProperty_Cast(ShieldProperty("S")) is None
    assert App.PulseWeaponProperty_Cast(None) is None


def test_condition_pulse_ready_sees_a_charged_forward_cannon():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    system = PulseWeaponSystem("Pulse"); system._parent_ship = ship
    prop = PulseWeaponProperty("Cannon")
    prop.SetOrientation(App.TGPoint3_GetModelForward(), App.TGPoint3_GetModelUp())
    cannon = PulseWeapon("Cannon"); cannon._parent_ship = ship
    cannon.SetProperty(prop)
    system._children.append(cannon)
    ship._pulse_weapon_system = system
    pSet.AddObjectToSet(ship, "Ours")
    # Fully charged.
    cannon.SetChargeLevel(cannon.GetMaxCharge())

    cond = ConditionScript_Create(
        "Conditions.ConditionPulseReady", "ConditionPulseReady",
        "Ours", App.TGPoint3_GetModelForward())
    assert cond._instance is not None, cond._init_error
    assert len(cond._instance.lpCachedWeapons) == 1, (
        "the forward cannon was excluded — PulseWeaponProperty_Cast is a stub")
    assert cond.GetStatus() == 1
```

Before finalising: read `Conditions/ConditionPulseReady.py` `__init__` in the SDK for the exact constructor arguments (ship name, direction vector, optional charge fraction), and `engine/appc/properties.py:627` + `weapon_subsystems.py:2393-2420` for `SetOrientation`/`SetProperty`/`SetChargeLevel`/`GetMaxCharge` names; adjust the fixture to the real names. The test must build the ship with the real classes, not a double.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_pulse_weapon_property_cast.py -q -p no:cacheprovider`
Expected: FAIL on the `_NamedStub` assert and on `lpCachedWeapons == []`.

- [ ] **Step 3: Implement**

In `App.py` after `ShieldProperty_Cast`:

```python
def PulseWeaponProperty_Cast(obj):
    """SDK Conditions/ConditionPulseReady.py:139 —
    `App.PulseWeaponProperty_Cast(pWeapon.GetProperty()).GetOrientationForward()`.
    Was undefined; the stub dotted to 0 and excluded every weapon, so
    ConditionPulseReady read FALSE forever (heatmap ranks 83-88)."""
    from engine.appc.properties import PulseWeaponProperty
    return obj if isinstance(obj, PulseWeaponProperty) else None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_pulse_weapon_property_cast.py tests/integration/test_non_fed_attack_smoke.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add App.py tests/unit/test_pulse_weapon_property_cast.py
git commit -m "feat(ai): PulseWeaponProperty_Cast — ConditionPulseReady sees its cannons

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `WeaponSystem_Cast` + `WeaponSystem.IsInTargetList` (spec #7)

**Files:**
- Modify: `App.py` (beside `PulseWeaponSystem_Cast` at `App.py:634`)
- Modify: `engine/appc/weapon_subsystems.py:1145` (beside `GetNumTargets`)
- Test: `tests/unit/test_weapon_system_cast_and_target_list.py`

**Interfaces:**
- Produces: `App.WeaponSystem_Cast(obj) -> WeaponSystem | None`; `WeaponSystem.IsInTargetList(target) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_weapon_system_cast_and_target_list.py
"""App.WeaponSystem_Cast + WeaponSystem.IsInTargetList — heatmap 115/116/167.

AI/PlainAI/StarbaseAttack.py:112-115:
    pWeapSystem = App.WeaponSystem_Cast(pSystem)
    for pTarget in lTargets:
        if not pWeapSystem.IsInTargetList(pTarget):
            pWeapSystem.StartFiring(pTarget)
Both undefined: stub.IsInTargetList() is truthy, `not` is False, StartFiring
is never called. The E7M3 starbases never fired."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc.weapon_subsystems import PhaserSystem, PhaserBank, WeaponSystem, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_cast_is_real_and_accepts_any_weapon_system():
    assert not isinstance(App.WeaponSystem_Cast, App._NamedStub)
    p = PhaserSystem("P"); t = TorpedoSystem("T")
    assert App.WeaponSystem_Cast(p) is p
    assert App.WeaponSystem_Cast(t) is t
    assert App.WeaponSystem_Cast(HullSubsystem("H")) is None
    assert App.WeaponSystem_Cast(None) is None


def test_is_in_target_list_is_a_real_int():
    p = PhaserSystem("P")
    target = ShipClass()
    assert p.IsInTargetList(target) == 0
    p._add_target(target)
    assert p.IsInTargetList(target) == 1


def test_starbase_attack_starts_firing_at_its_target():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    base = ShipClass()
    base._hull = HullSubsystem("H"); base._hull.SetMaxCondition(1000.0)
    phasers = PhaserSystem("P"); phasers._parent_ship = base
    base._phaser = phasers
    pSet.AddObjectToSet(base, "Base")
    enemy = ShipClass(); enemy.SetTranslateXYZ(0, 400, 0)
    enemy._hull = HullSubsystem("H"); enemy._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(enemy, "Enemy")

    calls = []
    original = phasers.StartFiring
    def _record(target, *a, **k):
        calls.append(target)
        return original(target, *a, **k)
    phasers.StartFiring = _record

    plain = PlainAI_Create(base, "SBA")
    plain.SetScriptModule("StarbaseAttack")
    inst = plain.GetScriptInstance()
    inst.SetTargets(["Enemy"])       # StarbaseAttack.py:41 — ObjectGroup_ForceToGroup(lsTargets)
    inst.Update()
    assert calls and calls[0] is enemy, (
        "StarbaseAttack never called StartFiring — WeaponSystem_Cast/IsInTargetList are stubs")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_weapon_system_cast_and_target_list.py -q -p no:cacheprovider`
Expected: FAIL on all three.

- [ ] **Step 3: Implement**

`engine/appc/weapon_subsystems.py`, after `GetNumTargets`:

```python
    def IsInTargetList(self, target) -> int:
        """SDK AI/PlainAI/StarbaseAttack.py:114. Must be a real int: a stub
        here is truthy, so `if not IsInTargetList(t): StartFiring(t)` never
        fired (heatmap 116)."""
        return 1 if target is not None and target in self._target_list else 0
```

`App.py`, after `PulseWeaponSystem_Cast`:

```python
def WeaponSystem_Cast(obj):
    """SDK AI/PlainAI/StarbaseAttack.py:112,129 —
    `pWeapSystem = App.WeaponSystem_Cast(pSystem)` over a
    CT_WEAPON_SYSTEM match. Any WeaponSystem (phaser/torpedo/pulse/tractor
    aggregator OR a leaf bank, which subclasses WeaponSystem here) passes."""
    return obj if isinstance(obj, WeaponSystem) else None
```

(`WeaponSystem` must be in `App.py`'s import from `engine.appc.weapon_subsystems`; add it if the grep `^from engine.appc.weapon_subsystems import` shows it absent.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_weapon_system_cast_and_target_list.py tests/integration/test_starbase_attack_plainai_smoke.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add App.py engine/appc/weapon_subsystems.py tests/unit/test_weapon_system_cast_and_target_list.py
git commit -m "feat(ai): WeaponSystem_Cast + IsInTargetList — StarbaseAttack fires

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `TGGeomUtils_LineSphereIntersection` (spec #13)

**Files:**
- Modify: `engine/appc/math.py` (append)
- Modify: `App.py` (same import line as Task 1)
- Test: `tests/unit/test_line_sphere_intersection.py`

**Interfaces:**
- Produces: `App.TGGeomUtils_LineSphereIntersection(start: TGPoint3, ray: TGPoint3, centre: TGPoint3, radius: float, near_out: TGPoint3, far_out: TGPoint3) -> int` — 1 if the segment `start → start+ray` intersects the sphere, writing entry/exit points into the two out-params via `SetXYZ`; 0 otherwise (out-params untouched).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_line_sphere_intersection.py
"""App.TGGeomUtils_LineSphereIntersection — AI/PlainAI/Intercept.py:326.

The SDK passes (vStart, vRay, centre, radius, vNearPoint, vFarPoint) and
reads vNearPoint back. Undefined, the truthy stub made every candidate
"intersect" with vNearPoint left at the origin, so Intercept dodged the
FIRST obstacle in its list rather than the nearest."""
import App
from engine.appc.math import TGPoint3


def _p(x, y, z):
    return TGPoint3(float(x), float(y), float(z))


def test_is_real_surface():
    assert not isinstance(App.TGGeomUtils_LineSphereIntersection, App._NamedStub)


def test_segment_through_sphere_reports_entry_and_exit():
    near, far = TGPoint3(), TGPoint3()
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 100, 0), _p(0, 50, 0), 10.0, near, far)
    assert hit == 1
    assert (near.x, round(near.y, 6), near.z) == (0.0, 40.0, 0.0)
    assert (far.x, round(far.y, 6), far.z) == (0.0, 60.0, 0.0)


def test_segment_missing_sphere_reports_zero_and_leaves_outputs():
    near, far = _p(9, 9, 9), _p(8, 8, 8)
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 100, 0), _p(50, 50, 0), 10.0, near, far)
    assert hit == 0
    assert (near.x, near.y, near.z) == (9.0, 9.0, 9.0)


def test_sphere_beyond_segment_end_is_a_miss():
    near, far = TGPoint3(), TGPoint3()
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 10, 0), _p(0, 50, 0), 10.0, near, far)
    assert hit == 0


def test_start_inside_sphere_reports_start_as_entry():
    near, far = TGPoint3(), TGPoint3()
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 100, 0), _p(0, 0, 0), 10.0, near, far)
    assert hit == 1
    assert (near.x, near.y, near.z) == (0.0, 0.0, 0.0)
    assert round(far.y, 6) == 10.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_line_sphere_intersection.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

`engine/appc/math.py`:

```python
def TGGeomUtils_LineSphereIntersection(start, ray, centre, radius,
                                       near_out, far_out) -> int:
    """Segment start→start+ray vs sphere(centre, radius). SDK caller:
    AI/PlainAI/Intercept.py:326 (obstacle refinement). Returns 1 and writes
    the entry point into near_out and exit point into far_out when the
    SEGMENT (not the infinite line) touches the sphere; a start inside the
    sphere reports start itself as the entry. Returns 0 and leaves the
    out-params untouched otherwise. Stated assumption: BC's native routine
    is segment-bounded — Intercept only cares about obstacles between it
    and its destination."""
    dx, dy, dz = ray.x, ray.y, ray.z
    a = dx * dx + dy * dy + dz * dz
    if a <= 0.0:
        return 0
    ox, oy, oz = start.x - centre.x, start.y - centre.y, start.z - centre.z
    b = 2.0 * (ox * dx + oy * dy + oz * dz)
    c = ox * ox + oy * oy + oz * oz - float(radius) * float(radius)
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return 0
    root = math.sqrt(disc)
    t0 = (-b - root) / (2.0 * a)
    t1 = (-b + root) / (2.0 * a)
    if t1 < 0.0 or t0 > 1.0:
        return 0
    t_near = max(t0, 0.0)
    t_far = min(t1, 1.0)
    near_out.SetXYZ(start.x + dx * t_near, start.y + dy * t_near, start.z + dz * t_near)
    far_out.SetXYZ(start.x + dx * t_far, start.y + dy * t_far, start.z + dz * t_far)
    return 1
```

Export from `App.py` on the `engine.appc.math` import line.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_line_sphere_intersection.py tests/integration/test_ai_intercept_smoke.py tests/integration/test_intercept_polish_smoke.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/math.py App.py tests/unit/test_line_sphere_intersection.py
git commit -m "feat(ai): TGGeomUtils_LineSphereIntersection — Intercept dodges the nearest obstacle

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `TGCondition_Cast` and conditions in the object-id registry (spec #10)

**Files:**
- Modify: `engine/core/ids.py:1-30` (add `allocate_id`)
- Modify: `engine/appc/ai.py:47-66` (`TGCondition.__init__`), `:150-170` (`ConditionScript.__init__`), `:230-238` (add `TGCondition_Cast`)
- Modify: `App.py` (export `TGCondition_Cast` beside `ConditionScript_Cast`)
- Test: `tests/unit/test_tgcondition_cast_and_ids.py`

**Interfaces:**
- Produces: `ids.allocate_id() -> int`; `TGCondition.GetObjID() -> int` valid for `App.TGObject_GetTGObjectPtr`; `App.TGCondition_Cast(obj) -> TGCondition | None`.
- Consumers: `MissionLib.ConditionChangedRedirect` (`:2536`), `E2M0.py:156`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tgcondition_cast_and_ids.py
"""App.TGCondition_Cast — heatmap 122/130.

MissionLib.ConditionChangedRedirect:2536 does
    pCondition = App.TGCondition_Cast(pEvent.GetSource())
    bStatus = pCondition.GetStatus()
and forwards bStatus to the mission's handler. Undefined, bStatus was a
truthy stub on BOTH the 0->1 and 1->0 edges, so E7M6's g_bInOrbit never
cleared. E2M0.py:156 goes further and looks the condition up by id via
TGObject_GetTGObjectPtr, which needs conditions in the id registry."""
import App
from engine.appc.ai import TGCondition, ConditionScript_Create


def test_cast_is_real_and_type_checks():
    assert not isinstance(App.TGCondition_Cast, App._NamedStub)
    c = TGCondition()
    assert App.TGCondition_Cast(c) is c
    assert App.TGCondition_Cast(object()) is None
    assert App.TGCondition_Cast(None) is None


def test_condition_script_is_a_tgcondition_for_the_cast():
    cs = ConditionScript_Create("Conditions.ConditionFlagSet", "ConditionFlagSet", {}, "x")
    assert App.TGCondition_Cast(cs) is cs


def test_condition_is_reachable_by_object_id():
    c = TGCondition()
    assert App.TGObject_GetTGObjectPtr(c.GetObjID()) is c
    cs = ConditionScript_Create("Conditions.ConditionFlagSet", "ConditionFlagSet", {}, "x")
    assert App.TGObject_GetTGObjectPtr(cs.GetObjID()) is cs


def test_condition_script_get_by_id_still_resolves():
    from engine.appc.ai import ConditionScript_GetByID
    cs = ConditionScript_Create("Conditions.ConditionFlagSet", "ConditionFlagSet", {}, "x")
    assert ConditionScript_GetByID(cs.GetObjID()) is cs


def test_condition_changed_redirect_passes_the_real_status():
    """The MissionLib path end to end: a condition flipping 1 -> 0 must hand
    the handler 0, not a truthy stub."""
    import MissionLib
    seen = []
    def handler(status):
        seen.append(status)
    MissionLib.__dict__["_probe_handler"] = handler
    c = TGCondition()
    MissionLib.CallFunctionWhenConditionChanges(c, "MissionLib._probe_handler") \
        if hasattr(MissionLib, "CallFunctionWhenConditionChanges") else None
    c.SetStatus(1)
    c.SetStatus(0)
    assert seen[-2:] == [1, 0]
```

Read `MissionLib.py:2500-2545` in the SDK to confirm the registration helper's real name and calling convention and replace the `hasattr` guard with the real call; if the helper resolves the function by dotted string, register `_probe_handler` accordingly.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_tgcondition_cast_and_ids.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

`engine/core/ids.py`, after `register`:

```python
def allocate_id() -> int:
    """Hand out the next object id without creating a TGObject. For classes
    that must be findable via TGObject_GetTGObjectPtr but deliberately are
    NOT TGObjects (TGCondition — a TGObject's __getattr__ stub would hide
    condition-script bugs behind truthy stubs)."""
    return next(_counter)
```

`engine/appc/ai.py` `TGCondition.__init__`:

```python
    def __init__(self):
        from engine.core import ids
        self._obj_id: int = ids.allocate_id()
        ids.register(self)          # E2M0.py:156 looks conditions up by id
        self._status: int = 0
        self._handlers: list = []
        self._active: bool = False

    def GetObjID(self) -> int:
        return self._obj_id
```

`ConditionScript.__init__`: delete the two lines `self._obj_id = ConditionScript._next_id` / `ConditionScript._next_id += 1` (the base now assigns it) and keep `ConditionScript._registry[self._obj_id] = weakref.ref(self)`. Delete `ConditionScript.GetObjID` (inherited now). Remove the `_next_id` class attribute if nothing else reads it (grep first).

After `ConditionScript_Cast`:

```python
def TGCondition_Cast(obj):
    """SDK MissionLib.py:2536 (ConditionChangedRedirect) and E2M0.py:156.
    Undefined, the stub's GetStatus() was truthy on both edges."""
    return obj if isinstance(obj, TGCondition) else None
```

Export `TGCondition_Cast` from `App.py` next to `ConditionScript_Cast`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_tgcondition_cast_and_ids.py tests/unit/test_condition_*.py tests/unit/test_conditional_eval_memo.py tests/unit/test_ai_activation_lifecycle.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/core/ids.py engine/appc/ai.py App.py tests/unit/test_tgcondition_cast_and_ids.py
git commit -m "feat(ai): TGCondition_Cast + conditions in the object-id registry

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: `AddTimer` returns the timer id (spec #12)

**Files:**
- Modify: `engine/appc/timers.py:69-71`
- Test: `tests/unit/test_add_timer_returns_id.py`

**Interfaces:**
- Produces: `TGTimerManager.AddTimer(timer) -> int` (the timer's `GetObjID()`), usable with the existing `DeleteTimer(obj_id)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_add_timer_returns_id.py
"""TGTimerManager.AddTimer must return the timer id.

Conditions/ConditionAttacked.py:105 and ConditionAttackedBy.py:119:
    idTimer = App.g_kTimerManager.AddTimer(pTimer)
    if idTimer: self.dForgivenessTimers[sAttacker] = idTimer
Returning None meant the id was never recorded, so StopForgivenessTimer
never deleted anything and the forgiveness timer fired regardless of later
hits — the conditions reached TRUE less often than BC."""
import App
from engine.appc.timers import TGTimer


def test_add_timer_returns_the_objid():
    t = App.TGTimer_Create()
    t.SetTimerStart(App.g_kTimerManager.get_time() + 5.0)
    got = App.g_kTimerManager.AddTimer(t)
    assert got == t.GetObjID()
    App.g_kTimerManager.DeleteTimer(got)
    assert got not in App.g_kTimerManager._timers


def test_condition_attacked_records_its_forgiveness_timer():
    import pytest
    from engine.appc.ai import ConditionScript_Create
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import HullSubsystem
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    victim = ShipClass(); victim._hull = HullSubsystem("H"); victim._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(victim, "Victim")
    shooter = ShipClass(); shooter._hull = HullSubsystem("H"); shooter._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(shooter, "Shooter")

    cond = ConditionScript_Create("Conditions.ConditionAttacked", "ConditionAttacked", "Victim", 0.5)
    cond.SetActive()
    assert cond._instance is not None, cond._init_error

    evt = App.WeaponHitEvent_Create()
    evt.SetEventType(App.ET_WEAPON_HIT)
    evt.SetSource(shooter); evt.SetDestination(victim)
    evt.SetFiringObject(shooter); evt.SetDamage(10.0); evt.SetHullHit(1)
    App.g_kEventManager.AddEvent(evt)

    timers = cond._instance.dForgivenessTimers
    assert "Shooter" in timers and isinstance(timers["Shooter"], int), (
        "forgiveness timer id was not recorded — AddTimer returned None")
```

Confirm the SDK's `ConditionAttacked.__init__` arguments and the dict name (`dForgivenessTimers` or similar) by reading `Conditions/ConditionAttacked.py:95-125`; confirm `WeaponHitEvent` setter names in `engine/appc/events.py:381-461`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_add_timer_returns_id.py -q -p no:cacheprovider`
Expected: FAIL (`None == id`; dict empty).

- [ ] **Step 3: Implement**

```python
    def AddTimer(self, timer: TGTimer) -> int:
        """Returns the timer's object id. Conditions/ConditionAttacked.py:105
        keys its forgiveness timers on this return value and deletes them
        through DeleteTimer(id); a None return silently disabled cancel."""
        timer._fire_pending = False
        self._timers[timer.GetObjID()] = timer
        return timer.GetObjID()
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_add_timer_returns_id.py tests/unit/test_timers*.py tests/unit/test_condition_timer_end_to_end.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/timers.py tests/unit/test_add_timer_returns_id.py
git commit -m "fix(timers): AddTimer returns the id so ConditionAttacked can cancel forgiveness

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Per-node exception guard in the AI tick (spec #9)

**Files:**
- Modify: `engine/appc/ai_driver.py:488-506` (`_tick_plain`), `:1240-1248` (`_tick_preprocessing`)
- Test: `tests/unit/test_ai_script_exception_guard.py`

**Interfaces:**
- Produces: `ai_driver._run_script_step(ai, call) -> object | None` — runs `call()`, on `Exception` records it on the node as `ai._last_script_error = (type_name, message)`, prints once per node per exception type under dev mode, and returns `None` (which the two callers already map to `US_ACTIVE` / `PS_NORMAL`).

Policy, stated for the reviewer: BC's embedded Python reports a script exception and continues the frame. Dauntless today lets it unwind `loop.tick()` and kill the sim. This task adopts BC's policy per node: the failing node reports "no work this tick", every other ship keeps ticking, and the error is visible in dev mode and on the node for the AI inspector.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_script_exception_guard.py
"""A leaf or preprocessor that raises must not take the whole AI tick down.

Spec #9: nothing between the SDK script and host_loop's loop.tick() caught an
exception, so one Disable order (FireScript.GetChildTargets, spec #6) or
Defend.py's GetConditionScript would end the sim for every ship. BC's
embedded interpreter reports and continues."""
import App
from engine.appc.ai import PlainAI_Create, PreprocessingAI_Create, ArtificialIntelligence, PreprocessingAI
from engine.appc.ai_driver import tick_ai, tick_all_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


class _Boom:
    def __init__(self): self.calls = 0
    def Update(self):
        self.calls += 1
        raise RuntimeError("scripted failure")


class _BoomPreprocessor:
    def GetNextUpdateTime(self): return 0.0
    def Update(self, dEndTime):
        raise AttributeError("GetChildTargets")


def _ship(pSet, name):
    s = ShipClass(); s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(s, name)
    return s


def test_raising_plain_ai_reports_active_and_records_the_error():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship(pSet, "A")
    plain = PlainAI_Create(ship, "Boom")
    plain._script_instance = _Boom()      # bypass SetScriptModule: synthetic leaf
    status = tick_ai(plain, 0.0)
    assert status == ArtificialIntelligence.US_ACTIVE
    assert plain._last_script_error[0] == "RuntimeError"


def test_raising_preprocessor_does_not_stop_the_other_ship():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    bad = _ship(pSet, "Bad"); good = _ship(pSet, "Good")
    pp = PreprocessingAI_Create(bad, "PP")
    pp.SetPreprocessingMethod(_BoomPreprocessor(), "Update")
    bad.SetAI(pp)
    ticked = []
    class _Counter:
        def Update(self): ticked.append(1); return ArtificialIntelligence.US_ACTIVE
    plain = PlainAI_Create(good, "Count"); plain._script_instance = _Counter()
    good.SetAI(plain)

    tick_all_ai(0.0)          # must not raise
    assert ticked, "the healthy ship was never ticked after the bad one raised"
    assert pp._last_script_error[0] == "AttributeError"
```

`PlainAI._script_instance` is the real attribute (`ai.py:636`) and `GetScriptInstance()` returns it. Confirm `tick_all_ai` iterates ships from `App.g_kSetManager` the way the test builds them (see `ai_driver.py:1592-1640`); if it needs the `ship_iter` active-set list, add the set the same way `tests/unit/test_ai_driver.py` does.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_ai_script_exception_guard.py -q -p no:cacheprovider`
Expected: FAIL — both tests raise through `tick_ai`.

- [ ] **Step 3: Implement**

In `ai_driver.py`, near the top-level helpers (after `_timed_dispatch`):

```python
_reported_script_errors: set = set()


def _run_script_step(ai, call):
    """Run one SDK script entry point (a leaf Update or a preprocessor
    method) under BC's policy: a Python exception is reported and the frame
    continues. Returns the call's result, or None on failure — both callers
    already map None to "no status change" (US_ACTIVE / PS_NORMAL).

    The failure is recorded on the node (AI inspector reads it) and printed
    once per (node id, exception type) under --developer. Silent in
    production, like BC.
    """
    try:
        return call()
    except Exception as exc:                     # noqa: BLE001 — policy
        ai._last_script_error = (type(exc).__name__, str(exc))
        key = (ai.GetID(), type(exc).__name__)
        if key not in _reported_script_errors:
            _reported_script_errors.add(key)
            if dev_mode.is_enabled():
                import traceback
                ship = ai.GetShip()
                name = ship.GetName() if ship is not None and hasattr(ship, "GetName") else "?"
                print(f"[ai] {name} node '{ai.GetName()}' raised "
                      f"{type(exc).__name__}: {exc}")
                traceback.print_exc()
        return None
```

Add `_last_script_error: tuple | None = None` to `ArtificialIntelligence.__init__` in `ai.py` (so the attribute always exists).

`_tick_plain`: replace `status = update_fn()` with `status = _run_script_step(ai, update_fn)`.

`_tick_preprocessing`: replace

```python
        if arity >= 1:
            result = bound(game_time + 1.0)
        else:
            result = bound()
```
with
```python
        if arity >= 1:
            result = _run_script_step(ai, lambda: bound(game_time + 1.0))
        else:
            result = _run_script_step(ai, bound)
```

Also wrap the `GotFocus`/`LostFocus` dispatch calls in `_dispatch_lost_focus` and `_flush_pending_got_focus` the same way (`_run_script_step(node, fn)`), since `Warp.LostFocus` and `FireScript.LostFocus` are SDK code too.

Add `_reported_script_errors.clear()` to whatever reset hook `ai_driver` already exposes for mission swap (grep `def reset` in the file; if none, add `def reset_script_error_log(): _reported_script_errors.clear()` and call it from `tests/conftest.py`'s `_reset_leakable_engine_globals`).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_ai_script_exception_guard.py tests/unit/test_ai_driver*.py tests/unit/test_preprocess_done_is_lethal.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai_driver.py engine/appc/ai.py tests/unit/test_ai_script_exception_guard.py tests/conftest.py
git commit -m "feat(ai): script exceptions are reported per node and the tick continues (BC policy)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: `FireScript.GetChildTargets` on the wrapper (spec #6)

**Files:**
- Modify: `engine/appc/ai_optimized.py:368-424` (`_non_lethal_class`) — add a FireScript-only method
- Test: `tests/integration/test_disable_order_targets_child_subsystems.py`

**Interfaces:**
- Produces: `FireScript_NonLethal.GetChildTargets(self, pSubsystem) -> list` — the targetable, still-alive descendants of a non-targetable subsystem, depth-first, matching what `ChooseTargetSubsystem` (`Preprocessors.py:830-838`) iterates.

Stated assumption (record it in the docstring): BC's native FireScript is unreconstructed; "targetable descendants with condition > 0" is the only reading under which the SDK loop's `if not pSubsystem.IsTargetable(): lTargets = self.GetChildTargets(...)` makes sense, since every stock hardpoint marks the aggregator systems `SetTargetable(0)` and their banks/tubes targetable.

- [ ] **Step 1: Write the failing test**

Reuse the headless probe from the review verbatim (it reproduced the crash at `~0.8 s`), turned into a test:

```python
# tests/integration/test_disable_order_targets_child_subsystems.py
"""A FireScript with an explicit TargetSubsystems list (every Disable order:
AI/Fleet/DisableTarget.py:18, AI/Player/Disable*.py) reaches
Preprocessors.py:832 `self.GetChildTargets(pSubsystem)` whenever the matched
subsystem is non-targetable — and stock hardpoints mark Impulse/Warp/
Phasers/Torpedoes/Tractors/Engineering SetTargetable(0)
(ships/Hardpoints/galaxy.py:774-995). GetChildTargets is defined nowhere
in the SDK: it was a method of BC's NATIVE FireScript. Reproduced 2026-09-19
as an AttributeError out of tick_ai after ~0.8 s."""
import pytest

import App
from engine.appc import ai_sensor_gate
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (HullSubsystem, ImpulseEngineSubsystem,
                                    SensorSubsystem, TorpedoAmmoType)
from engine.appc.weapon_subsystems import PhaserSystem, PhaserBank, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    _reset_app_state()
    monkeypatch.setattr(ai_sensor_gate, "can_detect", lambda *a, **k: True)
    yield
    _reset_app_state()


def _scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES"); ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    ours._sensor_subsystem = SensorSubsystem("Sensors")
    ours._phaser = PhaserSystem("P"); ours._phaser._parent_ship = ours
    ours._torpedo_system = TorpedoSystem("T"); ours._torpedo_system._parent_ship = ours
    ours._torpedo_system._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    pSet.AddObjectToSet(ours, "Attacker")

    target = ShipClass(); target.SetTranslateXYZ(0, 500, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    # The galaxy.py shape: a non-targetable aggregator with targetable children.
    phasers = PhaserSystem("Phasers"); phasers._parent_ship = target
    phasers.SetTargetable(0)
    bank = PhaserBank("Fwd Bank"); bank._parent_ship = target
    bank.SetMaxCondition(100.0); bank.SetCondition(100.0); bank.SetTargetable(1)
    phasers._children.append(bank)
    target._phaser = phasers
    pSet.AddObjectToSet(target, "Target")
    ours.SetTarget("Target")
    return ours, target, bank


def _disable_fire_script(ours):
    import AI.Preprocessors
    pFire = PreprocessingAI_Create(ours, "Fire")
    fs = AI.Preprocessors.FireScript("Target", TargetSubsystems=[(App.CT_WEAPON_SYSTEM, 1)])
    pFire.SetPreprocessingMethod(fs, "Update")
    inst = pFire.GetPreprocessingInstance()
    inst.AddWeaponSystem(ours._torpedo_system); inst.AddWeaponSystem(ours._phaser)
    pStay = PlainAI_Create(ours, "Stay"); pStay.SetScriptModule("Stay")
    pFire.SetContainedAI(pStay)
    ours.SetAI(pFire)
    return pFire


def test_get_child_targets_returns_targetable_live_descendants():
    ours, target, bank = _scene()
    pFire = _disable_fire_script(ours)
    inst = pFire.GetPreprocessingInstance()
    assert inst.GetChildTargets(target._phaser) == [bank]
    bank.SetCondition(0.0)
    assert inst.GetChildTargets(target._phaser) == []


def test_disable_order_runs_ten_seconds_and_picks_a_subsystem():
    ours, target, bank = _scene()
    pFire = _disable_fire_script(ours)
    t = 0.0
    for _ in range(600):
        tick_ai(pFire, t); t += 1.0 / 60
    assert pFire._last_script_error is None, pFire._last_script_error
    assert ours.GetTargetSubsystem() is not None, (
        "Disable order never chose a subsystem to fire at")
```

Confirm `PhaserSystem._children` is the real child list name (`subsystems.py:967-970` `GetNumChildSubsystems`/`GetChildSubsystem`) and that `StartGetSubsystemMatch(CT_WEAPON_SYSTEM)` yields `target._phaser` (`ships.py:1703`, `subsystem_types.py:108-112`); adjust the fixture to whatever the real registration path is (for example `target._subsystems.append(...)`).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_disable_order_targets_child_subsystems.py -q -p no:cacheprovider`
Expected: first test `AttributeError: GetChildTargets`; second fails on `_last_script_error == ("AttributeError", ...)`.

- [ ] **Step 3: Implement**

In `_non_lethal_class`, after the `Update` wrapper definition and before `cls = type(...)`:

```python
    def GetChildTargets(self, pSubsystem):
        """Targetable, still-alive descendants of a non-targetable subsystem.

        Called from the SDK's ChooseTargetSubsystem (Preprocessors.py:832)
        and defined nowhere in the SDK — it belonged to BC's NATIVE
        FireScript, which is unreconstructed. Stated assumption: the only
        reading under which the SDK loop makes sense. Every stock hardpoint
        marks its aggregator systems SetTargetable(0) and their banks/tubes
        targetable (galaxy.py:774-995), so this branch is the common case for
        any explicit TargetSubsystems list (Fleet/DisableTarget, Player/
        Disable*). Without it: AttributeError out of the AI tick.
        """
        out = []
        n = int(pSubsystem.GetNumChildSubsystems()) if hasattr(pSubsystem, "GetNumChildSubsystems") else 0
        for i in range(n):
            child = pSubsystem.GetChildSubsystem(i)
            if child is None:
                continue
            if child.IsTargetable() and child.GetCondition() > 0:
                out.append(child)
            else:
                out.extend(GetChildTargets(self, child))
        return out

    members = {
        "Update": Update,
        "__doc__": (
            "SDK %s with its lethal PS_DONE return translated to "
            "PS_NORMAL. See engine/appc/ai_optimized.py." % base.__name__
        ),
    }
    if base.__name__ == "FireScript":
        members["GetChildTargets"] = GetChildTargets
    cls = type(base.__name__ + "_NonLethal", (base,), members)
```

replacing the existing `cls = type(base.__name__ + "_NonLethal", (base,), {...})` call (Task 10 changes the bases tuple in this same line).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_disable_order_targets_child_subsystems.py tests/unit/test_fire_script_*.py tests/unit/test_optimized_fire_script.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai_optimized.py tests/integration/test_disable_order_targets_child_subsystems.py
git commit -m "fix(ai): FireScript.GetChildTargets — Disable orders no longer raise out of the tick

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: The FireScript wrapper is an `OptimizedFireScript` (spec #11)

**Files:**
- Modify: `engine/appc/ai_optimized.py` (`_non_lethal_class` bases), `engine/appc/ai.py:304-328` (docstring only)
- Test: `tests/unit/test_optimized_fire_script_identity.py`

**Interfaces:**
- Produces: `isinstance(<FireScript node>.GetPreprocessingInstance(), App.OptimizedFireScript)` is true, so `TacticalMenuHandlers.GetPlayerFiringAIScripts` (`:1650-1677`) collects it and `CheckFiring`/`CheckSubsystemTargeting` (`:1679-1775`) drive `SetEnabled`, `RemoveAllWeaponSystems`, `AddWeaponSystem`, `Ignore/RestoreSubsystemTargets` — all of which the SDK `FireScript` already defines (`Preprocessors.py:172-230`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_optimized_fire_script_identity.py
"""The player's tactical fire-control toggles (Manual Aim / Phasers Only /
Target At Will) reach the ship's FireScript only if the node's preprocessing
instance isinstance-matches App.OptimizedFireScript
(Bridge/TacticalMenuHandlers.py:1861, GetPlayerFiringAIScripts). Our wrapper
subclassed the SDK FireScript only, so g_lPlayerFireAIs was always empty and
the toggles were no-ops."""
import App
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def test_bound_fire_script_is_an_optimized_fire_script():
    import AI.Preprocessors
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    node = PreprocessingAI_Create(ship, "Fire")
    node.SetPreprocessingMethod(AI.Preprocessors.FireScript("X"), "Update")
    inst = node.GetPreprocessingInstance()
    assert isinstance(inst, App.OptimizedFireScript)
    # And it still is the SDK class, with the control surface BC's binding lists.
    assert isinstance(inst, AI.Preprocessors.FireScript)
    for name in ("AddWeaponSystem", "RemoveAllWeaponSystems", "SetEnabled",
                 "HasSubsystemTargets", "IgnoreSubsystemTargets",
                 "RestoreSubsystemTargets"):
        assert callable(getattr(inst, name))


def test_other_preprocessors_are_not_optimized_fire_scripts():
    import AI.Preprocessors
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    node = PreprocessingAI_Create(ship, "Alert")
    node.SetPreprocessingMethod(AI.Preprocessors.AlertLevel(App.ShipClass.RED_ALERT), "Update")
    assert not isinstance(node.GetPreprocessingInstance(), App.OptimizedFireScript)


def test_tactical_menu_collects_the_players_fire_scripts():
    import AI.Preprocessors
    import Bridge.TacticalMenuHandlers as TMH
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    node = PreprocessingAI_Create(ship, "Fire")
    node.SetPreprocessingMethod(AI.Preprocessors.FireScript("X"), "Update")
    ship.SetAI(node)
    TMH.g_lPlayerFireAIs = []
    found = TMH.GetPlayerFiringAIScripts(ship) if TMH.GetPlayerFiringAIScripts.__code__.co_argcount else None
    assert node.GetPreprocessingInstance() in (found or TMH.g_lPlayerFireAIs)
```

Read `Bridge/TacticalMenuHandlers.py:1640-1680` for how `GetPlayerFiringAIScripts` populates/returns and whether it takes the player as an argument or reads `MissionLib.GetPlayer()`; write the third test against the real signature (set up `App.Game_GetCurrentPlayer` the way `tests/integration/test_warp_clears_target_on_arrival.py:145-155` does if it needs the player).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_optimized_fire_script_identity.py -q -p no:cacheprovider`
Expected: FAIL on the isinstance assertions.

- [ ] **Step 3: Implement**

In `_non_lethal_class`, choose the bases:

```python
    bases = (base,)
    if base.__name__ == "FireScript":
        # BC's binary swaps FireScript for its native OptimizedFireScript
        # (App.py:5186, a PreprocessingAI subclass carrying the control
        # surface). TacticalMenuHandlers.GetPlayerFiringAIScripts:1861 finds
        # the player's fire nodes by isinstance against that class — so the
        # wrapper must BE one. The SDK FireScript already defines every
        # method the binding lists (Preprocessors.py:172-230).
        from engine.appc.ai import OptimizedFireScript
        bases = (base, OptimizedFireScript)
    cls = type(base.__name__ + "_NonLethal", bases, members)
```

Update the `OptimizedFireScript` docstring in `ai.py` to say the wrapper now inherits it and delete the stale `TODO(combat-fidelity)` paragraph. `OptimizedFireScript` stays an empty marker class with no `__init__` (so MRO stays trivial).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_optimized_fire_script_identity.py tests/unit/test_optimized_fire_script.py tests/integration/test_warp_clears_target_on_arrival.py tests/unit/test_fire_script_*.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai_optimized.py engine/appc/ai.py tests/unit/test_optimized_fire_script_identity.py
git commit -m "feat(ai): the FireScript wrapper is an OptimizedFireScript — tactical fire toggles reach it

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: ObjectGroup membership events (spec #4)

**Files:**
- Modify: `engine/appc/objects.py:1040-1060` (`ObjectGroup`: live registry + `broadcast_membership`)
- Modify: `engine/appc/sets.py:181-200` (`AddObjectToSet`), `:242-256` (`RemoveObjectFromSet`, `DeleteObjectFromSet`)
- Test: `tests/unit/test_object_group_membership_events.py`, `tests/integration/test_condition_all_in_same_set_live.py`

**Interfaces:**
- Produces: `ObjectGroup.broadcast_membership(obj, *, entered: bool) -> None` (classmethod) — for every live group containing `obj.GetName()` whose per-name flag includes `ENTERED_SET`/`EXITED_SET`, posts a `TGObjPtrEvent` of type `ET_OBJECT_GROUP_OBJECT_ENTERED_SET`/`_EXITED_SET` with `SetObjPtr(obj)`, `SetSource(obj)`, `SetDestination(group)`.
- Payload contract, from the consumers: `ConditionAllInSameSet.EnteredSet` reads `pObjEvent.GetObjPtr()` then `.GetContainingSet().GetName()` (`ConditionAllInSameSet.py:89-90`) — so the emit must happen **after** `_containing_set` and `_objects[identifier]` are set on add; `ConditionExists` registers with `target = pObjectGroup`, so destination must be the group. `tests/unit/test_condition_exists.py:88-102` already posts this exact shape by hand.
- **Do not suppress the warp-transit set** (unlike `_broadcast_set_transition`): `AllInSameSet.EnteredSet` only acts while status != 1, so a warping ship must first EXIT (→ 0) before its arrival ENTER can re-evaluate. BC has a real `"warp"` set (`FollowThroughWarp.py:119`), so a transit entry/exit pair is faithful.
- `ET_OBJECT_GROUP_CHANGED` is **out of scope**: its trigger (name list edits vs. set moves) is not established, and per-name flags cannot be set on a group before it has names.

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/test_object_group_membership_events.py
"""ObjectGroup ENTERED_SET / EXITED_SET events — spec #4.

ObjectGroup.SetEventFlag stored the flag and nothing ever posted the event:
13 SDK files subscribe, 21 SetEventFlag call sites. ConditionAllInSameSet
(25 mission AIs) and AnyInSameSet were frozen at their construction value."""
import pytest

import App
from engine.appc.objects import ObjectGroup
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


class _Recorder:
    def __init__(self): self.events = []
    def Entered(self, evt): self.events.append(("in", evt.GetObjPtr(), evt.GetDestination()))
    def Exited(self, evt): self.events.append(("out", evt.GetObjPtr(), evt.GetDestination()))


def _subscribe(group):
    rec = _Recorder()
    w = App.TGPythonInstanceWrapper(); w.SetPyWrapper(rec)
    group.SetEventFlag(App.ObjectGroup.ENTERED_SET)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET, w, "Entered", group)
    group.SetEventFlag(App.ObjectGroup.EXITED_SET)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_OBJECT_EXITED_SET, w, "Exited", group)
    rec._w = w
    return rec


def _ship():
    s = ShipClass(); s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    return s


def test_add_to_set_posts_entered_to_the_watching_group():
    grp = ObjectGroup(); grp.AddName("Bart")
    rec = _subscribe(grp)
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship(); pSet.AddObjectToSet(ship, "Bart")
    assert rec.events == [("in", ship, grp)]
    # The consumer reads the containing set off the object: it must be set by now.
    assert ship.GetContainingSet() is pSet


def test_remove_from_set_posts_exited():
    grp = ObjectGroup(); grp.AddName("Bart")
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship(); pSet.AddObjectToSet(ship, "Bart")
    rec = _subscribe(grp)
    pSet.RemoveObjectFromSet("Bart")
    assert rec.events == [("out", ship, grp)]


def test_group_without_the_flag_or_the_name_is_silent():
    watching = ObjectGroup(); watching.AddName("Lisa")      # wrong name
    unflagged = ObjectGroup(); unflagged.AddName("Bart")    # right name, no flag
    rec_w = _subscribe(watching)
    rec_u = _Recorder(); w = App.TGPythonInstanceWrapper(); w.SetPyWrapper(rec_u)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET, w, "Entered", unflagged)
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    pSet.AddObjectToSet(_ship(), "Bart")
    assert rec_w.events == [] and rec_u.events == []


def test_non_ship_objects_also_post():
    from engine.appc.planet import Planet
    grp = ObjectGroup(); grp.AddName("Vulcan")
    rec = _subscribe(grp)
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    planet = Planet(); pSet.AddObjectToSet(planet, "Vulcan")
    assert [e[0] for e in rec.events] == ["in"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_object_group_membership_events.py -q -p no:cacheprovider`
Expected: FAIL — `rec.events == []`.

- [ ] **Step 3: Implement**

`engine/appc/objects.py` — inside `ObjectGroup`:

```python
    # Every live group, so a set add/remove can find the groups watching the
    # object's name. Weak: a mission's condition drops its group when the
    # condition dies, and the registry must not keep it (or its handlers) alive.
    _live: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self):
        super().__init__()
        self._names: list[str] = []
        self._event_flags: dict[str, set[int]] = {}
        ObjectGroup._live.add(self)

    @classmethod
    def broadcast_membership(cls, obj, *, entered: bool) -> None:
        """Post ET_OBJECT_GROUP_OBJECT_{ENTERED,EXITED}_SET to every group
        watching obj's name with the matching flag. Payload per the SDK
        consumers (ConditionAllInSameSet.py:83-110, ConditionExists.py:84-90):
        TGObjPtrEvent, GetObjPtr() = the object, destination = the group.
        Called from SetClass after the object's containing-set is updated,
        because EnteredSet reads GetContainingSet().GetName() off the object.
        The warp-transit set is NOT suppressed here (see plan Task 11)."""
        name = obj.GetName() if hasattr(obj, "GetName") else None
        if not name:
            return
        import App
        flag = cls.ENTERED_SET if entered else cls.EXITED_SET
        et = (App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET if entered
              else App.ET_OBJECT_GROUP_OBJECT_EXITED_SET)
        for group in list(cls._live):
            if name not in group._names:
                continue
            if flag not in group._event_flags.get(name, ()):
                continue
            evt = App.TGObjPtrEvent_Create()
            evt.SetEventType(et)
            evt.SetObjPtr(obj)
            evt.SetSource(obj)
            evt.SetDestination(group)
            App.g_kEventManager.AddEvent(evt)
```

(`import weakref` at the top of `objects.py` if absent.) Also make the **single-arg** `SetEventFlag(flag)` apply to names added later: store a group-level default in `self._default_flags: set[int]` and have `AddName` seed `self._event_flags[name]` with it — otherwise `ConditionExists.SetTarget`'s `RemoveAllNames(); AddName(sTarget)` (`ConditionExists.py:62-64`) drops the flag and the re-armed condition never hears its target arrive. `RemoveAllNames` clears per-name flags but keeps `_default_flags`.

`engine/appc/sets.py` — in `AddObjectToSet`, immediately after the existing `_broadcast_set_transition(obj, entered=True)` call (find it below the block shown at `:181-200`):

```python
        from engine.appc.objects import ObjectGroup
        ObjectGroup.broadcast_membership(obj, entered=True)
```

In both `RemoveObjectFromSet` and `DeleteObjectFromSet`, after `self._broadcast_set_transition(obj, entered=False)`:

```python
            from engine.appc.objects import ObjectGroup
            ObjectGroup.broadcast_membership(obj, entered=False)
```

- [ ] **Step 4: Run the unit test**

Run: `uv run pytest tests/unit/test_object_group_membership_events.py tests/unit/test_condition_exists.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Write the failing integration test with the real condition**

```python
# tests/integration/test_condition_all_in_same_set_live.py
"""ConditionAllInSameSet must follow ships between sets with NO hand-posted
events — the engine's own set add/remove must drive it. Before spec #4 it
froze at its construction value."""
import pytest

import App
from engine.appc.ai import ConditionScript_Create
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


def _set(name):
    s = App.SetClass_Create(); s.SetName(name); App.g_kSetManager._sets[name] = s
    return s


def _ship():
    s = ShipClass(); s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    return s


def test_all_in_same_set_tracks_a_ship_leaving_and_returning():
    a, b = _set("A"), _set("B")
    s1, s2 = _ship(), _ship()
    a.AddObjectToSet(s1, "One"); a.AddObjectToSet(s2, "Two")

    cond = ConditionScript_Create("Conditions.ConditionAllInSameSet",
                                  "ConditionAllInSameSet", "One", "Two")
    cond.SetActive()
    assert cond._instance is not None, cond._init_error
    assert cond.GetStatus() == 1

    a.RemoveObjectFromSet("Two"); b.AddObjectToSet(s2, "Two")
    assert cond.GetStatus() == 0, "ship moved to another set but the condition never heard"

    b.RemoveObjectFromSet("Two"); a.AddObjectToSet(s2, "Two")
    assert cond.GetStatus() == 1, "ship came back but the condition never re-evaluated"
```

- [ ] **Step 6: Run it, then prove sensitivity**

Run: `uv run pytest tests/integration/test_condition_all_in_same_set_live.py -q -p no:cacheprovider` — Expected: pass.
Then comment out the two-line `broadcast_membership` call in `sets.py:AddObjectToSet`, rerun — Expected: FAIL at the third assertion. Restore by editing; `git diff engine/appc/sets.py` must show only the intended additions.

- [ ] **Step 7: Full AI subset + commit**

Run: `uv run pytest tests/unit/test_ai_*.py tests/unit/test_condition_*.py tests/unit/test_object_group*.py tests/integration/test_condition_*.py tests/integration/test_fed_attack_smoke.py tests/integration/test_non_fed_attack_smoke.py tests/integration/test_follow_through_warp_plainai_smoke.py -q -p no:cacheprovider`

```bash
git add engine/appc/objects.py engine/appc/sets.py tests/unit/test_object_group_membership_events.py tests/integration/test_condition_all_in_same_set_live.py
git commit -m "feat(events): ObjectGroup ENTERED/EXITED_SET are emitted on set add/remove

13 SDK subscriber files, none ever fired. ConditionAllInSameSet (25 mission
AIs) and AnyInSameSet were frozen at construction; seven more conditions
lost their late-spawn re-arm.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: `ET_DELETE_OBJECT_PUBLIC` emitter (spec #5)

**Files:**
- Modify: `engine/appc/objects.py` (module-level `broadcast_object_deleted`)
- Modify: `engine/appc/sets.py:249-256` (`DeleteObjectFromSet`), `engine/appc/ship_death.py:189-200` (`_remove`), `engine/host_loop.py:5105-5116` (the `_delete_me` sweep)
- Test: `tests/unit/test_delete_object_public_event.py`

**Interfaces:**
- Produces: `objects.broadcast_object_deleted(obj) -> None` — posts a `TGEvent` of type `ET_DELETE_OBJECT_PUBLIC` with source = destination = `obj`. Called exactly at the three places an object leaves the world for good (explicit `DeleteObjectFromSet`, end of the death linger, the `SetDeleteMe` sweep). **Not** from `RemoveObjectFromSet`, which is also how warp moves a ship between sets.
- Consumers register with `target = pObject` (`ConditionExists.py:39,89`; `ConditionInNebula.ObjectDeleted`; `ConditionInRange.ProxDeleted`; `MissionLib.py:2488`), so destination must be the object; `tests/unit/test_condition_exists.py:63-79` already posts this shape by hand.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_delete_object_public_event.py
"""ET_DELETE_OBJECT_PUBLIC — spec #5. Only constants_generated.py:345 and a
docstring mentioned it; 14 SDK files subscribe. ConditionExists never
returned to 0 after its target died."""
import pytest

import App
from engine.appc import ship_death
from engine.appc.ai import ConditionScript_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    ship_death.reset()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _scene():
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ship, "Bart")
    cond = ConditionScript_Create("Conditions.ConditionExists", "ConditionExists", "Bart")
    cond.SetActive()
    assert cond.GetStatus() == 1
    return pSet, ship, cond


def test_delete_object_from_set_drops_condition_exists():
    pSet, ship, cond = _scene()
    pSet.DeleteObjectFromSet("Bart")
    assert cond.GetStatus() == 0


def test_end_of_death_linger_drops_condition_exists():
    pSet, ship, cond = _scene()
    ship_death._remove(ship)
    assert cond.GetStatus() == 0


def test_delete_me_sweep_drops_condition_exists():
    from engine import host_loop
    pSet, ship, cond = _scene()
    ship.SetDeleteMe(1)
    host_loop._sweep_delete_me_objects()
    assert cond.GetStatus() == 0


def test_a_plain_set_move_is_not_a_delete():
    pSet, ship, cond = _scene()
    other = App.SetClass_Create(); other.SetName("T"); App.g_kSetManager._sets["T"] = other
    pSet.RemoveObjectFromSet("Bart"); other.AddObjectToSet(ship, "Bart")
    assert cond.GetStatus() == 1
```

Read `engine/host_loop.py:5095-5116` for the real name of the sweep function (the test calls it `_sweep_delete_me_objects`; use the real one). If it is a closure that cannot be called from a test, lift the loop body into a module-level function with that name and call it from the original site.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_delete_object_public_event.py -q -p no:cacheprovider`
Expected: first three FAIL with status 1.

- [ ] **Step 3: Implement**

`engine/appc/objects.py` (module level, near `ObjectClass_Cast`):

```python
def broadcast_object_deleted(obj) -> None:
    """Post ET_DELETE_OBJECT_PUBLIC (source == destination == obj) — BC's
    "this object is leaving the world" notice. 14 SDK files subscribe with
    target = the object (ConditionExists.py:39, MissionLib.py:2488).
    Call ONLY where an object is actually destroyed: an explicit
    DeleteObjectFromSet, the end of ship_death's linger, and the SetDeleteMe
    sweep. RemoveObjectFromSet is also how warp MOVES a ship between sets,
    so it must not post this."""
    import App
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_DELETE_OBJECT_PUBLIC)
    evt.SetSource(obj)
    evt.SetDestination(obj)
    App.g_kEventManager.AddEvent(evt)
```

`sets.py` `DeleteObjectFromSet`: after the `_broadcast_set_transition`/`broadcast_membership` calls and before the pop, `broadcast_object_deleted(obj)` (local import).
`ship_death._remove`: call `broadcast_object_deleted(ship)` **before** `pSet.RemoveObjectFromSet(...)`, inside the same `try`.
`host_loop` sweep: call `broadcast_object_deleted(obj)` for each doomed object before `pSet.RemoveObjectFromSet(name)`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_delete_object_public_event.py tests/unit/test_condition_exists.py tests/unit/test_ship_death*.py tests/integration/test_follow_through_warp_plainai_smoke.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/objects.py engine/appc/sets.py engine/appc/ship_death.py engine/host_loop.py tests/unit/test_delete_object_public_event.py
git commit -m "feat(events): ET_DELETE_OBJECT_PUBLIC is emitted when an object leaves the world

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: A playing `WarpSequence` is attached to its ship's warp engine (spec #8)

**Files:**
- Modify: `engine/appc/warp.py:636-668` (`WarpSequence`: `Play`, `Completed`)
- Test: `tests/unit/test_warp_sequence_attaches_to_engine.py`

**Interfaces:**
- Produces: while a `WarpSequence` is playing, `ship.GetWarpEngineSubsystem().GetWarpSequence()` returns it (via the existing `SetWarpSequence`, which posts `ET_SET_WARP_SEQUENCE`); on completion it is cleared to `None` (posting the event again, so `ConditionWarpingToSet.SequenceSet` re-reads and turns off). Stated assumption: BC clears the sequence on arrival — a condition that stayed "warping to X" after arriving at X would be useless to the nine E5M4 Orbit/Patrol AIs that consume it.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_warp_sequence_attaches_to_engine.py
"""WarpEngineSubsystem.SetWarpSequence had NO production caller (spec #8):
WarpSequence_Create(...).Play() never attached itself, so GetWarpSequence()
was None for every ship and ConditionWarpingToSet read FALSE forever. The
ET_SET_WARP_SEQUENCE emitter closed 2026-09-02 was real but unreachable."""
import pytest

import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, WarpEngineSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _ship_in_set():
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    ship._warp_engine_subsystem = WarpEngineSubsystem("WES")
    pSet.AddObjectToSet(ship, "Ours")
    return ship


def test_play_attaches_and_completed_detaches():
    ship = _ship_in_set()
    seq = App.WarpSequence_Create(ship, "S", 0.0, "Player Start")
    assert ship.GetWarpEngineSubsystem().GetWarpSequence() is None
    seq.Play()
    assert ship.GetWarpEngineSubsystem().GetWarpSequence() is seq
    seq.Completed()
    assert ship.GetWarpEngineSubsystem().GetWarpSequence() is None


def test_condition_warping_to_set_follows_the_real_warp_lifecycle():
    ship = _ship_in_set()
    cond = ConditionScript_Create("Conditions.ConditionWarpingToSet",
                                  "ConditionWarpingToSet", "Ours", "S")
    cond.SetActive()
    assert cond._instance is not None, cond._init_error
    assert cond.GetStatus() == 0
    seq = App.WarpSequence_Create(ship, "S", 0.0, "Player Start")
    seq.Play()
    assert cond.GetStatus() == 1, "warp started but the condition never heard ET_SET_WARP_SEQUENCE"
    seq.Completed()
    assert cond.GetStatus() == 0, "warp finished but the condition still reads warping"


def test_a_ship_with_no_warp_engine_still_warps():
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ship, "Ours")
    seq = App.WarpSequence_Create(ship, "S", 0.0, "Player Start")
    seq.Play()          # must not raise
    seq.Completed()
```

Read `Conditions/ConditionWarpingToSet.py` `__init__` for the argument order (ship name, destination set name) and adjust.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_warp_sequence_attaches_to_engine.py -q -p no:cacheprovider`
Expected: first two FAIL.

- [ ] **Step 3: Implement**

In `WarpSequence` (`warp.py:636`):

```python
    def _warp_engine(self):
        ship = self._ship
        get = getattr(ship, "GetWarpEngineSubsystem", None)
        return get() if callable(get) else None

    def Play(self) -> None:
        # Attach BEFORE the actions start so a ConditionWarpingToSet created
        # mid-warp (SetupInitialState reads GetWarpSequence) sees us, and so
        # SetWarpSequence's ET_SET_WARP_SEQUENCE ping reaches the ones that
        # already exist. spec #8: nothing called SetWarpSequence in production.
        engine = self._warp_engine()
        if engine is not None:
            engine.SetWarpSequence(self)
        super().Play()

    def Completed(self) -> None:
        super().Completed()
        engine = self._warp_engine()
        if engine is not None and engine.GetWarpSequence() is self:
            # Stated assumption: BC clears the sequence on arrival. The same
            # ping fires, so the condition re-reads None and turns off.
            engine.SetWarpSequence(None)
```

Check `TGSequence.Completed` (`actions.py:456`) unregisters the id — call order above keeps that behaviour.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_warp_sequence_attaches_to_engine.py tests/unit/test_condition_warping_to_mission.py tests/unit/test_tier_a_event_emitters.py tests/unit/test_warp*.py tests/integration/test_warp*.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp.py tests/unit/test_warp_sequence_attaches_to_engine.py
git commit -m "feat(warp): a playing WarpSequence is attached to the warp engine — ConditionWarpingToSet is live

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: SelectTarget event hooks (spec #14)

**Files:**
- Modify: `engine/appc/ai_driver.py:1337-1387` (`_ensure_select_target_initialized`)
- Test: `tests/unit/test_select_target_event_hooks.py`

**Interfaces:**
- Consumes: Task 11's group events (`TargetEnteredSet` handler registers on `ET_OBJECT_GROUP_OBJECT_ENTERED_SET` with target = `pTargetGroup`) and the existing `ET_ENTERED_SET` (`sets.py:283`, destination = ship) and `ET_DECLOAK_BEGINNING` (grep its emitter in `engine/appc/subsystems.py` / `cloak*.py` before writing the test; the SDK handler `ObjectDecloaked` reads `pEvent.GetDestination()` as the decloaking object).
- Produces: the four SDK handlers `TargetEnteredSet`, `OurShipEnteredSet`, `ObjectDecloaked`, `TargetListChanged` are registered exactly as the commented-out SDK block at `Preprocessors.py:1094-1157` shows, minus `GROUP_CHANGED` (out of scope per Task 11). Each just calls `pCodeAI.ForceUpdate()` (`Preprocessors.py:1277-1302`), which resets `_next_update_time` so the next tick re-selects.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_select_target_event_hooks.py
"""SelectTarget's native-era event hooks (spec #14). BC's C++ CodeAISet
registered them; the Python copy is commented out (Preprocessors.py:1094-
1157). Without them a new target entering the set waited up to the 5 s
cadence before SelectTarget noticed."""
import pytest

import App
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.objects import ObjectGroup
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


def _ship(pSet, name, y=0.0):
    s = ShipClass(); s.SetTranslateXYZ(0, y, 0)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(s, name)
    return s


def _select_target_node(ours, group):
    import AI.Preprocessors
    node = PreprocessingAI_Create(ours, "Select")
    node.SetPreprocessingMethod(AI.Preprocessors.SelectTarget(group), "Update")
    stay = PlainAI_Create(ours, "Stay"); stay.SetScriptModule("Stay")
    node.SetContainedAI(stay)
    ours.SetAI(node)
    return node


def test_target_entering_the_set_forces_an_early_reselect():
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ours = _ship(pSet, "Ours")
    grp = ObjectGroup(); grp.AddName("Late")
    node = _select_target_node(ours, grp)
    tick_ai(node, 0.0); tick_ai(node, 1.0 / 60)        # cadence settles on tick 2
    assert node._next_update_time > 1.0, "precondition: SelectTarget is sleeping on its 5 s cadence"
    assert ours.GetTarget() is None

    _ship(pSet, "Late", y=600.0)                        # the target arrives
    assert node._next_update_time == 0.0, "TargetEnteredSet never called ForceUpdate"
    tick_ai(node, 2.0 / 60)
    assert ours.GetTarget() is not None and ours.GetTarget().GetName() == "Late"


def test_our_ship_entering_a_set_forces_an_early_reselect():
    a = App.SetClass_Create(); a.SetName("A"); App.g_kSetManager._sets["A"] = a
    b = App.SetClass_Create(); b.SetName("B"); App.g_kSetManager._sets["B"] = b
    ours = _ship(a, "Ours")
    grp = ObjectGroup(); grp.AddName("Enemy")
    node = _select_target_node(ours, grp)
    tick_ai(node, 0.0); tick_ai(node, 1.0 / 60)
    assert node._next_update_time > 1.0
    a.RemoveObjectFromSet("Ours"); b.AddObjectToSet(ours, "Ours")
    assert node._next_update_time == 0.0, "OurShipEnteredSet never called ForceUpdate"
```

Confirm `SelectTarget.__init__(self, pTargetGroup, ...)` in the SDK, and that `ForceUpdate` resets `_next_update_time` to `0.0` (`ai.py:591`). Read the cadence note in memory `project_forceupdate_and_preprocessor_cadence`: the sleep settles on the **second** tick.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_select_target_event_hooks.py -q -p no:cacheprovider`
Expected: FAIL at the `_next_update_time == 0.0` assertions.

- [ ] **Step 3: Implement**

In `_ensure_select_target_initialized`, after the existing `ET_WEAPON_HIT` registration:

```python
    # The native CodeAISet's other registrations (SDK Preprocessors.py:1094-
    # 1157, commented out there because the native node did this work). Each
    # handler just ForceUpdate()s so the next tick re-selects instead of
    # waiting out the 5 s cadence. GROUP_CHANGED is not registered: no engine
    # producer (see plan Task 11).
    group = getattr(inst, "pTargetGroup", None)
    if group is not None and callable(getattr(inst, "TargetEnteredSet", None)):
        group.SetEventFlag(App.ObjectGroup.ENTERED_SET)
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET, inst.pEventHandler, "TargetEnteredSet", group)
    if callable(getattr(inst, "OurShipEnteredSet", None)):
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_ENTERED_SET, inst.pEventHandler, "OurShipEnteredSet", pShip)
    if callable(getattr(inst, "ObjectDecloaked", None)):
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_DECLOAK_BEGINNING, inst.pEventHandler, "ObjectDecloaked", None)
```

`ObjectDecloaked` filters on `pTargetGroup.IsNameInGroup(destination name)` itself, so the broadcast target is `None` (any destination). Verify `AddBroadcastPythonMethodHandler` accepts `None` as "no target filter" (`events.py:737`); if it requires an object, read how `_method_handlers` filters (`events.py:806-810`: `target is not None and ... is not target`) — `None` already means unfiltered.

Also remove these handlers where the `ET_WEAPON_HIT` one is removed on node teardown — grep `RemoveBroadcastHandler` in `ai_driver.py`/`ai.py` for the existing teardown site and mirror it; if there is none for `ET_WEAPON_HIT` either, leave a one-line comment noting both share that gap.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_select_target_event_hooks.py tests/unit/test_select_target_*.py tests/unit/test_ai_acquires_close_cloaked.py tests/unit/test_dormant_priority*.py tests/integration/test_fed_attack_smoke.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai_driver.py tests/unit/test_select_target_event_hooks.py
git commit -m "feat(ai): SelectTarget re-selects on target arrival, our arrival, and decloak

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 15: AI teardown when a ship dies (spec #15)

**Files:**
- Modify: `engine/appc/ship_death.py:179-200` (`_mark_dead` or `_remove`)
- Test: `tests/unit/test_ai_teardown_on_death.py`

**Interfaces:**
- Consumes: `ShipClass._deactivate_ai_tree(ai)` (`ships.py:166-232`, dispatches `LostFocus` down the tree and clears activation/focus latches).
- Produces: at `_mark_dead`, the dead ship's tree gets `LostFocus` and is detached (`ship._ai = None`) **without** `ET_AI_DONE`. Stated assumption: `ET_AI_DONE` announces a tree that *finished*; a dead ship's tree did not finish, and missions gate beats on that event (`ConditionPlayerOrbitting` reads it), so posting it on death could fire a beat early. Use the tree-deactivation half of `ClearAI` only.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ai_teardown_on_death.py
"""A dead ship's AI tree must get LostFocus and be detached (spec #15).
Nothing outside ships.py touched the AI slot, so a destroyed ship's Warp
leaf never ran LostFocus (which re-enables collisions) and its tree stayed
installed on a hulk."""
import pytest

import App
from engine.appc import ship_death
from engine.appc.ai import PlainAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


class _Leaf:
    def __init__(self): self.lost = 0
    def Update(self): return 0
    def GotFocus(self): pass
    def LostFocus(self): self.lost += 1


def test_marking_a_ship_dead_dispatches_lost_focus_and_detaches_the_tree():
    App.g_kSetManager._sets.clear(); ship_death.reset()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ship, "Doomed")
    leaf = _Leaf()
    plain = PlainAI_Create(ship, "Leaf"); plain._script_instance = leaf
    ship.SetAI(plain)
    tick_ai(plain, 0.0)                      # gains focus
    done_events = []
    w = App.TGPythonInstanceWrapper()
    class _Rec:
        def Done(self, evt): done_events.append(evt)
    w.SetPyWrapper(_Rec())
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_AI_DONE, w, "Done", ship)

    ship_death._mark_dead(ship)

    assert leaf.lost == 1, "LostFocus never reached the leaf"
    assert ship.GetAI() is None
    assert done_events == [], "ET_AI_DONE must not be announced for a ship that died"
```

`PlainAI._script_instance` is the real attribute (`ai.py:636`). Confirm `tick_ai` on a lone PlainAI root dispatches `GotFocus` (`_flush_pending_got_focus`) so `LostFocus` has something to undo; if the leaf needs to be reached via `tick_all_ai`, build it that way.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_ai_teardown_on_death.py -q -p no:cacheprovider`
Expected: FAIL — `leaf.lost == 0`, `GetAI()` is the tree.

- [ ] **Step 3: Implement**

In `ship_death._mark_dead`, before the `ET_OBJECT_DESTROYED` broadcast:

```python
    # Tear the AI down the way ClearAI does — LostFocus down the tree (Warp's
    # re-enables collisions, FireScript's stops firing) and detach — but
    # WITHOUT ET_AI_DONE: that event means "the tree finished", and missions
    # gate beats on it. A ship that died did not finish its orders.
    ai = ship.__dict__.get("_ai")
    if ai is not None:
        try:
            ship._deactivate_ai_tree(ai)
        except Exception as _e:
            dev_mode.log_swallowed("deactivate AI tree on death", _e)
        ship._ai = None
        ship._insystem_warp_transit = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_ai_teardown_on_death.py tests/unit/test_ship_death*.py tests/unit/test_ai_done_event.py tests/integration/test_fed_attack_smoke.py -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ship_death.py tests/unit/test_ai_teardown_on_death.py
git commit -m "fix(ai): a dying ship's AI tree gets LostFocus and is detached, without ET_AI_DONE

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 16: Close-out — docs, heatmap marks, gate

**Files:**
- Modify: `docs/engine/npc-ai-contract-review-2026-09-19.md` (§2 table: mark each row ✅ with the commit), `docs/engine/aieditor-ai-surface-and-gaps.md` (§3 row citing `_ensure_fire_script_initialized`; §4 "34" → 33; add a pointer to the review), `docs/engine/event-emitter-gaps.md` (#12: note the attach landed in Task 13), `docs/stub_heatmap.md` (`markedResolvedOn` cells only — the file is regenerated, add no prose), `engine/appc/collision_avoidance.py:19-30` (docstring: `tick_collision_avoidance` has no engine caller; the AI-side path is `course_override_for`).
- Test: the gate.

- [ ] **Step 1: Mark the heatmap rows resolved**

In `docs/stub_heatmap.md`, type `2026-09-19` into the `markedResolvedOn` cell of rows: 1, 2, 3, 6, 11, 12, 13, 14 (`TGPoint3_GetRandomUnitVector*`), 7, 8, 9, 10, 61 (`PhaserBank_Cast*`), 83–88 (`PulseWeaponProperty_Cast*`), 115, 116, 167 (`WeaponSystem_Cast*`), 122, 130 (`TGCondition_Cast*`). Also 71, 89, 90 (`WarpSequence_Cast*`, resolved 2026-08-11) and 91 (`Torpedo_Cast().GetObjID`, resolved 2026-08-09) with their real dates.

- [ ] **Step 2: Edit the three docs as listed in Files**

Each ✅ in the review's §2 table gets the short commit hash from `git log --oneline -16`.

- [ ] **Step 3: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exits 0; any failure it names that is not in `tests/known_failures.txt` is a regression from this plan — fix it in the task that introduced it before continuing. Paste the summary line into the commit message.

- [ ] **Step 4: Run the docs consistency tests**

Run: `uv run pytest tests/docs -q -p no:cacheprovider`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add docs/engine/npc-ai-contract-review-2026-09-19.md docs/engine/aieditor-ai-surface-and-gaps.md docs/engine/event-emitter-gaps.md docs/stub_heatmap.md engine/appc/collision_avoidance.py
git commit -m "docs(ai): close out the 2026-09-19 NPC AI contract review

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Out of scope, deliberately

- `ET_OBJECT_GROUP_CHANGED` (trigger semantics not established).
- The native `ManagePower` behaviour (`ai_optimized.py:120` TODO), `ForceDormantStatus`/`ForceStatusChange`, `GetCombinedConditionPercentage` child aggregation, `IsHittableFromLocation`, `SetAcceleration`, `HasBuildingAIs` — placeholders recorded in the review that no shipped doctrine trips on today.
- `FollowThroughWarp`'s cross-set path (`SetClass.GetRegionModule`, `WarpSequence.GetDestinationSet`, the Python-2 string `raise`) — one SDK site, needs its own design.
- `Defend.py:18 GetConditionScript` — an SDK bug that is not SWIG-bound in BC either; Task 8 makes it non-fatal.
- Live verification. Every gap here is headless-provable, but spec #1's `Warp`-with-obstacle and `AvoidObstacles` scoring changes NPC *feel* and should get a live pass under `--developer` with `DAUNTLESS_MISSION=engine.dev_missions.combat_stress` before being called done.
