# FXAA → SMAA 1x Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the renderer's post-process FXAA anti-aliasing with SMAA 1x, exposed as an Off/On toggle under Settings > Configuration > Graphics.

**Architecture:** SMAA 1x is three fullscreen passes (edge detection → blend-weight calculation → neighborhood blending) that occupy the exact pipeline slot FXAA does today — post-tonemap, LDR, after `ResolvePass` writes into `LdrTarget`, before the CEF composite. A new `SmaaPass` class (mirroring `FxaaPass`) owns the three shader programs, two intermediate render targets (`edges` RG8, `weights` RGBA8), and two precomputed lookup textures (AreaTex, SearchTex) embedded as byte arrays. FXAA is removed entirely.

**Tech Stack:** C++20, OpenGL (GL 3.3 core / GLSL 330; offscreen tests via llvmpipe), pybind11 host bindings, Python config-panel UI, CEF/JS for the panel widget. SMAA core algorithm + lookup textures are vendored from the upstream MIT-licensed reference (iryoku/smaa).

## Global Constraints

- **GLSL version:** `#version 330 core` — matches every existing shader (`fxaa.vert`, `resolve.frag`, `bloom_up.frag`). Use the SMAA reference's `SMAA_GLSL_3` path. Copy verbatim.
- **Single build tree:** build from `<project-root>/build/` only. `cmake -B build -S . && cmake --build build -j`. Never run cmake inside `native/`.
- **Shader edits need reconfigure:** new/changed `.vert`/`.frag`/`.glsl` files are NOT picked up by `cmake --build` alone — re-run `cmake -B build -S .` first (the `embed_shader` headers are generated at configure time).
- **host_bindings build target:** `native/src/host/host_bindings.cc` compiles into BOTH `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so`. After editing it, rebuild `dauntless` (not just the module) or the binary goes stale.
- **Default state:** SMAA on by default (matches FXAA's current `g_fxaa_enabled = true`). Session-only — NOT persisted across launches.
- **Color space:** SMAA runs on the tonemapped LDR color (perceptual/gamma-encoded), which is what its luma edge detection expects. Do not move it pre-tonemap.
- **Provenance:** vendored SMAA files keep their upstream MIT license header intact.
- **Python test runner:** `uv run pytest <path> -v` (or `scripts/run_tests.sh` for the full suite).
- **C++ test runner:** `ctest --test-dir build --output-on-failure -R <regex>`. Offscreen GL tests set `GALLIUM_DRIVER=llvmpipe` (already wired in `native/tests/renderer/CMakeLists.txt`).

---

## File Structure

**Created:**
- `native/src/renderer/shaders/smaa_lib.glsl` — vendored SMAA reference core (adapted to GLSL 330), embedded as a string and prepended to each stage at program-link time.
- `native/src/renderer/shaders/smaa_edge.vert` / `.frag` — luma edge-detection entry shaders.
- `native/src/renderer/shaders/smaa_weight.vert` / `.frag` — blend-weight-calculation entry shaders.
- `native/src/renderer/shaders/smaa_blend.vert` / `.frag` — neighborhood-blending entry shaders.
- `native/src/renderer/area_tex.h` — vendored AreaTex byte array (RG8, 160×560).
- `native/src/renderer/search_tex.h` — vendored SearchTex byte array (R8, 64×16).
- `native/src/renderer/include/renderer/smaa_pass.h` — `SmaaPass` class declaration.
- `native/src/renderer/smaa_pass.cc` — `SmaaPass` implementation.
- `native/tests/renderer/smaa_pass_test.cc` — offscreen GL test.

**Modified:**
- `native/src/renderer/CMakeLists.txt` — embed new shaders, add `smaa_pass.cc`, drop fxaa entries (Task 4).
- `native/tests/renderer/CMakeLists.txt` — add `smaa_pass_test.cc`.
- `native/src/host/host_bindings.cc` — construct/use `SmaaPass`, `g_smaa_enabled`, `smaa_set_enabled` binding; remove fxaa wiring (Task 4).
- `engine/renderer.py` — `set_smaa_enabled` wrapper (replaces `set_fxaa_enabled`).
- `engine/ui/configuration_panel.py` — rename `fxaa`→`smaa` field/dispatch/keynav.
- `engine/host_loop.py:3140` — `set_fxaa=` → `set_smaa=`.
- `native/assets/ui-cef/js/configuration_panel.js` — relabel the toggle row.
- `tests/unit/test_configuration_panel.py` — rename fxaa→smaa assertions.

**Deleted (Task 4):**
- `native/src/renderer/fxaa_pass.cc`, `native/src/renderer/include/renderer/fxaa_pass.h`
- `native/src/renderer/shaders/fxaa.vert`, `native/src/renderer/shaders/fxaa.frag`

---

## Task 1: SmaaPass renderer component (3 passes, lookup textures, intermediate targets)

**Files:**
- Create: `native/src/renderer/shaders/smaa_lib.glsl`
- Create: `native/src/renderer/shaders/smaa_edge.vert`, `smaa_edge.frag`
- Create: `native/src/renderer/shaders/smaa_weight.vert`, `smaa_weight.frag`
- Create: `native/src/renderer/shaders/smaa_blend.vert`, `smaa_blend.frag`
- Create: `native/src/renderer/area_tex.h`, `native/src/renderer/search_tex.h`
- Create: `native/src/renderer/include/renderer/smaa_pass.h`
- Create: `native/src/renderer/smaa_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Test: `native/tests/renderer/smaa_pass_test.cc`, `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: nothing (entry task). Uses existing `renderer::Shader(vs_src, fs_src)`.
- Produces: `renderer::SmaaPass` with
  `SmaaPass()` and
  `void draw(std::uint32_t ldr_color_tex, std::uint32_t dest_fbo, int fw, int fh);`
  — runs the three SMAA passes over `ldr_color_tex` and writes the anti-aliased
  result into `dest_fbo` (pass `0` for the backbuffer). Owns + auto-resizes its
  intermediate targets internally; caller sets viewport before calling.

### Step-by-step

- [ ] **Step 1: Vendor the SMAA core library shader**

Download `SMAA.hlsl` from the upstream reference (https://github.com/iryoku/smaa, `SMAA.hlsl`, MIT). Create `native/src/renderer/shaders/smaa_lib.glsl` containing that source adapted for GLSL:
- Keep the full upstream MIT license comment block at the top.
- Do NOT add a `#version` line (this file is concatenated AFTER the version directive supplied by the entry shaders).
- The reference is already parameterized for GLSL via `SMAA_GLSL_3`; the entry shaders (Step 2) define `SMAA_GLSL_3`, `SMAA_PRESET_HIGH`, `SMAA_RT_METRICS`, and `SMAA_INCLUDE_VS`/`SMAA_INCLUDE_PS` before this file is concatenated, so no edits to the algorithm body are needed.
- Define `SMAA_RT_METRICS` as a uniform-backed value so resolution changes do not require a recompile. At the TOP of `smaa_lib.glsl` (before the upstream body), add:

```glsl
// Resolution provided as a uniform so resize() needs no recompile.
// (vec4(1/w, 1/h, w, h) — set by SmaaPass::draw each frame.)
uniform vec4 u_rt_metrics;
#ifndef SMAA_RT_METRICS
#define SMAA_RT_METRICS u_rt_metrics
#endif
```

- [ ] **Step 2: Write the six entry shaders**

These are the thin stage entry points. Each defines the SMAA macros, then the entry shader body. `smaa_lib.glsl` is concatenated immediately after the `#version` line and the `#define`s by `SmaaPass` (Step 5), so the SMAA functions are in scope.

`native/src/renderer/shaders/smaa_edge.vert`:
```glsl
in vec2 a_pos;
out vec2 v_uv;
out vec4 v_offset[3];
void main() {
    v_uv = (a_pos + 1.0) * 0.5;
    SMAAEdgeDetectionVS(v_uv, v_offset);
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
```

`native/src/renderer/shaders/smaa_edge.frag`:
```glsl
uniform sampler2D u_color_tex;
in vec2 v_uv;
in vec4 v_offset[3];
out vec4 frag;
void main() {
    frag = vec4(SMAALumaEdgeDetectionPS(v_uv, v_offset, u_color_tex), 0.0, 0.0);
}
```

`native/src/renderer/shaders/smaa_weight.vert`:
```glsl
in vec2 a_pos;
out vec2 v_uv;
out vec2 v_pixcoord;
out vec4 v_offset[3];
void main() {
    v_uv = (a_pos + 1.0) * 0.5;
    SMAABlendingWeightCalculationVS(v_uv, v_pixcoord, v_offset);
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
```

`native/src/renderer/shaders/smaa_weight.frag`:
```glsl
uniform sampler2D u_edges_tex;
uniform sampler2D u_area_tex;
uniform sampler2D u_search_tex;
in vec2 v_uv;
in vec2 v_pixcoord;
in vec4 v_offset[3];
out vec4 frag;
void main() {
    frag = SMAABlendingWeightCalculationPS(
        v_uv, v_pixcoord, v_offset,
        u_edges_tex, u_area_tex, u_search_tex, vec4(0.0));
}
```

`native/src/renderer/shaders/smaa_blend.vert`:
```glsl
in vec2 a_pos;
out vec2 v_uv;
out vec4 v_offset;
void main() {
    v_uv = (a_pos + 1.0) * 0.5;
    SMAANeighborhoodBlendingVS(v_uv, v_offset);
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
```

`native/src/renderer/shaders/smaa_blend.frag`:
```glsl
uniform sampler2D u_color_tex;
uniform sampler2D u_blend_tex;
in vec2 v_uv;
in vec4 v_offset;
out vec4 frag;
void main() {
    frag = SMAANeighborhoodBlendingPS(v_uv, v_offset, u_color_tex, u_blend_tex);
}
```

- [ ] **Step 3: Vendor the lookup-texture byte arrays**

Copy `AreaTex.h` and `SearchTex.h` from the upstream reference (iryoku/smaa, MIT) to `native/src/renderer/area_tex.h` and `native/src/renderer/search_tex.h`. Keep the license header. These define `areaTexBytes` (`AREATEX_WIDTH`=160, `AREATEX_HEIGHT`=560, RG8) and `searchTexBytes` (`SEARCHTEX_WIDTH`=64, `SEARCHTEX_HEIGHT`=16, R8). Wrap each array in `namespace renderer {` if the upstream uses a bare global, to avoid symbol collisions:

```cpp
// area_tex.h  (after the upstream license header)
#pragma once
namespace renderer {
#define AREATEX_WIDTH 160
#define AREATEX_HEIGHT 560
static const unsigned char areaTexBytes[/* AREATEX_WIDTH*AREATEX_HEIGHT*2 */] = {
    /* ... vendored bytes verbatim ... */
};
}  // namespace renderer
```
(Same shape for `search_tex.h` with `SEARCHTEX_WIDTH`/`SEARCHTEX_HEIGHT`, 1 byte/texel.)

- [ ] **Step 4: Embed the shaders in CMake**

In `native/src/renderer/CMakeLists.txt`, after the existing `embed_shader(... fxaa ...)` lines (~line 52-53), add:
```cmake
embed_shader(SHADER_SMAA_LIB   shaders/smaa_lib.glsl  smaa_lib)
embed_shader(SHADER_SMAA_EDGE_VS   shaders/smaa_edge.vert   smaa_edge_vs)
embed_shader(SHADER_SMAA_EDGE_FS   shaders/smaa_edge.frag   smaa_edge_fs)
embed_shader(SHADER_SMAA_WEIGHT_VS shaders/smaa_weight.vert smaa_weight_vs)
embed_shader(SHADER_SMAA_WEIGHT_FS shaders/smaa_weight.frag smaa_weight_fs)
embed_shader(SHADER_SMAA_BLEND_VS  shaders/smaa_blend.vert  smaa_blend_vs)
embed_shader(SHADER_SMAA_BLEND_FS  shaders/smaa_blend.frag  smaa_blend_fs)
```
And add `smaa_pass.cc` to the `add_library(renderer STATIC ...)` source list, right after `fxaa_pass.cc`.

- [ ] **Step 5: Write the SmaaPass header**

`native/src/renderer/include/renderer/smaa_pass.h`:
```cpp
#pragma once
#include <cstdint>
#include <memory>
#include <renderer/shader.h>
namespace renderer {

/// SMAA 1x post-process anti-aliasing: three fullscreen passes
/// (edge detection -> blend-weight calc -> neighborhood blend) over a
/// tonemapped LDR color texture. Owns two intermediate render targets
/// (edges RG8, weights RGBA8) and two lookup textures (AreaTex, SearchTex).
/// Drop-in replacement for FxaaPass in the post chain.
class SmaaPass {
public:
    SmaaPass();
    ~SmaaPass();
    SmaaPass(const SmaaPass&) = delete;
    SmaaPass& operator=(const SmaaPass&) = delete;

    /// Run SMAA over `ldr_color_tex` and write the result into `dest_fbo`
    /// (0 = backbuffer). `fw`,`fh` are the framebuffer pixel dims. Resizes
    /// internal targets as needed. Disables cull/depth/blend and restores them.
    void draw(std::uint32_t ldr_color_tex, std::uint32_t dest_fbo, int fw, int fh);

private:
    void resize(int w, int h);   // (re)alloc edges + weights targets
    void destroy_targets();

    std::unique_ptr<renderer::Shader> edge_;
    std::unique_ptr<renderer::Shader> weight_;
    std::unique_ptr<renderer::Shader> blend_;

    std::uint32_t vao_ = 0, vbo_ = 0;
    std::uint32_t area_tex_ = 0, search_tex_ = 0;
    std::uint32_t edges_fbo_ = 0,   edges_tex_ = 0;
    std::uint32_t weights_fbo_ = 0, weights_tex_ = 0;
    int width_ = 0, height_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 6: Write the SmaaPass implementation**

`native/src/renderer/smaa_pass.cc`:
```cpp
// native/src/renderer/smaa_pass.cc
//
// SMAA 1x: three fullscreen passes over the resolved LDR color texture.
#include <renderer/smaa_pass.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <string>

#include "embedded_smaa_lib.h"
#include "embedded_smaa_edge_vs.h"
#include "embedded_smaa_edge_fs.h"
#include "embedded_smaa_weight_vs.h"
#include "embedded_smaa_weight_fs.h"
#include "embedded_smaa_blend_vs.h"
#include "embedded_smaa_blend_fs.h"

#include "area_tex.h"
#include "search_tex.h"

namespace renderer {
namespace {

// Common GLSL prologue + SMAA library, prepended to every stage source.
// `stage_defines` selects VS vs PS code paths inside the SMAA library.
std::string compose(const char* stage_defines, const char* entry) {
    return std::string("#version 330 core\n")
         + "#define SMAA_GLSL_3 1\n"
         + "#define SMAA_PRESET_HIGH 1\n"
         + stage_defines
         + shader_src::smaa_lib + "\n"
         + entry;
}

GLuint make_lut(GLint internal_fmt, GLenum fmt, int w, int h,
                const unsigned char* bytes) {
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, internal_fmt, w, h, 0, fmt,
                 GL_UNSIGNED_BYTE, bytes);
    glBindTexture(GL_TEXTURE_2D, 0);
    return tex;
}

GLuint make_target(GLint internal_fmt, GLenum fmt, int w, int h, GLuint* fbo_out) {
    GLuint tex = 0, fbo = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, internal_fmt, w, h, 0, fmt,
                 GL_UNSIGNED_BYTE, nullptr);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, tex, 0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    *fbo_out = fbo;
    return tex;
}

}  // namespace

SmaaPass::SmaaPass()
    : edge_(std::make_unique<Shader>(
          compose("#define SMAA_INCLUDE_VS 1\n#define SMAA_INCLUDE_PS 0\n",
                  shader_src::smaa_edge_vs).c_str(),
          compose("#define SMAA_INCLUDE_VS 0\n#define SMAA_INCLUDE_PS 1\n",
                  shader_src::smaa_edge_fs).c_str())),
      weight_(std::make_unique<Shader>(
          compose("#define SMAA_INCLUDE_VS 1\n#define SMAA_INCLUDE_PS 0\n",
                  shader_src::smaa_weight_vs).c_str(),
          compose("#define SMAA_INCLUDE_VS 0\n#define SMAA_INCLUDE_PS 1\n",
                  shader_src::smaa_weight_fs).c_str())),
      blend_(std::make_unique<Shader>(
          compose("#define SMAA_INCLUDE_VS 1\n#define SMAA_INCLUDE_PS 0\n",
                  shader_src::smaa_blend_vs).c_str(),
          compose("#define SMAA_INCLUDE_VS 0\n#define SMAA_INCLUDE_PS 1\n",
                  shader_src::smaa_blend_fs).c_str())) {
    const float verts[] = { -1.0f, -1.0f,  3.0f, -1.0f,  -1.0f, 3.0f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);

    area_tex_   = make_lut(GL_RG8, GL_RG, AREATEX_WIDTH, AREATEX_HEIGHT, areaTexBytes);
    search_tex_ = make_lut(GL_R8,  GL_RED, SEARCHTEX_WIDTH, SEARCHTEX_HEIGHT, searchTexBytes);
}

SmaaPass::~SmaaPass() {
    destroy_targets();
    if (search_tex_) glDeleteTextures(1, &search_tex_);
    if (area_tex_)   glDeleteTextures(1, &area_tex_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void SmaaPass::destroy_targets() {
    if (edges_fbo_)   glDeleteFramebuffers(1, &edges_fbo_);
    if (edges_tex_)   glDeleteTextures(1, &edges_tex_);
    if (weights_fbo_) glDeleteFramebuffers(1, &weights_fbo_);
    if (weights_tex_) glDeleteTextures(1, &weights_tex_);
    edges_fbo_ = edges_tex_ = weights_fbo_ = weights_tex_ = 0;
}

void SmaaPass::resize(int w, int h) {
    if (w == width_ && h == height_ && edges_tex_) return;
    destroy_targets();
    edges_tex_   = make_target(GL_RG8,   GL_RG,   w, h, &edges_fbo_);
    weights_tex_ = make_target(GL_RGBA8, GL_RGBA, w, h, &weights_fbo_);
    width_ = w; height_ = h;
}

void SmaaPass::draw(std::uint32_t ldr_color_tex, std::uint32_t dest_fbo,
                    int fw, int fh) {
    resize(fw, fh);

    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    const glm::vec4 rt(fw > 0 ? 1.0f / fw : 0.0f,
                       fh > 0 ? 1.0f / fh : 0.0f,
                       static_cast<float>(fw), static_cast<float>(fh));

    glBindVertexArray(vao_);

    // Pass 1: edge detection -> edges_tex_
    glBindFramebuffer(GL_FRAMEBUFFER, edges_fbo_);
    glViewport(0, 0, fw, fh);
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    edge_->use();
    edge_->set_vec4("u_rt_metrics", rt);
    edge_->set_int("u_color_tex", 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, ldr_color_tex);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Pass 2: blend-weight calc -> weights_tex_
    glBindFramebuffer(GL_FRAMEBUFFER, weights_fbo_);
    glViewport(0, 0, fw, fh);
    glClear(GL_COLOR_BUFFER_BIT);
    weight_->use();
    weight_->set_vec4("u_rt_metrics", rt);
    weight_->set_int("u_edges_tex", 0);
    weight_->set_int("u_area_tex", 1);
    weight_->set_int("u_search_tex", 2);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, edges_tex_);
    glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, area_tex_);
    glActiveTexture(GL_TEXTURE2); glBindTexture(GL_TEXTURE_2D, search_tex_);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Pass 3: neighborhood blend -> dest_fbo
    glBindFramebuffer(GL_FRAMEBUFFER, dest_fbo);
    glViewport(0, 0, fw, fh);
    blend_->use();
    blend_->set_vec4("u_rt_metrics", rt);
    blend_->set_int("u_color_tex", 0);
    blend_->set_int("u_blend_tex", 1);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, ldr_color_tex);
    glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, weights_tex_);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    glBindVertexArray(0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glUseProgram(0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
```

> NOTE: if `renderer::Shader` has no `set_vec4`, add a thin `set_vec4(const std::string&, const glm::vec4&)` to `shader.{h,cc}` mirroring the existing `set_vec2` (grep `set_vec2` in `shader.cc` for the exact body — it is `glUniform2f(location(name), v.x, v.y)`; the vec4 version uses `glUniform4f(..., v.x, v.y, v.z, v.w)`). Fold that one-line addition into this task.

- [ ] **Step 7: Write the failing test**

`native/tests/renderer/smaa_pass_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/smaa_pass.h>
#include <renderer/window.h>
#include <memory>

namespace {
class SmaaPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64,64,"smaa-test",false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

// A synthetic LDR input with a hard diagonal edge, fed through SMAA, must
// produce GL-error-free non-black output in the backbuffer.
TEST_F(SmaaPassTest, RunsThreePassesErrorFreeAndProducesOutput) {
    // Build a 64x64 source texture: left half white, right half black.
    GLuint src = 0;
    glGenTextures(1, &src);
    glBindTexture(GL_TEXTURE_2D, src);
    std::vector<unsigned char> px(64*64*4, 0);
    for (int y = 0; y < 64; ++y)
        for (int x = 0; x < 32; ++x) {
            int i = (y*64 + x) * 4;
            px[i] = px[i+1] = px[i+2] = 255; px[i+3] = 255;
        }
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 64, 64, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, px.data());

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0,0,0,1);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::SmaaPass smaa;
    smaa.draw(src, /*dest_fbo=*/0, 64, 64);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    // The white half should still read white where unaffected by edge blending.
    unsigned char out[4] = {0,0,0,0};
    glReadPixels(8, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, out);
    EXPECT_GT(out[0], 200);  // non-black, ~white
    glDeleteTextures(1, &src);
}
}  // namespace
```
Add `smaa_pass_test.cc` to `add_executable(renderer_tests ...)` in `native/tests/renderer/CMakeLists.txt` (after `bloom_pass_test.cc`).

- [ ] **Step 8: Reconfigure, build, run the test (expect FAIL → then PASS)**

```bash
cmake -B build -S . && cmake --build build -j
ctest --test-dir build --output-on-failure -R SmaaPass
```
Expected: PASS once Steps 1-7 are correct. If it fails to compile, the most likely cause is a missing `set_vec4` on `Shader` (see NOTE in Step 6) or a shader compile error printed by `Shader` — fix and rebuild (re-run `cmake -B build -S .` after any shader edit).

- [ ] **Step 9: Commit**

```bash
git add native/src/renderer/smaa_pass.cc \
        native/src/renderer/include/renderer/smaa_pass.h \
        native/src/renderer/shaders/smaa_*.glsl native/src/renderer/shaders/smaa_*.vert native/src/renderer/shaders/smaa_*.frag \
        native/src/renderer/area_tex.h native/src/renderer/search_tex.h \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/smaa_pass_test.cc native/tests/renderer/CMakeLists.txt
