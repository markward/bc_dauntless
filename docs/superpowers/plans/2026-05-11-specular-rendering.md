# Specular (`_spec` / `_specular`) Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Blinn-Phong specular term to the opaque pass, modulated by a `_specular`/`_spec` per-texel mask when present on a ship's NIF images. Ships without the mask render identically to today.

**Architecture:** Mirror the implemented `_glow` pipeline. Classify NiImage filenames during `load_all_textures`, route detected images to `Material::StageSlot::Gloss`, accumulate Blinn-Phong specular per directional light in the fragment shader, gated on a black-fallback texture so missing masks contribute zero.

**Tech Stack:** C++20, GLSL 330, GoogleTest, pytest + `_open_stbc_host` python module.

**Reference:** [docs/superpowers/specs/2026-05-11-specular-rendering-design.md](../specs/2026-05-11-specular-rendering-design.md)

---

## File Structure

**Created:**
- `native/src/renderer/include/renderer/lighting.h` — `glossiness_to_specular_power` helper (one function).
- `native/tests/renderer/lighting_test.cc` — pinned-value test for the gloss → exponent mapping.
- `tests/host/test_specular_pass.py` — end-to-end smoke test rendering a `_specular`-using ship.

**Modified:**
- `native/src/assets/src/material_build.h` — extend `MaterialInputs` with `specular_image_links`.
- `native/src/assets/src/material_build.cc` — branch `apply_texture_property` on spec detection; bind to `Gloss` only (no dual-bind, unlike glow).
- `native/src/assets/src/model_build.cc` — add `filename_is_specular`; populate `specular_image_links` in `TextureLoadResult`; pass through to `MaterialInputs`.
- `native/src/assets/include/assets/material.h` — update `StageSlot::Gloss` docstring to describe the runtime-attached convention.
- `native/tests/assets/cpu/material_build_test.cc` — new TEST verifying spec binding routes to Gloss only.
- `native/src/renderer/shaders/opaque.vert` — emit `v_position_ws`.
- `native/src/renderer/shaders/opaque.frag` — add Blinn-Phong specular accumulation.
- `native/src/renderer/frame.cc` — bind `StageSlot::Gloss` to texture unit 2; set `u_camera_pos_ws`, `u_specular_color`, `u_specular_power` uniforms.
- `native/tests/renderer/frame_test.cc` — new TEST_F smoke-testing a `_specular`-using ship renders without GL errors and produces non-black output.
- `native/tests/renderer/CMakeLists.txt` — add `lighting_test.cc`.

Each file has one clear responsibility. The lighting helper is split into its own header so the mapping curve can be retuned in one place independent of frame.cc.

---

## Task 1 — Lighting helper + pinned mapping test

**Files:**
- Create: `native/src/renderer/include/renderer/lighting.h`
- Create: `native/tests/renderer/lighting_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/lighting_test.cc`:

```cpp
// native/tests/renderer/lighting_test.cc
#include <gtest/gtest.h>

#include <renderer/lighting.h>

TEST(Lighting, GlossinessToSpecularPowerPinnedValues) {
    using renderer::glossiness_to_specular_power;
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.00f),   4.0f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.12f),  18.88f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.25f),  35.0f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.30f),  41.2f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(1.00f), 128.0f);
    // Clamp on out-of-range BC outlier (gloss=4.0 appears in the corpus)
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(4.00f), 128.0f);
    // Clamp on negative
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(-1.0f),  4.0f);
}
```

- [ ] **Step 2: Add the new test source to CMake**

Modify `native/tests/renderer/CMakeLists.txt`. Insert `lighting_test.cc` into the `add_executable(renderer_tests ...)` list, e.g. immediately after `frame_test.cc`:

```cmake
add_executable(renderer_tests
    window_test.cc
    shader_test.cc
    pipeline_test.cc
    frame_test.cc
    lighting_test.cc
    backdrop_pass_test.cc
    sun_pass_test.cc
    dust_pass_test.cc
)
```

- [ ] **Step 3: Run test to verify it fails to build**

Run: `cmake --build build --target renderer_tests 2>&1 | tail -20`
Expected: build error, "fatal error: 'renderer/lighting.h' file not found" (or similar).

