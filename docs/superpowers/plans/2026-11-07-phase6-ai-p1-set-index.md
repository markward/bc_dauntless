# Phase 6 AI, Part 1 — The Native Set Index — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One native index, keyed by the set OBJECT, that holds each set's members by class and its (set, target) "targeted by" counts. It answers `SetClass.GetClassObjectList` and the contact model's per-set lists, and it exposes popularity and "who targets X" for Part 2's native `SelectTarget`.

**Architecture:** A C++ core (`dauntless::combat::SetIndex`) that knows only opaque object keys, object ids and class keys, so gtest can drive it with no Python. A pybind layer in `host_bindings.cc` holds the strong Python references, runs `isinstance` (`PyObject_IsInstance`) when a bucket is created or a member is added, and builds the Python lists. A thin Python façade, `engine/appc/set_index.py`, is called from exactly two kinds of door: membership (`SetClass` add / leave / pop) and targeting (`ShipClass.SetTarget`), plus `native_combat.reclassify` for a `__class__` swap. `contact_index` keeps its public functions and loses its own buckets.

**Tech Stack:** C++20 (`native/src/combat`, `-ffp-contract=off`), pybind11 (`native/src/host/host_bindings.cc`), Python 3.11, gtest (`ctest -R combat_`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §4.1 (the set index), §5 item 2 (popularity), §5.1 seam 3 (who targets X), §7 (measurement).

## The programme (four parts, one plan each)

Mark's order, 2026-11-07. Each part: its own phase branch cut from `project/phase6-ai`, measured in Release, live-checked by Mark, then merged into the project branch. Plans 2–4 are written after the previous part is measured, because each part's numbers shape the next.

1. **This plan.** The set index; `GetClassObjectList` and `contact_index` answered from it.
2. **Native `SelectTarget`, `AvoidObstacles`, `FireScript`** (BC's own CodeAI nodes, `ai_optimized.py`'s docstring). Exact stock class with stock methods only (identity check against a snapshot taken at SDK load, as kernel M does); anything else runs the SDK Python. `SelectTarget` reads popularity from this plan's index, weights from the instance, builds its candidate list as its own step, and stays inside `ai_sensor_gate`. `ManagePower` already has its replacement.
3. **The hot SDK-facing App methods** per SIG-198: `GetWorldLocation`, `GetNearObjects`, `IsTypeOf`, `GetVelocityTG`, `StartFiring`. Point getters build the Python `TGPoint3` in C++; no native point type.
4. **A5, the AI tree engine** in C++: container nodes, condition evaluation, sleeping-tree scheduling, calling SDK PlainAI scripts and conditions at their nodes. The 4-tick tree sleep and the 4 Hz avoidance re-decision are behaviour and stay.

## What this part buys, said up front

On its own, little. `GetClassObjectList` was 5.6% of AI at 128 ships (SIG-197), almost all of it from `SelectTarget`'s popularity loop, which still runs in Python until Part 2. This part makes each of those 167 k calls a bucket copy instead of an `isinstance` scan over every object in the set (≈ 1,500 torpedoes in a fight). The real payoff is Part 2: popularity becomes one lookup instead of a loop over every ship, for every candidate, for every ship.

## Global Constraints

- Worktree `.claude/worktrees/phase6-ai`, branch `ws/ai-p1-set-index`, cut from `project/phase6-ai` (= local `main` at `35604f3b3`).
- **Never run the gate or a whole suite.** Focused test files only, listed literally. Never hand pytest an empty or unsplit file list (zsh does not word-split `$VAR`). Cheap tree guards allowed: `tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`.
- No destructive git (CLAUDE.md list). Stage with explicit paths.
- Golden fights (`tests/integration/test_golden_fights.py`, `k1_gameloop_ai` above all) stay byte-identical. Never set `UPDATE_COMBAT_GOLDEN`. A golden change is a stop-and-report, not a re-record.
- Bit-exact with today's Python. The reference is a scan of `SetClass._objects` (for class lists) and the SDK's popularity loop (`AI/Preprocessors.py` `GetTargetRating`, the `fPopularity` block) for counts.
- **No Python copy** of the index (spec §3 "Python copies"). An audit switch `DAUNTLESS_SET_INDEX_AUDIT=1` compares against the scan; it is a check, not a fallback.
- Build from the worktree root: `cmake --build build -j`. Combat gtests: `ctest --test-dir build -R combat_`.
- Never launch the game, headless or not, without asking Mark. Benchmarks only in Task 5.

## Exact semantics the index must reproduce

`SetClass._objects` is a dict, and the index mirrors it slot for slot:
- **Order.** Each identifier gets a sequence number when it is NEW to the set. Overwriting an identifier (`AddObjectToSet(obj2, "X")` while "X" holds `obj1`) keeps the slot's number and replaces the object. A popped identifier that is added again gets a new number (dict re-insert goes to the end). Class buckets list members in sequence order.
- **Multiplicity.** One entry per identifier. An object under two identifiers is two entries, in the class lists and in the counts, exactly as `GetClassObjectList` and the stock loop see it.
- **Removal timing.** `RemoveObjectFromSet` / `DeleteObjectFromSet` run their handlers (`ET_EXITED_SET` broadcast, `sensor_contacts.on_exited_set`, `ObjectGroup` membership) BEFORE `_objects.pop`. Today `contact_index.on_removed` runs before the handlers and the scan sees the object until the pop. The index keeps both: `on_leaving` (before the handlers) marks the entry LEAVING, which hides it from the contact view (`ships_in`, `nebulae_in`, `sets_holding`, `push_set_members`); `on_removed` (at the pop) drops it, which removes it from class lists and counts. A handler that re-adds the object under the same identifier clears LEAVING (an overwrite), and the pop then removes it, exactly as the dict does.
- **Contact view.** `ships_in(pSet)` = distinct `ShipClass` members, not LEAVING, in first-entry order. `nebulae_in` the same for `Nebula`. Equal to today's `contact_index` buckets in every case except two pathological ones, both of which were drift bugs in `contact_index` and are recorded in the Task 4 commit message: an overwritten identifier's old ship is dropped (today it stays in the bucket forever), and an object still present under a second identifier stays listed (today one removal drops it).
- **Class test.** `isinstance(obj, cls)` (`PyObject_IsInstance`), evaluated when a bucket is created and when a member is added, and re-evaluated for every bucket of every set holding the object on `native_combat.reclassify(obj)` (the only `__class__` swap: `engine/rocks/rock.py:88`, `:188`).
- **Counts.** For set S and target id T: the number of entries in S whose object is a `ShipClass` whose current target's `GetObjID()` is T. A target is keyed by `GetObjID()` (`None` or an object without `GetObjID` counts as no target). Target membership in S is irrelevant: ships keep targeting an object that left, and if it returns, the stock loop counts them, so the count must still be there.
- **Popularity** (stock `GetTargetRating`, rater R in set S, candidate C): `count(S, id(C)) − multiplicity(S, R) × [R's target id == id(C)]`. The stock loop skips every entry with R's ObjID, so a rater under two identifiers is subtracted twice.
- **Who targets X.** The objects of the counted entries, in sequence order (duplicates kept, like the count).

## Review Focus

1. **A handler that reads `GetClassObjectList` during a removal broadcast** (SDK `ConditionIncomingTorps` reads `CT_TORPEDO` from its exit handlers). It must still see the leaving object. Task 2 pins it with an `ET_EXITED_SET` handler.
2. **A rock conversion after a bucket exists.** A ship added, a `CT_SHIP` bucket created, then `__class__ = RockClass`: the rock must appear in the rock-class bucket and stay in the ship bucket. Task 2 pins it.
3. **A ship's target changing while it is in no set, then the ship joining a set.** The count must pick up its current target at the join. Task 3 pins it.
4. **A mission swap or test reset.** Every strong reference the index holds (sets and members) must be released, or one test keeps every ship alive (the 4.3 GB suite leak, `docs/reference/architecture/test-suite-memory.md`). Task 2 pins it with weakrefs.
5. **A second write path into `ShipClass._target` or `SetClass._objects`.** Either would silently desync the index. Task 3 adds an AST guard for `_target`; Task 2 one for `_objects`.

---

### Task 1: The C++ core, `SetIndex`

**Files:**
- Create: `native/src/combat/include/dauntless/combat/set_index.h`, `native/src/combat/src/set_index.cc`
- Modify: `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`
- Test: `native/tests/combat/set_index_test.cc`

**Interfaces:**
- Produces, in namespace `dauntless::combat`:
  - `using IndexKey = std::uintptr_t;` (object identity; 0 = none) and `constexpr int64_t kNoTarget = -1;`
  - `class SetIndex` with:
    - `std::optional<IndexKey> add(IndexKey set, std::string_view ident, IndexKey obj, int64_t obj_id, bool is_ship, int64_t target_id)` — returns the object it replaced on an overwrite (so the binding can drop that reference), else `nullopt`. Clears LEAVING on an overwrite. `target_id` is recorded as the ship's current target (ignored when `!is_ship`).
    - `void mark_leaving(IndexKey set, std::string_view ident)` — no-op for an unknown identifier.
    - `std::optional<IndexKey> remove(IndexKey set, std::string_view ident)` — returns the removed object.
    - `void set_target(IndexKey ship, int64_t target_id)` — updates every count of every set holding the ship, by multiplicity; records the target even when the ship is in no set.
    - `void set_is_ship(IndexKey obj, bool is_ship)` — reclassify support.
    - Buckets: `bool has_bucket(IndexKey set, IndexKey cls) const`, `void create_bucket(IndexKey set, IndexKey cls, const std::function<bool(IndexKey)>& member_of)`, `std::vector<IndexKey> bucket_classes(IndexKey set) const`, `void set_bucket_membership(IndexKey set, IndexKey cls, IndexKey obj, bool member)` (all entries of `obj` in that set), `std::vector<IndexKey> bucket(IndexKey set, IndexKey cls) const` (entries, sequence order, LEAVING included).
    - Contact view: `std::vector<IndexKey> distinct_live(IndexKey set, IndexKey cls) const` (distinct, not LEAVING, first-entry order).
    - Counts: `int64_t targeted_by(IndexKey set, int64_t target_id) const`, `int64_t multiplicity(IndexKey set, IndexKey obj) const`, `int64_t popularity(IndexKey set, IndexKey rater, int64_t target_id) const`, `std::vector<IndexKey> targeting(IndexKey set, int64_t target_id) const` (sequence order).
    - Lifetime: `std::vector<IndexKey> sets_holding(IndexKey obj) const` (sets with a live entry, in the order the object first entered each), `std::vector<IndexKey> forget_set(IndexKey set)` and `std::vector<IndexKey> reset()` — each returns every key whose reference count it dropped (members and the set itself), with multiplicity, so the binding can `Py_DECREF` the same number of times. `std::vector<IndexKey> sets() const`.
- Data layout is the builder's (spec §8). `set_target` must not scan sets: keep a per-object map of sets holding it with multiplicities.

- [ ] **Step 1: Write the failing gtests** (`ctest -R combat_set_index`):
  - `SetIndex.BucketFollowsDictOrder`: add a, b, c; overwrite b with d → bucket `[a, d, c]`, `add` returned b; remove a; add a again → `[d, c, a]`.
  - `SetIndex.LeavingEntryStaysInBucketsAndCountsButNotTheContactView`: a ship targeting t, `mark_leaving` → `bucket` keeps it, `targeted_by == 1`, `distinct_live` drops it; `remove` → all three drop it.
  - `SetIndex.OverwriteOfALeavingEntryClearsLeaving`.
  - `SetIndex.CountsFollowTargetsAndMembership`: three ships, targets set and changed; a ship moved to another set takes its count with it; target id that is not a member is still counted.
  - `SetIndex.PopularitySubtractsTheRaterByMultiplicity`: rater under two identifiers targeting c, one other ship targeting c → `targeted_by == 3`, `popularity == 1`.
  - `SetIndex.TargetSetOutsideAnySetIsPickedUpOnAdd`: `set_target(s, t)` with s in no set, then `add(..., target_id = t)` → count 1. (Also: `set_target` on an unknown ship is a no-op apart from recording.)
  - `SetIndex.TargetingListsRatersInSequenceOrder`.
  - `SetIndex.ForgetSetAndResetReturnEveryReference`: the returned key multiset equals every key added (members by entry count, plus the set key once).
  - `SetIndex.DistinctLiveDropsDuplicates`.
- [ ] **Step 2: Run them; they fail to compile** (no header).
- [ ] **Step 3: Implement `SetIndex`.**
- [ ] **Step 4: Run** `ctest --test-dir build -R combat_set_index --output-on-failure`. Expect PASS.
- [ ] **Step 5: Commit** `feat(native): SetIndex core — set members by class and (set, target) counts`.

### Task 2: Bindings, the Python façade, membership doors, `GetClassObjectList`

**Files:**
- Modify: `native/src/host/host_bindings.cc` (the `set_index_*` bindings), `engine/appc/sets.py` (`AddObjectToSet`, `RemoveObjectFromSet`, `DeleteObjectFromSet`, `GetClassObjectList`), `engine/appc/native_combat.py` (`reclassify` calls `set_index.on_reclassified`), `engine/host_loop.py` (`reset_mission_state` calls `set_index.reset()`), `engine/core/mission_change.py:211` (`set_index.forget_set`)
- Create: `engine/appc/set_index.py`
- Test: `tests/unit/test_set_index.py`

**Interfaces:**
- Consumes: Task 1's `SetIndex`.
- Produces (`engine/appc/set_index.py`; every function a thin call into the binding):
  - `on_added(pSet, identifier: str, obj) -> None` — called right after `self._objects[identifier] = obj`. Passes `is_ship = isinstance(obj, ShipClass)`, `obj_id`, the ship's current target id; the binding tests `obj` against every existing bucket class of `pSet`.
  - `on_leaving(pSet, identifier: str) -> None` — called where `contact_index.on_removed` is called today (before the handlers).
  - `on_removed(pSet, identifier: str) -> None` — called at each `_objects.pop(name, ...)` in the two removal doors.
  - `on_reclassified(obj) -> None`.
  - `class_objects(pSet, cls: type) -> list` — a NEW list each call; creates the bucket on first use.
  - `ships_in(pSet) -> tuple`, `nebulae_in(pSet) -> tuple` — the contact view; the binding may return a cached tuple that it invalidates on any change to that set.
  - `sets_holding(obj) -> list`, `forget_set(pSet) -> None`, `reset() -> None`.
  - `target_id(target) -> int` — `-1` for `None` or an object that does not implement `GetObjID` (`engine.core.ids.implements`), else `int(target.GetObjID())`.
- `GetClassObjectList` keeps its argument handling (`object_types.resolve_class`, `ShipProperty → ShipClass`, a non-type → `[]`) and returns `set_index.class_objects(self, class_type)`. With `DAUNTLESS_SET_INDEX_AUDIT=1` (read at use), it also computes the old scan and raises `AssertionError` naming the set, class and both lists on any difference (identity, order, length).
- Bindings: pybind `m.def` (`set_index_add`, `set_index_leaving`, `set_index_remove`, `set_index_reclassified`, `set_index_class_objects`, `set_index_ships`, `set_index_nebulae`, `set_index_sets_holding`, `set_index_forget_set`, `set_index_reset`, and Task 3's targeting calls). The binding owns one heap-allocated `SetIndex` that is never destroyed (no static destructor at interpreter exit), and one `IndexKey → (PyObject*, refcount)` table: one strong reference per entry and per set; dropped as the core returns keys. `ShipClass` and `Nebula` class keys are passed in once by the façade at import (`set_index_configure(ShipClass, Nebula)`).

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_set_index.py`:
  - `test_class_lists_match_the_scan_for_every_ct_tag`: one set holding ships, a rock (`engine.rocks.rock` constructor), several torpedoes, a planet, a sun, a nebula, a waypoint, a character if the fixture allows. For every tag in `object_types.registered_tags()` and for `CT_SHIP`, `GetClassObjectList(tag)` equals `[o for o in s._objects.values() if isinstance(o, cls)]` by identity and order, and two calls return different list objects.
  - `test_overwrite_keeps_the_slot`: `AddObjectToSet(a,"A")`, `(b,"B")`, `(c,"C")`, `(d,"B")` → `[a, d, c]`.
  - `test_exit_handlers_still_see_the_leaving_object` (Review Focus 1): an `ET_EXITED_SET` broadcast handler records `GetClassObjectList(CT_SHIP)` and `contact_index.ships_in`; on `DeleteObjectFromSet` the ship is in the first and not the second; after the call, in neither.
  - `test_rock_conversion_moves_buckets` (Review Focus 2): bucket for `CT_SHIP` created first, then the ship becomes a rock via `engine.rocks.rock`'s conversion; it is in the rock class's list and still in `CT_SHIP`'s.
  - `test_reset_releases_every_reference` (Review Focus 4): weakrefs to two ships and the set; after `set_index.reset()` and dropping the test's own references (`gc.collect()`), all three are dead. Same for `forget_set`.
  - `test_audit_flags_a_drift`: with `DAUNTLESS_SET_INDEX_AUDIT=1`, poke `s._objects` directly (bypassing the door) and assert `GetClassObjectList` raises `AssertionError`.
  - `test_objects_dict_has_one_writer` (Review Focus 5): an AST scan of `engine/`, `App.py` and `tools/mission_harness.py` finds no subscript-assignment, `del`, `.pop`, `.clear`, `.update`, `.setdefault` or `.popitem` on an attribute named `_objects` outside `engine/appc/sets.py`'s three doors.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_set_index.py -q`. Expect FAIL (no module).
- [ ] **Step 3: Implement the bindings, the façade and the door calls.** Keep the existing `contact_index.on_added` / `on_removed` calls in place for now (Task 4 removes them).
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_set_index.py tests/unit/test_object_types.py tests/unit/test_torpedo_set_membership.py tests/unit/test_nebula_list_hoisted.py tests/unit/test_asteroid_field.py tests/unit/test_rock_death.py tests/unit/test_sets_publish_lifecycle.py tests/unit/test_contact_index.py tests/unit/test_contact_index_set_maintenance.py tests/unit/test_conftest_leak_resets.py -q`, then `DAUNTLESS_SET_INDEX_AUDIT=1 uv run pytest tests/integration/test_golden_fights.py -q`. Expect PASS, goldens unchanged, no audit failure.
- [ ] **Step 5: Commit** `feat(ai): native set index answers GetClassObjectList`.

### Task 3: Targeting — the counts, popularity, "who targets X", and every door

**Files:**
- Modify: `engine/appc/ships.py` (`SetTarget`: after the `self._target` assignment, when `self._target is not old_target`, call `set_index.on_target_changed(self)` BEFORE the `ET_TARGET_WAS_CHANGED` event, so a handler sees the new count), `engine/appc/set_index.py`, `native/src/host/host_bindings.cc`
- Test: `tests/unit/test_set_index_targeting.py`

**Interfaces:**
- Consumes: Task 2's façade and bindings.
- Produces (`engine/appc/set_index.py`):
  - `on_target_changed(ship) -> None`
  - `targeted_by_count(pSet, target) -> int`
  - `targeting(pSet, target) -> list` (the raters, sequence order; seam 3)
  - `popularity(pSet, rater, target) -> float` — the stock value: same float type and value as the SDK loop's `fPopularity`.
  - These Python functions are for tests, the audit and the later UI. Part 2's native `SelectTarget` reads `SetIndex::popularity` in C++ directly.

The target doors (all route through `ShipClass.SetTarget`, so one door call covers them; each gets a test that the count changes):

| Site | What changes the target |
|---|---|
| `engine/appc/ai_driver.py:1457` | SDK `SelectTarget.Update`'s `pOurShip.SetTarget(sCurrentTarget)` |
| `engine/ui/target_list_view.py:325` | the player picks a row |
| `engine/appc/target_menu.py:860` | the remembered player target restored |
| `engine/appc/ship_death.py:141` | others' targets cleared when a target dies |
| `engine/appc/warp.py:288` | target cleared on warp |
| `engine/appc/sensor_detection.py:968` | player target dropped when lost to sensors |
| SDK scripts | any `SetTarget(...)` call (string or object) |

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_set_index_targeting.py`:
  - `test_popularity_matches_the_stock_loop_under_random_play`: seeded RNG, two sets, 12 ships plus a planet target; 400 random steps of `SetTarget(name | object | None)`, moving a ship between sets (remove + add), deleting a ship, adding a ship under a second identifier, overwriting an identifier. After each step, for every ship R in each set and every object C in that set, `set_index.popularity(S, R, C)` equals a verbatim Python transcription of the SDK's `fPopularity` block (written in the test, reading `S.GetClassObjectList(App.CT_SHIP)`), as floats.
  - `test_join_picks_up_a_target_set_outside_any_set` (Review Focus 3).
  - `test_targeting_lists_the_raters_in_set_order`.
  - One test per row of the doors table: drive the site (or its smallest public entry) and assert `targeted_by_count` before/after. Reuse each module's existing test fixtures where they exist (`tests/unit` files for `ship_death`, `warp`, `sensor_detection`, `target_list_view`, `target_menu`, `ai_driver`); the SDK row uses a string `SetTarget` and an object `SetTarget`.
  - `test_target_has_one_writer` (Review Focus 5): an AST scan of `engine/`, `App.py`, `tools/mission_harness.py` finds assignments to an attribute `_target` only in `engine/appc/ships.py` (`__init__`, `SetTarget`) and in an explicit allowlist of the non-ship classes that own their own `_target` (`weapon_subsystems.py`, `events.py`, `native_combat.py` descriptor constructors, `engine/ui/letterbox.py`, `engine/ui/quick_battle_setup_panel.py`), and no `__dict__["_target"]` write anywhere.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_set_index_targeting.py -q`. Expect FAIL.
- [ ] **Step 3: Implement** the bindings, the façade functions and the `SetTarget` door call.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_set_index_targeting.py tests/unit/test_set_index.py -q` plus the existing test files for the six engine sites that Step 1 reused, then `uv run pytest tests/integration/test_golden_fights.py -q`. Expect PASS, goldens unchanged.
- [ ] **Step 5: Commit** `feat(ai): (set, target) counts, popularity and who-targets-X in the set index`.

### Task 4: `contact_index` onto the set index

**Files:**
- Modify: `engine/appc/contact_index.py` (delete `_buckets`, `_nebula_buckets`, `on_added`, `on_removed`; `ships_in`, `ship_positions_in`, `nebulae_in`, `sets_holding`, `reset`, `forget_set` delegate to `set_index`; rewrite the module docstring around the single index), `engine/appc/sets.py` (drop the `contact_index.on_added` / `on_removed` calls; `set_index.on_leaving` takes `on_removed`'s place), `engine/appc/set_index.py` (calls `native_combat.push_set_members(pSet)` whenever a set's contact view changes: an add of a ship or nebula, `on_leaving`, a `remove` of an entry that was not LEAVING, `forget_set`, `reset` for every set it held), `engine/host_loop.py:4475` and `engine/core/mission_change.py:211` (one reset / forget call each, not two)
- Test: `tests/unit/test_contact_index.py`, `tests/unit/test_contact_index_set_maintenance.py` (unchanged unless a test pins one of the two recorded drift cases, which is updated to the new answer with a comment naming it), `tests/unit/test_set_index.py`

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces: `contact_index`'s public functions with unchanged signatures and results (two recorded exceptions in the semantics section). `push_set_members` is called with the same ship and nebula lists, in the same order, at the same points in each door as today.

- [ ] **Step 1: Write the failing test** `test_push_set_members_sees_the_same_lists_at_the_same_points` in `tests/unit/test_set_index.py`: wrap `native_combat.push_set_members` to record `(set name, ships_in names, nebulae_in names)` at each call; drive add ship, add nebula, add torpedo (no push), overwrite, `RemoveObjectFromSet`, `DeleteObjectFromSet`, `forget_set`, `reset`. The expected sequence is recorded from today's tree (run the test body once at Task 3's tip and paste the list into the test). It fails after the Step 3 edits only if a push moved, vanished or changed.
- [ ] **Step 2: Run it at Task 3's tip.** Expect PASS (it is the recorded reference).
- [ ] **Step 3: Move `contact_index` onto `set_index`.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_set_index.py tests/unit/test_set_index_targeting.py tests/unit/test_contact_index.py tests/unit/test_contact_index_set_maintenance.py tests/unit/test_conftest_leak_resets.py tests/unit/test_ship_iter.py tests/integration/test_golden_fights.py -q`, plus `DAUNTLESS_NATIVE_AUDIT=1 uv run pytest tests/integration/test_golden_fights.py -q` and the tree guards. Expect PASS, goldens unchanged. The module docstrings of `set_index.py` and `contact_index.py` are the record; CLAUDE.md is not edited in this plan.
- [ ] **Step 5: Commit** `refactor(ai): contact_index reads the set index; one set index, not two`, naming the two recorded drift cases in the body.

### Task 5: Measure, record, live-check list

- [ ] **Step 1: Ask Mark** to clear the machine and to approve the runs (they launch `./build/dauntless`).
- [ ] **Step 2: Release captures.** `.claude/worktrees/release-macos` detached at this branch's tip, rebuilt Release. The capture command in `docs/reference/engine/native-motion/phase0-runbook.md` §1, `DAUNTLESS_MISSION=engine.dev_missions.combat_stress`, `DAUNTLESS_COMBAT_SHIPS=64` and `=128`, exterior and bridge, 1,500 frames, two runs each; then the same eight at `35604f3b3` as the before, back to back in one session. Score frame ms, ticks a frame, and per tick `gl.ai` (sum and `ai.*` children), median of reports 3–11.
- [ ] **Step 3: cProfile.** One run each side at 128 exterior, `DAUNTLESS_PROFILE_PY=<path>`, frames 500:400. Report `GetClassObjectList` cumulative and per call, `GetTargetRating` cumulative, `contact_index.ships_in` and `ship_positions_in`, and `tick_all_ai`'s share of the root. Relative shares only.
- [ ] **Step 4: Perf register.** Captures plus one signal (next SIG id). State the catch-up-loop confound as SIG-199 does: per-tick rows are the comparable ones; frame ms at 128 moves with ticks a frame and projectiles in flight. Say plainly if the gain is within the spread.
- [ ] **Step 5: Commit** `docs(perf): phase 6 AI part 1, the set index (SIG-…)`.
- [ ] **Step 6: Live-check list for Mark** (in the ledger and the hand-off): a 64-ship Quick Battle (ships pick and switch targets; the target list fills and empties as ships die); E1M2 (Haven, rocks: a rock conversion); a warp out and back (sets swap; the target clears); a nebula mission (`nebulae_in`, sensors conceal); `--developer` → Load Mission to swap missions twice (reset).
