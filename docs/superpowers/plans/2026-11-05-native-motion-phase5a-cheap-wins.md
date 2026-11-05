# Native Motion Phase 5a: Cheap Single-Thread Wins — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut main-thread time at 64 ships before the render thread is built: stop drawing hulls no camera or shadow can see, find and cut the contact list's per-frame cost, and try Apple's multithreaded GL engine.

**Architecture:** One sphere-in-frustum test, shared by the opaque hull submit (every camera, so the main view and the viewscreen feed) and the shadow caster submit, behind counters the frame profiler prints. The contact list gets sub-scopes, then a fix for whichever part costs most. The Mac GL engine is an env-gated experiment, measured in Task 5.

**Tech Stack:** C++20 renderer (`native/src/renderer/`), pybind host bindings, Python 3.11 engine, gtest + pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md` §5.5 (phase 5, threading). Phase 5a is not in the spec. Mark agreed it in chat on 2026-11-04 (below), so rulings made without a spec section are provisional.

## Why this phase (the evidence)

Release build, 64 ships, headless 1280×720 (`~/Documents/dauntless-perf/p5-release-play-cs64-*-20261104-2207.log`, plus a `sample` of the main thread):

- Exterior view: 20.8 ms a frame, all of it CPU on one thread. The GPU takes 4.7 ms.
- Python takes 12.1 ms of the frame; `ui.contacts` alone is 1.1 ms.
- Native render CPU is 8.7 ms, of which `space.opaque` is 4.7 ms and `shadow` 0.9 ms.
- About 80% of `space.opaque` is inside Apple's `glDrawElements`. That cost is per draw: the driver copies the default uniform block (memmove) and validates the bound textures.
- No hull is frustum-culled (`host_bindings.cc` says so above `space.opaque`). In bridge view the 640×360 viewscreen feed alone costs 4.4 ms.

Decisions:
- **Merging meshes is out.** The per-draw cost comes from state, not from how many meshes there are. Merging would also fight per-mesh features: posed-owner damage filtering, structure parts, the name-cut fix, and articulated nodes.
- **Moving the uniform arrays into a UBO is deferred.** Task 5 measures what is left after the cull and decides whether it becomes phase 5b.

## Global Constraints

- Work on branch `ws/motion-phase5a` in `.claude/worktrees/native-motion`, cut from main `48d782c23`. The branch merges into `project/native-motion-and-proximity`.
- Never run the gate or a whole pytest or ctest suite. Run only the focused tests a task names (CLAUDE.md "Test gate").
- No destructive git, and stage files with explicit paths (CLAUDE.md "Shared checkout").
- Production pixels must stay identical. The cull may only drop a hull whose bounding sphere is wholly outside the camera's (or the shadow light's) frustum.
- `opaque.frag`: no new sampler, no early return (CLAUDE.md, Layered hull damage).
- Build with `cmake --build build -j` from the worktree root. Never run cmake inside `native/`, and never change `CMAKE_BUILD_TYPE`.
- Benchmarks run only in Task 5. Mark has cleared the machine for benchmarking.

## Review Focus

1. **An articulated part swung outside the rest-pose sphere** (a rigged hull's nacelle) must not vanish at the screen edge. The rigged slack in Task 2 covers this; Task 2 Step 1 pins it.
2. **A model with a mesh that has no bound** (a parentless non-root node drawn at identity, or a mesh without CPU data) must never be culled. Task 2 Step 1 pins it.
3. **The viewscreen feed and the main view cull against their own cameras**, not a shared one. Task 2 Step 1 calls the submit with two different cameras.
4. **A scaled hull** (E1M2's `SetScale(3)` rocks, or the geosphere planets) is culled by its scaled radius. Task 2 Step 1 pins it.
5. **A shadow caster outside the view frustum but inside the light volume** must still cast. The shadow cull uses the light's matrix, never the camera's. Task 2 Step 1 pins it.

---

### Task 1: Hull draw counters in the frame profiler

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h` (add `HullDrawStats`, the accessors, and a `stats` parameter on `submit_shadow_depth`)
- Modify: `native/src/renderer/frame.cc` (count in `submit_opaque_in_pass` and `submit_shadow_depth`)
- Modify: `native/src/host/host_bindings.cc` (reset per frame where the far and rock counters reset; binding `hull_stats`)
- Modify: `engine/renderer.py` (`hull_stats` wrapper, added to the exported-name list)
- Modify: `engine/core/frame_profiler.py` (`hull_summary()`, printed after `rock_summary()`)
- Test: `native/tests/renderer/frame_test.cc`, `tests/unit/test_frame_profiler.py`

