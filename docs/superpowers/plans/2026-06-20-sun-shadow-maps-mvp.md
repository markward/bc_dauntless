# Sun Shadow Maps (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single orthographic sun shadow map so ships and stations cast and receive directional shadows in exterior view, toggled under the Modern VFX config group (default on).

**Architecture:** One depth-only shadow map computed once per frame from a player-centered, capped-radius orthographic box (light-relative, view-independent → shared by main view and viewscreen RTT). Hull-like instances (`rim_eligible`) render into it and sample it in `opaque.frag` with 3×3 PCF. A GL-free `compute_light_matrix` does the frustum fitting; everything else mirrors existing renderer patterns.

**Tech Stack:** C++17, OpenGL 4.1 core, GLSL 330, glm, pybind11, GoogleTest (C++), pytest (Python), CEF (config UI).

**Spec:** `docs/superpowers/specs/2026-06-20-sun-shadow-maps-mvp-design.md`

## Global Constraints

- **Rotation convention:** column-vector. World-forward = `R.GetCol(1)`; never read rows. Body→world = `R · v_body`. Renderer hands `R` to shaders directly (no transpose).
- **Left-handed basis:** ship world matrices are det = −1 (the X-flip in `_ship_world_matrix`). Winding is inverted — the shadow depth-pass cull face must be chosen **empirically**, not assumed `GL_FRONT`.
- **No global up:** never reference world-Z for any up vector. Derive the shadow light's up from the light direction via a deterministic numerical helper only.
- **Units:** everything spatial is game units (GU); 1 GU = 175 m. Internal vars are `*_gu`, never `*_m`. Shadow fit constants are in GU.
- **Shader rebuilds:** `.vert`/`.frag` edits require `cmake -B build -S .` (reconfigure) before `cmake --build build -j` — the embedded-header step is not auto-detected on source change.
- **Binding rebuilds:** edits to `host_bindings.cc` need a full `dauntless` rebuild (compiled into both the binary and the `_dauntless_host` module).
- **When shadows are OFF, the render path must be byte-identical to today.**
- **Build:** `cmake -B build -S . && cmake --build build -j`. **C++ tests:** `ctest --test-dir build -j8`. **Python tests:** `uv run pytest <path> -v`.

---

### Task 1: Shadow toggle namespace + binding + Python wrapper

**Files:**
- Modify: `native/src/renderer/frame.cc` (add `dauntless_shadows` namespace next to `dauntless_hdr`, ~line 60-66)
- Modify: `native/src/host/host_bindings.cc` (forward-decl near the `dauntless_rim` decl ~line 654; pybind `def` after `hdr_set_enabled` ~line 1762)
- Modify: `engine/renderer.py` (add `set_shadows_enabled` after `set_hdr_enabled`, ~line 192)
- Test: `tests/unit/test_renderer_shadows.py` (create)

**Interfaces:**
- Produces (C++): `namespace dauntless_shadows { bool enabled(); void set_enabled(bool); }`
- Produces (pybind): `_dauntless_host.shadows_set_enabled(bool)`
- Produces (Python): `engine.renderer.set_shadows_enabled(enabled: bool) -> None`

- [ ] **Step 1: Write the failing Python test**

Create `tests/unit/test_renderer_shadows.py`:

```python
"""engine.renderer shadows wrapper forwards to the host module."""
from unittest.mock import MagicMock
import engine.renderer as renderer


def test_set_shadows_enabled_forwards_true(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_shadows_enabled(True)
    fake.shadows_set_enabled.assert_called_once_with(True)


def test_set_shadows_enabled_forwards_false(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_shadows_enabled(False)
    fake.shadows_set_enabled.assert_called_once_with(False)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_renderer_shadows.py -v`
Expected: FAIL — `AttributeError: module 'engine.renderer' has no attribute 'set_shadows_enabled'`

- [ ] **Step 3: Add the Python wrapper**

In `engine/renderer.py`, immediately after the `set_hdr_enabled` definition:

```python
def set_shadows_enabled(enabled: bool) -> None:
    """Toggle sun shadow mapping (Modern VFX). Default: on after init()."""
    _h.shadows_set_enabled(enabled)
```

- [ ] **Step 4: Add the C++ toggle namespace**

In `native/src/renderer/frame.cc`, directly after the `dauntless_hdr` namespace block:

```cpp
// Toggle for sun shadow maps (depth pre-pass + PCF in opaque). Default on.
namespace dauntless_shadows {
namespace {
    bool g_shadows_enabled = true;
}
    bool enabled() { return g_shadows_enabled; }
    void set_enabled(bool v) { g_shadows_enabled = v; }
}
```

- [ ] **Step 5: Forward-declare and bind in host_bindings.cc**

Near the existing `dauntless_rim` forward declaration:

```cpp
namespace dauntless_shadows {
    void set_enabled(bool v);
}
```

After the `hdr_set_enabled` pybind definition:

