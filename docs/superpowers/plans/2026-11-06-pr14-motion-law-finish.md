# PR #14 motion law — finishing work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the contributed motion law (PR #14, jmanyc, rebased onto local main) mergeable: no Python hand-back for turn goals, an honest `GetAccelerationTG` for every ship including the manually flown player, no per-row zero write-backs, the shuttle tests green on main's suite, goldens re-recorded.

**Architecture:** Kernel M (`native/src/combat/src/motion_step.cc`) stays a bit-exact port of the Python reference (`engine/appc/ship_motion.py` + `ShipClass._steer_turn_goal`). Acceleration becomes the motion law's own output (step / dt), written where the law runs, so it no longer needs a before/after finite difference. The turn goal's spec is mirrored so the kernel steers it natively; Python keeps the reference and the hand-back for anything the kernel cannot represent.

**Tech Stack:** Python 3.11 engine, C++20 combat kernels, pybind-free CPython glue in `native/src/host/`, pytest + gtest/ctest.

**Spec:** this plan stands on the PR #14 review findings (session of 2026-11-06) and the PR's own description (https://github.com/markward/bc_dauntless/pull/14). Mark's ruling 2026-11-06: **acceleration = controller output** (the law's step / dt), not dv/dt.

## Global Constraints

- Work ONLY in the worktree `.claude/worktrees/pr14-motion-law`, branch `contrib/pr14-motion-law`. Never touch the main checkout.
- ⛔ Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths. To mutate a file temporarily: `cp` to `/tmp`, mutate, `cp` back, `diff` to prove.
- ⛔ No full suites, no gate (`scripts/check_tests.sh`, `gate_merge.sh`, `gate_full.sh`), no whole-directory pytest. Run only the files each task names. Never pass pytest an empty file list.
- ⛔ Never launch the game (`./build/dauntless`), headless or not, without asking Mark.
- Build: `cmake --build build -j 6` in the worktree (Debug tree already configured). Never re-run cmake with a different `CMAKE_BUILD_TYPE`; never run cmake from `native/`.
- Kernel M must stay **bit-exact** with the Python reference: same operations in the same order. Python `x ** 0.5` is `std::pow(x, 0.5)`, not `std::sqrt`; `math.sqrt` is `std::sqrt`; `sum(gen)` starts from integer 0 (`0 + a` is `a`, except `-0.0` becomes `0.0`). TGPoint3 operations (`Cross`, `Dot`, `Unitize`, `Length`, `MultMatrixLeft`) must be ported from `engine/appc/math.py` exactly; reuse the kernel's existing ports where they exist.
- jmanyc's two commits (`3c8f559d3`, `147c04bae`) are never rewritten. All work is new commits on top.
- **Every commit on this branch** ends with BOTH trailers (Mark 2026-11-06: the contributor gets credit on all follow-up work):
  ```
  Co-authored-by: jmanyc <9269281+jmanyc@users.noreply.github.com>
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```
  Write messages to a file and use `git commit -F`.
- Game units: speeds `*_gups`, distances `*_gu`; never `*_m`.

## Review Focus

1. **A manually flown player under fire**: `GetAccelerationTG()` on the player while the keyboard turns or throttles must be the helm's law step / dt, not zero — and the kernel's passed-over player row must not overwrite it (Task 1 test `test_player_helm_records_controller_acceleration`).
2. **Warp drop-out / dash stop / scripted `SetVelocity`**: the tick after must report the law's acceleration (bounded by MaxAccel), never `Δv/dt` of the jump (Task 1 test `test_external_velocity_write_gives_no_spike`).
3. **An about-face goal** (target dead astern) and a goal **with a roll constraint** (`TurnTowardOrientation`): native steering must equal Python's on both, since they take the degenerate branches of `_turn_rotation` / `_frame_rotation` (Task 2 differential beats).
4. **A mod that patches `ShipClass._steer_turn_goal` or `_turn_rotation`**: the row must go back to Python, not be steered natively (Task 2 test `test_patched_steering_hands_back`).
5. **An AI tree that stops issuing commands mid-turn** (AI cleared, ship done): the stored goal keeps steering natively every tick with zero hand-backs (Task 2: `motion_branches` golden asserts `python_rows` has no `TurnGoal`).

---

### Task 1: Acceleration is the controller's output, mirrored, written only when it changes

