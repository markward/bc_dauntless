# Filmic Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single "Filmic Filter" toggle under the Modern VFX config group that applies film grain, vignette, and chromatic aberration to the main exterior space view via a dedicated final post-process pass.

**Architecture:** A new `renderer::FilmicPass` mirrors `ResolvePass`/`SmaaPass` (fullscreen triangle, embedded `filmic.frag`, reusing `resolve.vert`). It runs **last** in the post chain — after tonemap and after SMAA — and only when the view is exterior (`!viewer_mode && !bridge_active`) and the toggle is on. A `dauntless_filmic` flag namespace + `filmic_set_enabled` binding + `engine.renderer.set_filmic_enabled` wrapper + config-panel row mirror the Procedural Sky toggle (commit `f4535337`) end to end.

**Tech Stack:** C++17, OpenGL 3.3 core (GLSL 330), GLAD, pybind11, GoogleTest (ctest), Python 3, pytest, CEF (vanilla JS UI).

## Global Constraints

- One build tree at `<root>/build/`. Binary `build/dauntless`; module `build/python/_open_stbc_host.cpython-*.so`. Never build from inside `native/`.
- Shader (`.vert`/`.frag`) changes require re-running `cmake -B build -S .` BEFORE `cmake --build build -j` — embedded shaders regenerate at configure time.
- `host_bindings.cc` is compiled into BOTH `build/dauntless` and the `_dauntless_host` module — edits need a full `dauntless` rebuild, not just the module.
- Default **on**, not persisted across launches.
- Filter applies to the main exterior space view ONLY. Bridge interior, bridge viewscreen inset, comm sets, and the Ship Property Viewer (hologram) are unaffected; for any non-exterior view or when the toggle is off, the render path is byte-identical to today.
- Effect strengths are named `const float` at the top of `filmic.frag`, tuned by feel.
- Python 1.5 constraints apply only to `tools/` snippet code, NOT to `engine/` — ignore them here.

---

## File Structure

- Create `native/src/renderer/include/renderer/filmic_pass.h` — `FilmicPass` class declaration.
- Create `native/src/renderer/filmic_pass.cc` — `FilmicPass` implementation.
- Create `native/src/renderer/shaders/filmic.frag` — grain + vignette + CA fragment shader.
- Create `native/tests/renderer/filmic_pass_test.cc` — GL unit tests for the pass.
- Modify `native/src/renderer/frame.cc` — add `dauntless_filmic` toggle namespace.
- Modify `native/src/renderer/CMakeLists.txt` — embed `filmic.frag`, add `filmic_pass.cc` to the renderer lib.
- Modify `native/tests/renderer/CMakeLists.txt` — add `filmic_pass_test.cc` to `renderer_tests`.
- Modify `native/tests/renderer/frame_test.cc` — add a `dauntless_filmic` toggle round-trip test.
- Modify `native/src/host/host_bindings.cc` — globals (`g_filmic_pass`, `g_ldr_target2`), init/shutdown, frame() routing, `filmic_set_enabled`/`filmic_enabled` bindings.
- Modify `engine/renderer.py` — `filmic_enabled()` + `set_filmic_enabled()` wrappers.
- Modify `engine/ui/configuration_panel.py` — `filmic_on` setting, `set_filmic` applier, dispatch/focus/payload.
- Modify `tests/unit/test_configuration_panel.py` — applier mock, round-trip, toggle, payload tests.
- Modify `native/assets/ui-cef/js/configuration_panel.js` — focus list entry + graphics row.
- Modify `engine/host_loop.py` — initial `filmic_on` snapshot + `set_filmic` applier wiring.

---

## Task 1: C++ filmic toggle namespace

**Files:**
- Modify: `native/src/renderer/frame.cc` (after the `dauntless_procedural_sky` namespace, ~line 102)
- Test: `native/tests/renderer/frame_test.cc` (after the `DauntlessDecalsToggle` test, ~line 30)

**Interfaces:**
- Produces: `namespace dauntless_filmic { bool enabled(); void set_enabled(bool); }` — default `true`. Consumed by host_bindings (Task 3) and the frame test.

