# FXAA Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-process FXAA pass to the renderer, exposed as an on/off control (default on) in the Graphics configuration panel.

**Architecture:** A new `FxaaPass` runs after the existing resolve pass. When FXAA is on, resolve writes to a new color-only `LdrTarget` FBO and FXAA samples that into the backbuffer; when off, resolve writes straight to the backbuffer (today's path, untouched). A file-local `g_fxaa_enabled` flag (default true) gates the branch and is driven from Python through the same toggle plumbing as the HDR/rim/decals settings.

**Tech Stack:** C++20 + OpenGL (glad/GLFW) renderer, pybind11 host bindings, Python UI panels, CEF (HTML/JS) configuration panel.

**Spec:** `docs/superpowers/specs/2026-06-08-fxaa-toggle-design.md`

---

## File Structure

**New files:**
- `native/src/renderer/include/renderer/ldr_target.h` — color-only RGBA8 FBO.
- `native/src/renderer/ldr_target.cc` — its implementation.
- `native/src/renderer/include/renderer/fxaa_pass.h` — FXAA fullscreen pass.
- `native/src/renderer/fxaa_pass.cc` — its implementation.
- `native/src/renderer/shaders/fxaa.vert` — fullscreen-triangle vertex shader.
- `native/src/renderer/shaders/fxaa.frag` — FXAA 3.11 (Simon Rodriguez) fragment shader.

**Modified files:**
- `native/src/renderer/CMakeLists.txt` — embed fxaa shaders + add the two new `.cc` to the `renderer` library.
- `native/src/host/host_bindings.cc` — includes, globals, init/teardown, frame wiring, binding.
- `engine/renderer.py` — `set_fxaa_enabled`.
- `engine/host_loop.py` — `SettingsSnapshot(fxaa_on=True, ...)` + `set_fxaa=r.set_fxaa_enabled`.
- `engine/ui/configuration_panel.py` — `fxaa_on` field, `set_fxaa` param, `toggle:fxaa` dispatch, render payload, focusables, key handling.
- `tests/unit/test_configuration_panel.py` — `_make` factory + new FXAA tests.
- `native/assets/ui-cef/js/configuration_panel.js` — FXAA row + focusable.

**Build commands (memory: new shaders/sources REQUIRE a reconfigure, not just `--build`):**
```bash
cmake -B build -S . && cmake --build build -j
```

**Test commands (memory: the full pytest suite OOMs the host — always use a focused subset):**
```bash
uv run pytest tests/unit/test_configuration_panel.py -q
```

---

## Task 1: LdrTarget — color-only RGBA8 FBO

**Files:**
- Create: `native/src/renderer/include/renderer/ldr_target.h`
- Create: `native/src/renderer/ldr_target.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `ldr_target.cc` to `add_library(renderer STATIC ...)`)

This is a trimmed `HdrTarget` (no depth attachment, RGBA8 instead of RGBA16F). No unit test harness exists for GL targets; verification is "it compiles and links."

- [ ] **Step 1: Create the header**

`native/src/renderer/include/renderer/ldr_target.h`:
```cpp
// native/src/renderer/include/renderer/ldr_target.h
#pragma once
#include <cstdint>

namespace renderer {

/// One offscreen RGBA8 color target (no depth). The resolve pass renders the
/// tonemapped LDR image here when FXAA is enabled; FxaaPass then samples
/// color_texture() back to the backbuffer. Mirrors HdrTarget's resize/bind
/// contract but without a depth renderbuffer.
class LdrTarget {
public:
    LdrTarget() = default;
    ~LdrTarget();
    LdrTarget(const LdrTarget&) = delete;
    LdrTarget& operator=(const LdrTarget&) = delete;

    /// (Re)allocate to w x h. No-op if already that size. Must be called with
    /// a current GL context before bind().
    void resize(int w, int h);

    /// Make this the draw framebuffer and set the viewport to its size. The
    /// caller must restore the default framebuffer + window viewport before any
    /// backbuffer-targeted draw afterwards. Must be called after resize().
    void bind() const;

    std::uint32_t color_texture() const { return color_tex_; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t color_tex_ = 0;
    int width_ = 0;
    int height_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 2: Create the implementation**

`native/src/renderer/ldr_target.cc`:
```cpp
// native/src/renderer/ldr_target.cc
#include "renderer/ldr_target.h"
#include <cassert>
#include <glad/glad.h>

namespace renderer {

LdrTarget::~LdrTarget() { destroy(); }

void LdrTarget::destroy() {
    if (color_tex_) { glDeleteTextures(1, &color_tex_); color_tex_ = 0; }
    if (fbo_)       { glDeleteFramebuffers(1, &fbo_); fbo_ = 0; }
}

void LdrTarget::resize(int w, int h) {
    if (w < 1) w = 1;
    if (h < 1) h = 1;
    if (w == width_ && h == height_ && fbo_ != 0) return;
    destroy();
    width_ = w; height_ = h;

    glGenTextures(1, &color_tex_);
    glBindTexture(GL_TEXTURE_2D, color_tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, color_tex_, 0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void LdrTarget::bind() const {
    assert(fbo_ != 0 && "LdrTarget::bind() before resize()");
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
}

}  // namespace renderer
```

- [ ] **Step 3: Add to the renderer library**

In `native/src/renderer/CMakeLists.txt`, inside `add_library(renderer STATIC ...)`, add `ldr_target.cc` immediately after the `hdr_target.cc` line:
```cmake
    hdr_target.cc
    ldr_target.cc
    bloom_pass.cc
```

- [ ] **Step 4: Configure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build; `ldr_target.cc.o` compiles. No warnings about unused — the class is referenced in Task 3.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/ldr_target.h native/src/renderer/ldr_target.cc native/src/renderer/CMakeLists.txt
git commit -m "feat(renderer): LdrTarget color-only RGBA8 FBO for FXAA

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: FxaaPass + shaders

**Files:**
- Create: `native/src/renderer/shaders/fxaa.vert`
- Create: `native/src/renderer/shaders/fxaa.frag`
- Create: `native/src/renderer/include/renderer/fxaa_pass.h`
- Create: `native/src/renderer/fxaa_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (embed lines + `fxaa_pass.cc` source)

No unit harness for GL passes; verification is compile + link.

- [ ] **Step 1: Create the vertex shader**

`native/src/renderer/shaders/fxaa.vert` (mirrors `resolve.vert` — bottom-up UV, no V flip):
```glsl
#version 330 core
layout(location=0) in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = (a_pos + 1.0) * 0.5;   // bottom-up; LDR texture is bottom-up (NO V flip)
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
```

- [ ] **Step 2: Create the fragment shader**

`native/src/renderer/shaders/fxaa.frag` (standard FXAA 3.11, Simon Rodriguez variant; luma from RGB, edge walk + subpixel):
```glsl
#version 330 core

in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_tex;
uniform vec2 u_inv_resolution;   // (1/width, 1/height)

#define EDGE_THRESHOLD_MIN 0.0312
#define EDGE_THRESHOLD_MAX 0.125
#define ITERATIONS 12
#define SUBPIXEL_QUALITY 0.75

float rgb2luma(vec3 rgb) {
    return sqrt(dot(rgb, vec3(0.299, 0.587, 0.114)));
}

float QUALITY(int i) {
    if (i < 5)  return 1.0;
    if (i == 5) return 1.5;
    if (i < 10) return 2.0;
    if (i == 10) return 4.0;
    return 8.0;
}

void main() {
    vec2 inverseScreenSize = u_inv_resolution;
    vec3 colorCenter = texture(u_tex, v_uv).rgb;

    float lumaCenter = rgb2luma(colorCenter);
    float lumaDown  = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 0, -1)).rgb);
    float lumaUp    = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 0,  1)).rgb);
    float lumaLeft  = rgb2luma(textureOffset(u_tex, v_uv, ivec2(-1,  0)).rgb);
    float lumaRight = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 1,  0)).rgb);

    float lumaMin = min(lumaCenter, min(min(lumaDown, lumaUp), min(lumaLeft, lumaRight)));
    float lumaMax = max(lumaCenter, max(max(lumaDown, lumaUp), max(lumaLeft, lumaRight)));
    float lumaRange = lumaMax - lumaMin;

    // Not an edge — passthrough.
    if (lumaRange < max(EDGE_THRESHOLD_MIN, lumaMax * EDGE_THRESHOLD_MAX)) {
        frag = vec4(colorCenter, 1.0);
        return;
    }

    float lumaDownLeft  = rgb2luma(textureOffset(u_tex, v_uv, ivec2(-1, -1)).rgb);
    float lumaUpRight   = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 1,  1)).rgb);
    float lumaUpLeft    = rgb2luma(textureOffset(u_tex, v_uv, ivec2(-1,  1)).rgb);
    float lumaDownRight = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 1, -1)).rgb);

    float lumaDownUp    = lumaDown + lumaUp;
    float lumaLeftRight = lumaLeft + lumaRight;
    float lumaLeftCorners  = lumaDownLeft + lumaUpLeft;
    float lumaDownCorners  = lumaDownLeft + lumaDownRight;
    float lumaRightCorners = lumaDownRight + lumaUpRight;
    float lumaUpCorners    = lumaUpRight + lumaUpLeft;

    float edgeHorizontal = abs(-2.0 * lumaLeft + lumaLeftCorners)
                         + abs(-2.0 * lumaCenter + lumaDownUp) * 2.0
                         + abs(-2.0 * lumaRight + lumaRightCorners);
    float edgeVertical   = abs(-2.0 * lumaUp + lumaUpCorners)
                         + abs(-2.0 * lumaCenter + lumaLeftRight) * 2.0
                         + abs(-2.0 * lumaDown + lumaDownCorners);

    bool isHorizontal = (edgeHorizontal >= edgeVertical);

    float luma1 = isHorizontal ? lumaDown : lumaLeft;
    float luma2 = isHorizontal ? lumaUp : lumaRight;
    float gradient1 = luma1 - lumaCenter;
    float gradient2 = luma2 - lumaCenter;

    bool is1Steepest = abs(gradient1) >= abs(gradient2);
    float gradientScaled = 0.25 * max(abs(gradient1), abs(gradient2));

    float stepLength = isHorizontal ? inverseScreenSize.y : inverseScreenSize.x;

    float lumaLocalAverage = 0.0;
    if (is1Steepest) {
        stepLength = -stepLength;
        lumaLocalAverage = 0.5 * (luma1 + lumaCenter);
    } else {
        lumaLocalAverage = 0.5 * (luma2 + lumaCenter);
    }

    vec2 currentUv = v_uv;
    if (isHorizontal) {
        currentUv.y += stepLength * 0.5;
    } else {
        currentUv.x += stepLength * 0.5;
    }

    vec2 offset = isHorizontal ? vec2(inverseScreenSize.x, 0.0)
                               : vec2(0.0, inverseScreenSize.y);
    vec2 uv1 = currentUv - offset;
    vec2 uv2 = currentUv + offset;

    float lumaEnd1 = rgb2luma(texture(u_tex, uv1).rgb) - lumaLocalAverage;
    float lumaEnd2 = rgb2luma(texture(u_tex, uv2).rgb) - lumaLocalAverage;

    bool reached1 = abs(lumaEnd1) >= gradientScaled;
    bool reached2 = abs(lumaEnd2) >= gradientScaled;
    bool reachedBoth = reached1 && reached2;

    if (!reached1) uv1 -= offset;
    if (!reached2) uv2 += offset;

    if (!reachedBoth) {
        for (int i = 2; i < ITERATIONS; i++) {
            if (!reached1) lumaEnd1 = rgb2luma(texture(u_tex, uv1).rgb) - lumaLocalAverage;
            if (!reached2) lumaEnd2 = rgb2luma(texture(u_tex, uv2).rgb) - lumaLocalAverage;
            reached1 = abs(lumaEnd1) >= gradientScaled;
            reached2 = abs(lumaEnd2) >= gradientScaled;
            reachedBoth = reached1 && reached2;
            if (!reached1) uv1 -= offset * QUALITY(i);
            if (!reached2) uv2 += offset * QUALITY(i);
            if (reachedBoth) break;
        }
    }

    float distance1 = isHorizontal ? (v_uv.x - uv1.x) : (v_uv.y - uv1.y);
    float distance2 = isHorizontal ? (uv2.x - v_uv.x) : (uv2.y - v_uv.y);

    bool isDirection1 = distance1 < distance2;
    float distanceFinal = min(distance1, distance2);
    float edgeThickness = (distance1 + distance2);
    float pixelOffset = -distanceFinal / edgeThickness + 0.5;

    bool isLumaCenterSmaller = lumaCenter < lumaLocalAverage;
    bool correctVariation = ((isDirection1 ? lumaEnd1 : lumaEnd2) < 0.0) != isLumaCenterSmaller;
    float finalOffset = correctVariation ? pixelOffset : 0.0;

    // Subpixel antialiasing.
    float lumaAverage = (1.0 / 12.0) * (2.0 * (lumaDownUp + lumaLeftRight)
                       + lumaLeftCorners + lumaRightCorners);
    float subPixelOffset1 = clamp(abs(lumaAverage - lumaCenter) / lumaRange, 0.0, 1.0);
    float subPixelOffset2 = (-2.0 * subPixelOffset1 + 3.0) * subPixelOffset1 * subPixelOffset1;
    float subPixelOffsetFinal = subPixelOffset2 * subPixelOffset2 * SUBPIXEL_QUALITY;

    finalOffset = max(finalOffset, subPixelOffsetFinal);

    vec2 finalUv = v_uv;
    if (isHorizontal) {
        finalUv.y += finalOffset * stepLength;
    } else {
        finalUv.x += finalOffset * stepLength;
    }

    frag = vec4(texture(u_tex, finalUv).rgb, 1.0);
}
```

- [ ] **Step 3: Create the pass header**

`native/src/renderer/include/renderer/fxaa_pass.h`:
```cpp
#pragma once
#include <cstdint>
#include <memory>
#include <renderer/shader.h>
namespace renderer {

class FxaaPass {
public:
    FxaaPass();
    ~FxaaPass();
    FxaaPass(const FxaaPass&) = delete;
    FxaaPass& operator=(const FxaaPass&) = delete;

