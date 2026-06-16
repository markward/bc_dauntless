# Hull Damage Tessellation — Plan 5a: Dent/Gouge Shading (Damage.tga baseline)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Where the hull is displaced past a rupture threshold, render it as a **gouge** — a torn interior (the stock `Damage.tga`, triplanar-projected) with a charred edge ring — while shallower displacement stays a **dent** (hull texture preserved).

**Architecture:** The deform TES emits the per-fragment displacement magnitude as a new `v_deform_depth` varying; the static-path vertex shaders (`opaque.vert`, `skinned.vert`) emit it as `0.0` so the shared `opaque.frag` interface stays matched. `opaque.frag` thresholds `v_deform_depth` (smoothstep over a rupture band) and, where it ruptures, blends the base color toward a triplanar sample of a shared damage texture (in body space, reusing the already-reconstructed `p_body`/`n_body`), darkened with a charred edge ring. `Pipeline` loads `Damage.tga` once and binds it to texture unit 3 for every ship draw, with a graceful fallback (black) if the asset is missing. No config toggle and no procedural variant here — those are Plan 5b. Like Plan 4b, this is invisible in gameplay until Plan 6 wires the crater trigger; it is verified by GPU render-readback tests.

**Tech Stack:** C++20, OpenGL 4.1, GLSL 330 (opaque.frag/vert, skinned.vert) + 410 (deform TES), GLM, GoogleTest (renderer GPU suite, offscreen FBO + glReadPixels), `assets::decode_tga`/`upload_image`.

**Spec:** `docs/superpowers/specs/2026-06-16-hull-damage-tessellation-design.md` — §Architecture.3 (FS dent vs gouge: triplanar `Damage.tga`, charred ring), §Three damage looks (dent = texture preserved; gouge = ruptured interior).

**Branch:** create `feat/hull-damage-gouge` off `main` (Plans 1–4b merged).

---

## Key facts for the implementer (you have zero context — read these)

- bc_dauntless is an open C++ reimplementation of Star Trek: Bridge Commander. ONE build tree at the project root. Always: `cmake -B build -S . && cmake --build build -j` from `/Users/mward/Documents/Projects/bc_dauntless`. **NEVER** run cmake inside `native/`.
- **The fragment shader `opaque.frag` is SHARED** by three vertex-stage paths: `opaque.vert` (static ships), `skinned.vert` (skinned ships/characters), and the deform `opaque_deform.tese` (cratered ships). It declares `in vec3 v_normal_ws; in vec2 v_uv; in vec3 v_position_ws;` and reconstructs body-frame `p_body`/`n_body` from `v_position_ws` via `u_ship_world_inv` (around line 285). ANY new `in` varying added to `opaque.frag` must be emitted by ALL THREE feeding stages or the program fails to link.
- **The deform TES** (`native/src/renderer/shaders/opaque_deform.tese`) computes `disp_body` (the body-frame crater displacement vector) in `main()`. Its magnitude `length(disp_body)` is the displacement depth at that vertex.
- **Texture binding** (`native/src/renderer/frame.cc`, `draw_model`): material textures bind to units 0 (`u_base_color`), 1 (`u_glow_map`), 2 (`u_specular_map`) via `glActiveTexture(GL_TEXTUREn) + glBindTexture + prog.set_int("u_...", n)`. **Unit 3 is free.** `draw_model` has `white_fallback`/`black_fallback` GL texture ids in scope.
- **Texture loading:** `assets::Image assets::decode_tga(std::span<const std::uint8_t>)` + `assets::Texture assets::upload_image(const Image&, bool mipmaps)` (`native/src/assets/include/assets/texture.h`). `assets::Texture` is an RAII GL-handle wrapper (`.id()`). Load pattern (see `sun_pass.cc`): read file bytes → `decode_tga` → `upload_image`. `decode_tga` throws on failure (`UnsupportedTga`/`TextureDecodeError`) — catch it.
- **`Pipeline`** (`native/src/renderer/include/renderer/pipeline.h` + `pipeline.cc`) is constructed once with a live GL context and owns shader programs (+ now the deform program). It's the right owner for a single shared `Damage.tga` texture. `Pipeline` is available in `frame.cc`'s submission functions (passed to `draw_model` indirectly — confirm how `draw_model` gets pipeline/fallbacks).
- **Asset path:** the renderer loads fixed assets by direct relative path from the project root, e.g. `"game/data/Textures/Effects/Damage.tga"` (confirmed to exist). `game/` is gitignored — present on the dev machine, ABSENT in clean CI. So the Pipeline load MUST gracefully fall back (no texture / black) when the file is missing, and any test that needs the real asset must `GTEST_SKIP()` when absent. Tests of the FS gouge blend should bind their OWN sentinel texture (not the real asset) so they run everywhere.
- **Tests:** renderer GPU tests use a hidden `renderer::Window` (skip on `std::runtime_error`) + offscreen FBO + `glReadPixels`. The deform program + a crater + `glVertexAttrib1f(7, 1.0f)` is the established way to drive displacement in a test (see `deform_pipeline_test.cc` `CraterDisplacesGeometry`). Register new tests in `native/tests/renderer/CMakeLists.txt`.
- **Body frame:** `p_body`/`n_body` in `opaque.frag` are the ship-local position/normal (model units). Triplanar projection uses `p_body` for the three planar UVs and `n_body` for the blend weights.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `native/src/renderer/shaders/opaque_deform.tese` | Emit `v_deform_depth = length(disp_body)` | Modify |
| `native/src/renderer/shaders/opaque.vert` | Emit `v_deform_depth = 0.0` (static path) | Modify |
| `native/src/renderer/shaders/skinned.vert` | Emit `v_deform_depth = 0.0` (skinned path) | Modify |
| `native/src/renderer/shaders/opaque.frag` | Declare `v_deform_depth` + `u_damage_texture`; gouge threshold + triplanar blend + charred ring | Modify |
| `native/src/renderer/include/renderer/pipeline.h` | `damage_texture()` accessor + member | Modify |
| `native/src/renderer/pipeline.cc` | Load `Damage.tga` once (graceful fallback) | Modify |
| `native/src/renderer/frame.cc` | Bind damage texture to unit 3 + set `u_damage_texture` in `draw_model` | Modify |
| `native/tests/renderer/gouge_shading_test.cc` | Render-readback: deep displacement → gouge fill from a bound sentinel texture | Create |
| `native/tests/renderer/CMakeLists.txt` | Register the test | Modify |