- [ ] **Step 1: Write the failing test** in `native/tests/renderer/frame_test.cc`. Add the forward declaration next to the existing `dauntless_decals` one (~line 21) and the test next to `DauntlessDecalsToggle` (~line 30):

```cpp
namespace dauntless_filmic { bool enabled(); void set_enabled(bool); }

TEST(DauntlessFilmicToggle, DefaultsOnAndRoundTrips) {
    EXPECT_TRUE(dauntless_filmic::enabled());      // default on
    dauntless_filmic::set_enabled(false);
    EXPECT_FALSE(dauntless_filmic::enabled());
    dauntless_filmic::set_enabled(true);           // restore for other tests
    EXPECT_TRUE(dauntless_filmic::enabled());
}
```

- [ ] **Step 2: Run the test to verify it fails (link error)**

Run: `cmake --build build -j --target renderer_tests`
Expected: FAIL — undefined reference to `dauntless_filmic::enabled()` / `set_enabled`.

- [ ] **Step 3: Add the namespace** in `native/src/renderer/frame.cc` immediately after the closing `}` of `namespace dauntless_procedural_sky` (mirror its exact shape):

```cpp
namespace dauntless_filmic {
    bool g_filmic_enabled = true;
    bool enabled() { return g_filmic_enabled; }
    void set_enabled(bool v) { g_filmic_enabled = v; }
}
```

- [ ] **Step 4: Build and run the test**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R DauntlessFilmicToggle --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/frame.cc native/tests/renderer/frame_test.cc
git commit -m "feat(vfx): add dauntless_filmic toggle namespace (default on)"
```

---

## Task 2: FilmicPass class + shader

**Files:**
- Create: `native/src/renderer/include/renderer/filmic_pass.h`
- Create: `native/src/renderer/filmic_pass.cc`
- Create: `native/src/renderer/shaders/filmic.frag`
- Create: `native/tests/renderer/filmic_pass_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (embed at ~line 51, source list at ~line 84)
- Modify: `native/tests/renderer/CMakeLists.txt` (add to `renderer_tests`)

**Interfaces:**
- Consumes: existing `shader_src::resolve_vs` (the fullscreen-triangle vertex shader, reused).
- Produces: `renderer::FilmicPass` with `void draw(std::uint32_t src_tex, std::uint32_t dest_fbo, int fw, int fh, float time_seconds)`. Consumed by host_bindings (Task 3).

- [ ] **Step 1: Create the fragment shader** `native/src/renderer/shaders/filmic.frag`:

```glsl
#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_src;
uniform float u_time;

// Filmic grade strengths — eye-tunable by rebuilding (like the resolve-grade
// consts). Applied in final display space, after tonemap + AA.
const float GRAIN_STRENGTH    = 0.05;   // peak +/- luma jitter at midtones
const float VIGNETTE_STRENGTH = 0.28;   // corner darkening fraction
const float CA_STRENGTH       = 0.005;  // chromatic split, UV units at the corner

// Cheap hash noise in [0,1).
float hash(vec2 p) {
    p = fract(p * vec2(443.897, 441.423));
    p += dot(p, p + 19.19);
    return fract((p.x + p.y) * p.x);
}

void main() {
    vec2 uv = v_uv;
    vec2 d  = uv - vec2(0.5);
    float r = length(d);

    // Chromatic aberration: push R out / B in along the radial, scaled by r
    // so the center is clean and corners separate most.
    vec2 ca = d * (r * CA_STRENGTH);
    vec3 col = vec3(
        texture(u_src, uv + ca).r,
        texture(u_src, uv).g,
        texture(u_src, uv - ca).b);

    // Vignette: smooth radial darkening. smoothstep(0.8,0.45,r) is 1 at center,
    // falling toward the corners (r ~= 0.707).
    float vig = smoothstep(0.8, 0.45, r);
    col *= mix(1.0 - VIGNETTE_STRENGTH, 1.0, vig);

    // Film grain: animated hash noise, weighted toward midtones (less in deep
    // shadow / blown highlight). fract(u_time) reseeds each frame.
    float n   = hash(uv * vec2(1920.0, 1080.0) + fract(u_time) * 100.0) - 0.5;
    float luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
    float midweight = 1.0 - abs(luma - 0.5) * 2.0;   // 1 at mid, 0 at extremes
    col += n * GRAIN_STRENGTH * midweight;

    frag_color = vec4(clamp(col, 0.0, 1.0), 1.0);
}
```