- [ ] **Step 4: Create the header with the chosen mapping**

Create `native/src/renderer/include/renderer/lighting.h`:

```cpp
// native/src/renderer/include/renderer/lighting.h
#pragma once

#include <algorithm>
#include <cmath>

namespace renderer {

/// Map BC's normalized glossiness [0,1] to a Blinn-Phong exponent.
///
/// BC NIFs author NiMaterialProperty.glossiness in a normalized [0,1]
/// range (corpus values: 0.000, 0.120, 0.250, 0.300, with a single 4.0
/// outlier — not Phong exponents). This function remaps to a usable
/// exponent. The chosen mapping is linear into [4, 128]:
///
///   gloss=0.12 -> 18.88   gloss=0.25 -> 35.0
///   gloss=0.30 -> 41.2    gloss=1.00 -> 128.0
///
/// To A/B-compare alternate curves, swap the body and re-run the build.
/// The pinned values in lighting_test.cc must be updated in the same
/// commit so the test documents the deliberate change.
///
/// Alternates considered:
///   D3D-fixed-function era:  2.0f + 254.0f * g   (range [2, 256])
///   exp2 mapping:            std::pow(2.0f, g * 10.0f) (range [1, 1024])
inline float glossiness_to_specular_power(float g) {
    g = std::clamp(g, 0.0f, 1.0f);
    return 4.0f + 124.0f * g;
}

}  // namespace renderer
```

- [ ] **Step 5: Build and run the test**

Run: `cmake --build build --target renderer_tests -j && ./build/native/tests/renderer/renderer_tests --gtest_filter='Lighting.*'`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/lighting.h \
        native/tests/renderer/lighting_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): glossiness_to_specular_power mapping + pinned test"
```

---

## Task 2 — Asset-side: `filename_is_specular` + binding to Gloss slot

**Files:**
- Modify: `native/src/assets/src/material_build.h`
- Modify: `native/src/assets/src/material_build.cc`
- Modify: `native/src/assets/src/model_build.cc`
- Modify: `native/src/assets/include/assets/material.h`
- Modify: `native/tests/assets/cpu/material_build_test.cc`

- [ ] **Step 1: Write the failing binding test**

Append to `native/tests/assets/cpu/material_build_test.cc` (after the existing tests, before the final `}  // namespace`):

```cpp
TEST(MaterialBuild, SpecularImageBindsToGlossSlotOnly) {
    // _specular images are standalone masks; unlike _glow, they do NOT
    // dual-bind to Base. Base must remain empty.
    nif::NiTextureProperty tex;
    tex.image_link = 42;

    std::unordered_map<std::uint32_t, int> img_to_tex = {{42, 7}};
    std::unordered_set<std::uint32_t> spec_links = {42};

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &img_to_tex;
    in.specular_image_links = &spec_links;

    auto m = assets::detail::build_material(in);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(m.stages[static_cast<std::size_t>(S::Gloss)].texture_index, 7);
    EXPECT_LT(m.stages[static_cast<std::size_t>(S::Base)].texture_index, 0)
        << "_specular images must not dual-bind to Base";
}

TEST(MaterialBuild, NonSpecularImageStillBindsToBase) {
    // Sanity: when specular_image_links is provided but the image_link
    // is NOT in it, behavior is unchanged from before this feature.
    nif::NiTextureProperty tex;
    tex.image_link = 100;

    std::unordered_map<std::uint32_t, int> img_to_tex = {{100, 3}};
    std::unordered_set<std::uint32_t> spec_links = {99};  // a different image

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &img_to_tex;
    in.specular_image_links = &spec_links;

    auto m = assets::detail::build_material(in);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(m.stages[static_cast<std::size_t>(S::Base)].texture_index, 3);
    EXPECT_LT(m.stages[static_cast<std::size_t>(S::Gloss)].texture_index, 0);
}
```

- [ ] **Step 2: Run test to verify it fails to compile**

Run: `cmake --build build --target assets_tests 2>&1 | tail -10`
Expected: error referencing `specular_image_links` not a member of `MaterialInputs`.

