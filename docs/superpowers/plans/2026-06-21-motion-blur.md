# Motion Blur Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Motion Blur" toggle under the Modern VFX group that applies camera motion blur to the exterior view via a dedicated post-process pass using depthless fixed-distance reprojection against the previous frame's view-projection.

**Architecture:** A new `renderer::MotionBlurPass` (mirrors `FilmicPass`) reprojects each pixel's view ray (placed at a fixed distance D) through the cached previous-frame view-projection to derive a screen-space motion vector, then averages N color taps along it. It slots into the post chain after SMAA and before filmic. The post-resolve routing is refactored from hand-cased SMAA×filmic into a 2-target ping-pong over the optional passes (SMAA → motion blur → filmic), preserving the no-optional-pass path byte-for-byte. A `dauntless_motion_blur` flag + bindings + config row mirror the filmic toggle end to end.

**Tech Stack:** C++17, OpenGL 3.3 core (GLSL 330), GLAD, glm, pybind11, GoogleTest (ctest), Python 3, pytest, CEF (vanilla JS).

## Global Constraints

- One build tree at `<root>/build/`. Binary `build/dauntless`; module `_dauntless_host` at `build/python/`. Never build from inside `native/`.
- Shader (`.vert`/`.frag`) changes require re-running `cmake -B build -S .` BEFORE `cmake --build build -j` (embedded shaders regenerate at configure time).
- `host_bindings.cc` compiles into BOTH `build/dauntless` and the `_dauntless_host` module — edits need a full `dauntless` rebuild.
- Motion blur is **camera-only** (no per-object velocity buffer) and **exterior-only** (`!viewer_mode && !bridge_active`); bridge interior and the viewscreen inset never blur.
- Default **on**, not persisted across launches.
- The HDR scene target's depth is a renderbuffer; do NOT change it. The technique is depthless by design.
- When no optional post pass (SMAA, motion blur, filmic) is active, the resolve→backbuffer path must remain byte-identical to today.
- Tunable shader constants are named `const` at the top of `motion_blur.frag`, live-tunable by rebuilding.
- The real config focus/render order (Python panel AND CEF JS) is: `dust, specular, fov, procedural_sky, hdr, rim, shadows, decals, smaa, filmic` — append `motion_blur` LAST. Do NOT reorder existing rows.

---

## File Structure

- Create `native/src/renderer/include/renderer/motion_blur_pass.h` — `MotionBlurPass` class.
- Create `native/src/renderer/motion_blur_pass.cc` — implementation.
- Create `native/src/renderer/shaders/motion_blur.frag` — reprojection blur shader.
- Create `native/tests/renderer/motion_blur_pass_test.cc` — GL unit tests.
- Modify `native/src/renderer/frame.cc` — `dauntless_motion_blur` toggle namespace.
- Modify `native/src/renderer/CMakeLists.txt` — embed `motion_blur.frag`, add `motion_blur_pass.cc`.
- Modify `native/tests/renderer/CMakeLists.txt` — add `motion_blur_pass_test.cc`.
- Modify `native/tests/renderer/frame_test.cc` — `dauntless_motion_blur` toggle test.
- Modify `native/src/host/host_bindings.cc` — globals, init/shutdown, ping-pong routing refactor, prev-viewproj caching, bindings.
- Modify `engine/renderer.py` — `motion_blur_enabled()` + `set_motion_blur_enabled()`.
- Modify `engine/ui/configuration_panel.py` — `motion_blur_on` setting, applier, dispatch/focus/payload.
- Modify `tests/unit/test_configuration_panel.py` — applier mock, round-trip, toggle, payload tests.
- Modify `native/assets/ui-cef/js/configuration_panel.js` — focus entry + graphics row.
- Modify `engine/host_loop.py` — initial `motion_blur_on` snapshot + applier.

---

## Task 1: C++ motion-blur toggle namespace

**Files:**
- Modify: `native/src/renderer/frame.cc` (after the `dauntless_filmic` namespace block)
- Test: `native/tests/renderer/frame_test.cc` (after the `DauntlessFilmicToggle` tests)

**Interfaces:**
- Produces: `namespace dauntless_motion_blur { bool enabled(); void set_enabled(bool); }` — default `true`. Consumed by host_bindings (Task 3) and the frame test.

