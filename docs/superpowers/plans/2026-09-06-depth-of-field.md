# Targeted Depth of Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the exterior space view a lens that holds deep focus by default and racks onto a subject — the selected target, or the torpedo the camera is riding — when one exists.

**Architecture:** One new HDR pass sits between the scene and bloom, reading `g_hdr_target`'s colour and depth and writing `g_dof_target`; bloom and resolve then source from whichever of the two the pass produced. A thin-lens circle-of-confusion drives a 24-tap golden-angle gather with scatter-as-gather weighting. All focus logic is pure Python in `engine/cameras/dof.py`, pushed to the renderer as six floats per frame.

**Tech Stack:** C++17, OpenGL 4.1 core / GLSL 410, glad, glm, GoogleTest, pybind11, Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-09-06-depth-of-field-design.md`

## Global Constraints

- **Byte-identical off-path.** When no subject is focused the DOF pass must not run at all; bloom and resolve read `g_hdr_target` exactly as today. Deep focus costs nothing.
- **No look-affecting constants in C++ or GLSL.** `NEAR_STRENGTH`, `FAR_STRENGTH`, `FAR_CEILING`, `MAX_RADIUS_FRAC` live only in `engine/cameras/dof.py` and arrive as uniforms. The single permitted C++ constant is `kTapCount = 24` (kernel structure, not look).
- **Exterior only.** Gate on `!viewer_mode && !bridge_active`, the same gate filmic and motion blur use. Inert on the bridge, the comm viewscreen, the hologram / Ship Property Viewer path, and the star map.
- **Distances are game units.** Every distance variable is named `*_gu`. Never `*_m` or `*_mps`. 1 GU = 175 m.
- **Scatter-as-gather weighting is not an optimisation.** `w = clamp(tap_radius_px - dist_to_tap_px + 1.0, 0.0, 1.0)` must not be removed or "simplified".
- **Shader edits need a cmake reconfigure.** Run `cmake -B build -S .` before `cmake --build build -j` whenever a `.frag`/`.vert` changes — shaders are embedded at configure time. Shader compile errors are **runtime**, not build-time; a clean build proves nothing about `dof.frag`.
- **Never run `cmake` from inside `native/`.** One build tree only, at `<repo-root>/build/`.
- **Shared checkout.** Stage with explicit pathspecs. Never `git add -A`, `git add .`, `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, or `git reset --hard`.
- **Never launch the game.** Not even headless. Live verification is Mark's; verify shaders through `renderer_tests`.
- **Gate with `scripts/check_tests.sh`**, which builds C++ and runs pytest + ctest against `tests/known_failures.txt`. Never call a failure "pre-existing" by eyeball.
- **Commit trailer** on every commit:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `native/src/renderer/include/renderer/dof.h` | **Create.** `DofParams`, `linear_depth_gu()`, `coc_from_depth()`. Header-only, no GL. The reference implementation the shader mirrors. |
| `native/src/renderer/shaders/dof.frag` | **Create.** The gather. Mirrors `dof.h` exactly; holds no look-affecting constants. |
| `native/src/renderer/include/renderer/dof_pass.h` | **Create.** `DofPass` declaration. Mirrors `filmic_pass.h`. |
| `native/src/renderer/dof_pass.cc` | **Create.** Fullscreen-triangle pass reusing `resolve.vert`. |
| `native/tests/renderer/dof_test.cc` | **Create.** gtest over `dof.h`. No GL context needed. |
| `native/tests/renderer/dof_pass_test.cc` | **Create.** gtest over the GL pass, headless-window guarded. |
| `engine/cameras/dof.py` | **Create.** Tuning constants **and** `FocusSolver`. The one file to open when tuning. |
| `tests/unit/test_dof_focus.py` | **Create.** pytest over the solver and subject resolution. |
| `native/src/renderer/CMakeLists.txt` | Modify. Embed `dof.frag`; add `dof_pass.cc`. |
| `native/tests/renderer/CMakeLists.txt` | Modify. Register both new test files. |
| `native/src/host/host_bindings.cc` | Modify. `g_dof_target`, `g_dof_pass`, `dauntless_dof` state, frame insertion, three pybind bindings. |
| `engine/renderer.py` | Modify. Façade wrappers + `_REQUIRED_BINDINGS` entries. |
| `engine/appc/camera_modes.py` | Modify. `focus_subject()` on `CameraMode` and `TorpCameraMode`. |
| `engine/host_loop.py` | Modify. Construct the solver, push params next to `r.set_camera`, pass `set_dof` to the panel. |
| `engine/settings_store.py` | Modify. Fifth applier on the `camera_realism` fan-out. |
| `engine/ui/configuration_panel.py` | Modify. `set_dof` constructor param, `"dof"` in `MASTER_TOGGLES` and `_appliers`. |
| `engine/dev_keybindings.py` | Modify. `,` and `.` live-tuning keys. |

**No CEF/JS change is needed.** `configuration_panel.js` needs a matching row only when a *new master* is added; this adds an applier to an existing master, whose row already exists.

---

### Task 1: Circle-of-confusion math

**Files:**
- Create: `native/src/renderer/include/renderer/dof.h`
- Create: `native/tests/renderer/dof_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: `renderer::DofParams` (fields `focus_gu`, `blend`, `near_strength`, `far_strength`, `far_ceiling`, `max_radius_frac`, all `float`); `float renderer::linear_depth_gu(float d, float near_gu, float far_gu)`; `float renderer::coc_from_depth(float d, float near_gu, float far_gu, const DofParams& p)`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/dof_test.cc`:

```cpp
// native/tests/renderer/dof_test.cc
#include <gtest/gtest.h>
#include <renderer/dof.h>

namespace {

constexpr float kNear = 1.0f;
constexpr float kFar  = 5000.0f;

// Inverse of linear_depth_gu: the [0,1] depth-buffer value for a view
// distance. Lets the tests below read in game units instead of raw depth.
float depth_for_z(float z, float near_gu = kNear, float far_gu = kFar) {
    const float ndc = (far_gu + near_gu - 2.0f * near_gu * far_gu / z)
                    / (far_gu - near_gu);
    return (ndc + 1.0f) * 0.5f;
}

renderer::DofParams params_at(float focus_gu) {
    renderer::DofParams p;
    p.focus_gu        = focus_gu;
    p.blend           = 1.0f;
    p.near_strength   = 1.0f;
    p.far_strength    = 1.0f;
    p.far_ceiling     = 0.4f;
    p.max_radius_frac = 0.008f;
    return p;
}

TEST(Dof, LinearDepthSpansNearToFar) {
    EXPECT_NEAR(renderer::linear_depth_gu(0.0f, kNear, kFar), kNear, 1e-3f);
    EXPECT_NEAR(renderer::linear_depth_gu(1.0f, kNear, kFar), kFar,  1e-1f);
}

TEST(Dof, DepthForZRoundTrips) {
    for (float z : {2.0f, 25.0f, 100.0f, 900.0f}) {
        EXPECT_NEAR(renderer::linear_depth_gu(depth_for_z(z), kNear, kFar),
                    z, z * 1e-3f);
    }
}

TEST(Dof, SharpExactlyAtFocus) {
    const auto p = params_at(100.0f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(100.0f), kNear, kFar, p),
                0.0f, 1e-4f);
}

// Near field is signed negative and clamps hard at -1. At half the focus
// distance the thin-lens term is exactly -1, which is the clamp boundary.
TEST(Dof, NearFieldClampsAtMinusOne) {
    const auto p = params_at(100.0f);
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(50.0f), kNear, kFar, p),
                -1.0f, 1e-3f);
    // Closer still stays clamped, never overshoots.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(10.0f), kNear, kFar, p),
                -1.0f, 1e-3f);
}

TEST(Dof, NearFieldBelowTheClampIsProportional) {
    const auto p = params_at(100.0f);
    // z=80: 1 - 100/80 = -0.25
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(80.0f), kNear, kFar, p),
                -0.25f, 1e-3f);
}

TEST(Dof, FarFieldSaturatesAtTheCeiling) {
    const auto p = params_at(100.0f);
    // z=125: 1 - 100/125 = 0.2, below the 0.4 ceiling.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(125.0f), kNear, kFar, p),
                0.2f, 1e-3f);
    // z=200: 1 - 100/200 = 0.5, above the ceiling -> capped.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(200.0f), kNear, kFar, p),
                0.4f, 1e-3f);
    // z=2000 is far beyond, still exactly the ceiling. This is the anti-mush
    // guarantee: the far field can never blur harder than far_ceiling.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(2000.0f), kNear, kFar, p),
                0.4f, 1e-3f);
}

// The backdrop pass draws the sky with glDepthMask(GL_FALSE), so sky pixels
// never write depth and hold the clear value. Exempting them keeps the
// starfield sharp.
TEST(Dof, StarfieldIsExempt) {
    const auto p = params_at(100.0f);
    EXPECT_EQ(renderer::coc_from_depth(1.0f, kNear, kFar, p), 0.0f);
    // Just inside the 0.98*far threshold is still exempt...
    EXPECT_EQ(renderer::coc_from_depth(depth_for_z(4950.0f), kNear, kFar, p),
              0.0f);
    // ...and just outside it is not.
    EXPECT_GT(renderer::coc_from_depth(depth_for_z(4000.0f), kNear, kFar, p),
              0.0f);
}

// A zero focus distance means "no subject". Without this guard the thin-lens
// term degenerates to 1.0 and the whole frame would blur at the ceiling.
TEST(Dof, NoSubjectMeansNoBlur) {
    const auto p = params_at(0.0f);
    EXPECT_EQ(renderer::coc_from_depth(depth_for_z(100.0f), kNear, kFar, p),
              0.0f);
}

TEST(Dof, StrengthScalesBothSidesIndependently) {
    auto p = params_at(100.0f);
    p.near_strength = 0.5f;
    p.far_strength  = 0.25f;
    // z=80: -0.25 * 0.5 = -0.125
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(80.0f), kNear, kFar, p),
                -0.125f, 1e-3f);
    // z=200: 0.5 * 0.25 = 0.125, under the ceiling so uncapped.
    EXPECT_NEAR(renderer::coc_from_depth(depth_for_z(200.0f), kNear, kFar, p),
                0.125f, 1e-3f);
}

}  // namespace
```

