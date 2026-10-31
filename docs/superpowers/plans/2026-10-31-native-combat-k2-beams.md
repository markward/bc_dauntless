# Native Combat Step — Phase 2 (K2 Beams) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the per-tick `cb.phasers` step into C++. Every SDK-visible value and event must stay bit-identical; Python keeps only the effects (`StopFiring`, `beam_contact`, `apply_hit`).

**Architecture:** K2 is a resumable C++ walk of the `cb.phasers` loop over the phase 1 mirror. It returns one record per Python effect and copies K1's protocol: write log, `ASK`, `RUN_PYTHON`, GIL held. The hull trace calls the renderer's own compiled trace through a callback installed by the host bindings.

**Tech Stack:** C++20 (`native/src/combat/`, gtest), pybind11 (`native/src/host/host_bindings.cc`), Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-10-31-native-combat-k2-beams-design.md`. The input map is `docs/reference/engine/native-combat/k2-beams-map.md` (cited as "map §x" or "F#"). The parent spec `docs/superpowers/specs/2026-10-30-native-combat-step-design.md` §7.5 and §9.1-§9.2 bind as well.

## Global Constraints

- **Worktree and branch.** Work in `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-1b`, branch `perf/native-combat-k2`.
  - Build: `cmake --build build -j`. Never run cmake inside `native/`. Never change `CMAKE_BUILD_TYPE`. To force a recompile when mutating C++, delete the `.o`.
- **Bit-exact.**
  - Compare floats by `.hex()`, never `pytest.approx`.
  - Use `py_pow` for `** 0.5`, and never `std::pow` with a literal exponent.
  - Use `py_min`/`py_max` in Python argument order, keep Python operand order, and port every NaN branch as Python has it.
  - Every new `.cc` goes in the combat sources list (`-ffp-contract=off`, Debug `-O2`) and carries `#pragma clang fp contract(off)`.
- **Constants.** Named module constants are pushed from Python (`BEAM_DWELL_FLUSH_S`, `SHIELD_ELLIPSOID_AXIS_SCALE`). Inline literals are ported verbatim, with a comment citing the Python line (ruling G).
- **The switch.**
  - `DAUNTLESS_NATIVE_COMBAT=1` turns it on; it is OFF by default.
  - With it OFF, behaviour must be byte-identical to before.
  - K2 runs only when `native_combat.enabled()`.
- **GIL.** K2 holds the GIL (ruling J). It touches no Python object; the trace callback touches only `g_world`.
- **One copy of each rule.** Python effect code (`beam_contact`, `apply_hit`, `StopFiring`, the damage arithmetic) is reused, never duplicated. Geometry rules exist twice: Python, plus the kernel.
- **Focused tests only.** Name every file. Never run whole suites, `scripts/check_tests.sh`, ctest without `-R`, or pytest with an empty file list.
- **Shared-checkout git rules.**
  - Never use `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A` or `git add .`.
  - Stage explicit paths and commit with `git commit -F <file>`.
  - End each message with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Restore a mutated file by `cp`, then `diff` to prove it is identical.
- **Path rule.** Never spell `game` or `sdk` as a path segment.
- **Tests.** Never launch `./build/dauntless`. The host-level tests use the headless host fixture that the existing `tests/host/` files use.

## Review Focus

1. **A target whose shields drop mid-volley.** A handler's `apply_hit` takes the shields to zero. The next bank must re-read `has_shields` and `IsOn` and skip the bubble, exactly as Python does.
   - Tested in Task 1 (`test_set_max_shields_pushes_has_shields`) and Task 6.
2. **A locked subsystem on a different ship than the bank's target** (map §1.2). The aim point uses the lock's ship and that ship's pose flag.
   - Tested in Task 2 (`test_lock_on_other_ship_aim_matches`) and Task 6.
3. **A ship realized or popped mid-step** (a handler spawns or destroys one). The trace must use the current iid table.
   - Tested in Task 1 (`test_tracked_instances_version_bumps`) and Task 5 (`test_instances_resent_after_mutation`).
4. **A test or mod that monkeypatches `host_io.ray_trace_mesh` or `combat.apply_hit`.** The patched function must still be honoured.
   - Tested in Task 5 (`test_patched_trace_runs_python_step`).
5. **A beam in its 0.66 s windup, and a flush on the arc-fail tick.** Sparks are drawn every windup tick, and the partial pulse is still delivered on the stop tick.
   - Tested in Task 4 (`WindupContactsEveryTick`, `ArcFailStopsThenFlushes`) and Task 6.

