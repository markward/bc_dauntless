# Hull-Hit Smoke (SDK-Faithful) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the non-faithful subsystem-damage smoke plume system and replace it with a stock-faithful hull-hit smoke puff emitted at the weapon impact point.

**Architecture:** Delete the `subsystem_emitters` plume state machine and its `ParticleBackend` adapter (the parts that produced a sustained, ship-centred cloud), keeping the reusable SDK particle pipeline in `particles.py`. Add a small `hull_hit_smoke.maybe_emit(...)` that reproduces `Effects.py`'s `TorpedoHullHit`/`PhaserHullHit` smoke (probabilistic, detail-gated, at the impact point) and call it from the existing HULL/CRITICAL branch of `hit_feedback.dispatch`.

**Tech Stack:** Python (engine/appc), pytest. No C++/native change. Reuses the existing `particles.py` → `particle_pass.cc` render path.

## Global Constraints

- **SDK fidelity:** all smoke constants are copied verbatim from `sdk/Build/scripts/Effects.py` — do NOT re-tune: `fVelocity=0.2`, `fSize=0.3`, `fLife=2.0 + GetRandomNumber(30)/10.0`, torpedo roll `GetRandomNumber(10) < 2` (20%), phaser roll `GetRandomNumber(10) < 3` (30%), detail gate `EffectController_GetEffectLevel() >= MEDIUM`.
- **RNG:** use `App.g_kSystemWrapper.GetRandomNumber(N)` (returns `0..N-1`) for every roll, matching SDK semantics.
- **No native change:** `particle_pass.cc`, `host_bindings.cc`, and shaders are untouched.
- **Test gate:** `scripts/check_tests.sh` (pytest + ctest, diffed against `tests/known_failures.txt`) must pass with no new failures. `scripts/run_tests.sh` is pytest-only — not sufficient.
- **Shared checkout:** commit with explicit pathspecs; never `git add -A`.
- **Column-vector rotation convention** applies to any body/world math (`world_to_body` already handles it).

---

### Task 1: Remove the non-faithful subsystem-plume system

Delete the plume state machine, its backend adapter, its host-loop wiring, and its tests. Nothing replaces it in this task; the faithful smoke lands in Tasks 2–3.

**Files:**
- Delete: `engine/appc/subsystem_emitters.py`
- Modify: `engine/appc/particles.py` (remove `ParticleBackend` + `_ControllerHandle`)
- Modify: `engine/host_loop.py:65` (import), `:567` (pump call), `:1880-1884` (backend install), `:3588-3589` (reset)
- Modify: `tests/unit/test_torpedo_advance.py:76` (stale comment only)
- Modify: `tests/integration/test_particles_host_loop.py` (drop the one plume test)
- Delete: `tests/unit/test_subsystem_emitters_anchor.py`, `_backend.py`, `_budget.py`, `_persistence.py`, `_registry.py`, `_tiering.py`, `_transitions.py`
- Delete: `tests/unit/test_particle_backend.py`
- Delete: `tests/integration/test_host_loop_subsystem_plumes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a clean `particles.py` that still exports `AnimTSParticleController(_Create)`, `EffectAction_Create`, `register`/`deregister`, `advance`, `reset`, `snapshot_descriptors`, `active_count`, `EffectController`, `EffectController_GetEffectLevel`. These remain for Tasks 2–3 and the existing render path.

- [ ] **Step 1: Confirm the current gate baseline is green**

Run: `scripts/check_tests.sh`
Expected: PASS (only the 7 baselined headless-GL `FrameTest`s in `tests/known_failures.txt`). If anything else fails, STOP — it predates this work.

- [ ] **Step 2: Delete the plume module and its tests**

```bash
git rm engine/appc/subsystem_emitters.py \
       tests/unit/test_subsystem_emitters_anchor.py \
       tests/unit/test_subsystem_emitters_backend.py \
       tests/unit/test_subsystem_emitters_budget.py \
       tests/unit/test_subsystem_emitters_persistence.py \
       tests/unit/test_subsystem_emitters_registry.py \
       tests/unit/test_subsystem_emitters_tiering.py \
       tests/unit/test_subsystem_emitters_transitions.py \
       tests/unit/test_particle_backend.py \
       tests/integration/test_host_loop_subsystem_plumes.py
