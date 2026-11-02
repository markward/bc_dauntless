# Launches at the boundary, K1's walk check out of the kernel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** K1 never needs Python inside its computation: launches become logged writes plus a queued `SPAWN` delivered at the tick boundary, and the walk check becomes per-session C++ sets built and re-validated in the binding.

**Architecture:** The binding scans at K1 session begin (K0's caches) and re-validates before each `next()`; the kernel looks up sets. For a tube, dumb or pulse FIRE the kernel computes the fire-time spawn values, logs the launcher writes, and appends `SPAWN` ahead of the already-queued launch events; delivery runs the shared Python spawn path with those values.

**Tech Stack:** C++17 combat library and pybind11 bindings, Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-combat-launch-deferral-design.md`. Maps: `docs/reference/engine/native-combat/launch-map.md` (LM), `docs/reference/engine/native-combat/k1-walk-check-map.md` (WM).

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/combat-launch-cache`.
- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF; switch off byte-identical (the factored spawn path must give the same results as today).
- Game state bit-exact (`.hex()`) vs the Python reference, switch on; queued kinds compared per tick in order.
- Focused tests only (the files each task names). Never whole suites, never `scripts/check_tests.sh`.
- Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths; `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Build `cmake --build build -j`; never reconfigure cmake or change BUILD_TYPE; never cmake inside `native/`. C++ tests: `ctest --test-dir build -R "combat_|EffectQueue"`.
- Never launch the game. No `game`/`sdk` path segments in code. Never write lifted/decompiled mod text; never commit a mod-derived value in a test.
- Mutation proofs: `cp` backup, mutate, run, `cp` restore, `diff` clean. No subagents.

## Review Focus

1. A torpedo fired by a ship that a tractor moves later in the same step: it spawns where it was fired (fire-time pose), not where the ship is at delivery.
2. A tube with finite ammo firing its last round: the ammo debit, `_num_ready` and the cooldown writes match Python exactly, and `ET_TORPEDO_AMMO_CONSUMED` (player only) still follows the spawn.
3. A K1 method patched on an instance by Python that runs mid-pump (an ASK answer): a later walk in the same tick obeys it (hands back), as today.
4. A projectile module that cannot be resolved, or a type whose launch speed is not cached yet: handed back as a FIRE record and run in Python, never guessed.
5. A launch whose target dies, or is freed, before delivery: the spawn still happens with the fire-time target values; `Torpedo` target handling matches what Python does for a dead target at registration.

---

### Task 1: K1's walk check out of the kernel

**Files:** `native/src/host/host_bindings.cc` (`k1_walk_check`, `combat_k1_begin_pump`/`_system`, `combat_k1_next`), `native/src/combat/include/dauntless/combat/k1_fire_control.h`, `native/src/combat/src/k1_fire_control.cc`, `engine/appc/native_combat.py` (`k1_pump`, `k1_system`, the begin calls); tests `tests/unit/test_native_k1_dispatch.py`, `native/tests/combat/k1_fire_control_test.cc`, `tests/integration/test_native_k1_differential.py`, `tests/unit/test_native_k1_holds_gil.py` (unchanged: the lock is still held).

**Interfaces:** Produces: per-session `sys_set`/`ship_set` (handles) built in the binding at begin, re-validated at the top of `combat_k1_next` before the kernel compute; the kernel's check is a set lookup (the C++ `K1WalkCheck` hook may stay for tests). Uses K0's object cache (type, dict, `ma_version_tag`) and type cache (`tp_version_tag`).

- [ ] **Step 1:** New tests: a mid-pump instance patch from an ASK answer is obeyed by a later walk in the same tick (ON == OFF); nested K1 sessions keep separate sets; unbuilt dicts are handed back and stay unbuilt; the name tuples changing drop the caches; every WM §4.4 pin still passes. Run → the new ones FAIL.
- [ ] **Step 2:** Implement WM §4.1 (scan at begin, re-validate before compute, set lookup), handling WM §4.3's risks (climbed-ship key, live `_children`, `__class__` swaps, non-3.11 fallback).
- [ ] **Step 3:** Run the listed files and `ctest -R combat_K1` → PASS.
- [ ] **Step 4:** Mutation: skip the re-validation → the mid-pump test fails. Restore, `diff`.
- [ ] **Step 5:** Commit.

### Task 2: Tube and dumb launches through `SPAWN`

**Files:** `engine/appc/weapon_subsystems.py` (factor `_spawn_torpedo`/`FireDumb`/`TorpedoTube._fire_effect` so the live reads become parameters; one body for reference and delivery), `engine/appc/projectiles.py` (if registration needs the fire-time values), `engine/appc/effect_queue.py` (`SPAWN` kind and delivery), `engine/appc/native_combat.py` (per-type launch-speed cache for tubes, extending P6; purity check; send the cache to the kernel), `native/src/combat/src/k1_fire_control.cc` + header (fire-time computation, launcher writes, `SPAWN` entry, hand-back reasons), `native/src/host/host_bindings.cc` (entry operands); tests `tests/unit/test_native_k1_dispatch.py`, `tests/unit/test_effect_queue.py`, `native/tests/combat/k1_fire_control_test.cc`, the K1/K3/step differentials, `tests/helpers/k3_fight.py`.

**Interfaces:** Consumes the effect queue (Tasks of the fire-events phase: `session()`, entries ride K1 records, the binding appends after writes apply). Produces: queue kind `SPAWN(launcher, kind, record...)` with the spec §4.1 fields; `_spawn_from_record(...)` (or the factored spawn function) shared by the Python reference and delivery; hand-back reasons `launch_unresolved`, `launch_uncached`, `launch_impure`.

- [ ] **Step 1:** Tests: Review Focus 1, 2, 4, 5; the event order `SPAWN` → `ENTERED_SET` → `TORPEDO_FIRED` → `WEAPON_FIRED` → `AMMO_CONSUMED`; E8M2's `SetLifetime` handler acts on the spawned torpedo; the differentials compare spawned torpedoes field by field. Purity check: a module whose `Create` branches or draws random numbers (a test-local fixture module, not a mod) is handed back. Run → FAIL.
- [ ] **Step 2:** Implement (spec §4.1).
- [ ] **Step 3:** Run the listed files and `ctest -R "combat_K1|EffectQueue"` → PASS; K1 differential tallies show tube launches native.
- [ ] **Step 4:** Mutations: read the launcher pose at delivery; drop the ammo debit write. Each fails. Restore, `diff`.
- [ ] **Step 5:** Commit.

### Task 3: Pulse launches through `SPAWN`

**Files:** as Task 2 for `PulseWeapon._fire_effect`/`_spawn_projectile` and the K1 pulse FIRE; tests as Task 2.

**Interfaces:** Consumes Task 2's `SPAWN` kind, delivery and factored spawn path. Produces: K1 returns no FIRE records in normal play.

- [ ] **Step 1:** Tests: pulse charge drain and cooldown writes match; the damage scale is applied where Python applies it (parity, spec §2 non-goal); `ET_WEAPON_FIRED` only when a bolt spawned (it now spawns at delivery: the event must follow the spawn and be skipped when the spawn produced nothing — preserve the fire-events phase's M4 behaviour); differentials. Run → FAIL.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Run → PASS; K1 differential shows no FIRE records.
- [ ] **Step 4:** Mutation: apply the damage scale twice. Fails. Restore, `diff`.
- [ ] **Step 5:** Commit.

### Task 4: Measurement and documentation (controller)

- [ ] Records per tick by kind; two benchmark runs against C-268/C-269; perf register; spec §10; roadmap (§2 table, F, I); the maps' superseded notes. Commit.