    /// Draw a fullscreen triangle running FXAA over `ldr_color_tex` into the
    /// currently-bound framebuffer. Caller binds the target FBO + viewport
    /// first. `fw`,`fh` are the framebuffer pixel dims (for u_inv_resolution).
    /// Disables cull/depth/blend and restores them (mirrors ResolvePass).
    void draw(std::uint32_t ldr_color_tex, int fw, int fh);

private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 4: Create the pass implementation**

`native/src/renderer/fxaa_pass.cc` (mirrors `resolve_pass.cc`):
```cpp
// native/src/renderer/fxaa_pass.cc
//
// Fullscreen-triangle FXAA pass: samples the resolved LDR color texture and
// writes anti-aliased color to the currently-bound framebuffer.

#include <renderer/fxaa_pass.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include "embedded_fxaa_vs.h"
#include "embedded_fxaa_fs.h"

namespace renderer {

FxaaPass::FxaaPass()
    : shader_(std::make_unique<renderer::Shader>(
          shader_src::fxaa_vs, shader_src::fxaa_fs)) {
    // Fullscreen-triangle trick: one triangle covering [-1,3]² clipspace.
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

FxaaPass::~FxaaPass() {
    if (vbo_) glDeleteBuffers(1,      &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void FxaaPass::draw(std::uint32_t ldr_color_tex, int fw, int fh) {
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    const float inv_w = fw > 0 ? 1.0f / static_cast<float>(fw) : 0.0f;
    const float inv_h = fh > 0 ? 1.0f / static_cast<float>(fh) : 0.0f;

    shader_->use();
    shader_->set_int("u_tex", 0);
    shader_->set_vec2("u_inv_resolution", glm::vec2(inv_w, inv_h));

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, ldr_color_tex);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glUseProgram(0);
    glBindTexture(GL_TEXTURE_2D, 0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
```

- [ ] **Step 5: Wire into CMake**

In `native/src/renderer/CMakeLists.txt`, add the embed lines after the `SHADER_RESOLVE_FS` line (line 39):
```cmake
embed_shader(SHADER_FXAA_VS shaders/fxaa.vert fxaa_vs)
embed_shader(SHADER_FXAA_FS shaders/fxaa.frag fxaa_fs)
```
And add `fxaa_pass.cc` after `resolve_pass.cc` in `add_library(renderer STATIC ...)`:
```cmake
    resolve_pass.cc
    fxaa_pass.cc
```

- [ ] **Step 6: Configure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build; `embedded_fxaa_vs.h` / `embedded_fxaa_fs.h` generated, `fxaa_pass.cc.o` compiles and links into `librenderer`.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/shaders/fxaa.vert native/src/renderer/shaders/fxaa.frag \
        native/src/renderer/include/renderer/fxaa_pass.h native/src/renderer/fxaa_pass.cc \
        native/src/renderer/CMakeLists.txt
git commit -m "feat(renderer): FxaaPass + FXAA 3.11 shaders

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Wire FXAA into the frame + expose the binding

**Files:**
- Modify: `native/src/host/host_bindings.cc` (includes, globals, init/teardown, frame, binding)

No C++ unit harness; verification is build + the off-path being byte-identical. Functional verification is visual/runtime.

- [ ] **Step 1: Add includes**

In `native/src/host/host_bindings.cc`, next to the existing `#include <renderer/resolve_pass.h>` (line 34), add:
```cpp
#include <renderer/ldr_target.h>
#include <renderer/fxaa_pass.h>
```

- [ ] **Step 2: Add globals**

After the `g_resolve_pass` global declaration (line 97), add:
```cpp
std::unique_ptr<renderer::LdrTarget>       g_ldr_target;
std::unique_ptr<renderer::FxaaPass>        g_fxaa_pass;
bool g_fxaa_enabled = true;   // post-process FXAA; default on. Set by fxaa_set_enabled.
```

- [ ] **Step 3: Construct in init()**

After `g_resolve_pass = std::make_unique<renderer::ResolvePass>();` (line 197), add:
```cpp
    g_ldr_target   = std::make_unique<renderer::LdrTarget>();
    g_fxaa_pass    = std::make_unique<renderer::FxaaPass>();
```

- [ ] **Step 4: Tear down in shutdown()**

In `shutdown()`, immediately before `g_resolve_pass.reset();` (line 229), add:
```cpp
    g_fxaa_pass.reset();
    g_ldr_target.reset();
```

- [ ] **Step 5: Branch the resolve target in frame()**

Replace the resolve block at lines 323-329 (from the `// Resolve the HDR target back to the default framebuffer` comment through `g_resolve_pass->draw(...)`) with:
```cpp
    // Resolve the HDR target. When FXAA is on, resolve into an LDR intermediate
    // target and then run FXAA into the backbuffer; when off, resolve straight
    // to the backbuffer (unchanged, zero-added-cost path). CEF composite + swap
    // run after this so the overlay composites on top of the resolved 3D scene.
    const bool fxaa_on = g_fxaa_enabled;
    if (fxaa_on) {
        g_ldr_target->resize(fw, fh);
        g_ldr_target->bind();
    } else {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
    }
    g_resolve_pass->set_hdr_enabled(dauntless_hdr::enabled());
    g_resolve_pass->draw(g_hdr_target->color_texture(), bloom_tex);
    if (fxaa_on) {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
        g_fxaa_pass->draw(g_ldr_target->color_texture(), fw, fh);
    }
```

- [ ] **Step 6: Add the pybind binding**

In the bindings block, after the `decals_set_enabled` `m.def(...)` (ends line 742), add:
```cpp
    m.def("fxaa_set_enabled",
          [](bool enabled) { g_fxaa_enabled = enabled; },
          py::arg("enabled"),
          "Enable/disable the post-process FXAA pass (default on).");
```

- [ ] **Step 7: Build**

Run: `cmake --build build -j`
Expected: clean build; `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` relink.

- [ ] **Step 8: Smoke-check the symbol is exposed**

Run:
```bash
./build/python/../dauntless --help >/dev/null 2>&1; \
python3 -c "import sys; sys.path.insert(0,'build/python'); import _open_stbc_host as h; print(hasattr(h,'fxaa_set_enabled'))"
```
Expected: prints `True`. (If it prints `False`, the `.so` is stale — rebuild from `build/`, do not edit Python.)

- [ ] **Step 9: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(renderer): run FXAA after resolve; fxaa_set_enabled binding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: ConfigurationPanel FXAA toggle (TDD)

**Files:**
- Modify: `tests/unit/test_configuration_panel.py` (`_make` factory + new tests)
- Modify: `engine/ui/configuration_panel.py`

The `_make` factory must add `set_fxaa=Mock()` because `set_fxaa` becomes a required constructor argument — do Step 1 and Step 3 together so the existing suite keeps passing.

- [ ] **Step 1: Update the test factory and write failing tests**

In `tests/unit/test_configuration_panel.py`, add `set_fxaa=Mock(),` to the `kwargs` dict in `_make` (after `set_decals=Mock(),`, around line 31):
```python
        set_decals=Mock(),
        set_fxaa=Mock(),
        set_fov_rad=Mock(),
```
Then append these tests to the end of the file:
```python
# ---- fxaa toggle ----------------------------------------------------------

def test_toggle_fxaa_fires_applier_and_flips_state():
    p, kw = _make()
    p.open()
    assert p._settings.fxaa_on is True
    assert p.dispatch_event("toggle:fxaa") is True
    kw["set_fxaa"].assert_called_once_with(False)
    assert p._settings.fxaa_on is False


def test_render_payload_includes_fxaa_on():
    p, _ = _make()
    p.open()
    payload = json.loads(p.render_payload()[len("setConfigurationPanel("):-len(");")])
    assert payload["settings"]["fxaa_on"] is True


def test_fxaa_is_a_graphics_focusable():
    p, _ = _make()
    assert ("ctrl", "fxaa") in p._focusables()


def test_space_on_fxaa_row_toggles():
    p, kw = _make()
    p.open()
    p._focused = p._focusables().index(("ctrl", "fxaa"))

    class _Keys:
        KEY_DOWN = 1; KEY_UP = 2; KEY_SPACE = 3; KEY_ENTER = 4
        KEY_LEFT = 5; KEY_RIGHT = 6

    class _H:
        keys = _Keys()
        def key_pressed(self, code):
            return code == _Keys.KEY_SPACE

    p.handle_input(_H())
    kw["set_fxaa"].assert_called_once_with(False)
    assert p._settings.fxaa_on is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_configuration_panel.py -q`
Expected: the four new tests FAIL (constructor rejects `set_fxaa` / `SettingsSnapshot` has no `fxaa_on`). Existing tests may also error until Step 3 lands — that's expected because `_make` now passes `set_fxaa`.

- [ ] **Step 3: Implement in `engine/ui/configuration_panel.py`**

a) Add `fxaa_on` to `SettingsSnapshot` (defaulted `True` so snapshots built without it still work — it must come last since the other fields have no defaults):
```python
@dataclass
class SettingsSnapshot:
    dust_on: bool
    specular_on: bool
    hdr_on: bool
    rim_on: bool
    decals_on: bool
    fov_deg: int
    fxaa_on: bool = True
```

b) Add the `set_fxaa` parameter to `__init__` (after `set_decals`):
```python
                 set_decals: Callable[[bool], None],
                 set_fxaa: Callable[[bool], None],
                 set_fov_rad: Callable[[float], None]):
```