---

### Task 1: Mirror what K2 reads

**Files:**
- Modify:
  - `native/src/combat/include/dauntless/combat/mirror.h`, `native/src/combat/src/mirror.cc` and `native/tests/combat/mirror_test.cc`;
  - `engine/appc/native_combat.py`;
  - `engine/appc/ships.py`: `_target_subsystem`, `_use_target_offset`, `_manual_target_offset`, `_shield_subsystem`, `_shield_hull_box`;
  - `engine/appc/subsystems.py` / `weapon_subsystems.py`: bank `_length`, `_beam_on_countdown`, `_dwell`; a ShieldSubsystem `has_shields` flag, with `SetMaxShields` made a pushing mutator;
  - `engine/host_loop.py`: `session.ship_instances` becomes `TrackedInstances`.
- Create: the `TrackedInstances` dict subclass with a `version` int bumped on `__setitem__`, `__delitem__`, `pop`, `clear`, `update` and `setdefault`. Put it where `host_loop` can import it, for example `engine/core/tracked_instances.py`.
- Test: `tests/unit/test_native_combat_k2_mirror.py`.

**Interfaces:**
- Consumes 1b's `NativeField`/`NativeRefField`/`NativeWakeField`/`NativeFrozenField`, `push_field`, `_flags`, `audit_mirror`, `register`, rulings R1/R2/R6/R12 and the hidden-field guard.
- Produces mirrored fields:
  - **ship:** `_target_subsystem` (ref Subsystem), `_use_target_offset` (bool), `_manual_target_offset` (OFFSET: a TGPoint3 or unset), `_shield_subsystem` (ref Subsystem);
  - **ship hull box:** `_shield_hull_box` (6 doubles plus `hull_box_set`; anything that is not exactly `((3),(3))` encodes as unset);
  - **bank:** `_length`, `_beam_on_countdown`, `_dwell` (floats);
  - **ShieldSubsystem:** `has_shields` (a flag computed by Python's own `HasShields()` expression and pushed by every `_max_shields` writer);
  - **Object class flags:** `has_real_get_shields` (`implements(obj, "GetShields")`) and `is_ship_class`.
- Globals pushed: `BEAM_DWELL_FLUSH_S`, `SHIELD_ELLIPSOID_AXIS_SCALE`.
- `TrackedInstances.version` is an int.

- [ ] **Step 1: Write the failing tests.** Skip unless the bindings exist; enable native with `configure`. Use a real Galaxy and a real Bird of Prey.
  - `test_k2_fields_write_through`: drive each field through its public API and assert `combat_dump` equals the Python value by `.hex()`. The APIs are `SetTargetSubsystem`, `UseTargetOffsetTG`, `set_manual_target_offset`, `SetTarget` (which clears the offset), `SetShieldSubsystem`, `_cache_shield_hull_box`, `SetProperty` (`_length`), `UpdateCharge` (countdown), `accumulate_dwell`/`take_dwell`, and `tests/helpers/beams.py`.
  - `test_set_max_shields_pushes_has_shields`: `SetMaxShields(f, 0)` on every face makes the flag 0 and the audit stays clean.
  - `test_tracked_instances_version_bumps`.
  - `test_audit_clean_on_combat_stress`: 120 ticks, as the 1b weapons-mirror test does.
  - `test_switch_off_unchanged`: with the switch off, the existing phaser tests (Step 4) pass.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_native_combat_k2_mirror.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** List every write site of every new field in the report, and route each in-place mutation through a pushing mutator.
- [ ] **Step 4: Run** the new file plus these, and `ctest --test-dir build -R combat_`. Expected: PASS.
  - `tests/unit/test_native_combat_mirror.py`, `test_native_combat_weapons_mirror.py`, `test_native_posed_flag.py`;
  - `tests/unit/test_shield_bubble_wiring.py`, `test_manual_aim.py`;
  - `tests/integration/test_phaser_damage_applied_through_apply_hit.py`;
  - `tests/unit/test_energy_weapon_update_charge.py`;
  - `tests/host/test_native_combat_scene_audit.py`.
- [ ] **Step 5: Commit** (`feat(native-combat): mirror the state K2 reads`).

---

### Task 2: Native beam geometry

**Files:**
- Create: `native/src/combat/include/dauntless/combat/beam_geometry.h`, `native/src/combat/src/beam_geometry.cc`, `native/tests/combat/beam_geometry_test.cc`.
- Modify: `native/src/combat/src/weapon_geometry.cc`. Move `mult_matrix_left`, `world_location`, `xform` and `dot` into a shared internal header; add a `_resolve_bank_aim_world` variant whose target is a world point. Also `CMakeLists.txt` and `host_bindings.cc`.
- Test: `tests/unit/test_native_beam_geometry.py`.

**Interfaces.** These are in `dauntless::combat`, named after the Python functions. Each throws `std::invalid_argument` when unrepresentable. Each has a `combat_test_<name>` binding.
- `phaser_aim_point(ship, target, use_memo) -> {xyz, target_sub_handle | -1}`: map §1.2. It covers the manual offset (F4), the lock's `GetWorldLocation` (F3, with the lock's OWN ship and its pose flag) and the hull centre.
- `strip_emit_position(bank, target_world, use_memo) -> xyz`: F5-F10, with the early returns.
- `accumulate_dwell(bank, dt) -> {flushed, new_dwell}` and `take_dwell(bank) -> {flushed, 0.0}`: F13. These report values and write nothing.
- `ray_sphere_entry(origin, dir, max_dist, center, radius) -> optional xyz | ORIGIN`: F18. The `ORIGIN` marker covers the case where Python returns the origin object itself.
- `world_radius(obj)`.
- `shields_block(target, npc_shields_off, player)`: map §1.5. It throws for a non-ship target or one without a real `GetShields`.
- `shield_bubble_entry(target, origin, dir, max_dist) -> optional xyz`: F15-F16, including the NaN-point case.

