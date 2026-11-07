# Phase 6 AI, Part 2 — Native Stock Preprocessors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BC's own CodeAI design, restored for three SDK preprocessors. For an unpatched stock instance, AvoidObstacles' obstacle scan, SelectTarget's candidate rating and FireScript's whole `Update` run in C++. The results are bit-identical to the SDK Python bodies, and anything patched, subclassed or modded runs the SDK Python.

**Architecture:** Each preprocessor already reaches the engine through `engine/appc/ai_optimized.py`: `optimized_version_of` swaps a bound SDK instance for an engine subclass that shares its `__dict__`, and SelectTarget gets the same treatment in this plan. The engine subclass overrides only the hot method:
- AvoidObstacles: `TestCourseOverride`'s per-object `NeedToAvoid` loop.
- SelectTarget: `GetTargetRating`.
- FireScript: `Update`.

Each override asks `engine/appc/ai_native.py` whether the instance is stock. If it is, it calls one C++ entry point; if not, it calls the SDK method. Every SDK attribute, the driver's coupling (`lWeapons`, `idTargetedSubsystem`, `dDamageReceived`, `sCurrentTarget`, PS_* returns, `GetNextUpdateTime`), the sensor gate and the cadences stay exactly as they are. C++ reads positions and rotations from the transform store and conditions from the combat mirror, where an audit proves those equal Python's values. For everything else (dicts, names, velocities, scripts) it reads the Python objects directly, under the GIL.