c) Copy `fxaa_on` into the panel's own `SettingsSnapshot` (in the `self._settings = SettingsSnapshot(...)` block, after `decals_on=...`):
```python
            decals_on=initial_settings.decals_on,
            fxaa_on=initial_settings.fxaa_on,
            fov_deg=int(initial_settings.fov_deg),
```

d) Store the applier (after `self._set_decals = set_decals`):
```python
        self._set_decals = set_decals
        self._set_fxaa = set_fxaa
```

e) In `render_payload`, add `self._settings.fxaa_on` to the `snapshot` tuple (after `self._settings.decals_on,`) and `"fxaa_on": self._settings.fxaa_on,` to the `settings` dict (after the `decals_on` entry):
```python
            self._settings.decals_on,
            self._settings.fxaa_on,
            self._settings.fov_deg,
```
```python
                "decals_on": self._settings.decals_on,
                "fxaa_on": self._settings.fxaa_on,
                "fov_deg": self._settings.fov_deg,
```

f) Add the dispatch branch (after the `toggle:decals` branch, before `if action.startswith("fov:")`):
```python
        if action == "toggle:fxaa":
            new_val = not self._settings.fxaa_on
            self._set_fxaa(new_val)
            self._settings.fxaa_on = new_val
            return True
```

g) Add `("ctrl", "fxaa")` to `_focusables` (after `("ctrl", "decals")`):
```python
            out += [("ctrl", "dust"), ("ctrl", "specular"), ("ctrl", "fov"),
                    ("ctrl", "hdr"), ("ctrl", "rim"), ("ctrl", "decals"),
                    ("ctrl", "fxaa")]
```

