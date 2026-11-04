# Native motion phase 3 (sim-pose hit tests, glow, native interpolation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo: one `tdd-engineer` subagent per task, in order, focused tests only, commit between tasks, stop on any BLOCKED (CLAUDE.md "Executing plans").

**Status:** APPROVED by Mark 2026-11-04 (decisions below). Refreshed 2026-11-04 against phase 2 as merged (`6fe9eaec4`). Every "Assumes from phase 2" item holds; corrections are inline. Line references were written against `87401fe33`: since then `host_loop.py` moved by about −5 after line 1405 and `host_bindings.cc` by +4 to +10, so find each site by name.

**Goal:** Take gameplay off the drawn pose (hit tests read the simulation pose), stop resending unchanged glow state every frame, and move render interpolation into C++, cutting `sim.render_xforms` from ≈ 1.9–2.0 ms a frame by ≈ 1.3–1.5 ms (64-ship Debug fight).

**Architecture:** 3a gives every ship's render instance a native *sim source* (transform-store slot, scale, view offset). Every gameplay point query (mesh trace, `instance_translation`, world→body, decals, hull damage, shield splash, surface points) composes the pose from the live store through one function, `hit_pose_of`, instead of the drawn `world_linear`/`world_translation_d`. Pick tools ask for the drawn pose explicitly. Articulated part overrides are pushed whenever the sim pose changes (per tick), not once per frame. 3b adds change guards to the glow controller, in Python. 3c ports `TransformBuffer` and its math to C++ (`dauntless::InterpBuffer`). It is fed by one frame-end capture from the live store, and it composes every non-player ship's drawn matrix in one native call. Python keeps the player's handover smoother, warp-hide visibility and `pose_of`.