- [ ] **Step 3: Extend MaterialInputs**

Modify `native/src/assets/src/material_build.h`. Inside `struct MaterialInputs`, after the `glow_image_links` field, add:

```cpp
    /// Link IDs of NiImages whose filename matches BC's AddLOD
    /// "_specular" / "_spec" suffix convention. When a property's base-
    /// stage image is in this set, the texture is routed to
    /// StageSlot::Gloss (specular mask). Unlike glow, specular images
    /// do NOT dual-bind to Base — they are standalone masks.
    const std::unordered_set<std::uint32_t>* specular_image_links = nullptr;
```

- [ ] **Step 4: Branch the binding logic on spec detection**

Modify `native/src/assets/src/material_build.cc`. Replace `apply_texture_property` (currently lines 66-93) with:

```cpp
void apply_texture_property(
    Material& m,
    const nif::NiTextureProperty& src,
    const std::unordered_map<std::uint32_t, int>* image_to_texture,
    const std::unordered_set<std::uint32_t>* glow_image_links,
    const std::unordered_set<std::uint32_t>* specular_image_links)
{
    // Single-texture v3.x property — usually populates the Base stage.
    //
    // BC's AddLOD suffix conventions reinterpret this binding at runtime:
    //
    //   "_glow"     — image is the hull's diffuse (RGB) AND its self-
    //                 illumination mask (alpha). Bind to BOTH Base and
    //                 Glow so the lit term uses hull color and the glow
    //                 term adds emissive contribution.
    //
    //   "_specular" / "_spec" — image is a standalone per-texel specular
    //                 mask. Bind ONLY to Gloss. Do NOT dual-bind to Base
    //                 (that would replace the hull texture with the mask).
    int tex_idx = -1;
    if (image_to_texture) {
        if (auto it = image_to_texture->find(src.image_link);
            it != image_to_texture->end()) {
            tex_idx = it->second;
        }
    }
    const bool is_specular = specular_image_links &&
        specular_image_links->find(src.image_link) != specular_image_links->end();
    if (is_specular) {
        auto& gloss = m.stages[static_cast<std::size_t>(Material::StageSlot::Gloss)];
        gloss.texture_index = tex_idx;
        gloss.apply_mode    = 2;  // APPLY_MODULATE
        return;
    }
    auto& base = m.stages[static_cast<std::size_t>(Material::StageSlot::Base)];
    base.texture_index = tex_idx;
    base.apply_mode    = 2;
    const bool is_glow = glow_image_links &&
        glow_image_links->find(src.image_link) != glow_image_links->end();
    if (is_glow) {
        auto& glow = m.stages[static_cast<std::size_t>(Material::StageSlot::Glow)];
        glow.texture_index = tex_idx;
        glow.apply_mode    = 2;
    }
}
```

And update the call site in `build_material` (currently line 150):

```cpp
    if (in.texture) apply_texture_property(m, *in.texture,
        in.image_to_texture, in.glow_image_links, in.specular_image_links);
```

- [ ] **Step 5: Run the new tests**

Run: `cmake --build build --target assets_tests -j && ./build/native/tests/assets/assets_tests --gtest_filter='MaterialBuild.Specular*:MaterialBuild.NonSpecular*'`
Expected: both new tests PASS.

- [ ] **Step 6: Verify the existing material/model tests still pass**

Run: `./build/native/tests/assets/assets_tests`
Expected: 0 failures.

- [ ] **Step 7: Add the filename_is_specular classifier**

Modify `native/src/assets/src/model_build.cc`. After `filename_is_glow` (currently lines 39-49), add:

```cpp
/// True if `fname`'s extension-less basename ends in "_specular" or
/// "_spec" (case-insensitive). Matches BC's AddLOD suffix convention
/// for the 9th positional arg. Stock BC ships only ever use the long
/// form; "_spec" support exists for mod packs.
bool filename_is_specular(std::string_view fname) {
    auto dot = fname.find_last_of('.');
    auto stem = (dot == std::string_view::npos) ? fname : fname.substr(0, dot);
    auto lower_ends_with = [](std::string_view s, std::string_view suffix) {
        if (s.size() < suffix.size()) return false;
        for (std::size_t i = 0; i < suffix.size(); ++i) {
            char c = s[s.size() - suffix.size() + i];
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            if (c != suffix[i]) return false;
        }
        return true;
    };
    return lower_ends_with(stem, "_specular") || lower_ends_with(stem, "_spec");
}
```