git add native/src/renderer/shader.cc native/src/renderer/include/renderer/shader.h 2>/dev/null
git commit -m "feat(renderer): add SMAA 1x post-process pass (SmaaPass)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire SmaaPass into the frame + host binding

**Files:**
- Modify: `native/src/host/host_bindings.cc` (includes ~47, globals ~151-154, init ~314-316, shutdown ~367-369, frame ~599-613, binding ~1768-1771)

**Interfaces:**
- Consumes: `renderer::SmaaPass` from Task 1.
- Produces: host global `bool g_smaa_enabled` (default `true`) and pybind binding
  `_h.smaa_set_enabled(bool)`. The frame composites via SMAA when enabled.

### Step-by-step

- [ ] **Step 1: Add the include and globals**

In `native/src/host/host_bindings.cc`, after `#include <renderer/fxaa_pass.h>` (line 48) add:
```cpp
#include <renderer/smaa_pass.h>
```
After the `g_fxaa_*` globals (lines 153-154) add:
```cpp
std::unique_ptr<renderer::SmaaPass> g_smaa_pass;
bool g_smaa_enabled = true;   // post-process SMAA 1x; default on. Set by smaa_set_enabled.
```

- [ ] **Step 2: Construct and tear down**

After `g_fxaa_pass = std::make_unique<renderer::FxaaPass>();` (line 316) add:
```cpp
    g_smaa_pass    = std::make_unique<renderer::SmaaPass>();
```
Before `g_fxaa_pass.reset();` (line 367) add:
```cpp
    g_smaa_pass.reset();
```

