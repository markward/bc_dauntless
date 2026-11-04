# Native proximity (phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo: one `tdd-engineer` subagent per task, in order, focused tests only, commit between tasks, stop on any BLOCKED (CLAUDE.md "Executing plans").

**Status:** DRAFT, written 2026-11-03 against `project/combat_threading` (`2369cba41`) before it merged. After the merge, diff the files named below against this plan and fix any line references before Task 1.

**Goal:** Make AI proximity queries return what BC returns (no ProximityChecks) and cost a fraction of today, without changing which other objects come back or their order.

**Architecture:** Tasks 1–2 are Python fixes: drop checks from results, and make `IsTypeOf` cheap. Tasks 3–5 replace the per-query rebuild of the candidate list with a per-manager cache that is invalidated by a membership generation counter. The radius test becomes one native call (`near_indices`) over a cached packed handle array, returning hit indices into the cached list. No mirror rows and no new native table, so it works with the native switch on or off and on both transform-store backends. Task 6 applies ruling 6 (departed objects leave the manager list); Task 7, BC's size rule, waits for the parallel scaled-GetRadius merge.

**Tech Stack:** Python 3.11 (engine), C++17 (native/src/transforms, pybind11 in native/src/host), pytest, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md` §5.1 (phase 1), §3 rulings 1, 4 and 5. Maps: `docs/reference/engine/native-motion/proximity-membership-map.md` (PMM), `open-questions-by-reading.md` (OQR).

## Global Constraints

- **Banned git commands** (shared checkout): `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs. To mutate a file temporarily: `cp` to `/tmp`, mutate, then `cp` back and `diff`.
- **Focused test files only.** Never run whole suites (`tests`, `tests/unit`, `tests/ui`) and never the gate (`scripts/check_tests.sh`) unless Mark asks.
- **Build:** `cmake --build build -j` from the project root only. Never reconfigure the build type, and never run cmake inside `native/`.
- **Native compares:** proximity arithmetic is compiled `-ffp-contract=off` (`proximity_query.cc`). Every new compare lives in that translation unit.
- **No benchmarks** except Task 7's, on an idle machine.
- **Never commit to `main`.** Work on `project/native-motion-and-proximity` or a phase branch off it.
- **Results:** a query returns exactly today's objects in today's order, minus ProximityChecks (ruling 1). Any other change is a ruling in its own commit.

## Review Focus

1. **An object leaves a set during `gl.ai` and is queried in the same tick.** The cache must be invalidated synchronously, so the next query cannot return it. Task 4 tests this.
2. **A set holding a sized torpedo.** The whole query takes today's Python path, with the same order. Task 5 tests this.
3. **A non-physics member (planet, sun) whose radius goes from 0 to > 0 between queries**, with no membership change. Participation is read at query time. Task 5 tests this.
4. **An object that is both a set member and in the manager list.** It is reported once, at its set slot when it participates, else at its manager slot. Task 5 tests this.
5. **A cached object whose transform slot was freed**, e.g. collected while the cache still lists it. The cache holds strong references, so a slot cannot be freed while cached; a test pins that a cached query never raises `StaleHandleError`. Task 5 tests this.

---

### Task 1: Proximity queries drop ProximityChecks (ruling 1)

**Files:**
- Modify: `engine/appc/planet.py` (`GetNearObjects` ~:365, `GetLineIntersectObjects` ~:412; rewrite the `_candidates` docstring ~:320-336, which claims BC returns checks)
- Test: `tests/unit/test_proximity_excludes_checks.py` (new)

**Interfaces:**
- Consumes: `engine.appc.ai.ProximityCheck`.
- Produces: both queries skip `isinstance(obj, ProximityCheck)` entries, wherever they come from. `_candidates()` itself is unchanged, because the per-tick check evaluator (`proximity_table`) does not use it.

- [ ] **Step 1: Write the failing tests**

