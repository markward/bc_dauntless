# Hull Damage Tessellation — Plan 4b: Displacement Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make damaged hulls visibly cave in — a GPU tessellation draw path that subdivides ship patches and displaces them inward per the body-frame crater field, weighted by the per-vertex crushability attribute, reusing the existing fragment shader for all lighting/decal shading.

**Architecture:** A new `deform` shader program (`#version 410`: vertex → tessellation-control → tessellation-evaluation) that **reuses `opaque.frag` unchanged** as its fragment stage — the TES emits the exact varyings `opaque.frag` consumes (`v_position_ws`, `v_normal_ws`, `v_uv`). Displacement is computed in the ship body frame (the frame the craters live in): the TES maps each generated vertex local→world (`u_model`)→body (`u_ship_world_inv`), sums crater contributions (depth × radial falloff × interpolated crushability, along each crater's `impact_dir_body`), then maps the displaced point body→world (`u_ship_world`). The opaque pass routes an instance through this program — drawn as `GL_PATCHES` — only when tessellation is available AND the instance has ≥1 crater; everything else keeps the untouched static `GL_TRIANGLES` path. Built identity-first: the pipeline, routing, and crater uniforms land with a zero-displacement shader (byte-identical render) before the displacement math, so the plumbing is proven before the hard part.

**Tech Stack:** C++20, OpenGL 4.1 core (tessellation), GLSL 410 (tess stages) + 330 (reused fragment), GLM, GoogleTest (renderer GPU suite, offscreen FBO + glReadPixels).

**Spec:** `docs/superpowers/specs/2026-06-16-hull-damage-tessellation-design.md` — §Architecture.3 (GPU pipeline: adaptive TCS, TES displacement + normal recompute, crater uniform upload, GL_PATCHES draw path gated on tessellation_available), §8 (fallback when tessellation unavailable).

**Branch:** create `feat/hull-damage-displacement` off `main` (Plans 1–4a merged).

---

## Key facts for the implementer (you have zero context — read these)

- bc_dauntless is an open C++ reimplementation of Star Trek: Bridge Commander. ONE build tree at the project root. Always: `cmake -B build -S . && cmake --build build -j` from `/Users/mward/Documents/Projects/bc_dauntless`. **NEVER** run cmake inside `native/`.
- **The renderer is OpenGL 4.1 core** (Plan 1). `renderer::Shader` has a 4-arg constructor `Shader(vs, tcs, tes, fs)` for tessellation programs (`native/src/renderer/include/renderer/shader.h`). `renderer::query_gl_caps()` returns `GlCaps{version_major, version_minor, tessellation_available}` (`native/src/renderer/include/renderer/gl_caps.h`); it must be called with a current GL context.
- **Shaders are embedded, not loaded from disk.** CMake's `embed_shader(VAR path symbol)` in `native/src/renderer/CMakeLists.txt` generates `embedded_<symbol>.h` with `constexpr const char* renderer::shader_src::<symbol>`. Add `embed_shader(...)` calls and `#include` the headers in `pipeline.cc`. Pass `renderer::shader_src::<symbol>` to the `Shader` ctor. Pattern: see the existing `opaque_vs`/`opaque_fs` and the `passthrough_tess_*` set from Plan 1.
- **`opaque.frag`** (`native/src/renderer/shaders/opaque.frag`, `#version 330 core`) consumes exactly three varyings: `in vec3 v_normal_ws; in vec2 v_uv; in vec3 v_position_ws;`. It reconstructs body-frame position/normal itself (via `u_ship_world_inv`) for decals, does all lighting, decals, glow, rim. The deform TES MUST emit those three varyings (world space) and nothing else is required of it. **Mixed GLSL versions across stages in one program are legal** (each stage declares its own `#version`; the linker validates the in/out interface). Task 1 verifies the 410-tess + 330-frag program links on this GL stack.
- **Vertex attributes** (`mesh_upload.cc`): location 0 `a_position` (vec3), 1 `a_normal` (vec3), 2 `a_uv` (vec2), 7 `a_crushability` (float, added in Plan 4a). The deform vertex shader reads 0, 1, 2, 7.
- **`Pipeline`** (`native/src/renderer/include/renderer/pipeline.h` + `pipeline.cc`) owns shader programs as `std::unique_ptr<Shader>` and exposes `Shader& opaque_shader()` etc. Its constructor runs with a current GL context (it builds shaders), so it can call `query_gl_caps()`.
- **`frame.cc` `draw_model`** (`native/src/renderer/frame.cc`) draws a model: walks nodes, sets `u_model` per node, binds the VAO, `glDrawElements(GL_TRIANGLES, ...)`. It already uploads damage-decal uniforms per-instance by looping `decals.slots()` and packing into `u_decal_a/b/c` vec4 arrays + `u_decal_count` + `u_ship_world_inv` — **mirror this exact pattern** for craters. The opaque submission `for_each_visible` passes `inst.decals`; add `inst.craters`.
- **Per-instance data:** `scenegraph::Instance` has `HullCraterField craters` (`craters.slots()` → `std::array<HullCrater, 24>`; `craters.count()`). `HullCrater{point_body, impact_dir_body, normal_body, radius, depth, seq, active}` (`native/src/scenegraph/include/scenegraph/hull_craters.h`). All body-frame, model units.
- **Coordinate frames (critical):** `u_model = instance_world * node_world` (per node). `u_ship_world = instance_world`. `u_ship_world_inv = inverse(instance_world)`. For a vertex: `world = u_model * local`; `body = u_ship_world_inv * world` (= `node_world * local`, the instance-body frame the craters live in); after displacing in body frame, `world = u_ship_world * displaced_body`. Column-vector convention throughout (CLAUDE.md). `inst.world` IS `instance_world`; `frame.cc` already computes `glm::inverse(world)` for `u_ship_world_inv` — also pass `world` itself as `u_ship_world`.
- **Tests:** renderer GPU tests create a hidden `renderer::Window` (skip via `GTEST_SKIP()` on `std::runtime_error` if no GL), and render-and-readback with `glReadPixels`. Mirror `native/tests/renderer/tess_program_test.cc` (Plan 1) for a self-contained patch-render test, and `particle_pass_test.cc` for the `Window`+`Pipeline` fixture. Register new tests in `native/tests/renderer/CMakeLists.txt`.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `native/src/renderer/shaders/opaque_deform.vert` | `#version 410` VS: forward attributes (incl. crushability) to TCS | Create |
| `native/src/renderer/shaders/opaque_deform.tesc` | `#version 410` TCS: pass control points; set tess levels | Create |
| `native/src/renderer/shaders/opaque_deform.tese` | `#version 410` TES: interpolate, displace in body frame, emit world varyings | Create |
| `native/src/renderer/CMakeLists.txt` | Embed the three deform shaders | Modify |
| `native/src/renderer/include/renderer/pipeline.h` | `deform_shader()` + `tessellation_available()` accessors | Modify |
| `native/src/renderer/pipeline.cc` | Build `deform_` (4-arg ctor, `opaque_fs`) when tessellation available | Modify |
| `native/src/renderer/frame.cc` | `u_ship_world` + crater uniform upload; deform draw-path routing | Modify |
| `native/tests/renderer/deform_pipeline_test.cc` | Link test, identity render, displacement-changes-output test | Create |
| `native/tests/renderer/CMakeLists.txt` | Register the test file | Modify |

---

## Task 1: The `deform` shader set (identity) + link test

Author the three `#version 410` tessellation stages doing an **identity** transform (no displacement yet — just reproduce `opaque.vert`'s world-space output through the tessellator), embed them, and prove the program links against `opaque.frag` (validates mixed-version linking + the varying interface).

**Files:**
- Create: `native/src/renderer/shaders/opaque_deform.vert`, `.tesc`, `.tese`
- Modify: `native/src/renderer/CMakeLists.txt`
- Test: `native/tests/renderer/deform_pipeline_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

- [ ] **Step 1: Create the vertex shader** — `native/src/renderer/shaders/opaque_deform.vert`:

```glsl
#version 410 core
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 7) in float a_crushability;

out vec3  vcp_pos;       // local-space control point (pre-u_model)
out vec3  vcp_normal;    // local-space normal
out vec2  vcp_uv;
out float vcp_crush;

void main() {
    vcp_pos    = a_position;
    vcp_normal = a_normal;
    vcp_uv     = a_uv;
    vcp_crush  = a_crushability;
}
```

- [ ] **Step 2: Create the tessellation control shader** — `native/src/renderer/shaders/opaque_deform.tesc`:

```glsl
#version 410 core
layout(vertices = 3) out;

in  vec3  vcp_pos[];
in  vec3  vcp_normal[];
in  vec2  vcp_uv[];
in  float vcp_crush[];

out vec3  tcp_pos[];
out vec3  tcp_normal[];
out vec2  tcp_uv[];
out float tcp_crush[];

void main() {
    tcp_pos[gl_InvocationID]    = vcp_pos[gl_InvocationID];
    tcp_normal[gl_InvocationID] = vcp_normal[gl_InvocationID];
    tcp_uv[gl_InvocationID]     = vcp_uv[gl_InvocationID];
    tcp_crush[gl_InvocationID]  = vcp_crush[gl_InvocationID];

    if (gl_InvocationID == 0) {
        // Identity tessellation (level 1); Task 6 makes this adaptive.
        gl_TessLevelInner[0] = 1.0;
        gl_TessLevelOuter[0] = 1.0;
        gl_TessLevelOuter[1] = 1.0;
        gl_TessLevelOuter[2] = 1.0;
    }
}
```

- [ ] **Step 3: Create the tessellation evaluation shader** — `native/src/renderer/shaders/opaque_deform.tese`:

```glsl
#version 410 core
layout(triangles, equal_spacing, ccw) in;

in  vec3  tcp_pos[];
in  vec3  tcp_normal[];
in  vec2  tcp_uv[];
in  float tcp_crush[];

uniform mat4 u_model;   // instance_world * node_world (local -> world)
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_normal_ws;   // matches opaque.frag inputs
out vec2 v_uv;
out vec3 v_position_ws;

vec3 bary3(vec3 a, vec3 b, vec3 c) {
    return gl_TessCoord.x * a + gl_TessCoord.y * b + gl_TessCoord.z * c;
}

void main() {
    vec3  local_pos = bary3(tcp_pos[0], tcp_pos[1], tcp_pos[2]);
    vec3  local_n   = normalize(bary3(tcp_normal[0], tcp_normal[1], tcp_normal[2]));
    vec2  uv        = gl_TessCoord.x * tcp_uv[0]
                    + gl_TessCoord.y * tcp_uv[1]
                    + gl_TessCoord.z * tcp_uv[2];

    vec3 world_pos = (u_model * vec4(local_pos, 1.0)).xyz;
    vec3 world_n   = normalize(mat3(u_model) * local_n);

    v_position_ws = world_pos;
    v_normal_ws   = world_n;
    v_uv          = uv;
    gl_Position   = u_proj * u_view * vec4(world_pos, 1.0);
}
```

(This is the byte-identical-to-`opaque.vert` output, just routed through the tessellator. `tcp_crush` is forwarded but unused until Task 5 — that's fine.)

- [ ] **Step 4: Embed the three shaders**

In `native/src/renderer/CMakeLists.txt`, after the existing `embed_shader(...)` calls, add:

```cmake
embed_shader(SHADER_OPAQUE_DEFORM_VS  shaders/opaque_deform.vert opaque_deform_vs)
embed_shader(SHADER_OPAQUE_DEFORM_TCS shaders/opaque_deform.tesc opaque_deform_tcs)
embed_shader(SHADER_OPAQUE_DEFORM_TES shaders/opaque_deform.tese opaque_deform_tes)
```

(`embed_shader` runs `configure_file` at configure time and the generated headers land in the renderer binary dir, already on its include path — same as every other shader; no extra wiring.)

- [ ] **Step 5: Write the link test**

Create `native/tests/renderer/deform_pipeline_test.cc`:

```cpp
// native/tests/renderer/deform_pipeline_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/shader.h>
#include <renderer/window.h>

#include "embedded_opaque_deform_vs.h"
#include "embedded_opaque_deform_tcs.h"
#include "embedded_opaque_deform_tes.h"
#include "embedded_opaque_fs.h"

namespace {

TEST(DeformPipeline, ProgramLinksWithOpaqueFragment) {
    try {
        renderer::Window w(64, 64, "deform-link-test", /*visible=*/false);
        // 410 tess stages + 330 opaque fragment: mixed-version program must
        // link, and the TES out-varyings must match opaque.frag in-varyings.
        renderer::Shader prog(renderer::shader_src::opaque_deform_vs,
                              renderer::shader_src::opaque_deform_tcs,
                              renderer::shader_src::opaque_deform_tes,
                              renderer::shader_src::opaque_fs);
        EXPECT_NE(prog.program(), 0u);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
```

Register `deform_pipeline_test.cc` in `native/tests/renderer/CMakeLists.txt`'s `add_executable(renderer_tests ...)` list. (The embedded `opaque_*` headers are already on `renderer_tests`' include path — `tess_program_test.cc` from Plan 1 includes embedded headers the same way; follow it.)

- [ ] **Step 6: Build and run**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline.ProgramLinksWithOpaqueFragment" --output-on-failure`
Expected: PASS (or SKIP with no GL). A link failure here means either mixed-version linking is rejected on this stack or the TES varyings don't match `opaque.frag` — if so, report the exact `Shader tess link failed:` message; the fallback is to author an `opaque_deform.frag` (`#version 410`) duplicating `opaque.frag`, but try the reuse first.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/shaders/opaque_deform.vert \
        native/src/renderer/shaders/opaque_deform.tesc \
        native/src/renderer/shaders/opaque_deform.tese \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/deform_pipeline_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): add identity deform tessellation shaders + link test"
```

---

## Task 2: Pipeline `deform_` program + tessellation-available flag

**Files:**
- Modify: `native/src/renderer/include/renderer/pipeline.h`
- Modify: `native/src/renderer/pipeline.cc`
- Test: `native/tests/renderer/deform_pipeline_test.cc` (append)

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/deform_pipeline_test.cc` (add `#include <renderer/pipeline.h>` to the includes):

```cpp
TEST(DeformPipeline, PipelineExposesDeformShaderWhenTessellationAvailable) {
    try {
        renderer::Window w(64, 64, "deform-pipeline-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        // The test GL context is >= 4.1, so tessellation is available and the
        // deform program is built.
        EXPECT_TRUE(pipeline.tessellation_available());
        EXPECT_NE(pipeline.deform_shader().program(), 0u);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j --target renderer_tests`
Expected: FAIL to compile — `Pipeline` has no `tessellation_available()` / `deform_shader()`.

- [ ] **Step 3: Declare the accessors**

In `native/src/renderer/include/renderer/pipeline.h`, add to the public section (next to `opaque_shader()`):

```cpp
    /// Deform (hull-deformation tessellation) program. Only valid when
    /// tessellation_available() is true; otherwise null-program (do not use).
    Shader& deform_shader() noexcept { return *deform_; }
    bool tessellation_available() const noexcept { return tessellation_available_; }
```

and to the private members (next to the other `std::unique_ptr<Shader>` members):

```cpp
    std::unique_ptr<Shader> deform_;
    bool tessellation_available_ = false;
```

- [ ] **Step 4: Build the deform program conditionally**

In `native/src/renderer/pipeline.cc`, add the embedded includes near the other `embedded_*` includes:

```cpp
#include "embedded_opaque_deform_vs.h"
#include "embedded_opaque_deform_tcs.h"
#include "embedded_opaque_deform_tes.h"
```

and add `#include "renderer/gl_caps.h"` to the includes.

In the `Pipeline` constructor, after the existing shader builds, add:

```cpp
    // Hull-deformation tessellation program (GL 4.0+). Reuses opaque.frag as
    // the fragment stage (the TES emits the matching varyings). Falls back to
    // the static opaque path when tessellation is unavailable (spec §8).
    tessellation_available_ = query_gl_caps().tessellation_available;
    if (tessellation_available_) {
        deform_ = std::make_unique<Shader>(shader_src::opaque_deform_vs,
                                           shader_src::opaque_deform_tcs,
                                           shader_src::opaque_deform_tes,
                                           shader_src::opaque_fs);
    }
```

- [ ] **Step 5: Run to verify it passes**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline" --output-on-failure`
Expected: both DeformPipeline tests PASS (or SKIP).

- [ ] **Step 6: Run the full renderer suite (no regression from the Pipeline change)**

Run: `ctest --test-dir build -R "Pipeline|Shader|DeformPipeline|TessProgram" --output-on-failure`
Expected: all PASS/SKIPPED.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc native/tests/renderer/deform_pipeline_test.cc
git commit -m "feat(renderer): build deform tessellation program when GL supports it"
```

---

## Task 3: Crater uniform upload + `u_ship_world` in `draw_model`

Add the per-instance crater uniform upload (mirroring the decal pattern) and the `u_ship_world` (instance world) uniform that the TES needs for body→world. The crater uniforms are set unconditionally; only the deform program declares/reads them (the opaque program silently ignores unknown uniforms via `Shader::set_*`'s `loc >= 0` guard), so this is safe and keeps `draw_model` uniform.

**Files:**
- Modify: `native/src/renderer/frame.cc`

- [ ] **Step 1: Add `craters` to `draw_model`'s signature and the crater uniform upload**

In `native/src/renderer/frame.cc`, add a `const scenegraph::HullCraterField& craters` parameter to `draw_model` (next to the existing `const scenegraph::DamageDecalRing& decals` parameter), and update the forward declaration in `frame.h` if one exists.

In the per-instance uniform-upload block (right after the existing decal upload block that sets `u_decal_*` / `u_ship_world_inv`), add the crater upload, packing `HullCrater` into two vec4 arrays:

```cpp
    {
        constexpr int kMaxCraters =
            static_cast<int>(scenegraph::HullCraterField::kMaxCraters);
        glm::vec4 ca[kMaxCraters];  // point_body.xyz, depth
        glm::vec4 cb[kMaxCraters];  // impact_dir_body.xyz, radius
        int cn = 0;
        for (const auto& c : craters.slots()) {
            if (!c.active) continue;
            ca[cn] = glm::vec4(c.point_body, c.depth);
            cb[cn] = glm::vec4(c.impact_dir_body, c.radius);
            ++cn;
        }
        prog.set_int("u_crater_count", cn);
        if (cn > 0) {
            prog.set_vec4_array("u_crater_a", ca, cn);
            prog.set_vec4_array("u_crater_b", cb, cn);
            prog.set_mat4("u_ship_world", world);          // body -> world (TES)
            prog.set_mat4("u_ship_world_inv", glm::inverse(world));  // world -> body
        }
    }
```

(`u_ship_world_inv` is already set by the decal block; setting it again here is harmless and keeps the crater block self-contained. `world` is the instance world matrix already in scope in `draw_model`.)

- [ ] **Step 2: Pass `inst.craters` at the call site**

In the opaque submission (`for_each_visible` / `submit_opaque`), update the `draw_model(...)` call(s) to pass `inst.craters` in the new parameter position (alongside the existing `inst.decals`).

- [ ] **Step 3: Build and confirm no regression**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: full suite PASS/SKIPPED. (No behavior change yet: the opaque program ignores `u_crater_*`; the deform program isn't routed to until Task 4. This step just confirms the signature change + uniform upload compiles and breaks nothing.)

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/frame.cc native/src/renderer/include/renderer/frame.h
git commit -m "feat(renderer): upload hull-crater uniforms + u_ship_world in draw_model"
```

(If `frame.h` has no `draw_model` declaration to update, omit it from the `git add`.)

---

## Task 4: Route damaged ships through the deform path (identity = no visual change)

In the opaque pass, draw an instance through the deform program as `GL_PATCHES` when tessellation is available AND the instance has ≥1 crater; otherwise keep the static `GL_TRIANGLES` opaque path. With the identity deform shader (Tasks 1–3), a damaged ship renders identically — this proves routing + patches + uniforms end-to-end before displacement.

**Files:**
- Modify: `native/src/renderer/frame.cc`
- Test: `native/tests/renderer/deform_pipeline_test.cc` (append)

- [ ] **Step 1: Write the test**

Append to `native/tests/renderer/deform_pipeline_test.cc` a test that renders a single triangle patch through the deform program with **zero craters** and confirms it rasterizes white (identity path produces output). This is a focused stand-in for "the deform path draws correctly"; full-scene routing is exercised by the manual check in Task 8.

```cpp
TEST(DeformPipeline, IdentityPatchRasterizes) {
    try {
        renderer::Window w(64, 64, "deform-identity-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        // One triangle patch in NDC, fed straight through (identity model/view/
        // proj), crater count 0 -> no displacement. Attribute 0 = position;
        // attributes 1,2,7 default to 0 (unused by the identity output path).
        const float verts[] = {
            -0.5f, -0.5f, 0.0f,
             0.5f, -0.5f, 0.0f,
             0.0f,  0.5f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);

        glViewport(0, 0, 64, 64);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        prog.use();
        glm::mat4 I(1.0f);
        prog.set_mat4("u_model", I);
        prog.set_mat4("u_view", I);
        prog.set_mat4("u_proj", I);
        prog.set_int("u_crater_count", 0);
        // opaque.frag needs a base color sample; with no bound texture the
        // sampler reads 0, but the emissive/ambient path still writes alpha 1.
        while (glGetError() != GL_NO_ERROR) {}
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 3);

        unsigned char px[4] = {0, 0, 0, 0};
        glReadPixels(32, 24, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        EXPECT_EQ(px[3], 255);  // fragment shader ran and wrote alpha=1 at the patch

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

(The alpha==255 assertion is robust: `opaque.frag` always writes `frag_color.a = 1.0` for covered fragments regardless of lighting/textures, so a covered centroid pixel proves the deform program rasterized.)

- [ ] **Step 2: Run to verify it passes** (the program already works from Task 2)

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline.IdentityPatchRasterizes" --output-on-failure`
Expected: PASS (or SKIP). If it fails on a missing uniform/GL error, fix before proceeding.

- [ ] **Step 3: Add the routing in the opaque submission**

In `native/src/renderer/frame.cc`, find the opaque `for_each_visible` block that calls `draw_model(...)` with `pipeline.opaque_shader()`. Choose the deform program for damaged ships when available. Replace the shader selection so each instance picks its program:

```cpp
    world.for_each_visible([&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        if (!m) return;
        const bool rim_active = dauntless_rim::enabled() && inst.rim_eligible;
        // Route damaged ships through the deform (tessellation) path; everything
        // else uses the static opaque path. Gated on tessellation availability
        // (spec §8 fallback) and on having at least one crater.
        const bool deform = pipeline.tessellation_available()
                            && inst.craters.count() > 0;
        Shader& prog = deform ? pipeline.deform_shader() : pipeline.opaque_shader();
        draw_model(*m, inst.world, prog, pipeline.skinned_shader(),
                   white, black, rim_active,
                   inst.decals, inst.craters, inst.glow_regions, decal_time,
                   inst.emissive_scale, palette, deform);
    });
```

`draw_model` needs to know whether to draw patches: add a trailing `bool use_patches` parameter. In `draw_model`, where it issues the draw call, branch on it:

```cpp
            if (use_patches) {
                glPatchParameteri(GL_PATCH_VERTICES, 3);
                glDrawElements(GL_PATCHES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
            } else {
                glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
            }
```

(Skinned meshes: the deform path is for static ship hulls; if `draw_model` selects the skinned program for skinned meshes, leave those on `GL_TRIANGLES` — i.e. only use patches for the non-skinned branch. Match the existing skinned/non-skinned branch in `draw_model` and apply `use_patches` only to the non-skinned draw.)

- [ ] **Step 4: Build and confirm no regression (identity = unchanged render)**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: full suite PASS/SKIPPED. The deform path is now live for damaged ships but produces identical geometry (identity displacement), so nothing visual changes.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/frame.cc native/src/renderer/include/renderer/frame.h native/tests/renderer/deform_pipeline_test.cc
git commit -m "feat(renderer): route damaged ships through the deform tessellation path"
```

---

## Task 5: TES displacement — the dents

Replace the identity TES with the body-frame crater displacement. This is the first task that changes pixels.

**Files:**
- Modify: `native/src/renderer/shaders/opaque_deform.tese`
- Test: `native/tests/renderer/deform_pipeline_test.cc` (append)

- [ ] **Step 1: Write the failing test**

Append a test that renders the same patch twice — once with no crater, once with a crater whose displacement is large enough to move the geometry — and asserts the rendered images DIFFER. (This proves displacement is live and affects what's drawn, without asserting an exact dent shape.)

```cpp
TEST(DeformPipeline, CraterDisplacesGeometry) {
    try {
        renderer::Window w(64, 64, "deform-displace-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        // A full-screen-ish quad as two triangle patches at z=0, normal +z,
        // so a crater pushing along -z (impact dir) moves it toward/along view.
        const float verts[] = {
            -0.8f, -0.8f, 0.0f,  0.8f, -0.8f, 0.0f,  0.8f,  0.8f, 0.0f,
            -0.8f, -0.8f, 0.0f,  0.8f,  0.8f, 0.0f, -0.8f,  0.8f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        // crushability attribute (loc 7) is not in this VBO; the attribute
        // defaults to 0, which would zero the displacement. Force it to 1 via a
        // constant generic attribute so the displacement is visible.
        glVertexAttrib1f(7, 1.0f);

        auto render = [&](int crater_count) {
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
            prog.set_int("u_crater_count", crater_count);
            if (crater_count > 0) {
                // Crater centred on the quad, large radius + deep, pushing along
                // +x so geometry shifts sideways in screen space.
                glm::vec4 ca(0.0f, 0.0f, 0.0f, 0.6f);   // point_body, depth
                glm::vec4 cb(1.0f, 0.0f, 0.0f, 2.0f);   // impact_dir +x, radius
                prog.set_vec4_array("u_crater_a", &ca, 1);
                prog.set_vec4_array("u_crater_b", &cb, 1);
            }
            while (glGetError() != GL_NO_ERROR) {}
            glPatchParameteri(GL_PATCH_VERTICES, 3);
            glDrawArrays(GL_PATCHES, 0, 6);
        };

        std::vector<unsigned char> a(64 * 64 * 4), b(64 * 64 * 4);
        render(0);
        glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, a.data());
        render(1);
        glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, b.data());
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        EXPECT_NE(a, b) << "crater displacement did not change the rendered image";

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

Add `#include <vector>` to the test file's includes if not present.

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline.CraterDisplacesGeometry" --output-on-failure`
Expected: FAIL — `a == b` (identity TES ignores craters, so the crater-on render equals the crater-off render).

- [ ] **Step 3: Add displacement to the TES**

Replace `native/src/renderer/shaders/opaque_deform.tese` with the displacing version (adds the crater uniforms, the body-frame transform chain, and the displacement sum):

```glsl
#version 410 core
layout(triangles, equal_spacing, ccw) in;

in  vec3  tcp_pos[];
in  vec3  tcp_normal[];
in  vec2  tcp_uv[];
in  float tcp_crush[];

uniform mat4 u_model;          // instance_world * node_world (local -> world)
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_ship_world;     // instance_world (body -> world)
uniform mat4 u_ship_world_inv; // inverse(instance_world) (world -> body)

const int MAX_CRATERS = 24;
uniform int  u_crater_count;
uniform vec4 u_crater_a[MAX_CRATERS];  // point_body.xyz, depth
uniform vec4 u_crater_b[MAX_CRATERS];  // impact_dir_body.xyz, radius

out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;

vec3 bary3(vec3 a, vec3 b, vec3 c) {
    return gl_TessCoord.x * a + gl_TessCoord.y * b + gl_TessCoord.z * c;
}

// Body-frame displacement at a body-space point, weighted by per-vertex
// crushability. Each crater pushes along its impact direction; contribution
// falls off smoothly to zero at the crater radius.
vec3 crater_displacement(vec3 p_body, float crush) {
    vec3 disp = vec3(0.0);
    for (int i = 0; i < u_crater_count; ++i) {
        vec3  c_pt   = u_crater_a[i].xyz;
        float depth  = u_crater_a[i].w;
        vec3  dir    = u_crater_b[i].xyz;
        float radius = u_crater_b[i].w;
        if (radius <= 0.0) continue;
        float r = length(p_body - c_pt) / radius;   // 0 center, 1 edge
        if (r >= 1.0) continue;
        float fall = 1.0 - r * r;                    // smooth radial falloff
        fall *= fall;
        disp += depth * fall * crush * dir;
    }
    return disp;
}

void main() {
    vec3  local_pos = bary3(tcp_pos[0], tcp_pos[1], tcp_pos[2]);
    vec3  local_n   = normalize(bary3(tcp_normal[0], tcp_normal[1], tcp_normal[2]));
    vec2  uv        = gl_TessCoord.x * tcp_uv[0]
                    + gl_TessCoord.y * tcp_uv[1]
                    + gl_TessCoord.z * tcp_uv[2];
    float crush     = gl_TessCoord.x * tcp_crush[0]
                    + gl_TessCoord.y * tcp_crush[1]
                    + gl_TessCoord.z * tcp_crush[2];

    vec3 world_pos = (u_model * vec4(local_pos, 1.0)).xyz;
    vec3 body_pos  = (u_ship_world_inv * vec4(world_pos, 1.0)).xyz;

    vec3 disp_body      = crater_displacement(body_pos, crush);
    vec3 displaced_body = body_pos + disp_body;
    vec3 displaced_world = (u_ship_world * vec4(displaced_body, 1.0)).xyz;

    // Normal still from the undisplaced surface; Task 7 recomputes it.
    vec3 world_n = normalize(mat3(u_model) * local_n);

    v_position_ws = displaced_world;
    v_normal_ws   = world_n;
    v_uv          = uv;
    gl_Position   = u_proj * u_view * vec4(displaced_world, 1.0);
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline" --output-on-failure`
Expected: all DeformPipeline tests PASS (the identity-patch test still passes — crater_count 0 → no displacement; the new test passes — crater changes the image).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque_deform.tese native/tests/renderer/deform_pipeline_test.cc
git commit -m "feat(renderer): displace hull geometry from craters in the deform TES"
```

---

## Task 6: Adaptive tessellation level (TCS)

Replace the constant level-1 tessellation with a per-patch level driven by crater proximity and camera distance, so only patches near damage (and near the camera) are finely subdivided.

**Files:**
- Modify: `native/src/renderer/shaders/opaque_deform.tesc`
- Test: `native/tests/renderer/deform_pipeline_test.cc` (append a no-crash smoke test)

- [ ] **Step 1: Replace the TCS with an adaptive level**

Replace `native/src/renderer/shaders/opaque_deform.tesc` with:

```glsl
#version 410 core
layout(vertices = 3) out;

in  vec3  vcp_pos[];
in  vec3  vcp_normal[];
in  vec2  vcp_uv[];
in  float vcp_crush[];

out vec3  tcp_pos[];
out vec3  tcp_normal[];
out vec2  tcp_uv[];
out float tcp_crush[];

uniform mat4 u_model;          // local -> world
uniform mat4 u_ship_world_inv; // world -> body
uniform vec3 u_camera_pos_ws;  // world-space camera (already a frame uniform)

const int MAX_CRATERS = 24;
uniform int  u_crater_count;
uniform vec4 u_crater_a[MAX_CRATERS];  // point_body.xyz, depth
uniform vec4 u_crater_b[MAX_CRATERS];  // impact_dir_body.xyz, radius

const float MAX_TESS = 16.0;   // cap on subdivision (tuned by eye/perf)
const float MIN_TESS = 1.0;

// Patch centroid in body frame.
vec3 patch_body_centroid() {
    vec3 c_local = (vcp_pos[0] + vcp_pos[1] + vcp_pos[2]) / 3.0;
    vec3 c_world = (u_model * vec4(c_local, 1.0)).xyz;
    return (u_ship_world_inv * vec4(c_world, 1.0)).xyz;
}

float patch_tess_level() {
    if (u_crater_count == 0) return MIN_TESS;
    vec3 c_body = patch_body_centroid();
    // Strongest proximity to any crater: 1 at a crater centre, 0 beyond ~2*radius.
    float prox = 0.0;
    for (int i = 0; i < u_crater_count; ++i) {
        float radius = u_crater_b[i].w;
        if (radius <= 0.0) continue;
        float d = length(c_body - u_crater_a[i].xyz);
        prox = max(prox, clamp(1.0 - d / (2.0 * radius), 0.0, 1.0));
    }
    return mix(MIN_TESS, MAX_TESS, prox);
}

void main() {
    tcp_pos[gl_InvocationID]    = vcp_pos[gl_InvocationID];
    tcp_normal[gl_InvocationID] = vcp_normal[gl_InvocationID];
    tcp_uv[gl_InvocationID]     = vcp_uv[gl_InvocationID];
    tcp_crush[gl_InvocationID]  = vcp_crush[gl_InvocationID];

    if (gl_InvocationID == 0) {
        float L = patch_tess_level();
        gl_TessLevelInner[0] = L;
        gl_TessLevelOuter[0] = L;
        gl_TessLevelOuter[1] = L;
        gl_TessLevelOuter[2] = L;
    }
}
```

(`u_camera_pos_ws` is declared for a future camera-distance term but the first cut keys only on crater proximity; leaving the uniform in place lets Plan-later work add a distance falloff without a shader-interface change. It is already a frame uniform name used by `opaque.frag`.)

**Note for the implementer:** the TCS now reads `u_model`, `u_ship_world_inv`, and `u_crater_*`. Those are already uploaded per-instance in `draw_model` (Task 3) and set on `prog` (the deform program), so the TCS sees them — no new upload needed. Confirm the deform program's `u_ship_world_inv`/`u_crater_*` are set before the draw (they are, from Task 3's block, when `cn > 0`). When `cn == 0` the instance isn't routed to the deform path at all (Task 4 gate), so the TCS's `u_crater_count` is only read when > 0.

- [ ] **Step 2: Append a smoke test** (adaptive tessellation correctness is not readback-testable; assert it still renders without error)

```cpp
TEST(DeformPipeline, AdaptiveTessellationRendersWithoutError) {
    try {
        renderer::Window w(64, 64, "deform-adaptive-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        const float verts[] = {
            -0.8f, -0.8f, 0.0f,  0.8f, -0.8f, 0.0f,  0.0f,  0.8f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        glVertexAttrib1f(7, 1.0f);

        glViewport(0, 0, 64, 64);
        glClear(GL_COLOR_BUFFER_BIT);
        prog.use();
        glm::mat4 I(1.0f);
        prog.set_mat4("u_model", I);
        prog.set_mat4("u_view", I);
        prog.set_mat4("u_proj", I);
        prog.set_mat4("u_ship_world", I);
        prog.set_mat4("u_ship_world_inv", I);
        prog.set_int("u_crater_count", 1);
        glm::vec4 ca(0.0f, 0.0f, 0.0f, 0.3f);
        glm::vec4 cb(1.0f, 0.0f, 0.0f, 2.0f);
        prog.set_vec4_array("u_crater_a", &ca, 1);
        prog.set_vec4_array("u_crater_b", &cb, 1);
        while (glGetError() != GL_NO_ERROR) {}
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 3);
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

- [ ] **Step 3: Build and run**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline" --output-on-failure`
Expected: all DeformPipeline tests PASS (the displacement test from Task 5 still passes — higher tessellation only refines the same displacement).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/opaque_deform.tesc native/tests/renderer/deform_pipeline_test.cc
git commit -m "feat(renderer): adaptive tessellation level from crater proximity"
```

---

## Task 7: Normal recompute (finite difference)

Recompute the surface normal of the *displaced* geometry so lighting is correct in dents (currently the TES emits the undisplaced normal). Use finite differences: evaluate the displaced position at the patch centroid and at two small tess-coordinate offsets, and take the cross product of the resulting edge vectors.

**Files:**
- Modify: `native/src/renderer/shaders/opaque_deform.tese`
- Test: `native/tests/renderer/deform_pipeline_test.cc` (append)

- [ ] **Step 1: Write the test**

Append a test that renders the displacing quad and asserts the recomputed-normal build still renders without error AND that, with a crater present, the image differs from the flat-normal identity (covered by Task 5's test already). The focused new assertion: the displaced render with a strong directional light produces a different image than the same displacement with normals forced flat — but since we can't toggle normal mode at runtime, assert instead that the displacement test image (Task 5's `b`) remains stable and the render is error-free. Concretely, append:

```cpp
TEST(DeformPipeline, NormalRecomputeRendersWithoutError) {
    try {
        renderer::Window w(64, 64, "deform-normal-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        const float verts[] = {
            -0.8f, -0.8f, 0.0f,  0.8f, -0.8f, 0.0f,  0.8f,  0.8f, 0.0f,
            -0.8f, -0.8f, 0.0f,  0.8f,  0.8f, 0.0f, -0.8f,  0.8f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        glVertexAttrib1f(7, 1.0f);

        glViewport(0, 0, 64, 64);
        glClear(GL_COLOR_BUFFER_BIT);
        prog.use();
        glm::mat4 I(1.0f);
        prog.set_mat4("u_model", I);
        prog.set_mat4("u_view", I);
        prog.set_mat4("u_proj", I);
        prog.set_mat4("u_ship_world", I);
        prog.set_mat4("u_ship_world_inv", I);
        prog.set_int("u_crater_count", 1);
        glm::vec4 ca(0.0f, 0.0f, 0.0f, 0.5f);
        glm::vec4 cb(0.0f, 0.0f, -1.0f, 1.5f);  // push along -z (inward dent)
        prog.set_vec4_array("u_crater_a", &ca, 1);
        prog.set_vec4_array("u_crater_b", &cb, 1);
        while (glGetError() != GL_NO_ERROR) {}
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 6);
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

- [ ] **Step 2: Run to verify it builds/passes against the current TES**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline.NormalRecomputeRendersWithoutError" --output-on-failure`
Expected: PASS (this test renders error-free against the current TES too; it guards the next change from introducing a GL error).

- [ ] **Step 3: Recompute the normal in the TES**

In `native/src/renderer/shaders/opaque_deform.tese`, refactor so the displaced **body** position is produced by a helper, then finite-difference it. Replace the `main()` (keep the uniforms, `bary3`, and `crater_displacement` as-is) with:

```glsl
// Displaced body-frame position for a given barycentric coord. Re-evaluates
// the patch interpolation + crater displacement at an arbitrary (u,v,w).
vec3 displaced_body_at(vec3 bc) {
    vec3 lp = bc.x * tcp_pos[0] + bc.y * tcp_pos[1] + bc.z * tcp_pos[2];
    float cr = bc.x * tcp_crush[0] + bc.y * tcp_crush[1] + bc.z * tcp_crush[2];
    vec3 wp = (u_model * vec4(lp, 1.0)).xyz;
    vec3 bp = (u_ship_world_inv * vec4(wp, 1.0)).xyz;
    return bp + crater_displacement(bp, cr);
}

void main() {
    vec3 bc = gl_TessCoord;
    vec2 uv = bc.x * tcp_uv[0] + bc.y * tcp_uv[1] + bc.z * tcp_uv[2];

    vec3 db = displaced_body_at(bc);

    // Finite-difference the displaced surface in barycentric space for the
    // post-dent normal. Offsets stay inside the triangle by pulling toward the
    // opposite of the dominant coordinate; eps small relative to the patch.
    const float eps = 0.01;
    vec3 bc_u = clamp(bc + vec3( eps, -eps, 0.0), 0.0, 1.0);
    vec3 bc_v = clamp(bc + vec3( eps, 0.0, -eps), 0.0, 1.0);
    vec3 du = displaced_body_at(bc_u) - db;
    vec3 dv = displaced_body_at(bc_v) - db;
    vec3 n_body = normalize(cross(du, dv));

    // Keep the recomputed normal oriented like the original surface normal
    // (cross-product sign depends on offset choice / winding).
    vec3 orig_n_body = normalize(mat3(u_ship_world_inv) * (mat3(u_model)
                       * normalize(bc.x * tcp_normal[0] + bc.y * tcp_normal[1]
                                   + bc.z * tcp_normal[2])));
    if (dot(n_body, orig_n_body) < 0.0) n_body = -n_body;

    vec3 displaced_world = (u_ship_world * vec4(db, 1.0)).xyz;
    vec3 world_n = normalize(mat3(u_ship_world) * n_body);

    v_position_ws = displaced_world;
    v_normal_ws   = world_n;
    v_uv          = uv;
    gl_Position   = u_proj * u_view * vec4(displaced_world, 1.0);
}
```

(If the finite-difference normal degenerates where there is no displacement — `du`/`dv` become the flat-surface edges, whose cross product is still the correct flat normal — so undamaged regions keep their normal. The sign-fix against the original normal guards winding/offset ambiguity.)

- [ ] **Step 4: Run to verify the suite passes**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "DeformPipeline" --output-on-failure`
Expected: all DeformPipeline tests PASS (no GL errors; displacement test still differs from baseline).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque_deform.tese native/tests/renderer/deform_pipeline_test.cc
git commit -m "feat(renderer): recompute displaced surface normals in the deform TES"
```

---

## Task 8: Full build + manual visual verification

**Files:** none (verification)

- [ ] **Step 1: Build the full binary + run the whole suite**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: `build/dauntless` builds; full suite PASS/SKIPPED.

- [ ] **Step 2: Manual visual check (the payoff)**

This task produces the first visible deformation, so a human eyeball is the real verification. Hand off to the user: launch `./build/dauntless`, damage a ship (torpedo/ram), and confirm the hull visibly dents inward at impact locations, that undamaged ships look unchanged, and that lighting on the dents reads correctly. Per project memory, do NOT synthetic-click or screen-capture the user's workstation — the user performs this check. Note the outcome.

- [ ] **Step 3: Record the result**

No commit (no file change). If dents render correctly, Plan 4b is complete: damaged hulls deform via GPU tessellation, gated on tessellation availability + crater presence, with crushability-weighted displacement and recomputed normals. Plan 5 (dent/gouge fragment shading + Modern VFX) and Plan 6 (eligibility + Python wiring) build on this.

---

## Self-Review

**Spec coverage (Plan 4b scope = spec §3 GPU pipeline + §8 fallback):**
- §3 "new `#version 410` tessellation shaders for the deform path; static path keeps `opaque.{vert,frag}`" → Tasks 1 (shaders) reuse `opaque.frag`. ✓
- §3 "TCS sets adaptive tess level: high near craters, ~1 elsewhere" → Task 6. ✓
- §3 "TES displaces … = Σ depth · falloff(dist/radius) · crushability, along impact_dir_body" → Task 5 `crater_displacement`. ✓
- §3 "recomputes the normal by finite-difference" → Task 7. ✓
- §3 "drawn as GL_PATCHES … all other instances use the existing GL_TRIANGLES path" → Task 4 routing + `use_patches`. ✓
- §3 "crater data uploaded as shader uniforms each frame … mirroring the decal uniform upload" → Task 3. ✓
- §3 "gated on tessellation_available AND crater_count > 0" → Task 4 gate; Task 2 builds deform only when available. ✓
- §8 "if 4.1 unavailable, disable the deform pipeline … fall back to the static path" → `tessellation_available_` false → `deform_` null → routing picks `opaque_shader()`. ✓
- Player-always-tessellated (anti-pop) + nearest/largest eligibility cap → **Plan 6** (eligibility manager), not 4b. The 4b gate (crater_count > 0) means damaged ships tessellate; Plan 6 layers the cost cap on top. Noted.
- Phong smoothing of undamaged player hull → **Plan 6** (tied to eligibility/Modern VFX). Not 4b.

**Placeholder scan:** No TBD/TODO. `MAX_TESS = 16`, `eps = 0.01`, falloff curve are documented tunables, not placeholders. The `u_camera_pos_ws` TCS uniform is declared-but-unused-this-cut with an explicit rationale (interface stability for a later distance term) — a deliberate, documented choice.

**Type consistency:** varying names `vcp_*` (vert→tcs), `tcp_*` (tcs→tese), and `v_normal_ws`/`v_uv`/`v_position_ws` (tese→frag, matching `opaque.frag`) are consistent across Tasks 1/5/6/7. Crater uniform packing `u_crater_a` (point_body, depth) / `u_crater_b` (impact_dir_body, radius) is identical in the TES (Tasks 5/7), the TCS (Task 6), and the C++ upload (Task 3). `u_ship_world` / `u_ship_world_inv` / `u_model` semantics match between the C++ upload (Task 3) and all shader stages. `Pipeline::deform_shader()` / `tessellation_available()` (Task 2) are used in `frame.cc` routing (Task 4). `draw_model`'s new params (`const HullCraterField& craters`, `bool use_patches`) match between definition (Tasks 3/4) and call site (Task 4). ✓

---

## What comes next (not this plan)

- **Plan 5:** dent vs gouge in the fragment stage — threshold accumulated displacement; gouge interior via triplanar `Damage.tga` (baseline) or procedural (Modern VFX toggle); charred ring + embers reusing decal code. (`opaque.frag` or a deform-specific fragment variant gains the gouge branch; this is why 4b kept the fragment stage shared and simple.)
- **Plan 6:** eligibility manager (player always-tessellated for anti-pop + conservative Phong smoothing; capped nearest/largest set) feeding a per-instance deform-eligible flag that ANDs with the Task 4 crater gate; `engine/appc/hull_deformation.py` (GU depth/kind mapping); `hit_feedback` dispatch hook calling `renderer.hull_deform_add`; plus the Plan 2 deferrals (M1 wrapper pattern, M3 binding transform test) and the Plan 3 deferral (demote/document `probe_thickness`).