- [ ] **Step 1: Write the failing test** in `native/tests/renderer/frame_test.cc`. Add a forward declaration next to the existing `dauntless_filmic` one, and a test next to `DauntlessFilmicToggle`:

```cpp
namespace dauntless_motion_blur { bool enabled(); void set_enabled(bool); }

TEST(DauntlessMotionBlurToggle, DefaultsOnAndRoundTrips) {
    EXPECT_TRUE(dauntless_motion_blur::enabled());      // default on
    dauntless_motion_blur::set_enabled(false);
    EXPECT_FALSE(dauntless_motion_blur::enabled());
    dauntless_motion_blur::set_enabled(true);           // restore for other tests
    EXPECT_TRUE(dauntless_motion_blur::enabled());
}
```

- [ ] **Step 2: Run the test to verify it fails (link error)**

Run: `cmake --build build -j --target renderer_tests`
Expected: FAIL — undefined reference to `dauntless_motion_blur::enabled()`.

- [ ] **Step 3: Add the namespace** in `native/src/renderer/frame.cc` immediately after the closing `}` of `namespace dauntless_filmic`:

```cpp
// Toggle for camera motion blur (Modern VFX). Default on. Exterior-only;
// host_bindings.cc gates on view + a valid previous-frame view-projection.
namespace dauntless_motion_blur {
    bool g_motion_blur_enabled = true;
    bool enabled() { return g_motion_blur_enabled; }
    void set_enabled(bool v) { g_motion_blur_enabled = v; }
}
```

- [ ] **Step 4: Build and run the test**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R DauntlessMotionBlurToggle --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/frame.cc native/tests/renderer/frame_test.cc
git commit -m "feat(vfx): add dauntless_motion_blur toggle namespace (default on)"
```

---

## Task 2: MotionBlurPass class + shader

**Files:**
- Create: `native/src/renderer/include/renderer/motion_blur_pass.h`
- Create: `native/src/renderer/motion_blur_pass.cc`
- Create: `native/src/renderer/shaders/motion_blur.frag`
- Create: `native/tests/renderer/motion_blur_pass_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: existing `shader_src::resolve_vs` (fullscreen-triangle VS, reused).
- Produces: `renderer::MotionBlurPass` with
  `void draw(std::uint32_t src_tex, std::uint32_t dst_fbo, int fw, int fh, const glm::mat4& inv_proj, const glm::mat3& cam_rot, const glm::vec3& cam_pos, const glm::mat4& prev_viewproj)`. Consumed by host_bindings (Task 3).

- [ ] **Step 1: Create the fragment shader** `native/src/renderer/shaders/motion_blur.frag`:

```glsl
#version 330 core
in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_src;
uniform mat4 u_inv_proj;       // inverse(camera proj)
uniform mat3 u_cam_rot;        // camera view->world rotation
uniform vec3 u_cam_pos;        // camera world position
uniform mat4 u_prev_viewproj;  // previous frame proj * view

// Camera-motion-blur tuning — eye-tunable by rebuilding (like the filmic
// grade). Depthless: the scene is reprojected as if at DISTANCE_GU.
const float STRENGTH    = 1.0;    // motion-vector multiplier
const int   SAMPLES     = 8;      // taps along the vector
const float MAX_UV      = 0.05;   // cap on motion-vector length (screen frac)
const float DISTANCE_GU = 100.0;  // assumed scene distance (game units)

void main() {
    vec2 ndc = v_uv * 2.0 - 1.0;

    // View-space ray through this pixel (far-plane point; direction only).
    vec4 vr = u_inv_proj * vec4(ndc, 1.0, 1.0);
    vec3 ray_view = normalize(vr.xyz / vr.w);

    // Pseudo world point at a fixed distance along the ray.
    vec3 world = u_cam_pos + DISTANCE_GU * (u_cam_rot * ray_view);

    // Where that point sat on screen last frame.
    vec4 clip_prev = u_prev_viewproj * vec4(world, 1.0);
    vec2 uv_prev = (clip_prev.xy / clip_prev.w) * 0.5 + 0.5;

    // Screen-space motion vector, capped.
    vec2 mv = (v_uv - uv_prev) * STRENGTH;
    float len = length(mv);
    if (len > MAX_UV) mv *= MAX_UV / len;

    // Average taps trailing toward the previous position.
    vec3 acc = vec3(0.0);
    for (int i = 0; i < SAMPLES; ++i) {
        float t = float(i) / float(SAMPLES - 1);   // 0..1
        acc += texture(u_src, v_uv - mv * t).rgb;
    }
    frag_color = vec4(acc / float(SAMPLES), 1.0);
}
```

