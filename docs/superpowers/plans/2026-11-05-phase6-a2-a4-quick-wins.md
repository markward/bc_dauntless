# Phase 6 A2–A4 Quick Wins — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two quick per-tick wins before the main merge:
1. Stop the native subsystem stage from re-writing unchanged values.
2. Take the cheapest high-value cuts in weapons (K0), combat glue (K1/K2/K3) and combat render data.

**Architecture:** Same as A1. State is Python-authoritative in `__dict__`, mirrored natively, pushed on write and written back by C appliers. Every change is behaviour-identical: the goldens stay byte-identical.

**Tech Stack:** C++20 (`native/src/combat`, `-ffp-contract=off`), pybind (`native/src/host/host_bindings.cc`), Python 3.11, gtest (`ctest -R combat_`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §3 (Part A: A1 is done and merged; A2 weapons, A3 combat glue, A4 combat render data) and §7. Mark, 2026-11-05: "1 and 2 now quickly, then we merge into main and do 3 [AI] in a new session."

## Global Constraints

- Branch: `ws/motion-phase6-a2` in `.claude/worktrees/native-motion`, cut from `project/native-motion-and-proximity` at `8752793b0`.
- **Never run the gate or a whole suite.** Run focused test files only, listed literally. Never hand pytest an empty or unsplit file list (zsh doesn't word-split `$VAR`).
- No destructive git. Stage with explicit paths.
- Golden fights (`tests/integration/test_golden_fights.py`, including `native_subsystems_scene`) stay byte-identical. Never set `UPDATE_COMBAT_GOLDEN`.
- Bit-exact with today's behaviour.
- Spec Part A: a stage never falls back to Python because an App method was patched.
- Build from the worktree root with `cmake --build build -j`. Combat and renderer gtests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`.
- Benchmarks run only in the measuring task, on an idle machine (cleared by Mark).

## Review Focus

1. **A field whose Python value is an int** (e.g. `0` set in `__init__`). Skipping a "bit-identical" native write must not leave an int where the native write would have stored a float. The goldens' hashes catch a type change; Task 1 pins it.
2. **A Python-side write the mirror missed.** Such a write would make "mirror equals Python" false, and the skip would then hide a real update. Task 1 runs the mirror audit (`DAUNTLESS_NATIVE_AUDIT=1`) over the scene test.

---

### Task 1: The subsystem stage skips writes the mirror already holds

**Files:**
- Modify: `native/src/combat/src/subsystem_step.cc`. Every mirror-write-plus-`log(...)` pair goes through one helper that compares the mirror's current value bit for bit (`std::memcmp` of the doubles, so `-0.0` ≠ `0.0` and NaN payloads compare by bits) and, when identical, does neither the mirror write nor the log. Mirror writes stay as they are when the value differs. Event and skip logic are unchanged.
- Test: `native/tests/combat/subsystem_step_test.cc`; `tests/integration/test_native_subsystems_scene.py` (unchanged golden, plus an audit run).

**Interfaces:**
- Produces a native counter: writes logged, and writes skipped as identical, per stage call. It is exposed through the existing stage stats binding if one exists; otherwise add `combat_subsys_write_stats()` → `{"logged": int, "identical": int}`, reset per call.

- [ ] **Step 1: Write the failing tests.**
  - ctest `SubsystemStep.SteadyPowerLogsNoWritesOnTheSecondTick`: a plant with one consumer, two identical ticks inside one interval. The second tick logs zero consumer writes (`POWER_WANTED`, `POWER_RECEIVED`, `EFFICIENCY`, `POWER_FACTOR`).
  - ctest `SubsystemStep.AChangedValueIsStillWritten`.
  - ctest `SubsystemStep.NegativeZeroIsNotIdenticalToZero`.
  - pytest `test_scene_skips_identical_writes_and_audit_is_clean`: run the scene with `DAUNTLESS_NATIVE_AUDIT=1`. Assert `identical > 0`, no audit failures, and the golden unchanged.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the helper and route every pair through it.** If a golden changes because a Python field starts as an int (Review Focus 1), fix it at the source: initialise that field as a float, or force the first write. Never re-record.
- [ ] **Step 4: Run the new tests, plus** `tests/integration/test_golden_fights.py`, `tests/integration/test_native_subsystems_scene.py`, `tests/unit/test_native_subsystems_driver.py`, `tests/unit/test_native_subsystems_power.py`, `tests/unit/test_native_subsystems_shields.py`, `tests/unit/test_native_subsystems_cloak_repair.py`, and `ctest --test-dir build -R combat_`. Expect PASS, goldens unchanged.
- [ ] **Step 5: Commit** `perf(native): the subsystem stage skips writes the mirror already holds`.