Register it in `native/tests/renderer/CMakeLists.txt` by adding `dof_test.cc` to the `add_executable(renderer_tests ...)` source list, immediately after the `lighting_test.cc` line.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake --build build --target renderer_tests -j 2>&1 | tail -20
```

Expected: FAIL to compile — `renderer/dof.h` does not exist.

- [ ] **Step 3: Write the implementation**

Create `native/src/renderer/include/renderer/dof.h`:

```cpp
// native/src/renderer/include/renderer/dof.h
#pragma once

#include <algorithm>

namespace renderer {

/// Depth-of-field parameters, pushed whole from Python each frame.
///
/// EVERY field here is authored in engine/cameras/dof.py and arrives as a
/// uniform. There is deliberately no C++ default that means anything: the
/// values below exist only so a default-constructed DofParams is inert.
/// Adding a "tuned default" here would create a second home for a number that
/// must have exactly one -- see the spec's Tuning ergonomics section.
struct DofParams {
    float focus_gu        = 0.0f; ///< distance to the focus subject, GU
    float blend           = 0.0f; ///< 0..1 engage ramp; 0 == pass is skipped
    float near_strength   = 0.0f; ///< foreground defocus gain
    float far_strength    = 0.0f; ///< background defocus gain, pre-ceiling
    float far_ceiling     = 0.0f; ///< hard cap on far-field CoC
    float max_radius_frac = 0.0f; ///< max blur radius / screen height
};

/// Convert a [0,1] depth-buffer value to a view distance in game units.
///
/// Standard OpenGL perspective with glDepthRange left at its default. The
/// result is always in [near_gu, far_gu] for a well-formed projection.
inline float linear_depth_gu(float d, float near_gu, float far_gu) {
    const float ndc = 2.0f * d - 1.0f;
    return (2.0f * near_gu * far_gu)
         / (far_gu + near_gu - ndc * (far_gu - near_gu));
}

/// Signed circle of confusion, in [-1, far_ceiling].
///
/// Negative is the near field (between the camera and the subject), positive
/// the far field. The sign exists only so the two sides can be tuned
/// separately; the blur radius uses the magnitude.
///
/// This is a real thin lens: `1 - focus/z` is zero at the focus distance,
/// grows without bound toward the camera, and saturates at 1 as z goes to
/// infinity. That single form is why the design carries no near/far RANGE
/// constants -- focus on a 4 GU torpedo is shallow and focus on a ship 200 GU
/// out is deep, both falling out of the same expression.
///
/// MIRRORED IN shaders/dof.frag -- the two must agree. dof_pass_test.cc pins
/// the starfield threshold against this implementation; if you change the
/// curve here, change it there in the same commit.
inline float coc_from_depth(float d, float near_gu, float far_gu,
                            const DofParams& p) {
    // No subject: the thin-lens term would degenerate to 1.0 and blur the
    // whole frame at the ceiling. The host also skips the pass when blend is
    // 0, but this keeps the function itself total.
    if (p.focus_gu <= 0.0f) return 0.0f;

    const float z = linear_depth_gu(d, near_gu, far_gu);
    if (z <= 0.0f) return 0.0f;              // guard against invalid caller args

    // The backdrop pass draws the sky with glDepthMask(GL_FALSE), so sky
    // pixels never write depth and hold the clear value. Testing the
    // LINEARIZED distance rather than d >= 0.999999 keeps this correct even
    // if someone later calls glClearDepth with something other than 1.0.
    // At far=5000 the threshold is 4900 GU (857 km) -- no scene geometry is
    // ever that distant.
    if (z >= far_gu * 0.98f) return 0.0f;

    const float dd = 1.0f - p.focus_gu / z;
    return (dd < 0.0f) ? std::max(dd * p.near_strength, -1.0f)
                       : std::min(dd * p.far_strength,   p.far_ceiling);
}

}  // namespace renderer
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cmake --build build --target renderer_tests -j 2>&1 | tail -5 && ./build/native/tests/renderer/renderer_tests --gtest_filter='Dof.*' 2>&1 | tail -20
```

Expected: PASS, 9 tests. If the binary path differs, find it with `find build -name renderer_tests -type f`.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/dof.h \
        native/tests/renderer/dof_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "$(cat <<'EOF'
feat(renderer): add thin-lens circle-of-confusion math for DOF

A real thin lens in one division: 1 - focus/z is zero at the focus
distance, grows without bound toward the camera and saturates at
infinity. That form is why the design needs no near/far range constants
-- focus on a 4 GU torpedo is shallow and focus on a ship 200 GU out is
deep, both from the same expression.

The starfield exemption tests the linearized distance rather than a raw
depth near 1.0, so it survives someone changing the depth clear value.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The DOF pass and its shader

**Files:**
- Create: `native/src/renderer/shaders/dof.frag`
- Create: `native/src/renderer/include/renderer/dof_pass.h`
- Create: `native/src/renderer/dof_pass.cc`
- Create: `native/tests/renderer/dof_pass_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: `renderer::DofParams`, `renderer::coc_from_depth` from `renderer/dof.h` (Task 1).
- Produces: `renderer::DofPass` with
  `void draw(std::uint32_t src_tex, std::uint32_t depth_tex, std::uint32_t dest_fbo, int fw, int fh, float near_gu, float far_gu, const DofParams& p)`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/dof_pass_test.cc`:

```cpp
// native/tests/renderer/dof_pass_test.cc
//
// The GL half of DOF. These tests pin BEHAVIOUR that is observable through
// the framebuffer -- they cannot read the shader's CoC directly, so the
// anti-drift guard is the starfield-threshold pair at the bottom: it forces
// the shader's exemption to agree with dof.h's at the one depth where the
// two could silently diverge.
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/dof.h>
#include <renderer/dof_pass.h>
#include <renderer/hdr_target.h>
#include <renderer/window.h>
#include <memory>
#include <vector>