**Files:**
- Modify: `engine/appc/ship_motion.py` (`step_vector_velocity`, `_step_ship_motion`, `_step_after_warp`, `step_and_record`; delete `velocity_before`, `_record_acceleration`)
- Modify: `engine/host_loop.py` (`_PlayerControl.apply` — no new code expected beyond what `step_vector_velocity` now does; verify)
- Modify: `engine/appc/ships.py` (declare `_acceleration` descriptor on `ShipClass`, init `None`)
- Modify: `engine/appc/objects.py` (`GetAccelerationTG` docstring: controller output)
- Modify: `engine/appc/native_combat.py` (new `AccelerationField`)
- Modify: `engine/appc/native_motion.py` (driver: drop `warp_before` re-recording; `_SURFACE` names)
- Modify: `native/src/combat/include/dauntless/combat/mirror.h`, `native/src/combat/src/mirror.cc` (Object field `_acceleration`, FloatList)
- Modify: `native/src/combat/src/motion_step.cc`, `.../motion_step.h` (accel from the law; skip when equal to mirror; delete the finite-difference `plan_row` wrapper)
- Test: `tests/unit/test_motion_acceleration.py` (create), `tests/unit/test_native_motion_kernel.py`, `tests/unit/test_native_motion_apply.py`, `tests/unit/test_native_motion_differential.py`, `tests/unit/test_native_motion_driver.py`, `tests/unit/test_physics_object_accel.py`, `native/tests/combat/motion_step_test.cc`

