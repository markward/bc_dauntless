# Native motion (phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo: one `tdd-engineer` subagent per task, in order, focused tests only, commit between tasks, stop on any BLOCKED (CLAUDE.md "Executing plans").

**Status:** DRAFT, written 2026-11-04 against `project/native-motion-and-proximity` at `87401fe33`. Line numbers below were checked at that commit; re-locate by name if a merge moved them.

**Goal:** Run ship motion (`gl.motion`, ≈ 1.40 ms a tick at 64 ships, SIG-180) as one native kernel per tick, bit-exact with today's Python, then move the tractor force into the motion stage so motion is the only ship-pose writer, and publish the tick's poses.

**Architecture:** Kernel M lives in the combat library beside the mirror it reads. Python stays the authority: every input M reads is mirrored by a push on write, M computes with the GIL released (writing the transform store and the mirror's motion fields), and C code then stores the results quietly into the Python objects. Rows M cannot run (in-system warp, a non-stock class, an unrepresentable value) stop the kernel, Python runs that row, and the kernel resumes at the next row, so every ship still sees earlier ships moved and later ones not. `DAUNTLESS_NATIVE_MOTION=0` keeps the Python path, which stays as the reference until Mark's live check.

**Tech Stack:** Python 3.11 (engine), C++20 (`native/src/combat`, pybind11 and the C API in `native/src/host`), pytest, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md` §5.2 (the authority), §3, §4, §6, §7, §8. Maps: `docs/reference/engine/native-motion/motion-state-audit.md` (MSA), `golden-fights-for-motion.md` (GFM), `open-questions-by-reading.md` (OQR). Their line numbers are from `2369cba41`; this plan's are current.

**Rulings this plan builds on (Mark, 2026-11-04):**
- The tractor force moves into the motion stage (spec §8 Q1 answered). It is Task 7, after the bit-exact port and its unchanged goldens. Its pull then starts one tick after the K1 tractor walk engages; that is accepted.
- GitHub #9 (forces do not change momentum) goes into phase 2 unless it is significant scope creep. **Judged significant; kept out.** See "GH #9" below.

### Open questions for Mark

1. **GH #9.** Out of this phase (reasons below). Take the narrow slice (drifting and scripted-velocity ships only) into phase 2 as Tasks 7a–7b, or leave all of #9 for its own design spec?
2. **Spec §8 Q8 side findings.** The port keeps both: a manually flown player's `_current_speed` is stale (`GetImpulse`/`IsReverse` read it wrong), and after the SDK's `MissionLib.StopShip` both integrators can drive the player. Fix them in a later commit, or leave them?

### GH #9: why it stays out

What a fix needs, from `engine/appc/ship_motion.py`, `drift.py`, `tractor.py`, `collisions.py` and `host_loop._PlayerControl`:
- **A powered ship has nowhere to keep a sideways push.** Its motion is a scalar along the nose (`_current_speed`, `ship_motion.py:283-302`). A tractor or collision delta-v across the nose needs a new persistent world-velocity term, and a rule for how the engines cancel it (rate, damping, whether the AI fights it). BC's force model is not reconstructed (OQ-2.3; the issue's own "What we don't know yet"). That rule would be an invented mechanism.
- **The tractor law changes in C++.** `tractor_force.cc` is a kinematic displacement. Release momentum needs it to produce a velocity per mode (HOLD, TOW, PULL, PUSH, DOCK), each an assumption.
- **Collisions run once per frame, after the ticks, host only** (`collisions.tick_collisions`, `_apply_overlay_all` `collisions.py:1043-1060`). Feeding their impulse into tick-owned motion state either ties that state to frame rate or moves collisions per tick (phase 4 territory). The sustained-contact and grind tests are calibrated against the decaying overlay.
- **The manual player has its own copies** (`_PlayerControl._current_speed`, `_drift_velocity`): a non-goal of this project (spec §4), but a rammed player would otherwise behave unlike a rammed AI ship.
- **Scripted `SetVelocity` on an AI ship** (the documented "known gap", spec §4 non-goal) needs a precedence rule against the AI's next setpoint.
- **Size:** a design spec, then about 6–8 tasks across six engine files (`ship_motion.py`, kernel M, `tractor_force.{h,cc}`, `tractor.py`, `collisions.py`, `host_loop._PlayerControl`) and about 15 test files, plus golden re-records and a live feel check. That is about this whole phase again, and it changes the very behaviour the port pins.

**The narrow slice, if Mark wants it now (moderate, about 2 tasks after Task 7):** only ships whose motion is already a world velocity, the all-pods-out drifters (`_drift_velocity`) and setpoint-less ships (`_velocity`). HOLD zeroes that velocity, so a stopped drifter stays stopped (the symptom seen in play). A collision impulse adds to it instead of the overlay. TOW/PULL/PUSH release with the last step's displacement ÷ dt. Assumptions it would make, all against unreconstructed BC: HOLD cancels momentum; the release velocity is the beam's last step; a collision changes a drifter's velocity permanently; powered ships keep today's behaviour.

## Global Constraints

- **Worktree only:** work in `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-motion`. Never `cd` to the main checkout.
- **Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs. To mutate a file temporarily: `cp` to the scratchpad, mutate, `cp` back, `diff`.
- **Focused test files only.** Never a directory, never an empty file list, never a whole suite, never `scripts/check_tests.sh`.
- **Build:** `cmake --build build -j` from the worktree root only. Never reconfigure, never change `CMAKE_BUILD_TYPE`, never run cmake inside `native/`. A `_dauntless_host has no attribute` error means a stale build: rebuild.
- **No benchmarks** except Task 8, on an idle machine. **No game launches** without Mark's say-so.
- **Never commit to `main`.**
- **Goldens** are re-recorded only with `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="<why>"`, in their own commit, whose message names the behaviour change and the scenes. Tasks 2–6 change no existing golden: a changed one is a bug, STOP and report BLOCKED with the first differing tick and field.
- **Python stays the authority.** The mirror is a copy; resync, a dropped row and the switch all fall back to Python's values. `_current_angular_velocity` keeps its TGPoint3 object and is updated in place.
- **Bit-exact with Python:** every kernel source is in `DAUNTLESS_COMBAT_SOURCES` (`-ffp-contract=off`, `-O2` in Debug). Use `py_min`/`py_max`, never `std::min`/`std::max`; `py_pow(x, 0.5)` for `** 0.5`; `py_sin`/`py_cos`, never `std::sin`/`std::cos`; `std::sqrt` for `math.sqrt`. `TGMatrix3.MultMatrix` is `0.0 + a·b + c·d + e·f`, k ascending; `TGPoint3.MultMatrixLeft` has NO leading `0.0 +` (`math.py:86-96`); `MakeRotation` is the full Rodrigues form with the axis components (`math.py:232-240`), never a specialised axis rotation; Python's truthiness test `x or y or z` is `x != 0.0 || y != 0.0 || z != 0.0` (NaN is true).
- **Line references:** re-locate by name before editing; the maps' numbers predate merges.

## Review Focus

1. **A subclass or a monkeypatch of the motion surface** (a mod ship overriding `SetVelocity` or `IsImmobile`, an IES overriding `IsOn`, a test patching `ship_motion.impulse_fractions` or `drift.step`). Expected: the patch still runs. The row (class flags) or the whole stage (function snapshot) takes the Python path. Tests in Tasks 2 and 5.
2. **An in-place write to `_current_angular_velocity` outside motion** (manual flight's `_apply_body_rotation`, the manual→AI seed, a Python-path row), followed by a native tick. Expected: the kernel ramps from the written value. Tests in Task 2.
3. **The roster changes mid-stage.** An `ET_IN_SYSTEM_WARP` handler run inside a Python-owned row deletes a later ship, retargets one, or changes the current player. Expected: no crash, no stale handle; later rows see the change exactly as Python would. Test in Task 5.
4. **NaN and odd values** in a setpoint, a speed or a rate (an SDK script dividing by a zero length). Expected: the same branch and the same bits as Python. Values the mirror cannot represent (a tuple where a TGPoint3 belongs) take the Python path and raise there, as today. Tests in Tasks 4 and 5.
5. **The switch flipped between ticks** (`configure` with `DAUNTLESS_NATIVE_MOTION=0`, then on again), and the audit mode. Expected: motion continues without a jump, and `audit_mirror` stays clean either way. Test in Task 5.

---

### Task 1: The `motion_branches` golden scene and `motion` rows, recorded from today's Python

**Files:**
- Create: `tests/helpers/motion_fight.py`
- Modify: `tests/helpers/golden_fight.py` (`FIELDS` ~:100, `SCENES` ~:604, a `_motion_branches` wrapper), `tests/integration/test_golden_fights.py` (one test)
- Create (recorded): `tests/fixtures/golden_fights/motion_branches.darwin.json.gz`

**Interfaces:**
- Produces: `motion_fight.motion_rows(ships) -> list` of `["motion", name, ...]` rows; `motion_fight.run(mp, env, ticks) -> (state, events, queued)`, per tick: `_pose_rows` plus `motion_rows`; `golden_fight.FIELDS["motion"]`:
  `("name", "_current_speed", "_current_angular_velocity", "_drift_velocity", "_speed_setpoint", "_target_angular_velocity_setpoint", "_angular_velocity", "_angular_space", "warp_flight", "_warp_consumed", "arriving", "impulse_fractions", "effective_motion")`.
  Floats `.hex()`; absent or None is `None`; values read with `ship.__dict__.get` (never `getattr`: `TGObject.__getattr__`); `warp_flight` is None or `[target label, speed_policy, _parts_hold hex, _held hex]`; `impulse_fractions` is one `subsystems.impulse_fractions(ies)` call; `effective_motion` the six `_effective_motion(ship)` fields.
- Scene: `Scene("motion_branches", "native", <seed>, "2", 700, 1, _motion_branches)`. `SCHEMA` is not bumped: only this scene writes `motion` rows (GFM §3.2).

**Cast, in set order** (GFM §5.1; row order decides the kernel's segments): `Anchor` (Galaxy, `SetStatic(1)`, given a speed setpoint), `Ramp` (Galaxy), `Warper` (Galaxy, `InSystemWarp(Target, 50)` at tick 30, facing `Target` 600 GU off), `WarperBoP` (Bird of Prey, same: parts hold, so `warp_flight.step` returns False first), `Arriver` (Galaxy, dewarp drive from tick 20, setpoints after arrival), `Drifter` (no AI, `SetVelocity` + model-space `SetAngularVelocity`), `DrifterW` (the same in world space), `Cripple` (ramping; tick 200 every pod `SetCondition(0)`; tick 400 one pod back to max; one pod carries `_radiation_out = True` throughout), `Bare` (a `ShipClass_Create` with no IES), `ZeroLimits` (an IES with authored limits 0), `Target` (still), and the player (no setpoints, then `SetSpeed` at tick 500). combat_stress's two AI ships get `ClearAI()` after load. Ships come from `loadspacehelper.CreateShip`, so their IES has real pods.

**`Ramp` beats:** speed above max; pods to 50% while above the new cap; reverse; an angular setpoint above `max_ang_vel`; `SetPowerPercentageWanted(0.5)`; IES `TurnOff` then `TurnOn`; a world-space direction; `_speed_setpoint = None` with an angular setpoint left.

**Driver:** reuse, never copy: `k1_fight._seed_every_rng`, `headless_mission.clear_in_flight`, `fight_audio.isolate_fight_audio`, `effect_split.Queued`, and an `AddEvent` spy like `k1_fight._Scene.__init__`'s. Set `env` with `mp.setenv` before building `GameLoop(owns_boundary=False)`. Per tick: beats, `loop.tick()`, `host_loop._combat_tick_boundary()`, record. No weapons, no combat, no tractor.

- [ ] **Step 1: Write the test and the scene's self-checks.** `test_motion_branches()` in `test_golden_fights.py` calls `_golden("motion_branches")`. Inside `motion_fight.run`, assert after the loop: `Anchor`'s pose never changed; a `warp_flight` was seen on `Warper` and ended; `WarperBoP` had ticks with a flight and `_parts_hold > 0` and its position still changed; `arriving` was True on `Arriver` for 110–130 ticks; `Cripple`'s `_drift_velocity` was set, then cleared; `Bare`'s `_current_speed` equalled its setpoint one tick after it was written; the player's pose was unchanged before tick 500 and changed after; `ET_IN_SYSTEM_WARP` was posted both True and False.
- [ ] **Step 2:** Run `uv run pytest tests/integration/test_golden_fights.py::test_motion_branches -v`. Expected: SKIP naming the missing `motion_branches.darwin.json.gz`.
- [ ] **Step 3: Record.** `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="new scene: every motion branch, recorded from the Python motion before the native port (phase 2 Task 1)" uv run pytest tests/integration/test_golden_fights.py::test_motion_branches`. Expected: written, then SKIP.
- [ ] **Step 4:** Run it again without the variable, twice. Expected: PASS both times (determinism, R10). Run `uv run pytest tests/integration/test_golden_fights.py -v`. Expected: every other scene PASS, unchanged.
- [ ] **Step 5: Commit** the three test files and the fixture: `test(golden): motion_branches scene, recorded from the Python motion`.

### Task 2: Mirror every input kernel M reads

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/mirror.h` (`Field` enum, `ObjectRow`, `SubsystemRow`), `native/src/combat/src/mirror.cc` (field table, setters, dump), `engine/appc/native_combat.py` (new value types, `_flags`), `engine/appc/objects.py` (`PhysicsObjectClass` descriptors ~:677), `engine/appc/ships.py` (descriptors ~:18-50; `_impulse_engine_subsystem` :31), `engine/appc/subsystems.py` (`PoweredSubsystem._power_percentage_wanted` :1410; `ImpulseEngineSubsystem` :1825), `engine/appc/ship_motion.py` (one push after the in-place ramp, :318-320), `engine/host_loop.py` (`_PlayerControl._apply_body_rotation` :3167-3171, `_sync_ship_integrator_from_control` :3234-3238)
- Test: `tests/unit/test_native_motion_mirror.py` (new), `native/tests/combat/mirror_test.cc` (extend)

**Interfaces:**
- **Object fields** (all on `ObjectRow`; Python descriptor in brackets):
  - `_current_speed` F [`NativeField(float)`, ShipClass]
  - `_current_angular_velocity`, `_drift_velocity`, `_target_angular_velocity_setpoint` [ShipClass], `_angular_velocity` [PhysicsObjectClass]: type `native_combat.POINT_OR_NONE`. Encodes None or absent as `[]` (state 0, unset), a `TGPoint3` as `[x, y, z]` (state 1), anything else as `[0.0, 0.0, 0.0, 0.0]` (state 2, unrepresentable). The row keeps `<name>_state` beside the Vec3.
  - `_speed_setpoint` FloatList [`SpeedSetpointField`, ShipClass]: None is `[]`; `(speed, d, frame)` is `[float(speed), float(d.x), float(d.y), float(d.z), float(frame)]`; anything that does not unpack so is `[0.0] * 6` (unrepresentable). One `combat_set_floats` call per write.
  - `_angular_space` I, row default 1 (`DIRECTION_WORLD_SPACE`, as `getattr`'s default and `RockClass._become_rock`'s setdefault) [`NativeField(int)`, PhysicsObjectClass].
  - `_static`, `_stationary` I [`NativeField(bool)`; `IsImmobile` is `bool(...) or bool(...)`].
  - `_insystem_warp_transit` I [`PresenceField`: `0 if value is None else 1`].
  - `_impulse_engine_subsystem` Ref [becomes `NativeMountRefField("Subsystem")` instead of `MountSlotField`].
  - `motion_stock` I (a `_flags` class flag): 1 when `type(obj)` is a ShipClass whose `IsImmobile`, `IsStatic`, `IsStationary`, `GetImpulseEngineSubsystem`, `GetTranslate`, `SetTranslateXYZ`, `GetWorldRotation`, `SetMatrixRotation` and `SetVelocity` are the same function objects as `ShipClass`'s.
- **Subsystem fields:** `_power_percentage_wanted` F [`NativeFrozenField(float)`, so the passive-power thaw still runs]; `_max_speed`, `_max_accel`, `_max_angular_velocity`, `_max_angular_accel` F [`NativeField(float)`, ImpulseEngineSubsystem]; flags `motion_ies_stock` (the class's `IsDisabled`, `IsDestroyed`, `IsOn`, `GetNumChildSubsystems`, `GetChildSubsystem`, `GetPowerPercentageWanted`, `GetParentShip` and the four `GetAuthoredMax*` are ImpulseEngineSubsystem's) and `motion_pod_stock` (`IsDisabled`, `IsDestroyed`, `GetConditionPercentage`, `GetMaxCondition` are ShipSubsystem's).
- **In-place writers push:** after the in-place component writes at `ship_motion.py:318-320`, `host_loop.py:3169-3171` and `:3236-3238`, call `native_combat.push_field(<ship>, "_current_angular_velocity")`. That is behaviour-neutral, and it is what keeps a native tick after any of them exact.

- [ ] **Step 1: Write the failing tests** in `test_native_motion_mirror.py` (fixture: `nc.reset()`, `nc.configure({})`; each test reads the row with `_h.combat_dump(h)`):
  - `test_each_motion_input_is_pushed_on_write`: for every field above, a write through its real setter (`SetSpeed`, `SetTargetAngularVelocityDirect`, `CompleteStop`, `SetStatic`, `SetStationary`, `SetAngularVelocity(v, 0)`, `SetPowerPercentageWanted`, `SetMaxSpeed`/…, `SetImpulseEngineSubsystem`, `begin_warp_flight`/`_end_in_system_warp`) leaves the dump equal to its encoding, floats by `.hex()`;
  - `test_point_or_none_states`: None → 0, `TGPoint3` → 1, a 3-tuple → 2;
  - `test_speed_setpoint_none_tuple_and_garbage`;
  - `test_angular_space_defaults_to_world_and_rock_setdefault_agrees`;
  - `test_in_place_angular_velocity_writes_are_pushed`: `_PlayerControl._apply_body_rotation(player, 0.1, 0.2, 0.3, dt)`, `_sync_ship_integrator_from_control`, and one Python `_step_ship_motion` ramp each leave the row equal to `__dict__`;
  - `test_power_percentage_wanted_still_thaws_a_frozen_consumer` (the `FrozenField` contract, CLAUDE.md passive power);
  - `test_motion_stock_flags`: stock ShipClass and IES give 1; a subclass overriding `SetVelocity`, an IES subclass overriding `IsOn` and a pod class overriding `GetConditionPercentage` each give 0;
  - `test_audit_clean_after_a_headless_fight`: combat_stress, 8 ships, `DAUNTLESS_NATIVE_AUDIT=1`, 120 `GameLoop.tick()`s, then `nc.audit_failures() == []`;
  - gtest `Mirror.MotionFieldsRoundTrip`, `Mirror.PointOrNoneState`.
- [ ] **Step 2:** `cmake --build build -j`; `uv run pytest tests/unit/test_native_motion_mirror.py -v`. Expected: FAIL (unknown field ids).
- [ ] **Step 3: Implement** the fields, the three value types (`POINT_OR_NONE`, `SpeedSetpointField`, `PresenceField`) with `_encode` and `_matches` (the audit uses `_matches`), the `_flags` entries and the three pushes.
- [ ] **Step 4:** Build; run the new file, `ctest --test-dir build -R combat_Mirror\.`, and unchanged: `tests/unit/test_ship_motion.py tests/unit/test_ship_motion_drift.py tests/unit/test_ship_motion_stubs.py tests/unit/test_impulse_fractions_fused.py tests/unit/test_impulse_degradation_motion.py tests/unit/test_motion_power_factor.py tests/unit/test_static_object_immobility.py tests/unit/test_dewarp_drive.py tests/unit/test_player_ai_motion_handoff.py tests/unit/test_player_control_velocity.py tests/unit/test_passive_power.py tests/unit/test_native_combat_world.py`. Expected: PASS. Then `tests/integration/test_golden_fights.py`. Expected: PASS, unchanged.
- [ ] **Step 5: Commit** (every file above, by path): `feat(native): mirror the motion inputs`.

### Task 3: Native impulse fractions

**Files:**
- Create: `native/src/combat/include/dauntless/combat/impulse.h`, `native/src/combat/src/impulse.cc` (add to `DAUNTLESS_COMBAT_SOURCES`)
- Modify: `native/src/host/host_bindings.cc` (beside the combat bindings), `native/tests/combat/CMakeLists.txt`
- Test: `native/tests/combat/impulse_test.cc` (new), `tests/unit/test_native_impulse_fractions.py` (new)

**Interfaces:**
- C++: `struct ImpulseFractions { double online; double output; };` and `ImpulseFractions impulse_fractions(const Mirror& m, int64_t ies);`. It is a port of the FUSED walk, `subsystems.impulse_fractions` (`subsystems.py:3718-3768`): `ies == -1` gives (1, 1); `_is_offline(ies)` (leaf `IsDisabled`/`IsDestroyed`, then `is_offline_after_condition` from `sensor_detect.h`) gives (0, 0); no children gives (1, 1); otherwise per child, `disabled = leaf IsDisabled`, `offline = disabled || leaf IsDestroyed` when the IES has `has_parent_ship_getter`, else the full `_is_offline(pod)`; `contrib += condition_percentage(pod)` for a not-disabled pod; `online = online_n / n`, `cur = contrib / n`; switched off (`!_is_on`) gives `(online, 0)`; else `(online, py_max(0.0, py_min(1.0, cur)) * _power_percentage_wanted)`. The pod's own `_radiation_out` is NOT read under a known-good ship (OQR Q1). It throws `std::invalid_argument` where the mirror cannot answer (a `-2` ref, a gone row, a non-ShipClass parent in `_out_of_action`).
- Binding: `combat_impulse_fractions(ies_handle: int) -> tuple[float, float]`. It holds the GIL and raises ValueError on a fall-back. It is used by tests and by nothing in play (M calls the C++ directly).

- [ ] **Step 1: Write the failing tests:**
  - `test_native_matches_the_fused_walk_on_random_engines`: seeded, 500 IES states (0–4 pods; condition, max, disabled percentage, `_destroyed`, property max on or off; IES on or off, slider 0–1.25, IES radiation, ship dying or dead), compared with `subsystems.impulse_fractions` by `.hex()`;
  - `test_pod_radiation_out_follows_the_fused_walk` (the latent gap, pinned): a pod with `_radiation_out = True` gives native == fused, and fused online != `impulse_online_fraction(ies)`. The docstring says this difference is deliberate today and why (OQR Q1);
  - `test_unrepresentable_child_raises`;
  - gtests `ImpulseFractions.NoIes`, `.NoPods`, `.OfflineMasterZero`, `.DisabledPodForfeitsShare`, `.SwitchedOffKeepsOnline`, `.ClampBeforeSlider` (slider 1.25 gives 1.25), `.DyingShipZero`.
- [ ] **Step 2:** Build; run both. Expected: FAIL (no symbol / no binding).
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4:** Build; `ctest --test-dir build -R combat_ImpulseFractions`; `uv run pytest tests/unit/test_native_impulse_fractions.py tests/unit/test_impulse_fractions_fused.py tests/unit/test_impulse_online_fraction.py -v`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(combat): native impulse fractions, the fused walk`.

### Task 4: Kernel M

**Files:**
- Create: `native/src/combat/include/dauntless/combat/motion_step.h`, `native/src/combat/src/motion_step.cc` (in `DAUNTLESS_COMBAT_SOURCES`), `native/tests/combat/motion_step_test.cc`, `engine/appc/native_motion.py` (Task 4 part: the reference applier and constants)
- Modify: `native/src/host/host_bindings.cc` (`ComputeSite::Motion`, `kComputeKernels` 5 → 6 at :4028, `combat_compute_take` accepts 5, binding `combat_motion_compute`), `native/tests/combat/CMakeLists.txt`, `tests/unit/test_native_k1_holds_gil.py` (`RELEASED` gains `combat_motion_compute`)
- Test: `tests/unit/test_native_motion_kernel.py` (new)

**Interfaces:**
- C++ (`motion_step.h`):
  ```cpp
  enum class MotionStop : int32_t { Done = 0, WarpRow = 1, PythonRow = 2 };
  enum class MotionReason : int32_t { None = 0, NoRow, NotStock, Unrepresentable, FallBack, BadTransform, kCount };
  enum MotionWhat : uint8_t { kSpeed = 1, kAngVel = 2, kVelocity = 4, kDriftSet = 8, kDriftClear = 16 };
  struct MotionWrite { uint32_t row; uint8_t what; double speed; Vec3 cav, velocity, drift; };
  struct MotionResult { MotionStop stop; int64_t at; MotionReason reason; std::vector<MotionWrite> writes; };
  MotionResult motion_step(Mirror& m, TransformStore& store,
                           const std::vector<int64_t>& rows, int64_t player,
                           double dt, int64_t begin, bool resume_past_warp);
  ```
- **The walk** starts at `begin` and ports `_step_ship_motion` (`ship_motion.py:173-322`), `_integrate_rotation` (:325-338), `_effective_motion` (:91-131), `_cap_keep`, `_asymptote_step`, `_ramp_toward` and `drift.step` (`drift.py:45-76`). Per row:
  1. no row, `motion_stock == 0`, or an invalid transform → stop `PythonRow`;
  2. immobile → next row;
  3. in-system warp present, unless `resume_past_warp && row == begin` → stop `WarpRow`;
  4. `arriving` → next;
  5. no setpoints → `drift.step` unless `row == player`;
  6. else impulse fractions, then every pod out (`f <= 0`) → inertial drift, else the powered ramp, then rotation.
- **Each row is computed into locals and committed at its end.** A throw or an unrepresentable input (state 2, an IES ref of -2, an unrepresentable setpoint) stops `PythonRow` at that row with nothing of it written. A commit writes the store pose, the mirror's `_current_speed`, `_current_angular_velocity`, `_velocity` and `_drift_velocity`, and appends a `MotionWrite` with exactly the attributes Python would have written. The drift branch writes only the pose: `drift.step` sets no velocity. `kDriftSet` happens only on the snapshot tick, `kDriftClear` only when a snapshot existed.
- **Copied details that are easy to miss:**
  - with `sp` None, `world_dir` is world (0, 1, 0), neither rotated nor unitized (:234-236);
  - the model-space direction uses the rotation before this tick's spin;
  - translation is `p + (w·s)·dt`;
  - `if speed != 0.0` guards only the translate, not `SetVelocity`;
  - an angular accel ≤ 0 falls back to `FALLBACK_MAX_ACCEL` (1e9), and so does a linear accel ≤ 0 (`BC_IMPULSE_TAU` 1.0);
  - `drift.step`'s rate is `py_pow(x² + y² + z², 0.5)`; model-space spin post-multiplies, world pre-multiplies.
- **Binding:** `combat_motion_compute(handles: list[int], player: int, dt: float, begin: int, resume_past_warp: bool) -> (stop, at, reason, writes)`, with `writes` as `[(row, what, speed, (cx, cy, cz), (vx, vy, vz), (dx, dy, dz)), ...]`. It is one `released_compute(ComputeSite::Motion, ...)` around `motion_step` alone; the tuple build stays under the GIL.
- **Python** (`native_motion.py`): the constants `DONE, WARP_ROW, PYTHON_ROW`, the `REASONS` names, and `_apply_writes_py(ships, writes) -> None`, THE REFERENCE applier. Per write it does quiet `__dict__` stores (no push: the kernel wrote the mirror): `_current_speed`; `_current_angular_velocity`'s `.x/.y/.z` set in place on the existing object; `_velocity = TGPoint3(...)`; `_drift_velocity = TGPoint3(...)` or `None`. When one store raises, it applies the rest, then re-raises the first, as `native_combat.apply_writes` does.

- [ ] **Step 1: Write the failing tests.**
  - `test_native_motion_kernel.py`, one single-ship differential per branch through the binding plus `_apply_writes_py`, against Python `_step_ship_motion` from the same snapshot (save the pose and attributes; run native; read the results; restore; run Python; compare by `.hex()`):
    - `test_powered_ramp_model_space`, `test_powered_ramp_world_space`, `test_cap_keep_does_not_brake`, `test_reverse`, `test_switched_off_engine_snaps_down`, `test_angular_caps`;
    - `test_total_loss_snapshot_then_hold`, `test_total_loss_with_no_speed_setpoint_drifts_world_y`;
    - `test_repair_reseeds_speed_from_drift_length`;
    - `test_fallback_limits_bare_ship`, `test_fallback_limits_zero_authored`;
    - `test_setpointless_drift_model_and_world_spin`, `test_setpointless_player_is_untouched`;
    - `test_immobile_skips`, `test_arriving_skips`;
    - `test_nan_setpoint_takes_pythons_branch` (Review Focus 4);
    - `test_unrepresentable_angular_velocity_stops_python_row_and_writes_nothing`;
    - `test_warp_row_stops_and_resume_past_warp_runs_it`;
    - `test_rows_before_a_stop_are_committed_and_after_untouched`.
  - gtests `MotionStep.BranchOrder`, `.StopsBeforeWritingTheRow`, `.ResumePastWarpOnlyForBegin`, `.DriftWritesOnlyPose`, `.SignedZeroRotation` (cav with -0.0 components), `.FallbackAccelOnZeroLimits`.
  - `test_native_k1_holds_gil.py`: the new `RELEASED` entry, `"combat_motion_compute": ("Motion", "cb::motion_step(cb::mirror(), dauntless::transform_store(), rows, player, dt, begin, resume)")` (match the call as written).
- [ ] **Step 2:** Build; run the files and `ctest --test-dir build -R combat_MotionStep`. Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4:** Build; rerun Step 2's commands plus `tests/unit/test_native_gil_release.py tests/unit/test_matrix_multiply_exact.py tests/unit/test_native_combat_math.py`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(combat): kernel M, the native ship-motion step`.

### Task 5: The driver: C write-back, segments, the switch, wired into `gl.motion`

**Files:**
- Create: `native/src/host/motion_write_apply.{h,cc}` (add to `native/src/host/CMakeLists.txt`)
- Modify: `native/src/host/host_bindings.cc` (binding `combat_motion_step`), `engine/appc/native_motion.py` (driver), `engine/appc/ship_motion.py` (`tick_all_ship_motion` :154; split `_step_ship_motion` at the warp check into `_step_ship_motion` + `_step_after_warp(ship, dt)`, behaviour-neutral), `engine/core/loop.py` (`GameLoop.__init__` calls `native_motion.configure()` after `native_combat.configure()`), `engine/appc/native_combat.py` (`reset()` calls `native_motion.reset()`, imported lazily), `tests/helpers/golden_fight.py` (`ARMS["python_motion"] = {**k1d.ON, "DAUNTLESS_NATIVE_MOTION": "0"}`), `tests/integration/test_golden_fights.py`, `tests/unit/test_native_k1_holds_gil.py`, `tests/unit/test_native_gil_release.py` (`SITES` gains `"motion"`)
- Test: `tests/unit/test_native_motion_apply.py`, `tests/unit/test_native_motion_driver.py`, `tests/unit/test_native_motion_differential.py` (all new)

**Interfaces:**
- C++: `bool apply_motion_writes(PyObject* ships, std::span<const combat::MotionWrite> w);` It does what `_apply_writes_py` does, store for store: the same objects, value types, in-place identity and exceptions. The `TGPoint3` class is imported once from `engine.appc.math` and cached. False means a Python error is set.
- Binding: `combat_motion_step(ships: list, handles: list[int], player: int, dt: float, begin: int, resume_past_warp: bool) -> (stop, at, reason)`. It runs the compute released, as Task 4's, then `apply_motion_writes` under the GIL.
- Python (`native_motion.py`):
  - `configure(environ=os.environ) -> None`: `_switch = environ.get("DAUNTLESS_NATIVE_MOTION") != "0"`;
  - `enabled() -> bool`: `_switch` and the mirror is live (`native_combat._enabled`) and `get_store()` is a `NativeTransformStore` and the stock snapshot holds;
  - `reset() -> None`;
  - `step_all(dt: float) -> None`;
  - `counts() -> dict`: `native_calls`, `warp_rows`, `python_rows` by reason, `patched_stages`.
  - **The stock snapshot:** taken at import, it holds `ship_motion._step_ship_motion`, `_step_after_warp`, `_integrate_rotation`, `_effective_motion`, `_cap_keep`, `_ramp_toward`, `_asymptote_step`, `ship_motion.impulse_fractions`, `ship_motion.impulse_output_fraction`, `ship_motion.FALLBACK_MAX_ACCEL`, `ship_motion.BC_IMPULSE_TAU`, `drift.step`, `warp_state.is_arriving`, `subsystems._is_offline`, `ship_death._out_of_action`. If any differs at a step, the whole stage runs Python (`patched_stages += 1`).
- **`step_all`:**
  - build `ships = list(iter_non_rock_ships())` and `handles` (`__dict__.get("_nslot", -1)`);
  - read the player's handle from `App.Game_GetCurrentPlayer()` before **each** call;
  - loop on `combat_motion_step` from `begin`:
    - `WarpRow`: run `warp_flight.step(ship, dt)`. True resumes at `at + 1`; False resumes at `at` with `resume_past_warp=True`.
    - `PythonRow`: run `_step_after_warp(ship, dt)` if it was the resumed row, else `_step_ship_motion(ship, dt)`, then resume at `at + 1`.
  - record `combat_compute_take(5)` as `motion.kernel` under `gl.motion`.
- `tick_all_ship_motion(dt)`: `native_motion.step_all(dt)` when `native_motion.enabled()`, else today's loop, unchanged.

- [ ] **Step 1: Write the failing tests.**
  - `test_native_motion_apply.py`:
    - `test_c_apply_equals_the_reference`, on seeded write lists: every attribute's value and type match; `_current_angular_velocity` keeps its `id()`; `_velocity` is a new object; `_drift_velocity` absent stays absent;
    - `test_apply_pushes_nothing`: the dump before and after the apply alone is unchanged;
    - `test_apply_raise_applies_the_rest_then_raises_the_first`.
  - `test_native_motion_driver.py`:
    - `test_warp_row_sees_earlier_rows_moved_and_later_not` (a spy on `warp_flight.step` reads both neighbours' poses);
    - `test_warp_step_false_runs_the_row_natively_from_arriving`;
    - `test_subclass_row_runs_python` (Review Focus 1);
    - `test_patched_function_runs_the_stage_in_python` (patch `drift.step`; the patch is called);
    - `test_handler_deletes_a_later_ship_mid_stage` and `test_handler_changes_the_player_mid_stage` (Review Focus 3);
    - `test_switch_off_is_todays_loop`;
    - `test_switch_toggled_between_ticks_is_continuous` (Review Focus 5: the native, Python, native sequence equals all-Python by `.hex()`);
    - `test_audit_clean_with_native_motion` (`DAUNTLESS_NATIVE_AUDIT=1`, combat_stress, 120 ticks).
  - `test_native_motion_differential.py`, `test_native_equals_python_on_random_scripted_ships`: 40 seeds × 180 ticks, 10 asset-free ships (`ShipClass_Create` with an IES and 3 pods, as `test_impulse_degradation_motion._galaxy`, plus a bare ship) in one set. Random beats each tick: `SetSpeed` (both frames, negative, above max, one NaN), `SetTargetAngularVelocityDirect`, `CompleteStop`, `_speed_setpoint = None`, pod `SetCondition`, `SetDisabledPercentage`, IES `TurnOff`/`TurnOn`, `SetPowerPercentageWanted`, `SetStatic`, `SetStationary`, `SetVelocity`/`SetAngularVelocity` in both spaces, a pod's and the IES's `_radiation_out`, `SetDying`, and the current player moved between ships. Each seed runs fresh with the switch on, then off; the per-tick `golden_fight._pose_rows` + `motion_fight.motion_rows` are equal. The native arm has `counts()["python_rows"]` empty.
  - `test_golden_fights.py`: `test_motion_branches_python_motion_arm` calls `golden_fight.run_scene("motion_branches", "python_motion")` and `golden_fight.check("motion_branches", rows)`: both arms against the one Python recording.
  - The GIL guards: `RELEASED["combat_motion_step"]`, and `"motion"` in `test_native_gil_release.SITES`, so every motion compute call ran released.
- [ ] **Step 2:** Build; run the three new files. Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4:** Build; run the new files, both GIL files, and unchanged: every Task 2 Step 4 file plus `tests/unit/test_in_system_warp.py tests/unit/test_in_system_warp_parts_hold.py tests/unit/test_in_system_warp_preserves_speed.py tests/unit/test_warp_flight.py tests/unit/test_hot_path_imports_are_module_scope.py tests/integration/test_engines_disabled_decays_velocity.py tests/integration/test_e1m2_station_drift.py tests/integration/test_e1m1_dock_immobility.py tests/integration/test_in_system_warp_e2e.py tests/host/test_frame_rate_independence.py`. Expected: PASS.
- [ ] **Step 5: Goldens, the port's falsifier.** `uv run pytest tests/integration/test_golden_fights.py -v`. Expected: all PASS, unchanged, now with native motion (switch default on): `motion_branches` (both arms), `k1_gameloop_ai`, `sdk_dumb_fire` included. A change is BLOCKED; never re-record here.
- [ ] **Step 6: Commit:** `feat(motion): kernel M drives gl.motion (DAUNTLESS_NATIVE_MOTION, on unless =0)`.

### Task 6: The published-pose buffer

**Files:**
- Create: `native/src/combat/include/dauntless/combat/published_poses.h`, `native/src/combat/src/published_poses.cc`, `native/tests/combat/published_poses_test.cc`
- Modify: `native/src/host/host_bindings.cc`, `engine/appc/native_motion.py`, `engine/appc/ship_motion.py` (`tick_all_ship_motion` publishes last), CMake lists
- Test: `tests/unit/test_native_motion_publish.py` (new)

**Interfaces:**
- C++: `struct PublishedPose { int64_t object; double pos[3]; double rot[9]; double vel[3]; };` (15 doubles). `class PublishedPoses` has:
  - `void publish(const Mirror&, const TransformStore&, const std::vector<int64_t>& objects, int64_t tick);` which replaces the contents and skips -1, stale handles and invalid transforms;
  - `int64_t tick() const;`
  - `const PublishedPose* find(int64_t object) const;`
  - `std::span<const PublishedPose> all() const;`
  - `PublishedPoses& published_poses();` and `clear()`.
  
  The velocity is the mirror row's `_velocity`. Nothing reads the buffer in play until phases 3–4.
- Bindings: `combat_motion_publish(handles: list[int], tick: int) -> None` (GIL held: one short copy) and `combat_motion_published() -> (tick, [(h, pos3, rot9, vel3), ...])` (tests).
- Python: `native_motion.publish(handles) -> None`, a per-process `_tick` that increments once per stage. It runs at the end of `tick_all_ship_motion`, in both switch states, whenever the mirror is live. `reset()` clears the buffer.

- [ ] **Step 1: Write the failing tests:**
  - `test_buffer_equals_the_store_after_a_tick` (bit-exact with each motion row's store pose and `_velocity`);
  - `test_tick_tag_advances_once_per_tick`;
  - `test_a_later_teleport_does_not_change_the_buffer_until_the_next_stage`;
  - `test_ship_with_no_row_is_absent`;
  - `test_ship_spawned_mid_tick_appears_after_the_next_motion_stage`;
  - `test_published_with_the_switch_off_too`;
  - gtests `PublishedPoses.SkipsStaleAndNone`, `.ReplacesNotAppends`.
- [ ] **Step 2:** Build; run. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Build; run the new file, `ctest --test-dir build -R combat_PublishedPoses`, and `tests/unit/test_native_motion_driver.py tests/integration/test_golden_fights.py`. Expected: PASS, goldens unchanged.
- [ ] **Step 5: Commit:** `feat(motion): publish the tick's ship poses at the end of the motion stage`.

### Task 7: The tractor force moves into the motion stage (Mark, 2026-11-04)

**Decision, headless:** the motion-stage tractor runs wherever the motion stage runs, so **headless `GameLoop.tick` now moves tractored ships** (spec §8 Q5 no longer holds). That is the point: one motion stage, host and headless alike. What this changes in tests: a headless test that engages a tractor and ticks `GameLoop` now sees the target move; one that calls `host_loop._advance_combat` alone no longer moves it. `tractor.advance_tractors` itself is unchanged, so tests calling it directly (`test_tractor_effect.py`, `test_tractor_engage_intent.py`, `test_native_tractor.py`, `test_native_switch_default.py:245`) are untouched.

**Files:**
- Modify: `engine/appc/ship_motion.py` (new `tick_tractors(dt: float) -> None` = `tractor.advance_tractors(list(iter_ships()), dt)` under `_prof.scope("motion.tractors")`. Use the same `iter_ships()` roster the host's combat tick passes today (`host_loop._all_ships_for_tick`, :2575), rocks included. `tick_all_ship_motion` order: rows, `tick_tractors`, publish), `engine/host_loop.py` (`_advance_combat_step`: delete the `cb.tractors` block, its comment and its two `step_memo.forget()` lines, :1405-1415; update the `_advance_combat` docstring), `tests/helpers/golden_fight.py` (`_tractor_modes`: call `ship_motion.tick_tractors(TICK_DELTA)` where GameLoop's motion stage sits, after the timer bump and before `game_loop._update_ship_subsystems()`, never the full `tick_all_ship_motion`: that would start integrating the scene's ships, a second change), `tests/integration/test_tractor_effect.py` (`test_effect_runs_through_advance_combat` :215 becomes `test_effect_runs_through_the_motion_stage`), the spec (§5.2 tractor bullet, §6 table row, §8 Q1 answered, Q5 changed)
- Test: `tests/unit/test_tractor_in_motion_stage.py` (new)

**Interfaces:**
- Consumes: Task 6's publish (the tractor's moves are in the buffer).
- Produces: `ship_motion.tick_tractors(dt)`; the profiler row `cb.tractors` is gone, replaced by `motion.tractors` under `gl.motion`.

- [ ] **Step 1: Write the failing tests:**
  - `test_gameloop_tick_moves_a_tractored_ship_headless`;
  - `test_advance_combat_no_longer_moves_a_tractored_ship`;
  - `test_tractor_runs_after_every_motion_row_and_before_publish` (the order, by spies);
  - `test_published_buffer_holds_the_tractored_pose`;
  - `test_pull_starts_one_tick_after_the_k1_walk_engages` (the accepted shift, pinned);
  - and `test_effect_runs_through_the_motion_stage`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4:** Run the new file, `tests/integration/test_tractor_effect.py tests/integration/test_tractor_engage_intent.py tests/unit/test_native_tractor.py tests/unit/test_native_switch_default.py tests/unit/test_native_motion_publish.py tests/integration/test_warp_button_handler_sweep.py`. Expected: PASS.
- [ ] **Step 5: Goldens.** Run `tests/integration/test_golden_fights.py`. `tractor_modes` is expected to change. For it and any other scene that changes, confirm the first differing tick is at or after that scene's first tractor engage and the first differing row is a pose or tractor row. If not, STOP (BLOCKED). Then re-record each changed scene: `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="tractor force moved into the motion stage (Mark 2026-11-04)" uv run pytest tests/integration/test_golden_fights.py::test_<scene>`, and run the file again. Expected: PASS.
- [ ] **Step 6: Commit** the code, tests and spec: `feat(motion): the tractor force runs in the motion stage (Mark 2026-11-04)`. Then commit the re-recorded fixtures alone: `test(golden): re-record <scenes>: tractor force moved into the motion stage (Mark 2026-11-04)`.

### Task 8: Measure, record, ask for the live check (idle machine only)

- [ ] Rebuild (`cmake --build build -j`, no reconfigure). Run `docs/reference/engine/native-motion/phase0-runbook.md` §1's command twice (Debug, combat_stress, 64 ships, bridge view, 1,500 frames), then once more with `DAUNTLESS_NATIVE_MOTION=0` for the A/B. Score as runbook §1 (median of reports 3–11, ÷ printed ticks per frame).
- [ ] Rows: `gl.motion`, `motion.kernel`, `motion.tractors`, `gl.ai` (the new setpoint pushes land there: record it as a counter-signal), `sim.combat` (lost `cb.tractors`), `sim`.
- [ ] Record capture rows and one new signal (next free: SIG-186) in `docs/reference/engine/perf-register.md` against SIG-180, evidence tier *measured*. Never edit an old signal. The target is `gl.motion` ≈ 0.3 of 1.40 ms.
- [ ] Commit the register only: `docs(perf): phase 2 native motion measured`.
- [ ] Ask Mark for the live check (spec §7): a 64-ship fight, an E1M2 playthrough (Haven's drift, the rescaled rocks) and a tractor tow/hold. The Python copy is retired only after that check, in a later plan.

---

## Self-review notes

- **Spec §5.2 coverage:**
  - kernel inputs, outputs and branches: Tasks 2 and 4;
  - native impulse fractions and the radiation pin: Task 3;
  - bit-exact rules: Global Constraints and Task 4;
  - segments, python-owned not "skip": Tasks 4–5;
  - the write log applied in C: Tasks 4–5;
  - the new pushes, `_power_percentage_wanted` as `NativeFrozenField`: Task 2;
  - the tractor (now ruled): Task 7;
  - published poses: Task 6;
  - tests (`motion_branches` first, goldens unchanged, the differential, the existing motion tests unchanged): Tasks 1, 2, 5;
  - retiring the Python copy: after Task 8's live check, not here;
  - measurement: Task 8.
- **Deliberate shape choices:**
  - the kernel writes the mirror during compute and the C apply is quiet, rather than the apply pushing: the same contract as K0–K2's logs;
  - the in-place `_current_angular_velocity` writers push explicitly rather than becoming rebinds, so identity and `__dict__` readers (`collisions.py:315`, `host_loop.py:3167`) are untouched;
  - impulse fractions are their own task and translation unit because the differential against the fused walk is the cheapest place to pin them, before the kernel uses them;
  - `combat_motion_compute` (Task 4) stays as the test path beside `combat_motion_step` (Task 5), as `apply_writes` stays beside the C applier.
- **Behaviour changes:** only Task 7 (Mark's ruling), in its own re-record commit. GH #9 is out (header).
