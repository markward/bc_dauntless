# Native motion and proximity — design (DRAFT)

**Status:** draft, 2026-11-03. Written from reading `project/combat_threading` (`2369cba41`) and the fire-control worktree (`ws/native-default`, read only), before that project merged. Nothing here has been built or measured on the new branch. Every number is SIG-178's (Debug, 64-ship fight, C-278/C-279 rows, C-280 cProfile shares) and is re-measured in phase 0.
**Branch:** `project/native-motion-and-proximity`, from local `main` **after** `project/combat_threading` has merged. Phase branches fork from it and merge back; it merges to `main` once, when Mark says so.
**Builds on:** `2026-11-01-threaded-weapons-combat-roadmap.md` (§6 overlap bounds, J parked), `2026-11-03-kernels-off-the-lock-design.md` (kernels compute without the GIL), `2026-11-03-fire-control-native-only-design.md` (golden fights M7/R9/R10, native tractor step R7), `docs/reference/engine/native-combat/` (mirror rows, transform store, lock map).

## 1. Why

At 64 ships the sim costs ≈ 9.37 ms per tick, and a slow frame runs ≈ 3 ticks, so every millisecond per tick is about three per frame. After native combat, the three biggest Python costs left outside AI's own decisions are:

| Row | Cost | Where it goes (C-280 shares) |
|---|---|---|
| `gl.ai` proximity and obstacle queries | ≈ 25% of 3.36 ms per tick | `GetNearObjects`/`_candidates` 14%, `proximity_table.location_is_stored` 6.6%; plus the SDK's per-result `NeedToAvoid` loop and its `IsTypeOf` calls |
| `gl.motion` | 1.39 ms per tick | `_integrate_rotation` 26%, `impulse_fractions` 26%, `SetVelocity` 8%, pose get/set ≈ 13% |
| `sim.render_xforms` | ≈ 1.8 ms per **frame** | `subsystem_glow.update` 46%, `transform_buffer.sample` 15% |

Mark's goal: move these to C++, then decide **with measurements** whether any sim work should move to worker threads. **Hard constraint (Mark):** the design must keep it possible to run the combat sim and ship motion on separate threads later, for much bigger battles. So each part is a kernel with explicit inputs and outputs, and proximity and combat read the poses motion published for the tick, never poses still being written.

## 2. What the mapping found

1. **Proximity queries return objects BC never returns.** Each AvoidObstacles query scans ≈ 337 candidates, 272 of which are ProximityChecks (one per `ConditionInRange`). BC's queries skip ProximityChecks by class (`stbc_reference/spec/ProximityManager.md` §1, §8.1, confidence *faithful*). Ours return them, and the SDK then discards each with `IsTypeOf(CT_PROXIMITY_CHECK)`. From the call counts (4.65 M `NeedToAvoid`, 7.11 M `IsTypeOf`, five types in `lDontAvoidTypes` with the check first), about 87% of the ≈ 88 objects each query returns are checks (**derived**). The `_candidates` docstring (`planet.py:319`) argues the opposite of the clean-room reading; ruling 1 settles it.
2. **Combat does not read its own tick's poses.** A frame runs all its GameLoop ticks (`advance_ticks`, `host_loop.py:12383`), then all its combat ticks (`for _tick_i in range(...)`, `host_loop.py:12645`). Every combat tick of a frame reads the poses left by the frame's **last** motion tick.
3. **Hit tests read on-screen poses.** K2's trace hooks, Manual Aim's `ray_trace_mesh` and `GetRandomPointOnModel` read `g_world`'s instance matrices and `node_overrides`: the interpolated, one-frame-old poses `_sync_instance_transforms` pushes (`host_bindings.cc:683-760`, `k2-beams-map.md:234`, `posed-parts-map.md:36`). So that sync is gameplay, and `lock-map.md:279` lists it as a race for any combat thread.
4. **Motion's normal path reads only its own ship and fires no events.** Only in-system warp (`warp_flight.step`) reads other objects and posts `ET_IN_SYSTEM_WARP` synchronously. Most impulse inputs are already NativeFields. Motion cost scales with moving ships: quiet 64-ship scene 0.07 ms (SIG-155/159) against 1.39 fighting.
5. **Glow is presentation only.** `subsystem_glow.update` resends every region's dim every frame with no change guard (`subsystem_glow.py:456-510`); nothing reads its output but the renderer.
6. **The tractor force step is native** (fire-control R7, `57767f45c`): `native/src/combat/include/dauntless/combat/tractor_force.h`, driven by `native_combat.tractor_force_step` from `tractor.advance_tractors`, in `cb.tractors` after K2. It has explicit inputs and outputs and writes the transform store itself. Python then applies what it hands back: HOLD's damped targets (`SetVelocity(0)`) and the captured engage geometry. It is a pose writer: it moves both the target and the source.

