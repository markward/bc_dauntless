# Layered damage: pay only near damage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the layered-damage GPU cost (P-12: hull pass 0.39 → 1.00 ms for one damaged Akira at ~6% of a 4K frame) to near zero away from damage, and leave undamaged hulls on today's shader, measured before and after.

**Architecture:** The CPU builds, per draw, a compact list of only the records that carry wear (torpedo Scorch with wear, Internal blasts). The plating code moves behind `#ifdef PLATING` in `opaque.frag`, compiled as its own program (like `PLANET_SURFACE`) and chosen only for instances whose list is non-empty. Inside it, one cheap "near any damage?" loop runs first; far pixels skip everything, and far back faces discard at once. Double-sided drawing is decided from summed wear, matching the shader.

**Tech Stack:** C++20, GLSL 410 core, GoogleTest, pytest, CMake (Debug tree at `build/`).

**Spec:** `docs/superpowers/specs/2026-10-20-layered-hull-damage-productisation.md` (§2 review items 1, 2, 6; §3.2; §5 step 2). Perf context: `docs/engine/perf-register.md` P-12, SIG-087–SIG-091, scenario DP.

**Not in this plan (step 2b and later):** the permanent damage store (merge-not-evict), the per-ship eligibility cap, and the plating program on paths other than `submit_opaque_in_pass` (those keep the stock program, so they show no plating or holes until then).

## Global Constraints

- Branch `spike/damage-redesign`, worktree `.claude/worktrees/damage-redesign`. Never `git checkout --`, `restore`, `stash`, `clean`, `reset --hard`, `add -A/.`; stage explicit paths; commit with `git commit -F <file>`.
- Focused test files only; never a whole suite, never the gate. Never run pytest with an empty or glob-built file list.
- Any edit under `native/src/renderer/shaders/` needs `cmake -B build -S .` before `cmake --build build -j`; confirm with a grep in `build/native/src/renderer/embedded_opaque_fs.h`. Shader errors appear only at runtime: run the renderer GL tests after every shader change.
- Never add a `sampler3D` (or any new sampler type) to `opaque.frag` (driver miscompile, memory `project_opaque_frag_sampler3d_miscompile`).
- GLSL 410: no SSBOs; arrays are uniforms.
- Perf captures only when the machine is idle (no game, tests or builds), headless, Debug build, logs in `~/Documents/dauntless-perf/`, recorded in `perf-register.md` as new C-/SIG- rows (never edit old ones). GPU-focus runs give attribution, never frame time (M-6).
- Production visuals must not change for undamaged hulls: an instance with no wear-carrying record draws with the unmodified stock program.

## Review Focus

1. **Undamaged hull** — identical pixels to the stock program (no plating program selected). Pinned in Task 4 (`UndamagedHullUsesTheStockProgramPixels`).
2. **Ship with only phaser glow or collision scrapes** — no wear records, so stock program, no extra cost. Pinned in Task 2 (`HeatGlowAndScuffNeverEnterTheList`).
3. **Two overlapping records whose wear only sums past breach** — must draw double-sided (review item 1). Pinned in Task 2 (`SummedWearTurnsDoubleSidedOn`).
4. **Back face far from any damage on a double-sided ship** — discarded, so open geometry elsewhere looks as before (review item 2). Pinned in Task 4 (`FarBackFaceIsDiscarded`).
5. **Hull with more than 12 detected parts** — keeps the largest 12 (review item 6). Pinned in Task 2 (`PartsComeBackLargestFirst`).

---

### Task 1: Close-up DP scenario and the "before" captures

**Files:**
- Modify: `engine/dev_missions/damage_preview.py` (the `pWreck.SetTranslateXYZ(0.0, 6.0, 0.0)` line)
- Test: `tests/unit/test_damage_preview_impulse_steps.py`
- Modify: `docs/engine/perf-register.md` (DP scenario text, captures, signals)

**Interfaces:**
- Produces: `damage_preview._wreck_distance_gu() -> float`, read from `DAUNTLESS_DAMAGE_PREVIEW_DISTANCE_GU` (default 6.0, minimum 1.5; junk → 6.0).

- [ ] **Step 1: Write the failing test** `test_wreck_distance_comes_from_the_environment`: env `2.5` → `2.5`; `0.2` → `1.5`; `junk` → `6.0`; unset → `6.0`.
- [ ] **Step 2: Run** `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider tests/unit/test_damage_preview_impulse_steps.py` — expect FAIL (no `_wreck_distance_gu`).
- [ ] **Step 3: Implement** `_wreck_distance_gu()` and use it for the wreck's Y in `Initialize`.
- [ ] **Step 4: Run the test** — expect PASS.
- [ ] **Step 5: Find the close-up distance offline.** No game launch: pick the distance where the Akira spans about 60–80% of a 4K frame's height, from its bounding radius (`build/native/tools/dump_bounds -gu` on `Akira.nif`, as `damage_preview.py`'s scuff comment does) and the exterior camera's FOV (`settings.json` `fov_deg`). Record the chosen value in the DP scenario text.
- [ ] **Step 6: "Before" captures (machine idle).** Four runs, the DP command from `perf-register.md` with `DAUNTLESS_PROFILE_GPU_FOCUS=space.opaque,space.carve_stencil,space.breach`: Layered and Classic (`DAUNTLESS_HULL_CARVING=1 DAUNTLESS_PLATING=0`), each at the default distance and at the close-up distance. Add `DAUNTLESS_DEV_SCREENSHOT` for the close-up runs and check that the Akira fills the frame.
- [ ] **Step 7: Record** C- rows and one signal per window (damaged-alive, dying) with `space.opaque`/`space.breach` GPU means. This tests SIG-091 (the ~10 ms close-up extrapolation) directly.
- [ ] **Step 8: Commit** `engine/dev_missions/damage_preview.py`, the test, `docs/engine/perf-register.md`.