---

## Task 1: Add the `v_deform_depth` varying (all paths matched)

Thread the displacement depth from the deform TES to `opaque.frag`, with the static-path vertex shaders emitting 0 so the shared fragment interface stays linkable. `opaque.frag` declares it but does not use it yet (Task 2).

**Files:**
- Modify: `native/src/renderer/shaders/opaque_deform.tese`, `opaque.vert`, `skinned.vert`, `opaque.frag`
- Test: `native/tests/renderer/deform_pipeline_test.cc` (the existing `ProgramLinksWithOpaqueFragment` test already covers the deform program link; add a Pipeline-builds assertion)

- [ ] **Step 1: Emit the varying from the deform TES**

In `native/src/renderer/shaders/opaque_deform.tese`, add an output varying and set it from the displacement magnitude. Add near the other `out` declarations:
```glsl
out float v_deform_depth;   // |displacement| at this vertex (model units); FS thresholds dent vs gouge
```
In `main()`, after `disp_body` / `displaced_body` are computed (the displacement vector is `db - body_pos`, or recompute as `displaced_body_at(bc) - <undisplaced body_pos>`), set the varying. The simplest correct value: the magnitude of the crater displacement at this vertex. Compute the undisplaced body position once and take the difference. In `main()`, where `db = displaced_body_at(bc)` is computed, also compute the undisplaced body position and the depth:
```glsl
    // Undisplaced body position (same chain as displaced_body_at minus the
    // crater term) for the displacement magnitude the FS uses to pick gouge.
    vec3 lp0 = bc.x * tcp_pos[0] + bc.y * tcp_pos[1] + bc.z * tcp_pos[2];
    vec3 wp0 = (u_model * vec4(lp0, 1.0)).xyz;
    vec3 bp0 = (u_ship_world_inv * vec4(wp0, 1.0)).xyz;
    v_deform_depth = length(db - bp0);
```
(Place this alongside the existing `db` computation in `main()`; `db` is the displaced body position, `bp0` the undisplaced — their distance is the local displacement depth.)

- [ ] **Step 2: Emit `v_deform_depth = 0.0` from the static-path vertex shaders**

In `native/src/renderer/shaders/opaque.vert`, add:
```glsl
out float v_deform_depth;
```
and in `main()`:
```glsl
    v_deform_depth = 0.0;   // static path: no deformation
```
Do the identical addition in `native/src/renderer/shaders/skinned.vert` (it also feeds `opaque.frag`): add the `out float v_deform_depth;` declaration and `v_deform_depth = 0.0;` in its `main()`.