**Tech Stack:** Python 3.11 (engine), C++20 (`native/src/transforms`, `native/src/scenegraph`, pybind11 in `native/src/host`), pytest, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md` §5.3 (phase 3), §3 ruling 3, §4 anti-goals, §6 kernel contracts, §7 testing. Maps: `docs/reference/engine/native-combat/k2-beams-map.md` §1.4, `posed-parts-map.md` (corrections block), `lock-map.md` §g_world.

### Assumes from phase 2 (refresh when phase 2 lands)

1. **P2-1** Motion kernel M is the only writer of ship poses inside a tick, and writes the **live** `TransformStore` slots that `ObjectClass._xform` (index, generation) names (spec §5.2). Phase 3 reads only the live store.
2. **P2-2** The tractor force step now runs inside the motion stage (Mark 2026-11-04), so by the time combat runs in a tick, the live store already holds the tractor's pull. Phase 3 does not call or move it.
3. **P2-3** The motion-end published buffer exists: 15 doubles per non-rock ship (sized to the roster), tagged with a per-publish counter (not the GameLoop tick), written at the end of the motion stage. **Phase 3 reads nothing from it.** 3a reads the live store (spec: "from the published buffer once phase 4 lands"), and `hit_pose_of` is the one place phase 4 switches. 3c's frame-end snapshot is its own per-instance capture (contradiction 7). If phase 2 names the buffer, only the comment on `hit_pose_of` cites it.
4. **P2-4** `TransformStore::Transform` (`pos[3]`, row-major `rot[9]`), `compose_world_linear_translation`, `TransformStore::valid/at` and the `_xform` handle shape are unchanged by phase 2.
5. **P2-5** Phase 2 does not touch `_sync_instance_transforms`, `TransformBuffer`, `advance_ticks`, `articulation.tick_ship` (still called per ship per tick from `loop.py:177`) or `native_combat.push_posed_parts`.
6. **P2-6** The manually flown player stays on `_PlayerControl` (spec non-goal), so its render instance stays store-bound (`_apply_live_world_transform`).
7. **P2-7** Phase 2 adds no per-frame pose writer. The per-frame writers 3c's frame-end capture must follow are still collisions, debris, dash, the hand-off rebase (spec §5.3 3c).

### Mark's decisions (2026-11-04)

1. **3a scope:** every gameplay point query moves to the sim pose (contradiction 3). Default taken.
2. **No A/B switches.** No `DAUNTLESS_HIT_POSE`, no `DAUNTLESS_NATIVE_INTERP`: each change replaces the old path outright. The Python `TransformBuffer`, `interpolate.py` and `HandoverSmoother` stay only as test oracles for the C++ twins. (The old Task 9, retiring the switches, is gone: Task 7 deletes the Python render path itself.)
3. **The player goes native too**, interpolated or live, including the handover smoother (overrides contradiction 6). The native buffer owns a per-instance handover blend, and one native function gives the drawn pose to both `pose_of` (the camera) and the compose (the renderer), so they cannot disagree.
4. **Glow tail:** snap below `1e-3`. Default taken.
5. **Measurement** (Task 8): cleared; run it when reached, on an idle machine.

### Where the code contradicts or goes past the spec

1. **The node overrides are not interpolated.** Spec §2.3 / §5.3 3a say "float32 `node_overrides`". They are the sim articulation (`ship._articulation_poses`, written per tick by `articulation.tick_ship`, `articulation.py:416`), pushed once per frame by `_sync_ship_articulation` (`host_loop.py:9935`, called from `_sync_instance_transforms` `:10156`). The trace only accepts that float32 map (`ray_trace.h:76-83`). So "sim articulation poses" means the same map written when the pose changes (Task 4), not a new table.
2. **3a cannot change a golden.** Every golden scene is headless (`golden_fight.py:21`; `posed_fight` with `r=None`, so no `ship_instances`). `resolve_hit_point` returns the fallback tier before any trace (`beam_trace.cc`, `if (!iid)`). So the falsifier is goldens **unchanged**, not re-recorded.
3. **Part attribution and hit anchoring are not traces.** `hit_feedback.py:481` → `host_io.world_to_body` → `part_severance.record_hit`. Decals, hull damage and the shield splash all invert the drawn `world_linear` (`host_bindings.cc:702-713`, `:3537-3543`, `:11231`). If only the trace moves, a sim-pose hit goes through a drawn-pose inverse and lands off the hull by the lag.
4. **Manual Aim already mixes poses.** It traces the drawn hull but takes the offset against the live pose (`manual_aim.py:192-197`, `combat._body_frame_delta`). 3a fixes this without touching `manual_aim.py`.
5. **`GetRandomPointOnModel` does not trace.** It reads `instance_surface_points`, which uses the render-space `in->world` plus the render origin (`host_bindings.cc:7056-7071`), so it needs its own switch.
6. **The player's handover smoother moves to C++ with it** (Mark's decision 3). It is drawn from `pose_of` with the Python handover smoother today (`host_loop.py:9898-9932`, `:12990-13011`). Natively, the player is a composed instance with a mode (live: the store pose; interpolated: the lerp) plus an optional handover blend that starts from the pose the compose last drew.
7. **Render does not read "published poses at tick ends".** That is spec §6's render row; §5.3 3c says the renderer reads a frame-end publish. The plan follows 3c. The snapshot is per **instance**, not per motion row, because it must also cover rocks (`rocks.motion`) and immobile stations.
8. **`set_current` runs at two sites today:** `host_loop.py:12970` (the interpolated player) and `:10214` (all others). Both run after every per-frame writer. The native capture runs once, at the first.
9. **The view offset moves from 3c into 3a.** Mesh queries speak VIEW coordinates (`host_io.py:361-366`, `frames.view_offset`). A store pose is set-local, so the per-set view offset must reach the native side in 3a, not 3c.
10. **Compose site (my call).** Interpolated matrices are composed by one native call at the end of `_sync_instance_transforms`, where they are pushed today, not inside `frame()`. Every Python reader between the sync and `frame()` then sees the same pose as today, and frozen frames keep their last matrix as today.

## Global Constraints

- **Worktree only.** Phase 3 runs on its own branch (Mark: one branch per phase), `ws/motion-phase3`, forked from `project/native-motion-and-proximity` after phase 2 has merged back. **Never commit to `main`.**
- **Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs. To mutate a file temporarily: `cp` to `/tmp`, mutate, `cp` back, `diff`.
- **Focused test files only:** `uv run pytest <file> [<file> ...] -q`, never an empty file list, never a directory, never `scripts/check_tests.sh` or a whole suite.
- **Build:** `cmake --build build -j` from the worktree root only. Never reconfigure, never run cmake inside `native/`.
- **No benchmarks** except Task 8, on an idle machine, with Mark's go-ahead. **Game launches (headless included) only with Mark's say-so.**
- **Goldens:** re-record only with `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="<why>"`, in their own commit. Phase 3 expects none (contradiction 2): a changed golden is a stop-and-report.
- **Anti-goal (spec §4):** gameplay never reads presentation state. After Task 3 no gameplay caller may pass `drawn=True`; only pick tools (`ray_trace_mesh_pick`, the SPV decals pane), `bridge_mesh_geometry` and the hull-discharge VFX do.
- **Visual changes need Mark's live look** (Task 8). Beam ends and Manual Aim picks move by at most the interpolation lag. Task 3 bounds this headless.
- **Pose rules (CLAUDE.md):** never rebuild a world position in Python from `GetWorldLocation/Rotation` for anything the renderer draws through `inst->world`. Attached lights keep resolving in `frame()` after the store sweep.

## Review Focus

1. **A frame that runs no tick after a per-frame writer** (collision bounce, dash step, hand-off). The ship must still be drawn where the writer left it this frame (capture without a roll moves only `cur`). Task 6: `test_capture_without_roll_moves_only_cur`.
2. **A ship in a sibling region of the viewed frame** (an in-space cutscene rendered at Ona2 while the player is in Ona1). The pushed view offset must equal what `combat._resolve_hit_point` shifts by, or every mesh trace misses. Task 3: `test_a_sibling_region_ship_gets_frames_view_offset`.
3. **A sim source whose object was collected** (stale handle). Queries fall back to the drawn pose and the capture skips the slot; a recycled slot is never read. Task 2: `test_a_stale_source_falls_back_to_the_drawn_pose`. Task 6: `test_capture_skips_a_stale_source`.
4. **A discontinuity: mission swap, `RecreatePlayer`, a dash hand-off.** No frame blends across it. Task 7: `test_reset_all_reseeds_without_smear`, `test_player_hand_off_snaps_native_slot`.
5. **A glow edge after a quiet stretch, or the dev forced-glow toggle.** Change guards must never swallow an edge or a forced state. Task 1: `test_disable_after_many_quiet_frames_pushes_the_edge`, `test_dev_forced_state_change_pushes`.

---

### Task 1: Glow and emissive scale pushed on change only (3b)

**Files:**
- Modify: `engine/appc/subsystem_glow.py` (`glow_state` :139: hoist the per-call `from engine import dev_light_preview` into a module-level lazy cache; `ShipGlowController.update` :455-510; new constant `IMPULSE_SETTLE_EPS = 1e-3`)
- Modify: `engine/host_loop.py` (`_sync_instance_transforms` :10159, the `set_emissive_scale` push; `MissionSession` fields beside `slot_bindings` :6707, new `emissive_scales: dict`)
- Test: `tests/unit/test_subsystem_glow_change_guard.py` (new); re-run `tests/unit/test_subsystem_glow.py tests/unit/test_subsystem_glow_any_subsystem.py tests/unit/test_warp_engine_glow.py tests/unit/test_refresh_ship_glow.py tests/unit/test_render_transform_binding.py`

**Interfaces:**
- Produces: each region dict gains `"pushed_dim": tuple | None` (the last `(dim, etime, flick)` sent) and `"pushed_gain": float | None`. `update()` keeps its signature.
- Produces: `MissionSession.emissive_scales: dict[iid, float]`, the last scale sent per instance.

- [ ] **Step 1: Write the failing tests** (reuse `_FakeRenderer`, `_Pod`, `_AIShip` from `tests/unit/test_subsystem_glow.py` by import):

```python
def test_healthy_region_dim_is_pushed_once(): ...
    # 10 updates, state unchanged -> len(rend.dim_calls) == 1, == (7, 0, 1.0, -1.0, 0.0)