```cpp
m.def("shadows_set_enabled",
      [](bool enabled) { dauntless_shadows::set_enabled(enabled); },
      py::arg("enabled"),
      "Toggle sun shadow maps. Default: on.");
```

- [ ] **Step 6: Verify the Python test passes (mock — no rebuild needed)**

Run: `uv run pytest tests/unit/test_renderer_shadows.py -v`
Expected: PASS (both tests). The mock substitutes `_h`, so the native module need not be rebuilt for this test.

- [ ] **Step 7: Rebuild native to confirm the binding compiles**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds clean (compiles both `dauntless` and the `_dauntless_host` module).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/frame.cc native/src/host/host_bindings.cc engine/renderer.py tests/unit/test_renderer_shadows.py
git commit -m "feat(spv): shadows toggle namespace + binding + renderer wrapper"
```

---

### Task 2: Config panel + host_loop wiring + CEF UI row

**Files:**
- Modify: `engine/ui/configuration_panel.py` (`SettingsSnapshot` field; `__init__` param + store; `render_payload` snapshot tuple + JSON; `dispatch_event` handler)
- Modify: `engine/host_loop.py` (initial setting + applier injection, ~lines 3121-3143)
- Modify: `native/assets/ui-cef/js/configuration_panel.js` (Modern VFX group row + focusables list)
- Test: `tests/unit/test_configuration_panel.py` (add a shadows toggle test)

**Interfaces:**
- Consumes: `engine.renderer.set_shadows_enabled` (Task 1)
- Produces: `SettingsSnapshot.shadows_on: bool` (default `True`); `ConfigurationPanel(..., set_shadows=Callable[[bool], None])`; dispatch action `"toggle:shadows"`

- [ ] **Step 1: Write the failing config-panel test**

Add to `tests/unit/test_configuration_panel.py` (extend the existing `_make` helper to pass `set_shadows=Mock()` and `shadows_on=True` in `initial_settings`, mirroring the other appliers), then:

```python
def test_dispatch_toggle_shadows_flips_and_calls_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:shadows") is True
    kw["set_shadows"].assert_called_once_with(False)
    # Second toggle flips back.
    assert p.dispatch_event("toggle:shadows") is True
    kw["set_shadows"].assert_called_with(True)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_configuration_panel.py::test_dispatch_toggle_shadows_flips_and_calls_applier -v`
Expected: FAIL — `TypeError` on unexpected `set_shadows` kwarg (or assertion failure if `_make` not yet updated).

- [ ] **Step 3: Add the dataclass field**

In `engine/ui/configuration_panel.py`, add to `SettingsSnapshot` (default keeps it ON, consistent with HDR/rim):

```python
    shadows_on: bool = True
```

- [ ] **Step 4: Add the __init__ param, store it**

Add parameter `set_shadows: Callable[[bool], None]` to `__init__` and store:

```python
        self._set_shadows = set_shadows
```

Ensure `shadows_on=initial_settings.shadows_on` is carried into the internal `self._settings` construction.

- [ ] **Step 5: Add the dispatch handler**

In `dispatch_event`, alongside the other `toggle:*` handlers:

```python
        if action == "toggle:shadows":
            new_val = not self._settings.shadows_on
            self._set_shadows(new_val)
            self._settings.shadows_on = new_val
            return True
```

- [ ] **Step 6: Add shadows_on to the payload**

In `render_payload`, add `self._settings.shadows_on` to the change-detection snapshot tuple, and add to the JSON `settings` dict:

```python
            "shadows_on": self._settings.shadows_on,
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_configuration_panel.py -v`
Expected: PASS (the new test and all existing panel tests).

- [ ] **Step 8: Wire the applier in host_loop.py**

In `engine/host_loop.py` where `ConfigurationPanel` is constructed (~lines 3121-3143): add `shadows_on=True` to the `SettingsSnapshot(...)` `initial_settings`, and `set_shadows=r.set_shadows_enabled` to the constructor call.

- [ ] **Step 9: Add the CEF UI row + focusable**

In `native/assets/ui-cef/js/configuration_panel.js`, in the Modern VFX group (after the HDR/Rim rows):

```javascript
      // Dynamic Shadows toggle
      html += '<div class="cp-row' + (isFoc('shadows') ? ' cp-focused' : '') + '">'
            +   '<div class="cp-row__label">Dynamic Shadows</div>'
            +   '<div class="cp-row__control">'
            +     '<button class="cp-toggle' + (s.shadows_on ? ' cp-toggle--on' : '') + '"'
            +        ' onclick="dauntlessEvent(\'configuration/toggle:shadows\')">'
            +       (s.shadows_on ? 'On' : 'Off')
            +     '</button>'
            +   '</div>'
            + '</div>';
```

And in `_cpFocusableList()`, alongside the other Modern VFX controls:

```javascript
      out.push({kind: 'ctrl', target: 'shadows'});