## 3. Mark's rulings (2026-11-03)

1. **Proximity queries drop ProximityChecks**, as BC does. Results are the same objects as today minus the checks, in the same order. The checks' own per-tick evaluation (`proximity_table`) is unchanged.
2. **Each tick runs whole:** AI, then motion, then combat, then the next tick. This replaces "all GameLoop ticks, then all combat ticks". A deliberate behaviour change on multi-tick frames: combat sees its own tick's poses and AI sees the previous tick's combat results one tick sooner. Golden fights are re-recorded once, in that change's own commit.
3. **Hit tests use the simulation pose**, not the drawn one: K2 beam traces and their part attribution, Manual Aim's pick, and death-blast surface points. Impact points move by at most the interpolation lag. Mark: "it will have to."
4. **Near queries align to BC's size rule** (agreed; done as its own step after the bit-exact port, §5.1 step 1d).
5. **Proximity queries keep reading live poses**, not the motion-end published copy. The published copy would miss every pose written later in the tick: the tractor, effect-queue handlers, the per-frame writers, and an SDK script that teleports a ship and then queries. The SDK also judges each result with a live `GetWorldLocation`, so one AvoidObstacles pass would mix two poses. While AI runs before motion on the same thread, the switch buys no threading seam. If phase 5 builds threads, all of Python's pose reads move to a snapshot together (J's snapshot). This narrows Mark's original constraint: proximity reads published poses only once a concurrent writer exists.

6. **An object that leaves a set also leaves that set's proximity manager list.** Quick Battle `UpdateObject`s every ship into the manager at spawn and nothing removes it (proximity-membership-map §2). So an evicted hulk (past `MAX_HULKS` = 8), a ship deleted at End Combat, or one that warped away is still returned at its last pose, where nothing exists. Hulks still in the set are unaffected: they are returned at their set slot, correctly. Own commit, after the identical-results port (plan Task 6).

Rulings 1, 3, 4 and 6 move toward BC; ruling 2 matches BC's measured tick order (Q2: AI first, then physics).

## 4. Goals, non-goals, anti-goals

**Goals**
- Proximity queries, ship motion and render transforms computed in C++, each as a kernel with declared input and output tables, no CPython inside its compute, and the GIL released around compute (the kernels-off-the-lock pattern).
- **One pose writer per stage, and published poses.** Motion is the only stage that writes ship poses during a tick; at its end the poses are published, and proximity, combat and hit tests read the published copy.
- Sim poses and on-screen poses kept apart: the renderer's interpolation is presentation only.
- A measured threading decision (phase 5).

**Non-goals**
- Threads in this project, unless phase 5's measurement passes its threshold.
- Moving SDK AI scripts (AvoidObstacles, NeedToAvoid) to C++: they stay Python and loop over our results.
- AI to C++ (roadmap L), J (AI ↔ combat pipelining), collisions to C++.
- The manually flown player's integrator (`_PlayerControl.apply`, a second Python copy, once per frame on wall dt): one ship, stays Python.
- Fixing motion's documented "known gap" (an AI-owned ship ignores a bare scripted `SetVelocity`; `ship_motion.py` docstring): the port keeps it.

**Anti-goals (a failure even if it works)**
- A bit-exact port silently changing behaviour. Every behaviour change is one of §3's rulings, in its own commit, with goldens re-recorded and the reason stated.
- A kernel that calls back into Python mid-compute, or reads a pose another stage is still writing.
- Gameplay depending on presentation state again (traces on render poses, glow read by anything but the renderer).

## 5. Phases

Savings are per tick unless marked, from SIG-178 rows × C-280 shares. cProfile inflates call-heavy Python, so they are ranges, and phase 0 replaces them.

