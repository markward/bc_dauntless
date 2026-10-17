# Warp Tunnel Preload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the multi-second freeze on arrival after a set-to-set warp. The
destination loads during the warp tunnel, which waits (floor + 30 s cap) until
it is ready. Then the system haze is turned on for production.

**Architecture:** A pure-Python `Preload` object (`engine/warp_preload.py`)
owns one warp's destination work. Async CPU work (haze table, impostor-atlas
decode) runs on native `std::async` workers. GL work (planet/ship model loads,
uploads) runs one item per tunnel frame, through loader callables the host
injects. `engine/appc/warp.py` reaches it only through hooks
(`configure_warp_hooks`), like `_realize_hook` today. `_HoldUntilAction`
completes only when the floor has passed AND the preload is ready, or 30 s of
real time past the floor.

**Tech Stack:** Python 3.11 host loop, C++17 renderer (pybind11 `_dauntless_host`), gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-warp-tunnel-preload-design.md`.
Executors read the spec and this plan.

## Global Constraints

- Work in worktree `.claude/worktrees/warp-arrival-spikes`, branch `perf/warp-arrival-spike-log`. Never commit to main.
- **Banned git:** `checkout -- <path>`, `checkout .`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`, `add .`. Stage with explicit paths. Tell every subagent the same.
- Never reconfigure `CMAKE_BUILD_TYPE`; the tree is Debug and the numbers are Debug numbers.
- Build: `cmake --build build -j` in the worktree. Never run cmake from `native/`.
- `load_model`, texture uploads and every GL call: main thread only. Worker threads do CPU-pure work only, and must be native (`std::async`), never a Python thread.
- Safety cap: **30 s** of real time past the floor. Poll interval while waiting: **0.05 s** real time.
- GL budget during the tunnel: **at most one model load per frame** (planet or ship); at most **2** atlas uploads per frame.
- Never launch `./build/dauntless` yourself. Mark does live runs.
- No game-state mutation in the preload: it never runs SDK `Initialize`, never posts events, never changes sets.
- Tests: `scripts/check_tests.sh` is the merge gate. New/changed native bindings go in the facade manifests (`engine/renderer.py` binding list, `engine/host_io.py` `_OPTIONAL_BINDINGS` and their manifest tests).

## Review Focus

1. **A warp aborted mid-tunnel** (warp cancelled, player destroyed). The preload must end, with no tunnel stuck waiting and no stale preload stepping into the next warp. → Task 7 test `test_abort_ends_the_preload`.
2. **A destination with no system map** (QuickBattleRegion, mission-only sets). The preload is ready at once and the tunnel behaves exactly as today. → Task 6 test `test_unmapped_destination_is_ready_immediately`.
3. **Haze setting off** (Improved Space off, or production before Task 8). The preload must not wait on a haze table that will never be pushed. → Task 6 test `test_haze_not_awaited_when_gate_closed`.
4. **A dev dial change while a prebuild for the same system is pending.** The new key builds synchronously; the old future never overwrites the installed table. → Task 2 test `PendingOldKeyDoesNotReplaceNewInstall`.
5. **Warping back to a system already visited** (the measured 7.3 s return case). The cache hits and the preload is ready on its first step. → Task 6 test `test_cached_haze_is_ready_on_first_step`; acceptance run in Task 9.

---

### Task 1: Attribute the unexplained arrival time (scopes + checkpoint)

**Files:**
- Modify: `engine/core/loop.py:32-33` (timer ticks)
- Modify: `engine/appc/warp.py` (`_WarpDepartAction`, `_PlacePlayerAction`, `_ArriveFinalizeAction`, `_ArrivalExitedWarpAction`, `_ArrivalClearTargetsAction` `_do_play`)
- Modify: `native/src/host/host_bindings.cc:~1591-1606` (split `rock.near.draw`), `native/src/renderer/far_pass.cc:146` (`atlas_for`)
- Modify: `docs/engine/frame-profiler.md` (spike-capture scope list)
- Test: `tests/unit/test_frame_profiler_spikes.py`

