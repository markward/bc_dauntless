# Layered damage: uneven breaches and an interior behind every hole — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make wear eat through the ribs unevenly, and make every hole in the hull show decks and rooms instead of empty space, so neither a torpedo hole (Sovereign) nor a blown-out nacelle (Akira) shows the scene behind the ship.

**Architecture:**
- **Uneven breach.** The breach threshold becomes `breach × toughness(panel) + lumps(p)`. Toughness is a hashed per-panel factor; lumps is low-frequency noise at hole scale. The cut and the painted inner-hull tear both read this one function.
- **Cut marking.** The plating draw goes back to front faces only, the way the old carve worked: opaque draw → stencil-marking draw → interior draw under the stencil.
  - For each damaged hull that can tear, a marking draw of the plating program writes a stencil value unique to that hull, exactly where the hull is cut.
  - An interior draw of the same mesh then shades only those pixels. It walks a body-frame deck-and-room lattice ported from the breach-interior spike's `ih_shade`.
  - A plate is skipped where interior wear has destroyed it. Where the ray leaves the hull's fill volume, the far wall's inside face is drawn instead. Only past the deck-break wear does the ray see out of the ship.

**Tech Stack:** C++20, GLSL 410 core, GoogleTest, pytest, CMake (Debug tree at `build/` in the worktree).

**Spec:** `docs/superpowers/specs/2026-10-20-layered-hull-damage-productisation.md`. This plan covers §3.4 ("Fill: port the decks-and-rooms interior … onto the inside wall") and decision 5 (interior fill now), which Mark took on 2026-10-20 ("yes continue" to the combined step). Look reference: `docs/reference/engine/breach-interior-mapping-spike-findings.md` and branch `spike/breach-interior-mapping`, `breach.frag` (`ih_hash`, `ih_rand`, `ih_wall_exists`, `ih_room_light`, `ih_shade`). Perf context: `docs/reference/engine/perf-register.md` P-12, scenario DP, C-101–C-104.

**Mark's words this answers:**
- Sovereign after torpedo volleys: "whats not uneven is the wear THROUGH the ribs. theres also nothing behind that hole".
- Blown-out Akira: "we can see through the internals … you can spot the sovereign through the backfaces of the nacelle".

**Not in this plan:** the permanent damage store, the eligibility cap, articulated-part frames (spec steps 2b–3), and the room look on rocks (rocks keep whatever they get today).

## Global Constraints

- **Branch and git.**
  - Work on branch `spike/damage-redesign`, worktree `.claude/worktrees/damage-redesign`, with all paths below relative to it.
  - Never run `git checkout --`, `restore`, `stash`, `clean`, `reset --hard` or `add -A/.`.
  - Stage explicit paths. Commit with `git commit -F <file>`, the message ending `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **Tests.** Focused test files only: never a whole suite, never the gate. Never run pytest with an empty or glob-built file list.
- **Shader builds.**
  - Any edit under `native/src/renderer/shaders/` needs `cmake -B build -S .` before `cmake --build build -j`. Confirm with a grep in the matching `build/native/src/renderer/embedded_*.h`.
  - Shader errors appear only at runtime, so run the renderer GL tests after every shader change.
- **`opaque.frag` rules.**
  - Never add a `sampler3D`, or any new sampler, to `opaque.frag`: the driver miscompiles it (memory `project_opaque_frag_sampler3d_miscompile`). The fill volume is sampled only in the new interior shader.
  - `opaque.frag` is optimizer-fragile. After any edit to it, run `HullClipTest.*` and `ScuffTest.*` as well as the plating tests.
  - The stock program must not change: outside `#ifdef PLATING`, `opaque.frag` keeps exactly its current text. Check with `git diff 1fca3177d -- native/src/renderer/shaders/opaque.frag`: every hunk must sit inside `#ifdef PLATING`.
- **GLSL 410.** No SSBOs; arrays are uniforms.
- **Units.** Body frame = model units (1 mu ≈ 1.75 m, 0.01 GU). Room sizes and fog are model units, as tuned live in the interior spike.
- **Perf captures.** Only when the machine is idle (no game, tests or builds): headless, Debug build, logs in `~/Documents/dauntless-perf/`. Record them as new C-/SIG- rows in `perf-register.md`; never edit old rows. GPU-focus runs give attribution, never frame time (M-6).