**Interfaces:**
- Produces `struct renderer::HullDrawStats { int instances = 0; int culled = 0; int mesh_draws = 0; };`.
- Produces `FrameSubmitter::opaque_stats() const -> const HullDrawStats&` and `FrameSubmitter::reset_opaque_stats()`. The opaque stats accumulate across calls until reset, so they sum every camera in a frame.
- `submit_shadow_depth(world, light, pipeline, lookup, HullDrawStats* stats = nullptr)`: when `stats` is given, it accumulates into it.
- `instances` counts instances that reached the draw (after the existing `far_fade >= 1` skip). `mesh_draws` counts `glDrawElements` calls. `culled` stays 0 until Task 2.
- Produces the Python binding `hull_stats() -> {"opaque_instances", "opaque_culled", "opaque_mesh_draws", "shadow_instances", "shadow_culled", "shadow_mesh_draws"}`, for the last frame.
- Produces `frame_profiler.hull_summary() -> str`, never raising, with the format `"  hulls: opaque %d drawn, %d culled, %d mesh draws | shadow %d drawn, %d culled, %d mesh draws"`. If the binding is missing it prints `"  hulls: unavailable"`.

- [ ] **Step 1: Write the failing tests.**
  - gtest `FrameTest.OpaqueStatsCountInstancesAndMeshDraws`: submit two instances of the fixture model through `submit_opaque_in_pass`. Expect `instances == 2` and `mesh_draws == 2 × <the fixture model's drawn mesh count>`. Call it a second time without a reset and expect `instances == 4`. After `reset_opaque_stats()`, expect all zero.
  - pytest `test_hull_summary_states_both_passes`: monkeypatch `renderer.hull_stats` to return `{"opaque_instances": 40, "opaque_culled": 24, "opaque_mesh_draws": 410, "shadow_instances": 9, "shadow_culled": 55, "shadow_mesh_draws": 80}`. Assert the line contains `"opaque 40 drawn, 24 culled, 410 mesh draws"` and `"shadow 9 drawn, 55 culled, 80 mesh draws"`.
  - pytest `test_hull_summary_never_raises`: when `hull_stats` raises, the line is `"  hulls: unavailable"`.
