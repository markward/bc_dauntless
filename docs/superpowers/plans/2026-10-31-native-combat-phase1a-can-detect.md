# Native Combat Step — Phase 1a (Mirror + Native `can_detect`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every sensor-detection question (`can_detect` and the pieces other code calls directly) is answered by C++ reading a mirror of the state it needs. Each answer, latch and cache stays bit-identical to today's Python, which stays behind a switch as the oracle.

**Architecture:**
- **The mirror.** A new static library `native/src/combat/` holds the mirror: flat rows for objects, subsystems, subsystem properties, sets, nebulae and system profiles, addressed by generation-checked handles like `TransformStore`'s. Positions are read live from `TransformStore`, never copied.
- **Python stays the owner.**
  - Each mirrored field becomes a write-through descriptor (`NativeField`).
  - Each in-place container mutation goes through one mutator that pushes.
  - A `resync()` pushes everything at once. It is used when the switch turns on, and it defines what the mirror audit compares.
- **The sight-check state is native-owned:** the lock-break latch, both occlusion caches and the step-memo answer table (spec §7.6.2-3).
- **Dispatch.**
  - The public functions of `sensor_detection` and `sensor_occlusion` dispatch to C++ when the switch is on and both objects are registered.
  - Otherwise they run today's Python unchanged.
  - Under `DAUNTLESS_NATIVE_AUDIT=1` they run both and record every difference.

**Tech Stack:** C++20 (static lib, gtest), pybind11 bindings in `native/src/host/host_bindings.cc`, Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-native-combat-step-design.md` (approved by Mark 2026-10-31). This plan is the first half of spec §9 phase 1. Phase 1 is split in two:

- **1a (this plan):** the mirror and the native `can_detect`.
- **1b:** K1 fire control. It gets its own plan after 1a is measured.

Why the split:
- K1 turned out to need a resumable kernel. Its decision path writes `_depleted` and clears targets, and it posts `ET_WEAPON_FIRE_FAILED` in the middle of a system's walk (`docs/reference/engine/native-combat/k1-fire-control-map.md` §5, §8).
- `can_detect` is a pure query: no events, no random numbers, no SDK calls. It already serves every caller (AI, target list, torpedoes, phasers), so it lands and is measured on its own.

**Companion references (read before your task):**
- `docs/reference/engine/native-combat/can-detect-inputs.md` is the exhaustive map of `can_detect`: every input with its write sites, every float expression verbatim, the NaN and `min`/`max` semantics, the memo and cache rules, the callers, the hazards. The plan cites it as **CDM §n**.
- `docs/reference/engine/native-combat/native-infra-patterns.md` covers the patterns to copy: TransformStore handles, torpedo_scan's two backends, binding styles, CMake flags, `WakeField`, the passive switch and audit, `step_memo`, the differential test helpers. The plan cites it as **NIP §n**.

## Global Constraints

- **Bit-exact (spec §3.2, §5).** Every answer, latch state and cache answer is identical to the Python path. Floats are compared by `float.hex()`. Never use `pytest.approx` or a tolerance in a native-vs-Python test.
- **Exactness rules (spec §7.5; CDM §4, §9):**
  - `double` everywhere a Python float is used, with the same operand order as the Python (left-associative).
  - `-ffp-contract=off` on every combat source, plus `#pragma clang fp contract(off)` under `__clang__`.
  - Python `min(a, b)` is `(b < a) ? b : a` and `max(a, b)` is `(b > a) ? b : a`, written as ternaries in Python's argument order. Never `std::min`, `std::max`, `fmin` or `fmax`.
  - `math.dist` is CPython 3.11.15's `vector_norm`, ported verbatim (Task 1). `math.sqrt` is `std::sqrt`, and `math.floor` is `std::floor` on a double.
  - Every comparison is written so NaN takes the branch Python takes.
- **Optimised inside Debug (spec §7.6.5).**
  - Each combat source gets `COMPILE_OPTIONS "-ffp-contract=off;$<$<CONFIG:Debug>:-O2>"` in ONE `set_source_files_properties` call per file: the property is replaced, not appended (NIP §2).
  - Never change `CMAKE_BUILD_TYPE`.
- **The switch (spec §7.7):**
  - `DAUNTLESS_NATIVE_COMBAT=1` turns native on and `=0` forces Python.
  - **Unset means OFF in this plan.** The default flips to on only after Mark's live check, as a separate change.
  - `DAUNTLESS_NATIVE_AUDIT=1` turns the audit on, and implies native on.
  - Both are read only in `native_combat.configure()`, which `GameLoop.__init__` calls next to `passive_state.configure()`. Never read the environment at import.