## Review Focus

1. **Two damaged hulls, one behind the other's hole.** The front hull's interior must hide the rear hull. The rear hull's interior must never paint into the front hull's hole unless the front hull is blown clear through there. Pinned in Task 3 (`RearHullInteriorNeverPaintsThroughFrontHole`).
2. **A hull with no fill volume** (a mod ship with no `_vox` NIF and an unloadable mesh). Rooms still draw, with no "left the ship" test, rather than a see-through hole. Pinned in Task 3 (`NoFillStillDrawsRooms`).
3. **An undamaged, or only lightly worn, hull** (wear below the conservative tear bound). No marking draw, no interior draw, no stencil writes. Pinned in Task 2 (`NoMarkWithoutPossibleTear`) and Task 3 (`UndamagedSceneDrawsNoInterior`).
4. **Toughness and lumps both 0.** The breach outline must be exactly the old even one, so the dials A/B cleanly. Pinned in Task 1 (`ZeroSpreadAndLumpsKeepTheEvenOutline`).
5. **A plating draw leaves GL state stock.** Cull face on, back culled, stencil test off, masks restored after the marking and interior draws. Pinned in Task 2 (`PlatingDrawsLeaveStockGlState`).

---

### Task 1: Uneven breach — toughness per panel, lumps at hole scale

**Files:**
- Modify: `native/src/renderer/include/renderer/plating_damage.h`, `native/src/renderer/plating_damage.cc` (param count, `torn_possible`)
- Modify: `native/src/renderer/frame.cc` (`dauntless_plating::g_params`, the `u_plating` upload)
- Modify: `native/src/host/host_bindings.cc` (`set_plating_params` copies up to `kParamCount`)
- Modify: `native/src/renderer/shaders/opaque.frag` (PLATING only)
- Modify: `engine/appc/plating_dials.py`
- Test: `native/tests/renderer/plating_damage_test.cc`, `native/tests/renderer/plating_render_test.cc`, `tests/unit/test_plating_dials.py`

**Interfaces:**
- Produces:
  - `constexpr int renderer::plating::kParamCount = 32;` Use it for `g_params`, the upload, the binding and the tests' `extern` and saved-params arrays. No literal `24` may remain for the param count. Slot `kMaxDamage` stays 24.
  - New param slots, all live dials in `plating_dials.py`:
    - 22 `toughness_spread`, default 0.6, step 0.1.
    - 23 `breach_lumps`, default 1.0 wear, step 0.25.
    - 24 `deck_break_wear`, default 6.0, step 0.25.
    - 25 `interior`, default 1.0, max 1.0, step 1.0.
    - Slots 26–31 are 0 and reserved.
  - Slots 24 and 25 are first read in Task 3. They are added now so the param block grows once.
  - GLSL, PLATING only: `float plating_breach_at(vec3 p, vec2 cell)`, which is
    `u_plating[16] * (1.0 + u_plating[22] * (dhash(cell * 0.029 + 31.0) - 0.4)) + (plating_lumps(p) - 0.5) * 2.0 * u_plating[23]`.
  - GLSL, PLATING only: `float plating_lumps(vec3 p)`, which is
    `vnoise(p.xy * f + p.z * 0.61 * f + 13.7) * 0.65 + vnoise(p.yz * f * 1.9 + p.x * f * 0.7 + 21.1) * 0.35` with `f = 1.0 / max(2.5 * u_plating[2], 1.0)`.
  - The conservative floor `breach * (1 - 0.4 * spread) - lumps` is the lowest value `plating_breach_at` can return. Both the shader early-out and the CPU `torn_possible` use it.