- [ ] **Step 2: Create the header** `native/src/renderer/include/renderer/filmic_pass.h`:

```cpp
#pragma once
#include <cstdint>
#include <memory>
#include <renderer/shader.h>
namespace renderer {

/// Filmic post-process: film grain + vignette + chromatic aberration over a
/// final-display-space LDR color texture. Reuses the fullscreen-triangle vertex
/// shader (resolve.vert). Runs last in the post chain (after tonemap + SMAA),
/// applied only to the exterior space view.
class FilmicPass {
public:
    FilmicPass();
    ~FilmicPass();
    FilmicPass(const FilmicPass&) = delete;
    FilmicPass& operator=(const FilmicPass&) = delete;

    /// Draw a fullscreen triangle sampling `src_tex` into `dest_fbo`
    /// (0 = backbuffer), setting the viewport to `fw`x`fh`. `time_seconds`
    /// animates the grain. Disables cull/depth/blend and restores them.
    void draw(std::uint32_t src_tex, std::uint32_t dest_fbo,
              int fw, int fh, float time_seconds);
private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
};
}  // namespace renderer
```

- [ ] **Step 3: Create the implementation** `native/src/renderer/filmic_pass.cc`:

```cpp
// native/src/renderer/filmic_pass.cc
//
// Fullscreen-triangle filmic pass: grain + vignette + chromatic aberration
// over a final-display-space LDR color texture. Reuses resolve.vert.

#include <renderer/filmic_pass.h>

#include <glad/glad.h>

#include "embedded_resolve_vs.h"
#include "embedded_filmic_fs.h"

namespace renderer {

FilmicPass::FilmicPass()
    : shader_(std::make_unique<renderer::Shader>(
          shader_src::resolve_vs, shader_src::filmic_fs)) {
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

FilmicPass::~FilmicPass() {
    if (vbo_) glDeleteBuffers(1,      &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void FilmicPass::draw(std::uint32_t src_tex, std::uint32_t dest_fbo,
                      int fw, int fh, float time_seconds) {
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);

    glBindFramebuffer(GL_FRAMEBUFFER, dest_fbo);
    glViewport(0, 0, fw, fh);

    // The fullscreen triangle winds CCW; the Pipeline sets CW front-facing, so
    // it would be culled as a back face → black screen. Disable + restore.
    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);

    shader_->use();
    shader_->set_int("u_src", 0);
    shader_->set_float("u_time", time_seconds);

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

- [ ] **Step 4: Wire CMake.** In `native/src/renderer/CMakeLists.txt`, add an embed line right after the `SHADER_RESOLVE_FS` line (~line 51):

```cmake
embed_shader(SHADER_FILMIC_FS shaders/filmic.frag filmic_fs)
```

And add `filmic_pass.cc` to the renderer library source list right after `resolve_pass.cc` (~line 83):

```cmake
    filmic_pass.cc
```

- [ ] **Step 5: Create the GL unit test** `native/tests/renderer/filmic_pass_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/ldr_target.h>
#include <renderer/filmic_pass.h>
#include <renderer/window.h>
#include <memory>