- [ ] **Step 2: Create the header** `native/src/renderer/include/renderer/motion_blur_pass.h`:

```cpp
#pragma once
#include <cstdint>
#include <memory>
#include <glm/glm.hpp>
#include <renderer/shader.h>
namespace renderer {

/// Camera motion blur via depthless fixed-distance reprojection: each pixel's
/// view ray is placed at a fixed distance and reprojected through the previous
/// frame's view-projection to derive a screen-space motion vector, then color
/// is averaged along it. Reuses the fullscreen-triangle vertex shader
/// (resolve.vert). Runs after SMAA and before filmic, exterior view only.
class MotionBlurPass {
public:
    MotionBlurPass();
    ~MotionBlurPass();
    MotionBlurPass(const MotionBlurPass&) = delete;
    MotionBlurPass& operator=(const MotionBlurPass&) = delete;

    /// Draw a fullscreen triangle sampling `src_tex` into `dst_fbo`
    /// (0 = backbuffer), viewport `fw`x`fh`. `inv_proj` = inverse(proj),
    /// `cam_rot` = camera view->world rotation, `cam_pos` = camera world pos,
    /// `prev_viewproj` = previous frame proj*view. Disables cull/depth/blend
    /// and restores them.
    void draw(std::uint32_t src_tex, std::uint32_t dst_fbo, int fw, int fh,
              const glm::mat4& inv_proj, const glm::mat3& cam_rot,
              const glm::vec3& cam_pos, const glm::mat4& prev_viewproj);
private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
};
}  // namespace renderer
```

- [ ] **Step 3: Create the implementation** `native/src/renderer/motion_blur_pass.cc`:

```cpp
// native/src/renderer/motion_blur_pass.cc
//
// Camera motion blur: depthless fixed-distance reprojection against the
// previous-frame view-projection. Reuses resolve.vert.

#include <renderer/motion_blur_pass.h>

#include <glad/glad.h>

#include "embedded_resolve_vs.h"
#include "embedded_motion_blur_fs.h"

namespace renderer {

MotionBlurPass::MotionBlurPass()
    : shader_(std::make_unique<renderer::Shader>(
          shader_src::resolve_vs, shader_src::motion_blur_fs)) {
    const float verts[] = { -1.0f, -1.0f,   3.0f, -1.0f,   -1.0f,  3.0f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
}

MotionBlurPass::~MotionBlurPass() {
    if (vbo_) glDeleteBuffers(1,      &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void MotionBlurPass::draw(std::uint32_t src_tex, std::uint32_t dst_fbo,
                          int fw, int fh, const glm::mat4& inv_proj,
                          const glm::mat3& cam_rot, const glm::vec3& cam_pos,
                          const glm::mat4& prev_viewproj) {
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glBindFramebuffer(GL_FRAMEBUFFER, dst_fbo);
    glViewport(0, 0, fw, fh);

    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    shader_->use();
    shader_->set_int("u_src", 0);
    shader_->set_mat4("u_inv_proj", inv_proj);
    shader_->set_mat3("u_cam_rot", cam_rot);
    shader_->set_vec3("u_cam_pos", cam_pos);
    shader_->set_mat4("u_prev_viewproj", prev_viewproj);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, src_tex);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glUseProgram(0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
```

- [ ] **Step 4: Wire CMake.** In `native/src/renderer/CMakeLists.txt`, add an embed line after the `SHADER_FILMIC_FS` line:

```cmake
embed_shader(SHADER_MOTION_BLUR_FS shaders/motion_blur.frag motion_blur_fs)
```

And add `motion_blur_pass.cc` to the renderer library source list after `filmic_pass.cc`:

```cmake
    motion_blur_pass.cc
```

