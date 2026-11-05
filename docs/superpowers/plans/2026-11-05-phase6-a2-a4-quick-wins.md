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

## Tasks 2–6 (added 2026-11-05 after the A2–A4 recon)

Recon (a read-only explorer, 128-ship cProfile C-320 + frame rows C-327/C-329) ranked the cheap behaviour-preserving cuts below. **Deferred to a later phase** (bigger): a native beam/torpedo render feed, native-authoritative K0 fields (goldens read `__dict__`), and removing the damage `clean` list (needs a K2/K3 "clean all" mode).

### Task 2 (A2): K0 without the override guard, with a lean applier

**Files:** `engine/appc/native_combat.py` (`k0_weapons`, the guard: `_K0_METHODS`, `_k0_flag`, `_K0_*_PATCHES`, the `FloatRangeWatcher._update` watcher snapshot, the retry loop, `fresh`), `native/src/host/host_bindings.cc` (`combat_k0_begin` with `ctx=None`, `combat_k0_clear_caches`), `native/src/host/combat_write_apply.cc` (a lean K0 apply path), K0 tests.

- Spec §3 Part A: no fallback for patched App methods. So `k0_weapons` passes `ctx=None`; the binding already supports it ("no guard: every ship and weapon native"). Delete the Python guard machinery, and the binding's guard caches if nothing else uses them.
- Keep these stand-downs, which are not patch fallbacks: `off` (`DAUNTLESS_NATIVE_COMBAT=0`), `audit`, `nested`. Keep the RUN_PYTHON reasons that are representability, not patches. List every remaining RUN_PYTHON reason in the report, with what triggers it.
- Lean K0 apply, in the style of `subsystem_write_apply.cc`:
  - one registry lookup per run of same-handle writes;
  - a per-field store with no pins dict and no per-write kind lookup;
  - skip the `_passive_asleep` wake probe only where K0 can prove the object isn't asleep (K0 never sleeps a weapon), and keep it otherwise;
  - skip writes bit-identical to the mirror, as Task 1 did, except where a Python sentinel/int differs (Task 1's RAMP lesson: check each field's Python initial type).
- Tests:
  - guard-only tests (`test_native_k0_override_guard.py`, the guard parts of `test_native_k0_dispatch.py`) become `test_a_patched_k0_method_is_not_honoured` or are deleted (list them);
  - `tests/integration/test_native_k0_differential.py` and `test_passive_weapons_differential.py` still pass;
  - goldens unchanged;
  - `ctest -R combat_K0`.
- Commit `perf(native): K0 without the override guard; lean write-back`.

### Task 3 (A3): K1 skips sustain writes that change nothing

**Files:** `native/src/combat/src/k1_fire_control.cc` (sustain writes around `write_target_offset`, ~1431-1438), the mirror (a per-bank offset-source field if needed), `engine/appc/native_combat.py` (`_K1Walk.materialise` / `pin_system`), K1 tests.

- A beam already firing re-logs `_firing`, `_target` and a walk-offset `_target_offset` every tick, and each walk marker runs Python `materialise` / `pin_system`. Skip:
  - `_firing` when it is already True;
  - `_target` when it is the same handle;
  - `_target_offset` only when the bank already holds the same system's `_held_offset` object.

  Offset IDENTITY is recorded by the goldens (`offset_is_held_offset`, `offset_first_holder`, golden_fight.py ~121-124), so add whatever mirror state proves "same holder" (e.g. the system handle plus a `_held_offset` push generation). Manual Aim makes a new TGPoint3 per walk: it must keep writing.
- Tests: a ctest showing a sustained held-offset beam logs no sustain writes on its second tick; a Manual Aim case still writes; goldens unchanged (this is the guard on identity); `ctest -R combat_K1`.
- Commit `perf(native): K1 skips sustain writes that change nothing`.

### Task 4 (A3): combat glue — the cheap Python cuts

**Files:** `engine/appc/native_combat.py`, `engine/appc/objects.py`, `engine/appc/projectiles.py`, tests.