def test_disable_after_many_quiet_frames_pushes_the_edge(): ...
    # 50 healthy updates, then disabled at now=20.0 -> dim_calls[-1] == (7, 0, 0.0, 20.0, 1.0), len == 2
def test_disabled_then_healthy_pushes_both_edges(): ...
def test_dev_forced_state_change_pushes(monkeypatch): ...
    # dev_light_preview.forced_glow_state -> "destroyed" between updates -> one new dim call
def test_idle_impulse_gain_is_pushed_once(): ...
    # setpoint 0: 10 updates -> len(gain_calls) == 1, gain == 1.0
def test_moving_impulse_gain_still_pulses_every_frame(): ...
    # setpoint 10, max 10: updates at now=0, 0.1, 0.2 -> 3 gain calls, values differ
def test_eased_throttle_settles_to_zero_and_stops_pushing(): ...
    # full throttle then setpoint 0; advance until eased < IMPULSE_SETTLE_EPS -> ctrl._eased_frac == 0.0
    # and the following 5 updates add no gain call
def test_emissive_scale_pushed_on_change_only(): ...
    # host_loop._sync_instance_transforms twice with a recording renderer -> one set_emissive_scale per iid;
    # the ship dying (IsDead/out of action) -> one more call with 0.0
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_subsystem_glow_change_guard.py -q`. Expected: FAIL (repeat pushes).
- [ ] **Step 3:** In `update`, send `set_glow_region_dim` only when `(dim, etime, flick)` differs from `reg["pushed_dim"]`, and `set_glow_region_gain` (boost) only when `gain` differs from `reg["pushed_gain"]`. The first update always pushes, because both start at None. Keep the warp-region rule as it is. After easing: when `target == 0.0` and `self._eased_frac < IMPULSE_SETTLE_EPS`, set `self._eased_frac = 0.0`. In `_sync_instance_transforms`, push `set_emissive_scale` only when the value differs from `session.emissive_scales.get(iid)`, then store it. Prune the keys alongside the glow-controller prune.
- [ ] **Step 4:** Run the new file and every file listed under Test. Expected: PASS. An existing test that counts calls per update is updated in this commit, with the reason.
- [ ] **Step 5: Commit** `engine/appc/subsystem_glow.py engine/host_loop.py tests/unit/test_subsystem_glow_change_guard.py` (plus any updated test): `perf(glow): push region dim, gain and emissive scale only on change (phase 3b)`.

### Task 2: Native sim source and one hit pose for every gameplay point query (3a, native half)

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (new fields after `xform_scale`; `World::create_instance` already resets the whole `Instance`, `world.cc:18`)
- Modify: `native/src/host/host_bindings.cc`:
  - new `hit_pose_of` beside `instance_translation_for_python` (:686);
  - switch `instance_translation_for_python` (:686), `push_shield_hit` (:702), `trace_instance_for_python` (:721), `to_body_frame` / `radius_to_model` (:3533-3543), `world_to_body` (:11217) and `instance_surface_points` (:7056) to it;
  - new bindings beside `set_instance_transform_slot` (:6483);
  - `drawn` kwargs on `instance_translation` (:6471), `ray_trace_mesh` (:10409), `world_to_body` and `instance_surface_points`.
- Modify: `engine/host_io.py` (`_REQUIRED_BINDINGS` :41; wrappers `ray_trace_mesh` :570, `world_to_body` :406; `ray_trace_mesh_pick` :602 and `bridge_mesh_geometry` :857 call `instance_translation(iid, drawn=True)`; new wrappers), `engine/renderer.py` (`instance_surface_points` :1411 gains `drawn=False`)
- Test: `tests/host/test_sim_pose_hit_tests.py` (new); re-run `tests/host/test_mesh_ray_trace.py tests/host/test_instance_transform_slots.py tests/host/test_hull_damage_bindings.py tests/host/test_native_beam_trace.py tests/unit/test_host_io_binding_manifest.py tests/unit/test_host_io_instance_relative.py`

**Interfaces:**
- Produces (C++, `instance.h`): `int sim_xform_index = -1; std::uint32_t sim_xform_generation = 0; double sim_scale = 1.0; glm::dvec3 sim_view_offset{0.0};`
- Produces (C++, host_bindings.cc file scope): `struct HitPose { glm::mat3 linear; glm::dvec3 translation; };` and `HitPose hit_pose_of(const scenegraph::Instance& inst, bool drawn);`. The rule: when `!drawn && inst.sim_xform_index >= 0` and the store slot is valid, `compose_world_linear_translation(store.at(i), inst.sim_scale, linear, translation)` then `translation += inst.sim_view_offset`. Otherwise `{inst.world_linear, inst.world_translation_d}`. The comment states that phase 4 switches its store read to the published buffer.
- Produces (bindings): `set_instance_sim_source(iid, index: int, generation: int, scale: float, view_offset: tuple[float, float, float]) -> None` (`index < 0` clears), plus `instance_translation(iid, drawn=False)`, `ray_trace_mesh(iid, origin, direction, max_dist, rest_pose=False, drawn=False)`, `world_to_body(iid, point, normal, drawn=False)` and `instance_surface_points(iid, drawn=False)`. `shield_hit`, `damage_decal_add`, `hull_damage_add` and `hull_damage_add_body`'s radius take no flag: they always use the sim pose, because their points are gameplay hit points.
- Produces (Python, `host_io`): `set_instance_sim_source(iid, index, generation, scale, view_offset) -> bool` (False headless or for a non-`InstanceId`, as `set_instance_transform_slot`), `ray_trace_mesh(..., rest_pose=False, drawn=False)`, `world_to_body(..., drawn=False)`. The new name goes in `_REQUIRED_BINDINGS`.
- K2/K3's `combat_trace_hooks()` (:758) need no change: they call the two switched functions with `drawn=false`.

- [ ] **Step 1: Write the failing tests** in `tests/host/test_sim_pose_hit_tests.py`. Use a model-0 instance for the pose tests and the Galaxy fixture pattern of `tests/host/test_mesh_ray_trace.py` (skip without BC assets) for traces. An `ObjectClass` supplies the store slot.

```python
def test_binding_present(): assert hasattr(_h, "set_instance_sim_source")
def test_translation_is_the_store_pose_plus_view_offset():
    # obj at (100, 50, -7); drawn pushed at identity; source (idx, gen, 2.0, (10, 0, 0))
    # instance_translation(iid) == (110.0, 50.0, -7.0); instance_translation(iid, drawn=True) == (0, 0, 0)