**Interfaces:**
- Produces scope names, which Task 9's acceptance reads: `gl.timers.game`, `gl.timers.real`, `warp.depart`, `warp.place_player`, `warp.arrive_finalize`, `warp.exited_warp`, `warp.clear_targets`, `rock.near.build`, `rock.near.mesh_draw`, `rock.impostor.draw`, `rock.atlas.load`.

- [ ] **Step 1: Write the failing test** `test_warp_arrival_actions_are_scoped` in `tests/unit/test_frame_profiler_spikes.py`. Enable the profiler (`native=False`), `begin_frame(); mark("sim")`, call each listed action's `_do_play()` through a minimal fake (monkeypatch its body's collaborators, or invoke via the existing warp unit-test fixtures in `tests/unit/test_warp_arrival_adopts.py`), `end_frame()`, and assert each scope name is in `fp.parents()`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_frame_profiler_spikes.py -k scoped -v`. Expected: FAIL (names absent).
- [ ] **Step 3: Implement.** Wrap each action's `_do_play` body in `with frame_profiler.scope("<name>")`, the way `ChangeRenderedSetAction` already does (`_do_play` → `_swap`). Wrap the two timer ticks in `loop.py` in `gl.timers.game` / `gl.timers.real`. In `host_bindings.cc`, split the `rock.near.draw` block into nested `DAUNTLESS_FRAME_SCOPE`s: `rock.near.build` around `g_near_field.build`, `rock.near.mesh_draw` around `g_minor_pass->render`, `rock.impostor.draw` around `render_impostors`. In `FarPass::atlas_for`, put `DAUNTLESS_FRAME_SCOPE("rock.atlas.load")` around the `install_atlas(read_image…)` load (include `renderer/frame_timer.h`).
- [ ] **Step 4: Run** the test, then `cmake --build build -j` and `.venv/bin/python -m pytest tests/host/test_frame_profiler_gl.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `perf(profiler): scope warp arrival actions, timer ticks, rock draw split`.
- [ ] **Step 6: CHECKPOINT. Stop and hand Mark this launch command.** Ask him to run his route (Vesuvi Haven → Starbase 12 → Vesuvi Haven) and one E1M1 → E1M2 warp, then quit:
  ```bash
  cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/warp-arrival-spikes
  DAUNTLESS_PROFILE_SPIKES=logs/warp-spikes-2.log ./build/dauntless --developer
  ```
  Read the log. Record the attribution in the spec's Measured table. Continue to Task 2 only if:
  (a) the 817 ms / 402 ms blocks are now owned by a preloadable item, or by `warp.mission_change` (exempt per spec);
  (b) `rock.atlas.load` owns most of `rock.near.draw`'s first-visit cost.
  If (b) fails, drop Task 5 and note it. If (a) shows SDK work tied to its moment, **stop and bring the numbers to Mark** (spec §3).

### Task 2: Native haze table cache + async prebuild

