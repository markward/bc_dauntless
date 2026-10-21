# Layered damage production, phase 2: near/far switch and the cost rule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a damaged ship cost no more than twice the same ship undamaged. To get there:
- Draw rooms only for ships within 20 GU of the drawing camera, and on the viewscreen only for its target. Holes further out are painted as wreckage instead.
- Cut the CPU and GPU work of the passes that remain.

**Architecture:**
- **Interior policy.** A per-render interior policy decides, per instance, whether its holes get the marking and interior draws (near) or are painted in place by the plating shader (far). It holds the camera, the 20 GU limit, and whether this render is the viewscreen with a target. The main view and the viewscreen render set their own policy.
- **CPU cost:**
  - The marking draw gets a lean path in place of the full `draw_model`.
  - `Shader::set_*` caches uniform locations for every program.
  - Each mesh uploads only the damage records near it.
  - The interior walk tests deck breaks against a CPU-chosen subset.
- **Fill volume.** It is loaded on a background worker when the ship loads, not on its first cut.

**Tech Stack:** C++20, GLSL 410 core, pybind11, Python 3, GoogleTest, pytest, CMake (Debug tree `build/` in the worktree).

**Spec:** `docs/superpowers/specs/2026-10-21-layered-hull-damage-production-design.md`. This plan covers:
- goal 3 (near interior, far wreckage, blown-through cut at any distance, viewscreen target only);
- §3, the perf rule and its levers;
- §7, the driver rules.

Carry-overs from phase 1's reviews (memory `project_layered_hull_damage`) are folded into Tasks 3 and 5.

**Moved to phase 4 (proposed to Mark on 2026-10-21; phase 2 is the cost work):** structure parts at model load with a disk cache, and articulation.

## Global Constraints

- **Git.** Worktree `.claude/worktrees/damage-redesign`, branch `spike/damage-redesign`.
  - Never run `git checkout --`, `restore`, `stash`, `clean`, `reset --hard` or `add -A/.`.
  - Stage explicit paths. Commit with `git commit -F <file>`, ending `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **Tests.** Focused test files only, with explicit file lists: never a whole suite, never the gate.
  - Pytest: `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider <files>`.
  - GL: `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" build/native/tests/renderer/renderer_tests --gtest_filter=...`.
- **Shader edits.** Any edit under `native/src/renderer/shaders/` needs `cmake -B build -S .` before `cmake --build build -j`.
  - Grep the matching `build/native/src/renderer/embedded_*.h` afterwards.
  - Rebuild `dauntless` and `_dauntless_host`.
- **`opaque.frag` rules.**
  - It is optimizer-fragile on this Mac: never add a sampler, never `return` early from its PLATING main (single discards only).
  - Every hunk against `1fca3177d` stays inside `#ifdef PLATING`.
  - After any edit, run `HullClipTest.*` and `ScuffTest.*`.
- **Units.** Renderer world space is GU (1 GU = 175 m), render-relative (`Instance::world`). Body frame is model units.
- **The perf rule:** a damaged ship costs no more than double the same ship undamaged.
  - Measured at the pass level as `space.opaque` + `space.hull_interior`.
  - The damaged-alive and dying DP windows are each compared against the undamaged window of the same run.
  - CPU comes from a CPU-only run; GPU from a GPU-focus run, which is attribution only.
- **The look must not change for a near ship.** The only visible change is the far wreckage paint.

## Review Focus

1. **A ship straddling 20 GU.** Each ship takes one near/far decision per render, so the same ship never gets both a mark and a far paint in one render. Pinned in Task 1 (`OneDecisionPerInstancePerRender`).
2. **A ship blown clear through, far away,** still shows what is behind it (the cut holds at any distance). Pinned in Task 1 (`FarBlownThroughStillCuts`).
3. **The viewscreen with no target** shows no rooms at all, and the main view is unaffected by the viewscreen's policy. Pinned in Task 1 (`ViewscreenWithoutTargetDrawsNoInterior`, `MainViewPolicyRestoredAfterViewscreen`).
4. **An articulated hull** (node overrides present) must not lose damage on a moved part through the per-mesh subset. Pinned in Task 3 (`ArticulatedDrawUsesFullList`).
5. **A ship whose fill volume is still loading.** Its holes still show rooms, with no left-the-ship test, never see-through. Pinned in Task 4 (`InteriorDrawsWhileFillIsLoading`).