- [ ] **Step 1: Write the failing tests.**
  - `plating_damage_test.cc`, `TornPossibleUsesTheToughnessAndLumpFloor`: the bound must be `total >= p[16] * (1 - 0.4 * p[22]) - p[23] - 0.75 * p[19]`.
    - Defaults with one Internal record of wear 2.0 → `torn_possible` true (floor 4.5 × 0.76 − 1.0 − 0.675 = 1.745).
    - The same record with spread 0 and lumps 0 → false (the old bound, 4.5 − 0.675).
  - Shared setup for the two render tests below:
    - One Internal record at the quad centre, reach 30. Its centre wear `W` is chosen so the wear `W(1 − r²/R²)²` on a ring of radius 15 mu equals `breach_wear + δ`.
    - `tear_noise = 0` and `member_width = 0`, so per-pixel noise and surviving members cannot decide the result.
    - Sample 32 pixels evenly around that ring.
  - `plating_render_test.cc`, `BreachOutlineIsUnevenAtEqualWear`: with δ = +0.2 and default spread and lumps, at least 4 ring pixels are cut (clear colour) and at least 4 are not.
  - `plating_render_test.cc`, `ZeroSpreadAndLumpsKeepTheEvenOutline`: with `toughness_spread = 0` and `breach_lumps = 0`, δ = +0.2 gives all 32 cut, and δ = −0.2 gives none cut.
  - `test_plating_dials.py`: the four new keys, their defaults, and `len(params()) == 26`.
- [ ] **Step 2: Build and run** `build/native/tests/renderer/renderer_tests --gtest_filter='PlatingDamage*:PlatingRender*'` and `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider tests/unit/test_plating_dials.py`. Expect FAIL.
- [ ] **Step 3: Implement.**
  - Grow the param block to `kParamCount`.
  - Add the dials and the new `torn_possible` floor.
  - Add `plating_lumps` and `plating_breach_at` beside `plating_tear_w`.
  - In `plating_hole`:
    - Early-out first on `over_floor = w + tear_lift - floor <= 0`, where tear_lift is the existing noise term.
    - Otherwise take the toughness cell from an UNWARPED `plating_sample(part, p, nb, …)`, the same cell `apply_plating` calls `c0`.
    - Use `over = w + tear_lift - plating_breach_at(p, cell)`. The rest is unchanged.
  - In `apply_plating`, replace `breach` with `plating_breach_at(p_body, c0)` in the `dent`, `heat`, `torn` and `rim` lines. The painted tear and the cut then agree.