```

- [ ] **Step 3: Remove `ParticleBackend` and `_ControllerHandle` from `particles.py`**

Delete the entire `_ControllerHandle` class (starts `class _ControllerHandle:` ~line 370) and the entire `ParticleBackend` class (starts `class ParticleBackend:` ~line 382, through its `fire_one_shot` method). `ParticleBackend.create` is the only place `particles.py` imports `subsystem_emitters` (`from engine.appc import subsystem_emitters as se`), so removing it also removes that dependency. Leave everything else in the file untouched.

Verify no dangling reference remains:

Run: `grep -n 'ParticleBackend\|_ControllerHandle\|subsystem_emitters' engine/appc/particles.py`
Expected: no output.

- [ ] **Step 4: Unwire the plume from `host_loop.py`**

Remove `subsystem_emitters,` from the `from engine.appc import (...)` block (line 65).

Remove the pump call (line ~567):
```python
    subsystem_emitters.pump(ships_list, None, dt)
```

Remove the backend-install block (lines ~1879–1884), the whole comment + three statements:
```python
# Install the real particle backend so Spec B plume state machine drives
# actual SDK smoke controllers.  set_backend() only stores the reference and
# sets _manager = None — no simulation side-effects at import time.
from engine.appc import subsystem_emitters as _se_for_backend
from engine.appc import particles as _particles_for_backend
_se_for_backend.set_backend(_particles_for_backend.ParticleBackend())
```

Remove the reset lines (~3588–3589):
```python
        from engine.appc import subsystem_emitters
        subsystem_emitters.reset_manager()
```

Verify:

Run: `grep -n 'subsystem_emitters\|_se_for_backend\|_particles_for_backend\|ParticleBackend' engine/host_loop.py`
Expected: no output.

- [ ] **Step 5: Drop the plume test from `test_particles_host_loop.py`**

Delete only the `test_spec_b_plume_renders_through_particle_backend` function (it imports `subsystem_emitters` and the deleted registry helpers). Keep `test_build_particle_render_data_snapshots_active` and `test_object_exploding_registers_real_debris_sparks`.

Verify:

Run: `grep -n 'subsystem_emitters\|ParticleBackend' tests/integration/test_particles_host_loop.py`
Expected: no output.

- [ ] **Step 6: Fix the stale comment in `test_torpedo_advance.py`**

Line 76 references `subsystem_emitters._select_candidates` in a comment. Replace that comment line so it no longer names the removed module. Change:
```python
    # subsystem_emitters._select_candidates (reached via _advance_combat ->
```
to:
```python
    # combat damage attribution (reached via _advance_combat ->
```

- [ ] **Step 7: Run the full gate — confirm removal is clean**

Run: `scripts/check_tests.sh`
Expected: PASS with no failures beyond the 7 baselined `FrameTest`s. If a `test_particles_*` or host-loop test fails, a retained symbol was removed by mistake — restore it.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/subsystem_emitters.py engine/appc/particles.py engine/host_loop.py \
        tests/unit/test_subsystem_emitters_anchor.py tests/unit/test_subsystem_emitters_backend.py \
        tests/unit/test_subsystem_emitters_budget.py tests/unit/test_subsystem_emitters_persistence.py \
        tests/unit/test_subsystem_emitters_registry.py tests/unit/test_subsystem_emitters_tiering.py \
        tests/unit/test_subsystem_emitters_transitions.py tests/unit/test_particle_backend.py \
        tests/integration/test_host_loop_subsystem_plumes.py tests/integration/test_particles_host_loop.py \
        tests/unit/test_torpedo_advance.py
git commit -m "refactor(vfx): remove non-faithful subsystem-damage smoke plume system

The continuous, subsystem-state-driven, ship-centred plume was a Dauntless/mod
addition with no stock-BC basis (damaged-but-not-hit ships smoke from centre).
Deletes subsystem_emitters + its ParticleBackend adapter + tests; keeps the
reusable SDK particle pipeline in particles.py.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `hull_hit_smoke` module — faithful impact smoke

Reproduce `Effects.py`'s hull-hit smoke as a self-contained, testable unit.

**Files:**
- Create: `engine/appc/hull_hit_smoke.py`
- Test: `tests/unit/test_hull_hit_smoke.py`

**Interfaces:**
- Consumes: `particles.EffectController` / `particles.EffectController_GetEffectLevel`; `host_io.world_to_body(instance_id, world_pt3, world_n3) -> (body_pt3, body_n3) | None`; `App.g_kSystemWrapper.GetRandomNumber(n) -> int in [0,n)`; the SDK `Effects.CreateSmokeHigh(fVelocity, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo) -> EffectAction` (EffectAction has `.Start()`).
- Produces: `maybe_emit(ship, point, normal, weapon_type, ship_instances=None) -> None` where `point`/`normal` are world-space `TGPoint3` (`.x/.y/.z`) and `weapon_type` is `"torpedo"` / `"phaser"` / `None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_hull_hit_smoke.py`:

```python
import types
import pytest