h) Add the activate branch in `handle_input` (after the `decals` elif, before the `tab` elif):
```python
        elif activate and kind == "ctrl" and target == "decals":
            self.dispatch_event("toggle:decals")
        elif activate and kind == "ctrl" and target == "fxaa":
            self.dispatch_event("toggle:fxaa")
        elif activate and kind == "tab":
            self.dispatch_event("tab:" + target)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_configuration_panel.py -q`
Expected: all tests PASS (the four new ones plus the pre-existing suite).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/configuration_panel.py tests/unit/test_configuration_panel.py
git commit -m "feat(ui): FXAA on/off control in configuration panel

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Renderer wrapper + host_loop wiring

**Files:**
- Modify: `engine/renderer.py` (add `set_fxaa_enabled`)
- Modify: `engine/host_loop.py` (SettingsSnapshot + ConfigurationPanel call)

- [ ] **Step 1: Add the renderer wrapper**

In `engine/renderer.py`, after `set_decals_enabled` (ends ~line 179), add:
```python
def set_fxaa_enabled(enabled: bool) -> None:
    """Toggle the post-process FXAA pass. Default: on after init()."""
    _h.fxaa_set_enabled(enabled)
```

- [ ] **Step 2: Wire defaults + applier in host_loop**

In `engine/host_loop.py`, in the `ConfigurationPanel(...)` construction (lines 2058-2076):