- **One live rule (spec §7.6.4).** With the switch on, every caller of a ported function goes native whenever both objects are registered. Unregistered objects (test fakes, non-`ObjectClass` targets) take the Python path. No caller keeps a private Python copy.
- **Lifecycle (ruling against spec §7.1's "cleared mirror").** Mirror rows live exactly as long as their Python object: registered in `__init__`, unregistered by its `weakref.finalize`.
  - A mission swap does NOT clear rows, because carried-over objects (the player in the `"warp"` set, the bridge) keep theirs.
  - The native-owned state (latch, occlusion caches, memo) resets at exactly the points where Python's resets today: `reset_concealment_state`, `sensor_occlusion.reset`, `step_memo.forget`.
  - `combat_clear()` is for tests (conftest) only.
- **The lock.** Per-call queries hold the GIL: releasing it costs more than a 1 µs query. Batch kernels (phase 1b) are where the lock is released (spec §3.3).
- **Builds:** run `cmake --build build -j` from the worktree root (its `build/` is current). Never run cmake inside `native/`. A Python `AttributeError` on `_dauntless_host` means a stale `.so`: rebuild.
- **Focused tests only** (CLAUDE.md "Test gate"):
  - name every test file explicitly;
  - never run whole suites, `scripts/check_tests.sh` or `ctest` without `-R`;
  - never pass pytest an empty file list.
  - The C++ tests run with `ctest --test-dir build -R combat_`.
- **Shared checkout rules (CLAUDE.md):**
  - never run `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard` or `git add -A/.`;
  - stage explicit paths and commit with `git commit -F <file>`;
  - never commit to main.
- **Worktree:** `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-visibility`, branch `perf/native-combat`.
- **Paths:** never spell `game` or `sdk` as a path segment in new code (CLAUDE.md "BC content paths"). Asset-backed tests skip via `tests/helpers/bc_assets.py`.

## Review Focus

1. **A ship flies through Vesuvi's or Belaruz's sensor band (E3M2).** The profile radius comes from `math.dist`, and there the profile term is not clipped. Native must match on every step across the band. Tested in Task 1 (`test_dist3_matches_math_dist`) and Task 7 (`test_profile_band_sweep`).
2. **A sensor is damaged, repaired, irradiated or re-powered, or a nebula runtime rescales base range, between two questions.** The next answer sees it. Tested in Task 3 (`test_every_sensor_field_writes_through`) and the Task 7 scene audit.
3. **The mission swaps, Quick Battle restores, or a ship is rebuilt.** The latch and occlusion caches are reset as today. Dead objects' rows go away, and a reused row never answers for a dead handle. Tested in Task 2 (`StaleHandleRejected`), Task 3 (`test_finalize_unregisters`) and Task 6 (`test_reset_concealment_state_clears_native_latch`).
4. **Several combat steps run at the same final game time in one frame (6 ticks per frame), and the target-list sweep's `_scan_blocked` shares the occlusion cache.** Native answers stay frozen exactly as long as Python's. Tested in Task 6 (`test_occlusion_cache_shared_with_scan_blocked`) and Task 7 (`ticks_per_frame` 1 and 6).
5. **A test fake or a non-ship target (a planet, a probe torpedo) is asked about.** It takes the Python path with no crash and the same answer. Tested in Task 6 (`test_unregistered_pair_uses_python`).

---

### Task 1: Combat library, Python-semantics math, and the interpreter self-check

**Files:**
- Create:
  - `native/src/combat/CMakeLists.txt`
  - `native/src/combat/include/dauntless/combat/py_math.h`, `native/src/combat/src/py_math.cc`
  - `native/src/combat/include/dauntless/combat/nebula_density.h`, `native/src/combat/src/nebula_density.cc`
  - `native/src/combat/include/dauntless/combat/profile_eval.h`, `native/src/combat/src/profile_eval.cc`
  - `native/tests/combat/CMakeLists.txt`, `native/tests/combat/py_math_test.cc`
- Modify:
  - `native/CMakeLists.txt` (add_subdirectory `src/combat`);
  - `native/tests/CMakeLists.txt` (add_subdirectory `combat`);
  - `native/src/host/CMakeLists.txt` (link `dauntless_combat` into BOTH `_dauntless_host` and `dauntless`);
  - `native/src/host/host_bindings.cc` (test bindings).
- Test: `tests/unit/test_native_combat_math.py`

**Interfaces:**
- Produces, in C++ namespace `dauntless::combat`:
  - `double py_min(double a, double b)`, `double py_max(double a, double b)`, `double saturate(double v)`;
  - `double dist3(const double a[3], const double b[3])`: CPython 3.11.15 `math_dist_impl` + `vector_norm`, ported line for line with a comment citing `Modules/mathmodule.c` v3.11.15 and the PSF licence;
  - `double fbm(double x, double y, double z)`;
  - `double density(double px, double py, double pz, const Sphere* spheres, size_t n, const double seed[3], double freq, double gain, double floor, double drift_t)`, where `struct Sphere { double x, y, z, r; }` (CDM §4.5 verbatim);
  - `struct ProfileRow { double distance_gu; double sensors; }`;
  - `double evaluate_sensors(const ProfileRow* rows, size_t n, double r)`: CDM §4.6 `evaluate`, `sensors` column only, including the exact-breakpoint and NaN-falls-through-to-last-row paths;
  - `bool segment_hits(...)` and `bool contains(...)` (CDM §4.7 verbatim).
- Produces bindings: `combat_test_dist3(a: tuple, b: tuple) -> float`, `combat_test_density(px, py, pz, spheres: list[tuple], seed: tuple, freq, gain, floor, drift_t) -> float`, `combat_test_fbm(x, y, z) -> float`, `combat_test_profile_sensors(rows: list[tuple], r) -> float`, `combat_test_segment_hits(...) -> bool`.

- [ ] **Step 1: Write the failing Python test** `tests/unit/test_native_combat_math.py`
  - Skip it unless `hasattr(_h, "combat_test_dist3")` (NIP §3 pattern).
  - Seeded `random.Random(20261031)`.
  - `test_dist3_matches_math_dist`: 20,000 random pairs in ±2e5. Also include the edge set: zeros, ±0.0, 1e-300, 1e300, inf, nan, equal points. Assert `native.hex() == math.dist(a, b).hex()` for each. Compare NaN results with `math.isnan` on both sides.
  - `test_density_matches_python`: 2,000 random points around 1-13 random spheres with random seed and drift. Assert `.hex()` equality with `engine.appc.nebula_density.density`. Also cover `fbm` against `nebula_density.fbm`.
  - `test_profile_sensors_matches_python`:
    - for each of the 33 maps (`engine.systems.resolve.map_of`), r at every row distance, every midpoint, ±1 ulp of each breakpoint (`math.nextafter`), 0, NaN and inf;
    - `.hex()` equal to `profile.evaluate(prof, r).sensors`.
  - `test_occlusion_primitives_match`: `segment_hits` / `contains` on random inputs, including degenerate segments (`seg2 <= 1e-12`), against `sensor_occlusion._segment_hits` / `_contains`.
  - `test_py_min_max_nan_order`: covered through `combat_test_density` with a NaN sphere radius and a NaN-producing input. The point is that the NaN result follows Python's `min`/`max` argument order (CDM §4.3).

- [ ] **Step 2: Run it and verify it fails**
  - Run `uv run pytest tests/unit/test_native_combat_math.py -v`.
  - Expected: every test SKIPPED (no binding yet).
  - Build first (`cmake --build build -j`), confirm the skip is the binding's absence, then proceed.

- [ ] **Step 3: Create the library and bindings.**
  - CMake:
    - `add_library(dauntless_combat STATIC ...)` with `target_compile_features cxx_std_20` and a PUBLIC link to `dauntless_transforms` (positions are read from `transform_store()` in Task 5);
    - per-source `COMPILE_OPTIONS "-ffp-contract=off;$<$<CONFIG:Debug>:-O2>"` in one call;
    - the MSVC arm uses `/fp:precise` and `$<$<CONFIG:Debug>:/O2>`, after the lottie precedent at `native/src/lottie/CMakeLists.txt:11-26`.
  - Every `.cc` starts with the clang `fp contract(off)` pragma.
  - New gtest target `combat_tests` (`gtest_discover_tests`). `py_math_test.cc` pins a few hand-computed cases: `dist3` of (3,4,0) is 5.0; `py_min(NaN, 1.0)` is NaN; `py_min(1.0, NaN)` is 1.0.

- [ ] **Step 4: Run the tests and verify they pass**
  - Run `uv run pytest tests/unit/test_native_combat_math.py -v` → all PASS.
  - Run `ctest --test-dir build -R combat_ --output-on-failure` → PASS.

- [ ] **Step 5: Commit** the new files, the CMake edits and `host_bindings.cc` (`feat(native-combat): Python-exact math for the combat library`).

---

### Task 2: The C++ mirror store

**Files:**
- Create: `native/src/combat/include/dauntless/combat/mirror.h`, `native/src/combat/src/mirror.cc`, `native/tests/combat/mirror_test.cc`
- Modify: `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`, `native/src/host/host_bindings.cc`
- Test: `native/tests/combat/mirror_test.cc` and `tests/unit/test_native_combat_mirror_store.py`

**Interfaces:**
- Produces, C++:
  - `class Mirror` plus a singleton `Mirror& mirror()`.
  - Handles are `int64_t` packing `(index | generation << 32)` per row kind. Kind is one of `Object`, `Subsystem`, `Property`, `Set`, `Profile`.
  - Generation bumps on free and on reuse, as in `TransformStore` (NIP §1). A stale or wrong-kind handle throws `std::invalid_argument`, which reaches Python as `ValueError`.
  - Each row kind is a struct of plain fields named after the Python attribute it mirrors. The full list is in Task 3 and Task 4.
  - `enum class Field : int32_t` covers every mirrored field across kinds. `const char* field_name(Field)` gives the Python attribute name.
  - Setters `set_f(handle, Field, double)`, `set_i(handle, Field, int64_t)`, `set_ref(handle, Field, int64_t handle_or_minus1)`, `set_ids(handle, Field, const std::vector<int64_t>&)`.
  - `set_spheres(handle, std::vector<Sphere>)`, `set_profile_rows(handle, std::vector<ProfileRow>, double full_concealment)`.
  - `clear()` drops every row and also the native-owned state of Task 5.
  - `epoch()` returns a `uint64_t` raised by every setter and by `clear()`. Phase 1b reads it; this task only maintains it.
- Produces bindings:
  - `combat_register(kind: int, xform_index: int = -1, xform_gen: int = -1, obj_id: int = -1) -> int`;
  - `combat_unregister(handle)`;
  - `combat_set_f`, `combat_set_i`, `combat_set_ref`, `combat_set_ids`, `combat_set_spheres`, `combat_set_profile_rows`;
  - `combat_clear()`, `combat_epoch()`;
  - `combat_field_names() -> dict[str, int]`;
  - `combat_dump(handle) -> dict[str, object]`, for the audit.

- [ ] **Step 1: Write the failing gtests** `mirror_test.cc`:
  - `RegisterSetReadBack`;
  - `StaleHandleRejected` (unregister, re-register reuses the index, the old handle throws);
  - `WrongKindRejected`;
  - `ClearInvalidatesAll`;
  - `EpochRisesOnEverySetterAndClear`.
  - Use a local `Mirror m;` instance, not the singleton (torpedo_scan_test pattern).

- [ ] **Step 2: Run it and verify it fails** (`cmake --build build -j` fails to compile with `Mirror` undefined, as expected).

- [ ] **Step 3: Implement `Mirror` and its bindings.** Write the Python test `test_native_combat_mirror_store.py`:
  - `test_field_names_round_trip`: `combat_field_names()` is non-empty, and the values are unique ints;
  - `test_dump_reflects_setters`;
  - `test_unregister_then_stale_handle_raises_value_error`.

- [ ] **Step 4: Run** `ctest --test-dir build -R combat_ --output-on-failure` and `uv run pytest tests/unit/test_native_combat_mirror_store.py -v`. Expected: PASS.

- [ ] **Step 5: Commit** (`feat(native-combat): mirror store with generation-checked handles`).

---

### Task 3: Python plumbing, the switch, and objects and subsystems written through

**Files:**
- Create:
  - `engine/appc/native_combat.py`
  - `tests/unit/test_native_combat_mirror.py`
- Modify:
  - `engine/core/loop.py` (`GameLoop.__init__` calls `native_combat.configure()` after `passive_state.configure()`);
  - `engine/appc/objects.py` (`ObjectClass.__init__` registers after the `_xform` alloc, and the same `weakref.finalize` path unregisters; NativeFields on `_dead`, `_dying`, `_life_time`, `_containing_set`, `_radius`, `_scale`);
  - `engine/appc/ships.py` (NativeRefFields `_sensor_subsystem`, `_cloaking_subsystem`, and the hull reference `effective_radius` uses);
  - `engine/appc/subsystems.py`:
    - `ShipSubsystem.__init__` registers;
    - NativeFields `_condition`, `_max_condition`, `_disabled_percentage`, `_destroyed`, `_radiation_out`, `_radius`;
    - NativeRefFields `_parent_subsystem`, `_parent_ship`, `_property`;
    - `PoweredSubsystem._power_factor` becomes a `NativeFrozenField`;
    - `SensorSubsystem._base_sensor_range`, `_probe_ids` (list, pushed whole on rebinding);
    - `_known_objects` mutators `AddKnownObject` / `RemoveKnownObject` and the `.clear()` at `sensor_contacts.py:497` route through `native_combat.push_ids`;
    - `CloakingSubsystem._cloak_state`;
  - `engine/appc/properties.py` (the subsystem property's `MaxCondition` data-bag write pushes; properties register lazily when first referenced by `_property`);
  - `engine/rocks/rock.py` (both `ship.__class__ = RockClass` sites call `native_combat.reclassify(ship)`);
  - `engine/appc/sensor_contacts.py:497`;
  - `tests/conftest.py` (`_reset_leakable_engine_globals` calls `native_combat.reset()` and, guarded, `_h.combat_clear()`).
- Test: `tests/unit/test_native_combat_mirror.py`

**Interfaces:**
- Consumes the Task 2 bindings.
- Produces, in `engine/appc/native_combat.py`:
  - `configure(environ=os.environ) -> None`: sets `_enabled` and `_audit` per Global Constraints. On a False→True edge it runs `_self_check()` then `resync()`.
  - `enabled() -> bool`, `audit_enabled() -> bool`, `available() -> bool` (binding present), `reset() -> None` (defaults: off, audit off, failures cleared).
  - `_self_check() -> str | None`:
    - compares `combat_test_dist3` against `math.dist` on 256 seeded pairs, and `combat_test_density` against Python on 32 points;
    - on any mismatch, disables native and writes ONE stderr line `[native-combat] disabled: <reason>`;
    - it returns the reason.
    - This guards an interpreter other than 3.11.15 whose `math.dist` differs.
  - `class NativeField`: shaped like `WakeField` (NIP §5), with `__set_name__` and `__set__` only. `__set__` stores into `obj.__dict__`, then, if `_enabled` and the object has `_nslot`, pushes by the field's type: float → `set_f`, int/bool → `set_i`.
  - `class NativeRefField(NativeField)`: pushes the referent's `_nslot`, or −1 for None or an unregistered referent.
  - `class NativeFrozenField(FrozenField)`: FrozenField's thaw, then the push.
  - `register(obj, kind) -> None`:
    - always assigns `obj.__dict__["_nslot"]` when `available()`;
    - adds the object to a `weakref.WeakValueDictionary` keyed by handle;
    - pushes every NativeField the object already holds;
    - pushes the class-level flags the Python probes with `implements` / `type(...)`: `has_sensor_getter` (`implements(obj, "GetSensorSubsystem")`), `has_cloak_getter` (`getattr(type(obj), "GetCloakingSubsystem", None) is not None`), `is_rock` (`isinstance(obj, RockClass)`), `is_meta_nebula` (`isinstance(obj, MetaNebula)`), and `has_parent_ship_getter` for subsystems.
    - `reclassify` re-pushes these flags.
  - `reclassify(ship) -> None`.
  - `push_ids(obj, field: str, ids) -> None`.
  - `resync() -> None` pushes every registered object's fields plus every Task 4 structure.
  - `audit_mirror() -> None`: for each live registered object, compares each mirrored field with `combat_dump`. Floats by `.hex()`; refs by handle; id lists by sorted equality for sets and order for lists. Each mismatch appends `(type name, field)` to `_failures`.
  - `audit_failures() -> list`.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_native_combat_mirror.py`. Skip each unless `hasattr(_h, "combat_register")`, and enable with `native_combat.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})`.
  - `test_every_sensor_field_writes_through`:
    - build a ship with a sensor subsystem through the real SDK setup path (`tests/helpers/fresh_world.py` or an existing ship helper);
    - for each field in the Files list, write it through its public API (`SetCondition`, `SetMaxCondition`, `SetDestroyed`, the radiation outage helper, a power-plant draw, `SetBaseSensorRange`, `AddKnownObject` / `RemoveKnownObject`, `AddProbe`, `StartCloaking` driven to cloaked);
    - after each write, assert `combat_dump(handle)[field]` equals the Python value (`.hex()` for floats).
  - `test_property_max_condition_shared_template`: `GetProperty().SetMaxCondition(300)` on one subsystem is seen by every subsystem sharing that property.
  - `test_rock_reclassify_pushes`.
  - `test_finalize_unregisters`: drop the last reference, `gc.collect()`, and the old handle raises `ValueError`.
  - `test_switch_off_pushes_nothing_then_resync_catches_up`: writes made while off are absent from the dump; `configure(on)` makes them present.
  - `test_self_check_disables_on_mismatch`: monkeypatch `math.dist` to add 1 ulp; `configure(on)` leaves `enabled()` False, and the reason names `dist3`.
  - `test_audit_mirror_flags_a_bypassed_write`: write `obj.__dict__["_condition"]` directly; `audit_mirror()` records `("SensorSubsystem", "_condition")`.

- [ ] **Step 2: Run it and verify it fails.** Run `uv run pytest tests/unit/test_native_combat_mirror.py -v`. Expected: FAIL with `ModuleNotFoundError: engine.appc.native_combat`.

- [ ] **Step 3: Implement the plumbing.**
  - Before converting fields, list every write site of each converted field (CDM §3 table plus your own grep). Note any in-place mutation in your report and route it through `push_ids` or a setter.
  - The descriptors must keep reads as plain instance-dict reads: no `__get__`.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_native_combat_mirror.py tests/unit/test_passive_power.py tests/unit/test_sensor_detection.py -v`. Expected: all PASS. The last two prove the descriptor change kept `FrozenField` behaviour and the Python sensor path.