- [ ] **Step 3: Replace the frame composite branch**

Replace the FXAA composite block (lines 599-613) with the SMAA equivalent:
```cpp
    const bool aa_on = g_smaa_enabled;
    if (aa_on) {
        g_ldr_target->resize(fw, fh);
        g_ldr_target->bind();
    } else {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
    }
    g_resolve_pass->set_hdr_enabled(dauntless_hdr::enabled());
    g_resolve_pass->draw(g_hdr_target->color_texture(), bloom_tex);
    if (aa_on) {
        // SMAA writes to the backbuffer (dest_fbo = 0); it sets its own viewport.
        g_smaa_pass->draw(g_ldr_target->color_texture(), /*dest_fbo=*/0, fw, fh);
    }
```
(`g_fxaa_pass` is now unused; it is deleted in Task 4.)

- [ ] **Step 4: Add the pybind binding**

After the `fxaa_set_enabled` binding (lines 1768-1771) add:
```cpp
    m.def("smaa_set_enabled",
          [](bool enabled) { g_smaa_enabled = enabled; },
          py::arg("enabled"),
          "Enable/disable the post-process SMAA 1x pass (default on).");
```
(Leave `fxaa_set_enabled` for now; removed in Task 4.)

- [ ] **Step 5: Rebuild dauntless and smoke-test**