- [ ] **Step 3: Declare the varying in `opaque.frag` (unused yet)**

In `native/src/renderer/shaders/opaque.frag`, add alongside the other `in` declarations (after `in vec3 v_position_ws;`):
```glsl
in float v_deform_depth;   // |hull displacement| (model units); 0 on the static path
```
Do NOT use it yet — Task 2 adds the gouge logic. (An unused `in` is fine and keeps this task a pure interface-plumbing step.)

- [ ] **Step 4: Build + confirm all three programs still link**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline|Pipeline" --output-on-failure`
Expected: all PASS (the deform program, opaque, and skinned programs all link with the new matched varying; the existing `ProgramLinksWithOpaqueFragment` + `PipelineExposesDeformShaderWhenTessellationAvailable` tests cover opaque_fs linking against both the TES and — via the Pipeline build — opaque.vert and skinned.vert). If any program fails to link with `v_deform_depth`, a feeding stage is missing the matched `out` — fix it.

- [ ] **Step 5: Run the full suite (no regression — varying is emitted but unused)**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: full suite PASS/SKIPPED. Render output unchanged (the varying isn't sampled yet).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/opaque_deform.tese native/src/renderer/shaders/opaque.vert native/src/renderer/shaders/skinned.vert native/src/renderer/shaders/opaque.frag
git commit -m "feat(renderer): thread v_deform_depth varying to the shared fragment shader"
```

---

## Task 2: Gouge threshold + triplanar damage fill + charred ring in `opaque.frag`

Where `v_deform_depth` crosses the rupture band, blend the base color toward a triplanar sample of `u_damage_texture` (body space) with a charred darkened edge. Below the band, the hull is unchanged (a dent). Tested by binding a sentinel damage texture directly (no asset dependency).

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`
- Test: `native/tests/renderer/gouge_shading_test.cc` (create)
- Modify: `native/tests/renderer/CMakeLists.txt`

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/gouge_shading_test.cc`. It renders the deform program on a quad with a DEEP crater (so the dented region's `v_deform_depth` exceeds the rupture threshold), binds a distinctive solid-magenta texture to `u_damage_texture` (unit 3), and asserts the deeply-displaced center shows the gouge fill (magenta-influenced) while a corner (shallow) does not.

```cpp
// native/tests/renderer/gouge_shading_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <vector>

#include <renderer/pipeline.h>
#include <renderer/shader.h>
#include <renderer/window.h>

namespace {

// A 1x1 solid texture, returned id bound to a unit by the caller.
GLuint make_solid_texture(unsigned char r, unsigned char g, unsigned char b) {
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    const unsigned char px[4] = {r, g, b, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    return tex;
}

TEST(GougeShading, DeepDisplacementShowsDamageTexture) {
    try {
        renderer::Window w(64, 64, "gouge-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        const float verts[] = {
            -0.9f, -0.9f, 0.0f,  0.9f, -0.9f, 0.0f,  0.9f,  0.9f, 0.0f,
            -0.9f, -0.9f, 0.0f,  0.9f,  0.9f, 0.0f, -0.9f,  0.9f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        glVertexAttrib1f(7, 1.0f);  // crushability = 1

        // Bind a magenta damage texture to unit 3, white base to unit 0.
        GLuint dmg = make_solid_texture(255, 0, 255);
        GLuint white = make_solid_texture(255, 255, 255);
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, white);
        glActiveTexture(GL_TEXTURE3); glBindTexture(GL_TEXTURE_2D, dmg);

        glViewport(0, 0, 64, 64);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        prog.use();
        glm::mat4 I(1.0f);
        prog.set_mat4("u_model", I);
        prog.set_mat4("u_view", I);
        prog.set_mat4("u_proj", I);
        prog.set_mat4("u_ship_world", I);
        prog.set_mat4("u_ship_world_inv", I);
        prog.set_int("u_base_color", 0);
        prog.set_int("u_damage_texture", 3);
        // A directional light so the base (white) lit color is bright and
        // distinguishable from the magenta gouge fill.
        prog.set_vec3("u_ambient_light", glm::vec3(1.0f));
        prog.set_int("u_dir_light_count", 0);
        prog.set_vec3("u_diffuse_color", glm::vec3(1.0f));
        prog.set_float("u_emissive_scale", 0.0f);
        prog.set_int("u_decal_count", 0);
        prog.set_int("u_glow_region_count", 0);
        // Deep crater at the quad centre -> centre v_deform_depth high (gouge),
        // corners low (dent).
        prog.set_int("u_crater_count", 1);
        glm::vec4 ca(0.0f, 0.0f, 0.0f, 0.6f);   // point_body, depth 0.6 model units
        glm::vec4 cb(0.0f, 0.0f, -1.0f, 0.5f);  // dir -z, radius 0.5
        prog.set_vec4_array("u_crater_a", &ca, 1);
        prog.set_vec4_array("u_crater_b", &cb, 1);

        while (glGetError() != GL_NO_ERROR) {}
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 6);

        unsigned char center[4] = {0, 0, 0, 0};
        glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        // Gouge fill pulls the centre toward magenta (high R, low G, high B).
        // Without gouge the centre would be lit white (R≈G≈B high). The
        // discriminator: G is pulled DOWN by the magenta blend at the gouged centre.
        EXPECT_LT(center[1], 200) << "centre should show gouge fill (G pulled down by magenta), not lit white";

        glDeleteTextures(1, &dmg);
        glDeleteTextures(1, &white);
        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
```

Register `gouge_shading_test.cc` in `native/tests/renderer/CMakeLists.txt`.

- [ ] **Step 2: Run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ctest --test-dir build -R "GougeShading" --output-on-failure`
Expected: FAIL — `opaque.frag` has no `u_damage_texture` and no gouge blend yet, so the centre renders lit white (G high), failing `EXPECT_LT(center[1], 200)`.

- [ ] **Step 3: Add the damage sampler + gouge logic to `opaque.frag`**

In `native/src/renderer/shaders/opaque.frag`:

(a) Add the sampler uniform + tunable constants near the other uniforms (after `u_specular_map` etc.):
```glsl
uniform sampler2D u_damage_texture;   // shared torn-hull interior (unit 3)
// Rupture band (model units): displacement below RUPTURE_MIN is a dent (hull
// texture preserved); above RUPTURE_MAX is a full gouge (torn interior).
const float RUPTURE_MIN = 0.15;
const float RUPTURE_MAX = 0.45;
const float DAMAGE_TEX_SCALE = 1.5;   // triplanar tiling (1/model-units), tuned
const vec3  CHAR_COLOR = vec3(0.04, 0.03, 0.025);  // charred ring near the gouge edge
```

(b) In `main()`, AFTER `lit` (the base lit color) and `p_body`/`n_body` are computed (they already are, ~line 282-286), add the gouge blend before the decal application:
```glsl
    // Hull-deformation gouge: where the surface is displaced past the rupture
    // band, tear it open to a triplanar damage-texture interior with a charred
    // edge ring. v_deform_depth is 0 on the static path (no gouge there).
    if (v_deform_depth > RUPTURE_MIN) {
        float gouge = smoothstep(RUPTURE_MIN, RUPTURE_MAX, v_deform_depth);  // 0..1
        // Triplanar sample of the damage texture in body space.
        vec3 bw = abs(n_body);
        bw /= (bw.x + bw.y + bw.z + 1e-5);
        vec3 dx = texture(u_damage_texture, p_body.yz * DAMAGE_TEX_SCALE).rgb;
        vec3 dy = texture(u_damage_texture, p_body.zx * DAMAGE_TEX_SCALE).rgb;
        vec3 dz = texture(u_damage_texture, p_body.xy * DAMAGE_TEX_SCALE).rgb;
        vec3 interior = dx * bw.x + dy * bw.y + dz * bw.z;
        // Charred ring: darken strongest at the rupture onset, easing into the
        // open interior toward full gouge.
        float ring = (1.0 - gouge);
        vec3 gouge_color = mix(interior, CHAR_COLOR, ring * 0.6);
        lit = mix(lit, gouge_color, gouge);
    }
```
(Place this AFTER `vec3 lit = ...;` and after `p_body`/`n_body` are reconstructed, but BEFORE the `apply_damage_decals(...)` call so decals still composite over the gouge.)

- [ ] **Step 4: Run to verify it passes**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "GougeShading|DeformPipeline" --output-on-failure`
Expected: GougeShading PASSES (centre shows magenta-influenced gouge), and DeformPipeline tests still pass (they bind no damage texture / have shallow or no displacement → no gouge, or u_deform_depth below threshold).

- [ ] **Step 5: Run the full suite**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: full suite PASS/SKIPPED. Undamaged ships (v_deform_depth 0) and the static path are unaffected (the `if (v_deform_depth > RUPTURE_MIN)` guard is false → byte-identical).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/tests/renderer/gouge_shading_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): gouge fragment shading (triplanar damage interior + charred ring)"
```

---

## Task 3: Load `Damage.tga` in Pipeline + bind it for ship draws

So the real app's gouges show the stock damage texture (not the unit-3 fallback). Loaded once, bound to unit 3 each ship draw, graceful when the asset is missing.

**Files:**
- Modify: `native/src/renderer/include/renderer/pipeline.h`
- Modify: `native/src/renderer/pipeline.cc`
- Modify: `native/src/renderer/frame.cc`
- Test: `native/tests/renderer/gouge_shading_test.cc` (append a Pipeline-load test)

- [ ] **Step 1: Write the test**

Append to `native/tests/renderer/gouge_shading_test.cc` (add `#include <filesystem>`):
```cpp
TEST(GougeShading, PipelineLoadsDamageTextureWhenPresent) {
    try {
        renderer::Window w(64, 64, "dmg-load-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        const bool asset_present =
            std::filesystem::exists("game/data/Textures/Effects/Damage.tga");
        if (asset_present) {
            EXPECT_NE(pipeline.damage_texture(), 0u)
                << "Damage.tga present but Pipeline did not load it";
        } else {
            GTEST_SKIP() << "Damage.tga not present (game/ absent) — load path "
                            "falls back; nothing to assert";
        }
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```
(`damage_texture()` returns a `GLuint` texture id, 0 when not loaded.)

- [ ] **Step 2: Run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests`
Expected: FAIL to compile — `Pipeline` has no `damage_texture()`.

- [ ] **Step 3: Add the texture to Pipeline**

In `native/src/renderer/include/renderer/pipeline.h`, add a public accessor and a private member:
```cpp
    /// Shared torn-hull "Damage.tga" interior texture (GL id), bound to unit 3
    /// for ship draws. 0 if the asset was missing at load (gouges fall back to
    /// the unit-3 black fallback).
    unsigned damage_texture() const noexcept { return damage_texture_ ? damage_texture_->id() : 0u; }
```
and in the private section:
```cpp
    std::unique_ptr<assets::Texture> damage_texture_;
```
Add the include for `assets::Texture` at the top of pipeline.h: `#include <assets/texture.h>`.

In `native/src/renderer/pipeline.cc`, add includes:
```cpp
#include <assets/texture.h>
#include <fstream>
#include <iterator>
#include <vector>
```
In the `Pipeline` constructor (after the shader builds), load the texture with a graceful fallback:
```cpp
    // Shared hull-damage interior texture for gouge shading. Loaded once; bound
    // to unit 3 per ship draw. game/ is gitignored (absent in CI) — fall back
    // silently to no texture (gouges then sample the black fallback).
    try {
        std::ifstream in("game/data/Textures/Effects/Damage.tga", std::ios::binary);
        if (in) {
            std::vector<std::uint8_t> bytes(
                (std::istreambuf_iterator<char>(in)),
                std::istreambuf_iterator<char>());
            assets::Image img = assets::decode_tga(bytes);
            damage_texture_ =
                std::make_unique<assets::Texture>(assets::upload_image(img, true));
        }
    } catch (const std::exception&) {
        damage_texture_.reset();  // decode/upload failure -> no gouge texture
    }
```

- [ ] **Step 4: Bind the damage texture in `draw_model`**

In `native/src/renderer/frame.cc` `draw_model`, after the unit-2 (`u_specular_map`) bind, add a unit-3 bind. `draw_model` needs the damage texture id — pass it in. Add a `unsigned damage_tex` parameter to `draw_model` (after the `black_fallback` parameter), and at the call sites pass `pipeline.damage_texture()`. Then in the per-mesh texture-bind block:
```cpp
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_2D, damage_tex != 0 ? damage_tex : black_fallback);
    prog.set_int("u_damage_texture", 3);
```
Update the `draw_model` declaration in `frame.h` (if present) and all call sites (`submit_opaque`, `submit_opaque_in_pass`, and the `skinned_render_test.cc` direct call — pass `0u` there) to include the new `damage_tex` argument.

- [ ] **Step 5: Run the tests**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "GougeShading|DeformPipeline" --output-on-failure`
Expected: `PipelineLoadsDamageTextureWhenPresent` PASSES on this machine (game/ present → texture loaded) or SKIPs (absent); the existing GougeShading + DeformPipeline tests still pass.

- [ ] **Step 6: Run the full suite**

Run: `ctest --test-dir build --output-on-failure`
Expected: full suite PASS/SKIPPED.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc native/src/renderer/frame.cc native/src/renderer/include/renderer/frame.h native/tests/renderer/gouge_shading_test.cc native/tests/renderer/skinned_render_test.cc
git commit -m "feat(renderer): load Damage.tga in Pipeline and bind it for gouge shading"
```
(Omit frame.h / skinned_render_test.cc from `git add` if they needed no change.)

---

## Task 4: Full build + suite

**Files:** none (verification)

- [ ] **Step 1: Build + full suite**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: `build/dauntless` + `_dauntless_host` build; full suite PASS/SKIPPED.

- [ ] **Step 2: Record the result**

No commit. Gouge shading is in place: deep displacement renders the `Damage.tga` torn interior with a charred ring; shallow displacement stays a dent; static/undamaged paths are byte-identical. Like Plan 4b, this is only visible in gameplay once Plan 6 wires the crater trigger — the render-readback tests are the verification until then. (No manual visual check is meaningful yet; the in-battle eyeball happens after Plan 6.)

---

## Self-Review

**Spec coverage (Plan 5a scope = spec §3 FS dent vs gouge, Damage.tga baseline):**
- §3 "where accumulated displacement exceeds the rupture threshold → gouge fill" → Task 2 `smoothstep(RUPTURE_MIN, RUPTURE_MAX, v_deform_depth)`. ✓ (depth threaded in Task 1.)
- §3 "triplanar `Damage.tga` projected in body space (BC hull UVs mirror)" → Task 2 triplanar sample of `u_damage_texture` using `p_body`/`n_body`; Task 3 loads the real `Damage.tga`. ✓
- §3 "charred ring at the gouge edge" → Task 2 `CHAR_COLOR` ring term. ✓
- §3 "below threshold → dent, original texture preserved" → the `if (v_deform_depth > RUPTURE_MIN)` guard leaves `lit` untouched otherwise. ✓
- §3 procedural interior + Modern VFX toggle → **Plan 5b** (deliberately deferred; this plan ships the spec's *baseline* texture interior). Noted.
- §3 "embers reusing existing decal ember/age code" → the decal path (`apply_damage_decals`) already runs after the gouge blend and composites embers/scorch over it; a gouge-specific ember is Plan 5b polish if needed. The charred ring covers the edge-darkening; ember reuse is via the existing decal system that fires on the same hits.

**Placeholder scan:** No TBD/TODO. `RUPTURE_MIN/MAX`, `DAMAGE_TEX_SCALE`, `CHAR_COLOR` are documented tunables (final values tuned against Plan 6's real depths, noted). The graceful-fallback + skip-guarded asset test handle the gitignored `game/`.

**Type consistency:** `v_deform_depth` is `out float` in opaque_deform.tese / opaque.vert / skinned.vert and `in float` in opaque.frag — matched across all four (Task 1). `u_damage_texture` (sampler2D, unit 3) is declared in opaque.frag (Task 2), set via `prog.set_int("u_damage_texture", 3)` in the test (Task 2) and in `draw_model` (Task 3). `Pipeline::damage_texture()` returns `unsigned` (GL id, 0 if unloaded) — used in the test (Task 3) and passed to `draw_model` (Task 3). The `draw_model` `unsigned damage_tex` parameter matches between definition and call sites. ✓

---

## What comes next (not this plan)

- **Plan 5b:** procedural gouge interior (shader-synthesized charred metal / exposed ribbing) + the `dauntless_hull_damage` Modern VFX toggle (the 5-place plumbing: `frame.cc` namespace flag, `host_bindings.cc` pybind setter, `engine/renderer.py` wrapper, `engine/ui/configuration_panel.py` toggle, `engine/host_loop.py` wiring) selecting baseline `Damage.tga` (default) vs procedural via a `u_procedural_damage` uniform branch in `opaque.frag`.
- **Plan 6:** eligibility manager (player always-tessellated + capped nearest/largest) + `engine/appc/hull_deformation.py` (GU depth/kind mapping) + the `hit_feedback` dispatch hook calling `renderer.hull_deform_add` — the trigger that finally makes craters (and thus dents + gouges) appear in battle. Plus the carried-forward deferrals (Plan 2 M1/M3, Plan 3 probe_thickness exposure).
