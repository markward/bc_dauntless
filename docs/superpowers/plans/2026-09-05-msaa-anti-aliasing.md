# MSAA Anti-Aliasing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the opaque space pass true multisample anti-aliasing, exposed to the player as a single mutually-exclusive "Anti-aliasing" selector (Off / SMAA / 2× / 4× / 8×) replacing the current SMAA toggle.

**Architecture:** A separate `HdrMsaaTarget` (multisample renderbuffers) receives backdrop → suns → opaque → breach → shield, then one `glBlitFramebuffer` resolves colour *and* depth into the existing `HdrTarget`. Everything downstream of that resolve — nebulae, beams, particles, godrays, cloak, and the whole post chain — runs unchanged on the single-sample target it already expects. When MSAA is off, no multisample buffer is allocated and no blit occurs.

**Tech Stack:** C++17, OpenGL 4.1 core (glad loader at 3.3), pybind11, GoogleTest/ctest, Python 3, pytest, CEF-hosted HTML/JS UI.

**Spec:** `docs/superpowers/specs/2026-09-05-msaa-anti-aliasing-design.md`

## Global Constraints

- **The MSAA-off path must be byte-identical to today.** Not equivalent — identical. This is the convention already used for shadows, specular and normal maps. A lazily-allocated MSAA buffer means an Off/SMAA session never creates it and never blits.
- **Build from the repo root only:** `cmake -B build -S . && cmake --build build -j`. Never run `cmake` inside `native/`. The binary is `build/dauntless`; the extension module is `build/python/_dauntless_host.cpython-*.so`.
- **Never change `CMAKE_BUILD_TYPE` in an existing `build/`.** Left to itself cmake picks `RelWithDebInfo` here while the main checkout is `Debug`; reconfiguring in place keeps `_deps` at the old type and yields a `_dauntless_host.so` that **segfaults** in the audio tests while ctest stays green and `otool -L` looks identical. This tree is already configured `Debug`. If you must change it, `rm -rf build` and configure from scratch with `-DCMAKE_BUILD_TYPE=Debug`.
- **`host_bindings.cc` edits require rebuilding the `dauntless` target**, not just the library, and a reconfigure (`cmake -B build -S .`) before the build.
- **This work happens in a git worktree.** `VIRTUAL_ENV` is inherited from the main checkout and points at the wrong environment. Run pytest as `VIRTUAL_ENV="$PWD/.venv" ./.venv/bin/python -m pytest ...`, never bare `uv run pytest`, or you will test the main tree's environment against this tree's native module and get a SIGSEGV.
- **The test gate is `scripts/check_tests.sh`** — both suites, diffed against `tests/known_failures.txt`. Never call a failure "pre-existing" by eyeball. The script builds but does not configure; a tree without `build/` needs `cmake -B build -S .` first.
- **Shared checkout:** always `git add` with an explicit pathspec. Never `git add -A`, `git add .`, `git checkout --`, `git restore`, `git stash`, `git clean`, or `git reset --hard`.
- **Never launch the game**, even headless. Renderer verification goes through `renderer_tests`. Live visual checks are Mark's, in the main tree.
- **Sample counts are 2, 4 and 8**, clamped against `GL_MAX_SAMPLES`. 8× is retained deliberately — it is of real use on gaming rigs.
- **The default AA mode stays SMAA**, so the shipped baseline is unchanged and no player inherits a ~160 MB allocation without asking.
- **Rotation/matrix conventions and game units are untouched by this work.** Do not modify any lighting, camera or transform code.

---

### Task 1: `HdrMsaaTarget` and the max-sample-count capability

**Files:**
- Create: `native/src/renderer/include/renderer/hdr_msaa_target.h`
- Create: `native/src/renderer/hdr_msaa_target.cc`
- Modify: `native/src/renderer/include/renderer/gl_caps.h`
- Modify: `native/src/renderer/gl_caps.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Test: `native/tests/renderer/hdr_msaa_target_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `renderer::HdrMsaaTarget` with `void resize(int w, int h, int samples)`, `void bind() const`, `void resolve_to(const HdrTarget&) const`, `bool valid() const`, `std::uint32_t fbo() const`, `int width() const`, `int height() const`, `int samples() const`. Also `renderer::GlCaps::max_samples` (int) and `int renderer::clamp_msaa_samples(int requested, const GlCaps&)`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/hdr_msaa_target_test.cc`. It follows `hdr_target_test.cc` exactly — a 64×64 hidden `renderer::Window` in `SetUp`, skipping when no GL context is available.

```cpp
// native/tests/renderer/hdr_msaa_target_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/hdr_msaa_target.h>
#include <renderer/gl_caps.h>
#include <renderer/window.h>
#include <memory>