- [ ] **Step 8: Thread specular_image_links through TextureLoadResult**

In the same file (`model_build.cc`), modify `TextureLoadResult` (currently lines 51-54):

```cpp
struct TextureLoadResult {
    std::unordered_map<std::uint32_t, int> image_to_texture;
    std::unordered_set<std::uint32_t>      glow_image_links;
    std::unordered_set<std::uint32_t>      specular_image_links;
};
```

Then in `load_all_textures`, after the existing `if (img->use_external != 0 && filename_is_glow(img->file_name))` block (around line 101), add:

```cpp
        if (img->use_external != 0 && filename_is_specular(img->file_name)) {
            out.specular_image_links.insert(link_id);
        }
```

- [ ] **Step 9: Pass specular_image_links into MaterialInputs at the orchestrator call site**

Still in `model_build.cc`, find the spot that constructs `MaterialInputs` to call `build_material` (search for `glow_image_links =` to find it). Add the sibling line:

```cpp
        inputs.specular_image_links = &texture_result.specular_image_links;
```

- [ ] **Step 10: Update Material::StageSlot::Gloss docstring**

Modify `native/src/assets/include/assets/material.h`. Replace the `enum class StageSlot` declaration (currently lines 20-23) with:

```cpp
    /// Texture stages. Most slots are populated by NiTexturingProperty
    /// blocks. Two slots have runtime-attached conventions driven by
    /// AddLOD filename suffixes on NiImages (see model_build.cc):
    ///
    ///   Glow  — populated when a NiImage filename ends in "_glow".
    ///           Dual-binds with Base; alpha is the emissive mask.
    ///   Gloss — populated when a NiImage filename ends in "_specular"
    ///           or "_spec". Standalone per-texel specular mask; does
    ///           NOT dual-bind with Base.
    enum class StageSlot {
        Base = 0, Dark, Detail, Gloss, Glow, Bump, Decal0, Decal1, Decal2,
        Count
    };
```

- [ ] **Step 11: Rebuild and verify all asset tests still pass**

Run: `cmake --build build --target assets_tests -j && ./build/native/tests/assets/assets_tests`
Expected: 0 failures.

- [ ] **Step 12: Commit**

```bash
git add native/src/assets/src/material_build.h \
        native/src/assets/src/material_build.cc \
        native/src/assets/src/model_build.cc \
        native/src/assets/include/assets/material.h \
        native/tests/assets/cpu/material_build_test.cc
git commit -m "feat(assets): detect _specular/_spec NiImages and bind to Gloss slot"
```

---

## Task 3 — Renderer plumbing + shader math + C++ smoke test

**Files:**
- Modify: `native/src/renderer/shaders/opaque.vert`
- Modify: `native/src/renderer/shaders/opaque.frag`
- Modify: `native/src/renderer/frame.cc`
- Modify: `native/tests/renderer/frame_test.cc`

- [ ] **Step 1: Write the failing renderer smoke test**

Append to `native/tests/renderer/frame_test.cc` (after `GlowContributesWithZeroAmbient`, before the closing `}  // namespace`):