a) Add `fxaa_on=True,` to the `SettingsSnapshot(...)` (after `decals_on=True,`):
```python
                decals_on=True,
                fxaa_on=True,
                fov_deg=int(round(_math.degrees(
                    director.fov_y_rad
                ))),
```

b) Add the applier (after `set_decals=r.set_decals_enabled,`):
```python
            set_decals=r.set_decals_enabled,
            set_fxaa=r.set_fxaa_enabled,
            set_fov_rad=director.set_fov,
```

- [ ] **Step 3: Verify the wrapper imports cleanly**

Run:
```bash
uv run python -c "import engine.renderer as r; print(hasattr(r, 'set_fxaa_enabled'))"
```
Expected: prints `True`. (This imports the module; it does not need the host `.so` since `set_fxaa_enabled` only references `_h` at call time.)

- [ ] **Step 4: Commit**

```bash
git add engine/renderer.py engine/host_loop.py
git commit -m "feat(host): wire FXAA toggle (default on) through host_loop

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Configuration panel JS — FXAA row

**Files:**
- Modify: `native/assets/ui-cef/js/configuration_panel.js`

No JS unit harness; verification is visual at runtime. Mirror the HDR row exactly.

- [ ] **Step 1: Register the focusable**

In `_cpFocusableList`, after `out.push({kind: 'ctrl', target: 'decals'});`, add:
```javascript
        out.push({kind: 'ctrl', target: 'fxaa'});