| # | Phase | Expected saving | Threading seam it adds |
|---|---|---|---|
| 0 | Re-measure on main | — | the baseline phase 5 is judged on |
| 1 | Proximity | ≈ 1.0–1.5 of `gl.ai` 3.36 | queries read poses through one accessor |
| 2 | Motion kernel | ≈ 1.1 of 1.39 | motion is the only ship-pose writer; published poses |
| 3 | Sim-pose hit tests, glow, native interpolation | ≈ 1.3–1.5 ms per frame | render reads published poses only |
| 4 | Whole ticks | ≈ 0 | combat tick *i* reads motion tick *i*'s published poses |
| 5 | Threading decision | ≤ ≈ 0.9 at 64 ships | — |

### 5.0 Phase 0 — re-measure

- On main after the merge, native switch on by default: two runs of the C-278/C-279 command (`combat_stress`, 64 ships, bridge view, 1,500 frames, Debug, like for like), and one cProfile run as C-280.
- New rows, nested where they belong: `ai.avoid` (AvoidObstacles' `Update`), `prox.near`, `prox.line`, and later `motion.kernel`.
- One `DAUNTLESS_COMBAT_AVOID=0` run to isolate avoidance's share.
- A spike log (`DAUNTLESS_PROFILE_SPIKES`) to explain `sim.input`, which reads 1.1 ms per frame against ≈ 0.1 ms of its own code. A cyclic-GC pass landing in it is the leading guess (unverified).
- Record as new signals in `perf-register.md`; never edit SIG-178.

### 5.1 Phase 1 — proximity

Steps 1a–1c keep today's answers exactly apart from ruling 1. Step 1d is ruling 4's behaviour change.

**1a. Drop ProximityChecks from query results (ruling 1).**
- Both `GetNearObjects` and `GetLineIntersectObjects` skip `ProximityCheck` instances, whether they come from set membership or the manager's `AddObject` list.
- Expected effect on SDK consumers: none for AvoidObstacles, Intercept, the warp-obstacle grabs, ConditionInLineOfSight or the Helm collision alert, because each already discards checks or anything that is not a ship, planet or physics object. DockWithStarbase stops moving checks out of the docking zone, which BC never did.
- **Falsifier:** the golden fights are unchanged byte for byte, because `NeedToAvoid` returns 0 for a check before touching any state. If one changes, find out why before going on.
- Rewrite the `_candidates` docstring, which claims BC returns checks.

**1b. `IsTypeOf` in Python.**
- Hoist the per-call `from ... import` (`objects.py:157`; 2.2 s of `_handle_fromlist` in C-280) and cache `(type(obj), eType) → bool`.
- Invalidate the cache when `object_types`' registry changes (mods register classes at load).
- Same answers; a focused test pins them across the 34 `CT_*` types and a mod-registered class.

**1c. Cached candidates, one native radius call.** Revised after the membership map (`docs/reference/engine/native-motion/proximity-membership-map.md`) showed why a mirrored native table is the wrong shape:
- nothing maps a `py_id` back to an object;
- set order follows dict keys, with replace-in-slot and remove-by-name;
- the Set row holds ships and nebulae only;
- de-duplication depends on the radius at query time;
- mirror values exist only with the native switch on.

Instead:
- **A cache per manager.** Each `ProximityManager` caches its candidate list in today's order, plus per-entry flags (physics, stored, set twin) and a packed handle array of the stored entries.
- **Invalidation by a generation counter**, bumped at every membership mutation (the map's hook list) and at every sized-torpedo transition.
- **The radius test** is one new call, `near_indices`, on both transform-store backends. It returns the hit positions in ascending order, as indices into the Python-held list. So results come back as the same objects in the same order by construction, with no id mapping, and on both backends.
- **Participation** (`GetRadius() > 0` for non-physics entries) and the line query's reach are still read at query time.
- **A set holding a sized torpedo** runs today's Python path whole (torpedoes have no mirror row).
- **Poses** are read through the store, i.e. the live store (ruling 5).
- **Tests:** the existing order and semantics tests pass unchanged, plus a seeded differential against a verbatim copy of today's query (the oracle), by identity and order. Goldens unchanged.
- Task detail: `docs/superpowers/plans/2026-11-03-native-proximity-phase1.md`.

**1d. BC's size rule (ruling 4).**
- BC: the near query keeps an object when `distance(centre, position) − bounding radius ≤ query radius`. Ours tests centre distance only. The line query already adds the radius and keeps its math.
- **Resolve first, from the clean-room reference** (the stbc-reference server was down when this was drafted):
  - what the optional `includeSize` flag adds, beyond the coarse first pass (spec §8.1 calls it the object's "own size", a separate term from its bounding radius);
  - whether "bounding radius" includes `GetScale()` (E1M2's `SetScale(3)` rocks). Note that our base `ObjectClass.GetRadius` returns the unscaled `_radius`.
- Own commit: campaign sweep (26 missions, headless), goldens re-recorded, stub heatmap checked.
- Expected play effect: avoidance, the Helm collision alert and the docking clear-out see large objects (planets, starbases, scaled rocks) when their surface rather than their centre is in range.

### 5.2 Phase 2 — motion kernel

**Kernel M (one native call per tick, all motion rows):**
- **Inputs per row:**
  - transform handle;
  - flags: immobile (`IsStatic`/`IsStationary`), python-owned this tick, arriving (dewarp), manual player;
  - speed setpoint (speed, direction xyz, frame) or none;
  - angular setpoint xyz or none;
  - `_current_speed`, `_current_angular_velocity`, `_drift_velocity` (valid + xyz);
  - scripted `_velocity`, `_angular_velocity` and `_angular_space` for the drift branch;
  - the IES authored max speed, accel, angular velocity and angular accel;
  - the impulse inputs (below).
- **Outputs:** the store pose; the `_velocity` mirror; `_current_speed`, `_current_angular_velocity`, `_drift_velocity`. No events.
- **Branches, in today's order:**
  1. immobile → skip;
  2. python-owned → Python runs it (below);
  3. arriving → skip;
  4. no setpoints → `drift.step`, except the manual player;
  5. otherwise every pod out → inertial drift;
  6. otherwise powered ramp, then `_integrate_rotation`.
- **Impulse fractions natively** (`subsystems.impulse_fractions`, `:3705`):
  - online share of pods, and output = clamp(Σ condition% / n, 0, 1) × power wanted, or 0 when off;
  - read from the existing condition, max, disabled, destroyed, radiation, life/dying/dead, `_is_on` and `_children` mirrors and the property `MaxCondition` row;
  - add mirrors for `_power_percentage_wanted`, the ship→IES link, the four authored limits, the setpoints, `_current_*`, `_drift_velocity` and the static/stationary flags.
  - The fused walk skips a pod's own `_radiation_out` under `_ship_known_good`, while `impulse_online_fraction` tests it. Settled by reading (open-questions-by-reading Q1): no difference today, because radiation only picks top-level subsystems and pods are children. The port copies the fused walk. A test with a pod carrying `_radiation_out` pins the latent gap, since the player's integrator still uses the separate call (`host_loop.py:3400`).
- **Bit-exact with Python:**
  - `MultMatrix` as `0.0 + a·b + c·d + e·f`, k ascending (`test_matrix_multiply_exact.py`);
  - `MakeRotation`'s Rodrigues form;
  - `Unitize` with `sqrt` and the 1e-12 guard;
  - pitch·yaw·roll left-associative, post-multiplied;
  - the model-space direction from the pre-spin rotation;
  - `-ffp-contract=off`.
- **Python-owned rows (in-system warp):** today the walk handles a warp ship inline, so it sees earlier ships moved and later ones not. To stay bit-exact, the kernel **runs in segments**: rows up to a python-owned row, then Python's `warp_flight.step` for it, then the rest. Warp ships are rare in a fight, so this costs ≈ nothing. After phase 4 the segments can go, because warp flight then reads published poses (a ruling for then).
- **Python stays the authority; the kernel's outputs are written back in C** (decided after `docs/reference/engine/native-motion/motion-state-audit.md`).
  - The mirror assumes Python holds the real value: resync re-pushes from Python, and row drops and the switch fall back to it.
  - Many readers run after motion: next tick's AI `GetVelocityTG`, the hand-off, collisions, the UI.
  - Several read through `__dict__` (`collisions.py:310`, `host_loop.py:3167`, `ship_death.py:228`, `ai_inspector_model.py:489`), so storage cannot move behind a property.
  - So M computes with the GIL released into a write log. The log is then applied under the GIL by C code that sets the Python attributes and pushes the `_velocity` mirror, as K0/K1/K2's write logs are (weapon-state phase).
  - `_current_angular_velocity` keeps its TGPoint3 object and is updated **in place**. Its other in-place writers (`host_loop.py:3169-3171` manual flight, `:3278-3280` the AI hand-off seed) and `test_player_ai_motion_handoff.py:142` keep working.
  - Inputs that are not yet mirrored (setpoints, authored limits, flags) get pushes on write. `_power_percentage_wanted` is a FrozenField, so it becomes a `NativeFrozenField`.
  - Expected saving falls a little against a row-authoritative design, because the write-back costs about 64 × 4 attribute sets per tick in C. It stays well inside ≈ 1.1 ms.
- **Python-owned is not "skip natively".** While an in-system warp flight holds for its parts, `warp_flight.step` returns False and that row runs normal motion. So the segment boundary runs `warp_flight.step` in Python first, and then, only if it returned False, the row's native step.
- **Tractor (fire-control R7, built):** the native tractor force step runs after K2 in the combat step. This phase records it as a pose-writer stage the motion stage can own. Moving it into the motion stage shifts its pull by one tick relative to the K1 tractor walk; see open question 1.
- **Published poses:** at the end of the motion stage, copy each ship row's position, rotation and velocity into a native published buffer tagged with the tick number (64 × 15 doubles). Nothing reads it until phases 3 and 4.
- **Tests:**
  - **The goldens alone do not pin motion** (`docs/reference/engine/native-motion/golden-fights-for-motion.md`).
    - Only `k1_gameloop_ai` and `sdk_dumb_fire` run motion, covering the powered ramp and probably the every-pod-out drift.
    - Immobile, in-system warp, arriving, setpoint-less drift and fallback limits appear in no golden.
    - The recorder reads no `_current_speed`, angular velocity, `_drift_velocity` or setpoints.
    - So phase 2 starts by adding a `motion_branches` scene (sketched in that doc) and those fields to the recorder, recorded from Python **before** the port;
  - the existing goldens stay unchanged by the port;
  - a motion differential, native against Python on scripted ships covering every branch (drift, total loss, ramp caps, fallback limits, immobile, setpoint-less player);
  - the existing `tests/unit/test_ship_motion*.py`, `test_impulse_*` and `test_static_object_immobility.py` unchanged.
- **Retire the Python copy** after Mark's live check, as roadmap decision 1.

### 5.3 Phase 3 — sim-pose hit tests, glow, native interpolation

**3a. Hit tests on sim poses (ruling 3).**
- The trace hooks compose the ship's world matrix from the transform store, and from the published buffer once phase 4 lands, plus the **sim** articulation poses, instead of `g_world`'s instance matrix and float32 `node_overrides`.
- Applies to K2 beam traces and part attribution, Manual Aim's `ray_trace_mesh` and `GetRandomPointOnModel`.
- Articulated part poses go native per tick from `articulation.tick_ship`, not per frame from `_sync_ship_articulation`.
- Own commit, goldens re-recorded.

**3b. Glow on change only (Python).**
- Push a region's dim only when (state, edge, disable time) changed.
- Skip a boost region's gain when the eased fraction has settled at 0.
- No C++ unless phase 0's numbers show a remainder worth it: glow is presentation only and in the same per-frame scope.

**3c. Native interpolation.**
- Move `TransformBuffer` (prev/cur snapshots, `lerp_point`, `nlerp_rotation`) into C++, with the multi-tick re-seat kept.
- **What "cur" holds (my call):** a second, **frame-end publish** taken where `set_current` runs today, after every per-frame writer (collisions, debris, dash, the hand-off rebase, the tractor). The renderer reads only that snapshot, never the live store, so today's look is kept: tractor pulls and collision bounces are drawn the same frame, and a frame that runs no tick still draws them. The motion-end publish stays the one combat reads.
- `frame()` composes `inst->world` for every bound ship, as it already does for the manual player and planets (`sync_instance_transforms_from_store`).
- Python keeps the per-set view offset, the hand-off smoother, warp-hide visibility and `pose_of` for the camera; each becomes a value pushed to the native side rather than a pose.
- Because 3a took gameplay off these poses, the native nlerp only has to match visually: tolerance tests, plus the pinned degenerate cases.
- Ordering guards stay green: emitter lights resolve after the sweep (`test_attached_lights_resolve_ordering.py`), and running lights read the warp-hidden list.

### 5.4 Phase 4 — whole ticks (ruling 2)

- `advance_ticks` drives one complete tick at a time: GameLoop tick *i* (AI, motion, publish, subsystems), then combat tick *i*, then the combat tick boundary.
- The interpolation re-seat moves with it.
- **The per-frame stages that sit between the ticks and the combat ticks today (my call):** the mission-swap drain, `sim.session_sync` (Quick Battle's preload spawn, object deletions, player identity), `sim.input` (the manual player's integrator, fire keys, mouse, chords) and `manual_aim.update` move to **frame start, before tick 0**.
  - Fire presses and Manual Aim offsets still reach the same frame's first combat tick, as today.
  - The AI sees this frame's manual-player pose and firing state one stage sooner.
  - A swap requested during a tick is drained at the next frame's start, so the old mission finishes this frame's ticks, combat included.
  - Each of these is listed in the phase's commit as part of ruling 2.
- The combat kernels' pose accessor (`geometry_internal.h:49-58`) reads the published buffer. K3 keeps reading and writing live poses for its own torpedoes, which only combat moves.
- **Proximity queries stay on the live store (ruling 5).** `query_pose` keeps reading live poses, like every Python `GetWorldLocation`; it is the one place to switch if phase 5 builds threads.
- **Late pose writers:** collisions (still per frame, after the ticks) and SDK teleports from event handlers write the live store; the next motion stage starts from it and republishes.
- **Ship spawned mid-tick:** published at the end of its first motion stage. Until then, readers fall back to the live store (one rule in the accessor, tested).
- **Pinning the new order (my call).** The golden scenes drive ticks themselves and never go through `host_loop.run()`: `k1_gameloop_ai` already runs whole ticks, and `k1_ops_tpf6` copies today's batched order. So:
  - pull the frame's sim section out of `run()` into a callable, unchanged in behaviour (its own commit, before the reorder). About 25 tests parse `run()`'s source and must be repointed; the section reaches the renderer and GL, so a headless driver stubs the reconcile and the transform push (golden-fights-for-motion.md, `host_frames` sketch);
  - add a golden that drives that callable over multi-tick frames, recorded before the reorder;
  - rewrite the `tpf6` driver to whole ticks;
  - then reorder and re-record both in ruling 2's commit. That golden is the falsifier for any regression back to batching.
- Expected saving ≈ 0; this phase is what makes "combat reads the poses motion published for the tick" true.

### 5.5 Phase 5 — threading decision

- An overlap saves at most the smaller of the two jobs (roadmap §6). After phases 1–3 the native work per tick is ≈ 0.9 ms (combat compute 0.59 from SIG-177, motion ≈ 0.2, queries ≈ 0.1) against ≈ 5.5 ms of Python. That is the same bound that parked J.
- Splitting motion across cores saves under ≈ 0.2 ms: rows are independent, so it is easy, but small.
- **Measure:** `combat_stress` at 64, 128 and 256 ships (`DAUNTLESS_COMBAT_SHIPS`), recording the native stages against the Python stages per tick.
- **Threshold:** threads are built only if native stage time passes ≈ 2 ms per tick, or ≈ 25% of the tick, at a battle size Mark wants to support. Then the first candidate is motion rows across workers, and the second motion plus combat compute on a native thread beside Python. The second needs J's snapshot and outbox, and the unguarded push paths in the off-lock spec §10.

## 6. Kernel contracts (the threading seams)

| Stage | Reads | Writes | GIL during compute |
|---|---|---|---|
| AI (Python) | published poses (via queries), mirrors | setpoints, orders | held |
| Proximity query (native `near_indices`) | a packed handle array cached in Python, live poses (ruling 5) | ascending hit indices | released |
| Motion M (native) | motion rows, impulse mirrors, live poses of its own rows | live poses of its rows, velocity mirror, motion state; published buffer at the end | released |
| Tractor force (native, fire-control R7) | tractor state, masses, poses | poses of the target and the source | released |
| Combat K0–K4 (native) | published poses (phase 4), mirrors | weapon state, effect queue, damage | released (K4 held) |
| Hit traces (native) | published poses, sim part poses, `Model::trace_accel` | — | as caller |
| Render interpolation (native) | published poses at tick ends | `g_world` instance matrices | main thread, in `frame()` |

Rules:
- A stage reads only the tables in its row.
- No stage reads a pose another stage writes in the same tick, except motion reading its own rows.
- Every new push binding follows the off-lock pattern: queued when off the main thread, drained at session start and the tick boundary.

## 7. Testing

- **Focused files only during development** (CLAUDE.md "Test gate"): no whole-suite runs and no gate unless Mark asks.
- **Goldens:** goldens (fire-control M7, per platform R9, deterministic R10) are the bit-exact pin for every phase. Re-recorded only by a ruling's own commit, with the reason stated.
- **Proximity:**
  - order and semantics: `tests/unit/test_near_objects_batch_positions.py`, `test_proximity_skips_torpedoes.py`, `test_proximity_manager_iteration.py`, `test_proximity_manager_distance.py`, `test_planet.py`;
  - integration: `tests/integration/test_line_of_sight_and_warp_obstacles.py`, `test_dock_setup_clears_the_docking_zone.py`, `test_helm_collision_alert.py`, `test_pursuers_avoid_each_other.py`, `tests/unit/test_avoid_obstacles_sdk_cadence.py`;
  - plus a new checks-excluded test and the native-vs-Python query differential.
- **Motion:** `tests/unit/test_ship_motion*.py`, `test_impulse_fractions_fused.py`, `test_impulse_degradation_motion.py`, `test_motion_power_factor.py`, `test_static_object_immobility.py`, `test_dewarp_drive.py`, `test_player_ai_motion_handoff.py`, `tests/integration/test_engines_disabled_decays_velocity.py`, `tests/host/test_frame_rate_independence.py`, plus the new motion differential.
- **Render:** `tests/unit/test_transform_buffer.py`, `test_interpolate.py`, `test_render_transform_binding.py`, `tests/host/test_instance_transform_slots.py`, `test_attached_lights_resolve_ordering.py`, `test_handover_continuity.py`, `test_subsystem_glow*.py`.
- **Threading seams:** a guard per stage that its compute releases the GIL and makes no CPython call (as `test_native_k1_holds_gil.py`); a published-pose test that a mid-AI teleport is visible to combat in the same tick and a mid-combat one in the next.
- **Live checks by Mark:** after phases 1, 2 and 4, on a 64-ship fight and an E1M2/E6M2 playthrough (proximity, docking).

## 8. Open questions

1. **Tractor stage.** Under ruling 2, does the native tractor force (R7) stay in the combat stage, after K2 as built, or move into the motion stage? In the motion stage its pull starts one tick after the K1 tractor walk engages it. Decide when phase 2 starts; until then it stays as R7 builds it.
2. **BC size rule details** (§5.1 step 1d). Partly settled by reading (`docs/reference/engine/native-motion/open-questions-by-reading.md` Q3):
   - the near test is centre distance minus bounding radius, within the query radius;
   - for the near query, `includeSize` only widens the axis prune, so it should not change results (derived); for the line query it is part of the exact test;
   - BC's bounding radius is the world bound, **with scale**. Ours (`GetRadius`) is unscaled, so E1M2's `SetScale(3)` rocks would reach a fraction of their true size.
   - Still open: `≤` vs `<`; what "own size" is; result order (registration order inferred).
   - **Ruling needed from Mark before 1d:** scale the radius inside the proximity query only, or make `GetRadius` itself scaled as BC's is (wider than this project).
3. **Attached ProximityChecks sit at the set origin**, not their anchor: confirmed by reading (open-questions-by-reading Q2). `AttachObject` records the anchor only; BC parents the check's node. Firing is unaffected, because evaluation centres on the anchor. After ruling 1 nothing reads a check's own position, so it is left as is.
4. **`sim.input`'s missing ≈ 1 ms per frame** (phase 0).
5. **Headless runs never move tractored ships** (`GameLoop` does not run `cb.tractors`). Still true after the merge: only `host_loop._advance_combat_step` calls `advance_tractors`.
6. **Battle sizes to support** for phase 5's threshold (128? 256?), for Mark.
7. ~~Quick Battle ghosts~~: ruled, see ruling 6.
8. **Side findings from the motion audit** (inferred, not checked live):
   - a manually flown player's `_current_speed` is stale, so `GetImpulse` and `IsReverse` read it wrong;
   - after the SDK's `MissionLib.StopShip`, both integrators can drive the player at once.