**Files:**
- Create: `native/src/renderer/include/renderer/system_nebula_cache.h`, `native/src/renderer/system_nebula_cache.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add source), `native/src/renderer/system_nebula_pass.{h,cc}` (`set_profile` uses the cache)
- Modify: `native/src/host/host_bindings.cc` (new bindings beside `set_system_nebula_profile`; factor its dict→(profile, look) parse into one static helper `parse_system_nebula_profile(py::dict) -> std::pair<RadialProfile, LookParams>` used by all three)
- Modify: `engine/renderer.py` (wrappers + binding list)
- Test: `native/tests/renderer/system_nebula_cache_test.cc` (add to `native/tests/renderer/CMakeLists.txt`), `tests/host/test_system_nebula_prebuild_gl.py`

**Interfaces:**
- Produces (C++, namespace `renderer::atmosphere`):
  ```cpp
  struct BuiltProfile {                      // everything set_profile uploads
      std::vector<glm::vec2> radial;         // build_radial_texels
      std::vector<glm::vec3> tau;            // tau_from_table(table)
      std::vector<glm::vec3> inscatter;      // table.inscatter
  };
  std::uint64_t profile_key(const RadialProfile&, const LookParams&);  // FNV-1a over every field's bytes
  BuiltProfile build_profile(const RadialProfile&, const LookParams&);  // the CPU half of today's set_profile
  class TableCache {
  public:
      using Builder = std::function<BuiltProfile(const RadialProfile&, const LookParams&)>;
      explicit TableCache(Builder b = build_profile);
      void prebuild(const RadialProfile&, const LookParams&);   // no-op if cached or pending; else std::async
      bool ready(const RadialProfile&, const LookParams&);      // cached, or pending future ready (moves it into the cache)
      std::shared_ptr<const BuiltProfile> get(const RadialProfile&, const LookParams&);  // cache hit; else wait on pending; else build synchronously
      std::size_t size() const;
  };
  ```
- `SystemNebulaPass` gains `void prebuild(const RadialProfile&, const LookParams&)` and `bool prebuilt(const RadialProfile&, const LookParams&)`, both forwarding to a member `atmosphere::TableCache cache_`. `set_profile` uploads from `cache_.get(...)`.
- Produces (Python, `engine/renderer.py`): `system_nebula_prebuild(profile: dict) -> None` and `system_nebula_prebuilt(profile: dict) -> bool`. Same dict keys as `set_system_nebula_profile`.

- [ ] **Step 1: Write failing gtests** in `system_nebula_cache_test.cc`. Use a counting fake `Builder` that returns a tiny `BuiltProfile` (never the real 7 s build):
  - `SameInputsSameKey` / `ChangedGChangesKey` / `ChangedRowChangesKey`: `profile_key` equality and inequality.
  - `GetBuildsOnceThenHits`: two `get` calls → builder called once, same pointer.
  - `PrebuildThenGetDoesNotRebuild`: `prebuild`; spin `ready` until true (≤ 2 s); `get` → builder count 1.
  - `PrebuildIsIdempotentWhilePending`: two `prebuild`s → builder count 1.
  - `PendingOldKeyDoesNotReplaceNewInstall`: prebuild key A (the builder blocks on a latch); `get(B)` builds B synchronously; release the latch; `get(B)` still returns B's table, and `get(A)` returns A's.
  - `BuildProfileMatchesTodaysUpload`: real `build_profile` on a 2-row profile; `radial.size()==kRadialTexels`, `tau.size()==inscatter.size()==kTableR*kTableMu`. This one test pays one real build.
- [ ] **Step 2: Run** `cmake --build build -j && ./build/native/tests/renderer/renderer_tests --gtest_filter='TableCache*:SystemNebulaCache*'` (use the binary path ctest lists). Expected: FAIL to compile.
- [ ] **Step 3: Implement** the cache: `std::unordered_map<uint64_t, std::shared_ptr<const BuiltProfile>>` plus `std::unordered_map<uint64_t, std::shared_future<BuiltProfile>>` pending, main-thread access only. Move `set_profile`'s CPU half into `build_profile` and upload from the cached struct. Keep `profile_rebuild_count_` incrementing per `set_profile` call (existing tests read it).
- [ ] **Step 4: Run** the gtests and the existing `SystemNebulaPass*` tests. Expected: PASS.
- [ ] **Step 5: Write failing host test** `tests/host/test_system_nebula_prebuild_gl.py`, using the same `init`/`shutdown` module fixture as `tests/host/test_frame_profiler_gl.py`: `system_nebula_prebuild(d)` returns in < 50 ms; poll `system_nebula_prebuilt(d)` until True (timeout 60 s); then `set_system_nebula_profile(d)` takes < 200 ms. `d` is a 3-row profile.
- [ ] **Step 6: Implement** the bindings and facade wrappers, and add both names to `engine/renderer.py`'s binding list. Run the host test and `tests/unit/test_renderer_binding_manifest.py`. Expected: PASS.
- [ ] **Step 7: Commit** `perf(haze): session cache + async prebuild for the system nebula table`.

### Task 3: One Python builder for the haze profile dict

**Files:**
- Create: `engine/system_haze.py`
- Modify: `engine/host_loop.py` (`_push_system_nebula` uses it)
- Test: `tests/unit/test_system_haze.py`; existing `tests/unit/test_system_nebula_feed.py` must stay green unchanged

**Interfaces:**
- Produces: `profile_dict(m, *, veil: float, dials: dict, far_gu: float) -> dict | None`. Returns the exact dict `_push_system_nebula` pushes today, or None when `m` is None, has no profile, or has no star. `dials` = `dev_nebula_dials.current()`; `far_gu` = `host_loop.SCENE_FAR_GU`.
- Produces: `profile_dict_for_set(set_name: str) -> dict | None`. Resolves `engine.systems.resolve.for_set(set_name)` → map, then `profile_dict(m, veil=dev_nebula_dials.veil(), dials=dev_nebula_dials.current(), far_gu=<SCENE_FAR_GU>)`. Import `SCENE_FAR_GU` from wherever host_loop defines it; move the constant into `engine/system_haze.py` if importing host_loop would be circular.

- [ ] **Step 1: Write failing tests:** `test_profile_dict_matches_the_push` builds the same `SystemMap` fixture `test_system_nebula_feed.py` uses and asserts `profile_dict(...)` equals the dict `_push_system_nebula` pushes for it (captured through that file's `_R` double). Also `test_none_without_profile`, `test_none_without_star`, and `test_for_set_unknown_set_is_none`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_system_haze.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** by moving the dict construction out of `_push_system_nebula`; `_push_system_nebula` calls `profile_dict`.
- [ ] **Step 4: Run** `tests/unit/test_system_haze.py tests/unit/test_system_nebula_feed.py`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(haze): one builder for the system nebula profile dict`.