```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build of `build/dauntless` AND `build/python/_open_stbc_host.*.so`. Then launch and visually confirm AA still works:
```bash
./build/dauntless
```
Expected: scene renders with anti-aliased edges (SMAA active by default). Toggling via the binding (`_dauntless_host.smaa_set_enabled(False)`) shows aliased edges. This is a manual visual check — the automated AA-pass test lives in Task 1.

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): composite frame via SMAA, add smaa_set_enabled binding

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Config UI — rename FXAA toggle to SMAA

**Files:**
- Modify: `engine/renderer.py:201-203`
- Modify: `engine/ui/configuration_panel.py` (field ~34, dispatch ~161-165, keynav ~241-242, focusables ~261-263, ctor param ~47, attr ~68)
- Modify: `engine/host_loop.py:3140`
- Modify: `native/assets/ui-cef/js/configuration_panel.js:131-140`
- Test: `tests/unit/test_configuration_panel.py`

**Interfaces:**
- Consumes: `_h.smaa_set_enabled` from Task 2.
- Produces: `renderer.set_smaa_enabled(bool)`; `SettingsSnapshot.smaa_on`;
  panel dispatch action `toggle:smaa`; ctor param `set_smaa`.

### Step-by-step

- [ ] **Step 1: Update the failing tests first**

In `tests/unit/test_configuration_panel.py`:
- In `_make()` (line ~32): rename `set_fxaa=Mock()` → `set_smaa=Mock()`.
- In `test_initial_settings_round_trip_to_render_payload` (line ~68): change `"fxaa_on": True,` → `"smaa_on": True,`.
- In the focus comment (line ~247): `ctrl:fxaa is the last focusable` → `ctrl:smaa is the last focusable`.
- Add a new applier test mirroring the dust one:
```python
def test_dispatch_toggle_smaa_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:smaa") is True
    kw["set_smaa"].assert_called_once_with(False)
    assert p.dispatch_event("toggle:smaa") is True
    kw["set_smaa"].assert_called_with(True)
