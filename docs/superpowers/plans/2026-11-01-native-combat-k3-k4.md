# Native Combat Step — Phase 3 (K3 Projectiles + K4 Eligibility) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `cb.eligibility` (`damage_eligibility.update`) and `cb.projectiles` (`projectiles.update_all`'s guide, advance, broadphase and narrow phase) into C++, bit-identical to Python with the switch on, byte-identical behaviour with it off.

**Architecture:** One per-step scan gives K4 and K3 the ship handles and the sets in play; Python resolves those sets' frames every step. K4 is one pure call returning the eligible ships. K3 is one batch kernel over a new torpedo table (synced like `TorpedoScan`), using K1's record protocol only for `ASK`s and a final `DONE` with a write log, the ordered expiries and the hits; Python keeps `expire()`, `apply_hit` and the hit-list build.

**Tech Stack:** C++20 (`native/src/combat/`, gtest), pybind11 (`native/src/host/host_bindings.cc`), Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-native-combat-k3-k4-design.md`. Input map: `docs/reference/engine/native-combat/k3-k4-map.md` ("map §x", G#, A#, B#, E#). The parent spec §7.5 and §9.1-§9.2 and the K2 spec (§4-§6, ruling C2 in its §10) bind as well.

## Global Constraints

- **Worktree and branch.** Work in `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `perf/native-combat-k3`.
  - Build: `cmake --build build -j`. Never run cmake inside `native/`. Never change `CMAKE_BUILD_TYPE`. To force a recompile when mutating C++, delete the `.o`.
- **Bit-exact.**
  - Compare floats by `.hex()`, never `pytest.approx`.
  - `** 0.5` → `py_pow`; `Length` → `std::sqrt`; `math.dist` → `dist3`; `sin` → `py_sin`; `min`/`max` → `py_min`/`py_max` in Python argument order. Keep Python operand order; port every NaN branch as Python has it.
  - Every new `.cc` goes in the combat sources list (`-ffp-contract=off`) and carries `#pragma clang fp contract(off)`.
- **Constants.** Named module constants are pushed from Python (`_LEAD_ACCEL_K`, `PROX_WEIGHT`, `SIZE_WEIGHT`); inline literals are ported verbatim with a comment citing the Python line (ruling G).
- **The switch.** `DAUNTLESS_NATIVE_COMBAT=1` turns it on; OFF by default; with it OFF behaviour is byte-identical. K3/K4 run only when `native_combat.enabled()` and not under `DAUNTLESS_NATIVE_AUDIT=1` (they stand down with reason `"audit"`, as K2).
- **GIL** held throughout (ruling J).
- **One copy of each effect.** `expire()`, `apply_hit`, `select_eligible` and every Python decision function stay as they are and remain the reference; the kernel holds the second copy of each decision rule only.
- **A field the kernel reads MUST push** (a `Native*` descriptor or a pushing mutator); parent §9.1.
- **Focused tests only.** Name every file. Never run whole suites or directories, `scripts/check_tests.sh`, ctest without `-R`, or pytest with an empty file list.
- **Shared-checkout git rules.** Never use `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A` or `git add .`. Stage explicit paths; commit with `git commit -F <file>`; end each message with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Restore a mutated file by `cp`, then `diff` to prove it identical.
- **Path rule.** Never spell `game` or `sdk` as a path segment.
- **Never launch `./build/dauntless`.** Host-level tests use the headless host fixture the existing `tests/host/` files use.
- **Test isolation.** Differentials call `tests/helpers/fight_audio.isolate_fight_audio` per arm (K2 precedent).

## Review Focus