```

- [ ] **Step 10: Commit**

```bash
git add engine/ui/configuration_panel.py engine/host_loop.py native/assets/ui-cef/js/configuration_panel.js tests/unit/test_configuration_panel.py
git commit -m "feat(spv): Dynamic Shadows toggle row + config wiring"
```

---

### Task 3: `compute_light_matrix` — GL-free frustum fitting (TDD)

**Files:**
- Create: `native/src/renderer/include/renderer/shadow_light.h`
- Create: `native/src/renderer/light_matrix.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `light_matrix.cc` to the renderer library sources)
- Create: `native/tests/renderer/light_matrix_test.cc`
- Modify: `native/tests/CMakeLists.txt` (add the test to the renderer test executable)

**Interfaces:**
- Produces:
```cpp
namespace renderer {
struct ShadowLight {
    glm::mat4 view_proj{1.0f};   // clip = view_proj * vec4(world_pos, 1)
    float texel_world_size = 0.0f; // GU per shadow texel = 2R / resolution
};
struct ShadowFitParams {
    float radius_scale  = 3.0f;  // k: half-extent = k * player_bound_radius
    float radius_min_gu = 2.0f;  // R clamp floor (GU)
    float radius_max_gu = 40.0f; // R clamp ceiling (GU)
    float caster_reach_gu  = 30.0f; // extend near plane this far toward the sun (GU)
    float receiver_depth_gu = 30.0f; // box depth behind center (GU)
    int   resolution = 2048;     // shadow map texels (square)
};
ShadowLight compute_light_matrix(const glm::vec3& player_pos_ws,
                                 float player_bound_radius_gu,
                                 const glm::vec3& light_dir_ws, // normalized, points TOWARD the sun
                                 const ShadowFitParams& params);
}
```

- [ ] **Step 1: Write the failing C++ test**

Create `native/tests/renderer/light_matrix_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include "renderer/shadow_light.h"

using renderer::ShadowFitParams;
using renderer::compute_light_matrix;

namespace {
glm::vec3 project_ndc(const glm::mat4& vp, const glm::vec3& p) {
    glm::vec4 c = vp * glm::vec4(p, 1.0f);
    return glm::vec3(c) / c.w; // ortho → w == 1, but keep general
}
}

TEST(LightMatrix, TexelWorldSizeMatchesHalfExtent) {
    ShadowFitParams pr;          // k=3, clamp [2,40], res 2048
    auto sl = compute_light_matrix({0, 0, 0}, 5.0f, glm::normalize(glm::vec3(0, 1, 0)), pr);
    // R = clamp(3*5, 2, 40) = 15 → texel = 2*15/2048
    EXPECT_NEAR(sl.texel_world_size, 30.0f / 2048.0f, 1e-4f);
}

TEST(LightMatrix, RadiusClampsToMax) {
    ShadowFitParams pr;
    auto sl = compute_light_matrix({0, 0, 0}, 1000.0f, glm::normalize(glm::vec3(0, 1, 0)), pr);
    EXPECT_NEAR(sl.texel_world_size, 2.0f * pr.radius_max_gu / pr.resolution, 1e-4f);
}

TEST(LightMatrix, RadiusClampsToMin) {
    ShadowFitParams pr;
    auto sl = compute_light_matrix({0, 0, 0}, 0.01f, glm::normalize(glm::vec3(0, 1, 0)), pr);
    EXPECT_NEAR(sl.texel_world_size, 2.0f * pr.radius_min_gu / pr.resolution, 1e-4f);
}

TEST(LightMatrix, PlayerCenterProjectsNearOrigin) {
    ShadowFitParams pr;
    glm::vec3 center(123.0f, -45.0f, 67.0f);
    auto sl = compute_light_matrix(center, 5.0f, glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f)), pr);
    glm::vec3 ndc = project_ndc(sl.view_proj, center);
    // After texel-snap the center sits within a couple of texels of the NDC origin.
    float tol = 4.0f / pr.resolution;
    EXPECT_LT(std::abs(ndc.x), tol);
    EXPECT_LT(std::abs(ndc.y), tol);
    EXPECT_GT(ndc.z, -1.0f);
    EXPECT_LT(ndc.z, 1.0f);
}

TEST(LightMatrix, CasterTowardSunIsInsideFrustum) {
    ShadowFitParams pr;
    glm::vec3 center(0, 0, 0);
    glm::vec3 L = glm::normalize(glm::vec3(0.2f, 1.0f, 0.1f));
    auto sl = compute_light_matrix(center, 5.0f, L, pr);
    // A caster halfway along the reach toward the sun must be captured.
    glm::vec3 caster = center + L * (pr.caster_reach_gu * 0.5f);
    glm::vec3 ndc = project_ndc(sl.view_proj, caster);
    EXPECT_GT(ndc.z, -1.0f);
    EXPECT_LT(ndc.z, 1.0f);
    EXPECT_LT(std::abs(ndc.x), 1.0f);
    EXPECT_LT(std::abs(ndc.y), 1.0f);
}
```

