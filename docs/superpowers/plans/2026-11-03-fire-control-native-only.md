# Fire control native only — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fire control (K1) has one copy of its rules, in C++, covering tractors and the SDK's weapon calls. The native switch is on unless `DAUNTLESS_NATIVE_COMBAT=0`.

**Architecture:**
- Golden fights are recorded from today's Python arm first.
- Then each behaviour change lands, each re-recording only the scenes it touches:
  - aim points become plain body-frame points;
  - tractors go native;
  - the SDK weapon calls go native;
  - the switch semantics change.
- Finally the Python copy is deleted, and every former hand-back becomes a counted "no fire".

**Tech Stack:** C++17 combat library, pybind11 bindings, Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md` (FS). Map: `docs/reference/engine/native-combat/k1-retirement-map.md` (KRM). Read both. FS rulings M1-M10 and R1-R10 are binding.

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/native-default`.
- C++: build with `cmake --build build -j`. Never reconfigure cmake or change BUILD_TYPE; never run cmake inside `native/`. Run `ctest --test-dir build -R "combat_|EffectQueue"`.
- Focused tests only: the files each task names, plus every touched module's existing tests, via `uv run pytest <files>`. NEVER `uv run --active`. Never whole suites, never `scripts/check_tests.sh`. Never launch the game. The controller benchmarks.
- The full native list lives at `/private/tmp/claude-501/-Users-mward-Documents-Projects-bc-dauntless/5ddd11d1-ec16-4134-949b-d2ec14ac8f02/scratchpad/native_files.txt.all.i.2`. Run it once, in one process, at the end of every task that touches native code: `uv run pytest $(cat <list>)`. Order pollution has hidden regressions before.
- The banned git commands of CLAUDE.md "Shared checkout" apply. Stage explicit paths; `git commit -F <file> -- <paths>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- No red or xfail tests committed. Mutation proofs: `cp` backup, mutate, run, `cp` restore, `diff` clean. No subagents.
- A golden is re-recorded only in a commit whose message names the behaviour change and the scenes it touched. An unposed scene that moves is a bug, not a re-record.

## Review Focus

1. **A former hand-back fires in real play.** The phase removes every Python safety net, so a route the map missed surfaces as a weapon that silently stops firing. Every task asserts `k1_no_fire` is empty in its scenes. Task 6's source guard lists every deleted name.
2. **Mission scripts that touch tractors.** E7M2's win, E8M2's OD1 stop, ConditionFiringTractorBeam and PowerDisplay must keep working with queued events. Task 3's tractor scene has a STARTED handler that stops the beam, and a listener that re-reads `IsFiring()`.
3. **Low-difficulty AI dumb fire** (BasicAttack at Difficulty 0.0, E2M0, E3M2, E4M6). Task 4's scene 6.
4. **A stale build or a different interpreter.** It must fail loudly at start-up, not play without weapons. Task 5 tests a missing binding and a failed self-check.
5. **Tests that quietly ran the Python copy** (KRM §5.2-5.3). After Task 6 they run native or are deleted with a named reason. Task 6's report lists every changed or deleted test file and why.

---

### Task 1: Golden-fight recorder and the reference recordings

**Files:**
- Create `tests/helpers/golden_fight.py`, `tests/integration/test_golden_fights.py` and `tests/fixtures/golden_fights/`.
- Reuse the K1 differential's scene and record code (`tests/integration/test_native_k1_differential.py` `_Scene`, `record`, `OPS`, `SEED`, `_both`) and `tests/helpers/posed_fight.py`. Import or move them; don't copy them.

**Interfaces (Produces):**
- `golden_fight.run_scene(name: str, arm: str) -> list[tuple]`, where `arm` is `"python"` (switch `=0`) or `"native"`, returning per-tick canonical rows;
- `golden_fight.check(name, rows)`, which compares against `tests/fixtures/golden_fights/<name>.<platform>.json.gz` and names the first differing tick and field;
- `golden_fight.record(name, rows, reason)`, active only when `UPDATE_COMBAT_GOLDEN=1`;
- the platform key is `sys.platform`.

**Steps:**
- [ ] **Tests:** `test_golden_fights.py` has one test per scene: `k1_ops_tpf1`, `k1_ops_tpf6`, `k1_gameloop_ai`, `k1_midwalk_handler`, `posed_fight`, `tractor_modes`, `sdk_dumb_fire`.
  - Each runs its arm and calls `check`.
  - **Arms:** the scenes that are native today use the native arm. `tractor_modes` and `sdk_dumb_fire` use the Python arm until Tasks 3 and 4.
  - **Rows (KRM §5.5):** weapon and leaf fields, tractor fields, ship pose, hull and shields by `.hex()`; the ordered event log; effect-queue rows in delivery order. Labels are names and indices, never `id()` or handles.
  - **Determinism (FS R10):** seeds, `clear_in_flight`, `gc.collect()` at load, isolated fight audio.
  - **The two new scenes:**
    - `tractor_modes`: an attacker with a tractor system and a target. Steps through HOLD, TOW, PULL, PUSH, DOCK_STAGE_1 and DOCK_STAGE_2; out of range and back; out of arc and re-acquire; parent off and on; power starved. A broadcast handler on `ET_TRACTOR_BEAM_STARTED_FIRING` calls the system's `StopFiring()` once. A `ConditionFiringTractorBeam`-style listener re-reads `IsFiring()`. The force runs host-style through `_advance_combat`.
    - `sdk_dumb_fire`: an AI ship with `DumbFireTorps` on (SDK `AI/Compound/BasicAttack.py` at `Difficulty 0.0`), host-style ticks.
  - Also `test_golden_missing_platform_skips`.
- [ ] **Record** each scene from the **Python** arm (`UPDATE_COMBAT_GOLDEN=1`, reason "reference: Python arm before retirement").
- [ ] **Check native.** Run scenes 1-5 (`k1_*`, `posed_fight`) on the native arm against those recordings → PASS. If one fails, stop and report: it is a pre-existing native/Python mismatch.
- [ ] Report the size of each fixture file.
- [ ] **Mutation:** perturb one field in a recording → the check fails and names it.
- [ ] Commit.

### Task 2: Aim points are plain body-frame points (FS M5, R5, R6)

**Files:** everything in KRM §4.1-4.2, both the Python and the native sides:
- `engine/appc/native_combat.py` (manual slot, `resolve_stale_part_slots` manual half, `_forget_part_caches` manual lines, `_audit_manual_slot`, `_enc_baked`);
- `engine/appc/subsystems.py` `target_offset_world`;
- `engine/appc/projectiles.py` (bake, `_baked_offset`, `_steer_point`);
- `engine/appc/weapon_subsystems.py` `_launch_reads` bake;
- `engine/appc/effect_queue.py` SPAWN baked operands;
- `engine/manual_aim.py` (pull-back; delete `rest_point_for_live_point`);
- native `weapon_geometry`, `beam_geometry`, `projectile_geometry`, `part_pose`, `mirror`, `k1_fire_control`, `k2_beams`, `torpedo_table`, `host_bindings`.

Delete `tests/unit/test_native_manual_slot.py`.

**Steps:**
- [ ] **Tests (RED):**
  - `test_non_mount_offset_on_posed_target_is_body_point`, in Python and native geometry: a posed BoP, an offset inside a wing's box that is no mount. The aim point is `body_point_world(target, offset)`.
  - `test_mount_on_posed_part_still_follows_pose`.
  - `test_near_mount_offset_is_plain_point` (FS M8.5): 1e-6 off a mount gives a plain point in both copies.
  - `test_manual_pick_stored_as_hit_point`: the stored offset equals the live body point the ray hit.
  - `test_torpedo_at_pick_steers_to_body_point_all_flight`: no bake.
  - The K2, K3 and posed both-ways tests stay green, since both arms change together.
- [ ] Implement.
- [ ] **Goldens:** re-record `posed_fight` only (reason "D5: aim points plain body-frame"). Every other scene must pass unchanged.
- [ ] **Mutation:** restore the box rule in native `target_offset_world` → the posed test and the `posed_fight` golden fail.
- [ ] Run the full native list. Commit.

### Task 3: Tractors native (FS M4, R7, R8)

**Files:**
- `engine/appc/weapon_subsystems.py` (`TractorBeamSystem`, `TractorBeam`);
- `engine/appc/tractor.py` (the force becomes a call into native; constants stay the single source, pushed as globals);
- `engine/appc/native_combat.py` (mirror fields, flags, drivers);
- `engine/appc/effect_queue.py` (two kinds);
- `engine/host_loop.py` `cb.tractors`;
- native: `mirror`, `k0_charging` (holding branch), `k1_fire_control` (tractor walk, native StartFiring session), a new `tractor_force.{h,cc}`, `effect_queue`, `host_bindings`.

**Interfaces:**
- **Consumes:** Task 1's `tractor_modes` scene.
- **Produces:** `native_combat.k1_tractor_start(system, target, offset)` (StartFiring's session) and `native_combat.tractor_force_step(ships, dt)`.

**Steps:**
- [ ] **Tests (RED):**
  - `test_tractor_engage_native` (`k1_no_fire` empty, no `SelfManaged`);
  - `test_tractor_sustain_drop_out_of_arc_reacquires`;
  - `test_tractor_round_robin_single_fire`;
  - `test_k0_holding_tractor_power_loss_stops`, with no K0 tractor hand-back;
  - `test_tractor_force_matches_law`: `speed == clamp(5*100/mass, 0, 20)`, one tick per mode, by `.hex()` against the formula;
  - `test_tractor_events_are_queue_entries`: STARTED/STOPPED arrive at the boundary, in order, with source the system and destination the ship;
  - `test_power_thaw_on_firing_write`: a native `_firing` write still thaws the parent's power program;
  - plus ctest cases for the force step.
- [ ] **Implement.** Delete the self-managed flag and hand-back, `_pump_held_system`'s tractor branch, `TractorBeamSystem.update_weapons`, `_engage_beam`'s Python decision and `_target_tractorable`. Keep SDK methods (`StartFiring`, `StopFiring`, `IsFiring`, `GetMode`, `SetMode`) as wrappers.
- [ ] **Goldens:** `tractor_modes` switches to the native arm. Re-record it once (reason "R8: tractor events queued, one tick later"). Then mutate the force law → it fails.
- [ ] Run the existing tractor tests (KRM §5.2 list), `tests/unit/test_native_k0_dispatch.py` and the full native list. Commit.

### Task 4: SDK weapon routes native (FS M8.1-3, M8.6)

**Files:**
- `engine/appc/weapon_subsystems.py` (`Weapon.FireDumb`, `Fire`, `CanFire` wrappers; `_spawn_torpedo` slot-0 path);
- `engine/appc/native_combat.py` (dumb-fire session, slot-0 cache, stale re-push);
- native `k1_fire_control`, `fire_gates`, `host_bindings`.

**Steps:**
- [ ] **Tests (RED):**
  - `test_sdk_fire_dumb_is_native`;
  - `test_can_fire_is_native_and_clears_depleted`: same answer and side effect as before, over a charge sweep;
  - `test_fire_wrapper_native`;
  - `test_tube_without_ammo_type_fires_slot0_script`;
  - `test_reimported_pulse_module_repushed_not_no_fire`;
  - `test_cache_reset_mid_session_repushed`.
- [ ] **Implement.** `CanFire`, `Fire` and `FireDumb` call the native rule. Python keeps only the SDK signature.
- [ ] **Goldens:** `sdk_dumb_fire` switches to the native arm and must pass the Python recording unchanged.
- [ ] Run the full native list. Commit.

### Task 5: Switch semantics and loud failures (FS M1, M9, M10, R1)

**Files:** `engine/appc/native_combat.py` (`configure`, `available`, `_self_check`, `reset`), `tests/conftest.py` (the per-test reset), and the tests that pin the old default (`tests/unit/test_native_combat_k3_mirror.py::test_switch_off_registers_nothing`).

**Steps:**
- [ ] **Tests (RED):**
  - `test_switch_on_unless_zero`: unset → on, `0` → off, `1` → on;
  - `test_fire_control_native_with_switch_zero`: `=0` turns K0/K2/K3/K4/damage Python but K1 stays native;
  - `test_missing_binding_raises_at_configure`: the message names the missing binding;
  - `test_failed_self_check_raises`;
  - `test_conftest_reset_keeps_fire_control_native`.
- [ ] **Implement.** Update `test_switch_off_registers_nothing` to pin `=0`. Tests that need a Python arm of another kernel pin `=0` explicitly.
- [ ] Run the headless 26-mission campaign sweep (`tests/integration/test_campaign_warp_transitions.py`, `test_campaign_warp_in.py`), `tests/oracle/*`, and the full native list. Commit.

### Task 6: Delete fire control's Python copy (FS M3, M6, M8.4-5, M8.7-8, R2-R4)

**Files:**
- everything KRM §1.2-1.5 marks DELETE, plus K2's override guard (`k1_overridden` reads, K2C:388, 578, 794);
- the test migration of KRM §5.1-5.2;
- a new `tests/unit/test_fire_control_python_retired.py` source guard.

**Steps:**
- [ ] **Tests (RED):**
  - **Source guard:** `test_fire_control_python_retired` asserts that none of the deleted names exist. That covers `update_weapons`, `try_fire_weapon`, `_fire_decide`, `_k1_answer`, `_K1_LEAF_METHODS`, `RUN_PYTHON`, `K1Why`'s Python reasons, `_pump_held_system`, `_live_held_offset`, the walk check and the launch check.
  - `test_no_fire_rolls_back_before_first_shot` (FS R2);
  - `test_no_fire_after_shot_keeps_shot` (FS R2);
  - `test_no_fire_logged_once_per_reason`;
  - `test_dropped_row_is_counted_no_fire` (FS R3);
  - `test_part_resolution_error_retries_each_step` (FS M8.4);
  - `test_walk_offset_object_built_natively` (FS M8.8): every bank in a walk shares one object.
- [ ] **Implement the deletions.**
  - The K1 differential and `test_native_k1_dispatch.py`'s Python comparisons move to goldens or recorded expectations.
  - Tests of deleted scaffolding are deleted.
  - Fake-weapon tests move to real weapons.
  - Every changed or deleted test file is named in the report with its reason.
- [ ] **Goldens:** all scenes pass unchanged on the native arm.
- [ ] Run ctest, the campaign sweep, `tests/oracle/*`, the other kernels' differentials (both arms) and the full native list. Commit.

### Task 7: Benchmark, docs, review (controller)

- [ ] Benchmark two 64-ship runs against SIG-178, with no switch set. Add perf register entries.
- [ ] **Docs:**
  - FS §6;
  - the roadmap (E's first kernel retired, the M rulings, C's stale "still open" line);
  - KRM superseded notes;
  - CLAUDE.md lines to fix at the main merge: OQ-2.3's spring-damper, event-emitter gap #15, "all 12 gaps closed".
- [ ] Final whole-branch review on the most capable model, then one fix round.
- [ ] Hand to Mark for the live check (no switch set, including tractors).