from engine.appc import hull_hit_smoke, particles
from engine.appc.math import TGPoint3


class _RNG:
    """Deterministic App.g_kSystemWrapper.GetRandomNumber stand-in.
    Returns queued values in order; falls back to `default` when drained."""
    def __init__(self, values, default=0):
        self._values = list(values)
        self._default = default
        self.calls = []

    def GetRandomNumber(self, n):
        self.calls.append(n)
        return self._values.pop(0) if self._values else self._default


@pytest.fixture
def captured(monkeypatch):
    """Capture the CreateSmokeHigh call args; return a dict updated on emit."""
    box = {}

    def fake_create(fVelocity, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo):
        box.update(dict(fVelocity=fVelocity, fLife=fLife, fSize=fSize,
                        emit_from=pEmitFrom, emit_pos=kEmitPos, emit_dir=kEmitDir,
                        attach_to=pAttachTo))
        return types.SimpleNamespace(Start=lambda: box.__setitem__("started", True))

    fake_effects = types.SimpleNamespace(CreateSmokeHigh=fake_create)
    monkeypatch.setitem(__import__("sys").modules, "Effects", fake_effects)
    # Detail defaults HIGH; world_to_body returns a fixed body anchor.
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.HIGH)
    monkeypatch.setattr(hull_hit_smoke.host_io, "world_to_body",
                        lambda iid, p, n: ((0.1, 0.2, 0.3), (0.0, 0.0, 1.0)))
    return box


def _emit(rng_values, weapon, monkeypatch, ship_instances={"ship": 7}):
    rng = _RNG(rng_values)
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), TGPoint3(0.0, 1.0, 0.0),
        weapon, ship_instances=ship_instances)
    return rng


def test_torpedo_emits_below_threshold(captured, monkeypatch):
    # roll 1 < 2  -> emit ; then fLife roll 5 -> 2.0 + 0.5
    _emit([1, 5], "torpedo", monkeypatch)
    assert captured.get("started") is True
    assert captured["fVelocity"] == 0.2
    assert captured["fSize"] == 0.3
    assert captured["fLife"] == pytest.approx(2.5)
    assert captured["emit_pos"] == (0.1, 0.2, 0.3)      # body-frame anchor
    assert captured["emit_dir"] == (0.0, 0.0, 1.0)
    assert captured["emit_from"] == "ship"


def test_torpedo_silent_at_threshold(captured, monkeypatch):
    _emit([2], "torpedo", monkeypatch)                  # 2 >= 2 -> no emit
    assert "started" not in captured


def test_phaser_threshold_is_three(captured, monkeypatch):
    _emit([2, 0], "phaser", monkeypatch)                # 2 < 3 -> emit
    assert captured.get("started") is True


def test_unknown_weapon_never_emits(captured, monkeypatch):
    _emit([0], None, monkeypatch)
    assert "started" not in captured


def test_detail_below_medium_suppresses(captured, monkeypatch):
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.LOW)
    _emit([0], "torpedo", monkeypatch)
    assert "started" not in captured


def test_missing_normal_skips(captured, monkeypatch):
    rng = _RNG([0, 0])
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), None, "torpedo",
        ship_instances={"ship": 7})
    assert "started" not in captured


def test_no_instance_skips(captured, monkeypatch):
    _emit([0, 0], "torpedo", monkeypatch, ship_instances={})   # ship not mapped
    assert "started" not in captured
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_hull_hit_smoke.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: engine.appc.hull_hit_smoke`.

- [ ] **Step 3: Implement `hull_hit_smoke.py`**

Create `engine/appc/hull_hit_smoke.py`:

```python
# engine/appc/hull_hit_smoke.py
"""SDK-faithful hull-hit smoke puffs.

Reproduces stock BC's `Effects.TorpedoHullHit` / `PhaserHullHit` smoke: a small,
transient smoke puff at a weapon's hull-impact point, emitted probabilistically
and gated on graphics-detail level. This is deliberately NOT continuous,
subsystem-state-driven, or ship-centred — that was the removed
`subsystem_emitters` plume system.

Constants are copied verbatim from `sdk/Build/scripts/Effects.py`
(`CreateWeaponSmoke` -> `CreateSmokeHigh`). See
docs/superpowers/specs/2026-07-09-hull-hit-smoke-faithful-design.md.
"""
import App
from engine import host_io
from engine.appc import particles