```cpp
TEST_F(FrameTest, SpecularShipRendersWithDirectionalLight) {
    // Render a ship known to ship with _specular textures (Keldon).
    // Asserts:
    //   1) The opaque pass completes without GL errors after binding
    //      the spec uniforms.
    //   2) A directional light + non-zero specular term produce a
    //      non-black center pixel. (Smoke test — does not isolate the
    //      specular contribution numerically; the binding test in
    //      material_build_test.cc and the mapping test in
    //      lighting_test.cc cover those layers.)
    const std::filesystem::path keldon_nif =
        kProjectRoot / "game" / "data" / "Models" / "Ships" / "Keldon" / "Keldon.nif";
    const std::filesystem::path keldon_tex =
        kProjectRoot / "game" / "data" / "Models" / "Ships" / "Keldon" / "High";
    if (!std::filesystem::is_regular_file(keldon_nif)) {
        GTEST_SKIP() << "BC asset not available at " << keldon_nif;
    }
    if (!std::filesystem::is_directory(keldon_tex)) {
        GTEST_SKIP() << "BC texture dir not available at " << keldon_tex;
    }

    auto model_h = cache->load(keldon_nif, keldon_tex);

    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 800.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    lighting.ambient            = glm::vec3(0.1f, 0.1f, 0.1f);
    lighting.directional_count  = 1;
    lighting.directional_dir[0] = glm::vec3(0.0f, 0.0f, 1.0f);  // toward camera
    lighting.directional_color[0] = glm::vec3(1.0f, 1.0f, 1.0f);
    submitter.submit_opaque(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    int max_total = 0;
    for (int dx = -40; dx <= 40; dx += 20) {
        for (int dy = -40; dy <= 40; dy += 20) {
            unsigned char px[4] = {0};
            glReadPixels(128 + dx, 128 + dy, 1, 1,
                         GL_RGBA, GL_UNSIGNED_BYTE, px);
            int t = px[0] + px[1] + px[2];
            if (t > max_total) max_total = t;
        }
    }
    EXPECT_GT(max_total, 0)
        << "Expected the Keldon to render with non-zero pixels under a "
           "directional light.";
}
```

If `renderer::Lighting`'s public field names (`directional_dir`, `directional_color`, `directional_count`) differ from the assumption above, grep for them in `native/src/renderer/include/renderer/frame.h` and adapt the test to the actual field names before proceeding.

- [ ] **Step 2: Run test to verify it fails (or at minimum compiles incorrectly)**

Run: `cmake --build build --target renderer_tests -j && ./build/native/tests/renderer/renderer_tests --gtest_filter='*SpecularShipRenders*' 2>&1 | tail -30`

Expected outcome depends on starting state:
- If the test compiles and runs, the assertion may pass trivially because the shader currently ignores spec. That's acceptable — the test is a smoke test, not a differential. The point is it passes BEFORE and AFTER, with no GL errors after the spec uniforms are wired up.
- If the test fails to compile (e.g., field name mismatch in `Lighting`), fix the test to match the actual API.

- [ ] **Step 3: Update opaque.vert to emit world-space position**

Modify `native/src/renderer/shaders/opaque.vert`. Add a new varying and emit it:

```glsl
#version 330 core

layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 3) in vec4 a_color;
layout(location = 4) in vec4 a_bone_indices;
layout(location = 5) in vec4 a_bone_weights;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;

void main() {
    vec4 ws = u_model * vec4(a_position, 1.0);
    v_normal_ws = mat3(u_model) * a_normal;
    v_uv = a_uv;
    v_position_ws = ws.xyz;
    gl_Position = u_proj * u_view * ws;
}
```

- [ ] **Step 4: Update opaque.frag with Blinn-Phong specular term**

Modify `native/src/renderer/shaders/opaque.frag`. Replace the existing content with:

```glsl
#version 330 core

in vec3 v_normal_ws;
in vec2 v_uv;
in vec3 v_position_ws;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;

uniform sampler2D u_glow_map;
uniform vec3 u_emissive_color;

uniform sampler2D u_specular_map;
uniform vec3 u_specular_color;
uniform float u_specular_power;

uniform vec3 u_ambient_light;
uniform vec3 u_camera_pos_ws;

const int MAX_DIR_LIGHTS = 4;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 V = normalize(u_camera_pos_ws - v_position_ws);

    vec3 lit_dir  = vec3(0.0);
    vec3 spec_acc = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        vec3 L  = normalize(u_dir_light_dir_ws[i]);
        float nl = max(dot(n, L), 0.0);
        lit_dir += nl * u_dir_light_color[i];

        vec3 H = normalize(L + V);
        float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);
        spec_acc += s * u_dir_light_color[i];
    }

    vec4 base = texture(u_base_color, v_uv);
    vec3 lit  = (u_ambient_light + lit_dir) * u_diffuse_color * base.rgb;
    vec4 glow = texture(u_glow_map, v_uv);
    vec3 spec = spec_acc * u_specular_color * texture(u_specular_map, v_uv).rgb;

    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a + spec, 1.0);
}
```