- [ ] **Step 2: Add the header (declaration only)**

Create `native/src/renderer/include/renderer/shadow_light.h`:

```cpp
#pragma once
#include <glm/glm.hpp>

namespace renderer {

struct ShadowLight {
    glm::mat4 view_proj{1.0f};
    float texel_world_size = 0.0f;
};

struct ShadowFitParams {
    float radius_scale     = 3.0f;
    float radius_min_gu    = 2.0f;
    float radius_max_gu    = 40.0f;
    float caster_reach_gu  = 30.0f;
    float receiver_depth_gu = 30.0f;
    int   resolution       = 2048;
};

// light_dir_ws points TOWARD the sun (matches Lighting::directional_dir_ws).
ShadowLight compute_light_matrix(const glm::vec3& player_pos_ws,
                                 float player_bound_radius_gu,
                                 const glm::vec3& light_dir_ws,
                                 const ShadowFitParams& params);

}  // namespace renderer
```

- [ ] **Step 3: Register the test executable, run to verify it fails (link error)**

In `native/tests/CMakeLists.txt`, add `renderer/light_matrix_test.cc` to the renderer test executable's source list (same `add_executable` block as `renderer/particle_pass_test.cc`).

Run: `cmake -B build -S . && cmake --build build -j`
Expected: FAIL to link — `undefined reference to renderer::compute_light_matrix`.

- [ ] **Step 4: Implement `compute_light_matrix`**

Create `native/src/renderer/light_matrix.cc`:

```cpp
#include "renderer/shadow_light.h"
#include <glm/gtc/matrix_transform.hpp>
#include <algorithm>
#include <cmath>

namespace renderer {

namespace {
// Deterministic perpendicular to L for the light "up" — NOT a world-up
// reference; just the numerically-stable axis least aligned with L.
glm::vec3 stable_up(const glm::vec3& L) {
    glm::vec3 a;
    float ax = std::abs(L.x), ay = std::abs(L.y), az = std::abs(L.z);
    if (ax <= ay && ax <= az)      a = glm::vec3(1, 0, 0);
    else if (ay <= az)             a = glm::vec3(0, 1, 0);
    else                           a = glm::vec3(0, 0, 1);
    glm::vec3 right = glm::normalize(glm::cross(a, L));
    return glm::cross(L, right);
}
}  // namespace

ShadowLight compute_light_matrix(const glm::vec3& player_pos_ws,
                                 float player_bound_radius_gu,
                                 const glm::vec3& light_dir_ws,
                                 const ShadowFitParams& params) {
    const glm::vec3 L = glm::normalize(light_dir_ws); // toward the sun
    const float R = std::clamp(params.radius_scale * player_bound_radius_gu,
                               params.radius_min_gu, params.radius_max_gu);
    const glm::vec3 center = player_pos_ws;
    const glm::vec3 up = stable_up(L);

    // Eye sits caster_reach toward the sun; look back along -L through center.
    const glm::vec3 eye = center + L * params.caster_reach_gu;
    const glm::mat4 view = glm::lookAt(eye, center, up);

    // Depth runs from the eye (near=0, at the sun-side reach) to receiver_depth
    // behind the center.
    const float near_p = 0.0f;
    const float far_p  = params.caster_reach_gu + params.receiver_depth_gu;
    glm::mat4 proj = glm::ortho(-R, R, -R, R, near_p, far_p);

    // Texel-snap the center in light space to kill edge crawl.
    const glm::mat4 vp0 = proj * view;
    glm::vec4 origin = vp0 * glm::vec4(center, 1.0f);
    const float half_res = params.resolution * 0.5f;
    glm::vec2 origin_tx = glm::vec2(origin.x, origin.y) * half_res;
    glm::vec2 rounded = glm::vec2(std::round(origin_tx.x), std::round(origin_tx.y));
    glm::vec2 offset = (rounded - origin_tx) / half_res;
    proj[3][0] += offset.x;
    proj[3][1] += offset.y;

    ShadowLight out;
    out.view_proj = proj * view;
    out.texel_world_size = 2.0f * R / static_cast<float>(params.resolution);
    return out;
}

}  // namespace renderer
```

Also add `light_matrix.cc` to the renderer library sources in `native/src/renderer/CMakeLists.txt`.

- [ ] **Step 5: Build and run the test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R LightMatrix -j8`
Expected: PASS — all five `LightMatrix.*` tests.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/shadow_light.h native/src/renderer/light_matrix.cc native/src/renderer/CMakeLists.txt native/tests/renderer/light_matrix_test.cc native/tests/CMakeLists.txt
git commit -m "feat(spv): GL-free compute_light_matrix shadow frustum fit + tests"
```

---

### Task 4: `ShadowMapTarget` depth FBO