```python
def test_near_query_never_returns_a_check_from_the_manager_list(): ...
    # set with ship A at origin; check C AddObject'd at origin; GetNearObjects(origin, 10) walks [A] only
def test_near_query_never_returns_a_check_that_is_a_set_member(): ...
def test_line_query_never_returns_a_check(): ...
def test_other_objects_keep_their_order_when_checks_are_interleaved(): ...
    # members A, B; checks between and after; near result == [A, B]
def test_checks_still_fire_after_exclusion(): ...
    # a ConditionInRange-style check anchored on A still reports B entering range (proximity_table path)
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_proximity_excludes_checks.py -v`. Expected: the first four FAIL (the check is returned), the last PASSES.
- [ ] **Step 3:** In both queries, skip ProximityCheck candidates before any position work. Import `ProximityCheck` at module scope if that creates no cycle (`engine.appc.ai` imports `planet`? check); otherwise keep one lazy import per query, never per candidate.
- [ ] **Step 4:** Run the new file plus `tests/unit/test_proximity_manager_iteration.py tests/unit/test_near_objects_batch_positions.py tests/unit/test_proximity_skips_torpedoes.py tests/unit/test_proximity_check_evaluator.py tests/integration/test_dock_setup_clears_the_docking_zone.py tests/integration/test_pursuers_avoid_each_other.py tests/integration/test_line_of_sight_and_warp_obstacles.py`. Expected: all PASS. A test that asserted a check comes back is updated in this commit, with the reason (ruling 1).
- [ ] **Step 5: Falsifier.** Run `uv run pytest tests/integration/test_golden_fights.py -v`. Expected: PASS, unchanged. `NeedToAvoid` returns 0 for a check before touching state. If a golden changes, stop and report BLOCKED with the diff.
- [ ] **Step 6: Commit** `engine/appc/planet.py` and the new test: `fix(proximity): queries skip ProximityChecks, as BC does (ruling 1)`.

### Task 2: `IsTypeOf` without the per-call import and resolve chain

**Files:**
- Modify: `engine/appc/object_types.py` (`register` ~:29 bumps a generation; add `generation() -> int`), `engine/appc/objects.py` (`ObjectClass.IsTypeOf` ~:157)
- Test: `tests/unit/test_object_istypeof.py` (extend)

**Interfaces:**
- Produces: `object_types.generation() -> int`, which increases on every `register`. `ObjectClass.IsTypeOf(cls) -> int` returns the same answers, cached per `(type(self), cls)` while `generation()` is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_istypeof_matches_resolve_class_for_every_registered_tag(): ...
    # for a Ship, Planet, Sun, Torpedo, DebrisChunk-like ObjectClass: IsTypeOf(t) == (isinstance(obj, class_for(t)))
def test_istypeof_sees_a_class_registered_after_the_first_call(): ...
    # call IsTypeOf(new_tag) -> 0; register(new_tag, type(obj)); IsTypeOf(new_tag) -> 1