- `resolve_stale_part_slots` (runs ~4×/tick over all ships, 4.7 M `dict.get` in the profile): make it O(1) when nothing is stale. Keep a pending-handle set, filled on register, on a part-generation bump (`bump_part_gen`) and on a raise, and cleared on resolve. Every path that made a slot stale before must still land in the set. Pin it with a test per path.
- `ObjectGroup.broadcast_membership` scans every live group per expiring torpedo. Index groups by name (name → set of groups, kept on `AddName` / `RemoveName` / `RemoveAllNames` / group death via the existing WeakSet). Iteration order over matching groups must stay what it is today; if today's order is the WeakSet's arbitrary order, keep the index's order deterministic and document it.
- `projectiles._scan_table`: hoist its function-local import.
- Part A: delete the Python "module/class patched" checks that send K2/K3 to Python: `_k2_unchanged`, `_k2_classes_unchanged`, `_k3_unchanged` / `_k3_classes_ok`, `_dmg_unchanged` / `_kdmg_unchanged`. Keep the representability checks (row exists, class mirror flags). Guard-only tests become "a patched method is not honoured" tests or are deleted (list them).
- Tests: as named above, plus `test_native_k2_dispatch.py`, `test_native_k3_dispatch.py`, the K2/K3 differentials (`tests/host/test_native_k2_differential.py`, `tests/integration/test_native_k3_differential.py` or `tests/host/…`, whichever exist), goldens unchanged.
- Commit `perf(native): combat glue — O(1) stale part slots, indexed group broadcast, no patch scans`.

### Task 5 (A4): combat render data — the cheap Python cuts

**Files:** `engine/host_loop.py` (`_build_torpedo_render_data`, `_color_tuple`, `_build_phaser_beam_render_data`, `_build_tractor_beam_render_data`, `_ships_in_view`), `engine/appc/projectiles.py` (`CreateTorpedoModel` / `CreateDisruptorModel`), tests.

- Torpedoes: build each torpedo's static descriptor part (textures, the five colours via `_color_tuple`, sizes, id, disruptor and bolt fields) ONCE, when its model is created, and per frame set only position, age and forward. If an SDK script can change a torpedo's visuals after creation (TGColorA mutated, a setter called), invalidate the cache from that setter. Check the SDK for such calls and say what you found. The torpedo dynamic light reuses the cached colour.
- Beams and tractors: walk only firing banks (find them without calling `GetWeapon` / `IsFiring` on every bank of every ship, e.g. from a per-system firing set or the mirror's `_firing`), and compute `_ships_in_view` once per frame for both builders.
- The descriptors must be IDENTICAL to today's: there is no golden for them. Add a test comparing the old builders' output with the new for a scene with several torpedo types, disruptors, firing phaser banks and a tractor (keep the old builder only inside the test as the oracle, then delete it at the end of the task, or build the oracle from a recorded fixture). Plus `tests/unit/test_render_feeds_by_frame.py`, `test_tractor_beam_render_data.py`, `test_torpedo_render_marshal.py`, `test_dynamic_light_render_marshal.py`, `tests/host/test_render_space_feeds.py`.
- Commit `perf(render): torpedo visuals built once; beam builders walk firing banks only`.

### Task 6: Measure, record, live-check list

- Release build in `.claude/worktrees/release-macos` detached at the tip. Captures as phase 6 A1's Task 7: 64 and 128 ships, exterior and bridge, two runs each, plus one cProfile run at 128 exterior (`DAUNTLESS_PROFILE_PY`, frames 500:400).
- Score `sim.weapons`, `cb.held_weapons`, `cb.phasers`, `cb.projectiles`, `cb.eligibility` and `gl.subsystems` per tick, `cb.render_data` per frame, and frame ms. Compare against SIG-199 / C-323..C-332. State the catch-up-loop confound as SIG-199 does.
- Perf register: captures plus one signal. Commit `docs(perf): phase 6 A2-A4 quick wins (SIG-…)`.
- Ledger: the live-check list. A 64-ship fight; torpedoes of several types plus disruptors (visuals unchanged); phaser beams and a tractor tow; Manual Aim on a moving target; a Quick Battle with cloaked ships.
