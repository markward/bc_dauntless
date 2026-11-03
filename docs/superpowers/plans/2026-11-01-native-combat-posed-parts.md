# Native combat: posed parts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run ships with articulated (posed) parts through the native K1/K2/K3 kernels bit-exactly, removing the `posed_ship`/`posed_target` fallbacks and the posed `steer_point` ASK.

**Architecture:** Python stays the only resolver of which part a mount sits on; it pushes per-ship pose tables (doubles) and per-subsystem part slots stamped with a global generation. The C++ applies the pose (P1-P4) and falls back when a slot is stale. K1's target-offset mount lookup mirrors Python's subsystem iteration order.

**Tech Stack:** C++17 combat library (`native/src/combat/`), pybind11 bindings (`native/src/host/host_bindings.cc`), Python engine (`engine/appc/`), pytest + gtest.

**Spec:** `docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md`. Map: `docs/reference/engine/native-combat/posed-parts-map.md` (MAP).

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/combat-posed-parts`. Build `cmake --build build -j`; never reconfigure, never cmake inside `native/`, never change BUILD_TYPE; delete the `.o` to force a recompile when mutating.
- Bit-exact: floats compared by `.hex()`, never `pytest.approx`. Python operand order. Pose apply = `detail::mult_matrix_left(r, x)` then `+ t` componentwise. Identity/no-slot/detached = return the input unchanged (branch, never multiply). Every new `.cc` in the combat sources list and `#pragma clang fp contract(off)`.
- Part resolution is computed ONLY in Python (`articulation._live_part` minus the detached test); C++ reads pushed slots. Never call `articulation.leaf_for` from new code; resolve only ships whose `_articulation_leaf` is a non-empty `str`.
- A field the kernel reads MUST push. Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF; OFF is byte-identical. `DAUNTLESS_NATIVE_AUDIT=1` audits the new rows. GIL held.
- Arc/strip/cone DIRECTIONS are NOT posed (copy Python, MAP R7).
- Focused tests only: name every file; never whole suites/directories, never `scripts/check_tests.sh`, never pytest with an empty file list, never `ctest` without `-R`. The engine-class guard (`tests/helpers/engine_class_guard.py`) is active: use `monkeypatch`, never bare class assignment.
- Git: banned `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths; `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Restore a mutated file by `cp`, then `diff`.
- Never spell `game` or `sdk` as a path segment. Never launch `./build/dauntless`.

## Review Focus

1. A posed ship whose slot was resolved before the leaf's model was learned (box rule → `model_nearest_part` changes the answer): must read `part_stale`, never the old part (§4.3 trigger + stamp). Test in Task 1.
2. A severed wing mid-step (`apply_hit` → `sever`): the mount reads its REST point on the very next query (synchronous detached push). Test in Task 1 + Task 5.
3. Identity pose with a `-0.0` mount coordinate: native returns `-0.0` (branch, not multiply). Test in Task 2.
4. Parent and child subsystems sharing a point with different physical parents (R3): K1 `_RESOLVE` picks the same (first, parent) subsystem as Python. Test in Task 3.
5. A scaled posed target (`SetScale`): pose applies before scale. Test in Task 2.

---

### Task 1: Python side — pose tables, part slots, generation, triggers, mirror rows

**Files:**
- Modify: `engine/appc/native_combat.py` (`push_posed_parts`, new `resolve_part_slots`, `bump_part_gen`, `push_mount_order`, `audit_mirror` additions), `engine/appc/articulation.py`, `engine/appc/part_severance.py`, `engine/appc/physical_parents.py`, `engine/appc/properties.py`, `engine/appc/articulated_part.py`, subsystem attach/`_children` sites in `engine/appc/subsystems.py`/`ships.py` as found.
- Modify: `native/src/combat/include/dauntless/combat/mirror.h`, `native/src/combat/src/mirror.cc`, `native/src/host/host_bindings.cc` (storage + bindings only; no kernel use yet).
- Test: `tests/unit/test_native_part_slots.py` (new), plus a gtest in `native/tests/combat/` for the new rows' storage/dump.