**Files:**
- Create: `native/src/renderer/include/renderer/shadow_map_target.h`
- Create: `native/src/renderer/shadow_map_target.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add source)
- Create: `native/tests/renderer/shadow_map_target_test.cc`
- Modify: `native/tests/CMakeLists.txt` (add test)

**Interfaces:**
- Produces:
```cpp
namespace renderer {
class ShadowMapTarget {
public:
    ShadowMapTarget() = default;
    ~ShadowMapTarget();
    ShadowMapTarget(const ShadowMapTarget&) = delete;
    ShadowMapTarget& operator=(const ShadowMapTarget&) = delete;
    void resize(int w, int h);          // alloc depth tex + FBO; no-op if same size
    void bind() const;                  // draw FBO + viewport(w,h); clears nothing
    std::uint32_t depth_texture() const { return depth_tex_; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }
};
}
```

- [ ] **Step 1: Write the failing GL test**

Create `native/tests/renderer/shadow_map_target_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <memory>
#include "renderer/window.h"
#include "renderer/shadow_map_target.h"
#include <glad/glad.h>

class ShadowMapTargetTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> window;
    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(64, 64, "shadow-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
    }
};

TEST_F(ShadowMapTargetTest, ResizeAllocatesCompleteFramebuffer) {
    renderer::ShadowMapTarget t;
    t.resize(256, 256);
    EXPECT_NE(t.fbo(), 0u);
    EXPECT_NE(t.depth_texture(), 0u);
    EXPECT_EQ(t.width(), 256);
    glBindFramebuffer(GL_FRAMEBUFFER, t.fbo());
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}
```

(Match the exact `Window` constructor signature and glad include used by `native/tests/renderer/particle_pass_test.cc`; adjust the include/header paths to match that file if they differ.)

- [ ] **Step 2: Register and run to verify it fails**

Add the test to the renderer test executable in `native/tests/CMakeLists.txt`.
Run: `cmake -B build -S . && cmake --build build -j`
Expected: FAIL to compile/link — `shadow_map_target.h` not found / undefined symbols.

- [ ] **Step 3: Add the header**

Create `native/src/renderer/include/renderer/shadow_map_target.h`:

```cpp
#pragma once
#include <cstdint>

namespace renderer {

class ShadowMapTarget {
public:
    ShadowMapTarget() = default;
    ~ShadowMapTarget();
    ShadowMapTarget(const ShadowMapTarget&) = delete;
    ShadowMapTarget& operator=(const ShadowMapTarget&) = delete;

    void resize(int w, int h);
    void bind() const;