namespace {
class FilmicPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64,64,"filmic-test",false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

// Center pixel: CA offset is ~0 and the vignette is ~full there, so a mid-grey
// input survives close to itself (only grain jitter). Confirms the pass runs
// GL-error-free and is roughly identity at the screen center.
TEST_F(FilmicPassTest, MidGreyCenterSurvivesWithinGrainTolerance) {
    renderer::LdrTarget src;
    src.resize(32, 32);
    src.bind();
    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::FilmicPass f;
    f.draw(src.color_texture(), /*dest_fbo=*/0, 64, 64, /*time=*/0.0f);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_NEAR(px[0], 128, 20);   // ~grey, within grain jitter
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Vignette must darken the corners relative to the center on a uniform input.
TEST_F(FilmicPassTest, VignetteDarkensCorners) {
    renderer::LdrTarget src;
    src.resize(32, 32);
    src.bind();
    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::FilmicPass f;
    f.draw(src.color_texture(), /*dest_fbo=*/0, 64, 64, /*time=*/0.0f);

    unsigned char center[4] = {0}, corner[4] = {0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
    glReadPixels(1,  1,  1, 1, GL_RGBA, GL_UNSIGNED_BYTE, corner);
    EXPECT_LT(corner[0] + 10, center[0]);   // corner clearly darker than center
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Regression: the fullscreen triangle must survive the Pipeline's CW-front,
// back-face cull state (else the screen is black).
TEST_F(FilmicPassTest, DrawsWhenBackfaceCullingEnabled) {
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CW);

    renderer::LdrTarget src;
    src.resize(32, 32);
    src.bind();
    glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);   // black if the triangle is culled
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::FilmicPass f;
    f.draw(src.color_texture(), /*dest_fbo=*/0, 64, 64, /*time=*/0.0f);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_GT(px[0], 80);   // would be 0 if culled

    glDisable(GL_CULL_FACE);   // leave global state clean
}
}  // namespace
```

- [ ] **Step 6: Register the test** in `native/tests/renderer/CMakeLists.txt`, adding `filmic_pass_test.cc` right after `resolve_pass_test.cc` in the `add_executable(renderer_tests ...)` list:

```cmake
    filmic_pass_test.cc
```

- [ ] **Step 7: Reconfigure (new shader) + build + run**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ctest --test-dir build -R FilmicPassTest --output-on-failure`
Expected: 3 FilmicPassTest cases PASS (or SKIP if no GL context available — acceptable in headless CI; rerun locally with a display to confirm PASS).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/filmic_pass.h \
        native/src/renderer/filmic_pass.cc \
        native/src/renderer/shaders/filmic.frag \
        native/tests/renderer/filmic_pass_test.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(vfx): add FilmicPass (grain + vignette + chromatic aberration)"
```

---

## Task 3: Host integration — globals, routing, bindings, Python wrapper

**Files:**
- Modify: `native/src/host/host_bindings.cc` (globals ~line 170, init ~line 339, shutdown ~line 397, frame routing ~line 708–725, bindings ~line 1906)
- Modify: `engine/renderer.py` (after `procedural_sky_enabled`, ~line 164)

**Interfaces:**
- Consumes: `renderer::FilmicPass` (Task 2); `dauntless_filmic::enabled()` (Task 1); existing `g_ldr_target`, `g_smaa_pass`, `g_resolve_pass`, `viewer_mode`, `bridge_active`, `now`.
- Produces: bindings `_dauntless_host.filmic_set_enabled(bool)` and `_dauntless_host.filmic_enabled() -> bool`; `engine.renderer.set_filmic_enabled(bool)` and `engine.renderer.filmic_enabled() -> bool`. Consumed by config panel (Task 4) and host_loop (Task 6).

- [ ] **Step 1: Add the include and forward-declare the toggle.** Near the other renderer pass includes at the top of `host_bindings.cc`, add `#include <renderer/filmic_pass.h>`. With the other `namespace dauntless_* { ... }` forward declarations used in this file, ensure `dauntless_filmic` is visible (it is referenced from `frame.cc`; add a forward declaration if the file declares the others locally):

```cpp
namespace dauntless_filmic { bool enabled(); void set_enabled(bool); }
```

(Only add this forward declaration if the file does not already pull it in via a shared header — match how `dauntless_procedural_sky` is referenced at line 481/509.)

- [ ] **Step 2: Add globals** next to `g_ldr_target` (~line 170–171):

```cpp
std::unique_ptr<renderer::LdrTarget>   g_ldr_target2;   // SMAA→filmic intermediate
std::unique_ptr<renderer::FilmicPass>  g_filmic_pass;
```

- [ ] **Step 3: Construct them in init** next to `g_ldr_target = ...` (~line 339–340):

```cpp
g_ldr_target2  = std::make_unique<renderer::LdrTarget>();
g_filmic_pass  = std::make_unique<renderer::FilmicPass>();
```

- [ ] **Step 4: Reset them in shutdown** next to `g_ldr_target.reset()` (~line 397), in reverse construction order:

```cpp
g_filmic_pass.reset();
g_ldr_target2.reset();
```

- [ ] **Step 5: Rewrite the resolve/SMAA routing block** (`host_bindings.cc` ~lines 712–725). Replace the existing block:

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

with this filmic-aware version (filmic runs last, exterior-only):

```cpp
    const bool aa_on     = g_smaa_enabled;
    // Filmic only on the main exterior space view, never bridge/viewer/viewscreen.
    const bool filmic_on = dauntless_filmic::enabled() && !viewer_mode && !bridge_active;

    // Resolve target: an LDR intermediate if any post stage (SMAA or filmic)
    // follows; otherwise straight to the backbuffer (unchanged zero-cost path).
    if (aa_on || filmic_on) {
        g_ldr_target->resize(fw, fh);
        g_ldr_target->bind();
    } else {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
    }
    g_resolve_pass->set_hdr_enabled(dauntless_hdr::enabled());
    g_resolve_pass->draw(g_hdr_target->color_texture(), bloom_tex);

    if (aa_on) {
        // With filmic following, SMAA writes into a second LDR target; otherwise
        // straight to the backbuffer. SMAA sets its own viewport.
        std::uint32_t smaa_dest = 0;
        if (filmic_on) {
            g_ldr_target2->resize(fw, fh);
            smaa_dest = g_ldr_target2->fbo();
        }
        g_smaa_pass->draw(g_ldr_target->color_texture(), smaa_dest, fw, fh);
    }

    if (filmic_on) {
        // Source is whatever the previous final stage wrote: SMAA's output
        // (g_ldr_target2) when AA is on, else the resolve output (g_ldr_target).
        const std::uint32_t src = aa_on ? g_ldr_target2->color_texture()
                                        : g_ldr_target->color_texture();
        g_filmic_pass->draw(src, /*dest_fbo=*/0, fw, fh, static_cast<float>(now));
    }
```

- [ ] **Step 6: Add the bindings** in the `PYBIND11_MODULE` block, right after the `procedural_sky_enabled` binding (~line 1909):

```cpp
    m.def("filmic_set_enabled",
          [](bool enabled) { dauntless_filmic::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the Filmic Filter (Modern VFX): grain + vignette + chromatic "
          "aberration on the exterior view. Default: on.");
    m.def("filmic_enabled",
          []() { return dauntless_filmic::enabled(); },
          "Read the Filmic Filter toggle (Modern VFX). Default: on.");
```

- [ ] **Step 7: Add the Python wrappers** in `engine/renderer.py`, right after `set_procedural_sky_enabled` (~line 170):

```python
def filmic_enabled() -> bool:
    """Read the Filmic Filter toggle (Modern VFX). Default: on."""
    return _h.filmic_enabled()


def set_filmic_enabled(enabled: bool) -> None:
    """Toggle the Filmic Filter (Modern VFX): film grain + vignette +
    chromatic aberration on the exterior view. Default: on."""
    _h.filmic_set_enabled(enabled)
```

- [ ] **Step 8: Full rebuild + smoke check**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` build cleanly with no errors.

Then verify the bindings exist:
Run: `python -c "import sys; sys.path.insert(0,'build/python'); import _open_stbc_host as h; print(hasattr(h,'filmic_set_enabled'), hasattr(h,'filmic_enabled'))"`
Expected: `True True`

- [ ] **Step 9: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(vfx): route FilmicPass last in the exterior post chain + bindings"
```

---

## Task 4: Configuration panel (Python) + tests

**Files:**
- Modify: `engine/ui/configuration_panel.py`
- Test: `tests/unit/test_configuration_panel.py`

**Interfaces:**
- Consumes: `engine.renderer.set_filmic_enabled` / `filmic_enabled` (Task 3), wired by host_loop (Task 6).
- Produces: `SettingsSnapshot.filmic_on`, ctor param `set_filmic`, dispatch action `toggle:filmic`, focus entry `("ctrl","filmic")`, payload key `filmic_on`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_configuration_panel.py`. Add `set_filmic=Mock()` to the `_make` helper's kwargs (next to `set_procedural_sky=Mock()`); update the exact-dict assertion in `test_initial_settings_round_trip_to_render_payload` to include `"filmic_on": True`; and append two new tests:

```python
def test_dispatch_toggle_filmic_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:filmic") is True
    kw["set_filmic"].assert_called_once_with(False)
    assert p.dispatch_event("toggle:filmic") is True
    kw["set_filmic"].assert_called_with(True)


def test_filmic_on_in_render_payload():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, fov_deg=70, shadows_on=True,
        procedural_sky_on=True, filmic_on=False,
    ))
    p.open()
    payload = p.render_payload()
    body = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert body["settings"]["filmic_on"] is False