### Task 4: Hull-volume prewarm by model handle

**Files:**
- Modify: `native/src/host/host_bindings.cc` (beside `hull_volume_prewarm`)
- Modify: `engine/renderer.py` (wrapper + list), `engine/appc/hull_volume.py`
- Test: `tests/unit/test_hull_volume_prewarm_model.py`, `tests/host/test_hull_volume_prewarm_model_gl.py`

**Interfaces:**
- Produces (binding): `hull_volume_prewarm_model(model_handle: int, resolution: float) -> None`. Resolves `model->source`. If `resolution > 0`, calls `renderer::set_hull_volume_resolution(source, resolution)` then `hull_volume_cache().get(source, resolution, voxel::kDefaultQuality)`. Unknown handle or non-positive resolution: no-op. Creates no instance.
- Produces (Python): `hull_volume.prewarm_for_model(ship, handle) -> bool`. Reads `ship.GetDamageResolution()` with `push_resolution`'s exact error contract; True when a prewarm was issued.

- [ ] **Step 1: Write failing tests.** Unit: `prewarm_for_model` calls the binding with the ship's resolution; skips a ship with none or 0; lets a binding error propagate. Host GL: load a stock hull model (find content through the same helper the existing asset-backed host tests use, and skip-with-reason when no content root is configured), call `hull_volume_prewarm_model(handle, res)`, and assert no instance was created (`instance_count` before == after, or whatever counter the facade exposes).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them plus `tests/unit/test_renderer_binding_manifest.py`. Expected: PASS.
- [ ] **Step 5: Commit** `perf(hull): prewarm a hull volume by model handle, no instance`.

### Task 5: Impostor atlases decoded off the main thread (only if Task 1 confirmed)

**Files:**
- Modify: `native/src/renderer/include/renderer/far_pass.h`, `native/src/renderer/far_pass.cc`
- Modify: `native/src/host/host_bindings.cc` (beside the `far_*` bindings), `engine/renderer.py`
- Test: `native/tests/renderer/far_pass_test.cc`

