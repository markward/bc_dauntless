# NPC Subsystem Targeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NPC weapons aim at the subsystem the AI's FireScript already chose (e.g. the warp core), instead of always firing at the target's hull centre.

**Architecture:** The real SDK `FireScript` preprocessor already computes a target subsystem every fire tick and stores it as `inst.idTargetedSubsystem`, but our engine discards it. Add one post-`Update()` hook in the AI driver's preprocessor tick that mirrors that choice onto the firing ship via `ship.SetTargetSubsystem(...)`. Both existing aim sites already read `GetTargetSubsystem()`, so they start honoring the choice with no change. No SDK edit, no aim-site rewrite.

**Tech Stack:** Python 3 (engine/appc), pytest. Pure-Python change — no C++ rebuild.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-07-npc-subsystem-targeting-design.md`.
- Change is confined to `engine/appc/ai_driver.py` + new tests. **No C++ rebuild required** (pure Python).
- The hook must be a **no-op for any non-FireScript preprocessor** and must never affect the player ship (the driver only runs it for AI-driven FireScript nodes).
- Production behavior at difficulty < 0.35 (no `ChooseSubsystemTargets`) must be unchanged: `idTargetedSubsystem` stays `None` → NPCs fall back to centre-of-hull aim.
- The dev-mode debug log must be gated by `engine.dev_mode.is_enabled()` and emit nothing in production.
- Test gate: `scripts/check_tests.sh` (builds C++, runs pytest + ctest). A failure counts as pre-existing only if it is in `tests/known_failures.txt`.
- Match the existing rotation/units/API conventions in `engine/appc`. Resolve ids via `App.TGObject_GetTGObjectPtr` + `App.ShipSubsystem_Cast` (both exist in `App.py`).

---

### Task 1: FireScript → ship target-subsystem sync hook

**Files:**
- Modify: `engine/appc/ai_driver.py` (add two module-level helpers; add module logger + `dev_mode` import; call the sync helper inside `_tick_preprocessing` right after `ai._last_preprocess_status = result`, ~line 379)
- Test: `tests/unit/test_ai_driver_subsystem_target_sync.py` (new)

**Interfaces:**
- Consumes: `PreprocessingAI`, `PreprocessingAI_Create`, `tick_ai` from `engine.appc.ai` / `engine.appc.ai_driver`; `ShipClass` from `engine.appc.ships`; `App.TGObject_GetTGObjectPtr`, `App.ShipSubsystem_Cast`; subsystem `GetParentShip()` / `_climb_to_ship()`; `ship.GetTarget()`, `ship.GetTargetSubsystem()`, `ship.SetTargetSubsystem()`.
- Produces: module-level `_sync_fire_script_target_subsystem(inst) -> None` in `engine.appc.ai_driver` (called by `_tick_preprocessing`; also directly unit-tested and reused by Task 2's integration test).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ai_driver_subsystem_target_sync.py`:

```python
"""The AI driver must mirror a FireScript preprocessor's chosen target
subsystem (inst.idTargetedSubsystem) onto the firing ship via
SetTargetSubsystem, so the aim sites that read ship.GetTargetSubsystem()
(host_loop phaser tick, weapon_subsystems torpedo launch) actually honor
the AI's choice. See docs/superpowers/specs/2026-07-07-npc-subsystem-targeting-design.md.
"""
import App
from engine.appc.ai import PreprocessingAI, PreprocessingAI_Create
from engine.appc.ai_driver import tick_ai, _sync_fire_script_target_subsystem
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ShieldSubsystem


class _FireScriptLike:
    """Minimal stand-in for the SDK FireScript: carries the lWeapons marker
    and an idTargetedSubsystem slot, and recomputes it each Update()."""
    def __init__(self, chosen_id):
        self.lWeapons = []               # FireScript marker
        self.idTargetedSubsystem = None  # lives in __dict__
        self.pCodeAI = None
        self._chosen_id = chosen_id
        self.update_calls = 0

    def Update(self, dEndTime):
        self.update_calls += 1
        self.idTargetedSubsystem = self._chosen_id
        return PreprocessingAI.PS_NORMAL


class _NotFireScript:
    """A preprocessor with no lWeapons marker — the hook must ignore it."""
    def __init__(self):
        self.pCodeAI = None

    def Update(self, dEndTime):
        return PreprocessingAI.PS_NORMAL


def _ship_with_target_and_subsystem():
    """ours (attacker) targeting target; target carries an attached shield
    subsystem. Returns (ours, target, shield)."""
    ours = ShipClass()
    target = ShipClass()
    shield = ShieldSubsystem("Shield")
    shield.SetMaxCondition(500.0)
    target.SetShieldSubsystem(shield)   # _attach_subsystem sets _parent_ship
    ours.SetTarget(target)
    return ours, target, shield


def _wire(inst, ours):
    pp = PreprocessingAI_Create(ours, "FirePP")
    inst.pCodeAI = pp
    return pp


def test_sync_pushes_chosen_subsystem_onto_ship():
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(shield.GetObjID())
    _wire(inst, ours)
    inst.idTargetedSubsystem = shield.GetObjID()
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is shield


def test_sync_pushes_none_when_no_choice():
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(None)
    _wire(inst, ours)
    inst.idTargetedSubsystem = None
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is None


def test_sync_is_noop_for_non_firescript_preprocessor():
    ours, target, shield = _ship_with_target_and_subsystem()
    ours.SetTargetSubsystem(shield)          # pre-existing value
    inst = _NotFireScript()
    _wire(inst, ours)
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is shield  # untouched


def test_sync_clears_stale_subsystem_from_other_ship():
    """idTargetedSubsystem points at a subsystem belonging to a DIFFERENT
    ship than the ship's current target → clear to None (centre aim)."""
    ours, target, shield = _ship_with_target_and_subsystem()
    other = ShipClass()
    other_shield = ShieldSubsystem("OtherShield")
    other.SetShieldSubsystem(other_shield)
    inst = _FireScriptLike(other_shield.GetObjID())
    _wire(inst, ours)
    inst.idTargetedSubsystem = other_shield.GetObjID()
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is None


def test_sync_clears_dead_or_unresolvable_id():
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(999999999)   # never-registered id
    _wire(inst, ours)
    inst.idTargetedSubsystem = 999999999
    _sync_fire_script_target_subsystem(inst)
    assert ours.GetTargetSubsystem() is None


def test_driver_calls_sync_after_update():
    """End-to-end through tick_ai: ticking the wrapper runs Update (which
    sets idTargetedSubsystem) then the driver pushes it onto the ship."""
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(shield.GetObjID())
    pp = _wire(inst, ours)
    tick_ai(pp, game_time=0.0)
    assert inst.update_calls == 1
    assert ours.GetTargetSubsystem() is shield


def test_sync_only_writes_on_change(monkeypatch):
    ours, target, shield = _ship_with_target_and_subsystem()
    inst = _FireScriptLike(shield.GetObjID())
    _wire(inst, ours)
    inst.idTargetedSubsystem = shield.GetObjID()
    calls = {"n": 0}
    real_set = ours.SetTargetSubsystem
    def counting_set(s):
        calls["n"] += 1
        real_set(s)
    monkeypatch.setattr(ours, "SetTargetSubsystem", counting_set)
    _sync_fire_script_target_subsystem(inst)   # first: writes
    _sync_fire_script_target_subsystem(inst)   # second: no change
    assert calls["n"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_ai_driver_subsystem_target_sync.py -v`
Expected: FAIL — `ImportError: cannot import name '_sync_fire_script_target_subsystem'`.

- [ ] **Step 3: Implement the helpers in `engine/appc/ai_driver.py`**

At the top of the module, add the dev_mode import alongside the existing imports (after the `import inspect` / `import random` lines):

```python
from engine import dev_mode
```

**Do NOT use `logging`** for the dev diagnostic — the host configures no logging
handler, so `logging.info(...)` is swallowed and never reaches the terminal. Use
`print()` (see Step 3), matching the visible `[viewscreen]` / `[host_loop]`
dev-diagnostic convention.

Add these two module-level functions (place them near the other `_tick_*` helpers, e.g. just above `_tick_preprocessing`):