namespace {

constexpr int   kSize = 64;
constexpr float kNear = 1.0f;
constexpr float kFar  = 5000.0f;

float depth_for_z(float z) {
    const float ndc = (kFar + kNear - 2.0f * kNear * kFar / z) / (kFar - kNear);
    return (ndc + 1.0f) * 0.5f;
}

class DofPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(kSize, kSize, "dof-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }

    /// Fill an HdrTarget with a vertical split (left half black, right half
    /// white) at a uniform depth. The step edge is what a blur visibly softens.
    void fill_step_edge(renderer::HdrTarget& t, float depth) {
        t.resize(kSize, kSize);
        t.bind();
        glEnable(GL_SCISSOR_TEST);
        glClearDepth(static_cast<double>(depth));

        glScissor(0, 0, kSize / 2, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glScissor(kSize / 2, 0, kSize / 2, kSize);
        glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        glDisable(GL_SCISSOR_TEST);
        glClearDepth(1.0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }

    /// Read the row of pixels straddling the step edge.
    std::vector<float> read_edge_row(const renderer::HdrTarget& t) {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, t.fbo());
        std::vector<float> px(kSize * 4);
        glReadPixels(0, kSize / 2, kSize, 1, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::vector<float> row(kSize);
        for (int i = 0; i < kSize; ++i) row[i] = px[i * 4];
        return row;
    }

    /// How many pixels along the row sit strictly between black and white.
    /// A sharp step has none; a blurred one has a band.
    int transition_width(const std::vector<float>& row) {
        int n = 0;
        for (float v : row) if (v > 0.02f && v < 0.98f) ++n;
        return n;
    }

    renderer::DofParams params_at(float focus_gu, float blend = 1.0f) {
        renderer::DofParams p;
        p.focus_gu        = focus_gu;
        p.blend           = blend;
        p.near_strength   = 1.0f;
        p.far_strength    = 1.0f;
        p.far_ceiling     = 0.4f;
        p.max_radius_frac = 0.05f;   // exaggerated so the blur is unmistakable
        return p;
    }
};

// Geometry sitting exactly at the focus distance has CoC 0, so the pass is an
// identity. This is the guarantee that an in-focus subject stays crisp.
TEST_F(DofPassTest, AtFocusThePassIsIdentity) {
    renderer::HdrTarget src, dst;
    fill_step_edge(src, depth_for_z(100.0f));
    dst.resize(kSize, kSize);

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, params_at(100.0f));

    EXPECT_EQ(transition_width(read_edge_row(dst)), 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Geometry well beyond the focus distance defocuses, softening the step.
TEST_F(DofPassTest, FarFieldSoftensAStepEdge) {
    renderer::HdrTarget src, dst;
    fill_step_edge(src, depth_for_z(500.0f));   // focus at 100 -> far field
    dst.resize(kSize, kSize);

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, params_at(100.0f));

    EXPECT_GT(transition_width(read_edge_row(dst)), 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// blend == 0 means "no subject focused". Even if the host were to run the
// pass anyway, the image must come through untouched.
TEST_F(DofPassTest, ZeroBlendIsIdentity) {
    renderer::HdrTarget src, dst;
    fill_step_edge(src, depth_for_z(500.0f));
    dst.resize(kSize, kSize);

    renderer::DofPass pass;
    pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
              kSize, kSize, kNear, kFar, params_at(100.0f, /*blend=*/0.0f));

    EXPECT_EQ(transition_width(read_edge_row(dst)), 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// ANTI-DRIFT GUARD. dof.h and dof.frag hold the same CoC curve in two
// languages; nothing makes them agree automatically. These two cases
// bracket the starfield threshold, so a change to one file's exemption
// without the other turns one of them red.
TEST_F(DofPassTest, StarfieldThresholdAgreesWithTheCppReference) {
    const auto p = params_at(100.0f);

    // Inside the exemption: dof.h says CoC 0, so the shader must be identity.
    ASSERT_EQ(renderer::coc_from_depth(depth_for_z(4950.0f), kNear, kFar, p), 0.0f);
    {
        renderer::HdrTarget src, dst;
        fill_step_edge(src, depth_for_z(4950.0f));
        dst.resize(kSize, kSize);
        renderer::DofPass pass;
        pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
                  kSize, kSize, kNear, kFar, p);
        EXPECT_EQ(transition_width(read_edge_row(dst)), 0)
            << "shader blurred a depth dof.h exempts";
    }

    // Outside it: dof.h says nonzero, so the shader must blur.
    ASSERT_GT(renderer::coc_from_depth(depth_for_z(4000.0f), kNear, kFar, p), 0.0f);
    {
        renderer::HdrTarget src, dst;
        fill_step_edge(src, depth_for_z(4000.0f));
        dst.resize(kSize, kSize);
        renderer::DofPass pass;
        pass.draw(src.color_texture(), src.depth_texture(), dst.fbo(),
                  kSize, kSize, kNear, kFar, p);
        EXPECT_GT(transition_width(read_edge_row(dst)), 0)
            << "shader left sharp a depth dof.h blurs";
    }
}

}  // namespace
```

Register it in `native/tests/renderer/CMakeLists.txt` by adding `dof_pass_test.cc` to the `add_executable(renderer_tests ...)` list, immediately after the `dof_test.cc` line added in Task 1.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake -B build -S . >/dev/null && cmake --build build --target renderer_tests -j 2>&1 | tail -20
```

Expected: FAIL to compile — `renderer/dof_pass.h` does not exist.

- [ ] **Step 3: Write the shader**

Create `native/src/renderer/shaders/dof.frag`:

```glsl
#version 410 core
//
// Depth of field: a thin-lens circle of confusion driving a 24-tap
// golden-angle gather, run in HDR before the tonemap so defocused highlights
// stay bright and become real bokeh rather than grey smudges.
//
// The CoC block below MIRRORS renderer/dof.h. The two must agree; the
// starfield threshold is pinned across both by dof_pass_test.cc. If you
// change the curve here, change it there in the same commit.
//
// NO look-affecting constant lives in this file. Everything an artist would
// want to touch arrives as a uniform from engine/cameras/dof.py, so tuning
// needs no rebuild. kTapCount is kernel structure, not look.

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_src;             // HDR scene colour
uniform sampler2D u_depth;           // scene depth, same dimensions
uniform float u_near;
uniform float u_far;
uniform float u_focus_gu;
uniform float u_blend;               // 0..1 engage ramp
uniform float u_near_strength;
uniform float u_far_strength;
uniform float u_far_ceiling;
uniform float u_max_radius_px;       // already frac * framebuffer height
uniform vec2  u_texel;               // 1.0 / textureSize(u_src, 0)

const int   kTapCount   = 24;
const float kGoldenAngle = 2.39996323;   // radians

float linear_depth_gu(float d) {
    float ndc = 2.0 * d - 1.0;
    return (2.0 * u_near * u_far) / (u_far + u_near - ndc * (u_far - u_near));
}

float coc_at(vec2 uv) {
    if (u_focus_gu <= 0.0) return 0.0;
    float z = linear_depth_gu(texture(u_depth, uv).r);
    if (z <= 0.0) return 0.0;
    // Starfield: the backdrop pass never writes depth, so these pixels hold
    // the clear value. Tested on the linearized distance so the exemption
    // does not depend on the exact clear value.
    if (z >= u_far * 0.98) return 0.0;
    float dd = 1.0 - u_focus_gu / z;
    return (dd < 0.0) ? max(dd * u_near_strength, -1.0)
                      : min(dd * u_far_strength,  u_far_ceiling);
}

void main() {
    vec3  center     = texture(u_src, v_uv).rgb;
    float center_r   = abs(coc_at(v_uv)) * u_max_radius_px * u_blend;

    // Sub-pixel circle of confusion: nothing to gather. This early-out is
    // what makes an in-focus subject bit-for-bit sharp rather than merely
    // nearly sharp, and it is the fast path for most of the frame.
    if (center_r < 0.5) { frag_color = vec4(center, 1.0); return; }

    vec3  acc  = center;
    float wsum = 1.0;

    for (int i = 0; i < kTapCount; ++i) {
        // Vogel spiral: sqrt(t) radial spacing with the golden angle gives a
        // uniform distribution over the disc, so the bokeh is even rather
        // than centre-heavy.
        float t   = (float(i) + 0.5) / float(kTapCount);
        float r   = center_r * sqrt(t);
        float ang = float(i) * kGoldenAngle;
        vec2  uv  = v_uv + vec2(cos(ang), sin(ang)) * r * u_texel;

        float tap_r = abs(coc_at(uv)) * u_max_radius_px * u_blend;

        // SCATTER-AS-GATHER. A tap contributes only if ITS OWN circle of
        // confusion reaches this pixel. Without this, sharp foreground
        // objects bleed onto in-focus background and in-focus objects have
        // their edges eaten -- the two classic cheap-DOF tells. This is a
        // correctness term, NOT an optimisation: do not remove it.
        float w = clamp(tap_r - r + 1.0, 0.0, 1.0);

        acc  += texture(u_src, uv).rgb * w;
        wsum += w;
    }

    frag_color = vec4(acc / wsum, 1.0);
}
```

- [ ] **Step 4: Write the pass header**

Create `native/src/renderer/include/renderer/dof_pass.h`:

```cpp
// native/src/renderer/include/renderer/dof_pass.h
#pragma once
#include <cstdint>
#include <memory>
#include <renderer/dof.h>
#include <renderer/shader.h>

namespace renderer {

/// Depth of field over an HDR scene colour + depth pair.
///
/// Runs BEFORE bloom and the tonemap, unlike every other post pass here: a
/// defocused highlight has to still be bright when it spreads, or it reads as
/// a grey smudge instead of bokeh. Reuses the fullscreen-triangle vertex
/// shader (resolve.vert), as FilmicPass does.
///
/// Exterior space view only. The caller is expected to skip the pass entirely
/// when no subject is focused, which keeps the default deep-focus frame
/// byte-identical to the pre-DOF renderer.
class DofPass {
public:
    DofPass();
    ~DofPass();
    DofPass(const DofPass&) = delete;
    DofPass& operator=(const DofPass&) = delete;

    /// Draw a fullscreen triangle sampling `src_tex` (HDR colour) and
    /// `depth_tex` (the same target's depth) into `dest_fbo`, viewport
    /// `fw`x`fh`. `near_gu`/`far_gu` are the camera planes, needed to
    /// linearize depth. Disables cull/depth/blend and restores them.
    void draw(std::uint32_t src_tex, std::uint32_t depth_tex,
              std::uint32_t dest_fbo, int fw, int fh,
              float near_gu, float far_gu, const DofParams& p);

private:
    std::unique_ptr<renderer::Shader> shader_;
    std::uint32_t vao_ = 0, vbo_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 5: Write the pass implementation**

Create `native/src/renderer/dof_pass.cc`:

```cpp
// native/src/renderer/dof_pass.cc
//
// Fullscreen-triangle depth-of-field over an HDR colour + depth pair.
// Reuses resolve.vert.

#include <renderer/dof_pass.h>

#include <glad/glad.h>

#include "embedded_resolve_vs.h"
#include "embedded_dof_fs.h"

namespace renderer {

DofPass::DofPass()
    : shader_(std::make_unique<renderer::Shader>(
          shader_src::resolve_vs, shader_src::dof_fs)) {
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

DofPass::~DofPass() {
    if (vbo_) glDeleteBuffers(1,      &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void DofPass::draw(std::uint32_t src_tex, std::uint32_t depth_tex,
                   std::uint32_t dest_fbo, int fw, int fh,
                   float near_gu, float far_gu, const DofParams& p) {
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
    shader_->set_int("u_src",   0);
    shader_->set_int("u_depth", 1);
    shader_->set_float("u_near",          near_gu);
    shader_->set_float("u_far",           far_gu);
    shader_->set_float("u_focus_gu",      p.focus_gu);
    shader_->set_float("u_blend",         p.blend);
    shader_->set_float("u_near_strength", p.near_strength);
    shader_->set_float("u_far_strength",  p.far_strength);
    shader_->set_float("u_far_ceiling",   p.far_ceiling);
    // The radius is authored as a fraction of screen HEIGHT so it is
    // resolution-independent; converting here keeps the framebuffer size out
    // of the shader.
    shader_->set_float("u_max_radius_px",
                       p.max_radius_frac * static_cast<float>(fh));
    shader_->set_vec2("u_texel",
                      glm::vec2(1.0f / static_cast<float>(fw),
                                1.0f / static_cast<float>(fh)));

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, src_tex);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, depth_tex);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    glUseProgram(0);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);

    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (prev_blend)      glEnable(GL_BLEND);
}

}  // namespace renderer
```

`Shader::set_vec2` is declared `void set_vec2(const std::string& name, const glm::vec2& v) const` (`native/src/renderer/include/renderer/shader.h:25`) — it takes a `glm::vec2`, not two floats. Add `#include <glm/glm.hpp>` to `dof_pass.cc` if the transitive include from `dof.h` is not enough.

- [ ] **Step 6: Register the shader and source in CMake**

In `native/src/renderer/CMakeLists.txt`, add after the `SHADER_MOTION_BLUR_FS` line (~:106):

```cmake
embed_shader(SHADER_DOF_FS shaders/dof.frag dof_fs)
```

and add `dof_pass.cc` to the renderer source list, immediately after the `motion_blur_pass.cc` line (~:149).

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cmake -B build -S . >/dev/null && cmake --build build --target renderer_tests -j 2>&1 | tail -5 && ./build/native/tests/renderer/renderer_tests --gtest_filter='Dof*' 2>&1 | tail -25
```

Expected: PASS. Both `Dof.*` (9) and `DofPassTest.*` (4). If `DofPassTest` reports SKIPPED, no GL context is available in this environment — that is acceptable for the headless gate but means the shader is unverified, so say so explicitly in the task report rather than claiming the pass works.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/shaders/dof.frag \
        native/src/renderer/include/renderer/dof_pass.h \
        native/src/renderer/dof_pass.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/dof_pass_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "$(cat <<'EOF'
feat(renderer): add the depth-of-field gather pass

A 24-tap Vogel spiral weighted scatter-as-gather: a tap contributes only
if its own circle of confusion reaches the pixel. That term is what stops
sharp foreground bleeding onto in-focus background and in-focus edges
being eaten -- the two classic cheap-DOF tells.

The shader holds no look-affecting constant; all six arrive as uniforms
so tuning never needs a rebuild. dof.h and dof.frag mirror the same CoC
curve in two languages, so the test brackets the starfield threshold
across both to catch them drifting apart.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Host wiring and Python bindings

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`

**Interfaces:**
- Consumes: `renderer::DofPass`, `renderer::DofParams` (Task 2).
- Produces: pybind bindings `dof_set_enabled(bool)`, `dof_enabled() -> bool`, `dof_set_params(focus_gu, blend, near_strength, far_strength, far_ceiling, max_radius_frac)`; and Python façade `engine.renderer.set_dof_enabled(bool)`, `engine.renderer.dof_enabled() -> bool`, `engine.renderer.set_dof_params(focus_gu, blend, near_strength, far_strength, far_ceiling, max_radius_frac)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_renderer_binding_manifest.py`'s expectations implicitly — that test derives ground truth from `engine/renderer.py` itself, so it needs no edit. Instead write the behaviour test. Create `tests/unit/test_dof_bindings.py`:

```python
"""The DOF façade must be manifest-complete and must not crash headless.

engine/renderer.py's wrappers are no-ops when the extension module is absent
(unit tests, headless import contexts) and hard calls when it is present. Both
paths are exercised here so a missing binding shows up as a red test rather
than a silently dead feature at runtime.
"""
import engine.renderer as r


def test_dof_bindings_are_in_the_required_manifest():
    for name in ("dof_set_enabled", "dof_enabled", "dof_set_params"):
        assert name in r._REQUIRED_BINDINGS, (
            f"{name} missing from _REQUIRED_BINDINGS -- validate_bindings() "
            "would not catch a stale build that dropped it"
        )


def test_set_dof_params_forwards_every_field(monkeypatch):
    seen = {}

    class _FakeHost:
        def dof_set_params(self, *args):
            seen["args"] = args

    monkeypatch.setattr(r, "_h", _FakeHost())
    r.set_dof_params(120.0, 0.5, 1.0, 1.0, 0.4, 0.008)

    assert seen["args"] == (120.0, 0.5, 1.0, 1.0, 0.4, 0.008)


def test_set_dof_enabled_coerces_to_bool(monkeypatch):
    seen = {}

    class _FakeHost:
        def dof_set_enabled(self, v):
            seen["v"] = v

    monkeypatch.setattr(r, "_h", _FakeHost())
    r.set_dof_enabled(1)

    assert seen["v"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_dof_bindings.py -v 2>&1 | tail -20
```

Expected: FAIL — `_REQUIRED_BINDINGS` has no DOF entries and `set_dof_params` does not exist.

- [ ] **Step 3: Add the C++ state, pass, and bindings**

In `native/src/host/host_bindings.cc`:

**3a.** Add the include beside the other pass includes (~:71):

```cpp
#include <renderer/dof_pass.h>
```

**3b.** Add a state namespace beside `dauntless_motion_blur` (~:154):

```cpp
// Depth-of-field state. `enabled` is the Camera Realism master; `params`
// arrives whole from Python each frame. Deliberately no tuned defaults here
// -- engine/cameras/dof.py is the single home for every look-affecting
// number, so that tuning needs no rebuild.
namespace dauntless_dof {
namespace {
bool                 g_enabled = true;
renderer::DofParams  g_params;
}
bool enabled() { return g_enabled; }
void set_enabled(bool e) { g_enabled = e; }
const renderer::DofParams& params() { return g_params; }
void set_params(const renderer::DofParams& p) { g_params = p; }
}  // namespace dauntless_dof
```

**3c.** Add globals beside `g_motion_blur_pass` (~:329):

```cpp
std::unique_ptr<renderer::DofPass>    g_dof_pass;
std::unique_ptr<renderer::HdrTarget>  g_dof_target;
```

**3d.** Construct them in init beside `g_motion_blur_pass` (~:637):

```cpp
g_dof_pass   = std::make_unique<renderer::DofPass>();
g_dof_target = std::make_unique<renderer::HdrTarget>();
```

**3e.** Reset them in shutdown beside `g_motion_blur_pass.reset()` (~:693):

```cpp
g_dof_target.reset();
g_dof_pass.reset();
```

**3f.** Move the `exterior` declaration up. Delete this line from ~:1304:

```cpp
    const bool exterior = !viewer_mode && !bridge_active;
```

and insert it immediately before the bloom block (~:1290, just above the `// bloom_tex is set to the HDR color texture...` comment), together with the DOF block:

```cpp
    const bool exterior = !viewer_mode && !bridge_active;

    // Depth of field. Runs in HDR BEFORE bloom, which is the whole point: a
    // defocused nav light has to still be bright when it spreads, or it reads
    // as a grey smudge rather than bokeh. Physically it is also the right
    // order -- lens defocus happens before the sensor.
    //
    // Skipped entirely unless a subject is actually focused (blend > 0), so
    // the default deep-focus frame is byte-identical to the pre-DOF renderer:
    // bloom and resolve read g_hdr_target exactly as they always did.
    std::uint32_t scene_tex = g_hdr_target->color_texture();
    const bool dof_on = dauntless_dof::enabled()
                        && dauntless_dof::params().blend > 0.0f
                        && exterior
                        && g_dof_pass && g_dof_target;
    if (dof_on) {
        DAUNTLESS_FRAME_SCOPE("dof");
        g_dof_target->resize(fw, fh);
        g_dof_pass->draw(g_hdr_target->color_texture(),
                         g_hdr_target->depth_texture(),
                         g_dof_target->fbo(), fw, fh,
                         g_camera.near, g_camera.far,
                         dauntless_dof::params());
        scene_tex = g_dof_target->color_texture();
    }
```

**3g.** Point the downstream consumers at `scene_tex`. Four sites, all inside the same function:

- `std::uint32_t bloom_tex = g_hdr_target->color_texture();` → `= scene_tex;`
- `bloom_tex = g_bloom_pass->render(g_hdr_target->color_texture(), fw, fh);` → `render(scene_tex, fw, fh)`
- `std::uint32_t lens_flare_tex = g_hdr_target->color_texture();` → `= scene_tex;`
- `g_resolve_pass->draw(g_hdr_target->color_texture(), bloom_tex, lens_flare_tex);` → `draw(scene_tex, bloom_tex, lens_flare_tex)`

**3h.** Add the three bindings beside `motion_blur_set_enabled` (~:3549):

```cpp
    m.def("dof_set_enabled",
          [](bool enabled) { dauntless_dof::set_enabled(enabled); },
          "Toggle depth of field (the Camera Realism master). Default: on. "
          "Off means the pass never runs, whatever params say.");
    m.def("dof_enabled",
          []() { return dauntless_dof::enabled(); },
          "Whether depth of field is enabled.");
    m.def("dof_set_params",
          [](float focus_gu, float blend, float near_strength,
             float far_strength, float far_ceiling, float max_radius_frac) {
              renderer::DofParams p;
              p.focus_gu        = focus_gu;
              p.blend           = blend;
              p.near_strength   = near_strength;
              p.far_strength    = far_strength;
              p.far_ceiling     = far_ceiling;
              p.max_radius_frac = max_radius_frac;
              dauntless_dof::set_params(p);
          },
          "Push the whole DOF parameter set for this frame. blend <= 0 means "
          "no subject is focused and the pass is skipped entirely. Every "
          "value is authored in engine/cameras/dof.py -- there is no C++ "
          "default that means anything.");
```

- [ ] **Step 4: Add the Python façade**

In `engine/renderer.py`, add to `_REQUIRED_BINDINGS` (keeping rough alphabetical order, beside `destroy_instance` / `dust_set_density`):

```python
    "dof_enabled", "dof_set_enabled", "dof_set_params",
```

and add the wrappers beside `set_msaa_samples`:

```python
def set_dof_enabled(enabled: bool) -> None:
    """Depth of field on/off, for the Camera Realism master.

    Off means the pass never runs. On is not enough on its own: the pass also
    needs a focused subject (blend > 0 via set_dof_params), so the default
    deep-focus frame stays byte-identical to the pre-DOF renderer.
    """
    _h.dof_set_enabled(bool(enabled))


def dof_enabled() -> bool:
    """Whether depth of field is enabled."""
    return bool(_h.dof_enabled())


def set_dof_params(focus_gu: float, blend: float,
                   near_strength: float, far_strength: float,
                   far_ceiling: float, max_radius_frac: float) -> None:
    """Push this frame's DOF parameters.

    `focus_gu` is the camera-to-subject distance in game units and `blend` the
    0..1 engage ramp; both come from engine.cameras.dof.FocusSolver. The other
    four are lens shape, authored as module constants in that same file so
    retuning them after a live look needs no rebuild.
    """
    _h.dof_set_params(float(focus_gu), float(blend),
                      float(near_strength), float(far_strength),
                      float(far_ceiling), float(max_radius_frac))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cmake -B build -S . >/dev/null && cmake --build build -j 2>&1 | tail -5 \
  && uv run pytest tests/unit/test_dof_bindings.py tests/unit/test_renderer_binding_manifest.py -v 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py tests/unit/test_dof_bindings.py
git commit -m "$(cat <<'EOF'
feat(renderer): wire the DOF pass into the frame

The pass sits between the scene and bloom, the one gap where the
full-precision image and the depth buffer are both still alive. Bloom and
resolve now read a scene_tex that is the DOF output when it ran and
g_hdr_target when it did not, so the deep-focus default is byte-identical
to the pre-DOF frame rather than merely close to it.

`exterior` moves above the bloom block because the DOF gate needs it;
the later duplicate is removed rather than a second copy added.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The focus solver

**Files:**
- Create: `engine/cameras/dof.py`
- Create: `tests/unit/test_dof_focus.py`
- Modify: `engine/appc/camera_modes.py`

**Interfaces:**
- Consumes: `engine.renderer.set_dof_params` (Task 3) — not called here, but the field order must match.
- Produces:
  - module constants `NEAR_STRENGTH`, `FAR_STRENGTH`, `FAR_CEILING`, `MAX_RADIUS_FRAC`, `RACK_TAU_S`, `BLEND_TAU_S`
  - `focus_subject(player, camera_mode=None)` → the subject object or `None`
  - `subject_distance_gu(eye, subject)` → `float` or `None`
  - `FocusSolver` with `update(subject_distance_gu, dt)`, properties `focus_gu` / `blend`, attributes `near_strength` / `far_strength` / `far_ceiling` / `max_radius_frac`, and `nudge_strength(delta)` → `(near, far)`
  - `CameraMode.focus_subject()` → `None`; `TorpCameraMode.focus_subject()` → the latched torpedo or `None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dof_focus.py`:

```python
"""Focus control for depth of field.

The solver is deliberately pure Python with no GL dependency: every rule that
decides WHAT is in focus and how the lens gets there is testable headlessly.
"""
import math

import pytest

from engine.cameras import dof


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Obj:
    def __init__(self, x, y, z):
        self._p = _Pt(x, y, z)

    def GetWorldLocation(self):
        return self._p


class _Player:
    def __init__(self, target=None):
        self._t = target

    def GetTarget(self):
        return self._t


class _ModeWithSubject:
    def __init__(self, subject):
        self._s = subject

    def focus_subject(self):
        return self._s


# ── subject selection ────────────────────────────────────────────────────

def test_no_player_and_no_mode_means_no_subject():
    assert dof.focus_subject(None, None) is None


def test_falls_back_to_the_players_target():
    tgt = _Obj(0, 0, 0)
    assert dof.focus_subject(_Player(tgt), None) is tgt


def test_camera_mode_subject_beats_the_players_target():
    tgt, torp = _Obj(0, 0, 0), _Obj(1, 1, 1)
    assert dof.focus_subject(_Player(tgt), _ModeWithSubject(torp)) is torp


def test_camera_mode_with_no_subject_falls_through_to_the_target():
    tgt = _Obj(0, 0, 0)
    assert dof.focus_subject(_Player(tgt), _ModeWithSubject(None)) is tgt


def test_camera_mode_without_the_hook_is_tolerated():
    """Most camera modes will never grow a focus_subject(); their absence must
    fall through rather than raise."""
    class _Bare:
        pass

    tgt = _Obj(0, 0, 0)
    assert dof.focus_subject(_Player(tgt), _Bare()) is tgt


def test_no_target_means_no_subject():
    assert dof.focus_subject(_Player(None), None) is None


# ── distance ─────────────────────────────────────────────────────────────

def test_subject_distance_is_euclidean_in_game_units():
    d = dof.subject_distance_gu((0.0, 0.0, 0.0), _Obj(3.0, 4.0, 0.0))
    assert d == pytest.approx(5.0)


def test_subject_distance_of_nothing_is_none():
    assert dof.subject_distance_gu((0.0, 0.0, 0.0), None) is None


# ── the solver ───────────────────────────────────────────────────────────

def test_starts_disengaged():
    s = dof.FocusSolver()
    assert s.blend == 0.0
    assert s.focus_gu == 0.0


def test_first_acquisition_snaps_the_distance_but_ramps_the_blend():
    """A rack from nowhere would swing the lens wildly the moment a target is
    selected. The distance snaps; only the engage ramp is eased."""
    s = dof.FocusSolver()
    s.update(120.0, 1.0 / 60.0)
    assert s.focus_gu == pytest.approx(120.0)
    assert 0.0 < s.blend < 1.0


def test_blend_ramps_to_one_while_a_subject_is_held():
    s = dof.FocusSolver()
    for _ in range(240):
        s.update(120.0, 1.0 / 60.0)
    assert s.blend == pytest.approx(1.0, abs=1e-3)


def test_rack_eases_in_dioptres_not_distance():
    """A real focus pull moves the barrel in 1/distance. Easing linear
    distance would make a rack from 20 GU to 400 GU take visibly longer than
    the reverse; in dioptres the two are symmetric."""
    dt, tau = 0.05, dof.RACK_TAU_S

    out = dof.FocusSolver()
    out.update(20.0, dt)          # snap to 20
    out.update(400.0, dt)         # one eased step outward

    back = dof.FocusSolver()
    back.update(400.0, dt)        # snap to 400
    back.update(20.0, dt)         # one eased step inward

    a = 1.0 - math.exp(-dt / tau)
    expect_out  = 1.0 / (1.0 / 20.0 + (1.0 / 400.0 - 1.0 / 20.0) * a)
    expect_back = 1.0 / (1.0 / 400.0 + (1.0 / 20.0 - 1.0 / 400.0) * a)

    assert out.focus_gu == pytest.approx(expect_out, rel=1e-6)
    assert back.focus_gu == pytest.approx(expect_back, rel=1e-6)


def test_losing_the_subject_ramps_blend_down_not_snaps():
    s = dof.FocusSolver()
    for _ in range(240):
        s.update(120.0, 1.0 / 60.0)
    s.update(None, 1.0 / 60.0)
    assert 0.0 < s.blend < 1.0


def test_blend_reaches_exactly_zero_so_the_pass_can_be_skipped():
    """The host skips the pass on blend <= 0. An asymptote that never quite
    reaches zero would leave it running forever at an invisible strength."""
    s = dof.FocusSolver()
    for _ in range(240):
        s.update(120.0, 1.0 / 60.0)
    for _ in range(600):
        s.update(None, 1.0 / 60.0)
    assert s.blend == 0.0
    assert s.focus_gu == 0.0


def test_a_degenerate_distance_is_treated_as_no_subject():
    s = dof.FocusSolver()
    s.update(0.0, 1.0 / 60.0)
    assert s.blend == 0.0
    s.update(-5.0, 1.0 / 60.0)
    assert s.blend == 0.0


def test_solver_seeds_its_lens_values_from_the_module_defaults():
    s = dof.FocusSolver()
    assert s.near_strength == dof.NEAR_STRENGTH
    assert s.far_strength == dof.FAR_STRENGTH
    assert s.far_ceiling == dof.FAR_CEILING
    assert s.max_radius_frac == dof.MAX_RADIUS_FRAC


def test_nudge_moves_both_strengths_and_never_writes_back_to_the_module():
    s = dof.FocusSolver()
    before = dof.NEAR_STRENGTH
    near, far = s.nudge_strength(0.1)
    assert near == pytest.approx(before + 0.1)
    assert far == pytest.approx(dof.FAR_STRENGTH + 0.1)
    assert dof.NEAR_STRENGTH == before, "nudge must be per-session, not global"


def test_nudge_clamps_at_both_ends():
    s = dof.FocusSolver()
    for _ in range(100):
        s.nudge_strength(1.0)
    assert s.near_strength == dof.STRENGTH_MAX
    for _ in range(100):
        s.nudge_strength(-1.0)
    assert s.near_strength == dof.STRENGTH_MIN


def test_zero_dt_does_not_divide_by_zero():
    s = dof.FocusSolver()
    s.update(120.0, 0.0)
    assert s.focus_gu == pytest.approx(120.0)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_dof_focus.py -v 2>&1 | tail -20
```

Expected: FAIL — `engine.cameras.dof` does not exist.

- [ ] **Step 3: Write the solver**

Create `engine/cameras/dof.py`:

```python
"""Depth-of-field focus control — and the ONE home for every DOF tuning value.

Deep focus is the default: with no subject the solver reports blend 0 and the
host skips the DOF pass entirely, so the frame is byte-identical to the
pre-DOF renderer. Focus exists only when something has deliberately been
focused on, which is what keeps DOF a directorial signal rather than a blanket
filter that would fight readability.

TUNING. The four lens constants below are pushed to the shader as uniforms, so
editing them needs NO REBUILD -- change the number, relaunch, look. Under
--developer the ',' and '.' keys nudge the strengths live (see
engine/dev_keybindings.py) and print the result to stderr, so a value can be
found in one session rather than three rebuild-and-relaunch rounds.

Spec: docs/superpowers/specs/2026-09-06-depth-of-field-design.md
"""
import math

# ── Lens shape — pushed to the shader as uniforms ────────────────────────
# Deliberately conservative. Expect to calibrate UP and then back down after a
# live look, the way the directional ambient gradient went 0.6 -> 1.0 -> 0.8.
NEAR_STRENGTH = 1.0      # foreground defocus gain
FAR_STRENGTH = 1.0       # background defocus gain, before the ceiling
FAR_CEILING = 0.4        # hard cap on far-field CoC -- the anti-mush knob
MAX_RADIUS_FRAC = 0.008  # max blur radius as a fraction of screen height

# ── Focus behaviour — consumed here, never reaches the shader ────────────
RACK_TAU_S = 0.35        # focus-pull time constant
BLEND_TAU_S = 0.25       # engage/release ramp

# Bounds for the live dev nudge.
STRENGTH_MIN = 0.0
STRENGTH_MAX = 3.0

# Below this the blend is snapped to exactly 0 so the host can skip the pass.
# An exponential ease is asymptotic and would otherwise leave DOF running
# forever at an invisible strength.
_BLEND_EPSILON = 1e-3

# A subject closer than this is treated as no subject: the thin-lens term
# degenerates as focus approaches the near plane.
MIN_FOCUS_GU = 0.5


def _ease(current, target, dt, tau):
    """Frame-rate-independent exponential approach to `target`."""
    if tau <= 0.0 or dt <= 0.0:
        return target
    return current + (target - current) * (1.0 - math.exp(-dt / tau))


def focus_subject(player, camera_mode=None):
    """The object the lens should focus on, or None for deep focus.

    Priority: the active camera mode names its own subject (only TorpCameraMode
    does, returning the torpedo it is riding), otherwise the player's selected
    target, otherwise nothing. The hook is optional -- most modes will never
    grow one -- so its absence falls through rather than raising.
    """
    if camera_mode is not None:
        hook = getattr(camera_mode, "focus_subject", None)
        if callable(hook):
            subject = hook()
            if subject is not None:
                return subject
    if player is not None:
        get_target = getattr(player, "GetTarget", None)
        if callable(get_target):
            return get_target()
    return None


def subject_distance_gu(eye, subject):
    """Distance in game units from the camera to `subject`, or None.

    Both ships and torpedoes expose GetWorldLocation(); anything that does not
    is treated as unfocusable rather than raising, because a focus failure must
    never take the frame down.
    """
    if subject is None:
        return None
    get_loc = getattr(subject, "GetWorldLocation", None)
    if not callable(get_loc):
        return None
    p = get_loc()
    if p is None:
        return None
    dx = p.x - eye[0]
    dy = p.y - eye[1]
    dz = p.z - eye[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


class FocusSolver:
    """Eases the lens toward the current subject and reports the pass's params.

    Lens values are seeded from the module constants and held per instance, so
    a live dev nudge is per-session and never writes back to the module.
    """

    def __init__(self):
        self.near_strength = NEAR_STRENGTH
        self.far_strength = FAR_STRENGTH
        self.far_ceiling = FAR_CEILING
        self.max_radius_frac = MAX_RADIUS_FRAC
        # Held as a dioptre (1/distance); 0 means "not focused on anything".
        self._inv_focus = 0.0
        self._blend = 0.0

    @property
    def focus_gu(self):
        """Current focus distance in game units; 0.0 when disengaged."""
        return (1.0 / self._inv_focus) if self._inv_focus > 0.0 else 0.0

    @property
    def blend(self):
        """0..1 engage ramp. Exactly 0 means the host skips the pass."""
        return self._blend

    def update(self, distance_gu, dt):
        """Advance one frame toward `distance_gu` (None = deep focus)."""
        if distance_gu is not None and distance_gu > MIN_FOCUS_GU:
            target_inv = 1.0 / distance_gu
            if self._inv_focus <= 0.0:
                # First acquisition SNAPS the distance. Racking from nowhere
                # would swing the lens wildly the moment a target is selected;
                # what should ease in is the engagement, not the distance.
                self._inv_focus = target_inv
            else:
                # Eased in DIOPTRES, not distance. A real focus pull moves the
                # barrel in 1/distance, and easing linear distance would make a
                # rack outward take visibly longer than the same rack inward.
                self._inv_focus = _ease(self._inv_focus, target_inv,
                                        dt, RACK_TAU_S)
            self._blend = _ease(self._blend, 1.0, dt, BLEND_TAU_S)
        else:
            self._blend = _ease(self._blend, 0.0, dt, BLEND_TAU_S)
            if self._blend < _BLEND_EPSILON:
                self._blend = 0.0
                self._inv_focus = 0.0
        return self

    def nudge_strength(self, delta):
        """Move both defocus strengths by `delta`, clamped. Dev tuning only."""
        self.near_strength = min(STRENGTH_MAX,
                                 max(STRENGTH_MIN, self.near_strength + delta))
        self.far_strength = min(STRENGTH_MAX,
                                max(STRENGTH_MIN, self.far_strength + delta))
        return (self.near_strength, self.far_strength)
```

- [ ] **Step 4: Add the camera-mode hook**

In `engine/appc/camera_modes.py`, add to the `CameraMode` base class (the class at `:70`), as a new method:

```python
    def focus_subject(self):
        """The object this camera wants in focus, or None.

        Depth of field consults this before falling back to the player's
        selected target, so a camera that frames something other than the
        target can say so. Only TorpCameraMode overrides it today; the hook
        exists so cutscene and cinematic modes can adopt it without another
        special case.
        """
        return None
```

and to `TorpCameraMode` (the class at `:767`), as a new method:

```python
    def focus_subject(self):
        """The torpedo being ridden — the shot's actual subject.

        None once the torpedo has left the registry, even though the mode
        holds its final pose for DelayAfterTorpGone seconds: the shot is over,
        so the lens should release rather than stay locked on empty space.
        """
        return self._torp
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_dof_focus.py -v 2>&1 | tail -25
```

Expected: PASS, 18 tests.

- [ ] **Step 6: Verify the camera-mode hook did not break the mode stack**

```bash
uv run pytest tests/unit/test_camera_mode_stack.py -q 2>&1 | tail -5
```

Expected: PASS (unchanged).

- [ ] **Step 7: Commit**

```bash
git add engine/cameras/dof.py tests/unit/test_dof_focus.py engine/appc/camera_modes.py
git commit -m "$(cat <<'EOF'
feat(cameras): add the depth-of-field focus solver

Deep focus is the default and it is literal: with no subject the solver
reports blend 0 and the host skips the pass entirely.

Two behaviours worth keeping. First acquisition SNAPS the focus distance
and only eases the engagement, because racking from nowhere would swing
the lens the moment a target is selected. And the rack itself eases in
dioptres, not distance -- a real focus pull moves the barrel in
1/distance, so easing linear distance would make a rack outward take
visibly longer than the same rack back in.

Every tuning value lives here as a module constant, so retuning after a
live look is a Python edit with no rebuild.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Per-frame integration in the host loop

**Files:**
- Modify: `engine/host_loop.py`

**Interfaces:**
- Consumes: `engine.cameras.dof.FocusSolver`, `focus_subject`, `subject_distance_gu` (Task 4); `engine.renderer.set_dof_params` (Task 3).
- Produces: a module-level `_focus_solver` instance that Task 7's dev keybindings nudge.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dof_host_push.py`:

```python
"""The host must push DOF params from the same place it sets the camera.

This is the seam where a feature silently dies: the solver can be perfect and
the shader can be perfect, and if nothing calls set_dof_params the effect
simply never happens with every test still green.
"""
import ast
import pathlib

HOST_LOOP = pathlib.Path(__file__).resolve().parents[2] / "engine" / "host_loop.py"


def _calls_named(tree, name):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                out.append(node)
    return out


def test_host_loop_pushes_dof_params():
    tree = ast.parse(HOST_LOOP.read_text())
    assert _calls_named(tree, "set_dof_params"), (
        "host_loop never calls r.set_dof_params -- DOF would be inert"
    )


def test_dof_push_sits_next_to_the_exterior_set_camera():
    """The push must be near the exterior camera solve, not in some unrelated
    branch: it needs that frame's eye position to measure the subject."""
    tree = ast.parse(HOST_LOOP.read_text())
    cam_lines = [c.lineno for c in _calls_named(tree, "set_camera")]
    dof_lines = [c.lineno for c in _calls_named(tree, "set_dof_params")]
    assert dof_lines, "no set_dof_params call"
    assert any(abs(d - c) < 40 for d in dof_lines for c in cam_lines), (
        "set_dof_params is not adjacent to any set_camera call"
    )


def test_host_loop_constructs_a_focus_solver():
    src = HOST_LOOP.read_text()
    assert "FocusSolver()" in src, "no FocusSolver constructed"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_dof_host_push.py -v 2>&1 | tail -15
```

Expected: FAIL — no `set_dof_params` call and no `FocusSolver()`.

- [ ] **Step 3: Construct the solver**

In `engine/host_loop.py`, immediately after the `from engine.cameras import (...)` block (which ends at `:2072`), add:

```python
from engine.cameras.dof import FocusSolver as _DofFocusSolver

# Depth-of-field focus. Module-level so the dev keybindings can nudge the
# live lens strengths without threading a reference through the loop.
_focus_solver = _DofFocusSolver()
```

- [ ] **Step 4: Push the params each frame**

In `engine/host_loop.py`, immediately after the exterior `r.set_camera(...)` call (`~:8796-8798`, the one with `near=1.0, far=5000.0`), add:

```python
                # Depth of field. The subject is whatever the active
                # cinematic camera names (TorpCameraMode rides a torpedo),
                # else the player's selected target, else nothing — and
                # nothing means blend 0, which makes the host skip the pass
                # entirely. Measured from `eye`, this frame's actual camera
                # position, so a shaken or cutscene camera focuses correctly.
                from engine.cameras import dof as _dof
                _dof_mode = _cc[1] if _cc is not None else None
                _dof_solver_out = _focus_solver.update(
                    _dof.subject_distance_gu(
                        eye, _dof.focus_subject(player, _dof_mode)),
                    _player_dt)
                r.set_dof_params(_dof_solver_out.focus_gu,
                                 _dof_solver_out.blend,
                                 _dof_solver_out.near_strength,
                                 _dof_solver_out.far_strength,
                                 _dof_solver_out.far_ceiling,
                                 _dof_solver_out.max_radius_frac)
```

Note `_player_dt`, **not** wall-clock `dt`: the focus pull must freeze under pause along with everything else, the same reason the letterbox bars use it.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_dof_host_push.py -v 2>&1 | tail -15
```

Expected: PASS, 3 tests.

- [ ] **Step 6: Verify nothing else regressed**

```bash
uv run pytest tests/unit -q 2>&1 | tail -10
```

Expected: no new failures relative to `tests/known_failures.txt`.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_dof_host_push.py
git commit -m "$(cat <<'EOF'
feat(host): drive depth of field from the exterior camera solve

The push sits next to r.set_camera because it needs that frame's actual
eye position to measure the subject -- a shaken or cutscene camera then
focuses correctly rather than from a nominal pose.

Fed _player_dt rather than wall-clock dt, so a focus pull freezes under
pause instead of continuing to rack while the game is stopped.

The test guards the seam where this feature would otherwise die
silently: solver and shader can both be perfect and, with nothing calling
set_dof_params, the effect simply never happens with every test green.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Settings integration

**Files:**
- Modify: `engine/settings_store.py`
- Modify: `engine/ui/configuration_panel.py`
- Modify: `engine/host_loop.py`

**Interfaces:**
- Consumes: `engine.renderer.set_dof_enabled` (Task 3).
- Produces: `"dof"` as a member of the `camera_realism` master.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dof_settings.py`:

```python
"""DOF rides the existing Camera Realism master.

No new player-facing row and no schema migration: the master already owns
HDR, the filmic grade, motion blur and modern lens flares, and DOF is squarely
that family.
"""
from engine.ui.configuration_panel import MASTER_TOGGLES


def _appliers_for(key):
    for k, _label, appliers in MASTER_TOGGLES:
        if k == key:
            return appliers
    raise AssertionError(f"no master toggle {key!r}")


def test_dof_is_a_member_of_camera_realism():
    assert "dof" in _appliers_for("camera_realism")


def test_camera_realism_still_owns_its_original_four():
    appliers = _appliers_for("camera_realism")
    for name in ("hdr", "filmic", "motion_blur", "hdr_lens_flare"):
        assert name in appliers


def test_schema_version_is_unchanged():
    """Adding an applier to an existing master must not need a migration."""
    from engine.settings_store import SCHEMA_VERSION
    assert SCHEMA_VERSION == 2


def test_the_master_fans_out_to_set_dof_enabled():
    import inspect
    import engine.settings_store as store
    src = inspect.getsource(store)
    assert "set_dof_enabled" in src, (
        "camera_realism's fan-out never reaches the DOF toggle"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_dof_settings.py -v 2>&1 | tail -15
```

Expected: FAIL — `"dof"` is not in the `camera_realism` appliers.

- [ ] **Step 3: Add the applier to the master**

In `engine/ui/configuration_panel.py`, change the `camera_realism` row of `MASTER_TOGGLES` (~:73):

```python
    ("camera_realism", "Camera Realism",
     ("hdr", "filmic", "motion_blur", "hdr_lens_flare", "dof")),
```

Add the constructor parameter beside `set_motion_blur` (~:130):

```python
                 set_dof: Callable[[bool], None],
```

and the entry in `self._appliers` beside `"motion_blur"` (~:169):

```python
            "dof": set_dof,
```

- [ ] **Step 4: Add the fan-out and the construction argument**

In `engine/settings_store.py`, add a fifth lambda to the `camera_realism` `_fan(...)` (~:273-276), after the `set_motion_blur_enabled` line:

```python
                 lambda c, v: c.r.set_dof_enabled(v),
```

In `engine/host_loop.py`, at the `ConfigurationPanel(...)` construction (~:7379), add beside `set_motion_blur`:

```python
            set_dof=r.set_dof_enabled,
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_dof_settings.py -v 2>&1 | tail -15
```

Expected: PASS, 4 tests.

- [ ] **Step 6: Verify the panel's own suite still passes**

The constructor gained a **required** parameter, so every existing construction site and test fixture must supply it. Run:

```bash
uv run pytest tests/unit -q -k "config or panel or settings" 2>&1 | tail -15
```

Expected: PASS. If any test fails with `TypeError: __init__() missing 1 required positional argument: 'set_dof'`, add `set_dof=lambda v: None` to that fixture — the parameter is deliberately required (not defaulted) so a missing wiring is a construction-time `TypeError` rather than a silently dead toggle, matching the comment already on `self._appliers`.

- [ ] **Step 7: Commit**

```bash
git add engine/settings_store.py engine/ui/configuration_panel.py \
        engine/host_loop.py tests/unit/test_dof_settings.py
git commit -m "$(cat <<'EOF'
feat(ui): fold depth of field into the Camera Realism master

The master already owns HDR, the filmic grade, motion blur and modern
lens flares; DOF is squarely that family. Riding it means no new
player-facing row and no schema migration -- SCHEMA_VERSION stays at 2,
since only the master's fan-out grows.

set_dof is a required constructor parameter rather than a defaulted one,
matching the existing appliers: a missing wiring is then a TypeError at
construction instead of a toggle that quietly does nothing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Live tuning keybindings

**Files:**
- Modify: `engine/dev_keybindings.py`

**Interfaces:**
- Consumes: `engine.host_loop._focus_solver` (Task 5), `engine.dev_mode.register_dev_keybinding` .

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dof_dev_keys.py`:

```python
"""Live DOF tuning under --developer.

The point of these keys is that a visual constant gets calibrated in ONE
session: nudge in flight, read the value off stderr, and it becomes the
default in engine/cameras/dof.py. Without them each candidate value costs a
rebuild and a relaunch.
"""
import engine.dev_mode as dev_mode
import engine.dev_keybindings as dev_keybindings
from engine.cameras.dof import FocusSolver, STRENGTH_MAX, STRENGTH_MIN


class _FakeKeys:
    """Hands back a distinct int for any KEY_* name asked of it."""

    def __init__(self):
        self._codes = {}

    def __getattr__(self, name):
        return self._codes.setdefault(name, len(self._codes) + 1)


class _FakeHost:
    def __init__(self):
        self.keys = _FakeKeys()


def test_comma_and_period_are_registered(monkeypatch):
    seen = {}

    def _capture(key, handler, description):
        seen[key] = (handler, description)

    monkeypatch.setattr(dev_mode, "register_dev_keybinding", _capture)
    fake = _FakeHost()
    # register_for_frame tolerates a None session/player -- every handler that
    # needs them checks first.
    dev_keybindings.register_for_frame(fake, None, None)

    assert fake.keys.KEY_COMMA in seen
    assert fake.keys.KEY_PERIOD in seen
    assert "DOF" in seen[fake.keys.KEY_PERIOD][1]


def test_the_handlers_survive_no_host_loop_solver(monkeypatch):
    """The handler resolves host_loop._focus_solver lazily. If the loop has
    not started, pressing the key must be a no-op rather than an exception
    that kills the input dispatch."""
    seen = {}

    def _capture(key, handler, description):
        seen[key] = (handler, description)

    monkeypatch.setattr(dev_mode, "register_dev_keybinding", _capture)
    fake = _FakeHost()
    dev_keybindings.register_for_frame(fake, None, None)

    import engine.host_loop as host_loop
    monkeypatch.setattr(host_loop, "_focus_solver", None, raising=False)
    seen[fake.keys.KEY_PERIOD][0]()   # must not raise


def test_nudging_up_then_down_returns_to_the_start():
    s = FocusSolver()
    start = s.near_strength
    s.nudge_strength(0.1)
    s.nudge_strength(-0.1)
    assert abs(s.near_strength - start) < 1e-9


def test_nudge_saturates_rather_than_running_away():
    s = FocusSolver()
    for _ in range(200):
        s.nudge_strength(0.1)
    assert s.near_strength == STRENGTH_MAX
    for _ in range(200):
        s.nudge_strength(-0.1)
    assert s.near_strength == STRENGTH_MIN
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_dof_dev_keys.py -v 2>&1 | tail -15
```

Expected: FAIL — comma/period are not registered.

- [ ] **Step 3: Register the keys**

Add `import sys` to the imports at the top of `engine/dev_keybindings.py` (it is **not** currently imported; the file has only `from pathlib import Path` and `import engine.dev_mode as dev_mode`).

Add this module-level helper beside `_test_character_nif()` (~:21):

```python
def _dof_strength_nudge(delta):
    """Move both DOF defocus strengths and report the result.

    Live tuning for a purely visual constant: nudge in flight, read the
    number off stderr, and paste it into engine/cameras/dof.py as the new
    default. Per-session only -- nothing is persisted, and nothing is written
    back to the module constants.

    The solver is resolved lazily rather than captured, so pressing the key
    before the host loop has started is a no-op instead of an exception that
    would take down the whole dev-key dispatch.
    """
    from engine import host_loop
    solver = getattr(host_loop, "_focus_solver", None)
    if solver is None:
        return
    near, far = solver.nudge_strength(delta)
    print("[dof] near_strength=%.2f far_strength=%.2f" % (near, far),
          file=sys.stderr)
```

Then register the two keys **inside `register_for_frame`** (`:30`), at the end of the function, matching the indentation of the six existing `dev_mode.register_dev_keybinding(...)` calls:

```python
    # Live DOF tuning. Registered here rather than at import time only
    # because `_h` arrives as a parameter; the handler itself closes over
    # no per-frame state, and re-registering the same key replaces it.
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_COMMA, lambda: _dof_strength_nudge(-0.1),
        "DOF strength -0.1 (,)"
    )
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_PERIOD, lambda: _dof_strength_nudge(+0.1),
        "DOF strength +0.1 (.)"
    )
```

Both keys are free: `,` and `.` appear in `engine/input_map.py:197` only in the display-name table and are bound to no action.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_dof_dev_keys.py -v 2>&1 | tail -15
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Run the full gate**

```bash
scripts/check_tests.sh 2>&1 | tail -30
```

Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression from this branch — do not call it pre-existing without checking the ledger.

- [ ] **Step 6: Commit**

```bash
git add engine/dev_keybindings.py tests/unit/test_dof_dev_keys.py
git commit -m "$(cat <<'EOF'
feat(dev): add live DOF strength nudging under --developer

',' and '.' move both defocus strengths by 0.1 and print the result to
stderr. The point is calibrating a visual constant in ONE session: nudge
in flight, read the number you liked, paste it into
engine/cameras/dof.py as the default. Without this each candidate value
costs a rebuild and a relaunch, which is what made the directional
ambient gradient take three rounds.

Per-session only: the nudge moves solver instance state and never writes
back to the module constants.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Live verification (Mark, after the gate is green)

The headless gate cannot see game feel. These are the checks that need a real run — **do not attempt them; hand them over.**

1. **Deep focus by default.** No target selected: the frame must be exactly as sharp as before this branch. If anything is soft, the pass is running when it should be skipped.
2. **Rack onto a target.** Select a target in chase cam. The target sharpens, your own hull softens as foreground, and the transition takes roughly a third of a second rather than snapping.
3. **Release.** Deselect. Focus releases smoothly back to fully sharp.
4. **Torpedo cam (F4).** The ridden torpedo is the subject; the world behind it softens but distant ships stay readable and the starfield stays sharp.
5. **Strength calibration.** With `--developer`, hold a target and nudge with `,` / `.`. Find the value that reads as a lens without losing the frame, and report the `near_strength` / `far_strength` printed to stderr.
6. **`FAR_CEILING`.** The number most likely to be wrong at 0.4. If the background reads muddy, it wants lowering; if the far field looks flat and gamey, raising.

## Known limitations (expected, not bugs)

Stated in the spec and repeated here so a live look does not mistake them for defects:

1. **Additive transparents inherit the background's CoC.** Beams, torpedo glows and dust do not write depth, so a phaser crossing from your hull to a distant target is blurred by whatever is behind it, not by its own distance.
2. **Camera-anchored dust stays sharp**, for the same reason.
3. **No bokeh shape control** — a uniform disc, no aperture blades, no cat's-eye vignetting at frame edges.
4. **No focus breathing.**