- [ ] **Step 5: Create the GL unit test** `native/tests/renderer/motion_blur_pass_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/ldr_target.h>
#include <renderer/motion_blur_pass.h>
#include <renderer/window.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <memory>

namespace {
class MotionBlurPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64,64,"mblur-test",false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
    // Fill a 64x64 LDR target with a vertical edge: left half black, right white.
    void fill_edge(renderer::LdrTarget& t) {
        t.resize(64, 64);
        t.bind();
        glEnable(GL_SCISSOR_TEST);
        glScissor(0, 0, 32, 64);  glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
        glScissor(32, 0, 32, 64); glClearColor(1,1,1,1); glClear(GL_COLOR_BUFFER_BIT);
        glDisable(GL_SCISSOR_TEST);
    }
};

// Static camera (prev_viewproj == current) yields a ~zero motion vector, so a
// pixel deep in the black region stays black (passthrough, no smear).
TEST_F(MotionBlurPassTest, StaticCameraIsPassthrough) {
    renderer::LdrTarget src; fill_edge(src);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);

    glm::mat4 proj = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 100000.0f);
    glm::mat4 view = glm::lookAt(glm::vec3(0,0,0), glm::vec3(0,0,-1), glm::vec3(0,1,0));
    glm::mat4 inv_proj = glm::inverse(proj);
    glm::mat3 cam_rot  = glm::mat3(glm::inverse(view));
    glm::mat4 prev_vp  = proj * view;   // same as current => no motion

    renderer::MotionBlurPass m;
    m.draw(src.color_texture(), /*dst_fbo=*/0, 64, 64,
           inv_proj, cam_rot, glm::vec3(0), prev_vp);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(8, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);  // deep black side
    EXPECT_LT(px[0], 8);                       // still ~black: no smear
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// A yawed previous view-projection produces a horizontal motion vector, so a
// near-edge pixel changes vs the static (passthrough) result.
TEST_F(MotionBlurPassTest, CameraRotationBlursEdge) {
    glm::mat4 proj = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 100000.0f);
    glm::mat4 view = glm::lookAt(glm::vec3(0,0,0), glm::vec3(0,0,-1), glm::vec3(0,1,0));
    glm::mat4 inv_proj = glm::inverse(proj);
    glm::mat3 cam_rot  = glm::mat3(glm::inverse(view));

    // Read the near-edge pixel under no motion (passthrough baseline).
    renderer::LdrTarget src0; fill_edge(src0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    renderer::MotionBlurPass m0;
    m0.draw(src0.color_texture(), 0, 64, 64, inv_proj, cam_rot, glm::vec3(0), proj*view);
    unsigned char base[4] = {0}; glReadPixels(30, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, base);

    // Now a yawed previous view => horizontal reprojection => edge smears.
    glm::mat4 prev_view = glm::rotate(view, glm::radians(5.0f), glm::vec3(0,1,0));
    renderer::LdrTarget src1; fill_edge(src1);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    renderer::MotionBlurPass m1;
    m1.draw(src1.color_texture(), 0, 64, 64, inv_proj, cam_rot, glm::vec3(0), proj*prev_view);
    unsigned char blur[4] = {0}; glReadPixels(30, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, blur);

    EXPECT_GT(std::abs(int(blur[0]) - int(base[0])), 10);   // edge measurably smeared
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Regression: the fullscreen triangle must survive CW-front, back-face cull.
TEST_F(MotionBlurPassTest, DrawsWhenBackfaceCullingEnabled) {
    glEnable(GL_CULL_FACE); glCullFace(GL_BACK); glFrontFace(GL_CW);

    renderer::LdrTarget src; src.resize(32,32); src.bind();
    glClearColor(0.5f,0.5f,0.5f,1.0f); glClear(GL_COLOR_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);   // black if culled

    glm::mat4 proj = glm::perspective(glm::radians(60.0f), 1.0f, 0.1f, 100000.0f);
    glm::mat4 view = glm::lookAt(glm::vec3(0,0,0), glm::vec3(0,0,-1), glm::vec3(0,1,0));
    renderer::MotionBlurPass m;
    m.draw(src.color_texture(), 0, 64, 64, glm::inverse(proj),
           glm::mat3(glm::inverse(view)), glm::vec3(0), proj*view);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_GT(px[0], 80);     // would be 0 if culled
    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));   // pass restored cull state
    glDisable(GL_CULL_FACE); glFrontFace(GL_CCW);   // clean up for other tests
}
}  // namespace
```

- [ ] **Step 6: Register the test** in `native/tests/renderer/CMakeLists.txt`, after `filmic_pass_test.cc`:

```cmake
    motion_blur_pass_test.cc
```