### Task 2: CPU damage list, summed tear gate, parts largest first

**Files:**
- Create: `native/src/renderer/include/renderer/plating_damage.h`, `native/src/renderer/plating_damage.cc` (add to `native/src/renderer/CMakeLists.txt`)
- Modify: `native/src/voxel/src/structure_parts.cc` (final part order)
- Test: `native/tests/renderer/plating_damage_test.cc` (add to `native/tests/renderer/CMakeLists.txt`), `native/tests/voxel/structure_parts_test.cc`

**Interfaces:**
- Produces:
  ```cpp
  namespace renderer::plating {
  constexpr int kMaxDamage = 24;
  struct DamageList {
      int count = 0;
      glm::vec4 a[kMaxDamage];   // centre_body.xyz, reach (model units)
      glm::vec4 b[kMaxDamage];   // normal_body.xyz (zero for Internal), wear
      glm::vec4 c[kMaxDamage];   // kind (1 = Scorch, 3 = Internal), 0, 0, 0
      bool torn_possible = false;
  };
  // params = dauntless_plating::g_params (24 floats).
  DamageList build_damage_list(const scenegraph::DamageDecalRing& ring,
                               const float* params);
  }
  ```
  `reach` = `radius * params[7]` for Scorch, `radius` for Internal. Only active Scorch with `wear > 0` and Internal records enter. `torn_possible` = (sum of all listed wear) ≥ `params[16] - 0.75f * params[19]` (breach wear minus the shader's largest tear-noise lift, `plating_hole`'s `(n - 0.5) * tear_noise * 1.5`).
  `voxel::detect_structure_parts` returns parts sorted by `voxels`, largest first.

- [ ] **Step 1: Write the failing tests** in `plating_damage_test.cc`:
  - `HeatGlowAndScuffNeverEnterTheList`: ring with one HeatGlow and one Scuff → `count == 0`, `torn_possible == false`.
  - `ScorchReachIsRadiusTimesReachParam`: one Scorch radius 50, wear 1, `params[7] = 0.4` → `a[0].w == 20`, `b[0].w == 1`, `c[0].x == 1`.
  - `InternalKeepsItsRadiusAndHasNoFacing`: Internal radius 30, wear 10 → `a[0].w == 30`, `b[0].xyz == 0`, `c[0].x == 3`.
  - `SummedWearTurnsDoubleSidedOn`: two Internal records wear 2.5 each, `params[16] = 4.5`, `params[19] = 0.9` → `torn_possible`; one alone → not.
  - `ZeroWearScorchIsSkipped`.
  In `structure_parts_test.cc`: `PartsComeBackLargestFirst` — slab + bar from the existing test → `parts[0].voxels >= parts[1].voxels`.
- [ ] **Step 2: Build and run** `build/native/tests/renderer/renderer_tests --gtest_filter='PlatingDamage*'` and the voxel test binary `--gtest_filter='StructureParts.*'` — expect compile failure / FAIL.
- [ ] **Step 3: Implement** `build_damage_list` and the sort (`std::stable_sort` on `voxels` descending, after the final fit; relabel `seg.label` to match).
- [ ] **Step 4: Run both filters** — expect PASS.
- [ ] **Step 5: Commit.**