- [ ] **Step 1: Write the failing tests.** Seeded `random.Random(20261031)`, 2,000 cases each, comparing against the Python function by `.hex()`. Include the map's edges.
  - `test_strip_emit_matches`: zero projections (F7), a reversed width (F8), length ≤ 0 and NaN.
  - `test_dwell_matches`: NaN countdown and dwell, and the exact 0.5 boundary.
  - `test_aim_point_matches` and `test_lock_on_other_ship_aim_matches`.
  - `test_manual_aim_point_matches`.
  - `test_sphere_entry_matches`: inside the sphere (returns the origin), tangent, and behind.
  - `test_shields_block_matches`: on, off, disabled, destroyed, has_shields 0, cloaking/decloaking, and the dev cheat with and without the player.
  - `test_bubble_matches`: NaN, inside the bubble, `d_len < 1e-12`, `t` beyond `max_dist*d_len`, and a scale ≤ 0.
  - `test_posed_lock_ship_throws`.
- [ ] **Step 2: Run** the file. Expected: FAIL (bindings missing).
- [ ] **Step 3: Implement.** Port line by line in map operand order.
- [ ] **Step 4: Run** the new file plus these, and `ctest -R combat_`. Expected: PASS.
  - `tests/unit/test_strip_emit_position_arc.py`, `test_phaser_arc_handedness.py`, `test_bank_aim_world.py`, `test_arc_gate.py`;
  - `tests/unit/test_combat_hit_resolution.py`, `test_shield_bubble_entry.py`;
  - `tests/unit/test_native_weapon_geometry.py`.
- [ ] **Step 5: Commit** (`feat(native-combat): native beam geometry`).

---

### Task 3: The hull trace as a shared native function

**Files:**
- Modify: `native/src/host/host_bindings.cc`. Extract the `ray_trace_mesh` binding body into `trace_instance_for_python(...)`, used by both the binding and a new `std::function` installer.
- Create: `native/src/combat/include/dauntless/combat/beam_trace.h`, `native/src/combat/src/beam_trace.cc`, holding `resolve_hit_point(...)`. That function ports `combat._resolve_hit_point` plus `host_io.ray_trace_mesh` (F17, F18) and uses the installed callback, with view offsets passed in.
- Test: `tests/host/test_native_beam_trace.py`, a headless host with a real Galaxy instance (follow `tests/host/test_mesh_ray_trace.py`).

**Interfaces:**
- `using TraceFn = std::function<std::optional<TraceHit>(InstanceId, float o[3], float d[3], float max)>`. It throws `StaleInstance` for a stale iid.
- `resolve_hit_point(target, iid_or_none, origin, dir_or_none, max_dist, fallback_point, view_offset_or_none) -> {xyz, normal | none, tier}`, where `tier` is one of `mesh`, `sphere`, `fallback`, `origin`.
- Binding: `combat_test_resolve_hit_point(...)`. It uses the real installed callback.