- [ ] **Step 2: Run them and see them fail.** `cmake --build build -j --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='FrameTest.OpaqueStats*'` (look up the target's real name in `native/tests/renderer/CMakeLists.txt`), then `uv run pytest -q tests/unit/test_frame_profiler.py -k hull_summary`.
- [ ] **Step 3: Implement.** Follow the existing pattern: the far and rock counters reset at frame start and the binding reads them. The host keeps one `HullDrawStats` for the shadow pass and resets it beside `reset_opaque_stats()`.
- [ ] **Step 4: Run both tests, plus `uv run pytest -q tests/unit/test_frame_profiler.py`.** Expect PASS.
- [ ] **Step 5: Commit** `feat(profiler): hull draw counters per pass` (staging only the files above).

### Task 2: Frustum-cull hulls in the opaque and shadow submits

**Files:**
- Create: `native/src/renderer/include/renderer/frustum.h`. Move `struct Frustum` into it unchanged from `native/src/renderer/rock_field_common.h`, which then includes it. The tests can't include the renderer's src directory.
- Create: `native/src/renderer/include/renderer/hull_cull.h`, `native/src/renderer/hull_cull.cc` (add it to the renderer library's CMake source list)
- Modify: `native/src/renderer/frame.cc` (`ModelBounds` gains `bool cullable`; the cull in both submits; the `culled` counts)
- Modify: `native/src/host/host_bindings.cc` (rewrite the comment above `space.opaque` that says no cull runs)
- Test: `native/tests/renderer/hull_cull_test.cc` (new; add it to the renderer tests' CMake), `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Consumes `HullDrawStats` from Task 1.
- Produces, in `hull_cull.h`:
  - `inline constexpr float kHullCullSlack = 1.05f;`
  - `inline constexpr float kHullCullSlackRigged = 2.0f;`
  - `bool hull_cull_enabled();`, read once from `DAUNTLESS_HULL_CULL`: on unless the value is exactly `"0"`.
  - `bool hull_visible(const Frustum& frustum, const glm::mat4& world, const glm::vec3& center_body, float radius_body, bool cullable, bool rigged);`
- `hull_visible` returns true when `!cullable`. Otherwise the world centre is `world × center_body`, and the radius is `radius_body × length(vec3(world[0])) × (rigged ? kHullCullSlackRigged : kHullCullSlack)`. Test the sphere with `frustum.sphere(...)`. Each submit builds its `Frustum` once, before its instance loop. The rock code keeps compiling unchanged, and the Debug bit-exactness comment moves with the struct.
- `cullable` is false when any of `model_mesh_boxes(handle, model)`'s boxes has a half extent of `FLT_MAX`, or when the model has no boxes at all.
- Opaque: test against `camera.proj_matrix() * camera.view_matrix()` right after the `far_fade` skip. A culled instance does `++culled` and returns, before any per-instance work.
- Shadow: test against `light.view_proj`.
- With `hull_cull_enabled()` false, both submits behave exactly as they did before this task.

- [ ] **Step 1: Write the failing tests.**
  - `hull_cull_test.cc`, pure math with no GL:
    - `HullCull.InFrontIsVisible`
    - `HullCull.BehindCameraIsCulled`
    - `HullCull.JustOutsideEdgeWithinSlackIsVisible`: a sphere whose surface is 3% of the radius outside the left plane.
    - `HullCull.RiggedSlackKeepsASwungPart`: a sphere 1.5 radii outside the plane is culled unrigged and visible rigged.
    - `HullCull.UncullableIsAlwaysVisible`: behind the camera, `cullable=false`, expect visible.
    - `HullCull.ScaleGrowsTheRadius`: world scale 3, a centre 2.5 body radii outside the plane, expect visible; at scale 1, culled.
  - `frame_test.cc`:
    - `FrameTest.OpaqueCullsInstanceBehindCamera`: two instances, one in front and one behind. Expect `instances == 1` and `culled == 1`.
    - `FrameTest.OpaqueCullUsesEachCallsCamera`: the same world submitted with a camera facing +Y and then one facing −Y. Each call draws its own front instance, and the summed stats show `instances == 2`, `culled == 2`.
    - `FrameTest.ShadowCullUsesTheLightNotTheCamera`: a caster inside `light.view_proj`'s box but behind the view camera. Expect `submit_shadow_depth` to count it as drawn.
- [ ] **Step 2: Build and run the tests, and see them fail.** Filters `HullCull.*:FrameTest.*Cull*`.
- [ ] **Step 3: Implement `hull_cull.{h,cc}` and wire both submits as the Interfaces block says.**
- [ ] **Step 4: Run the new tests, the whole `FrameTest.*` filter, and the hull-interior and plating render test files** (`--gtest_filter='FrameTest.*:HullInterior*:Plating*'`; check their real suite names). Expect all PASS. If any frame test that does not mention culling now fails, it was relying on drawing an off-screen hull: find out why before you change the test.
- [ ] **Step 5: Commit** `perf(render): frustum-cull hulls in the opaque and shadow submits`.

### Task 3: Contact list — split the cost, then cut the biggest part

**Files:**
- Modify: `engine/host_loop.py` (`_pump_contacts`, and the `ui.contacts` block that calls it)
- Modify: whichever of `engine/appc/perception.py`, `engine/appc/target_menu.py`, `engine/appc/objects.py` (and new `engine/appc/affiliation.py`) Step 2's split names
- Test: `tests/unit/test_target_menu_shim.py` or a new `tests/unit/test_contacts_pump_cost.py`

**Interfaces:**
- Produces profiler sub-scopes under `ui.contacts`:
  - `contacts.perceive` (`perceived_by`)
  - `contacts.push` (`menu.set_contacts`)
  - `contacts.colors` (`menu.ResetAffiliationColors`)
  - `contacts.persist` (`remember_player_target` plus `attempt_persistent_restore`)
- The contract stays: contacts are derived every frame and never stored (the `_pump_contacts` docstring). A fix may skip work whose inputs have not changed. It may never skip deriving.

- [ ] **Step 1: Add the four scopes.** This has no test; scopes are profiler-only. Commit `chore(profiler): split ui.contacts`.
- [ ] **Step 2: Measure the split.** Use the Release build in `.claude/worktrees/release-macos`: run `git -C .claude/worktrees/release-macos checkout --detach <this branch's HEAD>`, then `cmake --build build -j` there. Then run the phase0-runbook §1 capture command, with `DAUNTLESS_DEV_VIEW=exterior` and `DAUNTLESS_PROFILE_FRAMES=1500`, and take the median of reports 3–11. Write the four numbers to the ledger.
- [ ] **Step 3: Fix the biggest part, using this table:**

  | Biggest | Fix |
  |---|---|
  | `contacts.colors` | Affiliation moves ONTO the contact record, so the row colour today and a future filtered view (Mark, 2026-11-05: filter out friendlies/neutrals, sort by name/distance/health — not in this phase) read one value. `ObjectGroup` gains `_generation: int`, bumped by EVERY method that changes its names (`AddName`, `RemoveName`, `RemoveAllNames`, `ObjectGroupWithInfo.AddNameAndInfo`, and any other writer of `_names` — find them all; each gets a test). New `engine/appc/affiliation.py`: `affiliation_of(ship) -> str` answers `resolve_affiliation(ship, current mission)`, memoised by ship name under a cache key `(id(mission), id + _generation of each of the friendly / enemy / neutral groups)` that empties the memo when it changes. `Contact` gains `affiliation: str`, filled in `perceived_by` from `affiliation_of`. The per-frame `ResetAffiliationColors` call in `_pump_contacts` becomes `menu.apply_contact_affiliations()`: for each pushed contact with a row, `SetAffiliation(c.affiliation)` only when it differs from the row's stored token. The SDK-facing `ResetAffiliationColors()` is unchanged: it always recomputes every row through `resolve_affiliation`. |
  | `contacts.push` | `set_contacts` skips a label write only when the label it would write is ALREADY the row's label (compare against the row's current caption state, not last frame's inputs), so an SDK relabel is overwritten exactly as today and nothing assumes a name-only or name-ordered list. `SetVisible()` and `_post_membership_changes()` still run every push, as their docstrings require. |
  | `contacts.perceive` or `contacts.persist` | No fix in this phase. Record the numbers in the ledger as a C++ candidate and go straight to Step 5. |

  For whichever row applies, first write a failing test that proves the skipped work comes back when its input changes:
  - colours: each `ObjectGroup` mutator changes the next frame's `Contact.affiliation` and the row's token; a ship rename does; a new row is coloured on its first push; a mission swap re-resolves; an SDK `ResetAffiliationColors()` still recomputes every row; an unchanged frame calls `resolve_affiliation` zero times;
  - push: an identify, a lost track and an Unknown-number change each rewrite the label.
- [ ] **Step 4: Run the new test plus `uv run pytest -q tests/unit/test_target_menu_shim.py tests/unit/test_target_menu_visibility_derived.py tests/unit/test_target_menu_derived_children.py tests/unit/test_target_menu_nested.py`.** Expect PASS.
- [ ] **Step 5: Commit** `perf(ui): <what was cut>` (or no commit, if the table says there is no fix).

### Task 4: Mac experiment — Apple's multithreaded GL engine

**Files:**
- Modify: `native/src/renderer/window.cc` (after `glfwMakeContextCurrent`)

**Interfaces:**
- On `__APPLE__` only: when `DAUNTLESS_GL_MP_ENGINE` is exactly `"1"`, call `CGLEnable(CGLGetCurrentContext(), kCGLCEMPEngine)` (`<OpenGL/OpenGL.h>`).
- Print one line to stderr: `[gl] multithreaded engine: on`, or `[gl] multithreaded engine: failed (<CGLError int>)`.
- Off by default. Other platforms don't compile it.

- [ ] **Step 1: Implement. There is no unit test,** because this is an env-gated driver switch and Task 5 measures it. Build. Run `./build/native/tests/renderer/renderer_tests --gtest_filter='FrameTest.*'` (the default is off, so nothing changes) and expect PASS.
- [ ] **Step 2: Commit** `perf(mac): DAUNTLESS_GL_MP_ENGINE=1 tries Apple's multithreaded GL engine`.

### Task 5: Measure, record, ask for the live check

**Files:**
- Modify: `docs/reference/engine/perf-register.md` (captures C-304 onward, signal SIG-192 onward)
- Modify: `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md` (a short "§5.5a done" paragraph under §5.5)

- [ ] **Step 1: Build the branch tip in Release** in `.claude/worktrees/release-macos` (detached at the tip, `cmake --build build -j`).
- [ ] **Step 2: Capture with the phase0-runbook §1 command**, 1500 frames, two runs of each configuration:
  - exterior and bridge, as they are;
  - exterior and bridge with `DAUNTLESS_HULL_CULL=0`;
  - exterior with `DAUNTLESS_GL_MP_ENGINE=1`.
  - Name the logs `p5a-<config>-cs64-<view>-<stamp>.log` in `~/Documents/dauntless-perf/`.
- [ ] **Step 3: Score** with `score_p0.py` and a read of the `hulls:` line. The table compares:
  - frame ms
  - `space.opaque`, `viewscreen.rtt`, `shadow`, `ui.contacts`
  - the hull counts
  - against the C-302/C-303 numbers and the 2026-11-04 play logs.
- [ ] **Step 4: Re-run the `sample` profile** of an exterior run (10 s, as on 2026-11-04). Record what share of the main thread `glDrawElements` now takes. That share decides whether a UBO phase (5b) is worth doing.
- [ ] **Step 5: Write the captures and signals into the perf register** (measured tier; Release). Write the "§5.5a done" spec paragraph. Commit `docs(perf): phase 5a captures (SIG-192..)`.
- [ ] **Step 6: Ask Mark for a live check.**
  - A 64-ship fight in both views. Look for hulls popping at the screen edge, and for shadows still landing on the player hull.
  - The LC Intrepid's moving nacelles at the screen edge.
  - E1M2's scaled rocks.
  - Optionally, one run with `DAUNTLESS_GL_MP_ENGINE=1`. Mark decides whether it becomes the default.