**Interfaces:**
- Produces: `step_vector_velocity(ship, forward, current_speed, target_speed, accel, dt, snap=False) -> (vx, vy, vz, speed)` (unchanged signature) now ALSO sets `ship._acceleration = ((vx - sx) / dt, (vy - sy) / dt, (vz - sz) / dt)` where `(sx, sy, sz)` is the vector it stepped FROM (after any re-seed); `(0.0, 0.0, 0.0)` when `dt <= 0`.
- Produces: `ShipClass._acceleration = native_combat.AccelerationField()` — `None` or a tuple of three floats; pushed as a FloatList (`[]` for None, the three values, `[0.0] * 4` unrepresentable → kernel takes the Python path).
- Produces: `ship_motion._no_thrust(ship) -> None` — sets `ship._acceleration = (0.0, 0.0, 0.0)`.
- Rule (Python reference AND kernel): every exit of `_step_ship_motion` that does not run `step_vector_velocity` calls `_no_thrust` — immobile, warp flight that returned True, arriving, no-setpoint drift, engines-out inertial drift — **except** the no-setpoint manually flown player (`ship is App.Game_GetCurrentPlayer()` with no setpoints), which writes nothing (its helm owns it).
- Kernel: `kAccel` is set only when the new acceleration differs bitwise from the mirror's `_acceleration` (or the mirror's is empty); the commit writes the mirror. `step_and_record` becomes a plain alias of `_step_ship_motion` kept for the driver (or callers switch to `_step_ship_motion`; pick one, update `_SURFACE` to match).

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_motion_acceleration.py` (build ships the way `tests/unit/test_native_motion_kernel.py` does):
  - `test_straight_line_acceleration_is_the_law_step`: Galaxy-like ship (MaxSpeed 6.3, MaxAccel 1.5) at rest, `SetImpulse(1.0)`, one tick of `ship_motion.tick_all_ship_motion(1/60)` → `GetAccelerationTG()` equals `forward × 1.5` to 1e-12 (the cap binds at the start).
  - `test_external_velocity_write_gives_no_spike`: ship cruising at full impulse for 5 s, then `ship._current_speed = 0.0` (a warp drop-out style direct write), one tick → `|GetAccelerationTG()| <= 1.5 + 1e-9`.
  - `test_drift_and_immobile_rows_report_zero`: an engines-out drifter and a `SetStatic(1)` ship after one tick → `(0, 0, 0)`.
  - `test_player_helm_records_controller_acceleration`: player ship flown by `_PlayerControl` (pattern: `tests/host/test_player_control_hardpoints.py`) with throttle 9 held one tick, then the motion stage run (`ship_motion.tick_all_ship_motion`, native ON) → player's `GetAccelerationTG()` is nonzero and equals the helm step / dt.
  - `test_zero_acceleration_rows_append_no_write`: kernel M on a scene of 3 drifting + 1 immobile ship, two ticks → second tick's `combat_motion_compute` log has no entry with `K_ACCEL` (and drift rows append no entry at all, as on main).
  - In `native/tests/combat/motion_step_test.cc`: `combat_MotionStep.AccelIsLawStepAndSkipsWhenUnchanged` — a cruising row at its target twice: first commit writes kAccel (zeros differ from empty mirror), second appends no kAccel.

- [ ] **Step 2: Run to verify they fail**
  Run: `cmake --build build -j 6 && uv run pytest tests/unit/test_motion_acceleration.py -v && ctest --test-dir build -R combat_MotionStep -V`
  Expected: the spike test FAILS (`|a|` ≈ v/dt), the player test FAILS (zero), the no-write test FAILS (K_ACCEL on every row).

- [ ] **Step 3: Implement** per the Interfaces block, Python reference first, then the kernel and both appliers (`_apply_writes_py`, `native/src/host/motion_write_apply.cc` — no order change, `kAccel` stays last). Delete `velocity_before`, `_record_acceleration`, the driver's `warp_before` and the C++ finite-difference wrapper; fix every caller. In `step_vector_velocity`'s docstring, state the re-seed contract in one paragraph: *the vector is trusted only while `current_speed` is bit-identical to `_motion_vel[3]`, the speed this function last returned; any writer that sets `_current_speed` directly (warp exit, drift re-seed, tests) makes them differ and the vector is re-seeded along the nose; a writer that must keep the vector (none today) must write both.* Mirror that paragraph as a comment at the kernel's re-seed.

- [ ] **Step 4: Run tests to verify they pass**
  Run: `cmake --build build -j 6 && uv run pytest tests/unit/test_motion_acceleration.py tests/unit/test_native_motion_kernel.py tests/unit/test_native_motion_apply.py tests/unit/test_native_motion_differential.py tests/unit/test_native_motion_driver.py tests/unit/test_physics_object_accel.py tests/host/test_player_control_hardpoints.py tests/integration/test_ai_intercept_smoke.py -v && ctest --test-dir build -R combat_ --output-on-failure`
  Expected: all PASS (update assertions in the existing files that pinned the finite-difference values; never weaken the bit-exact differential).

- [ ] **Step 5: Commit**
  `git add` the files above by path; message `fix(motion): acceleration is the law's output; the player's helm records it; no zero write-backs`.

---

### Task 2: Kernel M steers stored turn goals natively

**Files:**
- Modify: `engine/appc/native_combat.py` (new `TurnGoalField` replacing `PresenceField` for `ShipClass._turn_goal`)
- Modify: `engine/appc/ships.py` (`_turn_goal` declaration; nothing in the steering math changes — it stays the reference)
- Modify: `engine/appc/native_motion.py` (new store `_store_steer` in `_STORES`; `_SURFACE` adds the steering surface)
- Modify: `native/src/combat/include/dauntless/combat/mirror.h`, `native/src/combat/src/mirror.cc` (`_turn_goal` becomes a FloatList)
- Modify: `native/src/combat/src/motion_step.cc`, `.../motion_step.h` (steering; `kSteer = 128`; `MotionWrite::setpoint`)
- Modify: `native/src/host/motion_write_apply.cc`, `.../motion_write_apply.h` (store the steer write)
- Test: `tests/unit/test_native_motion_differential.py`, `tests/unit/test_native_motion_kernel.py`, `tests/unit/test_native_motion_apply.py`, `tests/unit/test_turn_goal_matches_original.py`, `native/tests/combat/motion_step_test.cc`

**Interfaces:**
- Consumes: Task 1's kernel layout (no finite-difference wrapper).
- Produces: `TurnGoalField` encoding of `ShipClass._turn_goal` (`[spec, owned_setpoint]` or None) as a FloatList: `[]` None; `[1, px, py, pz]` for `("loc", TGPoint3)`; `[2, pf(3), pt(3), 0]` for `("dirs", body_pf, pt, None, None)`; `[2, pf(3), pt(3), 1, sf(3), st(3)]` with a secondary; anything else `[0]` (unrepresentable → `TurnGoal` hand-back stays). Pushed on rebind only; `goal[1] = target` (in-place) never changes the spec and needs no push.
- Produces: `MotionWhat::kSteer = 128`; `MotionWrite::setpoint` (Vec3). Python store order becomes `drift_clear, drift_set, motion_vel, speed, velocity, steer, cav, accel` — the order `_step_after_warp` writes them. `_store_steer(ship, ...)`: `sp = TGPoint3(*setpoint)`; `d["_target_angular_velocity_setpoint"] = sp`; `d["_target_angular_velocity_fraction"] = None`; `d["_turn_goal"][1] = sp` (same object). `_apply_writes_py`'s entry tuple grows by one (setpoint), handled like the 6/8-tuple compatibility it has now.
- `_SURFACE` adds `(ShipClass, ("_steer_turn_goal", "_turn_goal_vectors", "_turn_rotation"))` and `(ships_module, ("_frame_rotation", "_to_body"))`, and `TGPoint3` `Cross`, `Dot` — so any patch sends the stage to Python.

- [ ] **Step 1: Write the failing tests**
  - `test_native_motion_differential.py`: extend the random beats with `TurnTowardOrientation(fwd, up)` (roll constraint), `TurnDirectionsToDirections` with and without secondaries, and a `TurnTowardLocation` point exactly astern (about-face); change `assert totals["turn_goal_rows"] > 0` to `== 0`; keep the 40 seeds × 180 ticks bit-exact comparison and add `_target_angular_velocity_setpoint` and `_turn_goal[1] is _target_angular_velocity_setpoint` to the compared state.
  - `test_native_motion_kernel.py::test_patched_steering_hands_back`: monkeypatch `ShipClass._steer_turn_goal` with a wrapper → the stage runs that row (and the rest) in Python and the wrapper is called.
  - `test_native_motion_kernel.py::test_unrepresentable_goal_hands_back`: `ship._turn_goal = [("loc", "not a point"), None]` → reason `TurnGoal`.
  - `motion_step_test.cc`: `combat_MotionStep.SteersLocGoalFromRest` — Galaxy-like row (MaxAngularAccel 0.12) with a loc goal 90° to starboard: the committed setpoint equals Python's value for the same inputs (hard-code it from a one-off Python run, commented with the command that produced it).

- [ ] **Step 2: Run to verify they fail**
  Run: `cmake --build build -j 6 && uv run pytest tests/unit/test_native_motion_differential.py tests/unit/test_native_motion_kernel.py -v && ctest --test-dir build -R combat_MotionStep -V`
  Expected: `turn_goal_rows == 0` FAILS (rows still handed back); the new C++ test FAILS (no steering).

- [ ] **Step 3: Implement** the native port of `_steer_turn_goal` → `_turn_goal_vectors` → `_turn_rotation` → `_frame_rotation` / `_to_body`, operation for operation (Global Constraints). Two ordering facts to honour: Python steers AFTER the linear step, so a "loc" goal reads the ship's position AFTER this tick's translate — confirm against what `GetWorldLocation()` returns at that point in Python (it may be the pre-translate world location if the world transform updates later; the differential decides) — and BEFORE the rotation integrates, so `R` is the pre-rotation matrix. `steering` = goal spec representable and `av_state == 1`; then the steered setpoint feeds the existing angular law with no `cap_keep` (as Python's `if not steering`). Unrepresentable spec → `to_python(TurnGoal)` as today.

- [ ] **Step 4: Run tests to verify they pass**
  Run: `cmake --build build -j 6 && uv run pytest tests/unit/test_native_motion_differential.py tests/unit/test_native_motion_kernel.py tests/unit/test_native_motion_apply.py tests/unit/test_native_motion_driver.py tests/unit/test_turn_goal_matches_original.py tests/unit/test_turn_directions.py tests/integration/test_maneuver_loop_smoke.py tests/integration/test_ai_intercept_smoke.py tests/unit/test_motion_acceleration.py -v && ctest --test-dir build -R combat_ --output-on-failure`
  Expected: all PASS, differential bit-exact with zero `TurnGoal` rows.

- [ ] **Step 5: Commit**; message `perf(motion): kernel M steers stored turn goals; no Python hand-back`.

---

### Task 3: Shuttle tests on main's suite

**Files:**
- Modify (only as the diagnosis requires): `engine/systems/shuttle_service.py` (choreography constants), `tests/unit/test_shuttle_service.py`

- [ ] **Step 1: Run and record the failures**
  Run: `uv run pytest tests/unit/test_shuttle_service.py -v`
  Record, for each failing test, the assertion and the measured value against its bound (e.g. `dmax` vs `far + BAND_SLACK_OUT`, `cross`, `any`, `bearing_accum - turned`).
- [ ] **Step 2: Fix the cause, not the bound.** The invariants are the shuttle service's promises and stay: no hits, `MIN_SEPARATION_GU`, cross-dock separation, two full turns before leaving, a held shuttle counts no turns. Prefer a choreography change in `shuttle_service.py` (circling speed / lead so the lagging course stays in its band; the hold coasting under the 1 s law) over moving a test bound. A bound may move only when the failure is the bound itself encoding the old scalar ramp (e.g. the "~0.05 rad" coast now taking longer under tau = 1 s) — say so in the commit message with the measured number. **STOP and report BLOCKED** if keeping an invariant needs a visible choreography change Mark has not seen (wider orbits, different band layout).
- [ ] **Step 3: Verify**
  Run: `uv run pytest tests/unit/test_shuttle_service.py tests/integration/test_tau_ceti_shuttles*.py -v` (whichever of the latter exist; skip the glob if none)
  Expected: all PASS.
- [ ] **Step 4: Commit** `fix(shuttles): <what changed> under the vector motion law`.

---

### Task 4: Goldens, motion-law reference doc, focused sweep

**Files:**
- Create: `docs/reference/engine/motion-law.md`
- Modify: `tests/integration/test_golden_fights.py` (assert no `TurnGoal` hand-backs in `motion_branches` and `k1_gameloop_ai`)
- Re-record: `tests/fixtures/golden_fights/*.darwin.json.gz` (whichever change)

- [ ] **Step 1: Add the hand-back assertion** to `_golden` (or the two scenes' tests): `assert native_motion.counts()["python_rows"].get("TurnGoal", 0) == 0`. Run `uv run pytest tests/integration/test_golden_fights.py -v` — expect golden mismatches (motion changed), not assertion errors about TurnGoal.
- [ ] **Step 2: Re-record**
  Run: `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="motion law (PR #14) + native turn goals + controller-output acceleration" uv run pytest tests/integration/test_golden_fights.py -v`, then the same WITHOUT the env vars → all PASS. List which goldens changed; any scene that changes but has no moving ship is a red flag — report it.
- [ ] **Step 3: Write `docs/reference/engine/motion-law.md`** (≤ 1 page): the linear and angular law (tau 1 s, MaxAccel cap, course lag), turn goals (stored, re-planned every tick, cubic plan, not capped at MaxAngularVelocity, about-face about own up), speed orders vs live max, reverse 2/9, acceleration = controller output (Mark 2026-11-06) and why (no spikes on external writes; issue #9's RE comment), the re-seed contract, and the **`ShipClass.GetAngularVelocityTG` / `GetAngularVelocity` overrides**: they now return the live controller rate (world / model space) instead of the never-written base field — list every caller in `engine/` and the SDK (`grep -rn "GetAngularVelocity" engine/ <sdk>/...`) and whether each wants the new value. Evidence tier per claim: measured (stbc-oracle, per the PR) vs designed. Credit jmanyc.
- [ ] **Step 4: Focused sweep** (one run, these files only):
  `uv run pytest tests/unit/test_native_motion_*.py tests/unit/test_motion_acceleration.py tests/unit/test_turn_goal_matches_original.py tests/unit/test_turn_directions.py tests/unit/test_physics_object_accel.py tests/unit/test_shuttle_service.py tests/unit/test_native_damage_clean_cache.py tests/unit/test_native_k2_scan_cache.py tests/host/test_player_control_hardpoints.py tests/integration/test_ai_intercept_smoke.py tests/integration/test_maneuver_loop_smoke.py tests/integration/test_golden_fights.py -v && ctest --test-dir build -R combat_ --output-on-failure`
  Expected: all PASS. (`test_native_damage_clean_cache.py` / `test_native_k2_scan_cache.py` were reported failing on 0.2.1 by the contributor — if they fail here, report whether they also fail on main's build, don't fix.)
- [ ] **Step 5: Commit** goldens + doc + test change; message `test(golden): re-record for the motion law; docs: motion-law reference`.

---

### After the tasks (Mark, not a subagent)

- Perf check, **only after asking Mark**: 64-ship `DAUNTLESS_MISSION=engine.dev_missions.combat_stress` profile, this branch vs main, reading `gl.motion` and the motion `python_rows` counts (perf-register B-baselines; Release vs Release).
- Mark's live check (turn feel, reverse, Intercept/torpedo runs, shuttles at Tau Ceti), then merge into main through the gate.
