# Phase 6 B0 + A1: Boundary Benchmark and the Subsystem Stage in C++ — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the Python↔C++ call boundary (B0), then run the per-tick subsystem stage — shields, power, cloak, repair, and the articulation skip — natively, with output bit-identical to today's Python.

**Architecture:** A new C++ stage, `subsystem_step`, walks the ships in the same order as `_update_ship_subsystems`. Inside each ship it runs shields, then power, cloak, repair and articulation. It reads the combat mirror, writes its results back into each object's `__dict__` through the existing C appliers, and **stops and hands a record back to Python** whenever:
- an SDK-visible event must fire (watcher crossings, cloak or repair completion);
- a piece is not native yet;
- the ship has a rig (articulation stays Python).

Python handles the record and resumes the session. This is K0's begin/next session shape.

**Tech Stack:** C++20 (`native/src/combat`, compiled with `-ffp-contract=off`), pybind (`native/src/host/host_bindings.cc`), Python 3.11 engine, gtest (`ctest -R combat_`) and pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` (APPROVED 2026-11-05), §3–§4 and §6–§7. **Stage map (read it first):** `docs/superpowers/plans/2026-11-05-phase6-a1-subsystem-stage-map.md`. It is a dated recon snapshot of every per-tick piece, its fields, events, cadences, callers and tests; line numbers drift, so find sites by name.

## Spec amendments (rulings, pending Mark's plan review)

- **R1 — state of record.** Spec §3 says "native-authoritative, Python reads through `Native*` descriptors". The codebase has no such pattern (stage map §4): every `Native*` field is Python-authoritative. A write pushes to the mirror, a read is a plain `__dict__` read, and kernels write back into `__dict__` through C appliers.
  - A1 follows the existing pattern. It meets the spec's intent: no per-tick repack, because the mirror is persistent and only writes push. It is also cheaper for Part B, because SDK reads stay plain attribute reads.
  - Cost if wrong: Part B revisits it.
- **R2 — the Python reference is scaffolding, deleted in the last task** (Mark, 2026-11-05: "why dont we remove it as the last task?"). This matches spec §3.
  - While the port is built, the Python `Update` methods are the bit-exact oracle, behind `DAUNTLESS_NATIVE_SUBSYSTEMS=0` with a per-tick differential test.
  - Task 2 extends the golden fights to record the stage's own state (batteries, the repair queue, every subsystem's condition, the cloak state), recorded from the Python path. Today those are covered only by the differential (stage map §6). Once extended, the goldens stay the oracle after the Python path is gone.
  - Task 8 deletes the Python stage and its switch, and moves the tests that drive the old methods onto the native stage.
- **R3 — event order.** SDK handlers run synchronously in the middle of the stage today (stage map §2 and §8). The native stage keeps exact order by stopping at each event and resuming after Python dispatches it, never by batching events to the end.

## Global Constraints

- Branch: `ws/motion-phase6-a1` in `.claude/worktrees/native-motion`, cut from `ws/motion-phase6-measure` (tip `4dd135379` or later). Merge into `project/native-motion-and-proximity` only after Mark's live check.
- **Never run the gate or a whole pytest or ctest suite.** Focused test files only (CLAUDE.md "Test gate"). Never run destructive git; stage with explicit paths.
- Golden fights (`tests/integration/test_golden_fights.py`) must stay unchanged. Never set `UPDATE_COMBAT_GOLDEN`, with ONE exception: Task 2's row extension, recorded from the Python path (`DAUNTLESS_NATIVE_SUBSYSTEMS=0`) with `COMBAT_GOLDEN_REASON` naming it. That adds rows and changes no existing value.
- Bit-exact with Python doubles: same operation order, `-ffp-contract=off` (already set for `native/src/combat`), no reassociation, Python's `min`/`max`/comparison semantics. Accumulators are reset, not subtracted, as Python does.
- Switch: `DAUNTLESS_NATIVE_SUBSYSTEMS`, on unless `=0`. Off = today's Python stage, byte-identical. The switch exists only until Task 8 deletes it.
- C++ builds from the worktree root (`cmake --build build -j`). Never run cmake in `native/`, and never change `CMAKE_BUILD_TYPE`. Renderer and combat gtests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"` or they SKIP.
- Benchmarks (B0 and Task 7) only on an otherwise idle machine; Mark has cleared it for benchmarking.

## Review Focus