- [ ] **Step 5: Commit** (`feat(native-combat): write-through mirror of objects and subsystems`).

---

### Task 4: Sets, nebulae, system profiles and dials written through

**Files:**
- Modify:
  - `engine/appc/sets.py` (`SetClass.__init__` registers kind Set; `SetName` pushes the resolved frame);
  - `engine/appc/contact_index.py` (`on_added`, `on_removed`, `reset` and `forget_set` push the set's ordered ship list and ordered nebula list, in today's bucket order);
  - `engine/appc/nebula.py`:
    - `AddNebulaSphere` pushes `set_spheres`;
    - `SetFbmDials` pushes;
    - `_seed` becomes a NativeField;
  - `engine/systems/region_hooks.py` (`mark_mapped` pushes the frame);
  - `engine/appc/sensor_dials.py` (`reset` and `_step` push `sensorless_range_gu`, `cloak_bubble_cap_gu`, `overboost_threshold`, `min_blocker_radius_gu`);
  - `engine/dev_nebula_dials.py` (conceal_cap pushes);
  - `engine/appc/sensor_occlusion.py` (`set_enabled` and `reset_enabled` push);
  - `engine/appc/native_combat.py`:
    - `push_set_frame(pSet)`;
    - `push_globals()`: dials, `dev_mode.is_enabled()`, `occ.enabled()`, `ENHANCED_SENSOR_CONTEST`, the CDM §3 #2 constants;
    - `resync` covers all of the above;
  - `native/src/combat/` and `host_bindings.cc` (`combat_set_globals(dict)`, `combat_set_frame(set_handle, profile_handle_or_-1, anchor: tuple, star: tuple)`).