```python
def _subsystem_belongs_to(subsystem, target) -> bool:
    """True if `subsystem` sits on `target`'s ship. In production, attached
    subsystems know their owning ship (directly via GetParentShip, or by
    climbing the parent-subsystem chain for children like torpedo tubes). A
    membership fallback covers top-level subsystems assigned without a
    parent-ship back-link."""
    owner = subsystem.GetParentShip()
    if owner is None:
        climb = getattr(subsystem, "_climb_to_ship", None)
        if callable(climb):
            owner = climb()
    if owner is target:
        return True
    try:
        return subsystem in target.GetSubsystems()
    except Exception:
        return False


def _sync_fire_script_target_subsystem(inst) -> None:
    """Mirror a FireScript preprocessor's chosen target subsystem onto its
    firing ship so the aim sites (host_loop phaser tick, weapon_subsystems
    torpedo launch) that read ship.GetTargetSubsystem() honor the AI's choice.

    No-op for any preprocessor that is not a FireScript (gated on the
    lWeapons + idTargetedSubsystem markers). Only the AI driver calls this,
    and only for AI-driven FireScript nodes, so the player is unaffected.
    See docs/superpowers/specs/2026-07-07-npc-subsystem-targeting-design.md.
    """
    # Gate: FireScript instances only. lWeapons is the FireScript marker
    # (also used by _ensure_fire_script_initialized); idTargetedSubsystem is
    # set in FireScript.__init__ so it lives in __dict__ (bypass the _Stub
    # __getattr__ that would otherwise mask a missing attr).
    if not hasattr(inst, "lWeapons"):
        return
    if "idTargetedSubsystem" not in getattr(inst, "__dict__", {}):
        return

    code_ai = getattr(inst, "pCodeAI", None)
    if code_ai is None:
        return
    ship = code_ai.GetShip()
    if ship is None or not hasattr(ship, "SetTargetSubsystem"):
        return

    import App

    chosen = None
    sub_id = inst.idTargetedSubsystem
    if sub_id is not None:
        resolved = App.ShipSubsystem_Cast(App.TGObject_GetTGObjectPtr(sub_id))
        # Accept only a live subsystem that belongs to the ship's current
        # target; a stale id (old/other target) or dead id clears back to
        # centre-of-hull aim.
        if resolved is not None:
            target = ship.GetTarget()
            if target is not None and _subsystem_belongs_to(resolved, target):
                chosen = resolved

    # Only write on change — avoids churn and drives the dev log (below) on
    # transitions rather than every fire tick.
    if ship.GetTargetSubsystem() is not chosen:
        ship.SetTargetSubsystem(chosen)
        if dev_mode.is_enabled():
            ship_name = ship.GetName() if hasattr(ship, "GetName") else "<ship>"
            sub_name = chosen.GetName() if chosen is not None else "hull centre"
            # print(), not logging: the host configures no logging handler, so
            # logging.info is swallowed and never reaches the terminal.
            print(f"[ai] {ship_name} -> targeting {sub_name}")
```

Then wire it into `_tick_preprocessing`: immediately after the line `ai._last_preprocess_status = result` (~line 379, inside the `if not ai._preprocess_done and game_time >= ai._next_update_time:` block), add:

```python
        # Bridge FireScript's chosen subsystem to the firing ship so the aim
        # sites honor it (spec 2026-07-07-npc-subsystem-targeting). No-op for
        # non-FireScript preprocessors.
        _sync_fire_script_target_subsystem(inst)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_ai_driver_subsystem_target_sync.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai_driver.py tests/unit/test_ai_driver_subsystem_target_sync.py
git commit -m "feat(ai): mirror FireScript-chosen subsystem onto firing ship"
```

---

### Task 2: Integration — real SDK FireScript picks the warp core and it lands on the ship

**Files:**
- Test: `tests/unit/test_ai_driver_subsystem_target_sync.py` (append)

**Interfaces:**
- Consumes: real `AI.Preprocessors.FireScript`; `_sync_fire_script_target_subsystem` from Task 1; `PowerSubsystem` (critical warp core) + `ShieldSubsystem` from `engine.appc.subsystems`; `App.SetClass_Create`, `App.g_kSetManager`.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/unit/test_ai_driver_subsystem_target_sync.py`:

```python
import pytest
from engine.appc.subsystems import PowerSubsystem


@pytest.fixture(autouse=True)
def _isolate_sets():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()


def _make_attacker_and_target_with_warp_core():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ours = ShipClass(); pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); pSet.AddObjectToSet(target, "Target")

    # Warp core: critical + targetable → highest FireScript rating
    # (IsCritical x6 beats the shield's type-rating of 5).
    warp_core = PowerSubsystem("Warp Core")
    warp_core.SetMaxCondition(7000.0)
    warp_core.SetCritical(1)
    warp_core.SetTargetable(1)
    target.SetPowerSubsystem(warp_core)

    shield = ShieldSubsystem("Shield")
    shield.SetMaxCondition(500.0)
    shield.SetTargetable(1)
    target.SetShieldSubsystem(shield)

    ours.SetTarget(target)
    return ours, target, warp_core