def test_istypeof_accepts_a_class_argument(): ...
def test_istypeof_bool_and_named_stub_answer_zero(): ...
def test_istypeof_unhashable_argument_falls_back_uncached(): ...
def test_object_types_generation_increases_on_register(): ...
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_object_istypeof.py -v`. Expected: FAIL on `generation` and on the late-registration test (if a cache exists without invalidation) or on the missing attribute.
- [ ] **Step 3:** Move the `object_types` import to module scope in `objects.py`; it imports `App` only lazily, so there is no cycle. Add a module dict cache keyed `(type(self), cls)`, cleared when `object_types.generation()` changes. On `TypeError` from hashing, compute uncached.
- [ ] **Step 4:** Run `tests/unit/test_object_istypeof.py tests/unit/test_object_types.py tests/unit/test_subsystem_istypeof.py`. Expected: PASS.
- [ ] **Step 5: Commit** both files and the test: `perf(objects): IsTypeOf caches per class and tag`.

### Task 3: `near_indices` on both transform-store backends

**Files:**
- Modify: `native/src/transforms/include/dauntless/transform_store.h` (~:77), `native/src/transforms/src/proximity_query.cc`, `native/src/host/host_bindings.cc` (beside `transform_within_radius` ~:12198), `engine/appc/transform_store.py` (both classes, beside `within_radius`)
- Test: `tests/unit/test_transform_within_radius.py` (extend: it covers both backends), `native/tests/transforms/transform_store_test.cc` (~:227-301)

**Interfaces:**
- Produces: `store.near_indices(packed: array('I'), x: float, y: float, z: float, r2: float) -> list[int]`. `packed` holds the handles flattened as index, generation pairs, the layout the native `within_radius` wrapper builds today. It returns the ascending positions k whose slot lies within or on the sphere, by the same compare as `within_radius`. A stale handle raises `StaleHandleError`.
- C++: `void TransformStore::near_indices(const std::uint32_t* handles, std::size_t n, const double point[3], double r2, std::vector<std::uint32_t>& out) const;` in `proximity_query.cc`.
- Binding: `transform_near_indices(buffer, x, y, z, r2) -> list[int]`. It releases the GIL around the loop only, per the off-lock pattern (transform-slot frees are already deferred to drain points).

- [ ] **Step 1: Write the failing tests:**
  - Python, run against both backends (the file's existing parametrisation):
    - `test_near_indices_matches_within_radius_flags` (random points, plus slots exactly on the boundary);
    - `test_near_indices_is_ascending`;
    - `test_near_indices_stale_handle_raises`;
    - `test_near_indices_empty_buffer`.
  - gtest: `NearIndicesMatchesWithinRadius`, `NearIndicesBoundaryInclusive`.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_transform_within_radius.py -v`. Expected: FAIL (no attribute).
- [ ] **Step 3:** Implement in all four places. The Python backend's `near_indices` unpacks `packed` pairwise.
- [ ] **Step 4:** Run `cmake --build build -j`, then `ctest --test-dir build -R transform` and the Python file. Expected: PASS. Also run `tests/unit/test_transform_store_conformance.py`.
- [ ] **Step 5: Commit** the five files and both tests: `feat(transforms): near_indices, one call returning hit positions`.

### Task 4: Membership generation counter