```

Also update the round-trip dict in `test_initial_settings_round_trip_to_render_payload` to:

```python
    assert body["settings"] == {
        "dust_on": False, "specular_on": True, "hdr_on": True, "rim_on": False,
        "decals_on": False, "smaa_on": True,
        "subtitles_on": True, "shadows_on": True, "procedural_sky_on": True,
        "filmic_on": True, "fov_deg": 62,
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/unit/test_configuration_panel.py -q`
Expected: FAIL — `_make` passes unexpected `set_filmic`, missing `filmic_on`, etc.

- [ ] **Step 3: Implement the panel changes** in `engine/ui/configuration_panel.py` (mirror every `procedural_sky` site):

  a. In `SettingsSnapshot` add (after `procedural_sky_on`):
```python
    filmic_on: bool = True
```
  b. Add ctor param after `set_procedural_sky`:
```python
                 set_filmic: Callable[[bool], None]):
```
  (insert before the existing closing `):` — i.e. make `set_procedural_sky` take a trailing comma and add the new param on the next line.)

  c. In the settings copy inside `__init__` (after `procedural_sky_on=...`):
```python
            filmic_on=initial_settings.filmic_on,
```
  d. Store the applier (after `self._set_procedural_sky = set_procedural_sky`):
```python
        self._set_filmic = set_filmic