def test_real_firescript_choice_reaches_ship_target_subsystem():
    from AI.Preprocessors import FireScript
    ours, target, warp_core = _make_attacker_and_target_with_warp_core()

    inst = FireScript("Target")
    inst.bChooseSubsystemTargets = 1
    pp = PreprocessingAI_Create(ours, "FirePP")
    inst.pCodeAI = pp

    # Run the real rating path, then the driver hook.
    inst.ChooseTargetSubsystem(target)
    assert inst.idTargetedSubsystem is not None      # rating picked something
    _sync_fire_script_target_subsystem(inst)

    chosen = ours.GetTargetSubsystem()
    assert chosen is warp_core                        # critical wins
```

(`ShipClass.SetPowerSubsystem` is confirmed at `engine/appc/ships.py:743`; it attaches via `_attach_subsystem` (sets `_parent_ship`) and `_power_subsystem` is in `GetSubsystems()`.)

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_ai_driver_subsystem_target_sync.py::test_real_firescript_choice_reaches_ship_target_subsystem -v`
Expected: PASS. (If the FireScript rating picks the shield over the warp core, confirm the warp core has `SetCritical(1)` — the `IsCritical x6` term is what makes it outrank the shield's type-rating of 5.)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_ai_driver_subsystem_target_sync.py
git commit -m "test(ai): real FireScript warp-core choice reaches ship target subsystem"
```

---

### Task 3: Full gate + live verification handoff

**Files:** none (verification only)

- [ ] **Step 1: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0. If it names a failing test, confirm it is in `tests/known_failures.txt` (only the 7 headless-GL FrameTests are baselined); anything else is a regression to fix before proceeding.

- [ ] **Step 2: Present the in-game live-test checklist to the user**

This change is Python-only — **no `cmake` rebuild needed**. Give the user these steps (they run them; do not drive their workstation):

1. Launch: `./build/dauntless --developer`
2. **Configuration → Gameplay → AI Difficulty = Hard** (guarantees `ChooseSubsystemTargets`; Medium/0.5 also works).
3. Start a combat scenario with an attacking NPC (QuickBattle with an enemy ship, or a combat mission via the dev **Load Mission…** picker).
4. Launch from a terminal and watch stdout for `[ai] <ship> -> targeting <subsystem>` lines. **Expected:** NPCs report targeting high-value subsystems (weapons / shields, sometimes Warp Core / engines), not "hull centre".
5. Let a fight run to a kill. **Expected with the fix:** NPCs concentrate fire — shields drop faster than the hull and specific subsystems get disabled (weapons/engines), with occasional **warp-core breach** kills (instant destruction) — rather than slow uniform hull attrition (the pre-fix behavior). Note: the SDK rating favors weapons/shields (type-rating 5) and critical systems; the warp core is chosen only when its critical bonus wins, so don't expect warp-core-first every time.
6. Cross-check: target the NPC under fire (or check your own ship if it's shooting you) via the target-subsystem HUD / Ship Property Viewer; confirm one subsystem's condition drops markedly faster than the rest — the one named in the log.

If the log shows `hull centre` persistently at Hard difficulty, the FireScript rating isn't selecting a subsystem (difficulty/config/targetability) rather than the hook — capture the log and diagnose upstream.

- [ ] **Step 3: Update memory after live-verify**

Once the user confirms in-game, update `project_npc_subsystem_aim_gap.md` (memory) from "gap" to "FIXED + live-verified", noting the branch/commit.

---

## Self-Review

**Spec coverage:**
- Root cause / seam → Task 1 helper + wiring. ✓
- Edge cases (None, dead id, stale id, non-FireScript, no pCodeAI/ship, player untouched) → Task 1 tests + gate logic. ✓
- Dev-mode debug log on change → Task 1 Step 3 (gated by `dev_mode.is_enabled()`). ✓
- Unit tests 1–6 → Task 1. Integration test 7 (warp core) → Task 2. ✓
- Live verification → Task 3. ✓
- Out-of-scope items (cloak, NumProbes, rating heuristic) → untouched. ✓

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. The one conditional ("if `SetPowerSubsystem` doesn't exist, use the correct setter") gives an exact way to find the right name rather than leaving it vague.

**Type consistency:** `_sync_fire_script_target_subsystem(inst)` and `_subsystem_belongs_to(subsystem, target)` are used with identical signatures in the helper, the driver wiring, and both test files. `idTargetedSubsystem` is an object id (SDK `Preprocessors.py:943` sets `GetObjID()`); resolved via `App.TGObject_GetTGObjectPtr` + `App.ShipSubsystem_Cast`, both defined in `App.py`. `ship.GetTargetSubsystem/SetTargetSubsystem/GetTarget` confirmed on `ShipClass`.