```

- [ ] **Step 2: Render the FXAA row**

In `_cpRenderGraphicsBody`, after the Damage Decals row block (the `html += ...` ending at the `return html;`), and before `return html;`, add:
```javascript
    // FXAA toggle (post-process anti-aliasing)
    html += '<div class="cp-row' + (isFoc('fxaa') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">FXAA</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.fxaa_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:fxaa\')">'
          +       (s.fxaa_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';

```

- [ ] **Step 3: Sanity-check the JS parses**

Run: `node --check native/assets/ui-cef/js/configuration_panel.js`
Expected: no output (exit 0). If `node` is unavailable, skip — the file is plain ES5 mirroring existing rows.

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/js/configuration_panel.js
git commit -m "feat(ui-cef): FXAA toggle row in graphics configuration panel

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Build clean from a reconfigure:** `cmake -B build -S . && cmake --build build -j` — no errors.
- [ ] **Focused tests pass:** `uv run pytest tests/unit/test_configuration_panel.py -q` — all green.
- [ ] **Binding present:** `python3 -c "import sys; sys.path.insert(0,'build/python'); import _open_stbc_host as h; print(hasattr(h,'fxaa_set_enabled'))"` — `True`.
- [ ] **Runtime visual (manual, optional):** launch `./build/dauntless`, open pause → Configuration → Graphics, confirm the FXAA row reads "On" by default and toggling it visibly hardens/softens edge aliasing on ship hulls.

## Self-review notes (addressed)

- **Spec coverage:** LdrTarget (Task 1), FxaaPass+shaders (Task 2), toggle namespace/binding/frame wiring (Task 3), panel field/dispatch/payload/focusables (Task 4), renderer.py + host_loop defaults (Task 5), JS row (Task 6), tests (Task 4). All spec sections mapped.
- **Type consistency:** `set_fxaa_enabled` (renderer.py) ↔ `fxaa_set_enabled` (pybind, `_h.`) ↔ `set_fxaa` (panel ctor param) ↔ `toggle:fxaa` (dispatch/JS) ↔ `fxaa_on` (SettingsSnapshot/payload) — consistent across tasks. `g_fxaa_enabled` is the single C++ source of truth.
- **No placeholders:** every code step contains complete content.
