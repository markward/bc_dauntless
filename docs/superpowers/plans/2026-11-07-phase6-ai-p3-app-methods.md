# Phase 6 AI, Part 3 — The Hot SDK-Facing App Methods — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move five App methods that SDK scripts and our AI call at high volume onto native code: `GetWorldLocation`, `GetNearObjects`, `IsTypeOf`, `GetVelocityTG`, `StartFiring`. Return values, the objects returned, and the exceptions raised stay bit-identical.

**Architecture:** This follows SIG-198's recommendation, "thin Python over native".
- Each method stays a Python function on its engine class. That keeps class-level identity, snapshots, subclass overrides and mod patches meaning what they mean today.
- Its body makes one native call that does the work and builds the result in C++.
- Point getters return a real `TGPoint3`, allocated in C++ with its three slots written directly. There is no native point type: `.x` reads would get 13× slower.
- `GetNearObjects` computes candidate radii and participation natively instead of calling Python `GetRadius` once per candidate per query.
- `StartFiring` runs its gates and writes natively and cuts the per-call Python session glue. A measurement inside the task decides which parts of the glue go.

**Tech Stack:** C++20 (`native/src/combat`, `native/src/transforms`, `-ffp-contract=off`), CPython C API / pybind11 (`native/src/host/host_bindings.cc`), Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §4 (Part B), §3 "Mods and patches (Part A)", §2 anti-goals, §7. B0 is SIG-198 in `docs/reference/engine/perf-register.md` (harness `tools/bench/boundary_bench.py`).

## Scope, and what it buys (Mark ruled 2026-11-07: keep the original list)

The numbers are from SIG-206's native cProfile (C-420, 128 ships, relative):

| Method | Profiled | Where |
|---|---|---|
| `GetNearObjects` | 4.43 s | 2.38 s of it is `_size` → `GetRadius`, 6.35 M calls (≈ 133 a query); native compare 0.08 s |
| `StartFiring` | 3.43 s (base), torpedo 1.77, held 1.68 | Python gates + writes ≈ 0.6 s; `run_k1` session glue ≈ 2.7 s |
| `GetWorldLocation` | 2.79 s, 1.83 M calls | half from `systems/frames.py:180 _xyz` (outside AI) |
| `IsTypeOf` | 0.32 s | 171 k calls, all from the native FireScript calling back `ShipSubsystem.IsTypeOf` |
| `GetVelocityTG` | 0.23 s | 297 k calls |

`GetNearObjects` and `StartFiring` carry the gain. `IsTypeOf` and `GetVelocityTG` are small by measurement, and are in scope on Mark's ruling. Task 7 states plainly what each one bought.

## Global Constraints

- Worktree `.claude/worktrees/phase6-ai`, branch `ws/ai-p3-app-methods`, cut from `project/phase6-ai` at `f85d00445`.
- **Never run the gate or whole suites.** Run focused files only, listed literally. Never pass an empty or unsplit pytest list. Tree guards are allowed: `tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`.
- No destructive git. Stage explicit paths. Temporary mutations: cp backup → mutate → run → cp back → diff.
- **Golden fights (`tests/integration/test_golden_fights.py`) and the Part 2 A/B (`tests/integration/test_native_ai_ab.py`) stay byte-identical. Never set `UPDATE_COMBAT_GOLDEN`.**
- **Bit-exact returns:**
  - same values (doubles), same types (`TGPoint3` with Python `float` slots, `int` 0/1 where the Python returns 0/1, `_ProximityIteration`);
  - a FRESH object on every call where the Python returns one;
  - the same exceptions: a stale transform handle raises `StaleHandleError` with today's message, and an attribute error raises the same `AttributeError`.