1. **An SDK handler fired mid-stage writes state that a LATER ship or subsystem in the same walk reads** (for example, a shield-watcher handler turning another ship's shields off). The native walk must see the write. Pinned in Task 2's differential, with a handler that writes.
2. **A mission changes a shared property template at runtime** (E2M0/E2M1/E6M2/E6M4 `SetMaxRepairPoints`; `SetMainBatteryPower`; `SetShieldChargePerSecond`). The native stage must use the new value on the next tick. Pinned in Tasks 3–5.
3. **A ship or subsystem is destroyed or removed by a handler mid-walk.** The session must not touch freed rows. Pinned in Task 2.
4. **Power edge semantics:** a plant with no property skips the pump; `PSM_DIRECT_MAIN` falls into `_draw`'s else branch; tractor and cloak direct steals are not counted in `_power_dispensed`. Pinned in Task 4.
5. **Repair reentrancy:** `ET_REPAIR_CANNOT_BE_COMPLETED` fires while the queue is being walked, and a handler may edit the queue. Pinned in Task 5.

---

### Task 1 (B0): Boundary benchmark

**Files:**
- Create: `tools/bench/boundary_bench.py`
- Modify: `native/src/host/host_bindings.cc` (dev-only `bench_*` bindings, under a comment block marking them benchmark-only)
- Test: `tests/tools/test_boundary_bench.py`
- Modify: `docs/reference/engine/perf-register.md` (one capture row and one signal)

**Interfaces:**
- Produces: `uv run python tools/bench/boundary_bench.py [--calls N]`, which prints one table row per variant: `variant  ns/call  allocs/call`.
- Variants (each reads the same 3 doubles for a "ship position"):
  1. `py_method`: today's shape, `get_store().get_position(i, g)` then `TGPoint3(x, y, z)`.
  2. `bind_tuple`: a pybind function returning `(x, y, z)`, wrapped in a Python `TGPoint3`.
  3. `bind_new_obj`: a pybind function that constructs and returns a Python `TGPoint3` from C++.
  4. `bind_fill`: a pybind function that writes `x, y, z` into a caller-supplied `TGPoint3`.
  5. `native_point`: a pybind class with `x/y/z` properties, created per call; also time reading `.x` on it against a `__slots__` `TGPoint3`.
  6. `buffer_view`: Python reading the three doubles from a `memoryview` over native memory.
- Also measured: the cost of one `combat_push_scalar` call (the `NativeField` write path), and a no-op pybind call (the floor).

- [ ] **Step 1: Write `test_boundary_bench_runs_every_variant`.** It runs the script with `--calls 1000` and asserts every variant name above, plus `push_scalar` and `noop`, appears with a positive ns/call.
- [ ] **Step 2: Run it and see it fail** (the script doesn't exist yet).
- [ ] **Step 3: Implement the bindings and the script.** Use `time.perf_counter_ns`, the best of 5 repeats of N calls, with N defaulting to 1,000,000. Count allocations with `tracemalloc` over one repeat.
- [ ] **Step 4: Run the test (PASS). Then run the full benchmark on the Release build in `.claude/worktrees/release-macos`** (detach it at this branch's tip and build). Write the numbers into the perf register as a capture row and SIG-198, which ends with a one-line recommendation per method family: "port", "thin Python over native", or "native point type".
- [ ] **Step 5: Commit** `perf(bench): Python↔C++ boundary benchmark (B0, SIG-198)`.

### Task 2: Stage session, hand-back protocol and differential harness (every piece still Python)

**Files:**
- Create: `native/src/combat/include/dauntless/combat/subsystem_step.h`, `native/src/combat/src/subsystem_step.cc`
- Create: `engine/appc/native_subsystems.py`
- Modify: `engine/core/loop.py` (`_update_ship_subsystems` calls `native_subsystems.step_all(TICK_DELTA)` when enabled)
- Modify: `native/src/host/host_bindings.cc` (session bindings), `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`
- Modify: `tests/helpers/golden_fight.py` (and `k1_fight.py` / `posed_fight.py` if they own the state rows) to record the stage's state; re-record `tests/fixtures/golden_fights/*.json.gz` from the Python path
- Test: `native/tests/combat/subsystem_step_test.cc`, `tests/integration/test_native_subsystems_differential.py`, `tests/unit/test_native_subsystems_driver.py`

**Interfaces:**
- C++ session, shaped like K0 (`k0_charging.h`):
  - `SubsystemSession begin(const Mirror&, std::span<const int64_t> ship_handles, double dt)`
  - `SubsystemRecord next(SubsystemSession&, Mirror&)`, returning one of:
    - `DONE`;
    - `RUN_PYTHON{ship, kind}`, where kind is one of `SHIELD, POWER, CLOAK, REPAIR, ARTICULATION`;
    - `EVENT{ship, kind, code, a, b}`.
  - The session keeps a cursor `(ship index, kind)` and resumes exactly after the record it returned.
- In this task every `(ship, kind)` returns `RUN_PYTHON`, so behaviour is unchanged by construction.
- Python: `native_subsystems.enabled() -> bool` (the switch, plus "the mirror is live"), and `native_subsystems.step_all(dt) -> None`.
  - `step_all` takes the ship list from `iter_non_rock_ships()` exactly as today, calls the session's `begin`, then loops `next`.
  - On `RUN_PYTHON` it calls that ship's existing method: `GetShieldSubsystem().Update(dt)`, `GetPowerSubsystem().Update(dt)`, `GetCloakingSubsystem().Update(dt)`, `GetRepairSubsystem().Update(dt)`, or `articulation.tick_ship(ship, dt)`, each only when the subsystem exists, as `loop.py` does.
  - On `EVENT` it dispatches through `native_subsystems._EVENT_HANDLERS[kind]`. That table is empty in this task; Tasks 3–5 fill it.
- A ship removed or freed mid-walk (its mirror row gone) is skipped by `next`: Review Focus 3.

- [ ] **Step 0: Extend the goldens first, before anything native exists.**
  - Add, per ship per recorded tick: main and backup battery power, available power, every subsystem's condition (not only the hull), the repair queue (subsystem names in order), the cloak state and transition elapsed, and the shield charge accumulator.
  - Check that the extended recorder reproduces every EXISTING row byte for byte against the current fixtures.
  - Then re-record with `DAUNTLESS_NATIVE_SUBSYSTEMS=0 UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="phase 6 A1: record the subsystem stage's own state"`.
  - Commit on its own: `test(golden): record the subsystem stage's state`.
- [ ] **Step 1: Write the failing tests.**
  - ctest `combat_SubsystemStep.AllPythonOrderIsShipThenKind`: three ships produce 15 `RUN_PYTHON` records in the order (ship0: SHIELD, POWER, CLOAK, REPAIR, ARTICULATION), (ship1: …), then `DONE`.
  - ctest `combat_SubsystemStep.SkipsAFreedRow`: the second ship's row is freed after the first record, and its records never appear.
  - pytest `test_step_all_matches_the_python_stage_call_for_call`: spy on the five methods across a 3-ship world; the call order with the switch on equals the order with it off.
  - pytest `test_differential_combat_scene_bit_exact`: a headless combat scene (reuse `tests/helpers/golden_fight.py`'s scene builder or `engine.dev_missions.combat_stress` at 16 ships), 600 ticks, switch on and off. After every tick, compare a snapshot of every stage-written field (the stage map §2 lists them per subsystem kind, plus watcher values and posted event rows) for exact equality. Include a mid-stage handler that writes to a later ship (Review Focus 1), registered on a shield watcher.
- [ ] **Step 2: Run them and see them fail** (no session or driver yet).
- [ ] **Step 3: Implement** the session, the bindings and the driver.
- [ ] **Step 4: Run the new tests plus `uv run pytest -q tests/integration/test_golden_fights.py tests/integration/test_passive_power_differential.py tests/integration/test_whole_ticks.py`, and `ctest --test-dir build -R combat_SubsystemStep`.** Expect PASS, goldens unchanged.
- [ ] **Step 5: Commit** `feat(native): subsystem stage session, every piece still Python`.

### Task 3: Shields native

**Files:**
- Modify: `native/src/combat/src/subsystem_step.cc`, `mirror.h` / `mirror.cc` (new fields), `engine/appc/subsystems.py` (`ShieldSubsystem`: `_charge_per_second` and `_charge_accum` become `Native*` fields; watcher-threshold pushes), `engine/appc/float_range_watcher.py` (push the range-check thresholds and the current value), `engine/appc/native_subsystems.py`
- Test: `native/tests/combat/subsystem_step_test.cc`, `tests/unit/test_native_subsystems_shields.py`, the Task 2 differential

**Interfaces:**
- The native SHIELD step reproduces `ShieldSubsystem.Update` exactly, per stage map §3:
  - `accum = accum + dt`; below 0.5, return;
  - otherwise `dt = accum; accum = 0.0`, then refresh the ramp; offline zeroes every face; otherwise per-face add and clamp, skipping faces with max 0.
- **Watchers.** Native computes each of the 7 shield watchers' new value as `GetSingleShieldPercentage` would. When the new value crosses none of the watcher's registered thresholds, it writes the value and continues. When it crosses any, it returns `EVENT{ship, SHIELD_WATCHER, watcher_index, new_value}`, and Python calls that watcher's own `_update(new_value)`, which fires the SDK events exactly as today.
- `_is_offline` inputs must all be mirrored or pushed: condition, disabled, destroyed, `_radiation_out`, and out-of-action. Add whatever is missing, each as a `Native*` field.
- `SetShieldChargePerSecond`, `SetCurShields` and `SetMaxShields` push: Review Focus 2.

- [ ] **Step 1: Write the failing tests.**
  - ctest `ShieldStep.ChargesOnTheThirtiethOrThirtyFirstTick` (an IEEE sum of 1/60, compared against a Python-computed tick index stored in the test);
  - ctest `ShieldStep.OfflineZeroesAllFaces`;
  - ctest `ShieldStep.CrossingYieldsAnEvent`;
  - pytest `test_sdk_set_charge_per_second_reaches_the_native_step`.
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Implement.** The SHIELD kind no longer returns `RUN_PYTHON`.
- [ ] **Step 4: Run the new tests, the Task 2 differential, `test_golden_fights.py`, and the shield unit tests listed in stage map §6** (`test_gameloop_shield_regen`, `test_shield_subsystem`, `test_shield_charge_accum_state`, `test_shield_generator_disabled_stops_regen`, `test_shield_alert_cycle_does_not_recharge`, `test_subsystem_watchers`, `test_float_range_watcher`). Expect PASS.
- [ ] **Step 5: Commit** `perf(native): shield regen in the subsystem stage`.

### Task 4: Power native (plant + consumer pump)

**Files:**
- Modify: `subsystem_step.cc`, `mirror.h` / `mirror.cc`, `engine/appc/subsystems.py` (`PowerSubsystem` plant fields and `PoweredSubsystem` `_power_wanted` / `_power_received` become `Native*` fields; consumer attach order is pushed), `engine/appc/properties.py` (the per-tick property values push on every setter, including on shared templates), `engine/appc/weapon_subsystems.py` (the tractor direct-steal flag), `engine/appc/native_subsystems.py`
- Test: `subsystem_step_test.cc`, `tests/unit/test_native_subsystems_power.py`, the Task 2 differential

**Interfaces:**
- The native POWER step reproduces `PowerSubsystem.Update`, including the consumer pump, exactly, per stage map §3:
  - the breach check (a breach returns `EVENT{ship, BREACH}`, and Python runs `death_check.note_breach`);
  - no property means no pump;
  - the 1.0 s interval is reset, not subtracted;
  - the recharge spills main → backup;
  - conduit budgets are computed unconditionally;
  - per-consumer `_draw` in attach order with its modes, including the `PSM_DIRECT_MAIN` else-branch;
  - tractor `DRAWS_DIRECT_FROM_MAIN` and the cloak's 1000·dt reserve steal, neither counted in `_power_dispensed`;
  - `_power_wanted_total`;
  - battery watchers handled like the shield watchers, with `EVENT{ship, BATTERY_WATCHER, 0|1, value}`.
- **Per-tick property values** (PowerOutput, MainBatteryLimit, BackupBatteryLimit, MainConduitCapacity, BackupConduitCapacity, MaxCondition) are mirrored per ship and pushed on every setter, including setters on shared templates: Review Focus 2.
- The passive power program is not used by the native path. It stays for the Python reference path (R2).

- [ ] **Step 1: Write the failing tests.** ctests:
  - `PowerStep.IntervalResetNotSubtract`
  - `PowerStep.MainSpillsToBackup`
  - `PowerStep.NoPropertySkipsPump`
  - `PowerStep.DirectMainFallsToElseBranch`
  - `PowerStep.TractorAndCloakStealsNotDispensed`

  pytests:
  - `test_sdk_set_main_battery_power_reaches_the_native_step`
  - `test_template_set_power_output_pushes_to_every_ship_using_it`
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Implement.** The POWER kind no longer returns `RUN_PYTHON`.
- [ ] **Step 4: Run the new tests and the Task 2 differential, plus:**
  - `test_golden_fights.py`, `test_passive_power_differential.py`, `test_power_reference_values.py`;
  - the power unit tests in stage map §6: `test_power_subsystem_update`, `_budget`, `_conduits`, `_breach`, `test_power_interval_tick`, `test_power_consumer_draws`, `test_conduit_getters_battery_limited`, `test_cloak_power_starvation`, `test_weapon_power_factor`, `test_motion_power_factor`.

  Expect PASS.
- [ ] **Step 5: Commit** `perf(native): power plant and consumer pump in the subsystem stage`.

### Task 5: Cloak and repair native

**Files:**
- Modify: `subsystem_step.cc`, `mirror.h` / `mirror.cc`, `engine/appc/subsystems.py` (`CloakingSubsystem` timers and `_backup_reserve`; the `RepairSubsystem` queue order and membership pushed on every queue change; MaxRepairPoints / NumRepairTeams / RepairComplexity per-tick values, which push, including from shared templates), `engine/appc/native_subsystems.py`
- Test: `subsystem_step_test.cc`, `tests/unit/test_native_subsystems_cloak_repair.py`, the Task 2 differential

**Interfaces:**
- **CLOAK** reproduces `CloakingSubsystem.Update`. Completion returns `EVENT{ship, CLOAK_DONE, cloaked|decloaked}`, and Python runs the existing `_fire` path. A forced decloak, when disabled or destroyed or when the reserve runs out, returns `EVENT{ship, FORCE_DECLOAK}`, and Python calls the existing decloak entry, so its SFX and weapon side effects stay in Python.
- **REPAIR** reproduces `RepairSubsystem.Update`: `raw = points * bayCondPct * dt; per_item = raw / len(worked); gain = per_item / complexity`, with complexity ≤ 0 treated as 1.
  - Condition writes go straight to the native `damage::set_condition` that `combat_dmg_set_condition` already uses, so their effect-queue entries are identical.
  - `ET_REPAIR_CANNOT_BE_COMPLETED` returns `EVENT{ship, REPAIR_CANNOT, sub}` at the same point in the queue walk. On resume, the walk re-reads the queue from the mirror (Review Focus 5).
  - `ET_REPAIR_COMPLETED` returns `EVENT{ship, REPAIR_DONE, sub}`.
  - The `_cannot_complete_notified` set is mirrored by subsystem handle, replacing `id()`.

- [ ] **Step 1: Write the failing tests.** ctests:
  - `CloakStep.CompletesAtDuration`
  - `CloakStep.ReserveOutForcesDecloak`
  - `RepairStep.SplitsPointsAcrossWorkedItems`
  - `RepairStep.CannotCompleteYieldsMidWalkAndResumes`

  pytests:
  - `test_mission_set_max_repair_points_reaches_the_native_step` (the E2M0 shape)
  - `test_handler_editing_the_queue_mid_walk`
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Implement.** The CLOAK and REPAIR kinds no longer return `RUN_PYTHON`.
- [ ] **Step 4: Run the new tests and the Task 2 differential, plus:**
  - `test_golden_fights.py`, `test_repair_oracle_galaxy.py`;
  - the cloak and repair unit tests in stage map §6: `test_repair_subsystem`, `test_repair_app_surface`, `test_gameloop_repair_tick`, `test_cloaking_subsystem`, `test_cloak_reserve_depletion`, `test_cloak_event_destination`.

  Expect PASS.
- [ ] **Step 5: Commit** `perf(native): cloak and repair in the subsystem stage`.

### Task 6: Articulation — native skip for rigless ships

**Files:**
- Modify: `subsystem_step.cc`, `mirror.h` / `mirror.cc` (a per-ship `rigged` flag), `engine/appc/articulation.py` (push the flag whenever `leaf_for` or the articulated-part generation changes)
- Test: `subsystem_step_test.cc`, `tests/unit/test_native_subsystems_articulation.py`

**Interfaces:**
- **ARTICULATION** returns nothing for a ship whose `rigged` flag is false (today's `_rigless_key` early-out, decided natively), and `RUN_PYTHON{ship, ARTICULATION}` for a rigged ship. So `tick_ship` runs only for rigged ships, unchanged.
- The flag is pushed by the code that computes `_rigless_key`, and again on a rig or generation change (hardpoint overrides, SPV edits).

- [ ] **Step 1: Write the failing tests.** ctest `ArticulationStep.RiglessShipsAreSkipped`; pytests `test_rig_added_at_runtime_starts_articulating` and `test_rigged_ship_still_runs_tick_ship`.
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the new tests, the Task 2 differential, `test_golden_fights.py` (posed_fight is in it), and the `tests/unit/test_articulation*.py` files.** Expect PASS.
- [ ] **Step 5: Commit** `perf(native): articulation skips rigless ships natively`.

### Task 7: Measure and record

**Files:**
- Modify: `docs/reference/engine/perf-register.md`; `docs/reference/engine/perf-cadences-and-latency.md` (fix the stale `subsystems.py:115` pointer for `SHIELD_CHARGE_PERIOD_S` and add a row for `DAUNTLESS_NATIVE_SUBSYSTEMS`); `CLAUDE.md` (add one sentence to the Native ship motion row naming the subsystem stage and its switch, within the row budget `tests/docs/test_doc_consistency.py` enforces)

- [ ] **Step 1: Build Release** in `.claude/worktrees/release-macos`, detached at the tip.
- [ ] **Step 2: Capture** with the spec §7 protocol: 64 and 128 ships, exterior and bridge, two runs each, switch on; one 128-ship exterior run with `DAUNTLESS_NATIVE_SUBSYSTEMS=0`; one `DAUNTLESS_PROFILE_PY` run at 128 ships.
- [ ] **Step 3: Score** `gl.subsystems` per tick, per-tick `sim`, frame time and ticks per frame, against SIG-196 and SIG-197.
- [ ] **Step 4: Record** the captures plus a signal, and fix the docs. Run `uv run pytest -q tests/docs`. Commit `docs(perf): native subsystem stage (SIG-…)`.
- [ ] **Step 5: Write the live-check list into the ledger** for the final message: a 64-ship fight; a cloaking Warbird; a repair after damage (engineering repairs the hull); a power-starved ship; E2M0 (a mission changing repair points); the LC Intrepid's moving parts. Mark is asked AFTER Task 8, so he checks the final, native-only code.

### Task 8: Delete the Python stage (R2)

**Files:**
- Modify: `engine/core/loop.py` (`_update_ship_subsystems` is only the native stage); `engine/appc/native_subsystems.py` (no switch; `enabled()` gone; a missing native module raises, like fire control, M10)
- Modify: `engine/appc/subsystems.py`:
  - delete `ShieldSubsystem.Update`, `PowerSubsystem.Update` and its pump helpers (`_pump_consumers`, `_interval` recharge), `CloakingSubsystem.Update`, `RepairSubsystem.Update`;
  - delete each consumer's `_update_power` / `_draw` / `_record_draw` where the native stage replaced it;
  - keep every SDK-facing method (getters, setters, `Repair`, `SetCondition`, `StartCloaking`/`StopCloaking`, the watchers).
- Delete: `engine/appc/passive_power.py`, and the power half of `passive_state.py` (the `FrozenField` / thaw descriptors that only power used, and `DAUNTLESS_PASSIVE_STATE` / `DAUNTLESS_PASSIVE_AUDIT` power paths). Keep what passive WEAPONS still needs, because K0's reference path is not part of this phase.
- Modify: the tests that drive the deleted methods directly (stage map §5–§6, about 60 unit tests and the differential drivers):
  - each moves onto a test helper, `tests/helpers/subsystem_stage.py: tick_subsystems(ships, dt, ticks=1)`, that runs the real native stage;
  - a test that only re-checked the Python implementation against itself, now covered by a ctest or a golden, is deleted and listed in the commit message;
  - the Task 2 differential and `test_passive_power_differential.py` are deleted (no second implementation is left to compare).
- Modify: `docs/reference/engine/perf-cadences-and-latency.md`, CLAUDE.md's Passive subsystem state row (power is now native; the WakeField / FrozenField rule remains for weapons only).

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces: no Python per-tick subsystem path. `rg -n "def Update" engine/appc/subsystems.py` shows none of the five deleted methods.

- [ ] **Step 1: Write `test_no_python_subsystem_stage_remains`.** It asserts those methods are gone, `DAUNTLESS_NATIVE_SUBSYSTEMS` has no effect, and `engine.appc.passive_power` cannot be imported. See it fail.
- [ ] **Step 2: Move the tests onto `tick_subsystems`.** One commit per test file group (power / shields / repair / cloak / articulation). Run each group's files before committing it.
- [ ] **Step 3: Delete the Python stage and the power passive-state machinery.** Run Step 1's test (PASS).
- [ ] **Step 4: Run** `test_golden_fights.py` (unchanged, including Task 2's extended rows), the moved test files, `tests/host/test_passive_state_scene_audit.py` (weapons half only; adjust it if it asserted power), `tests/docs`, and `ctest --test-dir build -R combat_`. Expect PASS.
- [ ] **Step 5: Commit** `refactor(native): the subsystem stage is native only; Python stage deleted`.