- [ ] **Step 4: Reconfigure, build, run** `--gtest_filter='PlatingDamage*:PlatingRender*:HullClipTest.*:ScuffTest.*:DecalRenderTest.*'` and the pytest file. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 2: Front faces only, and a stencil mark where the hull is cut

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag` (PLATING only)
- Modify: `native/src/renderer/frame.cc`, `native/src/renderer/include/renderer/frame.h`
- Modify: `native/src/host/host_bindings.cc` (call site and profiler scope)
- Test: `native/tests/renderer/plating_render_test.cc`

**Interfaces:**
- Consumes: `build_damage_list`, `wants_plating`, `DamageList::torn_possible` (Task 1 floor).
- Produces:
  - `draw_model(..., const plating::DamageList* plating = nullptr, bool plating_mark = false)`.
  - `uniform int u_plating_mark;` in `opaque.frag`, PLATING only.
  - `void FrameSubmitter::submit_plating_interior(const scenegraph::World&, const scenegraph::Camera&, Pipeline&, const ModelLookup&, CarveFieldCache* carve_cache, const Lighting&, float ambient_scale, float now)`.
    - Visits each visible Space instance with `far_fade < 1`, a model, `wants_plating` and `torn_possible`, in world order.
    - Gives the k-th such instance the stencil value `2 + k`, and stops after value 255. Value 1 stays the old carve's.
    - For each, issues the marking draw: plating program, `plating_mark = true`.
    - Task 3 adds the interior draw immediately after each marking draw, before the next instance is marked.
  - `int FrameSubmitter::plating_marks_last_frame() const`: the count, for tests.
  - Marking GL state:
    - Colour mask off and depth mask off.
    - Depth test on with `GL_LEQUAL`.
    - Stencil test on: `glStencilFunc(GL_ALWAYS, value, 0xFF)`, `glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE)`, mask 0xFF.
    - Afterwards, restore the stock state: stencil off, stencil mask 0xFF, masks on, `GL_LESS`, or whatever `submit_opaque_in_pass` leaves (read it, don't guess).

- [ ] **Step 1: Write the failing GL tests.** Replace `FarBackFaceIsDiscarded` and `InsideFaceNearDamageShowsThroughTheTear`, which pin the double-sided path being removed, with:
  - `PlatingDrawCullsBackFaces`: the two-quad scene from the old inside-face test, drawn through `submit_opaque_in_pass` only. The torn centre pixel shows the clear colour, because the back-facing far quad is culled.
  - `MarkingStampsOnlyTornPixels`:
    - Draw a single front quad with an Internal record (reach 30, wear 10) through `submit_opaque_in_pass`, then `submit_plating_interior`.
    - Read back stencil with `glReadPixels(..., GL_STENCIL_INDEX, GL_UNSIGNED_BYTE, ...)`.
    - The centre is 2. A hull pixel more than `reach + margin` from the record is 0. A pixel off the quad is 0.
    - `plating_marks_last_frame() == 1`.
  - `NoMarkWithoutPossibleTear`: the same quad with wear 0.3. `plating_marks_last_frame() == 0` and the stencil is all 0.
  - `PlatingDrawsLeaveStockGlState`: after `submit_opaque_in_pass` plus `submit_plating_interior` on a damaged quad:
    - `glIsEnabled(GL_CULL_FACE)`, cull face `GL_BACK`, `!glIsEnabled(GL_STENCIL_TEST)`.
    - Stencil writemask 0xFF, colour and depth writemasks on.
    - Depth func equal to its value before the calls.
- [ ] **Step 2: Build and run** `--gtest_filter='PlatingRender*'`. Expect FAIL.
- [ ] **Step 3: Implement.**
  - In `opaque.frag`:
    - Remove `u_plating_two_sided`, the far back-face discard, the inside-face branch, the `n = -n` flips in the member branch, and `plating_inner_wall`.
    - Right after `plating_hole` in `main`, add: `if (u_plating_mark != 0) { if (hole != 1) discard; frag_color = vec4(0.0); return; }`.
    - When `u_plating_mark != 0` and `!plating_near`, discard.
  - In `frame.cc`:
    - Remove the two-sided upload and `CullRestore`.
    - `draw_model` sets `u_plating_mark` on every plating draw.
    - Implement `submit_plating_interior`, marking only, as specified above.
  - In `host_bindings.cc`, call it right after the breach pass, under `DAUNTLESS_FRAME_SCOPE("space.hull_interior")`, with `g_carve_cache.get()`, the lighting, `ambient_scale` and `g_decal_game_time`.
- [ ] **Step 4: Reconfigure, build, run** `--gtest_filter='PlatingRender*:PlatingDamage*:HullClipTest.*:ScuffTest.*:DecalRenderTest.*:FrameTest.*'`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 3: The interior draw — decks and rooms behind every cut

**Files:**
- Create: `native/src/renderer/shaders/hull_interior.frag` (embed it in `native/src/renderer/CMakeLists.txt` the way `breach.frag` is embedded)
- Create: `native/src/renderer/include/renderer/hull_interior_pass.h`, `native/src/renderer/hull_interior_pass.cc` (add to the renderer CMake list)
- Modify: `native/src/renderer/pipeline.{h,cc}` (`hull_interior_shader()`)
- Modify: `native/src/renderer/frame.cc`, `native/src/renderer/include/renderer/frame.h` (`submit_plating_interior` draws the interior)
- Test: `native/tests/renderer/hull_interior_test.cc` (new; add to `native/tests/renderer/CMakeLists.txt`)

**Interfaces:**
- Consumes:
  - `submit_plating_interior` and its stencil values (Task 2).
  - Param slots 24 and 25 (Task 1).
  - `CarveFieldCache::get_for_source(model->source)` for the fill texture: `nullptr` means fill_tex 0.
  - `draw_model_positions_only` and `breach.vert`, unchanged. `breach.vert` puts the hull surface point in the body frame as `v_body_pos`.
- Produces:
  - `Pipeline::hull_interior_shader()`: `breach_vs` plus `hull_interior_fs`.
  - `class renderer::HullInteriorPass`:
    ```cpp
    void draw(const assets::Model& model, const glm::mat4& world_xf,
              const scenegraph::Camera& camera, Pipeline& pipeline,
              const plating::DamageList& list, const float* params,
              unsigned int fill_tex, const glm::vec3& fill_origin,
              const glm::vec3& fill_cell, const glm::ivec3& fill_dims,
              const Lighting& lighting, float ambient_scale, float now,
              int stencil_value,
              const std::unordered_map<int, glm::mat4>* node_overrides);
    int draw_calls() const;   // since construction
    ```
  - GL state for `draw`:
    - Stencil test on: `glStencilFunc(GL_EQUAL, stencil_value, 0xFF)`, stencil mask 0 (test only).
    - Cull back, depth test `GL_LEQUAL`, depth and colour writes on, blend off.
    - Fill on unit 0 as `sampler3D`. Bind and set it on every draw, even when 0: an unset sampler defaults to unit 0.
    - Restore the stock state afterwards, as Task 2 does.
  - `FrameSubmitter` owns one `HullInteriorPass`. `submit_plating_interior` calls `draw` right after each marking draw when `params[25] > 0.5`. With `params[25] <= 0.5`, the marking still runs and holes stay see-through: the A/B for the old look.
  - `int FrameSubmitter::plating_interiors_last_frame() const`.
- `hull_interior.frag` uniforms:
  - `u_camera_pos_body`.
  - `u_fill`, `u_fill_origin`, `u_fill_cell`, `u_fill_dims`, `u_fill_backing` (= `CarveFieldCache::kBackingIsovalue / 255`), `u_fill_ok`.
  - `u_dmg_count`, `u_dmg_a/b/c[24]`, with the `DamageList` layout.
  - `u_plating[32]`, `u_ambient_light` (lighting.ambient × ambient_scale), `u_time` (game clock).
  - Plus `breach.vert`'s own: `u_model`, `u_view`, `u_proj`, `u_ship_world_inv`.

`hull_interior.frag` behaviour, in body frame:

1. **Ray.**
   - `ro = v_body_pos`, `rd = normalize(v_body_pos - u_camera_pos_body)`.
2. **Interior wear.**
   - `iw(p) = Σ wear_i · (1 − r²)²` over all listed records with `r = |p − c_i| / reach_i < 1`.
   - There is no facing weight: inside the ship, every record counts.
3. **Walk.**
   - Port `ih_hash`, `ih_rand`, `ih_wall_exists`, `ih_room_light` and the plane-to-plane DDA of `ih_shade` verbatim, with the spike's tuned constants:
     - `kRoomSize (6.0, 8.67, 2.67)`, `kInteriorMaxSteps 24`;
     - wall chances 0.55 / 0.45, fog 120;
     - room mix 35 / 35 / 20 / 10, and the light levels in the findings doc's table.
   - Also port `blackbody` and `vnoise3` from `breach.frag`. Copies are expected; this is the project's existing pattern for `breach.frag`.
   - At each crossing:
     - (a) **Left the ship.** When `u_fill_ok` is set and the fill sample at p is below `u_fill_backing`, or p is outside the fill box:
       - if `iw(p) > u_plating[24]`, discard: the far wall is gone too, so the ship is blown through;
       - otherwise return the **far wall**, shaded with `ih_room_light` of the current cell in place of the spike's room-lit wall, and its albedo `INNER_HULL × u_plating[17] × (0.45 + 0.25 × grain)`.
     - (b) **Blown plate.** On an existing plate where `iw(p) + (vnoise3(p × 0.6) − 0.5) × u_plating[19] > u_plating[24]`, the plate is gone: keep walking.
     - (c) **Otherwise** shade the floor, ceiling or wall exactly as `ih_shade` does.
       - Replace the spike's torn-edge test with `edge = 1 − smoothstep(u_plating[24] − 1.0, u_plating[24], iw(p))`.
       - Then `c *= mix(1, 0.35, edge)` and `c += blackbody(0.5) × edge × 0.6`.
       - The spike's fresh-hit heat needs a breach age, which plating records do not have.
4. **Out of steps.**
   - Return the spike's deep-interior near-black.

- [ ] **Step 1: Write the failing GL tests** in `hull_interior_test.cc`. Reuse the window and pipeline setup of `plating_render_test.cc`, factored into a shared test helper if both need it, never copied.
  - **Fixture.** A closed box hull, 40 × 40 × 40 mu centred on the origin, six outward-wound quads. A synthetic fill: a `voxel::VoxelVolume` fully solid over the box, uploaded with the existing fill-upload code. If that code is file-local, expose it rather than duplicate it. A camera on +z looking at the box.
  - `HoleShowsInteriorNotClearColour`:
    - One Internal record at the near face's centre (0, 0, 20), reach 30, wear 10, so it is cut there.
    - Run `submit_opaque_in_pass` then `submit_plating_interior`.
    - The centre pixel is not the clear colour, and `plating_interiors_last_frame() == 1`.
    - With `params[25] = 0`, the same pixel is the clear colour.
  - `BlownThroughOnlyPastDeckBreak`:
    - A record at the box centre, reach 60, wear 10, so every plate and both walls are inside reach.
    - With `deck_break_wear = 1000`, the centre pixel is not the clear colour: plates hold.
    - With `deck_break_wear = 0.01`, the centre pixel is the clear colour: decks and far wall are blown.
  - `NoFillStillDrawsRooms`: as `HoleShowsInteriorNotClearColour` with fill_tex 0. The centre is not the clear colour.
  - `RearHullInteriorNeverPaintsThroughFrontHole`:
    - Two boxes on the camera axis, the front one cut at its near face (reach 30, wear 10), the rear one undamaged.
    - The front hole's centre pixel equals the single-box result from `HoleShowsInteriorNotClearColour`.
    - The rear box takes no marking (`plating_marks_last_frame() == 1`).
  - `UndamagedSceneDrawsNoInterior`: the box with no records. `plating_interiors_last_frame() == 0`, and the image equals the stock draw.
- [ ] **Step 2: Reconfigure, build, run** `--gtest_filter='HullInterior*'`. Expect FAIL.
- [ ] **Step 3: Implement** the shader, the pass, the pipeline program and the call from `submit_plating_interior`.
- [ ] **Step 4: Run** `--gtest_filter='HullInterior*:PlatingRender*:PlatingDamage*:HullClipTest.*:ScuffTest.*:DecalRenderTest.*:FrameTest.*:BreachPass*'` and `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider tests/unit/test_plating_dials.py tests/unit/test_internal_blast.py`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 4: Measure, and record the verdict

**Files:**
- Modify: `docs/reference/engine/perf-register.md`, `docs/superpowers/specs/2026-10-20-layered-hull-damage-productisation.md` (§1 Holes row, §3.4, §5)

- [ ] **Step 1: Captures (machine idle).** Run the DP command from `perf-register.md` with `DAUNTLESS_PROFILE_GPU_FOCUS=space.opaque,space.carve_stencil,space.breach,space.hull_interior` twice, at the default distance and at 1.5 GU (`DAUNTLESS_DAMAGE_PREVIEW_DISTANCE_GU=1.5`). Pass `DAUNTLESS_DEV_SCREENSHOT=<png> DAUNTLESS_DEV_SCREENSHOT_AFTER_S=15` on both. Look at the screenshots: the impulse holes must show rooms, not space.
- [ ] **Step 2: Record** C- rows and one signal per window (damaged-alive, dying), with `space.opaque` and `space.hull_interior` GPU means, against C-101 / C-102. Update P-12.
- [ ] **Step 3: Bars.** At the default distance:
  - damaged-alive `space.hull_interior` ≤ 0.30 ms;
  - damaged-alive `space.opaque` no higher than C-101's 0.514 ms (front-faces-only should lower it);
  - dying `space.hull_interior` ≤ 1.5 ms.

  Record misses with their numbers. Do not tune to the bar without recording it.
- [ ] **Step 4: Update the spec.** In §1's Holes row, the look is pending Mark's check. Fill in §3.4 as built, and add a step-2c row in §5.
- [ ] **Step 5: Commit** the docs.