**Files:**
- Create: `engine/appc/proximity_cache.py` (generation counter only)
- Modify: `engine/appc/sets.py` (the three `_objects`/`_non_torpedo` writers, PMM §1.1 and its hook list: `_index_member` both branches, the `RemoveObjectFromSet`/`DeleteObjectFromSet` pops), `engine/appc/planet.py` (`AddObject`, `RemoveObject`, `UpdateObject`), `engine/appc/projectiles.py` (the `_radius` setter's `_sized` transitions, PMM §6), and the `__class__` swap in `native_combat.reclassify` or its callers (PMM hook list).
- Test: `tests/unit/test_proximity_cache_generation.py` (new)

**Interfaces:**
- Produces: `proximity_cache.bump() -> None` and `proximity_cache.generation() -> int`, a process-wide monotonic int. `bump()` is called after every mutation that could change any manager's candidate list or order, and after a `_sized` transition. Cheap: one integer add.

- [ ] **Step 1: Write failing tests**, one per hook: adding a ship under a new name bumps; re-adding under an existing name bumps; remove and delete bump (after the handlers run); a torpedo under a key that held a non-torpedo bumps; `AddObject`, `RemoveObject` and `UpdateObject` bump only when they change the list; a torpedo gaining or losing radius > 0 bumps; a class swap bumps.
- [ ] **Step 2:** Run the new file. Expected: FAIL.
- [ ] **Step 3:** Add the calls at exactly the PMM hook-list sites.
- [ ] **Step 4:** Run the new file plus `tests/unit/test_proximity_skips_torpedoes.py tests/unit/test_sets.py` (if present; else the set tests PMM names). Expected: PASS.
- [ ] **Step 5: Commit** `feat(proximity): membership generation counter`.

### Task 5: Cached candidates and `near_indices` in `GetNearObjects` / `GetLineIntersectObjects`

**Files:**
- Modify: `engine/appc/planet.py` (`ProximityManager`: new `_cached()`; `GetNearObjects`, `GetLineIntersectObjects`)
- Test: `tests/unit/test_proximity_cached_candidates.py` (new), `tests/helpers/proximity_oracle.py` (new: a verbatim copy of today's `_candidates` + `GetNearObjects` + `GetLineIntersectObjects` from before this task, minus checks, as the differential oracle), `tests/unit/test_near_objects_batch_positions.py` (its store-call-count test now pins one `near_indices` call)

**Interfaces:**
- Consumes: `proximity_cache.generation()` (Task 4), `store.near_indices` (Task 3), check exclusion (Task 1).
- Produces: `ProximityManager._cached() -> _Cand`, rebuilt when `(proximity_cache.generation(), projectiles.sized_torpedo_in(set))` differs from the cached key. `_Cand` holds:
  - `objs`: today's candidate order, but with **every** set member, participant or not;
  - per entry: `is_set`, `physics` (isinstance `PhysicsObjectClass`), `stored` (`location_is_stored`), and `dup_of` (for a manager entry that is also a set member, that member's index, else −1);
  - `packed`: an `array('I')` of the stored entries' handles, and `packed_pos`, their positions in `objs`.
  - A set with a sized torpedo is not cached: the whole query runs the oracle-equivalent Python path.
- **Query rule (must equal the oracle):**
  1. A set entry is reported if it participates: physics, or `GetRadius() > 0` read **now**, and it is within range.
  2. A manager entry is reported if within range and `dup_of == -1`, or if its set twin did not participate this query.
  3. Within range = the hit set from one `near_indices` call for stored entries; Python's compare on `GetWorldLocation()` for unstored ones (none in a fight, PMM §4).
  4. Output is in `objs` order.
- The line query uses the same cache and today's Python segment math, reading `GetRadius()` per participant at query time (line queries are about 2% of near queries).

- [ ] **Step 1: Write the failing tests**
  - A differential, `test_cached_near_query_equals_oracle_on_random_scenes`. Seeded: 200 scenes of ships, planets with radius 0 or > 0, set members also `AddObject`'d, renamed members, removed members and manager ghosts, plus checks. Query points and radii are random, some exactly on the boundary. It asserts the result is **identical by identity and order** to the oracle.
  - The same differential for the line query.
  - `test_query_after_remove_in_same_tick_excludes_the_object` (Review Focus 1).
  - `test_sized_torpedo_set_takes_python_path_and_matches_oracle` (2).
  - `test_planet_radius_change_between_queries_is_seen` (3).
  - `test_member_also_in_manager_reported_once_at_the_right_slot` (4).
  - `test_cached_query_never_raises_stale_handle` (5): drop external references, `gc.collect()`, query.
  - `test_cache_is_rebuilt_only_on_generation_change`, which counts rebuilds over 100 queries with no membership change: expected 1.
- [ ] **Step 2:** Run the new file. Expected: FAIL.
- [ ] **Step 3:** Implement `_cached()` and the two queries per the rule above.
- [ ] **Step 4:** Run the new file plus every file from Task 1's Step 4, and `tests/unit/test_proximity_manager_distance.py tests/unit/test_planet.py tests/unit/test_helm_collision_alert.py tests/unit/test_avoid_obstacles_sdk_cadence.py` (whichever exist; PMM §8 lists them). Expected: PASS.
- [ ] **Step 5: Falsifier.** Run `tests/integration/test_golden_fights.py`. Expected: unchanged.
- [ ] **Step 6: Commit** `perf(proximity): cached candidates, one native radius call per query`.

### Task 6: Objects that leave a set leave its manager list (ruling 6)

**Files:**
- Modify: `engine/appc/sets.py` (the `RemoveObjectFromSet` / `DeleteObjectFromSet` pops, the same sites as Task 4's bump, after the exit handlers), `engine/appc/planet.py` (a `_forget(obj)` that removes every occurrence from `_objects`)
- Test: `tests/unit/test_proximity_manager_forgets_departed.py` (new)

**Interfaces:**
- Consumes: Task 4's bump sites; Task 5's cache, invalidated by the same bump.
- Produces: when an object leaves set S, it is removed from S's manager list (`S.GetProximityManager()._objects`) if present. ProximityChecks are untouched: their own lifetime goes through `RemoveAndDelete` and `_proximity_checks`, which this task does not change.

- [ ] **Step 1: Write the failing tests:**
  - `test_evicted_hulk_is_not_returned`: a ninth hulk evicts the oldest, and a query at the evicted hulk's last position returns nothing;
  - `test_hulk_still_in_set_is_returned`: the eight remaining hulks are returned, in set order;
  - `test_ship_deleted_at_end_combat_is_not_returned`;
  - `test_ship_that_warped_out_is_not_returned`, with no set move left in the manager list;
  - `test_qb_ship_reentering_the_set_is_returned_once`: an `UpdateObject` after a re-add;
  - `test_departed_object_no_longer_kept_alive_by_the_manager`: a weakref dies after `gc.collect()`, unless something else holds it.
- [ ] **Step 2:** Run the new file. Expected: FAIL on the departed cases.
- [ ] **Step 3:** Implement as specified.
- [ ] **Step 4:** Run the new file, Task 5's file, and `tests/integration/test_quickbattle_*.py` (whichever exist on the branch), plus `engine/quickbattle/sim_restore.py`'s tests (it removes and re-adds objects itself; PMM §2). Expected: PASS.
- [ ] **Step 5:** Goldens: run `tests/integration/test_golden_fights.py`. A golden that changes is re-recorded in this commit with the reason (ruling 6), with Mark asked first whether the radius session is mid-re-record.
- [ ] **Step 6: Commit** `fix(proximity): departed objects leave the manager list (ruling 6)`.

### Task 7: BC's size rule (ruling 4)

Written 2026-11-04, after `ws/scaled-getradius` merged (`1fd782393`): `GetRadius()` is now BC's scaled world bound.

**Evidence** (`docs/reference/engine/native-motion/open-questions-by-reading.md` Q3, from the clean-room `ProximityManager.md` §8.1, graded faithful):
- BC's near test is `|position − centre| − bounding radius` within the query radius.
- In the near query the `includeSize` flag only widens the axis prune, so it cannot change results; it stays accepted and ignored.
- The line query already adds `GetRadius()` to its reach, so it needs no change.

**Ruling (controller, 2026-11-04):** the boundary is inclusive (`≤`), matching every other compare here. The reference does not say, and its server was down; re-check when it is back.

**Files:**
- Modify: `native/src/transforms/include/dauntless/transform_store.h`, `native/src/transforms/src/proximity_query.cc`, `native/src/host/host_bindings.cc` (beside `transform_near_indices`), `engine/appc/transform_store.py` (both backends), `engine/appc/planet.py` (`_near_objects`'s cached and uncached paths, and the unstored compare), `tests/helpers/proximity_oracle.py` (the near query only: the same size rule, in this commit)
- Test: `tests/unit/test_proximity_size_rule.py` (new), `tests/unit/test_transform_within_radius.py` (extend), `native/tests/transforms/transform_store_test.cc` (extend)

**Interfaces:**
- C++: `void TransformStore::near_indices_sized(const std::uint32_t* handles, std::size_t n, const double* radii, const double point[3], double r, std::vector<std::uint32_t>& out) const;` keeps position k when `dx*dx + dy*dy + dz*dz <= reach*reach`, where `reach = r + max(radii[k], 0)`. It lives in `proximity_query.cc` (`-ffp-contract=off`) and appends, like `near_indices`.
- Binding: `transform_near_indices_sized(handles, radii, x, y, z, r) -> list[int]`. `radii` is a float64 buffer of the same length as the handle pairs; a length mismatch raises `ValueError`. It holds the GIL (ruling R3).
- Python: `store.near_indices_sized(packed: array('I'), radii: array('d'), x, y, z, r) -> list[int]` on both backends, with the same stale-handle behaviour as `near_indices`.
- `ProximityManager.GetNearObjects(point, radius, eType=None)`: an entry is within range when `|location − point| ≤ radius + max(GetRadius(), 0)`. `GetRadius()` is read live on every query for every stored entry, with no new invalidation hook; one that raises counts as 0, as the line query treats it. Participation, dedupe and order are unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `test_station_surface_in_range_is_returned`: a ship with radius 296 whose centre is 350 from the query point is returned at r = 60 and not at r = 50;
  - `test_boundary_is_inclusive`: `distance − R == r` exactly is returned;
  - `test_scaled_rock_reach_uses_scaled_radius`: base 10, `SetScale(3)`, centre 35 away, r = 10: returned (reach 40);
  - `test_radius_change_between_queries_is_seen`: a cached entry whose `SetRadius` or `SetScale` changes between two queries, with no membership change;
  - `test_zero_radius_objects_keep_the_centre_rule`;
  - `test_radius_that_raises_counts_as_zero`;
  - the existing differential, now against the size-rule oracle (identity and order);
  - native and Python `near_indices_sized` against a brute-force reference, plus a radii length mismatch.
- [ ] **Step 2:** Run the new tests. Expected: FAIL.
- [ ] **Step 3:** Implement the interfaces above. `cmake --build build -j`.
- [ ] **Step 4:** Run the new and extended files, `ctest --test-dir build -R TransformStore`, and the proximity files from Tasks 1–6. Expected: PASS.
- [ ] **Step 5: Goldens.** Run `tests/integration/test_golden_fights.py`. If any scene changes, STOP and report the scenes and the size of the change; the controller decides on the re-record, which goes in its own commit with the reason "ruling 4: BC's size rule".
- [ ] **Step 6: Campaign sweep.** Run `tests/integration/test_warp_button_handler_sweep.py`. Expected: PASS. Headless runs leave radii at 0 (no models), so this checks for crashes and stopped missions, not behaviour.
- [ ] **Step 7: Commit** `feat(proximity): BC's size rule for near queries (ruling 4)`.

### Task 8: Measure and record (idle machine only)

- [ ] Run `docs/reference/engine/native-motion/phase0-runbook.md` §1 (two runs) on the phase tip, with the phase 0 rows.
- [ ] Record capture rows and one signal in `perf-register.md`: `gl.ai`, `ai.avoid`, `prox.near` and `prox.line` per tick against phase 0's baseline signal. Never edit an old signal.
- [ ] Commit the register: `docs(perf): phase 1 proximity measured`.
- [ ] Ask Mark for the live check: a 64-ship fight, plus E6M2 docking (DockWithStarbase).

---

## Self-review notes

- **Coverage of spec §5.1:** 1a = Task 1, 1b = Task 2, 1c = Tasks 3–5, ruling 6 = Task 6, 1d = Task 7 (after the scaled-GetRadius merge), measurement = Task 8.
- **Deliberate departure from the spec's first wording of 1c:** no native per-set table, no mirror rows, no `_registry` mapping. PMM showed that `py_id` maps back to nothing, set order follows dict keys, the Set row cannot be reused, de-duplication depends on query-time radius, and mirror values exist only with the switch on. Indices into a Python-held list avoid all five, and the cost per query is one native call over about 65 handles.
- **Ruling 6 (Mark, 2026-11-03):** departed Quick Battle ships leave the manager list. Task 6, after the identical-results port, so Task 5's differential still compares against today.