# Stock rolls (Effects.py): torpedo 20% (rand(10) < 2), phaser 30% (rand(10) < 3).
_HULL_SMOKE_ROLL = {"torpedo": 2, "phaser": 3}


def maybe_emit(ship, point, normal, weapon_type, ship_instances=None) -> None:
    """Emit a stock-faithful hull-hit smoke puff, or do nothing.

    `point` / `normal` are world-space TGPoint3 (`.x/.y/.z`); `weapon_type` is
    "torpedo" / "phaser" / None; `ship_instances` maps ship -> renderer instance
    id. No-op unless the weapon is a torpedo/phaser, the probability roll passes,
    detail level >= MEDIUM, and the impact resolves to a body-frame hull anchor.
    """
    threshold = _HULL_SMOKE_ROLL.get(weapon_type)
    if threshold is None:
        return
    if (particles.EffectController_GetEffectLevel()
            < particles.EffectController.MEDIUM):
        return
    if normal is None:
        return
    if App.g_kSystemWrapper.GetRandomNumber(10) >= threshold:
        return
    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None:
        return
    conv = host_io.world_to_body(
        iid, (point.x, point.y, point.z), (normal.x, normal.y, normal.z))
    if conv is None:
        return
    body_point, body_normal = conv
    _emit_smoke(ship, body_point, body_normal)


def _emit_smoke(ship, body_point, body_normal) -> None:
    """Fire the SDK CreateSmokeHigh recipe (Effects.py fSize=0.3 hull puff),
    body-frame anchored and attached to the ship so the puff glues to the moving
    hull and self-expires (~10s) through the existing particle pipeline."""
    import Effects
    fLife = 2.0 + App.g_kSystemWrapper.GetRandomNumber(30) / 10.0
    action = Effects.CreateSmokeHigh(
        0.2, fLife, 0.3, ship, body_point, body_normal, ship)
    action.Start()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_hull_hit_smoke.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hull_hit_smoke.py tests/unit/test_hull_hit_smoke.py
git commit -m "feat(vfx): SDK-faithful hull-hit smoke module

Reproduces Effects.py TorpedoHullHit/PhaserHullHit smoke: probabilistic,
detail-gated smoke puff at the impact point (body-frame anchored, self-expiring).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Hook `hull_hit_smoke` into `hit_feedback.dispatch`

Fire the puff on genuine hull penetration, alongside the existing spark VFX.

**Files:**
- Modify: `engine/appc/hit_feedback.py` (HULL/CRITICAL branch, after `hit_vfx.spawn(...)`)
- Test: `tests/unit/test_hit_feedback_hull_smoke.py`

**Interfaces:**
- Consumes: `hull_hit_smoke.maybe_emit(ship, point, normal, weapon_type, ship_instances)` from Task 2.
- Produces: nothing new; `dispatch(...)` signature is unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_hit_feedback_hull_smoke.py`:

```python
import pytest

from engine.appc import hit_feedback
from engine.appc.math import TGPoint3


class _Hull:
    def GetConditionPercentage(self): return 1.0
    def IsDestroyed(self): return 0


class _Ship:
    def GetHull(self): return _Hull()


def _dispatch(monkeypatch, *, absorbed_shields, absorbed_hull, weapon_type):
    calls = []
    monkeypatch.setattr(
        "engine.appc.hull_hit_smoke.maybe_emit",
        lambda *a, **k: calls.append((a, k)))
    # Silence the other fan-out branches (audio/shake/carve) for isolation.
    monkeypatch.setattr(hit_feedback, "_play_audio", lambda *a, **k: None)
    ship = _Ship()
    hit_feedback.dispatch(
        ship=ship, source=None,
        point=TGPoint3(1.0, 2.0, 3.0), normal=TGPoint3(0.0, 1.0, 0.0),
        damage=100.0, subsystem=None,
        absorbed_shields=absorbed_shields, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        ship_instances={ship: 3}, weapon_type=weapon_type)
    return calls


def test_hull_hit_calls_smoke(monkeypatch):
    calls = _dispatch(monkeypatch, absorbed_shields=0.0,
                      absorbed_hull=50.0, weapon_type="torpedo")
    assert len(calls) == 1
    (ship, point, normal, wtype, ship_instances), _kw = calls[0]
    assert wtype == "torpedo"
    assert (point.x, point.y, point.z) == (1.0, 2.0, 3.0)