    std::uint32_t depth_texture() const { return depth_tex_; }
    std::uint32_t fbo() const { return fbo_; }
    int width() const { return width_; }
    int height() const { return height_; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t depth_tex_ = 0;
    int width_ = 0;
    int height_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 4: Implement the FBO (depth-only, PCF-ready, white border)**

Create `native/src/renderer/shadow_map_target.cc`:

```cpp
#include "renderer/shadow_map_target.h"
#include <glad/glad.h>

namespace renderer {

ShadowMapTarget::~ShadowMapTarget() { destroy(); }

void ShadowMapTarget::destroy() {
    if (depth_tex_) { glDeleteTextures(1, &depth_tex_); depth_tex_ = 0; }
    if (fbo_)       { glDeleteFramebuffers(1, &fbo_);    fbo_ = 0; }
    width_ = height_ = 0;
}

void ShadowMapTarget::resize(int w, int h) {
    if (w == width_ && h == height_ && fbo_ != 0) return;
    destroy();
    width_ = w; height_ = h;

    glGenTextures(1, &depth_tex_);
    glBindTexture(GL_TEXTURE_2D, depth_tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, w, h, 0,
                 GL_DEPTH_COMPONENT, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER);
    const float border[4] = {1.0f, 1.0f, 1.0f, 1.0f};  // outside box = lit
    glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR, border);
    // Hardware PCF: sampler2DShadow compares ref <= stored depth.
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_COMPARE_REF_TO_TEXTURE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depth_tex_, 0);
    glDrawBuffer(GL_NONE);
    glReadBuffer(GL_NONE);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void ShadowMapTarget::bind() const {
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glViewport(0, 0, width_, height_);
}

}  // namespace renderer
```

Add `shadow_map_target.cc` to the renderer library sources in `native/src/renderer/CMakeLists.txt`.

- [ ] **Step 5: Build and run the test**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R ShadowMapTarget -j8`
Expected: PASS (or SKIPPED if the CI box has no GL context — both are acceptable green states).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/shadow_map_target.h native/src/renderer/shadow_map_target.cc native/src/renderer/CMakeLists.txt native/tests/renderer/shadow_map_target_test.cc native/tests/CMakeLists.txt
git commit -m "feat(spv): depth-only ShadowMapTarget FBO (PCF-ready, white border)"
```

---

### Task 5: Shadow depth pass — shader, pipeline program, per-frame render

**Files:**
- Create: `native/src/renderer/shaders/shadow.vert`, `native/src/renderer/shaders/shadow.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (two `embed_shader(...)` lines)
- Modify: `native/src/renderer/pipeline.{h,cc}` (add a `shadow_depth` program built from the embedded shader, mirroring an existing program)
- Modify: `native/src/renderer/frame.cc` (add `submit_shadow_depth(...)`; add a frame-scoped `set_active_shadow(...)`/accessor used later by the opaque pass)
- Modify: `native/src/renderer/include/renderer/frame.h` (declare `submit_shadow_depth` + active-shadow setter)
- Modify: `native/src/host/host_bindings.cc` (own `g_shadow_target`; per-frame compute + render before `render_space`)

**Interfaces:**
- Consumes: `compute_light_matrix` (Task 3), `ShadowMapTarget` (Task 4), `world.for_each_visible_in_pass`, `Instance.rim_eligible`, `Instance.world`, `Instance.model_handle`, the model/VAO lookup used by `submit_opaque_in_pass`.
- Produces:
```cpp
namespace renderer {
// Renders depth for all visible rim_eligible casters in Pass::Space into the
// currently-bound (depth) framebuffer, using the shadow_depth program.
void submit_shadow_depth(const scenegraph::World& world,
                         const ShadowLight& light,
                         Pipeline& pipeline,
                         const ModelLookup& lookup);  // same lookup type submit_opaque_in_pass uses
// Frame-scoped state the opaque pass reads (Task 6).
void set_active_shadow(const ShadowLight& light, std::uint32_t depth_tex, bool enabled);
}
```

- [ ] **Step 1: Write the depth shaders**

Create `native/src/renderer/shaders/shadow.vert`:

```glsl
#version 330 core
layout(location = 0) in vec3 a_position;  // match the opaque mesh position attribute location
uniform mat4 u_light_view_proj;
uniform mat4 u_model;
void main() {
    gl_Position = u_light_view_proj * u_model * vec4(a_position, 1.0);
}
```

(Confirm the position attribute location matches the opaque vertex layout in `opaque.vert`; if opaque uses a different location for position, use that number here.)

Create `native/src/renderer/shaders/shadow.frag`:

```glsl
#version 330 core
void main() {
    // Depth-only. Color writes are disabled (GL_NONE draw buffer); depth is
    // written automatically.
}
```

- [ ] **Step 2: Embed the shaders + build the pipeline program**

In `native/src/renderer/CMakeLists.txt`, next to the other `embed_shader` calls:

```cmake
embed_shader(SHADER_SHADOW_VS shaders/shadow.vert shadow_vs)
embed_shader(SHADER_SHADOW_FS shaders/shadow.frag shadow_fs)
```

In `pipeline.{h,cc}`, add a `Program shadow_depth;` member and construct it from `renderer::shader_src::shadow_vs` / `shadow_fs`, mirroring how an existing program (e.g. the dust or opaque program) is built. Include `embedded_shadow_vs.h` / `embedded_shadow_fs.h` in `pipeline.cc`.

- [ ] **Step 3: Implement `submit_shadow_depth` and `set_active_shadow` in frame.cc**

Mirror `submit_opaque_in_pass`'s mesh walk, but bind the `shadow_depth` program, set `u_light_view_proj = light.view_proj` once, and per caster set `u_model = inst.world` and draw position-only. Filter to `inst.rim_eligible`. Use the empirically-chosen cull face (see Global Constraints; default to `glCullFace(GL_FRONT)` and flip in Task 7 if acne/peter-panning says otherwise):

```cpp
void submit_shadow_depth(const scenegraph::World& world,
                         const ShadowLight& light,
                         Pipeline& pipeline,
                         const ModelLookup& lookup) {
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_FRONT);  // TUNED in Task 7 against the det=-1 basis
    glEnable(GL_POLYGON_OFFSET_FILL);
    glPolygonOffset(2.0f, 4.0f);  // slope-scaled + constant bias backstop

    auto& prog = pipeline.shadow_depth;
    prog.use();
    prog.set_mat4("u_light_view_proj", light.view_proj);

    world.for_each_visible_in_pass(scenegraph::Pass::Space,
        [&](const scenegraph::Instance& inst) {
            if (!inst.rim_eligible) return;
            prog.set_mat4("u_model", inst.world);
            // Draw the instance's mesh hierarchy position-only via the same
            // VAO/draw calls submit_opaque_in_pass uses (no textures/uniforms
            // beyond u_model). Reuse the existing per-mesh draw helper.
            draw_model_depth_only(inst, lookup, prog);
        });

    glDisable(GL_POLYGON_OFFSET_FILL);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glCullFace(GL_BACK);
}
```

Add a small `draw_model_depth_only(...)` helper that walks the same mesh hierarchy as `draw_model` but only binds the VAO and issues `glDrawElements` per mesh (no material/texture/uniform setup). Factor the shared VAO-walk out of `draw_model` if practical; otherwise a focused copy of just the geometry loop is acceptable.

Add the frame-scoped active-shadow state:

```cpp
namespace {
    ShadowLight g_active_shadow_light;
    std::uint32_t g_active_shadow_tex = 0;
    bool g_active_shadow_enabled = false;
}
void set_active_shadow(const ShadowLight& light, std::uint32_t depth_tex, bool enabled) {
    g_active_shadow_light = light;
    g_active_shadow_tex = depth_tex;
    g_active_shadow_enabled = enabled;
}
```

(Expose `g_active_shadow_*` to `draw_model` in Task 6 via file-local accessors.)

- [ ] **Step 4: Drive it per-frame in host_bindings.cc**

Own a `std::unique_ptr<renderer::ShadowMapTarget> g_shadow_target;` (construct + `resize(2048, 2048)` in `init()`). In `frame()`, **before** the HDR target is bound and before `render_space`:

```cpp
if (dauntless_shadows::enabled() && g_shadow_target) {
    renderer::ShadowFitParams fp;  // defaults
    glm::vec3 light_dir = g_lighting.directional_dir_ws[0];
    renderer::ShadowLight sl = renderer::compute_light_matrix(
        player_world_pos, player_bound_radius_gu, light_dir, fp);

    GLint prev_fbo = 0; glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev_fbo);
    g_shadow_target->bind();
    glClear(GL_DEPTH_BUFFER_BIT);
    renderer::submit_shadow_depth(g_world, sl, *g_pipeline, model_lookup);
    glBindFramebuffer(GL_FRAMEBUFFER, prev_fbo);