- [ ] **Step 5: Bind the spec slot and set uniforms in frame.cc**

Modify `native/src/renderer/frame.cc`. Add the include at the top alongside other renderer headers:

```cpp
#include <renderer/lighting.h>
```

Inside `submit_opaque()` (the function that loops models), after the existing camera/view uniforms are set and before iterating draw_models, derive and upload the world-space camera position. Find the place where the view matrix is bound; immediately after, add:

```cpp
    glm::vec3 cam_pos_ws = glm::vec3(glm::inverse(view)[3]);
    shader.set_vec3("u_camera_pos_ws", cam_pos_ws);
```

(If the local matrix is named `view_matrix` or similar instead of `view`, adapt to the actual identifier in this file.)

Inside `draw_model()` per-mesh loop, immediately after the existing glow-slot binding block (currently around line 63-72, the block that ends with `shader.set_int("u_glow_map", 1);`), insert:

```cpp
            // Opaque pass texture-unit convention: 0 = base, 1 = glow,
            // 2 = specular mask. Each unit owns one sampler uniform.
            const int spec_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Gloss)
            ].texture_index;
            glActiveTexture(GL_TEXTURE2);
            if (spec_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[spec_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, black_fallback);
            }
            shader.set_int  ("u_specular_map",   2);
            shader.set_vec3 ("u_specular_color", mat.specular);
            shader.set_float("u_specular_power",
                renderer::glossiness_to_specular_power(mat.glossiness));
```

The local identifier `black_fallback` already exists at this scope from the glow work. Verify by grepping for `black_fallback` in `frame.cc`; if the variable is named differently, use the actual name.

- [ ] **Step 6: Build and run the renderer smoke test**

Run: `cmake --build build --target renderer_tests -j && ./build/native/tests/renderer/renderer_tests --gtest_filter='FrameTest.*'`
Expected: all FrameTest tests pass, including the new `SpecularShipRendersWithDirectionalLight`. No GL errors.

- [ ] **Step 7: Run the full renderer suite**

Run: `./build/native/tests/renderer/renderer_tests`
Expected: 0 failures across all renderer tests (no regressions in glow, sun, dust, backdrop).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/shaders/opaque.vert \
        native/src/renderer/shaders/opaque.frag \
        native/src/renderer/frame.cc \
        native/tests/renderer/frame_test.cc
git commit -m "feat(renderer): Blinn-Phong specular pass driven by _spec mask"
```

---

## Task 4 — Python host integration smoke test

**Files:**
- Create: `tests/host/test_specular_pass.py`

- [ ] **Step 1: Write the failing test**

Create `tests/host/test_specular_pass.py`:

```python
"""Render a `_specular`-using ship and assert the opaque pass produces
non-black pixels under a directional light.

Smoke test — does not isolate the specular contribution numerically.
The strong assertions live in C++ tests:
  - native/tests/assets/cpu/material_build_test.cc verifies that
    _specular images route to Material::StageSlot::Gloss only.
  - native/tests/renderer/lighting_test.cc pins the gloss -> exponent
    mapping curve.

The Keldon is the smallest BC ship that ships with _specular.tga files
(KeldonTop_specular.tga at all three LODs).
"""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
KELDON_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Keldon" / "Keldon.nif"
KELDON_TEX = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Keldon" / "High"