---

### Task 1: Interior policy — near rooms, far wreckage, viewscreen target

**Files:**
- Create: `native/src/renderer/include/renderer/hull_interior_policy.h`, `native/src/renderer/hull_interior_policy.cc` (add to the renderer CMake list)
- Modify:
  - `native/src/renderer/frame.cc`, `native/src/renderer/include/renderer/frame.h`: the policy setter, `submit_opaque_in_pass`, `submit_plating_interior`.
  - `native/src/renderer/shaders/opaque.frag`: PLATING only.
  - `native/src/host/host_bindings.cc`: `render_space_geometry` sets the policy, plus a `set_viewscreen_target_instance` binding.
  - `engine/renderer.py`, `engine/host_loop.py`: `_viewscreen_scene_feed`'s push also pushes the target's instance id, or `-1`.
- Test: `native/tests/renderer/hull_interior_test.cc`, `native/tests/renderer/plating_render_test.cc`, `tests/unit/test_viewscreen_interior_target.py` (new)

**Interfaces:**
- Produces:
  ```cpp
  namespace renderer {
  struct InteriorPolicy {
      float near_gu = 20.0f;                 // rooms only within this many GU of the camera
      bool viewscreen = false;               // this render is the bridge viewscreen feed
      std::optional<scenegraph::InstanceId> viewscreen_target;  // its target, if any
  };
  // Near = rooms for this instance in this render. Distance is from the camera
  // eye to the instance's bounding sphere surface (model bounding radius x scale),
  // render space. On the viewscreen only the target can be near, at any distance.
  bool interior_is_near(const scenegraph::Instance&, float model_radius,
                        const scenegraph::Camera&, const InteriorPolicy&);
  }
  ```
  - `FrameSubmitter::set_interior_policy(const InteriorPolicy&)` and `interior_policy()`.
  - `submit_opaque_in_pass` sets the PLATING uniform `u_plating_far` (0 or 1) per plated draw from `interior_is_near`.
  - `submit_plating_interior` marks and draws the interior only for near instances.
  - `int FrameSubmitter::plating_far_draws_last_frame() const`.
  - **Binding.** `set_viewscreen_target_instance(iid: int)`, with -1 for none. `render_space_geometry` sets `{viewscreen = to_viewscreen, viewscreen_target = that id}` before its submits, and `{}` for the main view.
  - **Python.** `host_loop._viewscreen_scene_feed`'s caller pushes the target ship's instance id (from the ship-instances map) through `engine/renderer.py`'s wrapper, or -1 when there is no target.
- **Shader (PLATING).**
  - `uniform int u_plating_far;`.
  - At the existing discard: a hole (`hole == 1`) is cut when `u_plating_far == 0`, or when `plating_w_here > u_plating[24]` (blown through).
  - Otherwise the hole is painted as wreckage. It is shaded on the inside path (`plating_inside = true`, glow killed):
    - **Base:** near-black char, `vec3(0.02)` × (0.7 + 0.3 × noise).
    - **Fires:** room cells (`floor(p / vec3(6.0, 8.67, 2.67))`) hashing below 0.03 add a fire glow, `blackbody(0.6) × 0.8`, to `g_plating_emissive`.
    - **Lit windows:** cells hashing between 0.03 and 0.055 add a cool lit-window glow, `vec3(0.8, 0.88, 1.0) × 0.5`.
  - The mark test stays one discard: `if (cut != (u_plating_mark != 0)) discard;`.