    renderer::set_active_shadow(sl, g_shadow_target->depth_texture(), true);
} else {
    renderer::set_active_shadow({}, 0, false);
}
```

(Use the existing accessors for the player ship's world position and bound radius — the same source the camera/centroid logic uses; `player_bound_radius_gu` is the player instance's model bound radius. If no player instance exists this frame, set `enabled = false` and skip.)

- [ ] **Step 5: Build and smoke-run**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds clean.

Run (visual smoke — depth pass active but opaque not yet sampling): `./build/dauntless` and load any exterior-view mission via the dev mission picker.
Expected: **no visual change yet** (shadow map is rendered but unused), **no GL errors**, no frame-time regression. Shadows-off must look identical.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/shadow.vert native/src/renderer/shaders/shadow.frag native/src/renderer/CMakeLists.txt native/src/renderer/pipeline.h native/src/renderer/pipeline.cc native/src/renderer/frame.cc native/src/renderer/include/renderer/frame.h native/src/host/host_bindings.cc
git commit -m "feat(spv): shadow depth pre-pass renders caster depth map per frame"
```

---

### Task 6: Opaque pass receives the shadow (PCF sampling)

**Files:**
- Modify: `native/src/renderer/shaders/opaque.vert` (pass world position to fragment — reuse if already present)
- Modify: `native/src/renderer/shaders/opaque.frag` (shadow uniforms + PCF + apply to directional[0])
- Modify: `native/src/renderer/frame.cc` (`draw_model` binds `u_shadow_map`, `u_light_view_proj`, `u_shadows_enabled`, `u_shadow_texel` from the active-shadow state)

**Interfaces:**
- Consumes: `set_active_shadow` state (Task 5), `ShadowLight` (Task 3).
- Produces: shadowed sun lighting on hull instances; no new external symbols.

- [ ] **Step 1: Add shadow sampling to the fragment shader**

In `opaque.frag`, add uniforms and a PCF helper:

```glsl
uniform int        u_shadows_enabled;   // 0/1
uniform mat4       u_light_view_proj;
uniform sampler2DShadow u_shadow_map;    // dedicated texture unit
uniform float      u_shadow_texel;       // world units/texel (unused in clip-space PCF; reserved)

float sun_shadow_factor(vec3 world_pos, vec3 world_normal) {
    if (u_shadows_enabled == 0) return 1.0;
    // Normal-offset bias: push the sample point along the surface normal.
    vec3 p = world_pos + world_normal * (u_shadow_texel * 1.5);
    vec4 lc = u_light_view_proj * vec4(p, 1.0);
    vec3 ndc = lc.xyz / lc.w;
    vec3 uvz = ndc * 0.5 + 0.5;            // NDC [-1,1] -> [0,1]
    if (uvz.z > 1.0) return 1.0;           // beyond far plane = lit
    float sum = 0.0;
    vec2 texel = 1.0 / vec2(textureSize(u_shadow_map, 0));
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x) {
            vec3 c = vec3(uvz.xy + vec2(x, y) * texel, uvz.z);
            sum += texture(u_shadow_map, c);   // hardware PCF compare
        }
    return sum / 9.0;
}
```

Then, where the directional light loop accumulates light, multiply **only the index-0 (sun)** diffuse + specular by `sun_shadow_factor(world_pos, n)`. Leave ambient and other directional indices untouched. Ensure `world_pos` and `n` (world-space) are available — `opaque.vert` already passes world position for decals/rim; reuse that varying.

- [ ] **Step 2: Bind the shadow uniforms in draw_model**

In `draw_model` (frame.cc), for each hull mesh, set:

```cpp
prog.set_int("u_shadows_enabled", g_active_shadow_enabled ? 1 : 0);
if (g_active_shadow_enabled) {
    prog.set_mat4("u_light_view_proj", g_active_shadow_light.view_proj);
    prog.set_float("u_shadow_texel", g_active_shadow_light.texel_world_size);
    const int unit = 5;  // pick a free texture unit (verify against existing binds 0-3)
    glActiveTexture(GL_TEXTURE0 + unit);
    glBindTexture(GL_TEXTURE_2D, g_active_shadow_tex);
    prog.set_int("u_shadow_map", unit);
}
```

(Confirm texture unit 5 is unused by the existing base/glow/specular/decal binds; if not, choose the next free unit.)

- [ ] **Step 3: Build (reconfigure for shader change) and run**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds clean.

Run: `./build/dauntless`, load an exterior-view mission with ≥2 ships.
Expected: ships now show sun shadows — ship-on-ship cast shadows and self-shadowing. Toggling **Dynamic Shadows** off in the config panel returns to the stock look.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/opaque.vert native/src/renderer/shaders/opaque.frag native/src/renderer/frame.cc
git commit -m "feat(spv): opaque pass samples sun shadow map (3x3 PCF, normal-offset bias)"
```

---

### Task 7: Acne tuning + visual verification

**Files:**
- Modify (as needed): `native/src/renderer/frame.cc` (`submit_shadow_depth` cull face + `glPolygonOffset` values; `draw_model` normal-offset scale), `native/src/renderer/shaders/opaque.frag` (bias constant)

**Interfaces:** none new — tuning only.

- [ ] **Step 1: Verify with a pitched ship (the det = −1 checkpoint)**

Use the `verify`/`run` skill: launch `./build/dauntless`, load an exterior mission, and orient the player ship at a pitch/roll where the sun rakes across the hull.

- [ ] **Step 2: Diagnose and fix shadow acne / peter-panning**

- If the hull shows **shadow acne** (stippled self-shadowing on lit surfaces): the cull face is likely wrong for the left-handed basis — flip `glCullFace(GL_FRONT)` ↔ `GL_BACK` in `submit_shadow_depth`. Re-test. This is the documented det = −1 tuning point.
- If shadows **detach from contact points (peter-panning)**: reduce the normal-offset scale (`u_shadow_texel * 1.5` → smaller) and/or lower `glPolygonOffset` constants.
- Iterate cull-face + bias until a raked hull is clean with grounded contact shadows. Record the chosen values in a code comment referencing the det = −1 constraint.

- [ ] **Step 3: Verify the shared-map property on the viewscreen**

Confirm shadows also appear correctly on ships seen through the bridge viewscreen RTT (same shadow map, no extra cost) — sanity check that the once-per-frame compute reaches both views.

- [ ] **Step 4: Verify off = stock**

Toggle Dynamic Shadows **off**; confirm the scene is visually identical to pre-feature (byte-identical shader path when `u_shadows_enabled == 0`).

- [ ] **Step 5: Full regression run**

Run: `ctest --test-dir build -j8` and `uv run pytest tests/unit -k "shadows or configuration or renderer" -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/frame.cc native/src/renderer/shaders/opaque.frag
git commit -m "tune(spv): shadow cull-face + bias for det=-1 basis; visual verification"
```

---

## Self-Review Notes

- **Spec coverage:** toggle/default-on (Tasks 1-2) ✓; player-centered capped-radius ortho fit + texel snap + near-extend (Task 3) ✓; `rim_eligible` caster/receiver predicate (Tasks 5-6) ✓; depth FBO with white border / hardware PCF (Task 4) ✓; once-per-frame, shared across views (Task 5 + Task 7 step 3) ✓; PCF + normal-offset + slope bias acne layers (Tasks 5-7) ✓; off = byte-identical (Tasks 1, 6, 7) ✓; CSM/torpedo deferral (no tasks — correctly out of scope) ✓.
- **Known refinement vs. spec:** the spec named a standalone `ShadowPass` class; the plan implements the depth submission as `submit_shadow_depth` in `frame.cc` (reusing the existing mesh-walk) with the FBO in `ShadowMapTarget`. Same behavior, less duplication — a reasonable implementation decision.
- **Unverified specifics to confirm during implementation (called out inline):** the position attribute location in `opaque.vert`; the exact `ModelLookup` type and per-mesh draw helper used by `submit_opaque_in_pass`; the free texture unit for `u_shadow_map`; the `Window` test-constructor signature; the player world-position/bound-radius accessors in `host_bindings.cc`.