- [ ] **Step 1: Write the failing tests.** On a real instance, 3,000 seeded rays compared with `combat._resolve_hit_point` by `.hex()`. Cover:
  - hits, misses (sphere tier), inside the sphere (origin);
  - no instance (fallback), a stale iid (sphere), `dir` None, `max_dist` NaN;
  - a scaled ship;
  - a shifted view set.

  Name them `test_trace_matches_python`, `test_stale_and_absent_instance_outcomes` and `test_view_shift_matches`. Also check the binding still returns identical results after the refactor (`test_binding_unchanged`).
- [ ] **Step 2: Run** the test. Expected: FAIL.
- [ ] **Step 3: Implement.** Never recompile `ray_trace.cc` into the combat library.
- [ ] **Step 4: Run** the new file plus `tests/host/test_mesh_ray_trace.py`, `tests/unit/test_combat_hit_resolution.py`, `tests/host/test_render_space_feeds.py`, `ctest -R combat_` and `ctest -R ray_trace`. Expected: PASS.
- [ ] **Step 5: Commit** (`feat(native-combat): native hull trace via the renderer's own function`).

---

### Task 4: The K2 kernel

**Files:**
- Create: `native/src/combat/include/dauntless/combat/k2_beams.h`, `native/src/combat/src/k2_beams.cc`, `native/tests/combat/k2_beams_test.cc`.
- Modify: `CMakeLists.txt` and `host_bindings.cc`.

**Interfaces:**
- **Bindings:**
  - `combat_k2_begin(ship_handles, dt, use_memo, ctx)`. `ctx` holds the iid table, view offsets, the cheat flag and the player handle; the trace callback is installed from the host bindings.
  - `combat_k2_next() -> tuple`, `combat_k2_answer(value)`, `combat_k2_set_ctx(ctx)` (re-send on resume), `combat_k2_end()`, `combat_k2_abandon()`, `combat_k2_kinds() -> dict` and `combat_k2_counts()`.
  - Counts are `k2_records`, `k2_python_ships`, `k2_asks` and `k2_python_reasons`.
- **Records:** per spec §4.1. Every record ends with `writes`. The write log carries `_dwell` writes only; an idle `0.0`-over-`0.0` write is elided.
- **Walk:** map §1.1 verbatim in structure, including:
  - `GetNumWeapons` read once and `GetWeapon(i)` live;
  - `target` read before `IsFiring`;
  - the flush path skipping detect and arc;
  - `_same_set` dropping a banked dwell;
  - `arc_aim` computed even on the flush path;
  - the trace before `shields_block`, and `shields_block` only when `aim_unit` is set;
  - a `CONTACT` record with `flush_dwell` for Python to choose `beam_contact` or `apply_hit`.
- **Fallbacks:** spec §5. The pre-scan runs before any record for a ship. `ASK` per bank, with queries `aim_point`, `is_dead`, `shields_block`, `bubble` and `resolve_hit` (map each to its exact Python call in the header). A throw before the first record for a ship gives `RUN_PYTHON`; after it, `ASK` or the documented invariant. Copy 1b's unwind rollback and its pinning contract.
- **Detect:** reuse 1a's native `can_detect` with K1's clocks.

- [ ] **Step 1: Write the failing gtests** on hand-built rows:
  - `SystemGateStopsEveryTick`;
  - `IdleBankTakesDwellElided`;
  - `DeadOrNoneTargetStops`, `UndetectableStops`, `CrossSetStopsOrDropsDwell`;
  - `WindupContactsEveryTick`, `ArcFailStopsThenFlushes`, `FlushPathSkipsDetectAndArc`;
  - `NumWeaponsReadOnce`;
  - `PrescanRunsPythonBeforeAnyRecord`;
  - `LockShipPosedAsks`;
  - `ResumeReadsLiveMirror`: after a `CONTACT`, change a later bank's target in the mirror and check the next record reflects it;
  - `UnwindLeavesMirrorEqual`.

  Use a fake `TraceFn`.
- [ ] **Step 2: Build and run** `ctest -R combat_K2`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use explicit cursor states, each named after its Python line.
- [ ] **Step 4: Run** `ctest --test-dir build -R combat_ --output-on-failure`. Expected: PASS.
- [ ] **Step 5: Commit** (`feat(native-combat): K2 beams kernel`).

---

### Task 5: Python driver and dispatch

**Files:**
- Modify:
  - `engine/host_loop.py`: the `cb.phasers` loop body moves into `_phaser_step_ship(ship, sys_, dt, ship_instances)`, and the Python path calls it. Add the native branch.
  - `engine/appc/hit_feedback.py`: `beam_contact(..., shields_block=<sentinel>)`. When the argument is given it is used; otherwise the function is unchanged.
  - `engine/appc/native_combat.py`: `run_k2`, the `ASK` answers, the override snapshot for spec §5.3's functions, and the context re-send.