**Interfaces:**
- Produces (C++ `FarPass`):
  - `void prefetch_atlases()`: for every index in `paths_` not loaded, failed or pending, start `std::async` → `{read_image + dilate_coverage}` for albedo and normal.
  - `int pump_atlas_uploads(int max_uploads)`: uploads up to `max_uploads` ready entries (no second dilate); returns the count still pending.
  - `atlas_for`: a pending index waits on its future and installs it. It must never decode twice.
  - Split `upload_atlas` into the dilate step and an upload-only step.
- Produces (Python): `far_prefetch_atlases() -> None`, `far_pump_atlas_uploads(max_uploads: int) -> int`.

- [ ] **Step 1: Write failing gtests** (FarPass GL fixture already in `far_pass_test.cc`), using temp PNGs written by the test:
  - `PrefetchThenPumpInstallsAll`: pump until 0 → `atlas_loaded(i)` for each index.
  - `PumpRespectsBudget`: with 3 ready entries, `pump(2)` returns 1 and installs 2.
  - `AtlasForWaitsOnPending`: prefetch, then `has_atlas(i)` → true, with no double decode (count decodes through a test hook, or by asserting `failed_` stays empty and the result is identical).
  - `BadPathIsRememberedAsFailed`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `FarPass*` gtests plus `tests/unit/test_renderer_binding_manifest.py`. Expected: PASS.
- [ ] **Step 5: Commit** `perf(rocks): decode impostor atlases off the main thread`.

### Task 6: The `Preload` object

**Files:**
- Create: `engine/warp_preload.py`
- Test: `tests/unit/test_warp_preload.py`

**Interfaces:**
- Consumes: `system_haze.profile_dict_for_set` (Task 3). The renderer's `system_nebula_prebuild` / `system_nebula_prebuilt` (Task 2) and `far_prefetch_atlases` / `far_pump_atlas_uploads` (Task 5), reached through an injected `renderer` object.
- Produces:
  ```python
  class Preload:
      def __init__(self, dest_set_name: str, *, renderer, haze_enabled: Callable[[], bool],
                   planet_models: Callable[[str], list[str]],      # set name -> planet model names to load
                   load_planet: Callable[[str], None],             # model name -> loads into the controller cache
                   ships: Callable[[str], list],                   # set name -> ships of that set if it exists, else []
                   load_ship: Callable[[object], None]) -> None    # model load + prewarm_for_model
      def step(self) -> None          # kicks async work on first call; then at most ONE load_planet/load_ship; then far_pump_atlas_uploads(2)
      def replan(self) -> None        # re-query ships(dest) (after a mission change); keep done work
      def ready(self) -> bool
      def pending(self) -> list[str]  # human-readable names of unfinished items, for the late log
  def begin(dest_set_name: str, **deps) -> Preload   # replaces any active preload
  def active() -> Preload | None
  def end() -> None
  ```
  `ready()` is True when every queued planet and ship is loaded, the atlas pump returned 0 (skip when Task 5 was dropped), and the haze is prebuilt, or `haze_enabled()` is False, or `profile_dict_for_set` is None.