- [ ] **Step 7: Reconfigure (new shader) + build + run**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ctest --test-dir build -R MotionBlurPassTest --output-on-failure`
Expected: 3 MotionBlurPassTest cases PASS (or SKIP if no GL context — acceptable in headless CI; confirm PASS locally).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/motion_blur_pass.h \
        native/src/renderer/motion_blur_pass.cc \
        native/src/renderer/shaders/motion_blur.frag \
        native/tests/renderer/motion_blur_pass_test.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(vfx): add MotionBlurPass (camera reprojection blur)"
```

---

## Task 3: Host integration — globals, ping-pong routing refactor, prev-viewproj, bindings, wrapper

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`

**Interfaces:**
- Consumes: `renderer::MotionBlurPass` (Task 2); `dauntless_motion_blur::enabled()` (Task 1); existing `g_camera`, `g_ldr_target`, `g_ldr_target2`, `g_smaa_pass`, `g_resolve_pass`, `g_filmic_pass`, `viewer_mode`, `bridge_active`, `now`, `dauntless_filmic::enabled()`, `dauntless_filmic::ambient_scale()`.
- Produces: `_dauntless_host.motion_blur_set_enabled(bool)` / `motion_blur_enabled()`; `engine.renderer.set_motion_blur_enabled` / `motion_blur_enabled`.

- [ ] **Step 1: Add the include + forward declaration.** Near the other renderer pass includes add `#include <renderer/motion_blur_pass.h>` and `#include <glm/gtc/matrix_inverse.hpp>` (only if not already included). With the other `namespace dauntless_*` forward declarations (next to `dauntless_filmic`), add:

```cpp
namespace dauntless_motion_blur {
    bool enabled();            // defined in frame.cc
    void set_enabled(bool v);  // defined in frame.cc
}
```

- [ ] **Step 2: Add globals** next to `g_filmic_pass` / `g_ldr_target2`:

```cpp
std::unique_ptr<renderer::MotionBlurPass> g_motion_blur_pass;
glm::mat4 g_prev_viewproj = glm::mat4(1.0f);   // previous exterior frame proj*view
bool      g_have_prev_viewproj = false;        // false until first exterior frame
```

- [ ] **Step 3: Construct in init** next to `g_filmic_pass = ...`:

```cpp
g_motion_blur_pass = std::make_unique<renderer::MotionBlurPass>();
```

- [ ] **Step 4: Reset in shutdown** next to `g_filmic_pass.reset()` (reverse order — reset motion blur with the other passes), and clear the prev-frame flag:

```cpp
g_motion_blur_pass.reset();
g_have_prev_viewproj = false;
```

- [ ] **Step 5: Replace the resolve/SMAA/filmic routing block with a ping-pong.** In `host_bindings.cc`, replace the entire block that currently begins at `const bool aa_on     = g_smaa_enabled;` and ends with the `if (filmic_on) { ... g_filmic_pass->draw(...); }` block, with:

```cpp
    const bool aa_on    = g_smaa_enabled;
    const bool exterior = !viewer_mode && !bridge_active;
    const bool filmic_on = dauntless_filmic::enabled() && exterior;
    const bool mblur_on  = dauntless_motion_blur::enabled() && exterior
                           && g_have_prev_viewproj;

    // Optional LDR post passes run, in order, after the HDR resolve:
    //   SMAA -> motion blur -> filmic.
    // Ping-pong between two LDR targets; the LAST active pass writes the
    // backbuffer. With none active, resolve writes straight to the backbuffer
    // (the original zero-cost path, byte-identical).
    const bool any_post = aa_on || mblur_on || filmic_on;

    if (any_post) { g_ldr_target->resize(fw, fh); g_ldr_target->bind(); }
    else { glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0, 0, fw, fh); }
    g_resolve_pass->set_hdr_enabled(dauntless_hdr::enabled());
    g_resolve_pass->draw(g_hdr_target->color_texture(), bloom_tex);

    if (any_post) {
        g_ldr_target2->resize(fw, fh);

        // Camera matrices for the motion-blur pass (current exterior camera).
        const glm::mat4 inv_proj = glm::inverse(g_camera.proj_matrix());
        const glm::mat3 cam_rot  = glm::mat3(glm::inverse(g_camera.view_matrix()));
        const glm::vec3 cam_pos  = g_camera.eye;

        // Active optional passes as uniform (src_tex, dst_fbo) callables.
        std::vector<std::function<void(std::uint32_t, std::uint32_t)>> passes;
        if (aa_on)
            passes.emplace_back([&](std::uint32_t s, std::uint32_t d) {
                g_smaa_pass->draw(s, d, fw, fh);
            });
        if (mblur_on)
            passes.emplace_back([&](std::uint32_t s, std::uint32_t d) {
                g_motion_blur_pass->draw(s, d, fw, fh, inv_proj, cam_rot,
                                         cam_pos, g_prev_viewproj);
            });
        if (filmic_on)
            passes.emplace_back([&](std::uint32_t s, std::uint32_t d) {
                g_filmic_pass->draw(s, d, fw, fh, static_cast<float>(now));
            });

        // resolve wrote into target[0]; ping-pong to target[1], alternating.
        renderer::LdrTarget* targets[2] = { g_ldr_target.get(), g_ldr_target2.get() };
        std::uint32_t cur_tex = targets[0]->color_texture();
        int dst_idx = 1;
        for (std::size_t i = 0; i < passes.size(); ++i) {
            const bool last = (i + 1 == passes.size());
            const std::uint32_t dst_fbo = last ? 0u : targets[dst_idx]->fbo();
            passes[i](cur_tex, dst_fbo);
            if (!last) { cur_tex = targets[dst_idx]->color_texture(); dst_idx ^= 1; }
        }
    }

    // Cache this exterior frame's view-projection for next frame's motion blur.
    // Non-exterior frames invalidate it so re-entering the exterior view skips
    // one frame of blur instead of smearing across the transition.
    if (exterior) {
        g_prev_viewproj = g_camera.proj_matrix() * g_camera.view_matrix();
        g_have_prev_viewproj = true;
    } else {
        g_have_prev_viewproj = false;
    }
```

Ensure `#include <functional>` and `#include <vector>` are present at the top of `host_bindings.cc` (add if missing).

- [ ] **Step 6: Add the bindings** in the `PYBIND11_MODULE` block, right after the `filmic_enabled` binding:

```cpp
    m.def("motion_blur_set_enabled",
          [](bool enabled) { dauntless_motion_blur::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle camera Motion Blur (Modern VFX) on the exterior view. "
          "Default: on.");
    m.def("motion_blur_enabled",
          []() { return dauntless_motion_blur::enabled(); },
          "Read the Motion Blur toggle (Modern VFX). Default: on.");
```

- [ ] **Step 7: Add the Python wrappers** in `engine/renderer.py`, right after `set_filmic_enabled`:

```python
def motion_blur_enabled() -> bool:
    """Read the Motion Blur toggle (Modern VFX). Default: on."""
    return _h.motion_blur_enabled()


def set_motion_blur_enabled(enabled: bool) -> None:
    """Toggle camera Motion Blur (Modern VFX) on the exterior view. Default: on."""
    _h.motion_blur_set_enabled(enabled)
```

- [ ] **Step 8: Full rebuild + smoke check**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build of `build/dauntless` + the module.

Run: `python -c "import sys; sys.path.insert(0,'build/python'); import _dauntless_host as h; print(hasattr(h,'motion_blur_set_enabled'), hasattr(h,'motion_blur_enabled'))"`
Expected: `True True`

- [ ] **Step 9: Run the renderer tests to confirm the routing refactor didn't regress**

Run: `ctest --test-dir build -R "FilmicPassTest|ResolvePassTest|MotionBlurPassTest|SmaaPass" --output-on-failure`
Expected: all PASS (the existing filmic/resolve/smaa paths still work under the new ping-pong).

- [ ] **Step 10: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(vfx): ping-pong post routing + MotionBlurPass wired (exterior, prev-viewproj cache)"
```

---

## Task 4: Configuration panel (Python) + tests

**Files:**
- Modify: `engine/ui/configuration_panel.py`
- Test: `tests/unit/test_configuration_panel.py`

**Interfaces:**
- Consumes: `engine.renderer.set_motion_blur_enabled` / `motion_blur_enabled` (Task 3), wired by host_loop (Task 6).
- Produces: `SettingsSnapshot.motion_blur_on`, ctor param `set_motion_blur`, dispatch `toggle:motion_blur`, focus entry `("ctrl","motion_blur")`, payload key `motion_blur_on`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_configuration_panel.py`. Add `set_motion_blur=Mock()` to the `_make` helper (next to `set_filmic=Mock()`); add `"motion_blur_on": True` to the exact-dict assertion in `test_initial_settings_round_trip_to_render_payload` (next to `"filmic_on": True`); and append:

```python
def test_dispatch_toggle_motion_blur_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:motion_blur") is True
    kw["set_motion_blur"].assert_called_once_with(False)
    assert p.dispatch_event("toggle:motion_blur") is True
    kw["set_motion_blur"].assert_called_with(True)


def test_motion_blur_on_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, fov_deg=70, shadows_on=True,
        procedural_sky_on=True, filmic_on=True, motion_blur_on=False,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["motion_blur_on"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/test_configuration_panel.py -q`
Expected: FAIL — unexpected `set_motion_blur`, missing `motion_blur_on`.

- [ ] **Step 3: Implement the panel changes** in `engine/ui/configuration_panel.py` (mirror every `filmic`/`filmic_on` site):

  a. In `SettingsSnapshot`, after `filmic_on: bool = True`:
```python
    motion_blur_on: bool = True
```
  b. Add ctor param after `set_filmic`:
```python
                 set_motion_blur: Callable[[bool], None]):
```
  (make `set_filmic` take a trailing comma; add the new param on the next line before the closing `):`).
  c. In the settings copy in `__init__` (after `filmic_on=initial_settings.filmic_on,`):
```python
            motion_blur_on=initial_settings.motion_blur_on,
```
  d. Store the applier (after `self._set_filmic = set_filmic`):
```python
        self._set_motion_blur = set_motion_blur
```
  e. In the snapshot tuple in `_maybe_push` (after `self._settings.filmic_on,`):
```python
            self._settings.motion_blur_on,
```
  f. In the payload dict (after `"filmic_on": self._settings.filmic_on,`):
```python
                "motion_blur_on": self._settings.motion_blur_on,
```
  g. In `dispatch_event`, after the `toggle:filmic` block:
```python
        if action == "toggle:motion_blur":
            new_val = not self._settings.motion_blur_on
            self._set_motion_blur(new_val)
            self._settings.motion_blur_on = new_val
            return True
```
  h. In the activate handler, after the `filmic` elif:
```python
        elif activate and kind == "ctrl" and target == "motion_blur":
            self.dispatch_event("toggle:motion_blur")
```
  i. In the graphics focus list, append `motion_blur` as the final entry (keep existing order, including `fov` before `procedural_sky`):
```python
            out += [("ctrl", "dust"), ("ctrl", "specular"),
                    ("ctrl", "fov"), ("ctrl", "procedural_sky"),
                    ("ctrl", "hdr"), ("ctrl", "rim"), ("ctrl", "shadows"),
                    ("ctrl", "decals"), ("ctrl", "smaa"), ("ctrl", "filmic"),
                    ("ctrl", "motion_blur")]
```
  Also update the focus-list docstring just above it to end `('ctrl','filmic'), ('ctrl','motion_blur')]` so it matches.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/unit/test_configuration_panel.py -q`
Expected: PASS (all, including the new two).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/configuration_panel.py tests/unit/test_configuration_panel.py
git commit -m "feat(vfx): add Motion Blur row to the configuration panel"
```

---

## Task 5: CEF graphics row (JS)

**Files:**
- Modify: `native/assets/ui-cef/js/configuration_panel.js`

**Interfaces:**
- Consumes: payload key `motion_blur_on` (Task 4); dispatches `configuration/toggle:motion_blur`.

- [ ] **Step 1: Add to the focusable list** in `_cpFocusableList`, after the `filmic` push:

```javascript
        out.push({kind: 'ctrl', target: 'motion_blur'});
```
(It must come immediately after the `filmic` push, matching the Python focus order which ends `...filmic, motion_blur`.)

- [ ] **Step 2: Render the row** in `_cpRenderGraphicsBody`, after the Filmic Filter row (mirror it exactly):

```javascript
    // Motion Blur toggle — camera motion blur on the exterior view (Modern VFX).
    html += '<div class="cp-row' + (isFoc('motion_blur') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Motion Blur</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.motion_blur_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:motion_blur\')">'
          +       (s.motion_blur_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';
```

- [ ] **Step 3: Commit** (no automated test — CEF JS verified visually in Task 7)

```bash
git add native/assets/ui-cef/js/configuration_panel.js
git commit -m "feat(vfx): add Motion Blur row to the CEF configuration UI"
```