- [ ] **Step 1: Write the failing tests.**
  - **GL** (`hull_interior_test.cc`; the test sets `near_gu` small so the box can be far):
    - `FarHullPaintsHoleAsWreck`: far, the centre is not the clear colour; marks == 0; interiors == 0.
    - `FarBlownThroughStillCuts`: far, deck break 0.01; the centre is the clear colour.
    - `NearHullStillDrawsInterior`: the old `HoleShowsInteriorNotClearColour` result, unchanged.
    - `OneDecisionPerInstancePerRender`: a box straddling `near_gu` gives `marks + far_draws == 1`.
    - `ViewscreenOnlyTargetGetsInterior`: two damaged boxes, viewscreen policy targeting one. Interiors == 1.
    - `ViewscreenWithoutTargetDrawsNoInterior`: interiors == 0.
    - `MainViewPolicyRestoredAfterViewscreen`: a viewscreen-policy render, then a main-policy render of the near box. Interiors == 1.
  - **pytest** (`test_viewscreen_interior_target.py`): with a target, the pushed target id equals that ship's instance id; with none, -1.
- [ ] **Step 2: Reconfigure, build, run** `--gtest_filter='HullInterior*:PlatingRender*'` and the pytest file. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `HullInterior*:PlatingRender*:PlatingDamage*:UnevenBreach*:HullClipTest.*:ScuffTest.*:DecalRenderTest.*:FrameTest.*` and the pytest file. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 2: Cached uniform locations, and a lean marking draw

**Files:**
- Modify:
  - `native/src/renderer/shader.cc`, `native/src/renderer/include/renderer/shader.h`: every `set_*` uses `cached_location`.
  - `native/src/renderer/frame.cc`: a new `draw_plating_mark`; `submit_plating_interior` uses it; `draw_model` loses `plating_mark`.
  - `native/src/renderer/shaders/opaque.frag`: comment only, if any.
- Test: `native/tests/renderer/plating_render_test.cc`, `native/tests/renderer/shader_test.cc` (or the existing shader test file; find it)

**Interfaces:**
- Produces:
  - `Shader::set_*(name, ...)` behaves as before, but looks the location up once per program per name. Missing names stay silent (-1) as today.
  - `void draw_plating_mark(const assets::Model&, const glm::mat4& world, Shader& plating, const plating::DamageList&, const float* params, const std::unordered_map<int, glm::mat4>* node_overrides)`, in `frame.cc`, file-local or declared in `frame.h` if tests need it.
    - It sets only what the PLATING fragment path reads up to and including its discard: the plating block, the parts, `u_ship_world_inv`, `u_plating_mark = 1`, `u_plating_far = 0`, and per mesh `u_model` and `u_node_rest_fix`.
    - It also sets, or neutralises, every uniform that can discard or move pixels before that point.
  - `draw_model` drops its `plating_mark` parameter; every other caller is unchanged.
- **The audit is part of this task.** List in the report every uniform and texture `opaque.frag` reads in `main` before the plating discard, and say for each whether the lean path sets it, neutralises it, or why it cannot matter. Candidates: `u_dither_fade`, `u_coverage_cutout`, the base texture for alpha, `u_carve_*` and `u_hull_field_enabled`, `u_decal_*`, and the impostor and planet defines (not compiled into PLATING).

- [ ] **Step 1: Write the failing tests:**
  - `LeanMarkStampsExactlyTheCutPixels` (`plating_render_test.cc`), on the Ambassador with an Internal record.
    - Draw the plating pass over a known background colour.
    - The cut set is every pixel inside the hull's undamaged silhouette that shows the background.
    - The stencil from `submit_plating_interior` (lean path) equals that set exactly.
  - `SetUniformLooksUpOncePerName`: two `set_float` calls with the same name on one program add one entry to its location cache. Expose a count accessor if needed.
- [ ] **Step 2: Build and run** `--gtest_filter='PlatingRender*:Shader*'`. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Task 1 GL filter plus `Shader*:Pipeline*:BridgePass*:HologramPass*`. These other programs share `Shader`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 3: Records near each mesh, a deck-break subset, no list copy, a pruned cache

**Files:**
- Modify:
  - `native/src/renderer/plating_damage.{h,cc}`: the deck-break subset and mesh bounds.
  - `native/src/renderer/frame.cc`, `native/src/renderer/include/renderer/frame.h`: per-mesh upload, the pointer instead of a copy, pruning.
  - `native/src/renderer/hull_interior_pass.cc`, `native/src/renderer/shaders/hull_interior.frag`: the deck-break subset.
  - `native/src/renderer/aabb.cc`, or `plating_damage.cc`: per-mesh body-frame AABBs.