```

- [ ] **Step 2: Run the tests, expect FAIL**

```bash
uv run pytest tests/unit/test_configuration_panel.py -v
```
Expected: FAIL — `ConfigurationPanel` has no `set_smaa` param / `fxaa_on` mismatch.

- [ ] **Step 3: Rename in the renderer wrapper**

In `engine/renderer.py` replace lines 201-203:
```python
def set_smaa_enabled(enabled: bool) -> None:
    """Toggle the post-process SMAA 1x pass. Default: on after init()."""
    _h.smaa_set_enabled(enabled)
```

- [ ] **Step 4: Rename in the panel**

In `engine/ui/configuration_panel.py`:
- `SettingsSnapshot.fxaa_on: bool = True` → `smaa_on: bool = True` (line ~34).
- Ctor param `set_fxaa: Callable[[bool], None],` → `set_smaa: Callable[[bool], None],` (line ~47).
- `self._set_fxaa = set_fxaa` → `self._set_smaa = set_smaa` (line ~68).
- Dispatch block (lines 161-165):
```python
        if action == "toggle:smaa":
            new_val = not self._settings.smaa_on
            self._set_smaa(new_val)
            self._settings.smaa_on = new_val
            return True
```
- Keynav (lines 241-242):
```python
        elif activate and kind == "ctrl" and target == "smaa":
            self.dispatch_event("toggle:smaa")