1. **A torpedo launched by an SDK handler during the HL:1320 `apply_hit` loop** (or by `cb.held_weapons` after `cb.projectiles`). It must get a row at `_active` append and first move next tick. Tested in Task 1 (`test_append_adds_row_in_list_order`) and Task 5 (`test_handler_launch_moves_next_tick`).
2. **`_active` mutated other than by append/remove** (a fixture `clear()`, `insert`, slice assignment, or a plain list swapped in). The table must rebuild from Python state in list order, or the step must run Python. Tested in Task 1 (`test_dirty_table_rebuilds_from_python`) and Task 5 (`test_plain_list_active_runs_python`).
3. **Two torpedoes hitting a ship the first one kills, in one tick.** Both hits are decided on the static world and both applied. Tested in Task 6 (`test_two_hits_on_one_ship_same_tick`).
4. **A target or the player changing region or set between ticks** (in-system warp hand-off). Frames are re-resolved every step, so homing, broadphase and eligibility use the new offset at once. Tested in Task 2 (`test_frame_table_resolved_every_step`) and Task 6 (cross-region scenario).
5. **An `ET_WEAPON_HIT` handler mutating `GetHitPoint()` in place on a bubble hit.** `shield_point` must move with it, as today. Tested in Task 5 (`test_bubble_hit_point_is_shield_point`).

---