- Test: `native/tests/renderer/plating_damage_test.cc`, `native/tests/renderer/plating_render_test.cc`, `native/tests/renderer/hull_interior_test.cc`

**Interfaces:**
- Produces:
  - `std::vector<renderer::Aabb> mesh_body_aabbs(const assets::Model&)`: one AABB per mesh in the body frame, at the rest pose. Cached per model handle, like `model_bounding_radius`.
  - `int plating::records_near(const DamageList&, const Aabb& body_box, float margin, std::array<std::uint8_t, kMaxDamage>& out)`: the indices of records whose sphere (`a.w + margin`) touches the box.
    - `margin` is the shader's `plating_margin`: `params[5] + params[6] + params[15] + params[2]`.
  - **`draw_model` plating draws:** per mesh, upload only that mesh's records (`u_dmg_count` and the a, b, c arrays, by count). A mesh with none uploads `u_dmg_count = 0`. With node overrides present, every mesh gets the whole list.
  - **`DeckBreakSet plating::deck_break_subset(const DamageList&, const float* params)`.** It keeps record i when the summed wear of all records whose spheres overlap i's (i included) is at least `params[24] - 1.25 * params[19]`.
    - Why this is exact: if an excluded record k covers a point, every record covering that point overlaps k. So the point's wear is at most k's overlap sum, which is below the threshold, and the point cannot be blown.
    - It is cached alongside the list, under the same revision and params key.
  - **`hull_interior.frag`.**
    - `uniform int u_db_count; uniform int u_db_idx[64];`.
    - The walk's blown-plate test and the far-wall blown-through test use the subset's wear.
    - Shading (soot, room light, char edge) keeps the full list.
  - **Pointer, not a copy.** `submit_opaque_in_pass` passes `&plating_list_for(inst)` to `draw_model`.
  - **Pruning.** `plating_list_cache_` drops ids no longer in the world, once per frame (in `submit_opaque_in_pass`).

- [ ] **Step 1: Write the failing tests:**
  - `RecordsNearSelectsOnlyTouchingSpheres`: a box at the origin with half-size 1, a record at x=5 (reach 3, margin 1, so it touches) and one at x=10 (it does not). The result is `{0}`.
  - `DeckBreakSubsetDropsIsolatedLightRecords`: one record of wear 10 and one isolated record of wear 1, deck break 6, tear noise 0.9. The subset is `{0}`. Then two overlapping records of wear 3 and 3: both are kept.
  - `MeshWithoutNearbyDamageUploadsNothing`: a two-quad model with damage on one quad. Per-mesh upload counts are `{n, 0}`, through a test hook or by drawing the far quad alone and checking it matches the stock image.
  - `ArticulatedDrawUsesFullList`: with node overrides present, every mesh gets the full count.
  - `InteriorSubsetMatchesFullWalk`: the existing interior tests' centre pixels are unchanged with the subset.
  - `ListCachePrunesDestroyedInstances`: after an instance is destroyed and a frame submits, the cache size drops by one.
- [ ] **Step 2: Reconfigure, build, run** `PlatingDamage*:PlatingRender*:HullInterior*`. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Task 2 filters. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 4: Load the fill volume in the background

**Files:**
- Modify:
  - `native/src/renderer/carve_field_cache.cc`, `native/src/renderer/include/renderer/carve_field_cache.h`.
  - `native/src/host/host_bindings.cc`: a `prefetch_hull_fill(model_handle)` binding.
  - `engine/renderer.py`.
  - `engine/appc/hull_volume.py`: `prewarm_for_model` also calls the prefetch.
- Test: `native/tests/renderer/hull_interior_test.cc` (or a new `carve_field_cache_test.cc`), `tests/unit/test_hull_volume_prewarm.py` (find the existing test for `prewarm_for_model`, or create it)