def test_specular_ship_renders_with_directional_light():
    if not KELDON_NIF.is_file():
        pytest.skip(f"BC asset not available at {KELDON_NIF}")
    if not KELDON_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {KELDON_TEX}")

    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host

    _open_stbc_host.init(640, 360, "test_specular")
    try:
        h = _open_stbc_host.load_model(str(KELDON_NIF), str(KELDON_TEX))
        iid = _open_stbc_host.create_instance(h)
        _open_stbc_host.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        _open_stbc_host.set_camera(
            eye=(0.0, 0.0, 800.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472,
            near=1.0,
            far=100000.0,
        )

        # Ambient + one directional light positioned to put the spec
        # highlight near screen center. Direction is "toward the light",
        # so (0, 0, 1) means light is in front of the camera (same side
        # as the viewer), which puts the half-vector close to the surface
        # normal on the saucer's front face.
        _open_stbc_host.set_lighting(
            (0.1, 0.1, 0.1),
            [((0.0, 0.0, 1.0), (1.0, 1.0, 1.0))],
        )
        _open_stbc_host.frame()

        fw, fh = _open_stbc_host.framebuffer_size()
        cx, cy = fw // 2, fh // 2

        max_brightness = 0
        for dx in range(-60, 61, 20):
            for dy in range(-40, 41, 20):
                r, g, b, _ = _open_stbc_host.read_pixel(cx + dx, cy + dy)
                max_brightness = max(max_brightness, r + g + b)

        assert max_brightness > 0, (
            "Expected Keldon to produce at least one non-black pixel "
            "with ambient + one directional light; sampled grid was "
            "entirely zero."
        )
    finally:
        _open_stbc_host.destroy_instance(iid)
        _open_stbc_host.shutdown()
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
```

Before running, sanity-check the `set_lighting` signature against the existing `test_glow_pass.py` invocation (which passes an empty list). If the directional-light tuple shape differs from `((dir_xyz), (color_rgb))`, adapt to the actual API.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/host/test_specular_pass.py -v 2>&1 | tail -30`
Expected: PASS (or SKIP if Keldon assets aren't present in `game/`). If FAIL: the lighting API likely differs from the assumed tuple shape — adjust the call and re-run.

- [ ] **Step 3: Run the full Python suite to confirm no regressions**

Run: `uv run pytest -q 2>&1 | tail -20`
Expected: 0 failures.

- [ ] **Step 4: Commit**

```bash
git add tests/host/test_specular_pass.py
git commit -m "test(host): smoke test specular rendering on Keldon"
```

---

## Self-Review

**1. Spec coverage:**
- Asset corpus findings → documented in spec (informational, no task)
- Scope decision (gated on _spec presence) → Task 2 (binding to Gloss when image_link in spec set, black fallback in Task 3)
- Glossiness mapping → Task 1
- `filename_is_specular` → Task 2 Step 7
- `material_build.cc` branch on spec detection → Task 2 Step 4
- `material.h` Gloss slot docstring → Task 2 Step 10
- `lighting.h` helper → Task 1
- `opaque.vert` v_position_ws → Task 3 Step 3
- `opaque.frag` Blinn-Phong term → Task 3 Step 4
- `frame.cc` spec binding + u_camera_pos_ws → Task 3 Step 5
- Tests: `test_specular_pass.py` → Task 4. `frame_test.cc` smoke → Task 3. `material_build_test.cc` binding → Task 2. `lighting_test.cc` pin → Task 1. All present.

**2. Placeholder scan:** No TBDs. All code blocks present. All commands explicit.

**3. Type consistency:**
- `specular_image_links` (lowercase, plural with `s`) used in `MaterialInputs`, `TextureLoadResult`, and the `apply_texture_property` signature. Consistent.
- `glossiness_to_specular_power` (snake_case) consistent in header, test, and call site.
- `Material::StageSlot::Gloss` (existing enum value) used throughout.
- `u_specular_map`, `u_specular_color`, `u_specular_power`, `u_camera_pos_ws` consistent between vert/frag/frame.cc.

**4. Spec divergence note:**
The spec's test section described a "differential" Python test (render with and without the spec mask, assert difference). Implementing that cleanly requires either mutating an `AssetCache`-owned model post-load (likely const) or adding a host-side "disable spec" debug knob — both outside the gating-only scope of this design. The plan instead places the *binding correctness* assertion in `material_build_test.cc` (deterministic, no rendering) and the *math correctness* assertion in `lighting_test.cc` (deterministic, no rendering), keeping the renderer/host tests as smoke tests. Update the spec's "Tests" section to match, or treat the differential as a deferred follow-on. Tracked here so the divergence is visible.