- Test: `tests/unit/test_native_combat_world.py`

**Interfaces:**
- The frame is pushed RESOLVED (CDM §9.15):
  - Python computes `(mapped?, profile handle for that system's map, anchor_gu, star position_gu)` with `frames` and `resolve`, exactly as `profile.locate` does;
  - native never sees a set name.
  - Profile rows register once per system map, lazily, at the first frame push.
- The nebula seed rule is native-computed when `_seed` is None: `seed_for(first sphere centre)`. That equals Python's lazy value because spheres only append (CDM §3 #33). A `_seed` Python already cached, including the before-any-sphere `(0,0,0)` case, is pushed and wins.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_native_combat_world.py`, with the same skip and enable pattern:
  - `test_set_ship_order_matches_contact_index`: add, remove and re-add ships; the dumped ship list equals `contact_index.ships_in(pSet)` order.
  - `test_nebula_spheres_and_seed`.
  - `test_frame_follows_mark_mapped_and_rename`: a QuickBattle-style in-place `SetName` to an unmapped name pushes "unmapped".
  - `test_dials_push_on_step_and_reset`.
  - `test_resync_matches_incremental`: build a world with the switch off, `configure(on)`, then dump every row. The result equals the same world built with the switch on.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_native_combat_world.py -v`. Expected: FAIL (`combat_set_frame` missing).

- [ ] **Step 3: Implement the pushes and bindings.**

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_native_combat_world.py tests/unit/test_native_combat_mirror.py tests/unit/test_sensor_occlusion.py tests/unit/test_nebula_concealment.py -v`. Expected: PASS.