namespace {

class HdrMsaaTargetTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64, 64, "msaa-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

TEST_F(HdrMsaaTargetTest, CapsReportAtLeastFourSamples) {
    // Every GL 3.3+ implementation must support at least 4. If this fails the
    // context is not what we think it is.
    const renderer::GlCaps caps = renderer::query_gl_caps();
    EXPECT_GE(caps.max_samples, 4);
}

TEST_F(HdrMsaaTargetTest, ClampNeverExceedsCapsAndPassesZeroThrough) {
    renderer::GlCaps caps;
    caps.max_samples = 4;
    EXPECT_EQ(renderer::clamp_msaa_samples(0, caps), 0);   // 0 means "off"
    EXPECT_EQ(renderer::clamp_msaa_samples(2, caps), 2);
    EXPECT_EQ(renderer::clamp_msaa_samples(4, caps), 4);
    EXPECT_EQ(renderer::clamp_msaa_samples(8, caps), 4);   // clamped down
    EXPECT_EQ(renderer::clamp_msaa_samples(-3, caps), 0);  // nonsense is off
}

TEST_F(HdrMsaaTargetTest, CreatesCompleteFramebufferAtEachSampleCount) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    for (int s : {2, 4, 8}) {
        if (s > caps.max_samples) continue;
        renderer::HdrMsaaTarget t;
        t.resize(128, 96, s);
        EXPECT_TRUE(t.valid()) << "samples=" << s;
        EXPECT_EQ(t.width(), 128);
        EXPECT_EQ(t.height(), 96);
        EXPECT_EQ(t.samples(), s);
        t.bind();
        EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE)
            << "samples=" << s;
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "samples=" << s;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

TEST_F(HdrMsaaTargetTest, ResizeToSameParamsIsANoOp) {
    renderer::HdrMsaaTarget t;
    t.resize(100, 100, 4);
    const std::uint32_t first = t.fbo();
    t.resize(100, 100, 4);
    EXPECT_EQ(t.fbo(), first);
}

TEST_F(HdrMsaaTargetTest, ChangingSampleCountReallocates) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    if (caps.max_samples < 4) GTEST_SKIP() << "needs 4x";
    renderer::HdrMsaaTarget t;
    t.resize(100, 100, 2);
    const std::uint32_t first = t.fbo();
    t.resize(100, 100, 4);
    EXPECT_NE(t.fbo(), first);
    EXPECT_EQ(t.samples(), 4);
    t.bind();
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

TEST_F(HdrMsaaTargetTest, ZeroSamplesIsInvalidAndAllocatesNothing) {
    renderer::HdrMsaaTarget t;
    t.resize(128, 96, 0);
    EXPECT_FALSE(t.valid());
    EXPECT_EQ(t.fbo(), 0u);
}

}  // namespace
```

Register it by adding `hdr_msaa_target_test.cc` to the source list in `native/tests/renderer/CMakeLists.txt`, in alphabetical position immediately after `hdr_target_test.cc` (line 33).

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: **compile failure** — `renderer/hdr_msaa_target.h: No such file or directory`. That is the correct RED state for a new type.

- [ ] **Step 3: Add `max_samples` to GL caps**

Replace `native/src/renderer/include/renderer/gl_caps.h` with:

```cpp
#pragma once
namespace renderer {
/// Snapshot of GL capabilities. Query with a current GL context.
struct GlCaps {
    int  version_major = 0;
    int  version_minor = 0;
    bool tessellation_available = false;  // true iff context is >= GL 4.0
    /// GL_MAX_SAMPLES — the ceiling on multisample renderbuffer sample counts.
    /// GL 3.3 guarantees >= 4. Queried, not assumed: we clamp the UI to it.
    int  max_samples = 0;
};
GlCaps query_gl_caps();  // requires a current GL context

/// Clamp a requested MSAA sample count to something this driver will give us.
/// 0 (and anything nonsensical) means "MSAA off" and is passed through as 0,
/// because 0 is the signal the frame path uses to skip the whole MSAA branch.
int clamp_msaa_samples(int requested, const GlCaps& caps);
}  // namespace renderer
```

Replace `native/src/renderer/gl_caps.cc` with:

```cpp
// native/src/renderer/gl_caps.cc
#include "renderer/gl_caps.h"
#include <glad/glad.h>
namespace renderer {
GlCaps query_gl_caps() {
    GlCaps caps;
    glGetIntegerv(GL_MAJOR_VERSION, &caps.version_major);
    glGetIntegerv(GL_MINOR_VERSION, &caps.version_minor);
    caps.tessellation_available = (caps.version_major >= 4);
    glGetIntegerv(GL_MAX_SAMPLES, &caps.max_samples);
    return caps;
}

int clamp_msaa_samples(int requested, const GlCaps& caps) {
    if (requested < 2) return 0;
    return (requested > caps.max_samples) ? caps.max_samples : requested;
}
}  // namespace renderer
```

- [ ] **Step 4: Write the header**

Create `native/src/renderer/include/renderer/hdr_msaa_target.h`:

```cpp
// native/src/renderer/include/renderer/hdr_msaa_target.h
#pragma once
#include <cstdint>

namespace renderer {

class HdrTarget;

/// A multisample RGBA16F colour + depth target for the opaque space pass.
///
/// Both attachments are RENDERBUFFERS, not textures, and that is deliberate:
/// nothing ever samples these surfaces. The only way data leaves this target
/// is resolve_to(), a glBlitFramebuffer into a single-sample HdrTarget. Using
/// renderbuffers keeps sampler2DMS and per-sample fetch out of the codebase
/// entirely.
///
/// Allocation is lazy at the call site: resize() is only called when MSAA is
/// actually enabled, so an Off/SMAA session never creates GL objects here.
class HdrMsaaTarget {
public:
    HdrMsaaTarget() = default;
    ~HdrMsaaTarget();
    HdrMsaaTarget(const HdrMsaaTarget&) = delete;
    HdrMsaaTarget& operator=(const HdrMsaaTarget&) = delete;

    /// (Re)allocate to w x h at `samples`. No-op if already those exact
    /// parameters. `samples` < 2 destroys any existing buffers and leaves the
    /// target invalid(). Requires a current GL context.
    ///
    /// If the driver refuses the combination (framebuffer incomplete), the
    /// target is destroyed and left invalid() rather than half-built — the
    /// caller checks valid() and falls back to the non-MSAA path. We do not
    /// trust GL_RGBA16F multisample support on the strength of the spec alone.
    void resize(int w, int h, int samples);

    /// Make this the draw framebuffer and set the viewport to its size.
    /// CALLER CONTRACT: matches HdrTarget::bind() — the caller must restore
    /// the intended framebuffer and viewport afterwards.
    void bind() const;

    /// Resolve colour AND depth into `dst` with a single glBlitFramebuffer.
    ///
    /// GL_NEAREST is mandatory, not a choice: a blit that includes
    /// GL_DEPTH_BUFFER_BIT rejects GL_LINEAR. `dst` must be exactly the same
    /// dimensions — a multisample blit cannot rescale.
    ///
    /// Restores no state; the caller binds what it needs next.
    /// No-op if !valid() or the sizes disagree.
    void resolve_to(const HdrTarget& dst) const;

