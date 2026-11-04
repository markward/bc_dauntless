# Native motion phase 4 (whole ticks) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo: one `tdd-engineer` subagent per task, in order, focused tests only, commit between tasks, stop on any BLOCKED (CLAUDE.md "Executing plans").

**Status:** APPROVED by Mark 2026-11-04 (as drafted, not the lean variant: the extracted `_run_frame_sim` is also phase 5's threading seam, and Mark leans towards threading). Refreshed the same day against phases 2-3 as merged (`887132c54`): corrections are inline under "Assumes from phases 2-3" and in Tasks 1, 3 and 4. Line references were written against `87401fe33` and have drifted by up to a few dozen lines in `host_loop.py`; find sites by name, and Task 1 Step 1's AST scan is the authority for the two field lists.

**Goal:** Each sim tick runs whole (AI, motion, combat, boundary) instead of all GameLoop ticks then all combat ticks, so combat tick *i* reads motion tick *i*'s published poses (ruling 2).

**Architecture:** First the frame's sim section moves out of `host_loop.run()` into `_run_frame_sim(ctx, ...)` unchanged, so a GL-free test can drive real host frames. Two goldens record that callable's batched order. Then one commit reorders it: the per-frame input and session stages move to frame start, `advance_ticks` drives a whole-tick closure, and the two goldens are re-recorded once. Last, the combat kernels' pose accessor reads the published buffer inside a per-tick read window and the live store everywhere else.

**Tech Stack:** Python 3.11 (engine, pytest), C++17 combat library + pybind11 bindings, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md` §5.4, §3 ruling 2 (and 5), §2 finding 2, §6, §7. Pre-work: `docs/reference/engine/native-motion/golden-fights-for-motion.md` (GFM) §4, §5.2; `motion-state-audit.md` §0.

### Assumes from phases 2-3

Names are from `docs/superpowers/plans/2026-11-04-native-motion-phase2.md` (draft, may change). No phase 3 plan existed when this was written.

1. **P2 Task 6:** `native/src/combat/{include/dauntless/combat,src}/published_poses.{h,cc}`, with `PublishedPoses::publish(const Mirror&, const TransformStore&, const std::vector<int64_t>& objects, int64_t tick)` (replaces the contents), `find(int64_t object)`, `tick()`, `all()`, `clear()`, and a `published_poses()` singleton. Bindings `combat_motion_publish(handles, tick)` and `combat_motion_published() -> (tick, [(h, pos3, rot9, vel3), ...])`. `engine/appc/native_motion.publish(handles)` runs at the end of `ship_motion.tick_all_ship_motion`, in both switch states, and `native_motion.reset()` clears the buffer.
2. **P2 Task 7:** the tractor force runs in the motion stage (`ship_motion.tick_tractors(dt)`, before the publish). `cb.tractors` is gone from `_advance_combat_step`. So **no code in the combat stage writes a ship pose.** Task 4's contract test depends on this.
3. **P2 Task 5:** `DAUNTLESS_NATIVE_MOTION` (on unless `=0`), and `GameLoop.__init__` calls `native_motion.configure()`. Python-owned rows (in-system warp) still run in segments. This phase does not remove the segments: that needs its own ruling (spec §5.2).
4. **P2 Task 1:** the `motion_branches` golden and `ARMS["python_motion"]` exist, and `golden_fight.SCHEMA` is still 3.
5. **P3 3a (as built):** every gameplay point query reads the sim pose through ONE native reader, `hit_pose_of(inst, drawn)` in `native/src/host/host_bindings.cc`, from the instance's sim source (`Instance::sim_xform_index/sim_xform_generation/sim_scale/sim_view_offset`). It is separate from `detail::xform`, so Task 4 gives it the same `pose_for(index, gen)`-then-store rule. Articulated node overrides are pushed from inside the sim tick (`engine/appc/pose_sink.py`), not per frame. 3a changed no golden.
6. **P3 3c (as built):** the buffer is `engine/core/native_transform_buffer.NativeTransformBuffer` (no Python render path, no `HandoverSmoother` instance, no `_interp_live_poses`). `advance_ticks(buf, n, tick, live_poses=None)` keeps its "re-seat prev before the last tick" contract through `buf.reseat_from_live()`. The renderer's frame-end capture (`_xform_buf.capture()`) and the native handover run in `sim.render_xforms`; this phase leaves them alone.
7. **P3** moved nothing outside `sim.render_xforms` (checked). Inside it, the carried state changed: `_handover` and `_interp_live_poses` are gone, `_prev_interp_player`, `_prev_player_set`, `_prev_view_set` and `_prev_drawn_player_pose` remain. Task 1's field lists change accordingly.

### Where the code and the spec disagree

1. Spec §6's AI row says AI reads "published poses (via queries)". Ruling 5 and §5.4 say queries stay on the live store. **This plan follows ruling 5.**
2. Spec §6 says combat K0-K4 read published poses. But K1 also runs outside the combat step: from the SDK's `CanFire`/`Fire`/`FireDumb` during `gl.ai` (fire control is native only), before the tick's publish, and from the fire keys at frame start. **Plan:** a read window that opens at the publish and closes when `_advance_combat` returns. Outside it, every kernel reads live (Task 4).
3. Spec §5.4 names four stages between the ticks and combat (swap drain, `sim.session_sync`, `sim.input`, Manual Aim). Two more sit there: `warp.preload` (`host_loop.py:12389-12391`) and `sim.keys` (`:12481-12518`). **Plan:** `sim.keys` moves to frame start, because it sits between `sim.session_sync` and `sim.input`. `warp.preload` stays after the ticks.
4. Spec §2 finding 2's line references are stale: `:12383` is now `:12386` (`advance_ticks`) and `:12645` is now `:12648` (the combat loop). GFM's references are `project/combat_threading`'s, and its `tests/integration/test_native_k1_differential.py` is now `tests/helpers/k1_fight.py`.
5. Spec §5.4 says "`k1_gameloop_ai` already runs whole ticks". The order is right, but its `GameLoop()` keeps `owns_boundary=True` (`tests/helpers/k1_fight.py:770`), so its GameLoop boundary runs before combat (`engine/core/loop.py:131-136`). The host uses `False` (`host_loop.py:11744`). `host_frames` uses the host's `False`.
6. Spec §8 Q1 and the §6 tractor row still say the tractor is undecided and sits in the combat stage. Phase 2 Task 7 settles that (Mark 2026-11-04) and edits the spec.
7. `_sync_player_identity`'s docstring (`host_loop.py:7412-7422`) says the pre-sim sync makes "weapons, combat ... drive the new ship". After the reorder, combat runs inside the ticks with the frame-start `player`. Combat uses `player` only for the render push (`_advance_combat_step` → `_push_combat_render_data`, and the host passes `push_render_data=False`), so this is harmless. Task 3 updates the docstring.

### Mark's decisions (2026-11-04)

1. **As drafted**: extract the sim section first, then record `host_frames` before the reorder (not the lean in-place variant).
2. **Deletions mid-frame:** frame start only, as the spec says (default; Review Focus 3 pins it).
3. **Nebula and radiation loop:** stays batched after all ticks (default).
4. **Live check (Task 5):** a 64-ship fight; E1M2 and E6M2; Quick Battle End Combat and respawn; a dev mission swap mid-fight; Manual Aim on a moving target; a manual dogfight with the fire keys at below 60 fps; a tractor tow and HOLD (default list plus the tractor, see Behaviour shift 14).
5. **Measurement (Task 5):** the machine is free for benchmarking until Mark says otherwise.

## Global Constraints

- **Branch:** `ws/motion-phase4`, cut from `project/native-motion-and-proximity` after phases 2 and 3 have merged into it (Mark: one branch per phase). Work in a worktree. **Never commit to `main`.**
- **Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs. To mutate a file temporarily: `cp` it to `/tmp`, mutate, `cp` it back, then `diff`.
- **Focused test files only**, never an empty file list and never a directory. Never whole suites, never `scripts/check_tests.sh`.
- **Build:** `cmake --build build -j` from the worktree root only. Never reconfigure, never run cmake inside `native/`.
- **No benchmarks** except Task 5 (cleared).
- **No game launches** without Mark's say-so, headless runs of `./build/dauntless` included. The `tests/host` files that run `hl.run()` under a hidden window are tests, not launches.
- **Goldens:** re-record only with `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="<why>"`, in a commit of their own whose message names the behaviour change and the scenes. Ruling 2 allows **ONE** re-record: `host_frames` and `k1_ops_tpf6`, together, in Task 3. Any other golden that changes in any task is a bug: STOP and report BLOCKED with the first differing tick, row and field. Recordings exist for darwin only (R9).
- **Ruling 2 is a gameplay-timing change.** Every shift in the "Behaviour shifts" table goes into Task 3's commit message and into `docs/reference/engine/perf-cadences-and-latency.md`, each with the test that pins it, or marked for Mark's live check.

## Review Focus

1. **A mission swap requested during a tick** (dev picker, `swap_mission`). The old mission finishes the frame's whole ticks, combat included, and the swap drains at the next frame's start, before tick 0. No frame may mix old-mission AI with new-mission combat, as today's frames can. Test in Task 3.
2. **A RecreatePlayer inside a tick** (an SDK timer). The post-tick pass that frame (`sensor_contacts`, crew prompts, `dash.tick`, `handoff.tick`) must see the new player, as it does today. That is why Task 3 adds a second identity sync after the ticks. Test in Task 3.
3. **A ship flagged for deletion mid-frame** stays in its set until the next frame starts (decision 2). Pinned in Task 3, so a ruling either way changes one test.
4. **A teleport, then a K1 call, both in the tick's effect delivery** (the scope's exit, after `_advance_combat`). The K1 call reads the live pose, never the published one, because the window has already closed. Test in Task 4.
5. **A fire press on a zero-tick frame** (high refresh rate). No combat runs that frame. The press must reach the next frame's first combat tick and must not be lost. Test in Task 3.

## Behaviour shifts (ruling 2), for Task 3's commit and docs

| # | What changes | Before | After | Pinned by |
|---|---|---|---|---|
| 1 | Poses combat reads on a multi-tick frame | every combat tick saw the poses after the frame's last motion tick | combat tick *i* sees motion tick *i* | `host_frames` golden |
| 2 | Combat results the AI sees | all of the frame's AI ticks ran before any of its combat | AI tick *i+1* sees combat tick *i*'s hits, deaths and events | `host_frames` |
| 3 | GameLoop effect delivery (`owns_boundary=False`) | every GameLoop tick's held effects landed at combat boundary 1 | GameLoop tick *i*'s effects land at combat boundary *i* | `host_frames` |
| 4 | Fire keys, mouse fire, chords, raw keys, skip-dialogue | after the frame's GameLoop ticks | before tick 0; still before the first combat tick, and this frame's AI sees the firing state | `test_fire_press_reaches_the_frames_first_combat_tick`; live |
| 5 | Manual Aim pick | after this frame's motion, with last frame's camera | at frame start: last frame's target pose and last frame's camera now agree | live (moving target) |
| 6 | Manual player integrator `_apply_input`, and the manual→AI seed | after the frame's AI ticks | before them: AI, proximity and combat all see this frame's manual pose, and a UI helm order is seeded before the first AI tick | `test_frame_start_stages_run_before_tick_0`; live |
| 7 | Mission-swap drain | after the GameLoop ticks, before combat | frame start; a mid-tick request drains next frame | Review Focus 1 test |
| 8 | Quick Battle preload-done spawn | after the ticks: AI saw the new ships next frame | frame start: AI sees them this frame | `test_frame_start_stages_run_before_tick_0` |
| 9 | `_process_object_deletions` | before the frame's combat | frame start only (decision 2) | Review Focus 3 test |
| 10 | Ship list per combat tick | tick 0's list was built after all GameLoop ticks | built after GameLoop tick *i* | `test_ship_spawned_in_tick_2_reaches_combat_tick_2_only` |
| 11 | A frame frozen by `sim.keys` (a dev key) | GameLoop ticks ran, combat did not | the frame's whole ticks run (*n* is decided at frame top) | `test_frame_frozen_mid_frame_still_runs_its_whole_ticks` |
| 12 | Interpolation re-seat | prev = pose before the last GameLoop tick | prev = pose after whole tick *n−1* | `test_reseat_runs_after_the_penultimate_boundary` |
| 14 | Tractor pull, HOLD and release latency | one FRAME after the K1 grip (phase 2 moved the force into the motion stage, and the frame ran all motion ticks before any combat) | one TICK, as Mark ruled | `tractor_modes` golden (unchanged: headless, one tick a frame); live |
| 13 | Unchanged | — | collisions, debris, dash, hand-off, the frame-end boundary, nebula and radiation (decision 3), the cadences in perf-cadences-and-latency.md (game time and tick counts are unchanged) | existing tests |

---

### Task 1: Extract the frame's sim section into `_run_frame_sim` (behaviour unchanged)

**Files:**
- Modify: `engine/host_loop.py`. The section runs from `frame_profiler.mark("sim")` (`:12334`) through the end of the frozen branch's reconcile (`:13036`, just before the `sim.spv_sync` comment). The new code goes at module level, above `run()`.
- Create: `tests/helpers/host_frame_source.py`, `tests/unit/test_host_frame_source.py`, `tests/helpers/host_frame_fight.py`, `tests/integration/test_host_frame_sim.py`
- Modify (repoint `inspect.getsource(host_loop.run)` / `hl.run` → `host_frame_source.run_source()`; AST users → `host_frame_source.run_tree()`): `tests/cameras/test_speed_fov.py`, `tests/host/{test_boot_notice_pump,test_camera_dt_wiring,test_contacts_pump,test_dash_render_continuity,test_host_loop_first_run (:398 only; :345/:375 read _run_preboot_panel),test_letterbox_pump,test_render_space_feeds,test_scene_reconcile_ordering,test_view_set_rebase,test_viewscreen_bars_game_loop_call,test_warp_state_host_wiring,test_frame_rate_independence (structural guard :159-161)}.py`, `tests/integration/test_damage_queue_order.py`, `tests/unit/{test_effect_queue,test_far_host_wiring,test_foundation_sounddef,test_minor_contact,test_minor_rocks_mission_swap,test_native_deferred_frees,test_paths_resolve,test_running_lights_host_push,test_spv_anchor_pose,test_spv_part_box_overlay,test_warp_preload_host}.py` (25 files)

**Interfaces:**
- Produces, in `host_loop`:
  - `@dataclass class FrameSimContext`. Fixed fields: `h, controller, director, view_mode, player_control, pause, input_map, xform_buf, tick_gameloop, snap_scene, close_star_map, consume_scroll, cef_send_wheel, crew_menu_panel, perf_monitor_panel, collisions, verbose, tick_dt, max_frame_dt, cutscene, bridge_camera, char_anim, walk_ctrl, watch_ctrl, idle_gestures, node_anim, lip_runtime, letterbox_anim`. Carried fields, read at entry and written back at exit: `accumulator: float, previous_real_time: float, bridge_left_pick_active=False, z_held_prev=False, v_held_prev=False, prev_interp_player=None, prev_player_set=(None, None), prev_view_set=None, prev_drawn_player_pose=None`.
  - `class FrameSimResult(NamedTuple)`: `now, wall_dt, frame_dt, player_dt, frame_game_dt, interp_alpha, sim_ticks, ships_this_tick, pose_of, player_interp_pose, session, player`.
  - `def _run_frame_sim(ctx: FrameSimContext, *, mx: float, my: float, cursor_in_panel: bool) -> FrameSimResult`.
  - Source markers: `# --- frame sim: begin ---` and `# --- frame sim: end ---` around the moved section inside `_run_frame_sim`; `# --- frame sim: call ---` and `# --- frame sim: call end ---` around the call and its unpacking in `run()`.
- Produces, in tests:
  - `host_frame_source.run_source() -> str`: `run()`'s source with the call block replaced by the section, re-indented to the call marker's indentation;
  - `host_frame_source.run_tree() -> ast.FunctionDef`: `ast.parse(run_source()).body[0]`;
  - `host_frame_fight.HEADLESS_STANDINS: dict[str, str]`, mapping a patched `module:attr` to its reason;
  - `host_frame_fight.headless_context(mp, scene, loop, *, tick_hook=None) -> FrameSimContext`;
  - `host_frame_fight.drive(ctx, frame_ticks: Sequence[int], frames: int, on_frame=None) -> list[FrameSimResult]`.

- [ ] **Step 1: Re-run the interface scan.** It checks which section locals `run()` reads afterwards and which `run()` locals the section reads. Parse `engine/host_loop.py`. For the section's line range, list the names stored in the range and loaded after it, and the names loaded in it and stored before it in `run()`. Expected: the output names are exactly `FrameSimResult`'s fields (written against `87401fe33`; phase 3 removed `handover` and `interp_live_poses`, so trust the scan). The inputs are `FrameSimContext`'s fields plus `_mx`, `_my`, `_cursor_in_panel`; ignore `_r`, `obj` and `key`, which are scan false positives. If phases 2-3 changed either list, update both classes before going on.
- [ ] **Step 2: Write the failing tests.**
  - `tests/unit/test_host_frame_source.py`:
    - `test_run_source_parses_as_one_function`: `run_tree().name == "run"`;
    - `test_run_source_has_the_section_in_place`: `src.index('frame_profiler.mark("sim")') < src.index("for _tick_i in range(_sim_ticks_this_frame)") < src.index('frame_profiler.mark("render_prep")')`, and `"_run_frame_sim(" not in src`;
    - `test_each_marker_appears_once` (in `inspect.getsource(host_loop.run)` and in `inspect.getsource(host_loop._run_frame_sim)`).
  - `tests/integration/test_host_frame_sim.py`:
    - `test_frame_sim_runs_headless_and_carries_its_state`: combat_stress with 2 ships, `headless_context`, `drive(ctx, (3, 0, 1), 3)`. Assert `[r.sim_ticks for r in results] == [3, 0, 1]`, that `ctx.accumulator` is within `[0, ctx.tick_dt)`, that `ctx.previous_real_time` equals the scripted clock's last value, and that `results[-1].player is App.Game_GetCurrentPlayer()`;
    - `test_headless_standins_mirror_the_real_surface`: every `module:attr` in `HEADLESS_STANDINS` exists on the real module.
- [ ] **Step 3:** Run `uv run pytest tests/unit/test_host_frame_source.py tests/integration/test_host_frame_sim.py -v`. Expected: FAIL (no `_run_frame_sim`).
- [ ] **Step 4: Move the section verbatim.** Implement `_run_frame_sim` as three parts:
  - a prologue that binds every old local from `ctx` (`_h = ctx.h`, `TICK_DT = ctx.tick_dt`, `MAX_FRAME_DT = ctx.max_frame_dt`, `_accumulator = ctx.accumulator`, …, plus the imports `run()` held: `App`, `step_accumulator`, `advance_ticks`);
  - the section between the markers, **byte for byte** (its `global` statements included);
  - an epilogue that writes the carried names back to `ctx` and returns `FrameSimResult`.

  In `run()`: build `_frame_ctx` once, immediately before `while not r.should_close():` (after the boot-notice clock restart at `:11930`). The loop body calls `_run_frame_sim(_frame_ctx, mx=_mx, my=_my, cursor_in_panel=_cursor_in_panel)` and unpacks the result's twelve fields into the old local names.
- [ ] **Step 5: Write the helpers.**
  - `run_source()` raises `AssertionError` naming any missing or duplicated marker.
  - `headless_context` uses the REAL `engine.cameras._CameraDirector()`, `host_loop._ViewModeController()`, `host_loop._PauseMenuController()`, `host_loop._PlayerControl(InputMap())` (no `.load()`) and `NativeTransformBuffer()`. It passes `h=None`, `perf_monitor_panel=None` and `crew_menu_panel=None`. The controller stand-in has exactly `session` (a `host_loop.MissionSession(mission_name=...)` whose `player` is the current player), `pending_swap=None`, `_drain_pending_swap` and `renderer=None`; `test_headless_standins_mirror_the_real_surface` also checks those four names on `host_loop.HostController`. `tick_gameloop` calls `tick_hook` if given, then `loop.tick()`.
  - Via `mp`, patch `host_loop._frame_clock` to a scripted clock. `drive` chooses each frame's dt as `(k + 0.5) * ctx.tick_dt - ctx.accumulator`, so frame *f* runs exactly `frame_ticks[f % len]` ticks.
  - Also via `mp`, stand in these GL- or window-bound calls, each listed in `HEADLESS_STANDINS` with its reason: `host_loop._reconcile_scene`, `host_loop._reconcile_camera_radius`, `host_loop._sync_instance_transforms`, `host_loop._poll_function_keys`, `host_loop._poll_raw_keyboard`, `host_loop._poll_skip_dialogue`, `host_loop._poll_mouse_buttons`, `host_loop._poll_modifier_chords`, `host_loop._poll_fire_keys` (no-op by default; Task 2 replaces it with the op stream), `engine.renderer:nebula_lightning_enabled` and `engine.renderer:volumetric_nebulae_enabled` (both return False), `engine.appc.debris_chunk:tick`.
  - Add a stand-in only when a run raises for want of GL or a window, and record it in the dict.
- [ ] **Step 6: Repoint the 25 guard files.** Replace each `inspect.getsource(host_loop.run)` (or `hl.run`, or the `__import__` form) with `host_frame_source.run_source()`. In `test_frame_rate_independence.py`, take `run_fn` from `host_frame_source.run_tree()` instead of walking the module for `run`. No assertion changes.
- [ ] **Step 7:** Run the two new files and the 25 repointed files, plus `tests/host/test_frame_rate_independence.py tests/host/test_native_combat_scene_audit.py tests/host/test_host_loop_unit.py` (these run `hl.run()` under a hidden window). Expected: all PASS.
- [ ] **Step 8: Falsifier.** Run `uv run pytest tests/integration/test_golden_fights.py -v`. Expected: all PASS, unchanged. No scene goes through `run()`, so a change here is a bug.
- [ ] **Step 9: Commit** `engine/host_loop.py`, the four new files and the 25 test files: `refactor(host): the frame's sim section becomes _run_frame_sim (no behaviour change)`.

### Task 2: `host_frames` goldens through the extracted callable, recorded before the reorder

**Files:**
- Modify: `tests/helpers/k1_fight.py` (split `_loop_arm` `:758` into `_loop_setup` plus the loop), `tests/helpers/host_frame_fight.py` (the scene), `tests/helpers/golden_fight.py` (`SCENES` `:604`, two wrappers, the module docstring's scene list), `tests/integration/test_golden_fights.py` (two tests, docstring)
- Create (recorded): `tests/fixtures/golden_fights/host_frames.darwin.json.gz`, `host_frames_tpf1.darwin.json.gz`

**Interfaces:**
- Consumes: Task 1's `headless_context`, `drive` and `HEADLESS_STANDINS`.
- Produces:
  - `k1_fight._loop_setup(mp, env, owns_boundary: bool = True) -> tuple[_Scene, GameLoop]`: everything in `_loop_arm` up to and including `_seed_every_rng(SEED)`. `_loop_arm` calls it, so its behaviour is unchanged;
  - `host_frame_fight.FRAME_TICKS = (3, 1, 6, 0, 2)`, `HOST_FRAME_OPS = ("fire",) * 4 + ("retarget",) * 2 + ("stop",)`;
  - `host_frame_fight.run(mp, env, spec, frame_ticks, frames, ops) -> golden_fight._Take`;
  - scenes `Scene("host_frames", "native", k1d.SEED, "8", 720, 0, _host_frames)` (300 frames; tpf 0 means the `FRAME_TICKS` cycle) and `Scene("host_frames_tpf1", "native", k1d.SEED, "8", 300, 1, _host_frames_tpf1)` (300 one-tick frames, no ops).

**The scene:**
- **Warm-up.** As `_k1_gameloop_ai`: `k1d._loop_arm(mp, k1d.OFF, ticks=WARM_UP_TICKS)`, then `gc.collect()`.
- **Setup.** `_loop_setup(mp, env, owns_boundary=False)`, then `headless_context`.
- **Ops.** Each frame's ops run inside the patched `host_loop._poll_fire_keys`: `rng.randint(0, 2)` × `scene.op(rng, ops)` with `rng = random.Random(k1d.SEED)`.
- **Recording.**
  - Patch `host_loop._combat_tick_boundary` to call the original, then `scene.record()`.
  - Attribute each tick by its index *within the frame*, so the two orders compare tick for tick. `tick_hook` sets `scene.tick = first + k` for GameLoop tick *k*. A wrapper on `host_loop._advance_weapons` sets `scene.tick = first + j` for combat tick *j*. The op hook sets `scene.tick = first - 1`.
  - Each frame appends a note `("frame", first - 1, n)`.
- **Self-checks.**
  - every frame ran its scheduled tick count;
  - at least one op ran;
  - `scene.starts > 0`;
  - `_check_native(scene)`, and `nc.audit_mirror()` is clean at the end.

- [ ] **Step 1: Write the tests.** Add `test_host_frames()` and `test_host_frames_tpf1()` to `test_golden_fights.py`, each `_golden(<name>)`.
- [ ] **Step 2:** Run `uv run pytest tests/integration/test_golden_fights.py::test_host_frames tests/integration/test_golden_fights.py::test_host_frames_tpf1 -v`. Expected: SKIP, naming the missing fixtures.
- [ ] **Step 3: Record.** `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="new scenes: host frames through _run_frame_sim, today's batched order, recorded before ruling 2 (phase 4 Task 2)" uv run pytest tests/integration/test_golden_fights.py::test_host_frames tests/integration/test_golden_fights.py::test_host_frames_tpf1`. Expected: written, then SKIP. Run the pair again. Expected: PASS twice in a row (determinism).
- [ ] **Step 4: Falsifier.** Run the whole `tests/integration/test_golden_fights.py`. Expected: PASS. `k1_gameloop_ai` and `sdk_dumb_fire` must be byte-identical after the `_loop_setup` split.
- [ ] **Step 5: Commit** the four test files and the two fixtures: `test(golden): host_frames scenes through the frame sim, batched order`.

### Task 3: Whole ticks (ruling 2)

**Files:**
- Modify: `engine/host_loop.py`:
  - the section inside `_run_frame_sim`'s markers;
  - the `_sync_player_identity` docstring `:7412-7422`.
- Modify: `tests/helpers/k1_fight.py` (`_Scene.run` `:499` gains `whole_ticks: bool = False`), `tests/helpers/golden_fight.py` (`k1_ops_tpf6` runs `_k1_ops_whole_ticks`), `tests/host/test_frame_rate_independence.py` (`per_tick` accepts FunctionDef `_whole_tick`), `tests/host/test_warp_state_host_wiring.py` (its `advance_ticks(` needle names `_whole_tick`), `tests/host/test_scene_reconcile_ordering.py` (new guard), `docs/reference/engine/perf-cadences-and-latency.md` (a "Whole ticks (ruling 2)" section: the Behaviour shifts table), spec §5.4 (status line)
- Create: `tests/integration/test_whole_ticks.py`
- Re-record (own commit): `host_frames`, `k1_ops_tpf6`

**Interfaces:**
- Consumes: Task 1's callable and harness; Task 2's scenes.
- Produces: the section's new order (below). The nested `def _whole_tick()` inside `_run_frame_sim` (it uses `nonlocal _ships_this_tick`). `k1_fight._Scene.run(..., whole_ticks=True)`: per frame, `before_frame`, then BOTH op draws (the `randint(0, 2)` pre-ops, then the former between-batch ops, in that RNG order), then per tick: timer bump, `_update_ship_subsystems()`, `tick += 1`, ships, scope(weapons, combat), boundary, record, and `rng.random() < 0.3` → op.

**The new section order** (all of it inside the markers):
1. freeze, clock and accumulator, through `_interp_alpha` (unchanged);
2. the swap drain block, when `_sim_ticks_this_frame > 0` (moved up, unchanged);
3. `session = controller.session`, `sim.session_sync`, `_on_player_change`, `_sync_player_identity`, `player = ...`, the camera radius after a swap (moved up);
4. `_pose_of` and `_player_interp_pose` set to None; `sim.keys` (moved up);
5. `_ships_this_tick = None`; `if not pause.sim_frozen:` `sim.input`, through `manual_aim.update(...)` (moved up, unchanged);
6. `def _whole_tick()`: `_tick_gameloop()`; `sim.ship_list` rebuilds `_ships_this_tick`; `with _combat_effect_scope():` `sim.weapons` `_advance_weapons(_ships_this_tick, TICK_DT)`, `sim.combat` `_advance_combat(...)` (arguments as today); `_combat_tick_boundary()`. **No new profiler scope**, so every row keeps its parent;
7. `advance_ticks(_xform_buf, _sim_ticks_this_frame, _whole_tick)`; `warp.preload`;
8. **second identity sync:** `if session is not None: _sync_player_identity(session, _on_player_change)`, then `player = session.player if session is not None else None` (Review Focus 2);
9. `if not pause.sim_frozen:` first, when `_ships_this_tick is None` (a zero-tick frame), build it once under `sim.ship_list`; then everything from `sensor_contacts.tick` on, unchanged. `else:` the frozen reconcile, unchanged. The old `for _tick_i in range(_sim_ticks_this_frame)` combat loop is deleted; the nebula and radiation loop stays.

- [ ] **Step 1: Write the failing tests** in `tests/integration/test_whole_ticks.py`. They drive `_run_frame_sim` through `host_frame_fight` (combat_stress with 2 ships unless stated) and use spies that append to one `order` list:
  - `test_each_tick_runs_whole`: one 3-tick frame. `order == ["gl", "weapons", "combat", "boundary"] * 3`, with spies on `tick_hook`, `host_loop._advance_weapons`, `host_loop._advance_combat` and `host_loop._combat_tick_boundary`;
  - `test_frame_start_stages_run_before_tick_0`: `_drain_pending_swap` (with a pending swap), `_fire_pending_preload_done`, `_process_object_deletions`, `_poll_fire_keys` and `manual_aim.update` all appear in `order` before the first `"gl"`;
  - `test_fire_press_reaches_the_frames_first_combat_tick`: the patched `_poll_fire_keys` calls the player's phaser system `StartFiring(target)`. At the first `_advance_weapons` call that frame, `system.IsFiring()` is true;
  - `test_fire_press_on_a_zero_tick_frame_reaches_the_next_combat_tick` (Review Focus 5): frames `(0, 1)`, press on frame 0. No `_advance_weapons` call on frame 0, and `IsFiring()` at frame 1's first call;
  - `test_swap_requested_during_a_tick_drains_at_next_frame_start` (Review Focus 1): `tick_hook` sets `controller.pending_swap` during tick 1 of a 3-tick frame. That frame: no drain, and three `"combat"` entries. Next frame: the drain comes before its first `"gl"`;
  - `test_recreate_player_inside_a_tick_reaches_the_post_tick_pass` (Review Focus 2): `tick_hook` makes another ship the game's player during tick 1. The spy on `engine.appc.sensor_contacts.tick` gets the new player that same frame, and `result.player` is the new one;
  - `test_ship_flagged_for_deletion_mid_frame_leaves_at_next_frame_start` (Review Focus 3): `SetDeleteMe(1)` on Enemy-1 during tick 1 of a 3-tick frame. It is in the ship lists of combat ticks 1-3, and not in the set after the next frame's frame-start stages;
  - `test_ship_spawned_in_tick_2_reaches_combat_tick_2_only`: a ship created in GameLoop tick 2 is absent from combat tick 1's list and present in tick 2's;
  - `test_zero_tick_frame_builds_the_ship_list_once`: frame `(0,)`. One `sim.ship_list` build, `result.ships_this_tick` is a list, no `"gl"`;
  - `test_frame_frozen_mid_frame_still_runs_its_whole_ticks`: a spy on `_route_scroll_wheel` (inside `sim.keys`) sets the pause stand-in's freeze. The 2-tick frame still has two `"combat"` entries; `sensor_contacts.tick` is not called;
  - `test_reseat_runs_after_the_penultimate_boundary`: a 3-tick frame. The spy on `ctx.xform_buf.reseat_from_live` lands between the second `"boundary"` and the third `"gl"`;
  - and in `tests/host/test_scene_reconcile_ordering.py`, `test_whole_tick_order_and_frame_start_stages`: in `run_source()`, inside `def _whole_tick`, `_tick_gameloop()` < `_advance_weapons(` < `_advance_combat(` < `_combat_tick_boundary()`; each of `_drain_pending_swap()`, `_fire_pending_preload_done()`, `_apply_input(`, `_poll_fire_keys(` and `manual_aim.update(` comes before `advance_ticks(`; the text `_advance_combat(` appears once.
- [ ] **Step 2:** Run `uv run pytest tests/integration/test_whole_ticks.py tests/host/test_scene_reconcile_ordering.py -v`. Expected: FAIL (batched order).
- [ ] **Step 3: Implement the order above,** `_Scene.run(whole_ticks=True)`, and `golden_fight._k1_ops_whole_ticks(mp, env, spec)` (as `_k1_ops`, with `whole_ticks=True`). Update the `_sync_player_identity` docstring, the comment blocks the move makes stale, the frame-rate guard and the warp-state needle.
- [ ] **Step 4:** Run the new file, the 25 repointed guard files, `tests/integration/test_host_frame_sim.py tests/host/test_frame_rate_independence.py tests/host/test_native_combat_scene_audit.py tests/host/test_passive_state_scene_audit.py tests/host/test_handover_continuity.py tests/unit/test_player_ai_motion_handoff.py tests/unit/test_transform_buffer.py`. Expected: PASS.
- [ ] **Step 5: Falsifier, before any re-record.** Run `uv run pytest tests/integration/test_golden_fights.py -v`. Expected: exactly `test_host_frames` and `test_k1_ops_tpf6` FAIL. `host_frames_tpf1` must PASS unchanged: on one-tick frames with no ops, whole ticks and batched ticks are the same sequence. If it changes, or any other scene changes, STOP (BLOCKED, with the first difference).
- [ ] **Step 6: Commit** the code, the tests and the docs: `feat(host): each tick runs whole -- AI, motion, combat, boundary (ruling 2)`. The message body lists the Behaviour shifts table's rows 1-12 and 14, one line each.
- [ ] **Step 7: The one re-record.** `UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="ruling 2: each tick runs whole (AI, motion, combat, boundary); input and session stages at frame start; k1_ops_tpf6 driven in whole ticks" uv run pytest tests/integration/test_golden_fights.py::test_host_frames tests/integration/test_golden_fights.py::test_k1_ops_tpf6`. Then run the whole file. Expected: PASS.
- [ ] **Step 8: Commit** the two fixtures alone: `test(golden): re-record host_frames, k1_ops_tpf6: each tick runs whole (ruling 2)`.

### Task 4: Combat reads the tick's published poses (a read window, live fallback)

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/published_poses.h`, `native/src/combat/src/published_poses.cc`, `native/src/combat/src/geometry_internal.h` (`xform` `:49-60`), `hit_pose_of` in `native/src/host/host_bindings.cc` (Assumption 5), `native/src/host/host_bindings.cc`, `engine/appc/native_motion.py`, `engine/host_loop.py` (`_advance_combat` `:1274`), `engine/core/loop.py` (the `owns_boundary` branch `:131-136`)
- Test: `native/tests/combat/published_poses_test.cc` (extend), `tests/unit/test_published_pose_window.py` (new), `tests/integration/test_host_frame_sim.py` (one test)

**Interfaces:**
- Consumes: Assumption 1's buffer and publish; Assumption 2's "no ship-pose writer in combat".
- Produces:
  - C++ `PublishedPoses`:
    - `const TransformStore::Transform* pose_for(uint32_t xform_index, uint32_t xform_gen) const` returns nullptr when the window is closed or the slot was not published. It is backed by a `std::vector<TransformStore::Transform>` and a `std::unordered_map<uint64_t, size_t>` keyed `index << 32 | gen`, both built in `publish`;
    - `void close()`; `bool is_open() const`;
    - `publish` opens the window; `clear` closes it.
  - `detail::xform(m, o)` returns `*pose_for(...)` when it is non-null, else today's store slot.
  - Bindings: `combat_motion_published_close()`, `combat_motion_published_open() -> bool`, and the test reader `combat_pose_read(h: int) -> (pos3, rot9)`, which returns what `detail::xform` returns for object handle `h` right now.
  - Python: `native_motion.close_published() -> None`. It is called in a `finally` around `host_loop._advance_combat`'s body, and in `GameLoop.tick` before `effect_queue.boundary()` when `owns_boundary`.
  - So the window is `[publish, end of _advance_combat]`. AI-stage K1 calls, frame-start fire keys, effect handlers, collisions and every headless `owns_boundary=True` loop read live.

- [ ] **Step 1: Write the failing tests.**
  - gtests:
    - `PublishedPoses.PoseForWhileOpen`;
    - `.ClosedReturnsNull`;
    - `.StaleGenerationReturnsNull`;
    - `.PublishReopens`.
  - `tests/unit/test_published_pose_window.py` (combat_stress with 2 ships, `GameLoop(owns_boundary=False)`, the host's whole-tick body called by hand):
    - `test_window_open_from_publish_to_the_end_of_advance_combat`: `combat_motion_published_open()` is False in a `gl.ai` spy, True in an `_advance_weapons` spy, and False after `_advance_combat` returns;
    - `test_mid_ai_teleport_seen_by_combat_same_tick`: a teleport of Enemy-1 in a `tick_all_ai` wrapper. Inside the `_advance_weapons` spy, `combat_pose_read(h)` equals the teleported pose;
    - `test_mid_combat_teleport_seen_next_tick`: a teleport inside the `_advance_weapons` spy. `combat_pose_read(h)` there still returns the published pose; after the next tick's publish it returns the teleported one;
    - `test_handler_after_combat_reads_live` (Review Focus 4): an effect-queue handler teleports and then calls `combat_pose_read`. It gets the live pose;
    - `test_kernel_outside_window_reads_live` (a teleport after the boundary);
    - `test_ship_spawned_after_publish_reads_live`;
    - `test_freed_and_reused_slot_reads_live`;
    - `test_owns_boundary_loop_closes_before_combat`.
  - `tests/integration/test_host_frame_sim.py`, `test_published_equals_live_at_every_combat_step`: 60 frames of `FRAME_TICKS` on combat_stress with 8 ships. At each `_advance_combat` entry, every row of `combat_motion_published()` equals the live store pose by `.hex()`. This is the §6 contract: no stage writes a ship pose between publish and combat.
- [ ] **Step 2:** `cmake --build build -j`; run `uv run pytest tests/unit/test_published_pose_window.py -v` and `ctest --test-dir build -R combat_PublishedPoses`. Expected: FAIL (unknown bindings, or the store pose read inside the window).
- [ ] **Step 3: Implement.** Change `detail::xform` (`world_location` and every caller go through it) and `hit_pose_of`, which gets the same rule keyed by its instance's `sim_xform_index`/`sim_xform_generation`: inside the window a gameplay hit test reads the published pose, outside it the live store. K3's torpedoes are never published, so they read live with no special case.
- [ ] **Step 4:** Build; run the new files, `tests/integration/test_host_frame_sim.py tests/integration/test_whole_ticks.py tests/unit/test_native_motion_publish.py tests/unit/test_native_k1_holds_gil.py tests/unit/test_native_combat_world.py`, and `ctest --test-dir build -R combat_`. Expected: PASS.
- [ ] **Step 5: Falsifier.** Run `uv run pytest tests/integration/test_golden_fights.py -v`. Expected: all PASS, unchanged, `host_frames` included: inside the window published equals live (Step 1's contract test). A change is BLOCKED; never re-record here.
- [ ] **Step 6: Commit:** `feat(combat): combat reads the tick's published poses inside the combat step`.

### Task 5: Measure, record, ask for the live check (cleared by Mark)

- [ ] Rebuild (`cmake --build build -j`). Run `docs/reference/engine/native-motion/phase0-runbook.md` §1's command twice (Debug, combat_stress, 64 ships, bridge view, 1,500 frames). Score as runbook §1.
- [ ] Record the next SIG number in `docs/reference/engine/perf-register.md`: rows `sim`, `sim.gameloop`, `sim.combat`, `sim.effects`, `sim.input`, ticks per frame, compared with phase 3's SIG-188 (C-296/C-297). The expected saving is ≈ 0 (spec §5.4). Record any change as measured, without an attribution the runs cannot support. Never edit an old signal.
- [ ] Mark spec §5.4 done (date, commits). Commit the docs: `docs(perf): phase 4 whole ticks measured`.
- [ ] Ask Mark for the live check (decision 4's list). Name Behaviour shifts rows 4-6 as the ones to feel for. Record his verdict in the spec on the day.

---

## Self-review

- **Spec coverage (§5.4):**
  - whole ticks and the re-seat: Task 3;
  - frame-start stages, with each shift listed: Task 3 and the Behaviour shifts table;
  - extraction first, with about 25 guards repointed: Task 1;
  - the `host_frames` golden recorded before the reorder: Task 2;
  - the `tpf6` rewrite and ONE re-record: Task 3;
  - the combat accessor on the published buffer, K3 live: Task 4;
  - proximity stays live (ruling 5): untouched, and stated in contradiction 1;
  - late pose writers and mid-tick spawns: Task 4 tests;
  - §7's teleport test: Task 4;
  - live check: Task 5.
- **Not covered, by decision:** removing the motion kernel's in-system-warp segments (needs a ruling, spec §5.2); nebula and radiation in the whole tick (decision 3).
- **Type consistency:** the same names are used everywhere:
  - `FrameSimContext`, `FrameSimResult`, `_run_frame_sim`, `run_source`, `run_tree`, `headless_context`, `drive`;
  - `_whole_tick`, `_loop_setup`, `whole_ticks`;
  - `pose_for`, `close_published`, `combat_motion_published_open`, `combat_pose_read`.
- **Proportion:** there are no function bodies, only signatures, orders and assertions. The section is moved verbatim, so it is not transcribed here.