**Interfaces:**
- Produces:
  - `void CarveFieldCache::prefetch(const std::filesystem::path& source)` starts the CPU load (`SourceVolumeCache::get_for_hull`'s work) on a single background worker, with one job at a time and later sources queued.
  - `get_for_source(source)` never blocks. It returns `nullptr` while the CPU volume is not ready, starting the prefetch if none is running. Once it is ready, it uploads the GL texture on the calling (render) thread and returns the entry.
  - A failure is still cached as "no fill".
  - The worker must not touch `SourceVolumeCache`'s map unguarded. Either give the worker its own decode call and hand back the volume, or guard the map.
  - **Binding.** `prefetch_hull_fill(model_handle)`, a no-op for an unknown handle or an empty source.
  - **Python.** `hull_volume.prewarm_for_model(ship, handle)` calls `renderer.prefetch_hull_fill(handle)`. It already runs at realize and in the warp preload's `load_ship`.

- [ ] **Step 1: Write the failing tests:**
  - `FillPrefetchDoesNotBlockAndBecomesReady`: `get_for_source` on a fresh cache returns `nullptr` straight away (under 50 ms on the Ambassador). Polling it every 10 ms returns an entry with `tex3d != 0` within 10 s.
  - `InteriorDrawsWhileFillIsLoading`: a hole drawn while the fill is not ready is not the clear colour, so rooms show with no left-the-ship test.
  - **pytest:** `prewarm_for_model` calls `renderer.prefetch_hull_fill` with the handle.
- [ ] **Step 2: Build and run** the filter and the pytest file. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the filters plus `BreachPass*`, which also reads this cache, and the pytest file. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 5: Test doubles and the merge-factor twin

**Files:**
- Modify:
  - `tests/unit/test_combat_cheats.py`, `tests/integration/test_combat_routes_through_host_io.py`, `tests/integration/test_damage_severity_sequence.py`: their fakes also fake `hull_damage_add` and `hull_damage_add_body`.
  - `tests/host/test_render_space_feeds.py`: its assertion set includes `hull_damage_add` where a torpedo hits the hull.
  - `native/src/host/host_bindings.cc`: a read-only `_test_only_hull_damage_constants()` returning `{"merge_factor": kMergeFactor, "capacity": kCapacity}`, following the `_test_only_*` convention.
- Test: `tests/host/test_hull_damage_bindings.py` gets `test_python_merge_factor_matches_native`.

- [ ] **Step 1: Write the failing test** `test_python_merge_factor_matches_native`: `hull_wear.MERGE_FACTOR == _h._test_only_hull_damage_constants()["merge_factor"]`. Also tighten `test_render_space_feeds.py`'s assertion. Run both; expect FAIL.
- [ ] **Step 2: Implement** the binding and the fakes. Rebuild `_dauntless_host`.
- [ ] **Step 3: Run** the five files. Expect PASS.
- [ ] **Step 4: Commit.**

### Task 6: Measure against the rule

**Files:**
- Modify: `docs/engine/perf-register.md` (new C-/SIG- rows, the P-12 verdict); the design spec §3 only if the rule is met or knowingly missed.

- [ ] **Step 1: Captures (machine idle; `uptime` in each row).** The DP command, four runs:
  - GPU-focus `space.opaque,space.carve_stencil,space.breach,space.hull_interior` and CPU-only.
  - Each at the default distance and at `DAUNTLESS_DAMAGE_PREVIEW_DISTANCE_GU=1.5`.
  - All with `DAUNTLESS_DEV_SCREENSHOT_AFTER_S=15` and a screenshot.
  - The camera sits about 14 GU behind the player. Confirm from the screenshots and the `space.hull_interior` numbers which runs drew rooms (near) and which painted wreckage (far), and say so.
- [ ] **Step 2: Record** per window (undamaged / alive / dying) `space.opaque`, `space.hull_interior` and their sum, CPU and GPU, plus the ratio to the undamaged window.
  - State plainly whether each ratio is at or under 2.0.
  - Compare against C-108 and C-109.
- [ ] **Step 3: Verdict in P-12:**
  - met;
  - or missed by how much, which window, and the largest remaining cost centre (from the GPU-focus attribution).

  Do not tune to the rule without recording it.
- [ ] **Step 4: Commit** the docs.