def test_without_a_source_every_query_reads_the_drawn_pose(): ...
def test_a_stale_source_falls_back_to_the_drawn_pose():
    # transform_free(idx, gen) -> instance_translation(iid) == drawn translation; no raise
def test_world_to_body_inverts_the_sim_pose():
    # asymmetric rotation (test_instance_transform_slots._asymmetric_rotation), scale 2 -> body == R^T (p - t) / 2 within 1e-5;
    # drawn=True inverts the pushed matrix instead
def test_ray_hits_the_sim_hull_not_the_drawn_one(galaxy):
    # store at origin, drawn at x=+2000: ray (0,0,-1000)->+z hits (via host_io.ray_trace_mesh);
    # ray (2000,0,-1000)->+z misses; the same ray with drawn=True hits
def test_hull_damage_and_decal_record_the_sim_body_point(galaxy):
    # hull_damage_add / damage_decal_add at a sim hull point -> _test_only_hull_damage_records / _test_only_damage_decals
    # body point == host_io.world_to_body(iid, p, n)[0] within 1e-4
def test_surface_points_follow_the_sim_pose(galaxy):
    # identity rotations: each instance_surface_points(iid)[k] == drawn point + (sim - drawn translation) within 1e-3
```

- [ ] **Step 2:** Run `cmake --build build -j`, then `uv run pytest tests/host/test_sim_pose_hit_tests.py -q`. Expected: FAIL (no binding).
- [ ] **Step 3:** Implement the interfaces above. `radius_to_model` reads the hit pose's linear column 0. Its length equals the drawn one, because scale is never interpolated. Keep `ray_trace_mesh_pick` (:10447) and `mesh_triangles_linear` on `world_linear`: they serve the bridge editor and the SPV, which pick what is drawn.
- [ ] **Step 4:** Rebuild and run the new file plus every file under Test. Expected: PASS. Without a sim source everything takes the drawn branch, so the existing files are unchanged.
- [ ] **Step 5: Commit** the five source files and the new test: `feat(host): hit pose from the transform store for gameplay point queries (phase 3a)`.

### Task 3: Ships feed their sim source; consumers checked on the sim pose (3a, Python half)

**Files:**
- Modify: `engine/host_loop.py`:
  - new `_mark_sim_source(session, ship, iid, model_scale)` beside `_mark_rigged` (:6849), called right after `_mark_rigged` at both realize sites (:7063, :8368);
  - `_sync_instance_transforms` (:10155-10219) pushes each ship's source on change (`MissionSession.sim_sources: dict`, pruned with the glow controllers);
  - the hull-discharge sample (:12795) passes `drawn=True`.
- Modify: `engine/ui/spv_decals_pane.py` (:619 fallback trace and :629 `world_to_body` pass `drawn=True`)
- Modify: `docs/reference/engine/native-combat/lock-map.md` (:278-280, :329: the trace hooks read the store plus the per-change node overrides, no longer the render sync)
- Test: `tests/unit/test_sim_source_push.py` (new), `tests/host/test_sim_pose_consumers.py` (new), `tests/host/test_native_beam_trace.py` (one new test); re-run `tests/unit/test_render_transform_binding.py tests/unit/test_manual_aim.py tests/unit/test_object_random_point_on_model.py tests/host/test_spv_decals_e2e.py tests/unit/test_combat_hit_resolution.py tests/integration/test_golden_fights.py`

**Interfaces:**
- Consumes: Task 2's `host_io.set_instance_sim_source` and the `drawn=` kwargs.
- Produces: `_push_sim_source(session, ship, iid, scale: float, view_offset: tuple | None) -> None`, guarded on `session.sim_sources.get(iid) == (index, gen, scale, off)`. `view_offset` is the same `_view_offset(ship)` value the drawn push uses today (`None` → `(0.0, 0.0, 0.0)`), and `scale` is `model_scale * GetScale()`. Task 7 reuses this helper.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_sim_source_push.py  (fakes as in test_render_transform_binding.py; stub host_io.set_instance_sim_source)
def test_every_ship_gets_its_slot_scale_and_view_offset(): ...
    # player + other, model_scale 2.0 -> calls == {(1, 7, 1, 2.0, (0,0,0)), (2, 7, 1, 2.0, (0,0,0))}
def test_sim_source_is_pushed_only_on_change(): ...      # second sync adds nothing; GetScale 1 -> 3 adds one call
def test_a_sibling_region_ship_gets_frames_view_offset(monkeypatch): ...
    # frames.viewing_set / offset_between patched: pushed offset == frames.view_offset(frames.containing_set(ship))
def test_both_realize_sites_mark_the_sim_source(): ...   # source parse: `_mark_sim_source(` follows `_mark_rigged(` in both
def test_spv_decal_pick_asks_for_the_drawn_pose(monkeypatch): ...  # recorded kwargs carry drawn=True

# tests/host/test_native_beam_trace.py
def test_trace_uses_the_sim_pose_when_a_source_is_set(scene): ...
    # drawn pose pushed 2000 GU off; source set: combat._resolve_hit_point and the native
    # combat_test_resolve_hit_point agree by float.hex() AND the point is within the hull radius of the SIM centre

# tests/host/test_sim_pose_consumers.py  (Galaxy fixture; skip without assets)
def test_manual_aim_pick_lands_on_the_sim_hull(): ...
    # doubles as test_manual_aim.py::test_update_stores_the_hull_hit_as_a_target_local_unscaled_offset, but no ray_trace=
    # (the real host_io path); drawn 2000 GU off -> stored offset == body point of the sim hit, |offset| < hull half-length
def test_random_point_on_model_lies_on_the_sim_hull(): ...
    # render_instances.register(obj, iid): 20 draws all within the model radius of the SIM centre
def test_sim_and_drawn_hits_differ_by_at_most_the_interpolation_lag(): ...
    # ship moving +x at 6.3 GU/s; drawn = TransformBuffer lerp(prev, cur, a) pushed via _world_matrix_from; source = cur;
    # broadside ray; for a in (0.0, 0.25, 0.5, 0.99): |p_sim - p_drawn| <= (1 - a) * 6.3 / 60 + 1e-3
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_sim_source_push.py tests/host/test_sim_pose_consumers.py tests/host/test_native_beam_trace.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the interfaces. In `_sync_instance_transforms`, call `_push_sim_source` for every ship, the player included, before the existing branches, reusing `_off` and `_ps`. The manual player's offset is None, so its source matches its store binding.
- [ ] **Step 4:** Run every file under Test. Expected: PASS, and `test_golden_fights.py` **unchanged** (contradiction 2). If a golden differs, stop and report BLOCKED with the diff.
- [ ] **Step 5: Commit** the source files, `lock-map.md` and the tests: `feat(combat): hit tests read the sim pose (phase 3a, ruling 3)`. The message states that beam ends and Manual Aim picks move by at most one tick's lag and that the goldens are unchanged.

### Task 4: Articulated part overrides pushed when the sim pose changes, not per frame (3a)

**Files:**
- Create: `engine/appc/pose_sink.py` (no imports from host or renderer)
- Modify: `engine/appc/articulation.py` (`_store_forced` :374 and the `if moved:` block of `tick_ship` :501-503 call `pose_sink.notify(ship)`)
- Modify: `engine/host_loop.py`:
  - `run()` setup installs the sink once: `pose_sink.set(lambda ship: _push_articulation(controller.session, ship))` (it reads the session at call time, so a mission swap needs no reset);
  - new `_push_articulation(session, ship) -> None`, which looks up `session.ship_instances.get(ship)` and calls `_sync_ship_articulation`;
  - `_mark_sim_source`'s realize call sites also call `_sync_ship_articulation` once;
  - remove the per-frame `_sync_ship_articulation` call from `_sync_instance_transforms` (:10156). `_sync_spv_articulation` stays.
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals`: `pose_sink.reset()`)
- Test: `tests/unit/test_articulation_render_push.py` (new); re-run `tests/unit/test_spv_anchor_pose.py tests/unit/test_articulation_fresh_part.py tests/ui/test_spv_part_nodes.py tests/unit/test_part_severance.py tests/unit/test_articulation.py tests/unit/test_render_transform_binding.py`

**Interfaces:**
- Produces: `pose_sink.set(fn: Callable[[object], None] | None) -> None`, `pose_sink.notify(ship) -> None` (a no-op when unset; an exception from the sink goes through `dev_mode.log_swallowed` and never raises into the tick), `pose_sink.reset() -> None`.

- [ ] **Step 1: Write the failing tests** (reuse `boxes` / `pushes` from `tests/unit/test_articulation_fresh_part.py`; a rigged double with `articulation.rig_for` / `state_for` monkeypatched for `tick_ship`):

```python
def test_tick_ship_pushes_a_moving_part_through_the_sink(): ...      # one tick mid-transition -> one node push
def test_a_settled_ship_ticks_without_a_push(): ...                  # after the transition ends, 5 ticks -> no new push
def test_force_part_pose_pushes_and_release_pushes_identity_once(): ...  # SPV name-posed part released -> identity pushed once
def test_a_severed_part_is_not_pushed(monkeypatch): ...              # part_severance.is_detached -> no push for it
def test_no_sink_is_a_no_op(): ...                                   # headless: tick_ship with sink unset raises nothing
def test_a_raising_sink_never_breaks_the_tick(): ...
def test_render_sync_no_longer_pushes_articulation(): ...
    # _sync_instance_transforms with a forced pose and no sink -> no set_instance_node_transform call
def test_realize_pushes_the_current_pose_once(): ...                 # source parse, or the realize helper with a recording stub
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_articulation_render_push.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. `_sync_ship_articulation`'s change guard (`session.ship_articulation`) is unchanged, so a notify that changes nothing pushes nothing.
- [ ] **Step 4:** Run every file under Test plus `tests/integration/test_golden_fights.py`. Expected: PASS, goldens unchanged. `test_spv_anchor_pose.py::test_the_articulation_sweep_runs_while_the_sim_is_FROZEN` must still find the unguarded SPV sweep.
- [ ] **Step 5: Commit** the four source files and the tests: `feat(articulation): node overrides follow the sim pose per change, not per frame (phase 3a)`.

### Task 5: `dauntless::InterpBuffer` and its Python twin (3c, pure C++)

**Files:**
- Create: `native/src/transforms/include/dauntless/interp_buffer.h`, `native/src/transforms/src/interp_buffer.cc` (compiled `-ffp-contract=off`, added to `set_source_files_properties` in `native/src/transforms/CMakeLists.txt`)
- Create: `native/tests/transforms/interp_buffer_test.cc` (added to `transform_store_tests` in `native/tests/transforms/CMakeLists.txt`)
- Modify: `native/src/host/host_bindings.cc` (test-only binding `_test_only_interp_lerp`)
- Test: `tests/host/test_native_interp_twin.py` (new)

**Interfaces:**
- Produces (C++):

```cpp
namespace dauntless {
using Pose = TransformStore::Transform;            // pos[3], row-major rot[9]
// interpolate.lerp_transform's twin: lerp_point, then nlerp_rotation (blend columns,
// forward primary, Gram-Schmidt up, right = forward x up, the same 1e-9 eps and
// fallbacks: endpoint column b then a, then the defaults, then _any_perpendicular).
Pose lerp_pose(const Pose& prev, const Pose& cur, double alpha);
class InterpBuffer {
public:
    using Key = std::uint64_t;                     // (index << 32) | generation
    bool has(Key k) const;
    void roll();                                   // prev = cur, every key
    void capture(Key k, const Pose& p);            // cur = p; prev = p for a new key
    void set_previous(Key k, const Pose& p);       // tracked keys only
    void snap(Key k, const Pose& p);               // prev = cur = p
    void erase(Key k);
    void clear();
    bool sample(Key k, double alpha, Pose& out) const;  // false for an unknown key
};
// HandoverSmoother's twin (engine/core/handover_smoother.py): blend from a
// frozen pose to the true one over kHandoverSeconds = 0.36, same weights.
struct HandoverBlend {
    bool active() const;
    void begin(const Pose& frozen);                // re-freezes when already active
    void advance(double dt);
    void cancel();
    Pose blend(const Pose& truth) const;           // truth itself when inactive
};
}
```

- Produces (bindings): `_test_only_interp_lerp(prev_pos, prev_rot9, cur_pos, cur_rot9, alpha) -> (pos3, rot9)` and `_test_only_handover_blend(frozen_pos, frozen_rot9, truth_pos, truth_rot9, elapsed) -> (pos3, rot9)`.

- [ ] **Step 1: Write the failing tests.** gtest: `InterpBuffer.NewKeySeedsPrevEqualCur`, `RollThenCaptureBlendsAcrossTheLastTick`, `CaptureWithoutRollMovesOnlyCur`, `SetPreviousIgnoresUntracked`, `SnapSetsBoth`, `EraseAndClear`, `SampleUnknownIsFalse`, `LerpPose.OrthonormalRightHanded` (det = +1 within 1e-12), `LerpPose.ZeroMatrixDoesNotCrash`, `LerpPose.DegenerateForwardFallsBackToEndpoint`, `LerpPose.ZeroUpColumnOnly`. These are the degenerate cases of `tests/unit/test_interpolate.py:88-106`. Python:

```python
def test_twin_matches_interpolate_on_random_poses(): ...
    # seeded random.Random(20261104), 2,000 (prev, cur, alpha) with rotations from MakeRotation:
    # every element |native - python| <= 1e-12
def test_twin_matches_every_degenerate_case(): ...   # the four test_interpolate.py degenerate inputs, element for element
def test_handover_twin_matches_the_python_smoother(): ...  # seeded poses, elapsed in (0, 0.09, 0.18, 0.36, 0.5): |native - python| <= 1e-12
```

- [ ] **Step 2:** Run `cmake --build build -j`. Expected: build fails or `ctest --test-dir build -R "InterpBuffer|LerpPose"` FAILS.
- [ ] **Step 3:** Implement. Read columns as `rot[r*3 + c]`, column c = body axis, as in `interpolate.py`'s `GetCol`.
- [ ] **Step 4:** Rebuild, then run `ctest --test-dir build -R "InterpBuffer|LerpPose"` and `uv run pytest tests/host/test_native_interp_twin.py tests/unit/test_interpolate.py tests/unit/test_handover_smoother.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** the six files: `feat(transforms): native render interpolation buffer (phase 3c)`.

### Task 6: Host interpolation bindings (3c, host half)

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (`bool interp_track = false; bool interp_compose = false;`), `native/src/scenegraph/src/world.cc` (`set_world_transform_d` clears `interp_compose`, as it clears `xform_index`; `set_transform_slot` with `index >= 0` clears it too)
- Modify: `native/src/host/host_bindings.cc` (`dauntless::InterpBuffer g_interp`; bindings beside `set_instance_transform_slot`; `destroy_instance` (:6400) erases the key; `shutdown`/`init` clear `g_interp`)
- Test: `tests/host/test_native_interp_bindings.py` (new); re-run `tests/host/test_instance_transform_slots.py tests/host/test_attached_lights_resolve_ordering.py tests/host/test_render_origin_bindings.py`

**Interfaces:**
- Consumes: Task 2's sim source (the slot, scale and view offset the capture and compose read), Task 5's `InterpBuffer`, `lerp_pose`.
- Produces (bindings, all no-ops on a stale iid):
  - `interp_track(iid, track: bool, compose: bool) -> None`. A newly tracked instance captures from its sim source at once, so prev = cur = live. `track=False` erases it.
  - `interp_roll() -> None`.
  - `interp_reseat() -> None`: `set_previous` from the live store for every tracked instance with a valid source.
  - `interp_capture() -> None`: the **frame-end publish**, `capture` from the live store for every tracked instance with a valid source; a stale source is skipped.
  - `interp_snap(iid) -> None`: snap to the live store.
  - `interp_reset_all() -> None`: `g_interp.clear()`. Tracked flags stay, and the next capture re-seeds.
  - `interp_set_live(iid, live: bool) -> None`: a live instance is drawn from its sim source's store pose instead of the lerp (the manually flown player).
  - `interp_handover_begin(iid) -> None` (freezes the pose the compose last drew for `iid`; no-op if it has none), `interp_handover_advance(dt) -> None`, `interp_handover_cancel() -> None`, `interp_handover_active() -> bool`. One blend, for one instance at a time (the player).
  - `interp_sample(iid, alpha)` returns the **drawn** pose: live or lerp, then the handover blend for the blended instance. Set-local, no scale, no view offset.
  - `interp_compose(alpha) -> None`: for every alive instance with `interp_compose`, the same drawn pose as `interp_sample` → `compose_world_linear_translation(pose, sim_scale)` → `+ sim_view_offset` → `World::set_world_transform_d`, then the compose flag is restored and the pose kept as that instance's last drawn pose. Compose reads only snapshots (and, for a live instance, the store), except a tracked instance with no snapshot yet, which seeds from the store first.

- [ ] **Step 1: Write the failing tests** (model-0 instances, `ObjectClass` slots, read back via `instance_translation(iid, drawn=True)` and `world_to_body(..., drawn=True)`):

```python
def test_compose_draws_the_lerp_with_scale_and_view_offset(): ...
    # capture at x=0, roll, move to x=6, capture; source scale 2, offset (10,0,0); interp_compose(0.25)
    # -> drawn translation == (11.5, 0, 0) within 1e-9; drawn linear == 2 * rotation within 1e-6
def test_capture_without_roll_moves_only_cur(): ...        # Review Focus 1
def test_reseat_puts_prev_one_tick_behind(): ...
def test_capture_skips_a_stale_source(): ...               # Review Focus 3: transform_free -> last snapshot kept, no raise
def test_track_only_is_never_composed(): ...               # pushed matrix survives interp_compose
def test_live_instance_draws_the_store_pose(): ...
def test_handover_blends_from_the_last_drawn_pose(): ...    # live -> interp flip: first composed frame == last drawn pose; after 0.36 s == the lerp
def test_handover_cancel_snaps_to_truth(): ...
def test_a_push_clears_compose(): ...                      # set_world_transform after tracking -> compose skips it
def test_binding_to_a_slot_clears_compose(): ...
def test_destroy_erases_the_snapshot(): ...                # recycled slot never inherits it
def test_reset_all_reseeds_on_next_capture(): ...
def test_sample_matches_compose_before_scale_and_offset(): ...
```

  Extend `tests/host/test_attached_lights_resolve_ordering.py` with `test_interp_compose_is_not_called_inside_frame`. Compose runs from Python before `frame()` (contradiction 10), so `frame()`'s xform_sync body must not contain `interp_compose`.
- [ ] **Step 2:** Run `cmake --build build -j`, then `uv run pytest tests/host/test_native_interp_bindings.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rebuild and run every file under Test. Expected: PASS.
- [ ] **Step 5: Commit** the four native files and the tests: `feat(host): native interpolation bindings and frame-end capture (phase 3c)`.

### Task 7: The host loop draws ships through native interpolation (3c, host loop)

**Files:**
- Create: `engine/core/native_transform_buffer.py`
- Modify: `engine/core/transform_buffer.py` (`advance_ticks` :66: when `buf` has `reseat_from_live`, call it in place of the `live_poses()` loop)
- Modify: `engine/host_loop.py`:
  - `run()` builds `NativeTransformBuffer()` (no switch; the Python `TransformBuffer` branch and `_interp_live_poses` are deleted);
  - the player capture site (≈ :12960-12968) becomes `track(player_iid, compose=True)` + `set_live(player_iid, not _interp_player)`, and the frame-end `capture()`;
  - `_drive_handover_smoother` calls `interp_handover_begin(player_iid)` on a flip; `_handover.advance` / `.cancel()` become `interp_handover_advance` / `interp_handover_cancel`; the Python `HandoverSmoother` instance is gone from `run()` (the module stays as the twin oracle);
  - `_rebase_player_render` calls `snap(iid)` and `interp_handover_cancel()`;
  - `_make_render_pose_provider` reads `xform_buf.sample(iid, alpha)` for every tracked ship, the player included (the blend is already in it), and falls back to the live pose only for an untracked object;
  - `_sync_instance_transforms`: every ship, the player included, gets `track(iid, compose=True)` (guarded in `session.interp_modes`); no per-ship `set_current` / `sample` / `set_world_transform` and no player store binding for drawing; then `host_io.interp_compose(interp_alpha)` after the loop, and `prune` untracks dropped iids.
- Modify: `engine/host_io.py` (wrappers for Task 6's bindings, in `_REQUIRED_BINDINGS`)
- Modify: `CLAUDE.md` ("Ship-attached dynamic lights" row: interpolated hulls are composed natively from the frame-end capture; a ⚠️ that gameplay point queries read `hit_pose_of`, pick tools pass `drawn=True`)
- Test: `tests/unit/test_native_interp_host_loop.py` (new), `tests/unit/test_transform_buffer.py` (two new tests); re-run `tests/unit/test_render_transform_binding.py tests/unit/test_interpolate.py tests/host/test_handover_continuity.py tests/unit/test_running_lights_host_push.py tests/host/test_scene_reconcile_ordering.py tests/host/test_frame_rate_independence.py tests/host/test_instance_transform_slots.py tests/unit/test_spv_anchor_pose.py`

**Interfaces:**
- Consumes: Task 6's bindings through `host_io`, Task 3's `_push_sim_source`.
- Produces: `class NativeTransformBuffer` with `has(iid) -> bool`, `roll()`, `reseat_from_live()`, `capture()`, `track(iid, compose: bool)`, `untrack(iid)`, `snap(iid, *_ignored)`, `reset_all()`, `prune(live_iids)`, and `sample(iid, alpha) -> tuple[TGPoint3, TGMatrix3] | None`. It keeps the Python-side set of tracked iids. `sample` has the same return shape as `TransformBuffer.sample`, so `_make_render_pose_provider` (:9903) is unchanged.
- No Python render path remains. Tests that drove `_sync_instance_transforms` with a Python `TransformBuffer` (`tests/unit/test_render_transform_binding.py`, `tests/host/test_handover_continuity.py`) are repointed to the native buffer (or a recording double of `NativeTransformBuffer`) in this commit.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_transform_buffer.py
def test_advance_ticks_reseats_from_live_once_on_multi_tick_frames(): ...  # fake buf: reseat_from_live called once, before the last tick
def test_advance_ticks_never_reseats_a_one_tick_frame(): ...

# tests/unit/test_native_interp_host_loop.py  (host_io interp_* and set_instance_sim_source stubbed, recorded in order)
def test_non_player_ships_are_tracked_and_composed_never_pushed(): ...  # r.pushed == []; track(2, compose=True) once over 3 frames
def test_compose_runs_once_after_the_ship_loop_with_this_frames_alpha(): ...
def test_player_is_composed_natively_in_both_modes(): ...   # r.pushed == []; set_live follows _player_render_interpolated
def test_pose_of_player_equals_the_composed_pose(): ...      # camera and hull agree, during a handover window too
def test_capture_runs_before_the_camera_pose_is_resolved(): ...           # source order in run(): capture( before _pose_of(
def test_player_hand_off_snaps_native_slot(): ...                         # Review Focus 4
def test_reset_all_reseeds_without_smear(): ...                           # _snap_scene / _on_player_change -> interp_reset_all
def test_drawn_motion_is_even_across_mixed_tick_frames_native(): ...
    # host test variant (skip without _dauntless_host): the native twin of test_transform_buffer.py:125 through the real bindings
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_native_interp_host_loop.py tests/unit/test_transform_buffer.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Keep the warp-hide `set_visible` calls, `_warp_hid_iids`, the scope-hidden AND, and `session.warp_hidden_iids` exactly where they are.
- [ ] **Step 4:** Run every file under Test. Expected: PASS.
- [ ] **Step 5: Commit** the source files, `CLAUDE.md` and the tests: `feat(render): ships drawn through native interpolation, frame-end capture (phase 3c)`.

### Task 8: Measure, record, live check (idle machine, Mark's go-ahead)

- [ ] Cleared by Mark (2026-11-04); idle machine. Run `docs/reference/engine/native-motion/phase0-runbook.md` §1's command twice on the phase tip. No switch, so it is judged against the latest signal, SIG-187 / C-295's `sim.render_xforms` 1.96 a frame, minding run-to-run drift.
- [ ] Record capture rows and one new signal in `docs/reference/engine/perf-register.md`: `sim.render_xforms` per frame for both conditions, plus `sim`, `sim.combat` and ticks per frame. Never edit an old signal. If `sim.render_xforms` stays above ≈ 0.6 ms a frame, note it, and add one cProfile run (runbook §4 method) only if Mark asks.
- [ ] Update the spec's §5.3 with a "Done" line (commit IDs, signal ID).
- [ ] Commit `docs/reference/engine/perf-register.md` and the spec: `docs(perf): phase 3 measured`.
- [ ] Ask Mark for the live look: a 64-ship fight, chase and tactical views, watching hull motion smoothness at < 60 fps, beam ends and impact sparks on hulls, and BoP wings shot while raised. Then a Felix torpedo run with Manual Aim on a moving target, and a helm handover both ways (manual → Intercept → take the conn back) on the chase camera. Record his verdict in the spec the same day.

---

## Self-review notes

- **Spec coverage, §5.3:**
  - 3a: Tasks 2–4, covering K2 traces and part attribution (Tasks 2–3), Manual Aim (Task 3), `GetRandomPointOnModel` (Tasks 2–3) and articulation per change (Task 4).
  - 3b: Task 1.
  - 3c: Tasks 5–7, covering TransformBuffer in C++ with the re-seat (Tasks 5–6), the frame-end publish (Task 6 `interp_capture`), native compose (Task 6), Python keeping the view offset, smoother, warp hide and `pose_of` (Task 7), tolerance twin plus pinned degenerate cases (Task 5), and the ordering guards (Tasks 6–7).
  - §7's render test list: run in Tasks 1, 3, 4 and 7.
  - Measurement and live checks: Task 8.
- **Deliberate departures**, each listed under "Where the code contradicts or goes past the spec": 3a covers every gameplay point query (3, 5); the goldens stay unchanged (2); the view offset moves to 3a (9); the player and its handover smoother go native (6, Mark's decision 3); compose runs at the sync site, not in `frame()` (10).
- **Types:**
  - `set_instance_sim_source(iid, index, generation, scale, view_offset)` and `hit_pose_of(inst, drawn)` are used the same way in Tasks 2, 3, 6 and 7.
  - `interp_*` names match between Task 6 (bindings) and Task 7 (wrappers and adapter).
  - `NativeTransformBuffer.sample` returns `TransformBuffer.sample`'s shape.
- **Threading seam (spec §6):** after Task 7 the renderer reads only the frame-end snapshot, and hit traces read only the store plus the per-change node overrides. Phase 4 switches `hit_pose_of`'s store read to the published buffer: one function.