- [ ] **Step 1: Write failing tests** with fakes for every dependency:
  - `test_first_step_kicks_haze_and_atlases`: prebuild called once with the dict; prefetch called once.
  - `test_one_gl_load_per_step`: 3 planets + 2 ships → five `step()`s each issue exactly one load; planets come first.
  - `test_ready_waits_for_haze`: all loads done, `prebuilt` False → not ready; True → ready.
  - `test_haze_not_awaited_when_gate_closed` (Review Focus 3).
  - `test_unmapped_destination_is_ready_immediately` (Review Focus 2): no map, no ships → ready after the first step.
  - `test_cached_haze_is_ready_on_first_step` (Review Focus 5).
  - `test_replan_adds_ships_created_by_the_mission_change`: `ships()` returns [] at begin and 2 ships after `replan()`; those 2 get loaded; finished planets are not reloaded.
  - `test_pending_names_the_unfinished_items`.
  - `test_begin_replaces_the_active_preload` / `test_end_clears_active`.
  - `test_a_failing_loader_does_not_block_ready`: a `load_planet` that raises is logged once (`dev_mode.log_swallowed`) and counted as done.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_warp_preload.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(warp): Preload — destination work spread over the tunnel`.

### Task 7: Wire the preload into the warp and the host loop

**Files:**
- Modify: `engine/appc/warp.py`:
  - `configure_warp_hooks` gains `preload_begin=None, preload_ready=None, preload_replan=None, preload_end=None, preload_pending=None`.
  - `_WarpDepartAction._do_play` calls `preload_begin(dest_set_name)` for the player only.
  - `_MissionChangePoint._do_play` calls `preload_replan()` after `mission_change.change`.
  - `_HoldUntilAction` waits.
  - `WarpSequence.Completed`/`Abort` call `preload_end()` for the player's warp.
- Modify: `engine/host_loop.py`:
  - Configure the hooks next to the existing `_warp.configure_warp_hooks(` call (~10221), with `haze_enabled=lambda: _system_nebula_gate(r)` and the other `Preload` deps built from `_load_planet_model(r, _planet_model_path(name), cache=controller)`, `_load_runtime_ship_model` + `hull_volume.prewarm_for_model`, and `_iter_ships_in_set(App.g_kSetManager.GetSet(name))`.
  - Call `warp_preload.active().step()` once per frame, inside `frame_profiler.scope("warp.preload")`, in the sim phase after the gameloop ticks.
  - Planet models come from `resolve.for_set(dest)` → map bodies with `orbits is not None` → `body.appearance.model`.
- Test: `tests/unit/test_warp_preload_hold.py`; keep `tests/integration/test_campaign_warp_transitions.py` and `tests/integration/test_in_system_warp_e2e.py` green

**Interfaces:**
- Consumes: `warp_preload.begin/active/end`, `Preload.ready/replan/pending` (Task 6).
- `_HoldUntilAction` constants: `PRELOAD_CAP_S = 30.0`, `PRELOAD_POLL_S = 0.05` (module-level in `warp.py`).
- Hold algorithm: `Play` → `_complete_after(remaining, on_elapsed=self._floor_reached, mgr=App.g_kTimerManager)`. `_floor_reached` records `App.g_kRealtimeTimerManager.get_time()` and calls `_poll`. `_poll` → `Completed()` if the ship is not the player, or no `preload_ready` hook, or `preload_ready()`. If the cap has elapsed, it prints `[warp-preload] late: <", ".join(preload_pending())>` to stderr and calls `Completed()`. Otherwise `_complete_after(PRELOAD_POLL_S, on_elapsed=self._poll, mgr=App.g_kRealtimeTimerManager)`.

- [ ] **Step 1: Write failing tests** in `test_warp_preload_hold.py`, driving timers with the same game/real timer managers the warp unit tests use:
  - `test_hold_completes_at_floor_when_ready`.
  - `test_hold_waits_past_floor_until_ready`: ready flips True at floor+2 s → completes then, not before.
  - `test_hold_releases_at_cap_and_logs_late` (capsys: `[warp-preload] late:`).
  - `test_npc_warp_never_waits`: hooks report not-ready; an NPC's hold completes at its floor.
  - `test_no_hooks_behaves_as_today`.
  - `test_abort_ends_the_preload` (Review Focus 1): Abort the sequence while waiting → `preload_end` called once; no further `_poll` fires.
  - `test_mission_change_replans`: `_MissionChangePoint` with a mission name → `preload_replan` called after `mission_change.change` (monkeypatch `change`).
  - `test_depart_begins_for_player_only`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_warp_preload_hold.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `warp.py` and the host wiring.
- [ ] **Step 4: Run** the new tests and both warp integration suites. Expected: PASS.
- [ ] **Step 5: Commit** `feat(warp): the tunnel waits for the destination preload (floor + 30 s cap)`.
- [ ] **Step 6: CHECKPOINT.** Run `scripts/check_tests.sh`; it must exit 0. Then give Mark the Task 1 launch command with `logs/warp-spikes-3.log`, and ask for the same route **without** `--developer`, plus one run with it. He also confirms the tunnel looks smooth. Arrival frames must be < 250 ms (the haze still only runs under `--developer` until Task 8; the `--developer` run proves its cache and prebuild). If a tunnel frame is ≥ 100 ms and is not `warp.mission_change`, fix it before Task 8.

### Task 8: Turn the system haze on for production

**Files:**
- Modify: `engine/host_loop.py`. `_system_nebula_gate(r)` becomes `r.volumetric_nebulae_enabled()`. Drop the `dev_mode.is_enabled()` early return in `_push_system_nebula`. Rewrite the "developer-only" docstrings.
- Modify: `native/src/renderer/{include/renderer/system_nebula_pass.h,system_nebula_pass.cc}`: `plan_nebula_draws(bool volumetric_setting, bool has_profile, bool have_volumes, bool have_wake)` (the `developer` parameter is removed). Update its call in `native/src/host/host_bindings.cc` `frame()`, and the `set_system_nebula_profile` docstring.
- Modify: `engine/renderer.py` (`set_system_nebula_profile` docstring). The preload's `haze_enabled` dep is `lambda: _system_nebula_gate(r)` (Task 7), so it follows this change with no edit.
- Modify docs: `docs/superpowers/specs/2026-09-29-system-nebula-render-design.md` (Status: shipped to production 2026-10-16, Mark), `docs/superpowers/specs/2026-09-23-radial-system-profile-design.md` (runtime table row), the CLAUDE.md "Radial system profile" row ("developer-only pending live approval" → "on in production; follows Volumetric Nebulae / Improved Space").
- Test: `tests/unit/test_system_nebula_feed.py`, `native/tests/renderer/system_nebula_pass_test.cc`

**Interfaces:** no new names. Production look = `dev_nebula_dials.DEFAULTS` (veil 0.15, …). The dial keys stay registered only under `--developer` (verify; do not change).

- [ ] **Step 1: Rewrite the production tests to the new contract.** Do not delete them. The ones that assert production makes no call (`test_gate_closed_dev_mode_off_never_touches_frames_or_pushes`, `test_production_makes_no_native_call_after_a_mission_swap`, `test_production_never_pushes_system_nebula_flashes`, `test_production_godray_list_is_exactly_the_flashes`) become: production + setting on pushes the profile, flashes and star godray exactly as developer mode does; production + setting off makes no renderer call. Add `test_production_pushes_default_dials` (g/floor/k_sys from `DEFAULTS`). Update `plan_nebula_draws` gtests to the 4-arg signature, and add `SystemDrawsWithoutDeveloper`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** the gate changes and docs.
- [ ] **Step 4: Run** `tests/unit/test_system_nebula_feed.py`, the `SystemNebula*` gtests, and `tests/docs/`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(haze): system-scale nebula on in production`.

### Task 9: Acceptance

- [ ] **Step 1:** `scripts/check_tests.sh` exits 0.
- [ ] **Step 2:** Hand Mark the launch command with `logs/warp-spikes-4.log`. Ask for the route once with and once without `--developer`, plus one E1M1 → E1M2 warp.
- [ ] **Step 3:** Read the logs against the spec's Acceptance section:
  - no arrival frame ≥ 250 ms;
  - no tunnel frame ≥ 100 ms other than `warp.mission_change`;
  - no `[warp-preload] late:` line in his terminal output (ask him).
  Write the measured table into the spec, and set its Status to implemented, with a "live-verified" line only after Mark confirms it feels seamless.
- [ ] **Step 4:** Update `docs/engine/frame-profiler.md`'s spike-capture scope list (`warp.preload`, Task 1's names). Commit `docs: warp tunnel preload — measured acceptance`.