**Interfaces (produces):**
- Mirror: Object row `part_poses: std::vector<PartPose>` with `struct PartPose { double r[9]; double t[3]; bool identity; bool detached; }`; Object row `mount_order: std::vector<int64_t>` (subsystem handles); Subsystem row `int32_t part_slot = -1; uint64_t part_gen = 0;`; global `uint64_t part_gen`.
- Bindings: `combat_set_part_poses(h, list[tuple(r9, t3, identity, detached)])`, `combat_set_part_slot(h_sub, slot, gen)`, `combat_set_mount_order(h, list[int])`, `combat_set_part_gen(gen)`; `combat_dump` shows them.
- Python: `native_combat.bump_part_gen()`, `native_combat.part_gen() -> int`, `native_combat.resolve_part_slots(ship) -> None`, `native_combat.resolve_stale_part_slots(ships) -> None` (called by Task 4 at step boundaries), `native_combat.push_mount_order(ship)`.

- [ ] **Step 1: Write failing tests** in `test_native_part_slots.py`: `test_pose_table_matches_articulation_poses` (BoP in cruise via `articulation.force_state_poses` or ticking to cruise: table order == `posed_part_names`, r/t `.hex()` equal, identity bits equal Python `is_identity`); `test_slot_matches_live_part` (every subsystem's slot names the part `_live_part` returns for its `_position` + `property_of`); `test_detached_bit_pushed_synchronously_on_sever`; `test_each_trigger_bumps_generation` (parametrised over every §4.3 trigger row); `test_slot_resolved_before_model_learned_reads_stale_after` (Review Focus 1); `test_mount_order_matches_iter_subsystems`; `test_unposed_ship_pushes_empty_table`; `test_switch_off_pushes_nothing` (no binding called); `test_audit_mirror_compares_pose_table` (corrupt a native entry → audit reports it).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_native_part_slots.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** storage, bindings, pushes, triggers, resolution.
- [ ] **Step 4: Run** the new file + `tests/unit/test_native_posed_flag.py tests/unit/test_target_offset_articulation.py tests/unit/test_physical_parents.py tests/unit/test_physical_parent_consumers.py tests/unit/test_part_severance.py tests/unit/test_articulation_transitions.py tests/unit/test_part_pose.py tests/unit/test_native_combat_mirror.py` and `ctest --test-dir build -R combat_`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(native-combat): mirror pose tables and part slots`.

### Task 2: Native pose geometry (P1-P4)

**Files:**
- Create: `native/src/combat/include/dauntless/combat/part_pose.h`, `native/src/combat/src/part_pose.cc`.
- Modify: `native/src/combat/src/weapon_geometry.cc` (`mount_position`, `target_offset_world` gain the posed branch behind `has_posed_parts`), `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`, `host_bindings.cc` (`combat_test_*` bindings).
- Test: `native/tests/combat/part_pose_test.cc`, `tests/unit/test_native_part_pose_geometry.py`.

**Interfaces:**
- Consumes Task 1 rows.
- Produces: `Vec3 apply_part_pose(const PartPose&, const Vec3&)` (P1/P2); `enum class SlotState { none, ok, stale }` and `SlotState posed_local(const Mirror&, const ObjectRow& ship, const SubsystemRow& sub, Vec3* out)`; `mount_position(...)` posed-aware (stale → throws the same `fall_back` type with a distinguishable reason `part_stale`); `target_offset_world(..., int64_t mount_sub, ...)` posed-aware, with `mount_sub == kNoMount` meaning `authored=False` → identity; bindings `combat_test_mount_position(h_sub, h_ship)`, `combat_test_target_offset_world(h_target, offset, h_mount_or_none)`.

- [ ] **Step 1: Failing tests**, seeded 2,000 cases each vs Python by `.hex()`: `test_mount_matches_subsystem_world_position` (posed ships incl. mid-transition, detached part, identity with `-0.0`); `test_target_offset_matches_python` (posed target, scaled target, mount given / not given); `test_stale_slot_raises_part_stale`; `test_unposed_path_unchanged` (has_posed_parts 0 → bit-identical to before, no slot read). gtests: `IdentityBranchKeepsSignedZero`, `PoseBeforeRotation`, `PoseBeforeScale`, `DetachedReadsRest`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new files, `tests/unit/test_native_weapon_geometry.py` (if present; else the K1 geometry test file), `tests/unit/test_native_beam_geometry.py`, `tests/unit/test_native_projectile_geometry.py`, `ctest --test-dir build -R combat_`. **Step 5: Commit** `feat(native-combat): native posed mount and target-offset geometry`.

### Task 3: Native mount lookup for target offsets (K1 `_RESOLVE`)

**Files:** `native/src/combat/src/part_pose.cc` (or a sibling), `host_bindings.cc`, tests.

**Interfaces:** Produces `int64_t authored_mount_subsystem(const Mirror&, const ObjectRow& target, const Vec3& offset)` — first subsystem in `mount_order` whose `_position` matches `offset` by Python's exact comparison (PS:511-512, same operand order and 1e-5), else `kNoMount`; binding `combat_test_authored_mount(h_target, offset)`.

- [ ] **Step 1: Failing tests:** `test_authored_mount_matches_python` (2,000 seeded offsets: exact mounts, ±0.9e-5, ±1.1e-5, NaN); `test_parent_child_same_point_picks_parent` (Review Focus 4); `test_mount_order_change_is_pushed` (attach a child → order updates).
- [ ] **Step 2-4:** run → FAIL → implement → run the new file + Task 1/2 files + `ctest -R combat_`.
- [ ] **Step 5: Commit** `feat(native-combat): native authored mount lookup`.

### Task 4: Kernels use the posed path

**Files:** `native/src/combat/src/k1_fire_control.cc`, `k2_beams.cc`, `projectile_geometry.cc`/`k3_projectiles.cc`, their headers (reason enums), `engine/appc/native_combat.py` (call `resolve_stale_part_slots` at step boundaries — `step_scan`, `k1_pump`, `k1_system` begin — and the counters/reason names), tests.

**Interfaces:** K1: remove `PosedShip` (K1C:438) and `PosedTarget` (K1C:473) prescan fallbacks; geometry handles posed; stale slot → new `K1Why::part_stale`. K2: remove `PosedShip` (K2C:315); lock-ship `aim_point` uses P3; keep the ASK for Manual Aim only; stale → `K2Why::part_stale`. K3: PG:310 posed condition becomes "mount slot usable and offset == mount position bit for bit", else ASK. Reason enums keep `posed_ship`/`posed_target` (counted 0) and add `part_stale`.

- [ ] **Step 1: Failing tests:** extend `tests/unit/test_native_k2_dispatch.py`, `tests/unit/test_native_k3_dispatch.py` and the K1 dispatch test file with: `test_posed_ship_fires_natively` (K1, beam + pulse + tube; per-tick `.hex()` vs Python arm, zero RUN_PYTHON for posed reasons); `test_posed_target_tube_aim_native` (K1 `_RESOLVE`); `test_posed_ship_beams_natively` (K2); `test_lock_on_posed_ship_needs_no_aim_ask` (K2); `test_posed_target_steer_point_native` (K3); `test_stale_slot_falls_back_part_stale` (each kernel); `test_resolve_runs_at_step_boundary`.
- [ ] **Step 2-4:** FAIL → implement → run those three dispatch files, Task 1-3 test files, `tests/unit/test_native_posed_flag.py`, `ctest -R combat_`.
- [ ] **Step 5: Commit** `feat(native-combat): kernels run posed ships natively`.

### Task 5: Posed differentials and scene audit

**Files:** Create `tests/integration/test_native_posed_differential.py` (headless) and `tests/host/test_native_posed_differential.py` (real instances); modify `tests/host/test_native_combat_scene_audit.py`. Reuse `tests/helpers/k3_fight.py` (recorder/compare/tally; extend it rather than copy).

- [ ] **Step 1: Write the tests:** a seeded fight with ≥2 Birds of Prey (one settled in cruise, one mid-transition via alert changes), Fed ships, both sides firing phasers, pulse and torpedoes with subsystem locks on the BoPs; a wing severed mid-fight; 600+ ticks at 1 and 4 ticks per frame; per-tick `.hex()` compare of everything K3's differential compares plus mount positions; assert posed reasons and `part_stale` are 0 and posed branch counts > 0 (posed firing, posed target aim, posed steer point). Scene audit: unaudited combat_stress → posed reasons 0; audited → pose table/slots audit clean.
- [ ] **Step 2: Run** → PASS (a difference is a porting bug: fix code, never the test).
- [ ] **Step 3: Mutation proofs:** pose after rotation; direction posed; identity multiplied; stale stamp ignored; child-before-parent order. Each must fail a test; restore by `cp` + `diff`.
- [ ] **Step 4: Run** the K1, K2, K3 differentials and the scene audit with the new files, both orders.
- [ ] **Step 5: Commit** `test(native-combat): posed-part differentials`.

### Task 6: Docs

**Files:** spec §10 Outcome; `posed-parts-map.md` header (implemented); CLAUDE.md "Physical parents" or native-combat row (within `tests/docs/test_doc_consistency.py` limits); roadmap §2 table row.

- [ ] **Step 1:** write. **Step 2:** `uv run pytest tests/docs/test_doc_consistency.py -q` → PASS. **Step 3: Commit** `docs(native-combat): posed parts outcome`.
