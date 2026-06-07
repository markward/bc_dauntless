# HDR Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the exterior + interior scene into a single HDR (`RGBA16F`) offscreen target and resolve it to the backbuffer through a tonemap + bloom + grade pass, gated by a runtime `HDR` toggle (default On) in the existing "Modern VFX" config group. No new art assets.

**Architecture:** Today every 3D pass draws straight to the default framebuffer (FBO 0), then CEF composites the UI, then `swap_buffers` (`native/src/host/host_bindings.cc:frame()`). This plan inserts one offscreen `RGBA16F` color + depth target: all 3D passes (backdrop → bridge) render into it, a fullscreen-triangle **resolve pass** writes it to FBO 0, and the existing CEF composite then runs on the resolved LDR backbuffer (so UI stays untonemapped). **Single render path**: HDR Off uses a neutral clamp-passthrough resolve (so "stock look" is preserved, pinned by a readback test); HDR On runs bloom + ACES tonemap + grade in the resolve. This is plan 2 of 2 for "Modern VFX" (plan 1, Fresnel rim, is merged).

**Tech Stack:** C++17 / OpenGL 3.3 (GLSL 330), pybind11 host bindings, Python host loop + CEF config UI, GoogleTest + pytest.

**Branch:** Feature branch in the main checkout — **no git worktree** (`sdk/`+`game/` are gitignored, live only here). `git checkout -b feat/hdr-pipeline`.