    bool valid() const { return fbo_ != 0; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }
    int samples() const { return samples_; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t color_rb_ = 0;
    std::uint32_t depth_rb_ = 0;
    int width_ = 0;
    int height_ = 0;
    int samples_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 5: Write the implementation**

Create `native/src/renderer/hdr_msaa_target.cc`. `resolve_to` is implemented here but is exercised in Task 2.

```cpp
// native/src/renderer/hdr_msaa_target.cc
#include "renderer/hdr_msaa_target.h"
#include "renderer/hdr_target.h"
#include <glad/glad.h>

namespace renderer {

HdrMsaaTarget::~HdrMsaaTarget() { destroy(); }

void HdrMsaaTarget::destroy() {
    if (color_rb_) { glDeleteRenderbuffers(1, &color_rb_); color_rb_ = 0; }
    if (depth_rb_) { glDeleteRenderbuffers(1, &depth_rb_); depth_rb_ = 0; }
    if (fbo_)      { glDeleteFramebuffers(1, &fbo_);       fbo_ = 0; }
    width_ = height_ = samples_ = 0;
}

void HdrMsaaTarget::resize(int w, int h, int samples) {
    if (w < 1) w = 1;
    if (h < 1) h = 1;
    if (samples < 2) { destroy(); return; }
    if (w == width_ && h == height_ && samples == samples_ && fbo_ != 0) return;
    destroy();

    glGenRenderbuffers(1, &color_rb_);
    glBindRenderbuffer(GL_RENDERBUFFER, color_rb_);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples, GL_RGBA16F, w, h);

    glGenRenderbuffers(1, &depth_rb_);
    glBindRenderbuffer(GL_RENDERBUFFER, depth_rb_);
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples,
                                     GL_DEPTH_COMPONENT24, w, h);
    glBindRenderbuffer(GL_RENDERBUFFER, 0);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                              GL_RENDERBUFFER, color_rb_);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                              GL_RENDERBUFFER, depth_rb_);

    const GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (status != GL_FRAMEBUFFER_COMPLETE) {
        // Driver refused this combination. Leave nothing half-built: the
        // caller's valid() check routes the frame down the non-MSAA path.
        destroy();
        return;
    }

    width_ = w; height_ = h; samples_ = samples;
}

void HdrMsaaTarget::bind() const {
    if (fbo_ == 0) return;
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
}

void HdrMsaaTarget::resolve_to(const HdrTarget& dst) const {
    if (fbo_ == 0) return;
    if (dst.width() != width_ || dst.height() != height_) return;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo_);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dst.fbo());
    // GL_NEAREST is required whenever the blit includes depth. Src and dst
    // rects are identical because a multisample blit cannot rescale.
    glBlitFramebuffer(0, 0, width_, height_,
                      0, 0, width_, height_,
                      GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT,
                      GL_NEAREST);
}

}  // namespace renderer
```

Add `hdr_msaa_target.cc` to the source list in `native/src/renderer/CMakeLists.txt`, in alphabetical position immediately after `hdr_target.cc`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "HdrMsaaTarget|GlCaps" --output-on-failure
```

Expected: PASS. On a machine where `GL_MAX_SAMPLES` is 4, `CreatesCompleteFramebufferAtEachSampleCount` skips the 8× iteration by design.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/hdr_msaa_target.h \
        native/src/renderer/hdr_msaa_target.cc \
        native/src/renderer/include/renderer/gl_caps.h \
        native/src/renderer/gl_caps.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/hdr_msaa_target_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): add HdrMsaaTarget and GL_MAX_SAMPLES capability

Multisample RGBA16F colour + depth renderbuffers behind a target that can
only be read by resolving. Renderbuffers rather than textures keeps
sampler2DMS out of the codebase. An incomplete framebuffer destroys the
target rather than leaving it half-built, so the caller falls back."
```

---

### Task 2: Prove the resolve preserves colour and depth

**Files:**
- Test: `native/tests/renderer/hdr_msaa_resolve_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: `renderer::HdrMsaaTarget` (`resize`, `bind`, `resolve_to`, `valid`) and `renderer::clamp_msaa_samples` from Task 1; `renderer::HdrTarget` (`resize`, `bind`, `fbo`, `width`, `height`), which already exists.
- Produces: nothing consumed by later tasks. This task exists to de-risk the depth resolve, which the spec names as risk #1: `nebula_volumetric.frag` terminates its raymarch at `min(t1, scene_dist)` read from this depth buffer, so a wrong resolve makes nebulae clip against hulls.

- [ ] **Step 1: Write the test**

Create `native/tests/renderer/hdr_msaa_resolve_test.cc`. The test clears both a multisample target and a single-sample reference to the same colour and depth, resolves the first, and compares readbacks. Clearing rather than drawing geometry is deliberate: every sample in a cleared buffer holds the same value, so the comparison is exact and cannot be confused by legitimate edge blending.

```cpp
// native/tests/renderer/hdr_msaa_resolve_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/hdr_msaa_target.h>
#include <renderer/hdr_target.h>
#include <renderer/gl_caps.h>
#include <renderer/window.h>
#include <memory>

namespace {

constexpr int kW = 64;
constexpr int kH = 48;

class HdrMsaaResolveTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64, 64, "resolve-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }

    // Clear whatever is currently bound to a known colour and depth.
    static void clear_to(float r, float g, float b, float a, float depth) {
        glClearColor(r, g, b, a);
        glClearDepth(depth);
        glDepthMask(GL_TRUE);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }
};

TEST_F(HdrMsaaResolveTest, ResolvedColourMatchesSingleSampleReference) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    const int samples = renderer::clamp_msaa_samples(4, caps);
    if (samples < 2) GTEST_SKIP() << "no MSAA on this driver";

    renderer::HdrMsaaTarget ms;
    ms.resize(kW, kH, samples);
    ASSERT_TRUE(ms.valid());

    renderer::HdrTarget dst;
    dst.resize(kW, kH);

    ms.bind();
    clear_to(0.25f, 0.5f, 0.75f, 1.0f, 0.5f);
    ms.resolve_to(dst);

    glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo());
    float px[4] = {0, 0, 0, 0};
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_FLOAT, px);
    EXPECT_NEAR(px[0], 0.25f, 1e-3f);
    EXPECT_NEAR(px[1], 0.50f, 1e-3f);
    EXPECT_NEAR(px[2], 0.75f, 1e-3f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// THE LOAD-BEARING TEST. glBlitFramebuffer's depth sample selection is
// implementation-defined. nebula_volumetric.frag reads this depth to
// terminate its march; if the resolve loses it, nebulae clip against hulls.
TEST_F(HdrMsaaResolveTest, ResolvedDepthMatchesSingleSampleReference) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    const int samples = renderer::clamp_msaa_samples(4, caps);
    if (samples < 2) GTEST_SKIP() << "no MSAA on this driver";

    // Reference: a plain single-sample target cleared to the same depth.
    renderer::HdrTarget reference;
    reference.resize(kW, kH);
    reference.bind();
    clear_to(0.0f, 0.0f, 0.0f, 1.0f, 0.375f);
    float ref_depth = 0.0f;
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &ref_depth);

    // Subject: multisample cleared identically, then resolved.
    renderer::HdrMsaaTarget ms;
    ms.resize(kW, kH, samples);
    ASSERT_TRUE(ms.valid());
    renderer::HdrTarget dst;
    dst.resize(kW, kH);

    ms.bind();
    clear_to(0.0f, 0.0f, 0.0f, 1.0f, 0.375f);
    ms.resolve_to(dst);

    glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo());
    float got_depth = 0.0f;
    glReadPixels(kW / 2, kH / 2, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, &got_depth);

    // 24-bit depth: one LSB is ~6e-8. 1e-5 is loose enough for the format and
    // far tighter than any plausible wrong-sample or dropped-blit result.
    EXPECT_NEAR(got_depth, ref_depth, 1e-5f);
    EXPECT_NEAR(got_depth, 0.375f, 1e-5f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

TEST_F(HdrMsaaResolveTest, MismatchedSizeIsANoOpNotACrash) {
    const renderer::GlCaps caps = renderer::query_gl_caps();
    const int samples = renderer::clamp_msaa_samples(4, caps);
    if (samples < 2) GTEST_SKIP() << "no MSAA on this driver";

    renderer::HdrMsaaTarget ms;
    ms.resize(kW, kH, samples);
    renderer::HdrTarget dst;
    dst.resize(kW * 2, kH);           // deliberately wrong size

    ms.bind();
    clear_to(1.0f, 0.0f, 0.0f, 1.0f, 0.5f);
    ms.resolve_to(dst);               // must not blit, must not raise GL error
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

}  // namespace
```

Add `hdr_msaa_resolve_test.cc` to `native/tests/renderer/CMakeLists.txt` immediately after `hdr_msaa_target_test.cc`.

- [ ] **Step 2: Run the tests**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R HdrMsaaResolve --output-on-failure
```

Expected: PASS, because Task 1 already implemented `resolve_to`. These tests are written second because their purpose is verification, not driving the implementation.

**If `ResolvedDepthMatchesSingleSampleReference` FAILS: STOP and report BLOCKED.** Do not proceed to Task 3. This is the spec's risk #1 materialising. The escape hatch (a `sampler2DMS` shader taking sample 0 instead of a blit) is a design change and needs Mark's decision, not an improvised fix.

- [ ] **Step 3: Commit**

```bash
git add native/tests/renderer/hdr_msaa_resolve_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "test(renderer): pin MSAA colour and depth resolve against a reference

Depth is the load-bearing half: glBlitFramebuffer's sample selection is
implementation-defined and nebula_volumetric terminates its march on this
buffer, so a lost resolve shows up as nebulae clipping against hulls."
```

---

### Task 3: Split `render_space` into geometry and VFX phases

**Files:**
- Modify: `native/src/host/host_bindings.cc:783-913` (the `render_space` lambda), `:997`, `:1003`, `:1037` (its three call sites)

**Interfaces:**
- Consumes: `renderer::HdrMsaaTarget` (Task 1) — for the parameter type only; nothing is multisampled yet.
- Produces: two lambdas replacing one.
  - `render_space_geometry(const scenegraph::Camera& cam, renderer::HdrTarget* hdr, renderer::HdrMsaaTarget* msaa, float ambient_scale)` — draws backdrop, suns, opaque, breach, shield into whichever target is non-null. Exactly one of `hdr`/`msaa` is non-null.
  - `render_space_vfx(const scenegraph::Camera& cam, bool for_viewscreen, renderer::HdrTarget& target, int vw, int vh, float ambient_scale)` — draws dust through cloak into `target`, and is the only phase that reads `target.color_texture()` / `target.depth_texture()`.

**This task is a PURE REFACTOR. Rendered output must be identical.** It is separated from Task 4 so a bisect can distinguish "the split broke something" from "MSAA broke something".

- [ ] **Step 1: Capture a before-baseline**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -30
```

Record the pass/fail counts. Every renderer test passing now must still pass after the split. If any test fails *before* your change, check it against `tests/known_failures.txt` — do not attribute it to this task.

- [ ] **Step 2: Split the lambda**

In `native/src/host/host_bindings.cc`, the current `render_space` lambda begins at line 783 with signature:

```cpp
auto render_space = [&](const scenegraph::Camera& cam, bool for_viewscreen,
                        renderer::HdrTarget& target, int vw, int vh) {
```

Replace it with two lambdas. **The split point is immediately after the `g_shield_pass->submit(...)` block and immediately before the `// Dust is normally skipped on the viewscreen RTT` comment.** Everything above that point goes into the geometry phase; everything from the dust block through the end of the cloak block goes into the VFX phase.

`ambient_scale` is currently computed inside the lambda (`const float ambient_scale = dauntless_filmic::ambient_scale();`). Both phases need it, so hoist it to a parameter — compute it once per call site and pass it in, so the two phases cannot disagree about it.

```cpp
    // Phase 1 — depth-writing geometry. Renders into EITHER the plain HDR
    // target (msaa == nullptr, the stock path) or a multisample target that
    // the caller resolves into the HDR target afterwards. Reads no scene
    // textures, which is exactly why it can be multisampled: nothing here
    // samples the surface it is drawing into.
    auto render_space_geometry = [&](const scenegraph::Camera& cam,
                                     renderer::HdrTarget* hdr,
                                     renderer::HdrMsaaTarget* msaa,
                                     float ambient_scale) {
        if (msaa != nullptr) msaa->bind(); else hdr->bind();
        {
            DAUNTLESS_FRAME_SCOPE("space.backdrop");
            // ... unchanged body ...
        }
        // ... suns, opaque, breach, shield — all unchanged ...
    };

    // Phase 2 — everything transparent, additive, or reading the scene back.
    // ALWAYS single-sample: nebula_volumetric samples target.depth_texture()
    // and both nebula_godray and cloak_pass sample target.color_texture()
    // while drawing into that same target. Those reads require a resolved,
    // sampleable surface.
    auto render_space_vfx = [&](const scenegraph::Camera& cam,
                                bool for_viewscreen,
                                renderer::HdrTarget& target,
                                int vw, int vh, float ambient_scale) {
        target.bind();
        // ... dust, nebula, godray, lens flare, weapons, hull discharge,
        //     shockwave, particles, cloak — all unchanged ...
    };
```

Add `#include <renderer/hdr_msaa_target.h>` alongside the existing renderer includes near the top of the file.

- [ ] **Step 3: Update the three call sites**

All three currently pass a single target. In this task every one of them still uses the non-MSAA path — `msaa` is `nullptr` everywhere. Task 4 changes only the main-view site.

At `:997` (the first viewscreen RTT call, which the spec excludes from MSAA):

```cpp
            const float vs_ambient = dauntless_filmic::ambient_scale();
            render_space_geometry(scam, g_viewscreen_hdr.get(), nullptr, vs_ambient);
            render_space_vfx(scam, /*for_viewscreen=*/true, *g_viewscreen_hdr,
                             vw, vh, vs_ambient);
```

Apply the same shape to the second viewscreen call at `:1003`, keeping its own camera variable (`vcam`) and its own `vw`/`vh` arguments exactly as they are today.

At `:1037` (the main view):

```cpp
        const float ex_ambient = dauntless_filmic::ambient_scale();
        render_space_geometry(g_camera, g_hdr_target.get(), nullptr, ex_ambient);
        render_space_vfx(g_camera, /*for_viewscreen=*/false, *g_hdr_target,
                         fw, fh, ex_ambient);
```

Note `g_hdr_target->resize(fw, fh); g_hdr_target->bind();` already happens at `:1021-1022`, before this call. Leave those lines alone — the geometry phase's own `bind()` is harmless and makes each phase self-contained.

- [ ] **Step 4: Verify nothing changed**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -30
```

Expected: **exactly the same pass/fail set as Step 1.** Any new failure means the split moved a pass across the boundary or dropped state. Compare your split against the pass order listed in the spec's "Frame flow" section.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "refactor(renderer): split render_space into geometry and VFX phases

Pure refactor, no behaviour change. The geometry phase writes depth and
reads nothing; the VFX phase is the only half that samples the target it
draws into (nebula depth, godray and cloak colour). Separating them lets
the geometry phase render multisampled while the VFX phase keeps the
resolved, sampleable surface it requires.

Committed separately from the MSAA wiring so a bisect can tell the split
apart from the feature."
```

---

### Task 4: Wire MSAA into the frame and expose it to Python

**Files:**
- Modify: `native/src/host/host_bindings.cc` (globals near `:273` and `:326`, init near `:608`, teardown near `:680`, main-view call site near `:1037`, pybind defs near `:3519`)
- Modify: `engine/renderer.py` (the expected-name list near `:57-74`, and a new wrapper beside `set_smaa_enabled` at `:509`)

**Interfaces:**
- Consumes: `renderer::HdrMsaaTarget` and `renderer::clamp_msaa_samples` from Task 1; `render_space_geometry` / `render_space_vfx` from Task 3.
- Produces:
  - Python: `renderer.set_msaa_samples(samples: int) -> None` (0 = off; 2/4/8 requested, clamped internally) and `renderer.max_msaa_samples() -> int`.
  - Native: `_dauntless_host.msaa_set_samples(samples)`, `_dauntless_host.msaa_max_samples()`.

- [ ] **Step 1: Add the native state and bindings**

Beside `bool g_smaa_enabled` (around `:326`) add:

```cpp
// Requested MSAA sample count for the opaque space pass. 0 == off, which is
// the stock path: no multisample target is allocated and no blit occurs.
// Set by msaa_set_samples; clamped against GL_MAX_SAMPLES at apply time.
int g_msaa_samples = 0;
```

Beside `std::unique_ptr<renderer::HdrTarget> g_hdr_target;` (`:273`) add:

```cpp
std::unique_ptr<renderer::HdrMsaaTarget>   g_msaa_target;
```

In init, beside `g_hdr_target = std::make_unique<renderer::HdrTarget>();` (`:608`):

```cpp
    g_msaa_target     = std::make_unique<renderer::HdrMsaaTarget>();
```

In teardown, beside `g_hdr_target.reset();` (`:680`):

```cpp
    g_msaa_target.reset();
```

Construction allocates no GL objects — the members are zero until `resize()` is called, which only happens when MSAA is actually on.

Add the pybind definitions beside `smaa_set_enabled` (`:3519`):

```cpp
    m.def("msaa_set_samples",
          [](int samples) { g_msaa_samples = samples; },
          py::arg("samples"),
          "Set MSAA sample count for the opaque space pass. 0 disables it "
          "(the stock path: no multisample buffer, no resolve blit). "
          "2/4/8 are clamped against GL_MAX_SAMPLES when applied.");

    m.def("msaa_max_samples",
          []() { return renderer::query_gl_caps().max_samples; },
          "GL_MAX_SAMPLES for this context — the ceiling the UI offers.");
```

Ensure `#include <renderer/gl_caps.h>` is present among the renderer includes.

- [ ] **Step 2: Route the main view through MSAA**

At the main-view call site (`:1037`, as rewritten in Task 3), replace the two unconditional calls with:

```cpp
        const float ex_ambient = dauntless_filmic::ambient_scale();

        // MSAA path: the depth-writing geometry renders multisampled, then
        // resolves colour+depth into g_hdr_target so every VFX pass and the
        // whole post chain receive exactly the single-sample textures they
        // already expect. Nothing downstream of the resolve is aware of MSAA.
        //
        // Falls through to the stock path whenever the requested count clamps
        // to 0, or the driver refused the allocation (!valid()) — we never
        // trust GL_RGBA16F multisample on the strength of the spec alone.
        const int msaa = renderer::clamp_msaa_samples(g_msaa_samples,
                                                      renderer::query_gl_caps());
        if (msaa >= 2) {
            g_msaa_target->resize(fw, fh, msaa);
        }
        if (msaa >= 2 && g_msaa_target->valid()) {
            render_space_geometry(g_camera, nullptr, g_msaa_target.get(), ex_ambient);
            g_msaa_target->resolve_to(*g_hdr_target);
        } else {
            render_space_geometry(g_camera, g_hdr_target.get(), nullptr, ex_ambient);
        }
        render_space_vfx(g_camera, /*for_viewscreen=*/false, *g_hdr_target,
                         fw, fh, ex_ambient);
```

`query_gl_caps()` per frame is a handful of `glGetIntegerv` calls, negligible against a frame where `sim` alone is ~70 ms.

**Do not touch the viewscreen call sites.** The spec excludes the RTT.

- [ ] **Step 3: Add the Python wrappers**

In `engine/renderer.py`, add `"msaa_set_samples"` and `"msaa_max_samples"` to the expected-name tuple that spans roughly `:57-74` (insert in the alphabetical position matching the surrounding entries). Then, immediately after `set_smaa_enabled` at `:509`:

```python
def set_msaa_samples(samples: int) -> None:
    """Set MSAA sample count for the opaque space pass.

    0 disables MSAA entirely — no multisample buffer is allocated and no
    resolve blit runs, so the frame is byte-identical to the pre-MSAA
    renderer. 2/4/8 are clamped against GL_MAX_SAMPLES when applied, and a
    driver that refuses the allocation silently falls back to 0.
    """
    _h.msaa_set_samples(int(samples))


def max_msaa_samples() -> int:
    """GL_MAX_SAMPLES for the live context — the ceiling the UI offers."""
    return int(_h.msaa_max_samples())
```

- [ ] **Step 4: Verify**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -20
VIRTUAL_ENV="$PWD/.venv" ./.venv/bin/python -m pytest tests/unit -q -k "renderer or binding" 2>&1 | tail -15
```

Expected: ctest unchanged from Task 3, and any test pinning `engine/renderer.py`'s expected-name list passes with the two new entries. If `AttributeError: module '_dauntless_host' has no attribute 'msaa_set_samples'` appears, the binary is stale — rebuild from `build/`, do not change the Python side.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(renderer): render the opaque space pass into an MSAA target

Geometry renders multisampled and resolves colour+depth into the existing
HdrTarget, so the VFX passes and post chain receive the single-sample
textures they already expect and need no changes at all.

0 samples, a clamped-to-zero request, or a driver that refuses the
allocation all fall through to the stock path unchanged. The viewscreen
RTT is deliberately excluded."
```

---

### Task 5: Replace the `smaa` setting with `aa_mode`, and migrate

**Files:**
- Modify: `engine/ui/configuration_panel.py` (module constants beside `FOV_MIN`/`FOV_MAX`; `SettingsSnapshot` at `:64`)
- Modify: `engine/settings_store.py` (`SCHEMA_VERSION` at `:31`, the panel import near the top, `load()` at `:59`, the `SETTINGS` table at `:210`)
- Test: `tests/unit/test_settings_store.py`

**Interfaces:**
- Consumes: `renderer.set_msaa_samples` and the existing `renderer.set_smaa_enabled` (Task 4).
- Produces: in `engine/ui/configuration_panel.py` — `AA_OFF = 0`, `AA_SMAA = 1`, `AA_MSAA_2X = 2`, `AA_MSAA_4X = 3`, `AA_MSAA_8X = 4`, `AA_MODE_SAMPLES = (0, 0, 2, 4, 8)`, `AA_MODE_LABELS = ("Off", "SMAA", "2×", "4×", "8×")`, and `SettingsSnapshot.aa_mode: int`. In `engine/settings_store.py` — a `Setting` row keyed `aa_mode`, and `SCHEMA_VERSION = 2`.

The constants live in `configuration_panel.py`, not `settings_store.py`, because `settings_store` already imports `FOV_MIN`/`FOV_MAX`/`SettingsSnapshot` from the panel module. Defining them the other way round would create an import cycle.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_settings_store.py`:

```python
import json

from engine.settings_store import SettingsStore, SCHEMA_VERSION, SETTINGS
from engine.ui.configuration_panel import (
    AA_OFF, AA_SMAA, AA_MSAA_4X, AA_MODE_SAMPLES, AA_MODE_LABELS,
)


def _write(tmp_path, doc):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_migrates_smaa_on_true_to_aa_mode_smaa(tmp_path):
    p = _write(tmp_path, {"version": 1, "graphics": {"smaa_on": True}})
    s = SettingsStore(path=p)
    s.load()
    assert s.get("graphics", "aa_mode") == AA_SMAA
    assert not s.has("graphics", "smaa_on")


def test_migrates_smaa_on_false_to_aa_mode_off(tmp_path):
    p = _write(tmp_path, {"version": 1, "graphics": {"smaa_on": False}})
    s = SettingsStore(path=p)
    s.load()
    assert s.get("graphics", "aa_mode") == AA_OFF
    assert not s.has("graphics", "smaa_on")


def test_migration_preserves_other_keys(tmp_path):
    p = _write(tmp_path, {"version": 1,
                          "graphics": {"smaa_on": True, "dust": False},
                          "paths": {"game": "/somewhere"}})
    s = SettingsStore(path=p)
    s.load()
    assert s.get("graphics", "dust") is False
    assert s.get("paths", "game") == "/somewhere"


def test_absent_smaa_key_creates_no_aa_mode(tmp_path):
    # An absent key must stay absent: apply_all never applies what was not
    # stored, so inventing aa_mode here would silently override the engine
    # default on first launch.
    p = _write(tmp_path, {"version": 1, "graphics": {"dust": True}})
    s = SettingsStore(path=p)
    s.load()
    assert not s.has("graphics", "aa_mode")


def test_already_migrated_document_is_untouched(tmp_path):
    p = _write(tmp_path, {"version": 2, "graphics": {"aa_mode": AA_MSAA_4X}})
    s = SettingsStore(path=p)
    s.load()
    assert s.get("graphics", "aa_mode") == AA_MSAA_4X


def test_newer_stamped_document_is_not_downgraded(tmp_path):
    # A file from a future build keeps its stamp and its keys. Migrating
    # "down" would corrupt settings the newer build owns.
    p = _write(tmp_path, {"version": 99,
                          "graphics": {"smaa_on": True, "aa_mode": AA_OFF}})
    s = SettingsStore(path=p)
    s.load()
    assert s.get("graphics", "aa_mode") == AA_OFF
    assert s.get("graphics", "smaa_on") is True


def test_schema_version_is_two():
    assert SCHEMA_VERSION == 2


def test_aa_mode_samples_table_matches_labels():
    assert len(AA_MODE_SAMPLES) == len(AA_MODE_LABELS) == 5
    assert AA_MODE_SAMPLES[AA_OFF] == 0
    assert AA_MODE_SAMPLES[AA_SMAA] == 0     # SMAA is not a sample count
    assert AA_MODE_SAMPLES[AA_MSAA_4X] == 4


def test_reset_graphics_restores_smaa_not_the_players_msaa_choice(tmp_path):
    # reset_default=AA_SMAA is what makes this true. Without it, Reset would
    # re-resolve `default` — which for a plain-constant row is the same value,
    # but pinning it here stops a future refactor to a callable `default`
    # from silently turning Reset into a no-op (the fov_deg/camera_shake bug
    # the Setting docstring describes).
    from engine.settings_store import reset_and_apply_section

    p = _write(tmp_path, {"version": 2, "graphics": {"aa_mode": AA_MSAA_4X}})
    s = SettingsStore(path=p)
    s.load()
    assert s.get("graphics", "aa_mode") == AA_MSAA_4X

    ctx = _ctx()   # reuse this file's existing SettingsContext helper
    out = reset_and_apply_section(s, ctx, "graphics")
    assert out["aa_mode"] == AA_SMAA
    assert not s.has("graphics", "aa_mode")   # reset deletes the stored key


def test_aa_mode_applier_sets_smaa_and_msaa_exclusively():
    from types import SimpleNamespace

    row = next(r for r in SETTINGS if r.key == "aa_mode")
    calls = []
    ctx = SimpleNamespace(r=SimpleNamespace(
        set_smaa_enabled=lambda v: calls.append(("smaa", v)),
        set_msaa_samples=lambda v: calls.append(("msaa", v)),
    ))

    expected = {0: (False, 0), 1: (True, 0), 2: (False, 2),
                3: (False, 4), 4: (False, 8)}
    for mode, (smaa, samples) in expected.items():
        calls.clear()
        row.apply(ctx, mode)
        assert ("smaa", smaa) in calls, mode
        assert ("msaa", samples) in calls, mode
```

If `SettingsStore.__init__` does not accept a `path=` keyword, match the signature the existing tests in this file already use to point a store at a temp file.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
VIRTUAL_ENV="$PWD/.venv" ./.venv/bin/python -m pytest tests/unit/test_settings_store.py -q 2>&1 | tail -20
```

Expected: FAIL — `ImportError: cannot import name 'AA_OFF' from 'engine.ui.configuration_panel'`.

- [ ] **Step 3: Add the AA constants and snapshot field**

In `engine/ui/configuration_panel.py`, beside the existing `FOV_MIN`/`FOV_MAX` module constants:

```python
# ── Anti-aliasing modes ─────────────────────────────────────────────────────
# One mutually-exclusive selector replaces the old independent SMAA toggle.
# The stored value is the INDEX, not a sample count: the settings table's
# lo/hi does a contiguous-range check, and driver capability is a separate
# concern handled by clamping at apply time against GL_MAX_SAMPLES. A file
# carrying AA_MSAA_8X on a 4x-max machine therefore applies 4x, and applies
# 8x again if moved to a machine that supports it.
AA_OFF = 0
AA_SMAA = 1
AA_MSAA_2X = 2
AA_MSAA_4X = 3
AA_MSAA_8X = 4

# Indexed by aa_mode. SMAA is not a sample count, hence the second 0.
AA_MODE_SAMPLES = (0, 0, 2, 4, 8)
AA_MODE_LABELS = ("Off", "SMAA", "2×", "4×", "8×")
```

In `SettingsSnapshot` (at `:64`), replace `smaa_on: bool = True` with:

```python
    aa_mode: int = AA_SMAA
```

- [ ] **Step 4: Bump the schema and add the migration**

In `engine/settings_store.py`, change `SCHEMA_VERSION = 1` to `SCHEMA_VERSION = 2`.

Extend the existing panel import to:

```python
from engine.ui.configuration_panel import (
    AA_MODE_SAMPLES, AA_MSAA_8X, AA_OFF, AA_SMAA,
    FOV_MAX, FOV_MIN, SettingsSnapshot,
)
```

In `load()`, replace the final `self._doc = doc` with:

```python
        self._doc = doc
        self._migrate()
```

Add the method immediately after `load()`:

```python
    def _migrate(self) -> None:
        """Bring an older document up to SCHEMA_VERSION, in place.

        Migrate UP ONLY. A file stamped newer than us belongs to a build that
        knows things we do not; rewriting its keys would corrupt them. This
        mirrors the setdefault-not-assignment rule in _save().

        Migrations do not save. The next set() writes the whole document
        anyway, and a load that silently rewrote the file would make a
        read-only install fail at boot rather than at first change.
        """
        try:
            stamped = int(self._doc.get("version", 1))
        except (TypeError, ValueError):
            stamped = 1
        if stamped >= SCHEMA_VERSION:
            return

        # v1 -> v2: the independent `smaa_on` bool became one mutually
        # exclusive `aa_mode` index shared with MSAA. An ABSENT smaa_on stays
        # absent — apply_all never applies an unstored key, so inventing
        # aa_mode here would override the engine default on first launch.
        graphics = self._doc.get("graphics")
        if isinstance(graphics, dict) and "smaa_on" in graphics:
            graphics["aa_mode"] = AA_SMAA if graphics.pop("smaa_on") else AA_OFF

        self._doc["version"] = SCHEMA_VERSION
```

- [ ] **Step 5: Replace the settings row**

In the `SETTINGS` tuple, replace the `smaa` row (`:210-211`) with:

```python
    Setting("aa_mode", "graphics", "aa_mode", int, AA_SMAA,
            _fan(lambda c, v: c.r.set_smaa_enabled(v == AA_SMAA),
                 lambda c, v: c.r.set_msaa_samples(AA_MODE_SAMPLES[v])),
            lo=AA_OFF, hi=AA_MSAA_8X, reset_default=AA_SMAA),
```

Reusing `_fan` keeps `set_smaa_enabled` untouched and puts the mutual exclusion where the rest of the semantics live. The default stays SMAA, so the shipped baseline is unchanged.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
VIRTUAL_ENV="$PWD/.venv" ./.venv/bin/python -m pytest tests/unit/test_settings_store.py -q 2>&1 | tail -20
grep -rn "smaa_on" engine/ tests/ native/assets/ | grep -v "\.pyc"
```

Expected: tests PASS. The grep should leave only hits in `native/assets/ui-cef/js/configuration_panel.js` and `engine/ui/configuration_panel.py`'s panel plumbing — both handled in Task 6.

- [ ] **Step 7: Commit**

```bash
git add engine/settings_store.py engine/ui/configuration_panel.py \
        tests/unit/test_settings_store.py
git commit -m "feat(settings): replace the smaa toggle with an aa_mode selector

SMAA and MSAA become mutually exclusive members of one setting. The stored
value is an index, not a sample count, so the store's lo/hi range check
still applies and driver capability stays a separate apply-time concern.

Adds the store's first migration (SCHEMA_VERSION 1 -> 2). It migrates UP
only: a file stamped newer belongs to a build that knows more than we do.
An absent smaa_on stays absent, because apply_all never applies an
unstored key and inventing one would override the engine default."
```

---

### Task 6: The "Anti-aliasing" segmented row

**Files:**
- Modify: `engine/ui/configuration_panel.py` (`__init__` params near `:91`, snapshot build near `:112`, applier field near `:141`, `render_payload` signature tuple near `:201` and payload dict near `:227`, `dispatch_event` near `:319`, `handle_input` near `:429` and `:446`, `_focusables` docstring `:463` and body `:472`)
- Modify: `engine/settings_store.py` (add `apply_setting`)
- Modify: `native/assets/ui-cef/js/configuration_panel.js:28` and `:114`
- Modify: `engine/host_loop.py:7281`
- Test: `tests/unit/test_configuration_panel.py`

**Interfaces:**
- Consumes: `AA_OFF`, `AA_SMAA`, `AA_MSAA_8X`, `AA_MODE_LABELS`, `SettingsSnapshot.aa_mode` (Task 5); `renderer.max_msaa_samples` (Task 4).
- Produces: `ConfigurationPanel(set_aa_mode=..., max_msaa_samples=...)` replacing `set_smaa=...`; the `configuration/aa_mode:<index>` CEF event; `engine.settings_store.apply_setting(ctx, key, value)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_configuration_panel.py`. That file already has a factory at `:21` — `_make(**overrides)`, which fills every `set_*` parameter with a `Mock()` and **returns a `(panel, kwargs)` tuple**, not a bare panel. Use it, and remember to unpack.

Its `kwargs` dict must also have `set_smaa=Mock()` replaced with `set_aa_mode=Mock()` in Step 3, or every existing test in the file breaks.

Note the payload is not bare JSON — the existing tests parse it as
`json.loads(payload[len("setConfigurationPanel("):-2])`. Follow that idiom.

```python
import json

from engine.ui.configuration_panel import (
    AA_OFF, AA_SMAA, AA_MSAA_2X, AA_MSAA_8X, AA_MODE_LABELS,
)


def _body(panel):
    """Parse the setConfigurationPanel(...) JS call the panel pushes."""
    payload = panel.render_payload()
    return json.loads(payload[len("setConfigurationPanel("):-2])


def test_aa_mode_dispatch_applies_and_persists():
    changed = []
    p, kw = _make(on_change=lambda k, v: changed.append((k, v)))
    assert p.dispatch_event("aa_mode:%d" % AA_MSAA_2X) is True
    kw["set_aa_mode"].assert_called_once_with(AA_MSAA_2X)
    assert changed == [("aa_mode", AA_MSAA_2X)]


def test_aa_mode_dispatch_rejects_out_of_range():
    p, kw = _make()
    assert p.dispatch_event("aa_mode:9") is False
    assert p.dispatch_event("aa_mode:-1") is False
    assert p.dispatch_event("aa_mode:banana") is False
    kw["set_aa_mode"].assert_not_called()


def test_aa_mode_appears_in_render_payload():
    p, _ = _make()
    p.open()
    body = _body(p)
    assert body["settings"]["aa_mode"] == AA_SMAA
    assert "smaa_on" not in body["settings"]


def test_render_payload_carries_the_sample_ceiling():
    p, _ = _make(max_msaa_samples=4)
    p.open()
    assert _body(p)["settings"]["max_msaa_samples"] == 4


def test_aa_mode_is_focusable_on_the_graphics_tab():
    p, _ = _make()
    p.open()
    assert ("ctrl", "aa_mode") in p._focusables()
    assert ("ctrl", "smaa") not in p._focusables()


def test_aa_mode_labels_are_five_wide():
    assert AA_MODE_LABELS == ("Off", "SMAA", "2×", "4×", "8×")
    assert AA_MSAA_8X == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
VIRTUAL_ENV="$PWD/.venv" ./.venv/bin/python -m pytest tests/unit/test_configuration_panel.py -q 2>&1 | tail -20
```

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'set_aa_mode'`.

- [ ] **Step 3: Update the panel**

In `engine/ui/configuration_panel.py`:

Replace the `set_smaa: Callable[[bool], None],` constructor parameter (`:91`) with:

```python
                 set_aa_mode: Callable[[int], None],
```

and add, after the other optional parameters:

```python
                 max_msaa_samples: int = 8,
```

A default of 8 means every existing construction site and test keeps working and shows all five segments.

Replace `self._set_smaa = set_smaa` (`:141`) with:

```python
        self._set_aa_mode = set_aa_mode
        self._max_msaa_samples = int(max_msaa_samples)
```

Replace `smaa_on=initial_settings.smaa_on,` in the snapshot construction (`:112`) with:

```python
            aa_mode=max(AA_OFF, min(AA_MSAA_8X, int(initial_settings.aa_mode))),
```

Replace `self._settings.smaa_on,` in the `render_payload` change-detection tuple (`:201`) with `self._settings.aa_mode,`, and `"smaa_on": self._settings.smaa_on,` in the payload dict (`:227`) with:

```python
                "aa_mode": self._settings.aa_mode,
                "max_msaa_samples": self._max_msaa_samples,
```

Replace the `toggle:smaa` branch in `dispatch_event` (`:319-323`) with a range-checked index handler, placed beside the existing `fov:` prefix handler:

```python
        if action.startswith("aa_mode:"):
            raw = action[len("aa_mode:"):]
            try:
                mode = int(raw)
            except ValueError:
                return False
            if not (AA_OFF <= mode <= AA_MSAA_8X):
                return False
            self._set_aa_mode(mode)
            self._settings.aa_mode = mode
            self._on_change("aa_mode", mode)
            return True
```

In `handle_input`, delete the `elif activate and kind == "ctrl" and target == "smaa":` branch (`:429-430`) and add left/right cycling beside the existing `ai_difficulty` block (`:452`):

```python
        if kind == "ctrl" and target == "aa_mode":
            if _pressed(App.WC_RIGHT):
                self.dispatch_event(
                    "aa_mode:" + str(min(AA_MSAA_8X, self._settings.aa_mode + 1)))
            elif _pressed(App.WC_LEFT):
                self.dispatch_event(
                    "aa_mode:" + str(max(AA_OFF, self._settings.aa_mode - 1)))
```

Match the exact key-constant spelling the neighbouring `ai_difficulty` block uses; do not invent constant names.

In `_focusables` (`:472`), change `("ctrl", "smaa")` to `("ctrl", "aa_mode")`, and update the docstring example at `:463` the same way.

- [ ] **Step 4: Add the settings applier helper**

In `engine/settings_store.py`, beside the existing `set_setting`:

```python
def apply_setting(ctx, key: str, value) -> None:
    """Run one SETTINGS row's applier without touching the store.

    The panel calls this rather than a renderer function directly: aa_mode is
    one index that drives two engine toggles, and that fan-out belongs in the
    table, not duplicated at the call site.
    """
    for row in SETTINGS:
        if row.key == key:
            row.apply(ctx, value)
            return
```

- [ ] **Step 5: Update the CEF panel**

In `native/assets/ui-cef/js/configuration_panel.js`, change line 28:

```js
const CP_GRAPHICS_STANDALONE = ['aa_mode', 'dust', 'fov'];
```

Replace line 114 (`html += _cpToggleRow('Anti-Aliasing (SMAA)', ...)`) with a segmented control modelled on the AI Difficulty block at `:174-186`. It stays first in the graphics body, exactly where the SMAA row was:

```js
    // Anti-aliasing — five-way segmented control. SMAA and MSAA are mutually
    // exclusive, so they are one setting rather than two toggles. Segments
    // above the driver's GL_MAX_SAMPLES are omitted, not disabled.
    const aaLabels = ['Off', 'SMAA', '2×', '4×', '8×'];
    const aaSamples = [0, 0, 2, 4, 8];
    const maxSamples = (typeof s.max_msaa_samples === 'number')
        ? s.max_msaa_samples : 8;
    const aa = (typeof s.aa_mode === 'number') ? s.aa_mode : 1;
    html += '<div class="cp-row' + (isFoc('aa_mode') ? ' cp-focused' : '') + '">'
          +     '<span class="cp-label">Anti-aliasing</span>'
          +     '<div class="cp-segmented">';
    for (let i = 0; i < aaLabels.length; ++i) {
        if (aaSamples[i] > maxSamples) continue;
        html += '<button class="cp-toggle' + (aa === i ? ' cp-toggle--on' : '') + '"'
              +    ' onclick="dauntlessEvent(\'configuration/aa_mode:' + i + '\')">'
              +    aaLabels[i]
              + '</button>';
    }
    html += '</div></div>';
```

- [ ] **Step 6: Wire the host loop**

In `engine/host_loop.py`, replace `set_smaa=r.set_smaa_enabled,` (`:7281`) with:

```python
            set_aa_mode=lambda mode: _settings.apply_setting(
                _settings_ctx, "aa_mode", mode),
            max_msaa_samples=r.max_msaa_samples(),
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
VIRTUAL_ENV="$PWD/.venv" ./.venv/bin/python -m pytest \
    tests/unit/test_configuration_panel.py tests/unit/test_settings_store.py -q 2>&1 | tail -20
grep -rn "smaa_on\|set_smaa=" engine/ tests/ native/assets/ | grep -v "\.pyc"
```

Expected: tests PASS, and the grep returns nothing — every reference to the old key is gone.

- [ ] **Step 8: Run the full gate**

```bash
cmake -B build -S . && ./scripts/check_tests.sh 2>&1 | tail -30
```

Expected: exit 0. Any failure not already in `tests/known_failures.txt` is a regression from this branch — fix it rather than baselining it.

- [ ] **Step 9: Commit**

```bash
git add engine/ui/configuration_panel.py engine/settings_store.py \
        engine/host_loop.py \
        native/assets/ui-cef/js/configuration_panel.js \
        tests/unit/test_configuration_panel.py
git commit -m "feat(ui): one Anti-aliasing selector replacing the SMAA toggle

Five-way segmented row (Off/SMAA/2x/4x/8x) reusing the AI Difficulty
markup, so no new control type enters the CEF panel and keyboard
left/right navigation comes for free. Segments above the driver's
GL_MAX_SAMPLES are omitted rather than shown disabled.

The panel routes through the settings row's applier rather than calling
the renderer directly: one mode index drives two engine toggles, and that
fan-out belongs in the table."
```

---

## Live verification (Mark, main tree — NOT automatable)

None of the above establishes whether MSAA looks better than SMAA. Green tests cannot see game feel, and the implementing agent must never launch the game. After the branch merges and `build/` is rebuilt in the main tree (a branch switch desyncs `build/`; a live check on a stale build is worthless):

1. **Nebula clipping first.** Load a mission with a nebula, set 4×, and look at where the cloud meets a hull. Clipping or a hard seam means the depth resolve is picking a wrong sample — the spec's risk #1. Everything else is cosmetic next to this.
2. **A/B the modes** on hull-against-black, the case SMAA was found underwhelming on. QuickBattle is fine for a static look.
3. **Fleet-scale motion**, where SMAA crawls worst: `DAUNTLESS_MISSION=engine.dev_missions.combat_stress DAUNTLESS_COMBAT_SHIPS=16`. Judge edge stability in motion, not a still frame.
4. **Frame cost at 8×** via the profiler (backtick under `--developer`). Read `docs/engine/frame-profiler.md` first — the GPU column is dead on this Mac, so `r.frame` CPU is the only number that will move.
5. **Confirm persistence** across a relaunch, and that an existing `settings.json` carrying `smaa_on` migrates to the matching `aa_mode` rather than resetting.
