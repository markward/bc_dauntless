# Native combat: cut the per-record Python round trips — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the native kernels handing Python records whose Python side is only field writes or presentation, so K1/K2/K3 run without routine mid-step Python and the combat step loses ~1 ms per tick.

**Architecture:** The kernels log the writes Python would have made (existing write logs + quiet setters, so `WakeField` wakes still fire) or batch presentation calls in walk order, delivering them with the next real record or `DONE`. Anything that posts an event, plays a sound, applies damage or spawns a projectile stays a record.

**Tech Stack:** C++17 combat library (`native/src/combat/`), pybind11 (`native/src/host/host_bindings.cc`), Python driver (`engine/appc/native_combat.py`), pytest + gtest.

**Spec:** `docs/superpowers/specs/2026-11-01-native-combat-round-trips-design.md`. Map: `docs/reference/engine/native-combat/remaining-fallbacks-map.md` (MAP).

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/combat-round-trips` (forked from `project/combat_threading` after the posed-parts merge). Build `cmake --build build -j`; never reconfigure, never cmake inside `native/`, never change BUILD_TYPE; delete the `.o` to force a recompile when mutating.
- Bit-exact: floats by `.hex()`; Python's write ORDER and object IDENTITY (new list objects stay new); presentation calls in the same order with the same arguments.
- Ruling P1: logged writes are applied before any later Python runs (with the next record, or at `DONE`).
- A field the kernel reads MUST push. Every Python method whose body becomes logged writes joins the K1/K2 override guard while the Python copies exist.
- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF, byte-identical off. `DAUNTLESS_NATIVE_AUDIT=1` stands down as before. GIL held.
- Records stay for: beam-edge FIRE, tube/pulse FIRE, FIRE_FAILED, FIRE_DUMB, a firing bank's stop, damage-pulse CONTACT, every ASK/RUN_PYTHON.
- Focused tests only, by name; never whole suites/directories, `scripts/check_tests.sh`, pytest with no files, or `ctest` without `-R`. Engine-class guard active: `monkeypatch` only.
- Git: banned `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths; `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Restore mutated files by `cp`, then `diff`.
- Never spell `game` or `sdk` as a path segment. Never launch `./build/dauntless` (benchmarks use the headless harness, controller only).

## Review Focus

1. A walk whose first record is an ASK or RUN_PYTHON: the lazily fetched offset object, the patch scan and the pin must happen before that Python runs, in today's order. Test in Task 1.
2. A beam-sustain FIRE logged, then a later record in the same walk runs Python that reads `bank._target_offset`: it must see the logged object (identity), not a copy. Test in Task 2.
3. A sleeping bank stopped by a logged idle BANK_STOP still wakes (WakeField). Test in Task 2.
4. Resting contacts queued, then a damage-pulse contact on the same target: every queued VFX call happens before the pulse's `apply_hit`, exactly as today. Test in Task 3.
5. A K2 offline system whose banks are all idle, ticked repeatedly: `_target_list` is a NEW empty list every tick (identity), as Python's `StopFiring` does. Test in Task 3.

---

### Task 1: K1 `WALK_START` → native offset, lazy object

**Files:** `native/src/combat/src/k1_fire_control.cc` (+ header), `native/src/host/host_bindings.cc`, `engine/appc/native_combat.py` (`run_k1`, `_K1_SYSTEM_METHODS`/ShipClass guard), tests `tests/unit/test_native_k1_dispatch.py`, `native/tests/combat/k1_*_test.cc`.

**Interfaces:** remove the `WALK_START` record kind from the emitted stream (keep the enum value for counters); every first real record of a walk carries `walk_system` (handle) and a `walk_first` flag; the kernel computes the offset value (MAP §3.1 predicate) at UW_DEAD_PRUNE; counters `k1_logged["walk_start"]`.

- [ ] **Step 1: Failing tests:** `test_no_walk_start_records` (counts 0, `k1_logged.walk_start` > 0); `test_offset_value_matches_live_held_offset` (manual / held / none / non-ShipClass firing ship, `.hex()`); `test_first_record_ask_sees_pinned_offset_object` (Review Focus 1); `test_target_list_write_on_every_walk_is_a_new_list` (identity); `test_live_held_offset_override_runs_python` (guard). gtests for the predicate.
- [ ] **Step 2-4:** FAIL → implement → run `tests/unit/test_native_k1_dispatch.py tests/unit/test_native_k1_holds_gil.py tests/integration/test_native_k1_differential.py tests/unit/test_native_posed_flag.py` + `ctest -R combat_`.
- [ ] **Step 5: Commit** `perf(native-combat): K1 walk start without a Python round trip`.

### Task 2: K1 beam-sustain FIRE and idle BANK_STOP → logged writes

**Files:** `k1_fire_control.cc` (`TF_FIRE`, bank stop), `native_combat.py` (`apply_writes` if needed, guard for `StopFiring`), tests as Task 1.

**Interfaces:** Beam decision with `was_firing` → log `_firing=True`, `_target`, `_target_offset=walk_offset` (in that order), no record; idle bank stop → log the class's StopFiring writes (energy: `_firing`, `_beam_on_countdown`; tube: `_firing`; pulse: `_firing`, `_target`, `_target_offset`); counters `k1_logged["beam_sustain"]`, `["idle_bank_stop"]`.

- [ ] **Step 1: Failing tests:** `test_beam_sustain_logged_not_recorded` (per-tick parity, counters); `test_beam_edge_still_records` (sound + ET_WEAPON_FIRED); `test_logged_target_offset_is_the_walk_object` (Review Focus 2); `test_idle_bank_stop_wakes_sleeping_bank` (Review Focus 3); `test_firing_bank_stop_still_records` (loop sound); per bank class write order.
- [ ] **Step 2-4:** FAIL → implement → Task 1's files + `tests/unit/test_passive_state*.py` files that cover WakeField (name them) + `ctest -R combat_`.
- [ ] **Step 5: Commit** `perf(native-combat): K1 sustain fires and idle stops as logged writes`.

### Task 3: K2 resting contacts batched; offline SYSTEM_STOP logged

**Files:** `native/src/combat/src/k2_beams.cc` (+ header: queued-contact list on the record/DONE, value write log), `host_bindings.cc`, `native_combat.py` (`run_k2`, `_k2_contact`, guard `StopFiring` system+bank), tests `tests/unit/test_native_k2_dispatch.py`, `tests/host/test_native_k2_differential.py`, gtests.

**Interfaces:** resting CONTACTs (no damage pulse: `flush_dwell <= 0`) are appended to a per-session queue delivered with the next Python-running record or DONE; the driver runs them in order BEFORE that record's effect. Offline-system stop with all banks idle → logged writes (system's five, then each bank's), K2 write log gains a value variant. Counters `k2_batched_contacts`, `k2_logged_system_stop`.

- [ ] **Step 1: Failing tests:** `test_resting_contacts_batched_in_walk_order` (per-tick VFX/shield-hit call sequence identical to Python); `test_queued_contacts_precede_damage_pulse` (Review Focus 4); `test_offline_system_stop_logged_new_list_every_tick` (Review Focus 5); `test_firing_bank_on_offline_system_still_records`; `test_system_stop_override_runs_python`.
- [ ] **Step 2-4:** FAIL → implement → the K2 files + `tests/unit/test_native_beam_geometry.py` + posed differentials + `ctest -R combat_`.
- [ ] **Step 5: Commit** `perf(native-combat): K2 resting contacts batched, offline stops logged`.

### Task 4: K3 native `unattributed` steer attribution

**Files:** `native/src/combat/src/projectile_geometry.cc`/`k3_projectiles.cc`, `native_combat.py` (`_k3_apply` `_mount_key` write), tests `tests/unit/test_native_k3_dispatch.py`, `tests/integration/test_native_k3_differential.py`.

**Interfaces:** attribution check calls `authored_mount_subsystem`; `kMountUnknown`/non-ShipClass target → ASK as today; else native mount + a `_mount_key` write in `K3TorpWrite` applied quietly as `(target_obj, x, y, z, mount_obj or None)`; counter `k3_native_attributions`.

- [ ] **Step 1: Failing tests:** `test_unattributed_steer_is_native` (ASK count 0, per-tick parity, `_mount_key` tuple identity of target/mount objects); `test_mount_unknown_still_asks`; `test_non_ship_target_still_asks`.
- [ ] **Step 2-4:** FAIL → implement → K3 files + posed differentials + `ctest -R combat_`.
- [ ] **Step 5: Commit** `perf(native-combat): K3 steer attribution native`.

### Task 5: Differentials, scene audit, mutation proofs

**Files:** extend `tests/helpers/k3_fight.py` / `tests/helpers/posed_fight.py` recorders to compare the per-tick presentation call sequence (K2) and assert the new counters; `tests/host/test_native_combat_scene_audit.py`.

- [ ] **Step 1:** add the counter assertions (> 0 for each new path) and the presentation-order compare to the K1, K2, K3 and posed differentials; scene audit unaudited run asserts `k1_logged.walk_start` > 0.
- [ ] **Step 2: Run** all differentials + scene audit, both orders → PASS (a difference is a porting bug: fix code).
- [ ] **Step 3: Mutation proofs:** wrong write order; `_target_list` write skipped when unchanged; beam edge logged without a record; batched contacts delivered after the next record's effect; logged stop without wake. Each must fail a test; `cp` + `diff` restore.
- [ ] **Step 4: Commit** `test(native-combat): round-trip removal differentials`.

### Task 6: Benchmarks and docs (controller runs the benchmarks)

- [ ] **Step 1 (controller):** 2 runs of the 64-ship fight, switch on, at the posed-parts tip and 2 at this branch's tip, machine idle, established harness (scratchpad `bench_fight.sh`); score per tick (value ÷ ticks per frame, reports 3-11).
- [ ] **Step 2:** docs — spec §10 Outcome, perf-register captures + signals (next free C-/SIG- numbers on this line), CLAUDE.md native-combat row (within limits), roadmap §2 table, map header (implemented). `uv run pytest tests/docs/test_doc_consistency.py -q` → PASS.
- [ ] **Step 3: Commit** `docs(native-combat): round trips outcome and measurements`.