### Task 3: The `PLATING` shader variant and the near-damage early-out

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag` (every `SPIKE (damage redesign)` block)
- Modify: `native/src/renderer/pipeline.cc`, `native/src/renderer/include/renderer/pipeline.h`

**Interfaces:**
- Produces: `Pipeline::plating_shader()` — `opaque_vs` + `with_define(opaque_fs, "PLATING")`, with the same fixed sampler units as `opaque_` (add it to the unit-assignment loop in `pipeline.cc`).
- Shader uniforms (PLATING only): `u_dmg_count`, `u_dmg_a[24]`, `u_dmg_b[24]`, `u_dmg_c[24]` (layout of `DamageList`), `u_plating[24]`, `u_plating_two_sided`, `u_part_*`.

- [ ] **Step 1: Gate.** Wrap every plating uniform, global, function and call site in `#ifdef PLATING`, including the soot multiplier in `apply_damage_decals`, the `glow_kill` and `g_plating_emissive` lines, and the `apply_scuffs`/plating guards in `main`. Without the define the source must be the pre-spike shader apart from the exact class-2 filter in `apply_scuffs`. Check: `git diff 9da1178c3 -- native/src/renderer/shaders/opaque.frag` shows only `#ifdef PLATING` blocks plus that one filter line.
- [ ] **Step 2: Compact loops.** `plating_wear`, `plating_internal` and `plating_wear_grad` loop over `u_dmg_*` instead of `u_decal_*`, with no class filters except `c.x` (1 vs 3).
- [ ] **Step 3: Early-out.** At the top of the plating section in `main`, compute once `bool plating_near` = any record with `length(p_body - a.xyz) < a.w + kPlatingMargin`, where `kPlatingMargin = u_plating[5] + u_plating[6] + u_plating[15] + u_plating[2]` (plate depth + rib depth + bend + one primary spacing: the furthest any march or chart sample reaches). If `!plating_near`: back face → `discard`; front face → skip `plating_hole` and `apply_plating`.
- [ ] **Step 4: Compute `plating_wear(p_body, n_body)` and `plating_internal(p_body)` once in `main`, and pass them into `plating_hole` and `apply_plating`** in place of their own calls at `p_body`.
- [ ] **Step 5: Reconfigure, build, grep** `plating_near` in `build/native/src/renderer/embedded_opaque_fs.h` (it must appear inside `#ifdef PLATING`).
- [ ] **Step 6: Run** `build/native/tests/renderer/renderer_tests --gtest_filter='DecalRenderTest.*:ScuffTest.*:PipelineTest.*:HullClipTest.*:RimFresnelTest.*:FrameTest.*'` — expect all PASS (stock program, no plating).
- [ ] **Step 7: Commit.**

### Task 4: Choose the program per draw, upload only for plating draws

**Files:**
- Modify: `native/src/renderer/frame.cc` (`submit_opaque_in_pass`; `draw_model`'s SPIKE plating block)
- Test: `native/tests/renderer/plating_render_test.cc` (new; add to `native/tests/renderer/CMakeLists.txt`; reuse the GL setup and saucer model of `native/tests/renderer/decal_render_test.cc`)

**Interfaces:**
- Consumes: `renderer::plating::build_damage_list` (Task 2), `Pipeline::plating_shader()` (Task 3).
- Produces: `bool renderer::plating::wants_plating(const DamageList&, const float* params)` = `params[0] > 0.5f && list.count > 0`; `draw_model` gains a trailing `const plating::DamageList* plating = nullptr` (nullptr = stock draw, no plating uniforms touched).

- [ ] **Step 1: Write the failing GL tests** in `plating_render_test.cc`:
  - `UndamagedHullUsesTheStockProgramPixels`: draw the saucer through the frame submitter with an empty ring, then with plating enabled and one HeatGlow record → both images equal the stock-program image byte for byte.
  - `TornCentreIsDiscarded`: one Internal record at a surface point, radius 30 mu, wear 10 → the centre pixel shows the clear colour (or the inside wall), not the hull.
  - `FarFromDamagePixelMatchesStock`: same draw; a pixel more than `reach + margin` away from the record equals the undamaged image there.
  - `FarBackFaceIsDiscarded`: a single-sided quad behind the saucer facing away, with the ship double-sided → its pixels stay the clear colour away from the record.
- [ ] **Step 2: Build and run** `--gtest_filter='PlatingRender*'` — expect FAIL.
- [ ] **Step 3: Implement.** In `submit_opaque_in_pass`, per instance: build the list (Task 2); if `wants_plating`, use `pipeline.plating_shader()` (configured with `configure_common` the first time it is needed in the frame, like `planet_shader()`) and pass the list to `draw_model`; otherwise use the stock program and upload nothing for plating. Move the u_plating / parts / two-sided uploads behind that choice; `torn_possible` now comes from the list. Cache uniform locations for the plating uniforms on first use.
- [ ] **Step 4: Run** `--gtest_filter='PlatingRender*:DecalRenderTest.*:ScuffTest.*:PipelineTest.*:HullClipTest.*:FrameTest.*'` — expect PASS.
- [ ] **Step 5: Python checks** `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider tests/unit/test_plating_dials.py tests/unit/test_internal_blast.py tests/unit/test_visible_damage.py tests/unit/test_damage_preview_impulse_steps.py` — expect PASS.
- [ ] **Step 6: Commit.**

### Task 5: "After" captures and the verdict

**Files:**
- Modify: `docs/engine/perf-register.md`, `docs/superpowers/specs/2026-10-20-layered-hull-damage-productisation.md` (§5 step 2 row)

- [ ] **Step 1: Repeat Task 1 Step 6** on the new build (same four runs, same commands). Also check the close-up Layered screenshot against Task 1's: the damage must look the same.
- [ ] **Step 2: Record** C- rows and signals: damaged-alive and dying `space.opaque` GPU, before vs after, at both distances. Update P-12's status and next step.
- [ ] **Step 3: Acceptance.** At the default distance, damaged-alive Layered `space.opaque` GPU is within 0.15 ms of Classic (0.39 ms in SIG-088). At close-up, Layered is no more than 2× Classic. If either misses, say so in P-12 with the numbers; do not tune to the target without recording it.
- [ ] **Step 4: Commit** the docs.