**Design decisions (locked with the user):**
- HDR On = **FBO + tonemap + bloom + grade** (full pipeline).
- HDR Off = **neutral resolve** (single path; clamp-passthrough, not a separate bypass). Stock-look guarantee = passthrough is an identity within ±1 LSB (16F intermediate), pinned by a GL readback test.
- Tonemap operator: **ACES filmic** (Narkowicz fit). Exposure fixed at 1.0 (no auto-exposure).
- Bloom: **dual-filter** (downsample/upsample mip chain) — efficient and soft; threshold bright-pass.
- Grade: **post-tonemap exposure + saturation** (subjective — expect visual tuning iterations like the rim's RIM_POWER/RIM_GAIN).
- Toggle plumbing **mirrors the merged `dauntless_rim` / `rim_set_enabled` / ConfigurationPanel rim toggle** exactly (see commits on the merged rim work as the reference pattern).

**Build/test reminders:**
- Full build: `cmake -B build -S . && cmake --build build -j`. **Shader edits need a reconfigure first** (`cmake -B build -S .`) — the embed is a configure-time step.
- `cmake --build build -j <target>` is misparsed (`-j` eats the target); use `cmake --build build --target <target> -j`.
- **Never** run the full pytest suite (OOMs the host) — target specific files.
- Single binary at `build/dauntless`; never create alternate build trees.
- GL tests run headless via `GALLIUM_DRIVER=llvmpipe` (see `native/tests/renderer/CMakeLists.txt`); they SKIP without a GL context.

**Reference patterns to read before starting:**
- `native/src/ui_cef/cef_composite_pass.cc` — the fullscreen-triangle VS/FS + VBO + `glDrawArrays(GL_TRIANGLES,0,3)` + GL-state-restore pattern the resolve/bloom passes mirror. **There is no existing FBO in `native/src` — this is the first.**
- `native/src/host/host_bindings.cc:225-319` — `frame()` composition + the `dauntless_rim`/`dauntless_specular` toggle forward-decls + bindings.
- `native/src/renderer/frame.cc` — `dauntless_specular` / `dauntless_rim` global-toggle namespace pattern.
- `engine/ui/configuration_panel.py` + `native/assets/ui-cef/js/configuration_panel.js` — the rim toggle wiring to copy for the HDR row.

---

### Task 1: `HdrTarget` — RGBA16F color + depth offscreen FBO

**Files:**
- Create: `native/src/renderer/include/renderer/hdr_target.h`
- Create: `native/src/renderer/hdr_target.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `hdr_target.cc` to the renderer lib sources)
- Modify: `native/tests/renderer/CMakeLists.txt` (add `hdr_target_test.cc`)
- Test: `native/tests/renderer/hdr_target_test.cc`

**Responsibility:** own one FBO with an `RGBA16F` color texture + a depth renderbuffer, sized to the framebuffer; recreate on resize; expose `bind()` (make it the draw target + set viewport), `color_texture()`, `width()/height()`.

- [ ] **Step 1: Write the failing test**

`native/tests/renderer/hdr_target_test.cc` (mirror the GL-fixture skip pattern from `native/tests/renderer/frame_test.cc` SetUp — create a `renderer::Window(64,64,"hdr-test",false)` in a fixture, GTEST_SKIP on no-GL):

```cpp
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/hdr_target.h>
#include <renderer/window.h>
#include <memory>

namespace {
class HdrTargetTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64, 64, "hdr-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

TEST_F(HdrTargetTest, CreatesCompleteFramebuffer) {
    renderer::HdrTarget t;
    t.resize(128, 96);
    EXPECT_EQ(t.width(), 128);
    EXPECT_EQ(t.height(), 96);
    EXPECT_NE(t.color_texture(), 0u);
    t.bind();
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(HdrTargetTest, ResizeReallocatesAndStaysComplete) {
    renderer::HdrTarget t;
    t.resize(100, 100);
    GLuint first = t.color_texture();
    t.resize(100, 100);                 // same size: no-op, keep texture
    EXPECT_EQ(t.color_texture(), first);
    t.resize(200, 150);                 // new size: reallocate
    t.bind();
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);
    EXPECT_EQ(t.width(), 200);
    EXPECT_EQ(t.height(), 150);
}
}  // namespace
```

- [ ] **Step 2: Run to verify it fails (or skips without GL)**

`cmake -B build -S . && cmake --build build --target renderer_tests -j && ctest --test-dir build -R "HdrTarget" -V`
Expected: compile error (`hdr_target.h` missing) — after adding to CMake in step 3.

- [ ] **Step 3: Implement the header**

`native/src/renderer/include/renderer/hdr_target.h`:

```cpp
// native/src/renderer/include/renderer/hdr_target.h
#pragma once
#include <cstdint>

namespace renderer {

/// One offscreen RGBA16F color + depth target. The whole 3D scene renders
/// here; the resolve pass reads color_texture() back to the backbuffer.
/// First FBO in the renderer — see cef_composite_pass.cc for the
/// fullscreen-triangle resolve pattern that consumes this.
class HdrTarget {
public:
    HdrTarget() = default;
    ~HdrTarget();
    HdrTarget(const HdrTarget&) = delete;
    HdrTarget& operator=(const HdrTarget&) = delete;

    /// (Re)allocate to w x h. No-op if already that size. Must be called
    /// with a current GL context before bind().
    void resize(int w, int h);

    /// Make this the draw framebuffer and set the viewport to its size.
    void bind() const;

    std::uint32_t color_texture() const { return color_tex_; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t color_tex_ = 0;
    std::uint32_t depth_rbo_ = 0;
    int width_ = 0;
    int height_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 4: Implement the source**

`native/src/renderer/hdr_target.cc`:

```cpp
// native/src/renderer/hdr_target.cc
#include "renderer/hdr_target.h"
#include <glad/glad.h>

namespace renderer {

HdrTarget::~HdrTarget() { destroy(); }

void HdrTarget::destroy() {
    if (color_tex_) { glDeleteTextures(1, &color_tex_); color_tex_ = 0; }
    if (depth_rbo_) { glDeleteRenderbuffers(1, &depth_rbo_); depth_rbo_ = 0; }
    if (fbo_)       { glDeleteFramebuffers(1, &fbo_); fbo_ = 0; }
}

void HdrTarget::resize(int w, int h) {
    if (w < 1) w = 1;
    if (h < 1) h = 1;
    if (w == width_ && h == height_ && fbo_ != 0) return;
    destroy();
    width_ = w; height_ = h;

    glGenTextures(1, &color_tex_);
    glBindTexture(GL_TEXTURE_2D, color_tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    glGenRenderbuffers(1, &depth_rbo_);
    glBindRenderbuffer(GL_RENDERBUFFER, depth_rbo_);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, w, h);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, color_tex_, 0);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                              GL_RENDERBUFFER, depth_rbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void HdrTarget::bind() const {
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
}

}  // namespace renderer
```

- [ ] **Step 5: Wire CMake**

In `native/src/renderer/CMakeLists.txt`, add `hdr_target.cc` to the renderer library's source list (next to `frame.cc`). In `native/tests/renderer/CMakeLists.txt`, add `hdr_target_test.cc` to the `renderer_tests` executable source list.

- [ ] **Step 6: Run to verify it passes**

`cmake -B build -S . && cmake --build build --target renderer_tests -j && ctest --test-dir build -R "HdrTarget" -V`
Expected: 2 tests PASS (or SKIP without GL).

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/hdr_target.h native/src/renderer/hdr_target.cc native/src/renderer/CMakeLists.txt native/tests/renderer/CMakeLists.txt native/tests/renderer/hdr_target_test.cc
git commit -m "feat(renderer): HdrTarget RGBA16F offscreen FBO

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Resolve pass (passthrough) + route the frame through the HDR target

**Files:**
- Create: `native/src/renderer/include/renderer/resolve_pass.h`, `native/src/renderer/resolve_pass.cc`
- Create: `native/src/renderer/shaders/resolve.vert`, `native/src/renderer/shaders/resolve.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (source + 2 `embed_shader` calls), `native/src/renderer/pipeline.cc`/`.h` if shaders are owned there (else ResolvePass owns its own program like CefCompositePass)
- Modify: `native/src/host/host_bindings.cc` (`init`, `frame`, `shutdown` to own + drive an `HdrTarget` + `ResolvePass`)
- Test: `native/tests/renderer/resolve_pass_test.cc`

**Responsibility:** a fullscreen-triangle pass that samples the HDR color texture and writes to the currently-bound framebuffer (FBO 0). This task implements ONLY the neutral passthrough (`clamp(color,0,1)`) — tonemap/bloom/grade come later behind the toggle. After this task the scene renders through the HDR buffer with HDR effectively "off", and must look like stock.

ResolvePass owns its own GL program + VAO/VBO, mirroring `CefCompositePass` (read it first). Do NOT route through the `Pipeline` shader registry unless that's cleaner — self-contained is consistent with CefCompositePass.

- [ ] **Step 1: Write the failing test**

`native/tests/renderer/resolve_pass_test.cc` — render a known color into an `HdrTarget`, resolve to a second tiny FBO (or the default), read back center pixel, assert it matches within tolerance (proves passthrough identity):

```cpp
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/hdr_target.h>
#include <renderer/resolve_pass.h>
#include <renderer/window.h>
#include <memory>

namespace {
class ResolvePassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64,64,"resolve-test",false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

TEST_F(ResolvePassTest, PassthroughPreservesColorWithinTolerance) {
    renderer::HdrTarget hdr;
    hdr.resize(32, 32);
    hdr.bind();
    glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // Resolve to the default framebuffer (the window's backbuffer).
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::ResolvePass resolve;
    resolve.set_hdr_enabled(false);              // neutral passthrough
    resolve.draw(hdr.color_texture());

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_NEAR(px[0], 64,  2);   // 0.25*255
    EXPECT_NEAR(px[1], 128, 2);   // 0.5*255
    EXPECT_NEAR(px[2], 191, 2);   // 0.75*255
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
}  // namespace
```

- [ ] **Step 2: Run to verify it fails**

`cmake -B build -S . && cmake --build build --target renderer_tests -j && ctest --test-dir build -R "ResolvePass" -V`
Expected: compile error (`resolve_pass.h` missing).

- [ ] **Step 3: Write the resolve shaders**

`native/src/renderer/shaders/resolve.vert`:
```glsl
#version 330 core
layout(location=0) in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = (a_pos + 1.0) * 0.5;   // GL bottom-up; HDR texture is bottom-up too
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
```

`native/src/renderer/shaders/resolve.frag` (this task: passthrough only; tonemap/bloom/grade added in Tasks 4–6):
```glsl
#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_hdr;
uniform int u_hdr_enabled;          // 0 = neutral clamp passthrough
void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    // HDR off: identity clamp (stock look). HDR on path filled in later.
    frag_color = vec4(clamp(c, 0.0, 1.0), 1.0);
}
```

- [ ] **Step 4: Implement ResolvePass**

`native/src/renderer/include/renderer/resolve_pass.h`:
```cpp
#pragma once
#include <cstdint>
namespace renderer {
class ResolvePass {
public:
    ResolvePass();
    ~ResolvePass();
    ResolvePass(const ResolvePass&) = delete;
    ResolvePass& operator=(const ResolvePass&) = delete;
    void set_hdr_enabled(bool e) { hdr_enabled_ = e; }
    /// Draw a fullscreen triangle sampling `hdr_color_tex` into the
    /// currently-bound framebuffer. Restores prior GL state it changes.
    void draw(std::uint32_t hdr_color_tex);
private:
    std::uint32_t program_ = 0;
    std::uint32_t vao_ = 0, vbo_ = 0;
    bool hdr_enabled_ = true;
};
}  // namespace renderer
```

`native/src/renderer/resolve_pass.cc` — mirror `CefCompositePass`: compile the embedded `resolve_vs`/`resolve_fs`, build a VBO with a single fullscreen triangle `{-1,-1, 3,-1, -1,3}`, and in `draw()` disable depth test + blend, bind the program, set `u_hdr=0` + `u_hdr_enabled`, bind `hdr_color_tex` to unit 0, `glDrawArrays(GL_TRIANGLES,0,3)`, then restore depth-test enable. Use the `embedded_resolve_vs.h`/`embedded_resolve_fs.h` headers produced by `embed_shader` (add those two calls to `native/src/renderer/CMakeLists.txt` and the includes to pipeline.cc or resolve_pass.cc).

- [ ] **Step 5: Wire CMake** — add `resolve_pass.cc` to the renderer lib, `embed_shader(... shaders/resolve.vert resolve_vs)` + `embed_shader(... shaders/resolve.frag resolve_fs)`, and `resolve_pass_test.cc` to `renderer_tests`.

- [ ] **Step 6: Route `frame()` through the HDR target**

In `native/src/host/host_bindings.cc`: add `std::unique_ptr<renderer::HdrTarget> g_hdr_target;` and `std::unique_ptr<renderer::ResolvePass> g_resolve_pass;` globals; construct in `init()`, reset in `shutdown()` (before `g_window`/`g_pipeline` teardown, matching the existing ordering comment). In `frame()`, replace the opening clear/viewport block so that:
  1. `g_hdr_target->resize(fw, fh); g_hdr_target->bind();` then the existing `glClearColor(0.05,0.07,0.10,1)` + clear — now into the HDR FBO.
  2. All 3D passes (backdrop → bridge, lines 243–288) render unchanged (they inherit the bound HDR FBO).
  3. After the bridge block, before `poll_events`: resolve to the backbuffer —
     ```cpp
     glBindFramebuffer(GL_FRAMEBUFFER, 0);
     glViewport(0, 0, fw, fh);
     g_resolve_pass->set_hdr_enabled(dauntless_hdr::enabled());  // Task 3 adds the toggle; for THIS task hardcode false
     g_resolve_pass->draw(g_hdr_target->color_texture());
     ```
     For Task 2 (no toggle yet), call `g_resolve_pass->set_hdr_enabled(false);` literally.
  4. The existing CEF `pump()`/`composite()` + `swap_buffers()` stay where they are (after resolve → they composite onto the resolved backbuffer). ✔

- [ ] **Step 7: Build, test, and a manual smoke run**

`cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "ResolvePass|HdrTarget|FrameTest" -V`
Expected: PASS/SKIP, no GL errors. Then `./build/dauntless` — the scene must look **identical to stock** (passthrough). If colors shifted or the image is flipped, fix the resolve UV orientation (the HDR texture and CEF bitmap have opposite V conventions — resolve.vert must NOT flip V, unlike the CEF shader which does).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/resolve_pass.h native/src/renderer/resolve_pass.cc native/src/renderer/shaders/resolve.vert native/src/renderer/shaders/resolve.frag native/src/renderer/CMakeLists.txt native/tests/renderer/CMakeLists.txt native/tests/renderer/resolve_pass_test.cc native/src/host/host_bindings.cc
git commit -m "feat(renderer): route frame through HDR target + passthrough resolve

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `HDR` runtime toggle — full plumbing (mirror the rim toggle)

**Files:** `native/src/renderer/frame.cc` (or a small `dauntless_hdr` TU), `native/src/host/host_bindings.cc`, `engine/renderer.py`, `engine/ui/configuration_panel.py`, `engine/host_loop.py`, `native/assets/ui-cef/js/configuration_panel.js`, tests `tests/unit/test_renderer_rim.py`-style + `tests/unit/test_configuration_panel.py`.

This is the **exact same shape as the merged Fresnel-rim toggle** — replicate it for `hdr`:
- C++ global `namespace dauntless_hdr { bool enabled(); void set_enabled(bool); }` (default `true`), defined alongside `dauntless_rim` in `frame.cc`; forward-declared in `host_bindings.cc`.
- Host binding `m.def("hdr_set_enabled", [](bool e){ dauntless_hdr::set_enabled(e); }, py::arg("enabled"), "...")` next to `rim_set_enabled`. (No per-instance flag this time — HDR is global only.)
- `engine/renderer.py`: `set_hdr_enabled(enabled: bool)` forwarding to `_h.hdr_set_enabled`. Test in `tests/unit/test_renderer_rim.py` (or a new `test_renderer_hdr.py`) mirroring `test_set_rim_enabled_forwards`.
- `engine/ui/configuration_panel.py`: add `hdr_on: bool` to `SettingsSnapshot`, `set_hdr` applier param, `toggle:hdr` dispatch, `("ctrl","hdr")` focusable, `handle_input` branch, and `hdr_on` in `render_payload` (tuple + dict). Place `hdr` FIRST in the Modern VFX group (before `rim`) — focusable order: `dust, specular, fov, hdr, rim`. Add tests mirroring the rim tests.
- `engine/host_loop.py`: add `hdr_on=True` to the panel's `SettingsSnapshot` and `set_hdr=r.set_hdr_enabled` to the appliers.
- `native/assets/ui-cef/js/configuration_panel.js`: in `_cpFocusableList` push `hdr` before `rim`; in `_cpRenderGraphicsBody`, under the existing `<div class="cp-group-header">Modern VFX</div>`, add an "HDR" toggle row BEFORE the Fresnel Rim row, mirroring the rim row markup (`s.hdr_on`, `toggle:hdr`).
- In `host_bindings.cc::frame()`, change the resolve call from the hardcoded `false` to `g_resolve_pass->set_hdr_enabled(dauntless_hdr::enabled());`.

Follow strict TDD on the Python layers (focused pytest only). C++ toggle has no unit test (covered by the rim pattern + visual). Use the same per-step structure as the rim plan (write failing test → run → implement → run → commit). **Commit** with message `feat: HDR runtime toggle in Modern VFX group`.

> NOTE (same commit-ordering caveat as rim): `SettingsSnapshot`/`ConfigurationPanel` gain required fields — update `engine/host_loop.py` in the same change so the panel construction stays valid.

After this task: toggling HDR Off at runtime → passthrough (stock); On → still passthrough (tonemap/bloom/grade land next), so no visible change yet except the resolve path is now toggle-driven.

---

### Task 4: ACES filmic tonemap (HDR On path)

**Files:** `native/src/renderer/shaders/resolve.frag`, `native/tests/renderer/resolve_pass_test.cc`.

- [ ] **Step 1: Add a failing test** — a known mid-bright HDR input (e.g. clear color `1.5, 1.5, 1.5` — above 1.0, only representable in the 16F target) resolved with `hdr_enabled=true` must come back **below** 255 on all channels (tonemap compresses highlights), whereas passthrough would clamp to 255. Assert `px[0] < 250` with hdr on, and (sanity) `== 255` with hdr off for the same input.

```cpp
TEST_F(ResolvePassTest, TonemapCompressesHighlights) {
    renderer::HdrTarget hdr; hdr.resize(16,16); hdr.bind();
    glClearColor(1.5f, 1.5f, 1.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0); glViewport(0,0,64,64);
    renderer::ResolvePass r;
    r.set_hdr_enabled(true);
    r.draw(hdr.color_texture());
    unsigned char on[4]; glReadPixels(32,32,1,1,GL_RGBA,GL_UNSIGNED_BYTE,on);
    EXPECT_LT(on[0], 250);   // ACES rolls the >1.0 highlight off below white
    EXPECT_GT(on[0], 150);   // but it's still bright
}
```

- [ ] **Step 2: Run → fails** (passthrough clamps 1.5→255).

- [ ] **Step 3: Implement** — in `resolve.frag`, add the ACES Narkowicz fit and branch on `u_hdr_enabled`:

```glsl
vec3 aces(vec3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}
void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    if (u_hdr_enabled != 0) {
        c = aces(c);                 // bloom (Task 5) added before this; grade (Task 6) after
    } else {
        c = clamp(c, 0.0, 1.0);
    }
    frag_color = vec4(c, 1.0);
}
```

- [ ] **Step 4: Run → passes.** Then `./build/dauntless` (reconfigure first): HDR On now gives a gentle filmic look; the sun/glows/rim highlights roll off instead of hard-clipping. HDR Off unchanged.

- [ ] **Step 5: Commit** `feat(renderer): ACES filmic tonemap in HDR resolve`.

---

### Task 5: Bloom (bright-pass + dual-filter down/up)

**Files:** Create `native/src/renderer/include/renderer/bloom_pass.h`, `native/src/renderer/bloom_pass.cc`, `native/src/renderer/shaders/bloom_down.frag`, `bloom_up.frag`, `bloom_prefilter.frag` (+ reuse `resolve.vert` for fullscreen). Modify `resolve.frag` to add the bloom texture, `host_bindings.cc::frame()` to run bloom before resolve when HDR on, CMake.

**Responsibility:** given the HDR color texture, produce a bloom texture: prefilter (threshold bright pixels) → N downsample steps (13-tap or simple box) → N upsample steps with additive accumulation (dual-filter). Mip chain held in a small set of `RGBA16F` FBOs owned by `BloomPass`, resized with the framebuffer (e.g. 6 mips or down to ~ /64).

- [ ] **Step 1: Failing test** — `BloomPass` GL test: feed a target with a single bright texel region (value 4.0) on a black background, run bloom, read back a neighbouring (previously black) texel and assert it's now > 0 (energy spread). And a fully-black input yields ~0 bloom.

- [ ] **Step 2: Run → fails** (no bloom_pass.h).

- [ ] **Step 3: Implement** `BloomPass` mirroring CefCompositePass program/VAO setup, with the dual-filter chain. Prefilter shader keeps `max(c - threshold, 0)` (threshold uniform, default ~1.0). Down/up shaders are standard dual-Kawase taps sampling the previous mip with `u_texel_size`. Provide complete GLSL for each (down = 4-tap box at 0.5 offsets; up = 9-tap tent; or the Call-of-Duty 13-tap/tent pair — pick one and write it fully). Expose `BloomPass::render(hdr_color_tex, fw, fh) -> bloom_texture()`.

- [ ] **Step 4: Composite into resolve** — `resolve.frag` gains `uniform sampler2D u_bloom; uniform float u_bloom_strength;` and, in the HDR-on branch, `c += u_bloom_strength * texture(u_bloom, v_uv).rgb;` **before** `aces(c)`. In `frame()`, when `dauntless_hdr::enabled()`, call `g_bloom_pass->render(...)` after the 3D passes and bind its result for the resolve; bind a 1x1 black texture when off (or skip — resolve reads `u_bloom` only in the on branch, so binding any valid texture is fine).

- [ ] **Step 5: Run tests + visual.** Reconfigure, build, `ctest -R "Bloom|ResolvePass"`, then `./build/dauntless`: nacelles, sun, phasers, and the Fresnel rim's hot edge should now bleed a soft glow. Expect to tune `u_bloom_strength` + threshold by eye (like the rim) — start strength ~0.04, threshold ~1.0.

- [ ] **Step 6: Commit** `feat(renderer): bloom (dual-filter) in HDR pipeline`.

---

### Task 6: Color grade (exposure + saturation) — subjective tune

**Files:** `native/src/renderer/shaders/resolve.frag`.

- [ ] **Step 1:** Add `const float EXPOSURE` and a saturation step in the HDR-on branch, applied **after** ACES (operate on the tonemapped LDR): `c *= EXPONENT? no — exposure multiplies the HDR value BEFORE aces; saturation after`. Concretely: before `aces`, `c *= EXPOSURE;` (default 1.0); after `aces`, `c = mix(vec3(dot(c, vec3(0.2126,0.7152,0.0722))), c, SATURATION);` (default ~1.05 for a slightly cooler/punchier Trek look). Keep both as named `const float` like the rim's RIM_POWER/RIM_GAIN so they're eye-tunable.
- [ ] **Step 2:** Reconfigure + build + `./build/dauntless`. **Tune EXPOSURE + SATURATION interactively with the user** (rebuild loop, same as rim). There is no automated test for grade aesthetics; the existing tonemap/bloom tests still pass.
- [ ] **Step 3:** Commit `feat(renderer): exposure + saturation grade in HDR resolve` with the locked values.

---

### Task 7: Full build, tests, visual verification + resize check

**Files:** none (verification).

- [ ] **Step 1:** `cmake -B build -S . && cmake --build build -j` — clean.
- [ ] **Step 2:** `ctest --test-dir build -R "HdrTarget|ResolvePass|Bloom|FrameTest|World|Lighting"` and `uv run pytest tests/unit/test_configuration_panel.py tests/unit/test_renderer_rim.py tests/unit/test_renderer_hdr.py` — all pass.
- [ ] **Step 3:** `./build/dauntless`:
  - HDR **On**: filmic highlights, visible bloom, rim edges bleed; Modern VFX group shows **HDR** + **Fresnel Rim Light** rows.
  - HDR **Off**: scene returns to stock look (passthrough). Toggle both ways live.
  - **Resize the window**: no GL errors, no stale/stretched HDR image (confirms `HdrTarget`/`BloomPass` resize paths).
  - Enter the **bridge** view: interior renders through HDR too (no seam, viewscreen consistent).
- [ ] **Step 4:** Any grade/bloom tuning tweaks → commit.

---

## Self-Review

**Spec coverage:** FBO+tonemap+bloom+grade (Tasks 1,4,5,6) ✓; single-path neutral-resolve off with readback identity test (Task 2) ✓; HDR toggle in Modern VFX, default on, mirroring rim (Task 3) ✓; interior+exterior both through the one buffer (Task 2 routes all passes incl. bridge; verified Task 7) ✓; CEF UI stays LDR (composite runs after resolve — Task 2 step 6) ✓; resize handled (Task 1 + Task 7 step 3) ✓.

**Known subjective/iterative bits (flagged, not gaps):** bloom strength/threshold (Task 5) and exposure/saturation (Task 6) need visual tuning with the user, exactly like the rim's RIM_POWER/RIM_GAIN — these are `const float`s in shaders for fast iteration, not config knobs.

**Risk notes for the implementer:** (1) UV V-orientation — the HDR texture is bottom-up; resolve.vert must NOT flip V (unlike cef_composite which flips for CEF's top-down bitmap). (2) Depth: the HDR target carries a depth renderbuffer so all depth-tested passes work unchanged. (3) The bridge pass does its own color+depth clear *inside* the HDR FBO — fine. (4) When HDR is off, the scene STILL goes through the FBO+passthrough (single path) — the readback test (Task 2) is the guardrail that this stays stock-identical within ±1 LSB.

**Out of scope (future):** auto-exposure, MSAA on the HDR target, FXAA, per-config bloom/exposure sliders, the planet-atmosphere Fresnel follow-up.