- [ ] **Step 5: Commit** (`feat(native-combat): mirror sets, nebulae, profiles and dials`).

---

### Task 5: The native sensor-detection kernel

**Files:**
- Create: `native/src/combat/include/dauntless/combat/sensor_detect.h`, `native/src/combat/src/sensor_detect.cc`, `native/tests/combat/sensor_detect_test.cc`
- Modify: `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`, `native/src/host/host_bindings.cc`

**Interfaces:**
- Consumes `Mirror` (Task 2) and live positions via `transform_store().at(xi).pos` after a `valid(xi, xg)` check. An invalid transform throws `std::invalid_argument`. Ruling: Python's `_get_xyz` swallows a stale transform to (0,0,0), but a registered object's transform is only freed at finalize, so that path is unreachable here (CDM §9.5).
- Produces, C++, as members of `Mirror` or free functions over it. Each one ports the Python function of the same name in `engine/appc/sensor_detection.py` / `sensor_occlusion.py` exactly as CDM §1 and §4 transcribe it, in its gate order (CDM §9.3):
  - `effective_sensor_range(obj)`;
  - `concealment_at(obj, now)`;
  - `is_hidden_by_cloak(obj)`;
  - `jammed(obs, tgt)`;
  - `in_reach(obs, tgt)`;
  - `occ_blocked(obs, tgt, now)`;
  - `can_detect(obs, tgt, now, use_memo, std::optional<double> dist_sq, bool apply_concealment, std::optional<double> concealment)`;
  - `occ_begin_tick(double)`, `occ_reset()`, `latch_reset()`, `bool latched(obs, tgt)`, `memo_clear()`.