- Test: `tests/unit/test_native_k2_dispatch.py`.

**Interfaces:**
- **`run_k2`.** It applies `writes`, then acts per record:
  - `SYSTEM_STOP` → `sys_.StopFiring()`;
  - `BANK_STOP` → `bank.StopFiring()`;
  - `CONTACT` → rebuild the TGPoint3 objects with tier identity, compute the damage arithmetic exactly as the Python body does, then call `beam_contact(..., shields_block=rec_value)` or `apply_hit(...)`;
  - `RUN_PYTHON` → `_phaser_step_ship`;
  - `ASK` → the exact Python call;
  - after each effect, re-send the context if the player, the cheat flag, the viewing set or `ship_instances.version` changed.
- **Whole-step fallback.** If any snapshot identity check fails, or `ship_instances` is not the session's `TrackedInstances` (and not None), the whole scope runs Python.

- [ ] **Step 1: Write the failing tests.** Each runs a scenario native off and native on with real ships, and compares per tick: every bank's `(_dwell.hex(), _firing, _target is None)`, the call log of `StopFiring` and `beam_contact` (arguments by hex, including `shields_block`) and `apply_hit`, and the event log.
  - `test_beam_volley_matches`;
  - `test_windup_and_flush_matches`;
  - `test_lock_and_manual_aim_match`;
  - `test_shields_drop_mid_volley`;
  - `test_off_system_stops_every_tick`;
  - `test_patched_trace_runs_python_step`;
  - `test_instances_resent_after_mutation`;
  - `test_posed_ship_runs_python`.
- [ ] **Step 2: Run** the file. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus everything in map §8.4 (the "Existing tests on this path" table: name each file), `tests/integration/test_native_k1_differential.py`, `tests/integration/test_native_combat_step_differential.py`, `tests/unit/test_native_k1_dispatch.py`, and `ctest -R combat_`. Expected: PASS.
- [ ] **Step 5: Commit** (`feat(native-combat): K2 dispatch from cb.phasers`).

---

### Task 6: Host-level K2 differential

**Files:**
- Create: `tests/host/test_native_k2_differential.py`.
- Modify: `tests/host/test_native_combat_scene_audit.py`, to assert `k2_records > 0` and that the audit stays clean with K2.

**What the differential does:**
- Builds a headless host with real `g_world` instances and `_cache_shield_hull_box` for every ship, in a seeded fight of at least 8 ships. The scene includes phasers in and out of arc, locks on other ships, Manual Aim on and off, shields up and down, a cloaking target and a posed ship.
- Runs Python (`"0"`) against native (`"1"`) for 300 or more ticks, with render transforms synced identically in both arms.
- Compares, per tick, everything Task 5 compares, plus `ET_WEAPON_HIT` payloads.
- Asserts these counts are above zero in the native arm: `CONTACT`s with tier `mesh` and with tier `sphere`, bubbles not None, and `apply_hit`s.
- Includes `test_handler_kills_target_mid_volley`.

- [ ] **Step 1: Write the test.**
- [ ] **Step 2: Run** it. Expected: PASS. A difference is a porting bug: fix the kernel, a write-through or the driver, never the test.
- [ ] **Step 3: Prove it can fail.** Mutate to drop the bubble, skip the F7 zero test and sort the strip clamp; each must fail. Back up with `cp`, restore, then `diff`.
- [ ] **Step 4: Commit** (`test(native-combat): host-level K2 differential`).

---

### Task 7: Docs

The controller takes the measurements: two runs of the 64-ship fight at the K2 tip.

**Files:**
- Modify:
  - `docs/reference/engine/perf-register.md`: new C- and SIG- rows;
  - `docs/superpowers/specs/2026-10-31-native-combat-k2-beams-design.md` §10 (Outcome);
  - the parent spec §9: a short note that phase 2 is done;
  - `CLAUDE.md`: the native combat row mentions K2 (stay within the length limit in `tests/docs/test_doc_consistency.py`);
  - `k2-beams-map.md`: a header note that it is implemented.

- [ ] **Step 1:** Record the measurements given by the controller.
- [ ] **Step 2: Run** `uv run pytest tests/docs/test_doc_consistency.py -v`. Expected: PASS.
- [ ] **Step 3: Commit** (`docs(native-combat): K2 measurements and outcome`).