**Tech Stack:** C++20 (`native/src/combat`, `-ffp-contract=off`, system libm), pybind11 / CPython C API (`native/src/host/host_bindings.cc`), Python 3.11, gtest (`ctest -R combat_`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §5 (Part C), §5.1 (seams), §2 anti-goals, §7. `engine/appc/ai_optimized.py`'s module docstring (binary RE of `PreprocessingAI::SetContainedAI`). Part 1 plan `docs/superpowers/plans/2026-11-07-phase6-ai-p1-set-index.md` ("Notes for Part 2").

## Why this shape (measured, SIG-205's cProfile C-402, shares of AI at 128 ships)

| Preprocessor | Share | Inside it |
|---|---|---|
| AvoidObstacles | 28.7% | `NeedToAvoid` 19.0% (1.1 M calls), `GetNearObjects` 5.6% (Part 3's list), `AvoidObjects` 0.3% |
| SelectTarget | 22.3% | `GetTargetRating` 20.7% (163 k calls, ≈ 100 µs each profiled), mostly the popularity loop |
| FireScript | 11.1% | `FireSystemAtTarget` 7.3% (of which `StartFiring` 4.5%, Part 3's list), `ChooseTargetSubsystem` 2.9%, `ConfigureWeaponSystem` 1.4% |

- **AvoidObstacles.** The scan is pure arithmetic, while `AvoidObjects`, which draws from the unit-vector random number generator (RNG), costs 0.3%. So only the scan moves; `AvoidObjects` stays SDK Python and keeps its RNG stream untouched.
- **SelectTarget.** Rating is pure arithmetic. `FindGoodTarget`'s candidate step (group order, filters, the sensor gate and its fallback) stays SDK Python and calls `self.GetTargetRating`, which becomes native. That keeps the candidate list its own step (seam 2).
- **FireScript.** Mark ruled 2026-11-07 to port all of it in this part.

## Global Constraints

- Worktree `.claude/worktrees/phase6-ai`, branch `ws/ai-p2-native-preprocessors`, cut from `project/phase6-ai` at `96e73bb31`.
- **Never run the gate or whole suites.** Run focused files only, listed literally; never an empty or unsplit pytest list (zsh does not word-split `$VAR`). Tree guards are allowed: `tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`.
- No destructive git (the CLAUDE.md list). Stage explicit paths. Temporary mutations: copy a backup, mutate, run, copy back, `diff`.
- **Golden fights (`tests/integration/test_golden_fights.py`, `k1_gameloop_ai` above all) stay byte-identical. Never set `UPDATE_COMBAT_GOLDEN`.** A golden change is a stop-and-report.
- **Bit-exact with the SDK Python bodies.** Same float operations in the same order, `-ffp-contract=off`, and the same libm (`acos`, `sqrt`) CPython's `math` calls. Same returned types (Python `int` 0/1 where the SDK returns 0/1, `float` where it returns a float, the same tuple shapes). Same exceptions on the same bad inputs (e.g. a missing `dDamageReceived` raises `AttributeError`, as the SDK does).
- **RNG streams are never reimplemented.** Every draw FireScript makes goes through the Python object the SDK calls (`App.g_kSystemWrapper.GetRandomNumber`), in the SDK's order and count, so presentation scopes and seeding keep working. AvoidObstacles' `TGPoint3_GetRandomUnitVector` draws stay in Python, because `AvoidObjects` stays Python.
- **Stock means stock** (spec §5 item 1), via `engine/appc/ai_native.py` (Task 1):
  - The SDK class of the instance is the stock SDK class.
  - Every preprocessor method the native code replaces or would call is a function defined in the stock SDK file (`paths.sdk_scripts()/AI/Preprocessors.py`, by `__code__.co_filename` and `__qualname__`), or one of our own marked wrappers of such a function (the sensor gate's).
  - The instance `__dict__` shadows none of them.
  - Every App method the native code replaces a call to resolves, on the object's type, to the engine's own function (a surface snapshot taken at import, as kernel M's `_SURFACE` / `_take_snapshot` in `engine/appc/native_motion.py`).
  - Anything else runs the SDK Python for that call. A mod that replaces `AI/Preprocessors.py` is not stock, because its functions come from another file.
- **Kept behaviour** (`docs/reference/engine/perf-cadences-and-latency.md`): the avoidance 4 Hz re-decide and phase offset, the AI tree's 4-tick sleep, SelectTarget's 5 s cadence, FireScript's 0.2 s cadence, PS_DONE → PS_NORMAL de-fanging. None of these change.
- **Seams (spec §5.1):** rating weights are read from the instance (`self.fDistanceFactor` …, as set by `SetRelativeImportance`) on every call, never from constants. The candidate step stays separate. Popularity comes from `SetIndex::popularity` with the candidate's live `GetObjID` (Task 3 showed `popularity_by_key` is wrong for a candidate held by no set).
- **Build switch** `DAUNTLESS_NATIVE_AI` (read at use): unset or `1` = all native; `0` = none; otherwise a comma list of `avoid`, `select`, `fire`. It exists for the A/B test and Task 7's measurement, and Task 8 deletes it (spec §3, "Python copies"). The SDK fallback for non-stock instances is permanent: it is the mod path, not a copy.
- **Native-reader contract** (Part 1, `set_index.h`): keys are borrowed `PyObject*` addresses. Read only under the GIL on the main thread. Never hold a borrowed key across a call that can run Python or allocate Python objects. Native AI code calls back into Python (side effects, scripts, RNG), so re-read anything borrowed after every callback.
- Build: `cmake --build build -j` from the worktree root. Combat gtests: `ctest --test-dir build -R combat_`. Never launch the game without asking Mark.

## Review Focus

1. **A candidate or obstacle whose class overrides an App method the native code reads.** `RockClass`, `DebrisChunk.GetRadius`, `Torpedo.GetVelocityTG`, a mod ship class. That call must run the SDK Python, decided per object type. Tasks 2 and 3 pin it with a subclass that overrides `GetRadius` / `GetWorldLocation`.
2. **The sensor-gated and the ungated `FindGoodTarget`.** The host installs the gate (`engine/host_loop.py:299`), the golden harness does not, and the gate's fallback `_best_detectable_candidate` calls `self.GetTargetRating` too. Both must reach the native rating. Task 3 covers both.
3. **A shield subsystem that is off, absent, or has total max ≤ 0** (`subsystems.py` `GetShieldPercentage` returns 1.0 there), and a ship with no weapon systems (`fWeaponsGood` stays 0.0). Task 3's differential test has a row for each.
4. **A FireScript callback that changes the world mid-`Update`.** `StartFiring`, `StopFiringAtTarget`, `FireDumb`, `SetAmmoType`, `CallExternalFunction("UsingWeaponType")` run Python that can mutate sets, targets and weapons, so borrowed pointers held across them would dangle. Task 4's A/B scenes include a target dying mid-volley and a mission handler on `UsingWeaponType`.
5. **A monkeypatch after the first native call** (a mission patching `FireScript.FireSystemAtTarget` mid-mission, or a test uninstalling the sensor gate). The next call must see it and run Python. Task 1 pins the gate's re-check.

---

### Task 1: The stock gate, the build switch, counters and the A/B harness

**Files:**
- Create: `engine/appc/ai_native.py`, `tests/unit/test_ai_native_gate.py`, `tests/integration/test_native_ai_ab.py`, `tests/helpers/native_ai_ab.py`
- Modify: `engine/appc/ai_sensor_gate.py` (mark its wrappers: `fn._dauntless_wraps = <the wrapped original>`)

**Interfaces:**
- Produces (`engine/appc/ai_native.py`):
  - `KINDS = ("avoid", "select", "fire")`; `enabled(kind: str) -> bool` (the build switch, read at use).
  - `is_stock_sdk_function(fn, qualname: str) -> bool`: true iff `fn`, after unwrapping `_dauntless_wraps` chains, is a function whose `__code__.co_filename` resolves to `paths.sdk_scripts() / "AI" / "Preprocessors.py"` and whose `__qualname__ == qualname`.
  - `preprocessor_is_stock(inst, sdk_class_name: str, methods: tuple[str, ...]) -> bool`: walks `type(inst).__mro__` for the class named `sdk_class_name` whose module file is the stock SDK file; checks each name in `methods` on `type(inst)` with `is_stock_sdk_function`, accepting the engine's own overrides on its `ai_optimized` subclasses (marked `_dauntless_native_entry = True`), and checks `inst.__dict__` shadows none of them. Budget ≤ 1 µs per call: cache per `type(inst)`, and invalidate the cache whenever any watched class `__dict__` entry or the gate changes (compare a cheap tuple of the resolved function objects, as `native_motion._stock_holds` does).
  - `object_surface_is_stock(obj, names: tuple[str, ...]) -> bool`: each name resolves on `type(obj)` to the function the import-time snapshot holds for the engine class that defines it. Cached per `(type, names)`, re-validated by the same tuple compare.
  - `note(kind: str, path: str, reason: str = "") -> None` and `stats() -> dict`: counts per kind of `native` and `python` with reasons (`"switch"`, `"not_stock"`, `"surface"`, `"no_mirror"`), plus `reset_stats()`, which `engine.host_loop.reset_mission_state` calls. `stats()` lines are printed with the frame profiler report when it is on (same style as `beam feed: native N, fallbacks M`).
- Produces (`tests/helpers/native_ai_ab.py`): `run_ab(scene, ticks) -> tuple[bytes, bytes, dict]`. It runs the same seeded scene twice in subprocesses, `DAUNTLESS_NATIVE_AI=0` and unset, with the `tests/helpers/golden_fight.py` recorder (every per-tick record it writes), and returns both serialised records and the native run's `ai_native.stats()`.
- Scenes (`test_native_ai_ab.py`, one test each):
  - `k1_gameloop_ai` as the goldens run it (ungated);
  - `combat_stress` 16 ships with avoidance on, sensor gate INSTALLED, 1,200 ticks;
  - a CloakAttack doctrine scene (`tests/unit/test_cloak_attack_doctrine.py`'s setup);
  - a FedAttack scene with `ChooseSubsystemTargets` on and more than 4 targetable subsystems (the RNG branch);
  - the Akira torpedo-selection scene (`tests/integration/test_akira_ai_ammo_selection.py`);
  - the SDK dumb-fire scene (`golden_fight.test_sdk_dumb_fire`'s Difficulty 0.0).
  - Each asserts the two records are byte-identical. From Task 2 on, each also asserts that its kind's `native` count is > 0, and that its `python` count is 0 or explained.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_ai_native_gate.py`:
  - `test_the_stock_sdk_functions_are_stock`: `SelectTarget.GetTargetRating`, `AvoidObstacles.NeedToAvoid` and `FireScript.Update` from the loaded SDK.
  - `test_a_monkeypatch_is_not_stock_and_is_seen_on_the_next_call`: patch, check, unpatch, check (Review Focus 5).
  - `test_a_subclass_method_is_not_stock`.
  - `test_an_instance_dict_override_is_not_stock`.
  - `test_a_function_from_another_file_with_the_same_qualname_is_not_stock`: compile a source with `class SelectTarget: def GetTargetRating(...)` under a temp filename.
  - `test_the_sensor_gate_wrapper_counts_as_stock`, plus the same after `uninstall_ai_sensor_gate()`.
  - `test_switch_parsing` for unset, `0`, `1`, `avoid,fire` and junk.
  - `test_object_surface_detects_a_subclass_override`.
  - `test_stats_reset_on_mission_state_reset`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_ai_native_gate.py -q`. Expect FAIL (no module).
- [ ] **Step 3: Implement** `ai_native.py`, the sensor-gate marks, and the A/B helper and test (no native path exists yet, so the records are trivially identical).
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_ai_native_gate.py tests/integration/test_native_ai_ab.py tests/unit/test_ai_sensor_gate.py tests/integration/test_golden_fights.py -q`. Expect PASS, goldens unchanged.
- [ ] **Step 5: Commit** `feat(ai): stock gate, build switch and A/B harness for native preprocessors`.

### Task 2: AvoidObstacles — the obstacle scan in C++

**Files:**
- Create: `native/src/combat/include/dauntless/combat/ai_avoid.h`, `native/src/combat/src/ai_avoid.cc`, `native/tests/combat/ai_avoid_test.cc`, `tests/unit/test_native_avoid_scan.py`
- Modify: `native/src/combat/CMakeLists.txt`, `native/tests/combat/CMakeLists.txt`, `native/src/host/host_bindings.cc` (`combat_ai_avoid_scan`), `engine/appc/ai_optimized.py` (`_phased_avoidance_class` gains a `TestCourseOverride` marked `_dauntless_native_entry`)

**Interfaces:**
- Consumes: Task 1's `ai_native`.
- Produces: the C++ core `bool need_to_avoid(const AvoidInputs&)`, a pure function of doubles: the SDK `NeedToAvoid` arithmetic (SDK `AI/Preprocessors.py:1769-1842`), exactly. It takes ship position and velocity, object position, velocity and radius, personal-space radius and prediction time; `is_physics` selects zero velocity for a non-physics object. gtested on its own.
- Produces: the binding `combat_ai_avoid_scan(inst, ship, personal_space_radius: float, near_iter: tuple) -> list`. It walks the `_ProximityIteration` tuple `GetNearObjects` returned, in order, skips the ship's own `GetObjID`, and applies the `lDontAvoidTypes` test and `need_to_avoid` to each object. It returns the objects to avoid, in order, exactly the SDK loop's `lAvoidObjects`.
  - The `IsTypeOf` verdict for `(type(obj), tuple(inst.lDontAvoidTypes))` is computed by calling Python `IsTypeOf` once and cached natively, keyed also by `engine.appc.object_types._GENERATION`.
  - Per object it reads position from the transform store, radius as `GetRadius()` would compute it, and velocity as `GetVelocityTG()` would return it.
  - An object whose type fails `object_surface_is_stock(obj, ("GetWorldLocation", "GetRadius", "GetVelocityTG", "IsTypeOf", "GetObjID"))` is evaluated by calling the SDK `NeedToAvoid` in Python for that object alone.
  - `fPredictionTime` and `lDontAvoidTypes` are read from the instance on every call.
- The engine `TestCourseOverride`: if `ai_native.enabled("avoid")` and `preprocessor_is_stock(self, "AvoidObstacles", ("TestCourseOverride", "NeedToAvoid", "AvoidObjects"))`, it is the SDK body (SDK `:1713-1767`) with the while loop replaced by one `combat_ai_avoid_scan` call, then `return self.AvoidObjects(pShip, lAvoidObjects)`. Otherwise it is the SDK method. Keep the SDK's calls before the loop identical (same App calls, same order). The `GetNearObjects` / `GetNextObject` / `EndObjectIteration` calls stay; the scan reads the iteration tuple and leaves its cursor as the SDK loop would.

- [ ] **Step 1: Write the failing tests.**
  - gtests `AiAvoid.MatchesTheSdkFormulaOnKnownCases`: inside personal space; head-on; parallel; `a == 0`; negative discriminant; `t1 < t2` both signs; hit time exactly 15.
  - pytest `test_native_scan_equals_the_sdk_loop_on_random_scenes`: seeded, 200 scenes of 2-40 objects (ships, a planet, a rock, a sun, debris, a torpedo, a nebula, a proximity check), random positions and velocities. The native list is identical to the SDK loop's list, by object identity and order.
  - pytest `test_an_object_overriding_getradius_takes_the_python_path` (Review Focus 1), asserting the `surface` fallback count.
  - pytest `test_a_patched_needtoavoid_runs_the_sdk_loop`.
  - pytest `test_lDontAvoidTypes_changed_on_the_instance_is_honoured`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `ctest --test-dir build -R combat_AiAvoid --output-on-failure` and `uv run pytest tests/unit/test_native_avoid_scan.py tests/unit/test_ai_native_gate.py tests/unit/test_avoid_obstacles_sdk_cadence.py tests/unit/test_avoid_obstacles_engine_node.py tests/unit/test_preprocess_done_is_lethal.py tests/unit/test_proximity_manager_iteration.py tests/integration/test_avoid_cadence_still_clears.py tests/integration/test_avoidance_does_not_suppress_combat.py tests/integration/test_pursuers_avoid_each_other.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py -q`. Expect PASS, goldens unchanged, A/B identical, `avoid` native count > 0.
- [ ] **Step 5: Commit** `perf(ai): AvoidObstacles' obstacle scan runs natively for stock instances`.

### Task 3: SelectTarget — `GetTargetRating` in C++

**Files:**
- Create: `native/src/combat/include/dauntless/combat/ai_rating.h`, `native/src/combat/src/ai_rating.cc`, `native/tests/combat/ai_rating_test.cc`, `tests/unit/test_native_target_rating.py`
- Modify: CMakeLists (both), `native/src/host/host_bindings.cc` (`combat_ai_target_rating`), `engine/appc/ai_optimized.py` (register `"SelectTarget"` in `OPTIMIZED_PREPROCESSORS` with a `__dict__`-sharing subclass whose `GetTargetRating` is marked `_dauntless_native_entry`; no other method overridden)

**Interfaces:**
- Consumes: Task 1, and Part 1's `SetIndex::popularity_by_key` (reach the index instance in `host_bindings.cc`'s `si::host()` from the new binding; both live in that file).
- Produces: the C++ core `double target_rating(const RatingInputs&)`, the nine factors summed in the SDK's list order starting from `0.0` (SDK `:1481-1619`), gtested on its own. Inputs: the two positions and our forward, `is_target`, shield percentage, the weapons average (sum in subsystem-match order, divided by count when > 0), hull percentage, damage dealt, priority, popularity, and the nine weights.
- Produces: the binding `combat_ai_target_rating(inst, target) -> float`. It gathers the inputs exactly as the SDK reads them:
  - **Our ship and the -1 return.** `self.pCodeAI.GetShip()`; if it is None, return `-1` (an int, as the SDK does).
  - **Positions and forward** from the transform store.
  - **`fIsTargetGood`** compares names, as the SDK does: with `bSetShipTarget`, our ship's `GetTarget().GetName() == target.GetName()`; otherwise `target.GetName() == self.sCurrentTarget`.
  - **Shields, weapons and hull only when `ShipClass_Cast(target)`:**
    - shields: `GetShields().GetShieldPercentage()` semantics;
    - weapons: the `StartGetSubsystemMatch(CT_WEAPON_SYSTEM)` order, which is `ships.py`'s fixed slot list filtered by the CT class;
    - weapons and hull: `GetCombinedConditionPercentage` semantics.
    - Read from the mirror where `DAUNTLESS_NATIVE_AUDIT=1` proves equality; otherwise call the Python method.
  - **Damage dealt.** `self.dDamageReceived` by `target.GetObjID()`. A missing attribute raises `AttributeError`, as the SDK does.
  - **Priority.** `ObjectGroupWithInfo_Cast(self.pTargetGroup)`, then `[name].get("Priority", 0.0)`.
  - **Popularity.** `popularity_by_key(our ship's containing set, our ship, target)`, or `0.0` with no set. It returns a float.
  - **Weights** from the instance attributes, every call.
  - A target or ship whose type fails `object_surface_is_stock` for the App methods read (`GetWorldLocation`, `GetWorldForwardTG`, `GetTarget`, `GetName`, `GetObjID`, `GetShields`, `GetHull`, `StartGetSubsystemMatch`, `GetContainingSet`) runs the SDK `GetTargetRating` for that call.
- The engine `GetTargetRating`: if `ai_native.enabled("select")` and `preprocessor_is_stock(self, "SelectTarget", ("GetTargetRating",))`, it returns `combat_ai_target_rating(self, pTarget)`; otherwise the SDK method.
- **Registering SelectTarget** must change nothing else. The driver's `_ensure_select_target_initialized` duck-typing, `DamageEvent` registration, the sensor gate's patch on the SDK class (still inherited) and `isinstance(inst, SelectTarget)` must still hold. Pin each.

- [ ] **Step 1: Write the failing tests.**
  - gtests `AiRating.SumsTheNineFactorsInSdkOrder`, `AiRating.DistanceAndAngleEdgeCases`: zero distance, behind, dot clamped at ±1.
  - pytest `test_native_rating_equals_the_sdk_bit_for_bit`: seeded, 300 rater/candidate pairs over ships with and without shields (off, absent, max 0: Review Focus 3), no weapons, damaged weapons and hull, planets and stations as candidates, an `ObjectGroupWithInfo` with priorities, `dDamageReceived` entries, both `bSetShipTarget` values, custom `SetRelativeImportance` weights, and ships targeting the candidate. Compare `float.hex()` of native against the SDK body called directly.
  - pytest `test_find_good_target_picks_the_same_name_gated_and_ungated` (Review Focus 2): the same scene with the sensor gate installed and uninstalled, native against `DAUNTLESS_NATIVE_AI=0`.
  - pytest `test_select_target_registration_keeps_driver_init_and_events`.
  - pytest `test_a_candidate_class_overriding_getworldlocation_takes_the_python_path`.
  - pytest `test_missing_damage_ledger_raises_like_the_sdk`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `ctest --test-dir build -R combat_AiRating --output-on-failure` and `uv run pytest tests/unit/test_native_target_rating.py tests/unit/test_ai_native_gate.py tests/unit/test_select_target_rating.py tests/unit/test_select_target_dispatch.py tests/unit/test_select_target_engine_stubs.py tests/unit/test_select_target_event_hooks.py tests/unit/test_select_target_drops_cloaked.py tests/unit/test_select_target_forceupdate_drops_cloaked.py tests/unit/test_ai_acquires_close_cloaked.py tests/unit/test_ai_sensor_gate.py tests/unit/test_set_index_targeting.py tests/integration/test_select_target_in_priority_list.py tests/host/test_qb_km_targeting.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py -q`. Expect PASS, goldens unchanged, A/B identical, `select` native count > 0.
- [ ] **Step 5: Commit** `perf(ai): SelectTarget rates candidates natively, popularity from the set index`.

### Task 4: FireScript — native `Update`, the firing cycle

**Files:**
- Create: `native/src/combat/include/dauntless/combat/ai_fire.h`, `native/src/combat/src/ai_fire.cc`, `native/tests/combat/ai_fire_test.cc`, `tests/unit/test_native_fire_script.py`
- Modify: CMakeLists (both), `native/src/host/host_bindings.cc` (`combat_ai_fire_update`), `engine/appc/ai_optimized.py` (`_non_lethal_class` for FireScript gains a native-entry `Update`; the PS_DONE → PS_NORMAL mapping stays around it)

**Interfaces:**
- Consumes: Task 1.
- Produces: `combat_ai_fire_update(inst, dEndTime) -> int` (a PS_* code). This is the SDK `FireScript.Update` (SDK `:281-342`) and everything it reaches in this task, natively:
  - `TargetInRange` and `GetTarget`;
  - the `iLastUpdate` cycle and its formula;
  - `FireSystemAtTarget`, `ConfigureWeaponSystem`, `CheckGoodShot`, `GetWeaponInfo`, `PredictTargetLocation` and `WeaponTooDangerous` (SDK `:417-787`).
- In this task, `ChooseTargetSubsystem` and `ChooseTorpType` are called back as `self.<method>(...)`, which Task 5 makes native.
- `TargetVisible` is called as `self.TargetVisible(...)`, because the sensor gate replaces it.
- Every side effect and external read goes through the same Python call the SDK makes, in the same order:
  - `StartFiring`, `StopFiring` / `StopFiringAtTarget`, `FireDumb(0, 1)`;
  - `SetPowerLevel`, `SetMode`, `SetAmmoType`;
  - `CallExternalFunction("UsingWeaponType", lWeapons)` over `pCodeAI.GetAllAIsInTree()[1:]`;
  - `__import__(torpedo script)` and its `GetDamage()`.
- Pure reads (positions, rotations, velocities, accelerations, `GetPositionTG` of subsystems, tube directions, launch speeds) and pure arithmetic are native.
- **State.** `iLastUpdate`, `bTargetVisible`, `idTargetedSubsystem`, `lWeapons`, `sTarget`, `bCallUsingWeaponTypeFunc` and the rest stay attributes of the instance: read on entry, written exactly where the SDK writes them, so `ai_driver._sync_fire_script_target_subsystem`, the AI inspector and mission calls see them unchanged.
- **Callbacks.** After each Python callback, re-read anything borrowed (the Global Constraints' contract) and re-check `pTarget` the way the SDK's next line would.
- **Gate.** The native `Update` runs only if `ai_native.enabled("fire")` and `preprocessor_is_stock(self, "FireScript", <every FireScript method the Update reaches, including Task 5's>)`. Otherwise it runs the SDK `Update`.

- [ ] **Step 1: Write the failing tests.**
  - gtests for the pure pieces: `AiFire.CycleFormula` (len 0, 1, 3; from -2 and -1), `AiFire.PredictTargetLocationMatchesTheSdk` and `AiFire.CheckGoodShotDotThreshold`, each against hand-computed SDK values.
  - pytest `test_native_fire_update_matches_the_sdk_call_by_call`: seeded scenes. Record every Python call the native `Update` makes (method, receiver, args) and the instance's `__dict__` after it, and compare against the SDK `Update` run on a deep copy of the same scene. The scenes:
    - in range and out of range;
    - target invisible, then visible;
    - torpedo, phaser, pulse and tractor systems (with the Dock Stage tractor exception);
    - dumb-fire with tubes facing and not facing;
    - `HighPower` on and off;
    - `WeaponTooDangerous` with in-flight torpedoes targeting us;
    - `bAttackIfNoSubsystemsLeft` off with no subsystem;
    - a `UsingWeaponType` handler registered.
  - pytest `test_a_target_destroyed_by_the_volley_mid_update` (Review Focus 4).
  - pytest `test_a_patched_fire_system_at_target_runs_the_sdk_update` (Review Focus 5).
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `ctest --test-dir build -R combat_AiFire --output-on-failure` and `uv run pytest tests/unit/test_native_fire_script.py tests/unit/test_ai_native_gate.py tests/unit/test_fire_script_update.py tests/unit/test_fire_script_state.py tests/unit/test_fire_script_configure.py tests/unit/test_optimized_fire_script.py tests/unit/test_optimized_fire_script_identity.py tests/unit/test_ai_driver_fire_script_init.py tests/unit/test_codeaiset_bind.py tests/unit/test_ai_driver_subsystem_target_sync.py tests/unit/test_should_be_aimed.py tests/unit/test_torpedo_ammo.py tests/unit/test_torpedo_script_fallback.py tests/unit/test_preprocess_done_is_lethal.py tests/integration/test_fire_script_minimal.py tests/integration/test_weapon_cast_ai_payoff.py tests/integration/test_condition_hooks_reach_combat_ai.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py -q`. Expect PASS, goldens unchanged, A/B identical, `fire` native count > 0.
- [ ] **Step 5: Commit** `perf(ai): FireScript's firing cycle runs natively for stock instances`.

### Task 5: FireScript — subsystem choice and torpedo choice native

**Files:**
- Modify: `native/src/combat/src/ai_fire.cc`, `native/src/combat/include/dauntless/combat/ai_fire.h`, `native/src/host/host_bindings.cc`, `native/tests/combat/ai_fire_test.cc`, `tests/unit/test_native_fire_script.py`

**Interfaces:**
- Consumes: Task 4.
- Produces: the native `Update` no longer calls back `self.ChooseTargetSubsystem` / `self.ChooseTorpType`; it runs them natively (SDK `:533-640`, `:789-1045`): `GetTargetableSubsystems`, `RateSubsystemForTargeting`, `PickTargetSubsystemFromList`, the incremental `dTargetSubsystemRating` update (`iNumTargetSubsystemsToUpdate = 4`, pruning deleted keys), the priority-list and player-target branches, and the `GetChildTargets` helper `ai_optimized.py` supplies.
- **RNG.** Every draw is `App.g_kSystemWrapper.GetRandomNumber(n)` called in Python at the SDK's point, so it uses the same stream, order and count, `n <= 0` included.
- **Fuzzy logic.** `App.FuzzyLogic_BreakIntoSets` is called in Python.
- **Torpedo scripts.** `GetDamage`, `GetGuidanceLifetime` and `GetMaxAngularAccel` come from `__import__(GetTorpedoScript())` in Python, with the SDK's except branch reproduced. That includes its latent unbound-`pScript` `NameError`: the same exception, not a fix.
- `dTargetSubsystemRating` stays a Python dict on the instance, read and written in place.

- [ ] **Step 1: Write the failing tests.** Extend `test_native_fire_script.py`'s call-by-call comparison with:
  - `ChooseSubsystemTargets` on, with 2, 4 and 9 targetable subsystems (the RNG branch), where the RNG draws (count and arguments) must match;
  - a subsystem destroyed between updates (key pruning);
  - an ignored-subsystem list;
  - a player-driven target subsystem;
  - smart torpedo selection with 1, 2 and 3 ammo types, one empty;
  - a torpedo script that fails to import (the except branch).
  Also add gtests for the pure rating pieces.
- [ ] **Step 2: Run them; they fail** (the native Update still calls back; assert the call log shows no `ChooseTargetSubsystem` / `ChooseTorpType` callback).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** Task 4's Step 4 list plus `tests/unit/test_fire_script_choose_subsystem.py tests/integration/test_akira_ai_ammo_selection.py tests/integration/test_disable_order_targets_child_subsystems.py`. Expect PASS, goldens unchanged, A/B identical.
- [ ] **Step 5: Commit** `perf(ai): FireScript's subsystem and torpedo choice run natively`.

### Task 6: The contact view's per-frame cost (Part 1's regression)

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`set_index_ship_positions`), `engine/appc/contact_index.py` (`ship_positions_in`), `engine/appc/set_index.py`
- Test: `tests/unit/test_set_index.py`, `tests/unit/test_contact_index.py`

**Interfaces:**
- Produces: `contact_index.ship_positions_in(pSet)` answered by one binding. It returns `((ship, (x, y, z)), ...)` built in C++ from the distinct live ships and the transform store, with the same values and order as today, under the allocate-first rule. `ships_in` gets cheaper too: no per-call hash set for de-duplication when the set has no duplicate entries (keep a per-set "has duplicates" count in the core).
- SIG-205: `contacts.perceive` +0.05 ms a frame; `ships_in` 2.5 → 37 µs a call, `ship_positions_in` 159 → 193 µs a call. Target: below the pre-Part-1 numbers.

- [ ] **Step 1: Write the failing test** `test_ship_positions_in_is_one_native_call_with_unchanged_values`: patch the transform store's Python `get_positions` to raise. It must not be called, and the values equal a recorded reference computed the old way in the same test.
- [ ] **Step 2: Run it; it fails.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_set_index.py tests/unit/test_contact_index.py tests/unit/test_contact_index_set_maintenance.py tests/integration/test_golden_fights.py -q` and `ctest --test-dir build -R combat_SetIndex`. Expect PASS.
- [ ] **Step 5: Commit** `perf(ai): ship_positions_in is one native call`.

### Task 7: Measure, record, live-check list

- [ ] **Step 1: Ask Mark** to clear the machine and approve the runs.
- [ ] **Step 2: Release** in `.claude/worktrees/release-macos`, detached at this branch's tip. One build, A/B by the switch, back to back: `DAUNTLESS_NATIVE_AI=0` against unset. 64 and 128 ships, exterior and bridge, two runs each, using the command in `docs/reference/engine/native-motion/phase0-runbook.md` §1, as in SIG-205 (`scratchpad` script `p6ai1_capture.sh` shape). Then one cProfile run each side at 128 exterior (`DAUNTLESS_PROFILE_PY`, frames 500:400).
- [ ] **Step 3: Score** frame ms, ticks a frame, per-tick `gl.ai` and `ai.avoid`, `sim.combat`, and per-frame `contacts.perceive`, as the median of reports 3–11. From cProfile: `tick_all_ai`'s share of the root, and the three preprocessors' cumulative times. Report the `ai_native` stats lines (native against Python counts and reasons) from the log.
- [ ] **Step 4: Perf register.** Add the captures and one signal (the next SIG id) beside SIG-205. State the catch-up confound: per-tick rows compare, and frame ms at 128 moves with ticks a frame and projectiles. Say plainly where the gain is inside the spread.
- [ ] **Step 5: Commit** `docs(perf): phase 6 AI part 2, native stock preprocessors (SIG-…)`.
- [ ] **Step 6: Live-check list** for Mark:
  - a 64-ship and a 128-ship Quick Battle (targets picked and switched, ships avoid each other and rocks, firing);
  - a cloaked Warbird fight (CloakAttack);
  - E1M2 Haven (rocks, avoidance);
  - a Quick Battle with an Akira (torpedo choice);
  - a disable order (subsystem targeting);
  - the LC Intrepid mod ship (mod AI path).

### Task 8: Delete the build switch; record the design

**Files:**
- Modify: `engine/appc/ai_native.py` (delete `enabled` and the switch, keeping counters and the stock gate), `engine/appc/ai_optimized.py`, `tests/helpers/native_ai_ab.py` + `tests/integration/test_native_ai_ab.py` (the A/B now forces the Python side by patching a gate hook in-process: `ai_native._force_python = True`, a test-only module flag that `preprocessor_is_stock` honours), `engine/appc/ai_optimized.py`'s module docstring (the three native nodes, what stays Python and why), CLAUDE.md (one new row "Native stock preprocessors": files, the stock rule, what stays SDK Python, the A/B test, the counters line)
- Test: everything Task 7 ran, plus `tests/docs`

- [ ] **Step 1: Write the failing test** `test_no_native_ai_switch_remains`: grep `engine/` and `native/` for `DAUNTLESS_NATIVE_AI` and expect no hit.
- [ ] **Step 2: Run it; it fails.**
- [ ] **Step 3: Delete the switch; rewire the A/B; write the docstring and the CLAUDE.md row.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_ai_native_gate.py tests/integration/test_native_ai_ab.py tests/integration/test_golden_fights.py tests/docs -q`. Expect PASS.
- [ ] **Step 5: Commit** `refactor(ai): native preprocessors have no switch; SDK Python is the mod path only`.