```
  e. In the snapshot tuple in `_maybe_push` (after `self._settings.procedural_sky_on,`):
```python
            self._settings.filmic_on,
```
  f. In the payload dict (after `"procedural_sky_on": ...,`):
```python
                "filmic_on": self._settings.filmic_on,
```
  g. In `dispatch_event`, after the `toggle:procedural_sky` block:
```python
        if action == "toggle:filmic":
            new_val = not self._settings.filmic_on
            self._set_filmic(new_val)
            self._settings.filmic_on = new_val
            return True
```
  h. In the activate handler, after the `procedural_sky` elif:
```python
        elif activate and kind == "ctrl" and target == "filmic":
            self.dispatch_event("toggle:filmic")
```
  i. In the graphics focus list, append `filmic` as the final entry:
```python
            out += [("ctrl", "dust"), ("ctrl", "specular"),
                    ("ctrl", "procedural_sky"), ("ctrl", "fov"),
                    ("ctrl", "hdr"), ("ctrl", "rim"), ("ctrl", "shadows"),
                    ("ctrl", "decals"), ("ctrl", "smaa"), ("ctrl", "filmic")]
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/unit/test_configuration_panel.py -q`
Expected: PASS (all, including the new two).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/configuration_panel.py tests/unit/test_configuration_panel.py
git commit -m "feat(vfx): add Filmic Filter row to the configuration panel"
```

---

## Task 5: CEF graphics row (JS)

**Files:**
- Modify: `native/assets/ui-cef/js/configuration_panel.js`

**Interfaces:**
- Consumes: payload key `filmic_on` (Task 4); dispatches `configuration/toggle:filmic`.

- [ ] **Step 1: Add to the focusable list** in `_cpFocusableList`, after the `smaa` push (so the JS list order matches the Python focus list, which ends with `filmic`):

```javascript
        out.push({kind: 'ctrl', target: 'smaa'});
        out.push({kind: 'ctrl', target: 'filmic'});
```
(If `smaa` is already pushed, just add the `filmic` line directly after it.)