### Task 1: Mirror what K3 and K4 read

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/mirror.h`, `native/src/combat/src/mirror.cc`, `native/tests/combat/mirror_test.cc`; `engine/appc/native_combat.py`; `engine/appc/projectiles.py` (Torpedo fields, `_ActiveList` hooks); `native/src/host/host_bindings.cc`.
- Create: `native/src/combat/include/dauntless/combat/torpedo_table.h`, `native/src/combat/src/torpedo_table.cc` (or extend `mirror.*` if that reads better; one responsibility per file).
- Test: `tests/unit/test_native_combat_k3_mirror.py`.

**Interfaces:**
- Consumes: 1b/K2 `Native*` descriptors, `push_field`, `register`, `audit_mirror`, `_hidden_fields`, the `_ActiveList` scan hooks (`_scan_add`, `_scan_drop`, `_scan_dirty`, `_scan_rebuild`).
- Produces:
  - Object row field `py_id` (uint64, the object's `id()`, written at register, never changes).
  - Torpedo table: rows in `_active` order with tombstones, keyed by a torpedo handle stored on the Python object (`_k3_row`), fields per spec §4.3: `xform`, `age`, `ttl`, `guidance_lifetime`, `guidance_initial`, `max_angular_accel`, `vel[3]`, `target` (ref), `target_offset[3]` + `target_offset_set`, `source` (ref), `cset` (ref), `last_seen[3]` + set flag, `last_tvel[3]` + set flag, `mount_sub` (ref) + `mount_attributed` + `mount_offset[3]`.
  - Python: `native_combat.torpedo_row_add(t)`, `torpedo_row_drop(t)`, `torpedo_table_mark_dirty()`, `torpedo_table_rebuild(active)`; every writer of the fields above pushes while the torpedo has a row.
  - Global `LEAD_ACCEL_K` pushed from `projectiles._LEAD_ACCEL_K`.
  - `audit_mirror` compares every torpedo row against its Python object (by `.hex()`), and `py_id` against `id()`.

- [ ] **Step 1: Write the failing tests:** `test_py_id_matches_id`; `test_append_adds_row_in_list_order`; `test_remove_drops_row`; `test_dirty_table_rebuilds_from_python` (clear, insert, slice assignment, sort); `test_sdk_setters_push` (`SetLifetime`, `SetGuidanceLifetime`, `SetMaxAngularAccel`, `SetTargetOffset`, `_target_ship`, `_source_ship`, `_containing_set`, `_velocity`, `_last_seen_target_pos`, `_last_target_vel`, `_mount_key`, `_age`); `test_audit_compares_torpedo_rows` (a forced mismatch is reported); `test_switch_off_registers_nothing`. Plus gtests `TorpedoTable.AddDropKeepsOrder`, `TorpedoTable.TombstonesCompact`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file, `tests/unit/test_torpedo_scan_conformance.py`, `tests/unit/test_torpedo_set_membership.py`, `tests/unit/test_torpedo_advance.py`, `tests/unit/test_native_combat_k2_mirror.py`, and `ctest --test-dir build -R combat_`. Expected: PASS.
- [ ] **Step 5: Commit** (`feat(native-combat): mirror torpedo rows and py_id for K3/K4`).

---

### Task 2: Step scan, frame table and K4

**Files:**
- Create: `native/src/combat/include/dauntless/combat/k4_eligibility.h`, `native/src/combat/src/k4_eligibility.cc`, `native/tests/combat/k4_eligibility_test.cc`.
- Modify: `native/src/host/host_bindings.cc`, `engine/appc/native_combat.py`, `engine/appc/damage_eligibility.py` (`update` only), `engine/host_loop.py` (call the step scan at the top of `cb.eligibility`).
- Test: `tests/unit/test_native_k4_eligibility.py`.

**Interfaces:**
- `combat_step_scan(ships_list) -> (representable: bool, reason: str | None, set_handles: list[int])`; keeps the ship-handle array native-side for K4 and K3 this step. Same unseen-class and patched rules as K2 (C2).
- `combat_step_frames(table)` where `table` is `[(set_handle, key_id, ax, ay, az), ...]`; Python builds it from `frames.frame_of(set)` for every handle the scan returned, every step (spec §4.1). `offset_between` natively: same handle → exact zeros if a SetClass row, different keys → none, else `b - a` per component.
- `combat_k4_eligible(player_handle, max_count, prox_w, size_w) -> list[int] | None` (indices into `ships_list`; None = Python). Exactness E1-E4 per spec §4.2.
- `native_combat.step_scan(ships_list)` returns the per-step state K3 also uses (`_StepScan`), and `damage_eligibility.update` branches to `native_combat.k4_update(player, ships)` when enabled.

- [ ] **Step 1: Write the failing tests:** seeded `random.Random(20261101)`, 2,000 scenes of 0-70 ships, comparing the native set to `select_eligible` exactly: `test_k4_matches_select_eligible`; `test_k4_ties_break_by_id` (identical ships at equal distance); `test_k4_cross_frame_gets_no_proximity`; `test_k4_no_player_size_only`; `test_k4_all_zero_radii_or_one`; `test_k4_nan_or_inf_falls_back`; `test_k4_duplicate_ship_falls_back`; `test_k4_patched_function_falls_back` (each snapshot target); `test_frame_table_resolved_every_step` (a set's frame changes between steps; the next step uses the new one). gtests `K4.TieBreak`, `K4.MaxROrOne`, `Frames.SameSetShortCircuit`, `Frames.DifferentKeysNone`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file, `tests/unit/test_damage_eligibility.py`, `tests/integration/test_frame_tripwire.py`, `tests/unit/test_native_k2_dispatch.py`, and `ctest -R combat_`. Expected: PASS.
- [ ] **Step 5: Commit** (`feat(native-combat): step scan, per-step frame table and K4 eligibility`).

---

### Task 3: Native projectile geometry

**Files:**
- Create: `native/src/combat/include/dauntless/combat/projectile_geometry.h`, `native/src/combat/src/projectile_geometry.cc`, `native/tests/combat/projectile_geometry_test.cc`.
- Modify: `CMakeLists.txt`, `host_bindings.cc`.
- Test: `tests/unit/test_native_projectile_geometry.py`.

**Interfaces** (in `dauntless::combat`, named after the Python functions, each throwing `std::invalid_argument` when unrepresentable, each with a `combat_test_<name>` binding):
- `bubble_bound_radius(ship)` (B1, with `world_radius`'s and `_hull_box_for`'s rules from K2's `beam_geometry`);
- `sphere_hit(p, c, r)` (A8);
- `guide_torpedo(row, dt, frames, use_memo, clocks) -> GuideResult` (G1-G12; the field writes as a result struct in Python write order; returns "needs steer_point ASK" for a posed target or an unattributed mount, "needs guide ASK" per spec §4.4);
- `advance_torpedo(prev, vel, dt, age, ttl) -> {cur, age, expired, seg, seg_len, aim_unit | none}` (A1-A6);
- `steer_point_unposed(target, offset, mount_sub, off)` reusing `weapon_geometry`'s `target_offset_world`.

- [ ] **Step 1: Write the failing tests:** seeded, 2,000 cases each against the Python functions by `.hex()`: `test_bubble_bound_matches` (no box, off-centre box, scale ≤ 0, NaN radius, unreadable radius → inf); `test_sphere_hit_matches` (NaN); `test_guide_matches` (visible/invisible/never-seen, dead, other frame, `speed < 1e-6`, `dist < 1e-6` after the writes, slerp vs snap, NaN aim, guidance window edge, re-emerge acc spike, cross-region `dist_sq_gu`); `test_advance_matches` (TTL boundary, NaN age, `seg_len ≤ 1e-9`); `test_steer_point_matches` (no offset, offset, scaled, rotated target); `test_posed_target_needs_ask`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Port line by line in map operand order.
- [ ] **Step 4: Run** the new file, `tests/unit/test_torpedo_guidance_fidelity.py`, `tests/unit/test_torpedo_subsystem_homing.py`, `tests/unit/test_projectile_broadphase.py`, `tests/unit/test_native_beam_geometry.py`, `ctest -R combat_`. Expected: PASS.
- [ ] **Step 5: Commit** (`feat(native-combat): native projectile geometry`).

---

### Task 4: The K3 kernel

**Files:**
- Create: `native/src/combat/include/dauntless/combat/k3_projectiles.h`, `native/src/combat/src/k3_projectiles.cc`, `native/tests/combat/k3_projectiles_test.cc`.
- Modify: `CMakeLists.txt`, `host_bindings.cc`.

**Interfaces:**
- Bindings: `combat_k3_begin(dt, clocks, use_memo, ctx)`, `combat_k3_next() -> tuple`, `combat_k3_answer(value)`, `combat_k3_end()`, `combat_k3_abandon()`, `combat_k3_kinds()`, `combat_k3_counts()` (`k3_runs`, `k3_python_steps`, `k3_asks` by kind, `k3_python_reasons`). `ctx` = K2's context plus the step scan and frame table from Task 2.
- Records per spec §4.4: `ASK frame|steer_point|guide|<K2 narrow asks>`, `DONE(writes, expired, hits)`. `writes` per torpedo: `age`, and for guided: `vel`, `last_seen`, `last_tvel`. `hits` entries per spec §4.5 (torpedo handle, ship handle, hit xyz, tier, normal | none, bubble xyz | none, `hit_is_bubble`). `expired`: TTL first, then hits, each in table order.
- Walk: map §A6 verbatim in structure (spec §4.4 steps 1-4). Broadphase calls the existing `sweep_candidates` in-process for same-set ships and the shifted test (B2) otherwise. Positions are written to the `TransformStore` directly (spec §4.3).
- Detect: native `can_detect` in torpedo list order with K1's clocks (memo only for the plain call; `dist_sq_gu` for cross-region; the `off is None` case still asks).

- [ ] **Step 1: Write the failing gtests** on hand-built rows with a fake `TraceFn`: `GuideThenAdvanceEveryTorpedoBeforeNarrow`; `TtlExpiriesFirstInExpired`; `TtlTorpedoStillGuidedNotHitTested`; `FirstHitByShipIndexWins`; `SourceShipNeverHit`; `DeadAtStartShipNotCached`; `BubbleHitWritesStoreOnBubble`; `CrossRegionCandidateUsesShiftedTest`; `PosedTargetAsksSteerPoint`; `UnattributedMountAsksSteerPointOnce`; `StubIsDeadTargetAsksGuide`; `MissingFrameAsksFrame`; `CanDetectCalledInListOrder` (latch state after a sequence matches the Python order); `AbandonLeavesMirrorEqual`.
- [ ] **Step 2: Build and run** `ctest --test-dir build -R combat_K3`. Expected: FAIL.
- [ ] **Step 3: Implement.** Explicit cursor states, each named after its Python line.
- [ ] **Step 4: Run** `ctest --test-dir build -R combat_ --output-on-failure`. Expected: PASS.
- [ ] **Step 5: Commit** (`feat(native-combat): K3 projectiles kernel`).

---

### Task 5: Python driver and dispatch

**Files:**
- Modify: `engine/appc/projectiles.py` (`update_all`: after `if not _active: return hits`, the native branch); `engine/appc/native_combat.py` (`run_k3`, ASK answers, write-log apply, hit build, whole-step reasons, snapshot of map §A8.3.9's patch points and replaced functions); `tests/unit/test_native_k2_override_guard.py` → extend, or create `tests/unit/test_native_k3_override_guard.py`, for the K3/K4 stood-in methods (spec §7).
- Test: `tests/unit/test_native_k3_dispatch.py`.

**Interfaces:**
- `run_k3(dt, all_ships, ship_instances) -> list[tuple] | None` (None = run the Python body). On `DONE`: apply writes without re-pushing to the torpedo row, leaving the scan table's velocity as the `_velocity` setter would; `expire(t)` for each of `expired` in order; build `hits` with spec §4.5's identity (`t._bubble_entry` set for the hit torpedo only).
- Whole-step reasons (spec §4.4): `"off"`, `"audit"`, `"plain_active"`, `"scan"`, `"patched"`, `"row"`, `"guard"`.

- [ ] **Step 1: Write the failing tests.** Each runs a scenario native off and on with real ships and torpedoes, comparing per tick every torpedo's position/velocity/age/guidance fields by `.hex()`, the `ET_TORPEDO_EXITED_SET`/`ET_WEAPON_HIT` sequence, and the returned `hits` (by hex, plus identities): `test_volley_matches`; `test_ttl_and_hit_expire_order`; `test_bubble_hit_point_is_shield_point`; `test_handler_launch_moves_next_tick`; `test_plain_list_active_runs_python`; `test_patched_target_visible_runs_python` (and each other snapshot target); `test_posed_target_asks_and_matches`; `test_write_log_keeps_scan_velocity`; `test_switch_off_unchanged_calls`.
- [ ] **Step 2: Run** the file. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file, the override guard file(s), every file in map §A8.4's table (name each), `tests/integration/test_native_k1_differential.py`, `tests/integration/test_native_combat_step_differential.py`, `tests/unit/test_native_k2_dispatch.py`, and `ctest -R combat_`. Expected: PASS.
- [ ] **Step 5: Commit** (`feat(native-combat): K3 dispatch from cb.projectiles`).

---

### Task 6: K3/K4 differentials

**Files:**
- Create: `tests/integration/test_native_k3_differential.py` (headless) and `tests/host/test_native_k3_differential.py` (real instances and hull boxes; template `tests/host/test_native_k2_differential.py`).
- Modify: `tests/host/test_native_combat_scene_audit.py` (unaudited run asserts K3 and K4 ran with zero whole-step fallbacks).

**What the differentials do:** Python arm vs native arm per tick for 600+ ticks, at 1 and 4 ticks per frame, in a seeded torpedo fight (8+ ships, both sides launching), comparing everything Task 5 compares plus `damage_eligibility._current` (as id sets) and the can_detect latch. Branch counts > 0 in the native arm for every branch in spec §7's list (guided visible / invisible / ballistic, window end, TTL, cross-region hit and homing, bubble hit, mesh and sphere tiers (host file), posed-target ASK, mount ASK, K4 ties and cross-frame ships). Include `test_two_hits_on_one_ship_same_tick`. Report the fallback reason breakdown.

- [ ] **Step 1: Write the tests.**
- [ ] **Step 2: Run** them. Expected: PASS. A difference is a porting bug: fix the kernel, a write-through or the driver, never the test.
- [ ] **Step 3: Prove they can fail:** mutate (a) hits-before-TTL in `expired`, (b) `seg = v*dt`, (c) `sqrt` for `centre_len`, (d) the `id()` tie-break reversed, (e) skip the `off is None` can_detect call; each must fail a test. Back up with `cp`, restore, `diff`.
- [ ] **Step 4: Run** the K1 and K2 differentials and the scene audit, in both orders with the new files. Expected: PASS.
- [ ] **Step 5: Commit** (`test(native-combat): K3/K4 differentials`).

---

### Task 7: Docs

The controller takes the measurements: two runs of the 64-ship fight at the K3 tip.

**Files:** `docs/reference/engine/perf-register.md` (C- and SIG- rows); the K3/K4 spec §10 (Outcome); the parent spec §9 (phase 3 done note); `CLAUDE.md` native-combat row (within `tests/docs/test_doc_consistency.py`'s limit); `k3-k4-map.md` header (implemented).

- [ ] **Step 1:** Record the measurements given by the controller.
- [ ] **Step 2: Run** `uv run pytest tests/docs/test_doc_consistency.py -q`. Expected: PASS.
- [ ] **Step 3: Commit** (`docs(native-combat): K3/K4 measurements and outcome`).