- Native-owned state (spec §7.6.2-3):
  - **The latch:** a set of (observer object handle, target object handle). An unregistered row drops its pairs.
  - **Occlusion:** rock and pair caches per set, with CDM §5's exact signatures `(now, tick_time, len(ships_in_set), min_r)` and `(now, tick_time, len(rocks))`. The rock entry freezes each rock's position and radius when the cache is built.
  - **The memo:** `(obs, tgt) → bool`. It is consulted and stored only when `use_memo`.
  - **The probe-walk guard.**
  - Probe ids that resolve to no registered object are skipped, not pruned. Python's `probes()` keeps its own prune, which is idempotent (CDM §5).
- Produces bindings, one per function above: `combat_can_detect(obs, tgt, now, use_memo, dist_sq=None, apply_concealment=True, concealment=None) -> bool`, `combat_concealment_at(obj, now) -> float`, `combat_effective_sensor_range(obj) -> float`, `combat_in_reach`, `combat_is_hidden_by_cloak`, `combat_jammed`, `combat_occ_blocked(obs, tgt, now)`, `combat_occ_begin_tick(t)`, `combat_occ_reset()`, `combat_latch_reset()`, `combat_latched(obs, tgt)`, `combat_memo_clear()`.

- [ ] **Step 1: Write the failing gtests** `sensor_detect_test.cc` on hand-built mirror rows (local `TransformStore` and `Mirror`):
  - `OfflineSensorsRangeZero`;
  - `SensorlessObserverUsesDial`;
  - `CloakedTargetBubbleUsesPyMin`;
  - `ZeroRangeWritesNoLatch`;
  - `OcclusionReturnsBeforeLatch`;
  - `LatchHysteresisBand`: conceal at 0.25 latches; it stays latched down to 0.2 and releases below;
  - `ProfileTermClippedByCap`;
  - `BeyondRangeNeedsBoostKnownAndNotJammed`;
  - `ProbeWalkOneLevel`;
  - `MemoOnlyWhenRequested`;
  - `OcclusionCacheFrozenWithinOneGameTime` (move the rock; same `now` gives the same answer; new `now` recomputes).