```
- Focusables (lines 261-263): replace `("ctrl", "fxaa")` with `("ctrl", "smaa")` and update the docstring example similarly (line ~258-263).

- [ ] **Step 5: Update the construction site**

In `engine/host_loop.py:3140` change:
```python
            set_smaa=r.set_smaa_enabled,
```

- [ ] **Step 6: Rename in the CEF panel**

In `native/assets/ui-cef/js/configuration_panel.js` replace the FXAA block (lines 131-140):
```javascript
    // SMAA toggle (post-process anti-aliasing)
    html += '<div class="cp-row' + (isFoc('smaa') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Anti-Aliasing (SMAA)</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.smaa_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:smaa\')">'
          +       (s.smaa_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';
```
(CEF JS needs no rebuild — it is loaded from assets at runtime.)

- [ ] **Step 7: Run the tests, expect PASS**

```bash
uv run pytest tests/unit/test_configuration_panel.py -v
```
Expected: PASS (including the new `test_dispatch_toggle_smaa_flips_and_calls_applier`).

- [ ] **Step 8: Commit**

```bash
git add engine/renderer.py engine/ui/configuration_panel.py engine/host_loop.py \
        native/assets/ui-cef/js/configuration_panel.js \
        tests/unit/test_configuration_panel.py
git commit -m "feat(config): replace FXAA toggle with Anti-Aliasing (SMAA)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Remove FXAA entirely

**Files:**
- Delete: `native/src/renderer/fxaa_pass.cc`, `native/src/renderer/include/renderer/fxaa_pass.h`
- Delete: `native/src/renderer/shaders/fxaa.vert`, `native/src/renderer/shaders/fxaa.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (drop fxaa embed + source)
- Modify: `native/src/host/host_bindings.cc` (drop fxaa include/globals/ctor/reset/binding)

**Interfaces:**
- Consumes: nothing new. SMAA (Tasks 1-3) fully replaces FXAA.
- Produces: no FXAA symbols remain anywhere.

### Step-by-step

- [ ] **Step 1: Delete the FXAA files**

```bash
git rm native/src/renderer/fxaa_pass.cc \
       native/src/renderer/include/renderer/fxaa_pass.h \
       native/src/renderer/shaders/fxaa.vert \
       native/src/renderer/shaders/fxaa.frag
```

- [ ] **Step 2: Remove FXAA from renderer CMake**

In `native/src/renderer/CMakeLists.txt` delete:
- `embed_shader(SHADER_FXAA_VS shaders/fxaa.vert fxaa_vs)`
- `embed_shader(SHADER_FXAA_FS shaders/fxaa.frag fxaa_fs)`
- the `fxaa_pass.cc` line in `add_library(renderer STATIC ...)`.

- [ ] **Step 3: Remove FXAA from host_bindings**

In `native/src/host/host_bindings.cc` delete:
- `#include <renderer/fxaa_pass.h>` (line ~48)
- `std::unique_ptr<renderer::FxaaPass> g_fxaa_pass;` and `bool g_fxaa_enabled = ...;` (lines ~153-154)
- `g_fxaa_pass = std::make_unique<renderer::FxaaPass>();` (line ~316)
- `g_fxaa_pass.reset();` (line ~367)
- the entire `m.def("fxaa_set_enabled", ...)` block (lines ~1768-1771)

- [ ] **Step 4: Verify no FXAA references remain**

```bash
grep -rin "fxaa" native/ engine/ tests/
```
Expected: NO output (empty). If anything prints, remove it.

- [ ] **Step 5: Reconfigure, build, and run the full renderer test suite**

```bash
cmake -B build -S . && cmake --build build -j
ctest --test-dir build --output-on-failure -R "Smaa|Resolve|Bloom|Frame"
uv run pytest tests/unit/test_configuration_panel.py -v
```
Expected: clean build, SMAA + resolve + bloom tests PASS, config-panel tests PASS. (`FrameTest.PhaserHeatGlow` is a known pre-existing failure unrelated to this work — see memory `project_cpp_ctest_not_in_run_tests`.)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(renderer): remove FXAA (replaced by SMAA 1x)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** SmaaPass + 3 passes + lookup textures (Task 1); pipeline slot + binding + default-on (Task 2); config UI Off/On rename + session-only (Task 3); FXAA removal (Task 4); C++ pass test + Python panel test (Tasks 1, 3). All spec sections mapped.
- **Out-of-scope items** (persistence, S2x/T2x, motion vectors, HDR-side changes) are intentionally absent — no tasks add them.
- **Type consistency:** `smaa_on` / `set_smaa` / `toggle:smaa` / `g_smaa_enabled` / `smaa_set_enabled` / `set_smaa_enabled` used consistently across Tasks 2-4. `SmaaPass::draw(color, dest_fbo, fw, fh)` signature matches between header (Task 1 Step 5), impl (Step 6), test (Step 7), and frame call (Task 2 Step 3).
- **Known external dependency:** the SMAA core (`smaa_lib.glsl`) and lookup-texture byte arrays (`area_tex.h`, `search_tex.h`) are vendored verbatim from iryoku/smaa (MIT). These are third-party data, not hand-authored — provenance and license retention are specified in Task 1 Steps 1 and 3.