def test_shield_hit_does_not_call_smoke(monkeypatch):
    calls = _dispatch(monkeypatch, absorbed_shields=100.0,
                      absorbed_hull=0.0, weapon_type="torpedo")
    assert calls == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_hit_feedback_hull_smoke.py -v`
Expected: FAIL — `test_hull_hit_calls_smoke` asserts 1 call but `hit_feedback.dispatch` does not yet call `maybe_emit` (0 calls).

- [ ] **Step 3: Add the call in `hit_feedback.dispatch`**

In `engine/appc/hit_feedback.py`, in the `else:` (HULL or CRITICAL) branch, immediately after the existing `hit_vfx.spawn(...)` call, add:

```python
        # Stock-faithful hull-impact smoke (Effects.py TorpedoHullHit/
        # PhaserHullHit): a probabilistic, detail-gated puff at the impact
        # point. Deferred import mirrors the hit_vfx/camera_shake pattern above.
        from engine.appc import hull_hit_smoke
        hull_hit_smoke.maybe_emit(ship, point, normal, weapon_type, ship_instances)
```

(Match the indentation of the surrounding `hit_vfx.spawn(...)` block.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_hit_feedback_hull_smoke.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hit_feedback.py tests/unit/test_hit_feedback_hull_smoke.py
git commit -m "feat(vfx): fire hull-hit smoke from hit_feedback on hull penetration

Calls hull_hit_smoke.maybe_emit in the HULL/CRITICAL dispatch branch, next to
the existing spark VFX. Shield hits take the other branch, so smoke only appears
on genuine hull penetration, matching stock BC.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Full gate + live verification

**Files:** none (verification only).

**Interfaces:** none.

- [ ] **Step 1: Run the full machine gate**

Run: `scripts/check_tests.sh`
Expected: PASS with no failures beyond the 7 baselined `FrameTest`s. If a baselined test now passes, delete its line in `tests/known_failures.txt` and commit that (message: `test: drop now-passing baseline <name>`).

- [ ] **Step 2: Live-verify the fix (E6M2 clean spawn)**

Build and run the app; load E6M2 via the developer mission picker (`./build/dauntless --developer` → pause → Load Mission… → Maelstrom / Episode 6 / E6M2). Observe the player ship at spawn.
Expected: the ship renders **clean** — no giant centre smoke cloud (matches the stock reference screenshot). Damage carve textures may still be present; that is correct.

- [ ] **Step 3: Live-verify the faithful smoke appears on hull hits**

Load QuickBattle, drop the target's shields, and land phaser/torpedo hits on its hull (or have an enemy hit you with shields down).
Expected: small, transient smoke puffs appear **at the impact points** on the hull, drifting and fading after a few seconds — not a sustained centre cloud. Ramming still produces the separate (correct) hull-breach venting VFX.

- [ ] **Step 4: Record the outcome**

If verification passes, note it in the branch/PR description. If the spawn still smokes, STOP and re-open the investigation — a second emitter path exists that this plan did not cover.

---

## Self-Review

**Spec coverage:**
- Spec §4.1 (remove plume system) → Task 1 (module, `ParticleBackend`, host_loop wiring, tests). ✓
- Spec §4.2 (faithful smoke module) → Task 2. ✓
- Spec §4.3 (hook into dispatch) → Task 3. ✓
- Spec §5 (unit + faithfulness + integration + removal + verify) → Tasks 2 (unit incl. constants), 3 (integration), 1/4 (removal + gate), 4 (live verify). ✓
- Spec §6 (out of scope) → nothing built for bridge/breach; the E6M2-damaged-by-design point is verified by Task 4 Step 2. ✓

**Placeholder scan:** no TBD/TODO; every code step has full code; every command has expected output.

**Type consistency:** `maybe_emit(ship, point, normal, weapon_type, ship_instances=None)` is defined identically in Task 2 and called identically in Task 3. `EffectController.MEDIUM/LOW/HIGH` are `1/0/2` (verified). `host_io.world_to_body(iid, world_pt3, world_n3)` returns `(body_pt3, body_n3) | None` (matches its use in `hit_feedback`). `Effects.CreateSmokeHigh(fVelocity, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo)` arity matches `Effects.py`. `EffectAction.Start()` exists (verified).

**Note for the faithfulness requirement:** Task 2's `test_torpedo_emits_below_threshold` asserts the exact stock constants (`fVelocity 0.2`, `fSize 0.3`, `fLife 2.0 + rand(30)/10`), satisfying the spec's "faithfulness test" requirement inline.