---

## Task 6: host_loop wiring

**Files:**
- Modify: `engine/host_loop.py`

**Interfaces:**
- Consumes: `engine.renderer.motion_blur_enabled` / `set_motion_blur_enabled` (Task 3); `ConfigurationPanel(set_motion_blur=...)` + `SettingsSnapshot(motion_blur_on=...)` (Task 4).

- [ ] **Step 1: Pass the initial snapshot value.** In the `SettingsSnapshot(...)` construction, after `filmic_on=r.filmic_enabled(),`:

```python
                motion_blur_on=r.motion_blur_enabled(),
```

- [ ] **Step 2: Wire the applier.** In the `ConfigurationPanel(...)` kwargs, after `set_filmic=r.set_filmic_enabled,`:

```python
            set_motion_blur=r.set_motion_blur_enabled,
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/unit/test_configuration_panel.py -q && PYTHONPATH=build/python python -c "import engine.host_loop"`
Expected: PASS; import succeeds.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(vfx): wire Motion Blur toggle into host_loop config panel"
```

---

## Task 7: Full build + verification

**Files:** none (verification only)

- [ ] **Step 1: Clean reconfigure + full build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build of `build/dauntless` + the module.

- [ ] **Step 2: Run the C++ renderer tests**

Run: `ctest --test-dir build -R "MotionBlurPassTest|DauntlessMotionBlurToggle|FilmicPassTest|ResolvePassTest" --output-on-failure`
Expected: all PASS (or SKIP only if the runner has no GL context).

NOTE: the 7 scorch/heat-glow `FrameTest.*` failures are PRE-EXISTING (verified identical on the merge-base; unrelated to this work) — do not treat them as regressions.

- [ ] **Step 3: Run the Python panel suite**

Run: `python -m pytest tests/unit/test_configuration_panel.py -q`
Expected: PASS.

- [ ] **Step 4: Live GUI check (manual — ask Mark to drive; do NOT synthetic-click or screen-capture his live workstation).**

In a running `./build/dauntless` exterior view, confirm:
  1. Turning/banking the camera smears the starfield + ships in the direction of motion.
  2. Accelerating/dollying produces a radial speed-streak.
  3. Configuration → Graphics → "Motion Blur" toggles the effect on/off.
  4. Bridge interior / viewscreen inset / Ship Property Viewer show NO blur regardless of the toggle.
  5. Toggling SMAA and Filmic in any combination with Motion Blur renders correctly (no black frame, correct ordering: blur under grain/vignette).
  6. Entering the bridge then returning to exterior does not produce a one-frame full-screen smear.

- [ ] **Step 5: Branch wrap-up** — once Mark confirms the live check (and any live strength tuning is settled), use `superpowers:finishing-a-development-branch`.

---

## Self-Review Notes

- **Spec coverage:** technique/reprojection (Task 2 shader), uniforms + host matrices (Tasks 2–3), prev-viewproj cache + first-frame skip (Task 3), pipeline placement after SMAA before filmic (Task 3 pass order), ping-pong refactor with byte-identical no-post path (Task 3), exterior-only gate (Task 3 `exterior`), own toggle default-on (Tasks 1,3,4,6), named tunable consts (Task 2 shader), CEF + focus-order append (Tasks 4–5), testing (Tasks 1,2 + Task 7). All covered.
  - **Deviation from spec testing:** the spec mentioned a "pure motion-vector helper" unit test. The reprojection math lives in GLSL; a C++ mirror would test non-production code (DRY violation). Replaced with the GL-level `MotionBlurPassTest` (static-camera passthrough proves zero-motion; yawed-prev proves directional smear) which exercises the real shader. This is a stronger test of the actual math.
- **Type consistency:** `MotionBlurPass::draw(src_tex, dst_fbo, fw, fh, inv_proj, cam_rot, cam_pos, prev_viewproj)` is defined in Task 2 and called with that exact arity in Task 3. `motion_blur` / `motion_blur_on` / `toggle:motion_blur` / `motion_blur_enabled` / `set_motion_blur_enabled` / `set_motion_blur` spelled identically across Tasks 3–6.
- **Placeholder scan:** every code step has complete code; no TBD/TODO. The pass uses the typed `Shader` setters (`set_mat4`/`set_mat3`/`set_vec3`/`set_int`), all confirmed present in `shader.h`.