- [ ] **Step 2: Run it and verify it fails** (the build fails, `sensor_detect.h` is missing).

- [ ] **Step 3: Implement** by porting the Python bodies line by line. Keep each Python function's name as a C++ function so a reviewer can read them side by side.

- [ ] **Step 4: Run** `ctest --test-dir build -R combat_ --output-on-failure`. Expected: PASS.

- [ ] **Step 5: Commit** (`feat(native-combat): native sensor detection kernel`).

---

### Task 6: Dispatch every caller to native, with the per-call audit

**Files:**
- Modify:
  - `engine/appc/sensor_detection.py`: `can_detect`, `concealment_at`, `effective_sensor_range`, `in_reach`, `is_hidden_by_cloak`, `jammed`, `reset_concealment_state`;
  - `engine/appc/sensor_occlusion.py`: `blocked`, `begin_tick`, `reset`;
  - `engine/core/step_memo.py`: add `on_forget(fn) -> None`; `forget()` also calls each registered fn; `native_combat` registers `combat_memo_clear`;
  - `engine/appc/native_combat.py`: `slot(obj) -> int | None`, `now() -> float` (today's `_game_time()` value), `record_call_failure(fn_name, observer, target, python_answer, native_answer)`.
- Test: `tests/unit/test_native_can_detect.py`

**Interfaces:**
- Each public function gains a native branch at its top:

```python
if native_combat.enabled():
    a, b = native_combat.slot(observer), native_combat.slot(target)
    if a is not None and b is not None:
        ...  # native call; under audit, also the Python body; record any difference; return the PYTHON answer under audit
```

  - Under audit, the Python answer is returned so the game behaves exactly as today while differences are recorded.
  - The existing Python body becomes `_py_<name>` and is unchanged.
- `can_detect` passes `use_memo = step_memo.active() and dist_sq_gu is None and apply_concealment and concealment is None`, which is today's memo condition (CDM §7.1).
- Exceptions: a native `ValueError` from an unregistered row mid-call falls back to the Python body. Callers' own try/except wrappers are untouched (CDM §9.5).

- [ ] **Step 1: Write the failing tests** `tests/unit/test_native_can_detect.py`. Each test runs the same scenario twice with real objects, `configure({"DAUNTLESS_NATIVE_COMBAT": "0"})` vs `"1"`, and compares answers and `_latched` / `combat_latched` step by step.
  - `test_cloak_offline_sensorless_cases`.
  - `test_nebula_latch_sequence`: walk a target into and out of a MetaNebula in 40 steps.
  - `test_rock_occlusion_and_probe`.
  - `test_occlusion_cache_shared_with_scan_blocked`:
    1. call `sensor_contacts._scan_blocked` at game time t;
    2. move the rock;
    3. `can_detect` at the same t returns the cached answer in both arms.
  - `test_memo_staleness_matches`: inside `step_memo.combat_step()`, ask; turn sensors off via `TurnOff`; ask again (stale in both arms); `forget()`; ask (fresh in both).
  - `test_unregistered_pair_uses_python`: a plain fake object; native on; no exception; the same answer as off.
  - `test_reset_concealment_state_clears_native_latch`.
  - `test_audit_records_a_planted_difference`: monkeypatch `_h.combat_can_detect` to invert its answer under audit; `audit_failures()` names `can_detect`, and the returned answer is Python's.

- [ ] **Step 2: Run it and verify it fails.** Run `uv run pytest tests/unit/test_native_can_detect.py -v`. Expected: FAIL (native arm answers equal Python only by accident; `on_forget` is missing).

- [ ] **Step 3: Implement the dispatch.**

- [ ] **Step 4: Run** the new test plus the existing callers' tests, to prove the Python path is untouched:
  - `uv run pytest tests/unit/test_native_can_detect.py tests/unit/test_sensor_detection.py tests/unit/test_sensor_step_answers.py tests/unit/test_concealment_latch_lifetime.py tests/unit/test_sensor_occlusion.py tests/unit/test_sensor_probes.py tests/unit/test_sensor_reach.py tests/unit/test_cloak_detection_contest.py tests/unit/test_perceived_by.py tests/unit/test_ai_sensor_gate.py -v`
  - Expected: PASS.

- [ ] **Step 5: Commit** (`feat(native-combat): every sensor-detection caller dispatches to native`).

---

### Task 7: Differentials and the whole-scene audit

**Files:**
- Create:
  - `tests/integration/test_native_can_detect_differential.py`
  - `tests/integration/test_native_combat_step_differential.py`
  - `tests/host/test_native_combat_scene_audit.py`
- Modify: `engine/core/loop.py` (when `native_combat.audit_enabled()`, call `native_combat.audit_mirror()` once at the end of each `GameLoop.tick`).

**Interfaces:**
- Consumes everything above.
- Copies NIP §7's `_Scene` / `_both` / `_hex` / `record` helpers, and the event capture of `tests/integration/test_passive_weapons_differential.py`.
- Swaps the switch for `DAUNTLESS_NATIVE_COMBAT` (reference arm `"0"`).

- [ ] **Step 1: Write the tests.**
  - `test_native_can_detect_differential.py` (asset-backed, skips without BC content), with seeded pair sweeps:
    - `test_profile_band_sweep`: load E3M2 headless; move the player in 500 steps radially across Vesuvi's 116,366–130,634 GU band and Belaruz's 124,385–133,304 GU band (CDM §4.6); at each step compare `can_detect`, `concealment_at` and the latch, by hex, for the player against every ship in the set.
    - `test_metanebula_sweep`: Multi5.
    - `test_rock_field_sweep`: E1M2 with `SetScale` rocks.
    - `test_cloak_bubble_sweep`: a ship cloaking at a range sweep.
    - Each sweep is driven through public SDK calls (`SetTranslateXYZ`, `StartCloaking`), never private writes.
  - `test_native_combat_step_differential.py`:
    - two seeded `combat_stress` runs (6 ships, 600 ticks, `ticks_per_frame` 1 and 6), reference arm `"0"` vs native arm `{"DAUNTLESS_NATIVE_COMBAT": "1"}` and an audit arm;
    - drive `host_loop._advance_weapons` and `host_loop._advance_combat` exactly as the weapons differential does;
    - seeded ops between frames: `TurnOff` / `TurnOn` sensors, `SetCondition` on sensors, `StartCloaking` / `StopCloaking`, `StartFiring` / `StopFiring`;
    - per tick, compare `(IsFiring, _target is None)` for every bank, the latch pairs, and the event log (`ET_WEAPON_FIRED`, `ET_TORPEDO_FIRED`, `ET_WEAPON_HIT`) with `==`;
    - assert `native_combat.audit_failures() == []` in the audit arm.
  - `tests/host/test_native_combat_scene_audit.py`:
    - copy `tests/host/test_passive_state_scene_audit.py`;
    - env `DAUNTLESS_NATIVE_AUDIT=1`, 16 ships;
    - `hl.run("engine.dev_missions.combat_stress", max_ticks=120) == 0`;
    - `audit_failures() == []`;
    - plus `native_combat.counts()["native_calls"] > 0` to prove the native path ran. Add `counts()` and `reset` of counts to `native_combat` for this.

- [ ] **Step 2: Run them.** Run `uv run pytest tests/integration/test_native_can_detect_differential.py tests/integration/test_native_combat_step_differential.py tests/host/test_native_combat_scene_audit.py -v`.
  - Expected: PASS. Any difference is a porting bug: fix it in Task 5's kernel or a missed write-through, never in the test.
  - Prove each test can fail. Back up `native/src/combat/src/sensor_detect.cc` by `cp`; flip `CONCEAL_K` to 0.8; rebuild; watch all three FAIL; restore by `cp`; `diff` the files to prove the restore; rebuild.

- [ ] **Step 3: Commit** (`test(native-combat): differentials and scene audit for native can_detect`).

---

### Task 8: Measure, record, document

**Files:**
- Modify:
  - `docs/reference/engine/perf-register.md`: new signals and capture IDs, read from the file's current tail; never reuse an ID;
  - `CLAUDE.md`: one row "Native combat mirror + sensor detection", at most 1200 characters (`tests/docs/test_doc_consistency.py` enforces it);
  - `docs/superpowers/specs/2026-10-30-native-combat-step-design.md`: a §9 note recording the 1a/1b split and this plan's rulings (switch default off, rows follow object lifetime rather than a cleared mirror, per-call queries hold the GIL, unregistered pairs take Python, probe ids skipped not pruned, stale transform unreachable);
  - `engine/dev_missions/combat_stress.py`: only if the scene line needs a `native=` field; then also its focused test `tests/unit/test_combat_stress_idle.py`.

- [ ] **Step 1: Paired captures.** Use the passive phase 2 pattern: four runs, 90 s cool-downs, `DAUNTLESS_PROFILE_FRAMES=1500`, 64 ships, logs in `~/Documents/dauntless-perf/`, fight and quiet scenes × native on/off.
  - Write the runner as a bash script in the scratchpad, never a zsh loop.
  - Before starting, check that no other gate or capture is running: `pgrep -fl "pytest|check_tests|dauntless"` must be empty. If not, wait and report.
  - Report per tick:
    - `cb.held_weapons`, `cb.phasers`, `cb.projectiles`, `sim.combat`, `gl.ai`, and the python-loop total;
    - the median of reports 3–11 (the existing `compare_caps.py` method).

- [ ] **Step 2: Record the signals and the docs updates.** Phase 1's bar of "own scope down half" (spec §7.6.6) is judged after 1b. For 1a, report the numbers and whether total `sim` per tick went down, did not change, or went up. A rise means the mirror's write cost exceeds the gain: say so plainly.

- [ ] **Step 3: Run** `uv run pytest tests/docs/test_doc_consistency.py -v`. Expected: PASS.

- [ ] **Step 4: Commit** (`docs(native-combat): phase 1a measurements and rulings`).

After Task 8 the controller hands Mark:
- the numbers;
- the live-test command (`DAUNTLESS_NATIVE_COMBAT=1 ./build/dauntless --developer`, in E3M2 Vesuvi, a nebula, and a cloak fight).

Flipping the default to on is a separate change after his check.