- [ ] **Step 2: Render the row** in `_cpRenderGraphicsBody`, after the last existing Modern VFX row (mirror the Procedural Sky row exactly):

```javascript
    // Filmic Filter toggle — grain + vignette + chromatic aberration on the
    // exterior view (Modern VFX).
    html += '<div class="cp-row' + (isFoc('filmic') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Filmic Filter</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.filmic_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:filmic\')">'
          +       (s.filmic_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';
```

- [ ] **Step 3: Commit** (no automated test — CEF JS is verified visually in Task 7)

```bash
git add native/assets/ui-cef/js/configuration_panel.js
git commit -m "feat(vfx): add Filmic Filter row to the CEF configuration UI"
```

---

## Task 6: host_loop wiring

**Files:**
- Modify: `engine/host_loop.py` (SettingsSnapshot construction ~line 3213; ConfigurationPanel applier kwargs ~line 3228)

**Interfaces:**
- Consumes: `engine.renderer.filmic_enabled` / `set_filmic_enabled` (Task 3); `ConfigurationPanel(set_filmic=...)` + `SettingsSnapshot(filmic_on=...)` (Task 4).

- [ ] **Step 1: Pass the initial snapshot value.** In the `SettingsSnapshot(...)` construction, after `procedural_sky_on=r.procedural_sky_enabled(),`:

```python
                filmic_on=r.filmic_enabled(),
```

- [ ] **Step 2: Wire the applier.** In the `ConfigurationPanel(...)` kwargs, after `set_procedural_sky=r.set_procedural_sky_enabled,`:

```python
            set_filmic=r.set_filmic_enabled,
```

- [ ] **Step 3: Run the affected suite** (host_loop import + panel construction must still hold together)

Run: `python -m pytest tests/unit/test_configuration_panel.py -q && python -c "import engine.host_loop"`
Expected: PASS; import succeeds with no error.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(vfx): wire Filmic Filter toggle into host_loop config panel"
```

---

## Task 7: Full build + live verification

**Files:** none (verification only)

- [ ] **Step 1: Clean reconfigure + full build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build of `build/dauntless` + the module.

- [ ] **Step 2: Run the C++ renderer tests**

Run: `ctest --test-dir build -R "FilmicPassTest|DauntlessFilmicToggle" --output-on-failure`
Expected: all PASS (or SKIP only if the runner has no GL context).

- [ ] **Step 3: Run the Python suite (capped runner)**

Run: `scripts/run_tests.sh tests/unit/test_configuration_panel.py`
Expected: PASS.

- [ ] **Step 4: Live GUI check (manual — ask Mark to drive; do NOT synthetic-click or screen-capture his live workstation).**

Confirm in a running `./build/dauntless` exterior view:
  1. Default look has subtle grain + corner vignette + faint edge color fringing.
  2. Configuration → Graphics → "Filmic Filter" row toggles On/Off; Off returns the clean render.
  3. Entering the bridge / viewscreen / Ship Property Viewer shows NO grain/vignette/CA regardless of the toggle.
  4. Toggling SMAA on/off with Filmic on still renders correctly (no black frame, no double-darkening).

- [ ] **Step 5: Final branch wrap-up** — once Mark confirms the live check, use the `superpowers:finishing-a-development-branch` skill to decide merge/PR.

---

## Self-Review Notes

- **Spec coverage:** single toggle (Tasks 4–6), default on (Task 1 namespace + Task 6 snapshot), exterior-only gating (Task 3 `filmic_on` guard), three effects (Task 2 shader), dedicated final pass after SMAA (Task 3 routing), byte-identical non-exterior/off path (Task 3 `aa_on || filmic_on` branch leaves the existing path untouched when both false), motion blur excluded (not present). All covered.
- **Type consistency:** `FilmicPass::draw(src_tex, dest_fbo, fw, fh, time_seconds)` is defined in Task 2 and called with that exact arity in Task 3. `set_filmic` / `filmic_on` / `toggle:filmic` / `filmic_enabled` / `set_filmic_enabled` are spelled identically across Tasks 3–6.
- **Placeholder scan:** every code step contains complete code; no TBD/TODO.