- **Each method stays a Python function on its engine class.** Kernel M's `_SURFACE` snapshot, `native_combat`'s stock-surface name lists, the Part 2 reader contracts (`ai_native._take_reader_bodies`), `proximity_table.location_is_stored` and `ai_optimized._AVOID_SURFACE` all compare these functions by identity. They must keep working unchanged, and they see the new functions because those are what the classes hold at import. Bodies that subclasses override stay untouched unless a task names them: `DebrisChunk.GetWorldLocation` returns its live `_loc`; `ShipSubsystem.GetWorldLocation`; `Torpedo._velocity` is a property.
- **The non-native transform store** (`transform_store.py`'s Python backend, used by some tests) keeps its old path. Check `type(store) is NativeTransformStore` (the store the method actually calls through `engine.appc.objects.get_store`), and take the Python path otherwise.
- **Mods and patches:** a patched App method changes what callers see, exactly as in BC (spec §3). Native callers inside our engine (the Part 2 bindings) keep calling App methods by attribute lookup, so they see patches too.
- **The native-reader contract** (Part 1 `set_index.h`, Part 2): borrowed keys only under the GIL; no borrowed pointer held across a Python call; allocate output before reading set-index keys.
- Build with `cmake --build build -j` from the worktree root. Never launch the game without asking Mark.

## Review Focus

1. **SDK code mutates returned points in place** (`vDiff.Subtract(...)`, `EvadeTorps.UpdateTorpInfo`). Every getter must return a distinct object each call; Task 1 pins aliasing.
2. **A candidate whose type overrides `GetRadius`** (`ProximityCheck`, `DebrisChunk`, `RockClass`, a mod class) or whose `GetRadius` raises. `_size` answers 0.0 on any exception. Task 5 pins both.
3. **A radius or scale changing between two queries** with no generation bump (`test_planet_radius_change_between_queries_is_seen`). Native radii must be read at query time, never cached across queries.
4. **`StartFiring` overridden per class** (torpedo ammo gate, held-fire None target, tractor). Also: an instance or class patch of `StartFiring` that the native FireScript must still reach through attribute lookup. Task 6 pins both.
5. **The Python transform-store backend**, and a monkeypatched `engine.appc.objects.get_store`. Both must take the Python path. Tasks 2 and 3 pin it.

---

### Task 1: A native `TGPoint3` constructor and its benchmark

**Files:**
- Modify: `native/src/host/host_bindings.cc` (a shared helper and its registration), `tools/bench/boundary_bench.py` (a new `bind_slots` variant), `engine/appc/math.py` (registers `TGPoint3` with the binding at import: `_h.point_register(TGPoint3)`)
- Test: `tests/unit/test_native_point.py`, `tests/tools/test_boundary_bench.py`

**Interfaces:**
- Produces, in C++: `PyObject* make_point(double x, double y, double z)`, which returns a new reference. It allocates the registered type with `tp_alloc` and writes the three `__slots__` members through their `PyMemberDescr` offsets (read once from the type at registration). It never runs `__init__`. The slot values are new Python floats. It throws if no type is registered or the type's layout isn't three float slots `x, y, z`.
- Produces: the binding `point_register(cls)`. It validates that `cls.__slots__ == ("x", "y", "z")`, that it defines no `__new__`, and that `__init__` is the engine's, then caches the offsets.
- Bench: `bind_slots` (raw `METH_FASTCALL` reading a store position into `make_point`) beside `bind_new_obj`. Report the ns per call and allocations as SIG-198 did.

- [ ] **Step 1: Write the failing tests:**
  - `test_make_point_equals_the_python_constructor` checks type, `float` slot types, values by `float.hex`, including -0.0, NaN and inf.
  - `test_make_point_returns_a_fresh_object_each_call` mutates one result and checks that a second is untouched (Review Focus 1).
  - `test_register_rejects_a_class_with_another_layout`.
  - In the bench test, the `bind_slots` variant runs.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_native_point.py tests/tools/test_boundary_bench.py -q`. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them again (PASS). Run the bench once (`uv run python tools/bench/boundary_bench.py`) and put its table in the report.
- [ ] **Step 5: Commit** `perf(core): TGPoint3 built natively, slots written directly`.

### Task 2: `GetWorldLocation` / `GetTranslate`

**Files:**
- Modify: `engine/appc/objects.py` (`ObjectClass.GetWorldLocation`, `GetTranslate`), `native/src/host/host_bindings.cc` (`transform_point(index, generation)`)
- Test: `tests/unit/test_native_world_location.py`

**Interfaces:**
- Consumes: Task 1's `make_point`.
- Produces: the body becomes
  ```python
  store = get_store()
  if type(store) is NativeTransformStore:
      return _transform_point(*self._xform)
  x, y, z = store.get_position(*self._xform)
  return TGPoint3(x, y, z)
  ```
  The point is built natively. A stale handle raises the same `StaleHandleError` as `NativeTransformStore.get_position` does today: same message, same chaining. `_transform_point` is a raw `METH_FASTCALL` binding.
- No other `GetWorldLocation` changes (`_ObjectNodeRef`, `ShipSubsystem`, `DebrisChunk`, `bridge_set`, `director`, `target_reticle`).

- [ ] **Step 1: Write the failing tests:**
  - `test_world_location_values_and_type_match_the_old_body`, over random stored objects, comparing by `float.hex`.
  - `test_a_stale_handle_raises_the_same_error`, matching type and message.
  - `test_the_python_store_backend_takes_the_old_path`.
  - `test_a_patched_objects_get_store_is_honoured` (Review Focus 5).
  - `test_fresh_point_each_call`.
  - `test_kernel_m_and_reader_snapshots_still_hold`: `native_motion._stock_holds()` is True, and `ai_native.object_reads_are_stock` for a ship is True.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_native_world_location.py tests/unit/test_object_transform_slots.py tests/unit/test_transform_store_conformance.py tests/unit/test_physics_object.py tests/unit/test_native_avoid_scan.py tests/unit/test_ai_native_gate.py tests/unit/test_native_motion_publish.py tests/unit/test_proximity_cached_candidates.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py -q`. Expect PASS, goldens unchanged.
- [ ] **Step 5: Commit** `perf(core): GetWorldLocation builds its point natively`.

### Task 3: `GetVelocityTG`

**Files:**
- Modify: `engine/appc/objects.py` (`PhysicsObjectClass.GetVelocityTG`, `GetVelocity`), `engine/appc/projectiles.py` (`Torpedo.GetVelocityTG`), `native/src/host/host_bindings.cc` (`point_copy(p)`)
- Test: `tests/unit/test_native_velocity.py`

**Interfaces:**
- Produces: `point_copy(p)` returns `make_point(p.x, p.y, p.z)` when `type(p)` is the registered `TGPoint3` (slot reads). For any other object it reads `x`, `y` and `z` by attribute, exactly as `TGPoint3(p.x, p.y, p.z)` would, including `float()` coercion and its errors.
- The bodies become `return _point_copy(self._velocity)`. `Torpedo` reads its property the same way. The copy stays a fresh object (`projectiles.py`'s docstring explains why that matters).

- [ ] **Step 1: Write the failing tests:**
  - `test_velocity_copy_equals_the_old_body`, including a `_velocity` written by kernel M (`native_motion._store_velocity`), and an int or bool component, where `float()` coercion applies.
  - `test_velocity_is_a_fresh_object`.
  - `test_a_non_point_velocity_behaves_like_the_old_body` (an object with `x`, `y`, `z` attributes, and one missing `z`, which raises the same `AttributeError`).
  - `test_torpedo_velocity_copy`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_native_velocity.py tests/unit/test_physics_object.py tests/unit/test_physics_object_accel.py tests/unit/test_native_motion_publish.py tests/unit/test_incoming_torps.py tests/unit/test_torpedo_guidance_fidelity.py tests/unit/test_native_avoid_scan.py tests/unit/test_native_fire_script.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py -q`. Expect PASS.
- [ ] **Step 5: Commit** `perf(core): GetVelocityTG copies natively`.

### Task 4: `IsTypeOf`

**Files:**
- Modify: `engine/appc/objects.py` (`ObjectClass.IsTypeOf`), `engine/appc/subsystems.py` (`ShipSubsystem.IsTypeOf`), `native/src/host/host_bindings.cc` (`is_type_of(obj, tag)`, plus the `fire::` binding's `s_IsTypeOf` call site)
- Test: `tests/unit/test_native_is_type_of.py`

**Interfaces:**
- Produces: `is_type_of(obj, tag)` returns the same `int` 0/1 as today's body. Its memo is keyed `(type(obj), tag)` and invalidated by `engine.appc.object_types._GENERATION`, as the Python `_ISTYPEOF_CACHE` is. Non-int, non-type tags take the uncached `resolve_class` path, as today. `ShipSubsystem.IsTypeOf` maps through `subsystem_class_for_ct` (call it from C++ on a memo miss; memo keyed the same way).
- The bodies become one call each.
- The Part 2 FireScript binding calls `IsTypeOf` back through attribute lookup on 171 k calls. When the subsystem's `IsTypeOf` resolves to the stock engine function and the instance dict doesn't shadow it, the binding calls `is_type_of` directly. Otherwise it keeps the attribute call.

- [ ] **Step 1: Write the failing tests:**
  - `test_is_type_of_matches_the_old_body_for_every_tag_and_class` (all `object_types.registered_tags()`, every engine object and subsystem class, plus a class tag and a junk tag).
  - `test_a_generation_bump_invalidates`.
  - `test_the_fire_binding_calls_is_type_of_natively_only_when_stock` (a patched `ShipSubsystem.IsTypeOf` must be called).
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_native_is_type_of.py tests/unit/test_object_istypeof.py tests/unit/test_subsystem_istypeof.py tests/unit/test_object_types.py tests/unit/test_subsystem_obj_type.py tests/unit/test_native_fire_script.py tests/unit/test_avoid_obstacles_engine_node.py tests/integration/test_weapon_cast_ai_payoff.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py -q`. Expect PASS.
- [ ] **Step 5: Commit** `perf(core): IsTypeOf answered natively`.

### Task 5: `GetNearObjects` — radii and participation native

**Files:**
- Modify: `engine/appc/planet.py` (`_near_objects`), `native/src/host/host_bindings.cc` (`prox_near(cand, px, py, pz, r)`), `native/src/transforms` (reuse `near_indices_sized`)
- Test: `tests/unit/test_native_near_objects.py`, `tests/unit/test_proximity_cached_candidates.py` (unchanged, must pass)

**Interfaces:**
- Produces: `prox_near` returns exactly today's `_near_objects` result for the cached path (`planet.py:~558-598`): a `_ProximityIteration` with the same objects in the same order. It does this in one native call:
  - **Radii.** For each stored candidate, the radius is `_size(obj)`: `float(obj.GetRadius())`, 0.0 on any exception. It is computed natively when `type(obj)` resolves `GetRadius` to `ObjectClass.GetRadius` (identity, memoised per type on its version tag) and the instance dict doesn't shadow it, reading `_radius * _scale` under the `_scale > 0 and finite` guard. Otherwise it calls Python `_size(obj)` for that object. Radii are read at query time and never cached across queries (Review Focus 3).
  - **Near test.** The same native compare (`near_indices_sized`'s arithmetic), on the same `packed` handles.
  - **Reports.** `_reports(cand, i)` natively: `physics[i]`, else `GetRadius() > 0` by the same rule as the radii, and the `dup_of` twin rule for manager entries.
  - **Unstored entries.** Python `GetWorldLocation` + `_within_reach` called from C++, merged in order as `sorted(keep + more)` does.
  - **Fallback.** `_cached()` returning None (non-SetClass set, sized torpedo) still takes `_near_objects_python`.
- `_Cand` stays built in Python on a generation change. The binding reads its arrays (`physics`, `stored`, `dup_of`, `packed`, `packed_pos`, `unstored_pos`, `objs`) without copying them per query.

- [ ] **Step 1: Write the failing tests:**
  - `test_native_near_equals_today_on_random_scenes`: seeded, 300 queries over sets with ships, planets, a sun, rocks, debris, proximity checks, manager-only entries and duplicates; compare identity and order.
  - `test_a_type_overriding_getradius_uses_its_override` and `test_a_raising_getradius_counts_as_zero` (Review Focus 2).
  - `test_radius_change_without_a_generation_bump_is_seen` (Review Focus 3).
  - `test_no_python_getradius_call_for_stock_candidates`: patch `ObjectClass.GetRadius` counting via a subclass instance only, and assert the stock ones made zero Python calls.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_native_near_objects.py tests/unit/test_proximity_cached_candidates.py tests/unit/test_proximity_manager_iteration.py tests/unit/test_proximity_skips_torpedoes.py tests/unit/test_proximity_manager_forgets_departed.py tests/unit/test_proximity_manager_distance.py tests/unit/test_near_objects_batch_positions.py tests/unit/test_proximity_size_rule.py tests/unit/test_proximity_excludes_checks.py tests/unit/test_native_avoid_scan.py tests/integration/test_sb12_dock_clearout_size_rule.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py -q`. Expect PASS.
- [ ] **Step 5: Commit** `perf(core): GetNearObjects reads radii natively`.

### Task 6: `StartFiring`

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (`WeaponSystem.StartFiring` and its three overrides), `engine/appc/native_combat.py` (`k1_system`, `_k1_entry`, `run_k1`), `native/src/host/host_bindings.cc`
- Test: `tests/unit/test_native_start_firing.py`, plus the existing files named in Step 4

**Interfaces:**
- **Step 0 is a measurement, and its result decides the scope.** Under cProfile, split `StartFiring`'s 3.4 s (Release, 128 ships, `combat_stress`, `DAUNTLESS_PROFILE_PY`, after asking Mark to clear the machine) into: the gates (`_is_offline`, `_cloak_blocks_fire`, `_dewarp_blocks_fire`, `_target_undetectable`, `_can_engage`), the writes (`_add_target`, the descriptors, `SetForceUpdate`), and `run_k1`'s pieces (`_k1_entry`: `drain`, `_refresh_stale_launches`, `resolve_stale_part_slots`, `_k1_clocks`; `effect_queue.session`; `combat_set_applier` / `_applier_context`; `combat_k1_next` / `result` / `end`). Write the table into the report.
- Produces: a native `start_firing(system, target, offset)` entry, called from the thin Python `WeaponSystem.StartFiring` body. It does three things in today's order:
  - **Gates natively** where the state is in the mirror (or read from the same Python attributes the gate functions read). It calls the Python gate function for anything not mirrored. That includes `_target_undetectable`'s try/except around `can_detect`, and the phaser `_can_engage` range check, which uses the native `GetWorldLocation`.
  - **Writes natively** through the same descriptors, so their mirror pushes happen.
  - **Starts the K1 system session.** Remove each piece of `run_k1`'s per-call glue that Step 0 shows to be material, but only where it is provably a no-op for a single-system session started mid-AI-tick. Each removal must be proved by the goldens, the A/B and a focused test. If one isn't provably a no-op, keep it, and report it.
- The three overrides keep their own Python gates and then call the base. A class or instance patch of `StartFiring` still wins, because callers look it up by attribute (Review Focus 4).
- **Unchanged:** `_post_cant_fire`, effect-queue events and sounds, `k1_no_fire` logging and the dev combat cheats.

- [ ] **Step 0: Measure** (above). Ask Mark before launching.
- [ ] **Step 1: Write the failing tests:**
  - `test_start_firing_gates_match_the_python_order` (each gate failing alone, with the same early return and no writes).
  - `test_start_firing_writes_and_pushes_match`.
  - `test_overrides_and_patches_still_win`.
  - One test per glue piece removed, showing it was a no-op on that path.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_native_start_firing.py tests/unit/test_start_firing_arms_tick.py tests/unit/test_weapon_no_target_bail.py tests/unit/test_weapons_disabled_blocks_fire.py tests/unit/test_phaser_fire_range_gate.py tests/unit/test_phaser_cloaked_target_no_fire.py tests/unit/test_cloak_combat_rules.py tests/unit/test_dewarp_drive.py tests/unit/test_torpedo_ammo_selection.py tests/unit/test_native_k1_dispatch.py tests/unit/test_native_k1_no_fire.py tests/unit/test_native_tractor.py tests/unit/test_tractor_in_motion_stage.py tests/unit/test_native_sdk_weapon_routes.py tests/unit/test_fire_control_python_retired.py tests/unit/test_native_fire_script.py tests/unit/test_effect_queue.py tests/unit/test_weapon_config.py tests/unit/test_native_write_apply.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py -q` and `ctest --test-dir build -R combat_K1`. Expect PASS, goldens unchanged.
- [ ] **Step 5: Commit** `perf(combat): StartFiring's gates, writes and session entry run natively`.

### Task 7: Measure, record, live-check list

- [ ] **Step 1: Ask Mark** to clear the machine and approve the runs.
- [ ] **Step 2: Release** in `.claude/worktrees/release-macos`. Before: `f85d00445` (the project tip this branch starts from). After: this branch's tip. Run back to back, using the Part 1 capture shape (`scratchpad/p6ai1_capture.sh`): 64 and 128 ships, exterior and bridge, two runs each, plus one cProfile run per side at 128 exterior.
- [ ] **Step 3: Score** as in SIG-206. Report per-tick `gl.ai` and `ai.avoid`, `sim.combat`, `cb.held_weapons`, frame ms and ticks a frame. From cProfile, report each of the five methods' cumulative and per-call cost before and after. State plainly which ones bought nothing measurable.
- [ ] **Step 4: Perf register.** Add the captures and one signal (the next SIG id), with the catch-up confound stated.
- [ ] **Step 5: Commit** `docs(perf): phase 6 AI part 3, the hot App methods (SIG-…)`.
- [ ] **Step 6: Live-check list** for Mark: a 64- and a 128-ship Quick Battle (avoidance, firing all weapon types, tractors); E1M2 Haven; a cloaked Warbird fight; a warp out and back; the LC Intrepid mod ship.

## Outcome

Patches the ports now bypass **by design** (a test or mod that applies one of these no longer sees it through the ported method):

- A `TGPoint3.__init__` patch, or a rebinding of `objects.TGPoint3`: the native `GetWorldLocation`/`GetTranslate`/`point_copy` build the point from the registered type directly.
- A `NativeTransformStore.get_position` patch: `GetWorldLocation` and `GetTranslate` use the raw `transform_point` binding. (The AI scans still guard `get_position` in `_decide_store`, so they fall back to Python.)
- `subsystems._subsystem_is_type_of`: bypassed by the native FireScript binding (it answers `IsTypeOf` directly).
- A `subsystem_types._ct_table` patch that leaves `_CT_TABLE_CACHE`: the cache is what the native `IsTypeOf` reads.
- The private planet helpers `planet._size`, `_radius_participates`, `_reports` and `_near_objects_cached`, for stock candidates in `GetNearObjects`.
- `_unstored_reaches`, looked up once per query rather than once per candidate.

`StartFiring`'s four field writes are plain `setattr` (final review): the real `NativeField.__set__` runs, so nothing copies it.

SIG-207 results per method (Release, back to back, `perf-register.md`):

- `GetNearObjects`: 87.7 → 28.1 µs per call; `ai.avoid` at 128 ships 0.51-0.57 → 0.34-0.38 ms a tick. This part's gain.
- `GetWorldLocation`: 1.20 → 0.47 µs per call (small in total).
- `GetVelocityTG`: 0.62 → 0.32 µs per call (small in total).
- `IsTypeOf`: Python calls 121 k → 1.6 k (the native FireScript answers it directly).
- `StartFiring`: 195.5 → 186.4 µs per call (≈ -5%); bought nothing measurable.
