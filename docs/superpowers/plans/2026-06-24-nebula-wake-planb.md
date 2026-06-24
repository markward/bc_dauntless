# Nebula Ship Wake — Plan B (decoupled additive trail) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-raymarch nebula ship wake (which rode on cloud density and read weak/strobing in sparse cloud) with a decoupled, self-luminous **additive billboard trail** spawned along the same wake path — visible regardless of cloud density, smooth where billboards overlap, and perf-decoupled from the raymarch.

**Architecture:** Keep the existing wake **data path** untouched — the Python `NebulaWakeTracker` (records the trail), the `set_nebula_wake` binding, `g_nebula_wake` (`std::vector<glm::vec4>`, xyz=pos, w=strength), and the host-loop tick + per-frame feed all stay. Only the **rendering** moves: revert the raymarch hook (Task 1, restoring the plain volumetric cloud byte-for-byte), then render the trail as additive camera-facing soft-glow billboards in a new `NebulaWakePass` (Task 2, a sibling of `HullDischargePass`). Live-tune the look (Task 3). This is spec §8 **Plan B #1**.

**Tech Stack:** C++/OpenGL 3.3 (renderer), GLSL, pybind11 (host bindings), Python (host loop + tracker), GoogleTest (C++ FrameTests), pytest.

## Global Constraints

- **Visual-only / GPU-only.** Never touch the CPU concealment field or any gameplay/physics state.
- **Gated by the Volumetric Nebulae toggle ONLY** (`dauntless_volumetric_nebulae::enabled()` / `r.volumetric_nebulae_enabled()`), not Nebula Lightning. The host feed already sends `[]` when the toggle is off, when not in a nebula, and during warp (`_warp_streaking`) — so an empty `g_nebula_wake` ⇒ the pass is a no-op.
- **Reuse the wake DATA path unchanged:** `engine/appc/nebula_wake.py` (tracker), `set_nebula_wake` binding, `g_nebula_wake` (vec4 xyz=pos, w=strength), and the host-loop tick + feed. Do NOT rebuild them.
- **The new pass mirrors `HullDischargePass` exactly** for GL discipline: additive blend `glBlendFunc(GL_ONE, GL_ONE)`, depth-test ON (nearer hull occludes), depth-write OFF, cull OFF; restore canonical GL state (`GL_CULL_FACE` on, `glDepthMask(GL_TRUE)`, `GL_DEPTH_TEST` on, `GL_BLEND` off) before returning. Zero GL work when the list is empty.
- **Single build tree at `build/`.** Build with `cmake -B build -S . && cmake --build build -j`; run `./build/dauntless`. Never cmake from inside `native/`, never create alternate output paths.
- **Shader and CMake changes require `cmake -B build -S .` (reconfigure), not just `--build`.** `host_bindings.cc` is compiled into both `./build/dauntless` and the `_dauntless_host` module — a full `cmake --build build -j` rebuilds both.
- **After Task 1, the three reverted renderer files must be byte-identical to merge-base `68505e41`** (verified with `git diff 68505e41 -- <file>` printing nothing).
- **Pre-existing baselines (this branch adds 0 new):** ~62 pre-existing pytest failures; 7 pre-existing Scorch/Phaser C++ FrameTest failures. Prove 0 NEW, do not assert "green".

---

### Task 1: Revert the in-raymarch wake hook (restore the plain volumetric cloud)

Removes the in-raymarch churn+glow (commits 9c43d87e + ac6a4e1c) so the volumetric cloud renders exactly as it did before the wake feature. Keeps the wake data path (`g_nebula_wake`, the `set_nebula_wake` binding, the host tick/feed) — those feed the new pass in Task 2.

**Files:**
- Modify (revert to `68505e41`): `native/src/renderer/shaders/nebula_volumetric.frag`
- Modify (revert to `68505e41`): `native/src/renderer/include/renderer/nebula_volumetric_pass.h`
- Modify (revert to `68505e41`): `native/src/renderer/nebula_volumetric_pass.cc`
- Modify (surgical): `native/src/host/host_bindings.cc` — drop ONLY the `g_nebula_wake` argument from the volumetric `render(...)` call (keep `g_nebula_wake`, the `set_nebula_wake` binding, init/shutdown clears).
- Modify: `native/tests/renderer/frame_test.cc` — remove the `NebulaWakeBrightensTrail` test (it tested the raymarch hook).

**Interfaces:**
- Consumes: nothing new.
- Produces: `NebulaVolumetricPass::render(...)` returns to its pre-wake signature (no `wake` parameter). `g_nebula_wake` (`std::vector<glm::vec4>`) and the `set_nebula_wake` binding remain available for Task 2.

- [ ] **Step 1: Revert the three pure-Task-2 renderer files to merge-base**

These three files changed ONLY in Task 2, so a clean checkout of the merge-base version is the exact revert:
```bash
cd /Users/mward/Documents/Projects/bc_dauntless
git checkout 68505e41 -- \
  native/src/renderer/shaders/nebula_volumetric.frag \
  native/src/renderer/include/renderer/nebula_volumetric_pass.h \
  native/src/renderer/nebula_volumetric_pass.cc
```

- [ ] **Step 2: Verify those three files are now byte-identical to merge-base**

Run:
```bash
git diff 68505e41 -- \
  native/src/renderer/shaders/nebula_volumetric.frag \
  native/src/renderer/include/renderer/nebula_volumetric_pass.h \
  native/src/renderer/nebula_volumetric_pass.cc
```
Expected: **no output** (empty diff). If anything prints, the revert is incomplete — re-run Step 1.

- [ ] **Step 3: Drop the `g_nebula_wake` argument from the volumetric render call**

In `native/src/host/host_bindings.cc`, the volumetric render call currently passes `g_nebula_wake` as its last argument (around line 616-620):
```cpp
                g_nebula_volumetric_pass->render(
                    cam, *g_pipeline, g_nebulae, g_lighting,
                    /* ...existing args... */,
                    g_nebula_wake);
```
Remove the trailing `,\n                    g_nebula_wake` so the call matches the pre-Task-2 signature. To see the exact pre-Task-2 call to match, run:
```bash
git show 68505e41:native/src/host/host_bindings.cc | grep -n -A6 'g_nebula_volumetric_pass->render'
```
Edit the call to match that argument list exactly. **Do NOT** remove `g_nebula_wake` (the global at ~line 165), its `.clear()` in init/shutdown (~368, ~429), or the `set_nebula_wake` binding (~1741) — those stay for Task 2.

- [ ] **Step 4: Remove the raymarch wake FrameTest**

In `native/tests/renderer/frame_test.cc`, delete the entire `TEST_F(... NebulaWakeBrightensTrail)` test (it asserted the in-raymarch churn+glow, which no longer exists). Find it with:
```bash
grep -n 'NebulaWakeBrightensTrail' native/tests/renderer/frame_test.cc
```
Remove the whole test function body (from its `TEST_F(` line through its closing `}`). Leave all other FrameTests intact.

- [ ] **Step 5: Reconfigure + build (shader reverted ⇒ reconfigure required)**

Run:
```bash
cmake -B build -S . && cmake --build build -j 2>&1 | tail -3
```
Expected: `Built target dauntless` (and `_dauntless_host`) with no errors. The `ld: warning ... newer 'macOS' version` line is pre-existing and harmless.

- [ ] **Step 6: Run the volumetric FrameTests — 0 new failures**

Run:
```bash
ctest --test-dir build -R "FrameTest" 2>&1 | tail -8
```
Expected: the 7 pre-existing Scorch/Phaser FrameTest failures remain; `NebulaWakeBrightensTrail` is gone; **0 new failures**. (Sanity: the existing `NebulaVolumetricRendersDensityAndObscuresHull` test still passes — the cloud is back to plain.)

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/shaders/nebula_volumetric.frag \
        native/src/renderer/include/renderer/nebula_volumetric_pass.h \
        native/src/renderer/nebula_volumetric_pass.cc \
        native/src/host/host_bindings.cc \
        native/tests/renderer/frame_test.cc
git commit -m "revert(nebula-wake): drop the in-raymarch churn+glow (moving to Plan B additive trail)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: New additive wake billboard pass (`NebulaWakePass`)

Renders `g_nebula_wake` as additive camera-facing **soft-glow** billboards — one per trail point, intensity = the point's faded strength. Self-luminous (independent of cloud density). A sibling of `HullDischargePass` with a soft-radial (not electric) shader.

**Files:**
- Create: `native/src/renderer/include/renderer/nebula_wake_pass.h`
- Create: `native/src/renderer/nebula_wake_pass.cc`
- Create: `native/src/renderer/shaders/nebula_wake.vert`
- Create: `native/src/renderer/shaders/nebula_wake.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (embed the two shaders + add `nebula_wake_pass.cc` to the `renderer` library sources)
- Modify: `native/src/renderer/include/renderer/pipeline.h` (shader accessor + member)
- Modify: `native/src/renderer/pipeline.cc` (include the embedded headers + construct the shader)
- Modify: `native/src/host/host_bindings.cc` (pass global + init/shutdown + gated render call + include)
- Test: `native/tests/renderer/frame_test.cc` (`NebulaWakeAdditiveTrail`)

**Interfaces:**
- Consumes: `g_nebula_wake` (`std::vector<glm::vec4>`, xyz = world pos, w = age-faded strength, set by the existing `set_nebula_wake` binding from the reverted in-raymarch work); `dauntless_volumetric_nebulae::enabled()` (the gate); `scenegraph::Camera`; `renderer::Pipeline`.
- Produces:
  - C++ `renderer::NebulaWakePass` with `void render(const scenegraph::Camera& camera, Pipeline& pipeline, const std::vector<glm::vec4>& wake, float time_s)`, plus `set_enabled(bool)`/`enabled()`.
  - `Pipeline::nebula_wake_shader()` accessor.
  - Global `g_nebula_wake_pass` (`std::unique_ptr<renderer::NebulaWakePass>`).

- [ ] **Step 1: Add the failing FrameTest**

In `native/tests/renderer/frame_test.cc`, add a test mirroring the additive-billboard FrameTest pattern used by the other passes (camera-facing additive sprite). It must prove (a) a wake point near the camera **adds brightness** at its screen location, and (b) an **empty** wake list renders **byte-identical** to not invoking the pass at all (off-path is a no-op):

```cpp
TEST_F(FrameTest, NebulaWakeAdditiveTrail) {
    // A camera looking down -Z at the origin; one wake point on the view ray.
    auto cam = MakeCameraLookingAtOrigin();          // mirror the helper other tests use
    renderer::NebulaWakePass pass;

    // (a) With a wake point at the origin (strength 1.0), the centre brightens.
    std::vector<glm::vec4> wake = { glm::vec4(0.0f, 0.0f, 0.0f, 1.0f) };
    auto with    = RenderToBufferWith([&]{ pass.render(cam, *pipeline_, wake, 0.0f); });
    auto without = RenderToBufferWith([&]{ /* pass not invoked */ });
    EXPECT_GT(CentreLuma(with), CentreLuma(without)); // additive glow lifts the centre

    // (b) Empty wake list -> the pass does zero GL work -> byte-identical.
    auto empty_invoked = RenderToBufferWith([&]{
        pass.render(cam, *pipeline_, {}, 0.0f);
    });
    EXPECT_EQ(0, std::memcmp(empty_invoked.data(), without.data(),
                             empty_invoked.size() * sizeof(empty_invoked[0])));
}
```
Adapt `MakeCameraLookingAtOrigin` / `RenderToBufferWith` / `CentreLuma` to the actual helpers in `frame_test.cc` (read the existing volumetric/hit-vfx FrameTests for the real helper names and buffer-readback machinery). The intent is fixed: **(a) wake brightens; (b) empty = no-op byte-identical**. Do not fake (b) — it must compare an empty-list invocation against the no-pass baseline.

- [ ] **Step 2: Run to verify it fails (does not compile / link yet)**

Run:
```bash
ctest --test-dir build -R "NebulaWakeAdditiveTrail" -V 2>&1 | tail -15
```
Expected: build/link failure — `NebulaWakePass` / `nebula_wake_pass.h` does not exist yet.

- [ ] **Step 3: Create the vertex shader**

Create `native/src/renderer/shaders/nebula_wake.vert` (camera-facing billboard, identical billboarding to `hull_discharge.vert`):
```glsl
#version 330 core
layout(location = 0) in vec2 a_corner;   // [-1,1] quad corner

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;   // trail-point world pos
uniform float u_size;     // billboard half-size (GU)

out vec2 v_uv;
void main() {
    vec3 right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 wp = u_center + (right * a_corner.x + up * a_corner.y) * u_size;
    v_uv = a_corner;
    gl_Position = u_proj * u_view * vec4(wp, 1.0);
}
```

- [ ] **Step 4: Create the fragment shader**

Create `native/src/renderer/shaders/nebula_wake.frag` — a **soft** radial glow (Gaussian-ish falloff) with a gentle low-frequency noise churn, additive premultiplied:
```glsl
#version 330 core
in vec2 v_uv;             // [-1,1] quad space
out vec4 frag;

uniform vec3  u_color;     // glow tint
uniform float u_strength;  // this point's age-faded strength (0..1)
uniform float u_glow;      // overall intensity dial
uniform float u_softness;  // radial falloff exponent (higher = softer/tighter)
uniform float u_time;      // for the slow churn

float hash(vec2 p){ return fract(sin(dot(p, vec2(41.3, 289.1))) * 43758.5453); }
float vnoise(vec2 p){
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i), b = hash(i + vec2(1,0));
    float c = hash(i + vec2(0,1)), d = hash(i + vec2(1,1));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

void main() {
    float r = length(v_uv);
    if (r >= 1.0 || u_strength <= 0.0) { frag = vec4(0.0); return; }
    // Soft radial falloff, modulated by a slow churn so the trail isn't a flat disc.
    float churn   = 0.7 + 0.6 * vnoise(v_uv * 2.5 + vec2(u_time * 0.3, 0.0));
    float falloff = pow(1.0 - r, u_softness);
    float e = falloff * churn * u_strength * u_glow;
    frag = vec4(u_color * e, 1.0);   // premultiplied additive (blend GL_ONE, GL_ONE)
}
```

- [ ] **Step 5: Create the pass header**

Create `native/src/renderer/include/renderer/nebula_wake_pass.h`:
```cpp
// native/src/renderer/include/renderer/nebula_wake_pass.h
#pragma once

#include <glm/glm.hpp>

#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// Decoupled ship-wake trail (spec §8 Plan B #1). Draws each wake trail point
/// (xyz = world pos, w = age-faded strength) as a camera-facing additive
/// soft-glow billboard — self-luminous, independent of cloud density. A sibling
/// of HullDischargePass: additive blend, depth-test ON (nearer hull occludes),
/// depth-write OFF; GL state restored to canonical defaults before returning.
class NebulaWakePass {
public:
    NebulaWakePass();
    ~NebulaWakePass();
    NebulaWakePass(const NebulaWakePass&)            = delete;
    NebulaWakePass& operator=(const NebulaWakePass&) = delete;

    /// wake: trail points (xyz world pos, w = strength 0..1). time_s drives the
    /// slow churn in the shader.
    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<glm::vec4>& wake,
                float time_s);

    void set_enabled(bool v) noexcept { enabled_ = v; }
    bool enabled() const noexcept { return enabled_; }

private:
    bool enabled_ = true;
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;

    void ensure_quad_mesh();
};

}  // namespace renderer
```

- [ ] **Step 6: Create the pass implementation**

Create `native/src/renderer/nebula_wake_pass.cc` (mirrors `hull_discharge_pass.cc`'s GL discipline; soft-glow dials instead of electric):
```cpp
// native/src/renderer/nebula_wake_pass.cc
#include "renderer/nebula_wake_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

namespace renderer {

namespace {

// Unit-quad corners ([-1,1]), 2 triangles — mirrors hull_discharge_pass.
constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,  +1.0f, -1.0f,  +1.0f, +1.0f,
    -1.0f, -1.0f,  +1.0f, +1.0f,  -1.0f, +1.0f,
};

// Look dials (live-tune at Vesuvi4). Decoupled from cloud density, so these
// directly control the wake's size/brightness/colour.
constexpr float kWakeSize   = 22.0f;                 // billboard half-size (GU)
constexpr float kWakeGlow   = 1.0f;                  // overall intensity
constexpr float kWakeSoft   = 2.0f;                  // radial falloff exponent
constexpr glm::vec3 kWakeColor{0.55f, 0.75f, 1.0f};  // soft blue-white

}  // namespace

NebulaWakePass::NebulaWakePass() = default;

NebulaWakePass::~NebulaWakePass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void NebulaWakePass::ensure_quad_mesh() {
    if (quad_vao_ != 0) return;
    glGenVertexArrays(1, &quad_vao_);
    glBindVertexArray(quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuadCorners), kQuadCorners,
                 GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glBindVertexArray(0);
}

void NebulaWakePass::render(const scenegraph::Camera& camera,
                            Pipeline& pipeline,
                            const std::vector<glm::vec4>& wake,
                            float time_s) {
    if (!enabled_ || wake.empty()) return;   // zero GL work when idle
    ensure_quad_mesh();

    auto& shader = pipeline.nebula_wake_shader();
    shader.use();
    shader.set_mat4 ("u_view", camera.view_matrix());
    shader.set_mat4 ("u_proj", camera.proj_matrix());
    shader.set_vec3 ("u_color",    kWakeColor);
    shader.set_float("u_glow",     kWakeGlow);
    shader.set_float("u_softness", kWakeSoft);
    shader.set_float("u_time",     time_s);

    // Additive soft-glow billboards: blend GL_ONE/GL_ONE, depth-test on so
    // nearer hull occludes, depth-write off, cull off (quad faces camera).
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);
    for (const auto& p : wake) {
        const float strength = p.w;
        if (strength <= 0.0f) continue;          // skip just-born (faded-in) points
        shader.set_vec3 ("u_center",   glm::vec3(p));
        shader.set_float("u_size",     kWakeSize);
        shader.set_float("u_strength", strength);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
    glBindVertexArray(0);

    // Restore canonical GL defaults so later passes aren't corrupted.
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
}

}  // namespace renderer
```

- [ ] **Step 7: Register the shader + pass in the build**

In `native/src/renderer/CMakeLists.txt`, after the `SHADER_HULL_DISCHARGE_*` embed lines (around line 42-43), add:
```cmake
embed_shader(SHADER_NEBULA_WAKE_VS shaders/nebula_wake.vert nebula_wake_vs)
embed_shader(SHADER_NEBULA_WAKE_FS shaders/nebula_wake.frag nebula_wake_fs)
```
And in the `add_library(renderer STATIC ...)` source list, after `hull_discharge_pass.cc` (line ~117), add:
```cmake
    nebula_wake_pass.cc
```

- [ ] **Step 8: Add the pipeline shader accessor + member**

In `native/src/renderer/include/renderer/pipeline.h`, after the `hull_discharge_shader()` accessor (line ~29) add:
```cpp
    Shader& nebula_wake_shader() noexcept { return *nebula_wake_; }
```
And after the `std::unique_ptr<Shader> hull_discharge_;` member (line ~59) add:
```cpp
    std::unique_ptr<Shader> nebula_wake_;
```

- [ ] **Step 9: Construct the shader in pipeline.cc**

In `native/src/renderer/pipeline.cc`, after the `#include "embedded_hull_discharge_fs.h"` line (line ~35) add:
```cpp
#include "embedded_nebula_wake_vs.h"
#include "embedded_nebula_wake_fs.h"
```
Then find where `hull_discharge_` is constructed (grep `hull_discharge_ =` in pipeline.cc) and add an analogous construction immediately after it, using the `nebula_wake_vs`/`nebula_wake_fs` embedded source symbols (match the exact `make_unique<Shader>(...)` / factory form used for `hull_discharge_`):
```cpp
    nebula_wake_ = /* same factory as hull_discharge_, with */ nebula_wake_vs, nebula_wake_fs;
```
(Read the real `hull_discharge_ = ...` line and mirror it exactly — symbol names `nebula_wake_vs`, `nebula_wake_fs`.)

- [ ] **Step 10: Wire the pass into host_bindings.cc**

In `native/src/host/host_bindings.cc`:
1. After `#include <renderer/hull_discharge_pass.h>` (line ~36) add:
   ```cpp
   #include <renderer/nebula_wake_pass.h>
   ```
2. After the `g_hull_discharge_pass` global (line ~180) add:
   ```cpp
   std::unique_ptr<renderer::NebulaWakePass> g_nebula_wake_pass;
   ```
3. In `init` (near `g_hull_discharge_pass = std::make_unique<...>();`, line ~374) add:
   ```cpp
   g_nebula_wake_pass = std::make_unique<renderer::NebulaWakePass>();
   ```
4. In `shutdown` (near `g_hull_discharge_pass.reset();`, line ~440) add:
   ```cpp
   g_nebula_wake_pass.reset();
   ```
5. Add the gated render call **immediately after the nebula render block** (after the `g_nebula_pass->render(... // V1 faithful` line, ~622, i.e. once the cloud is drawn so the wake is additive over it). `now` is the frame time already in scope at the render site (used by e.g. `g_sun_pass->render(..., now)`):
   ```cpp
                   if (dauntless_volumetric_nebulae::enabled() && g_nebula_wake_pass
                           && !g_nebula_wake.empty())
                       g_nebula_wake_pass->render(cam, *g_pipeline, g_nebula_wake, now);
   ```
   (Match the surrounding indentation. The wake is gated by the **Volumetric** toggle per the Global Constraints; the host feed already empties `g_nebula_wake` off-toggle / off-nebula / during warp.)

- [ ] **Step 11: Reconfigure + build (new shaders + CMake + new .cc ⇒ reconfigure)**

Run:
```bash
cmake -B build -S . && cmake --build build -j 2>&1 | tail -3
```
Expected: `Built target dauntless` + `_dauntless_host`, no errors.

- [ ] **Step 12: Run the FrameTest — passes, 0 new failures**

Run:
```bash
ctest --test-dir build -R "NebulaWakeAdditiveTrail" -V 2>&1 | tail -15
ctest --test-dir build -R "FrameTest" 2>&1 | tail -6
```
Expected: `NebulaWakeAdditiveTrail` PASSES (brightening + empty-list byte-identity); the broader FrameTest run shows only the 7 pre-existing Scorch/Phaser failures (**0 new**).

- [ ] **Step 13: Commit**

```bash
git add native/src/renderer/include/renderer/nebula_wake_pass.h \
        native/src/renderer/nebula_wake_pass.cc \
        native/src/renderer/shaders/nebula_wake.vert \
        native/src/renderer/shaders/nebula_wake.frag \
        native/src/renderer/CMakeLists.txt \
        native/src/renderer/include/renderer/pipeline.h \
        native/src/renderer/pipeline.cc \
        native/src/host/host_bindings.cc \
        native/tests/renderer/frame_test.cc
git commit -m "feat(nebula-wake): decoupled additive soft-glow wake trail (Plan B #1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Live verification + tuning (human-gated)

Hand off to Mark to fly a nebula and tune the look. The wake is now self-luminous, so brightness is a direct dial (no density coupling). This task ends the project once Mark signs off.

**Files (tuning only, as needed):**
- `native/src/renderer/nebula_wake_pass.cc` — `kWakeSize`, `kWakeGlow`, `kWakeSoft`, `kWakeColor` (rebuild: `cmake --build build -j`; no reconfigure needed for `.cc`).
- `engine/appc/nebula_wake.py` — `SPACING`, `N`, `LIFETIME`, `FRONT_RISE` (Python; relaunch only). The 24-point shader-array cap is **gone** with Plan B, so `N` may rise freely for a longer/denser trail.

- [ ] **Step 1: Build is current**

```bash
cmake --build build -j 2>&1 | grep -E "Built target dauntless|error:"
./build/dauntless
```

- [ ] **Step 2: Live checklist (Mark)**

Fly into a nebula (Volumetric Nebulae on) and confirm:
- A **continual, smooth, luminous** trail forms behind the ship (overlapping soft billboards — no strobe, no discrete puffs), visible **regardless of cloud density** (this is the Plan-B win over the in-raymarch version).
- Strongest/brightest just behind the ship, fading down the trail; trail extends a satisfying distance.
- Volumetric Nebulae **off** → wake gone (with the cloud). **Warp** → no wake streak. No GL state corruption in later passes (hull/HUD render normally).
- Framerate holds at 60 Hz.

- [ ] **Step 3: Tune to taste**

If the trail wants to be **longer/denser**: lower `SPACING` and/or raise `N` and `LIFETIME` in `engine/appc/nebula_wake.py` (relaunch). **If you lower `SPACING` below ~5 GU**, update `tests/unit/test_nebula_wake.py::test_records_by_distance_not_per_tick` — it moves the ship `0.1 GU/tick × 50 = 5 GU` total and asserts a single point; reduce the per-tick step (e.g. `i * 0.02`) so the total stays under the new `SPACING`, keeping the "tiny movement lays no second point" intent. Re-run `uv run pytest tests/unit/test_nebula_wake.py -v`.

If the look wants adjusting: `kWakeSize` (tube width), `kWakeGlow` (brightness), `kWakeSoft` (edge softness), `kWakeColor` (tint) in `nebula_wake_pass.cc` (rebuild with `cmake --build build -j`).

- [ ] **Step 4: Record the chosen dials + mark Plan B shipped**

Once Mark signs off, commit any tuned constants, then update `docs/superpowers/specs/2026-06-24-nebula-wake-design.md` §8 to mark **Plan B #1 shipped** (with the final dials), and update the `project_nebula_pockets` memory (the wake — the last nebula follow-on — is complete via Plan B). Commit:
```bash
git commit -am "tune(nebula-wake): Plan B dials from live verification

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (spec §8 Plan B #1):** "Drop the wake out of the raymarch entirely" → Task 1 (reverts the raymarch hook to byte-identical merge-base). "Render it as its own additive pass — glowing turbulent billboards/particles spawned along the trail, reuse the hit_vfx/dust_pass-style billboard infrastructure" → Task 2 (`NebulaWakePass`, a `HullDischargePass` sibling). "Zero added cost to the cloud raymarch; gated by the same toggle" → render call gated by `dauntless_volumetric_nebulae::enabled()`, no raymarch involvement. "Visually still a luminous churning trail" → soft-glow + noise churn shader; live-tuned in Task 3. The reused data path (tracker, binding, feed) is unchanged per the Global Constraints.

**Placeholder scan:** Steps 9 (pipeline shader construction) and the FrameTest helpers (Step 1) intentionally say "mirror the real `hull_discharge_` construction / the real frame_test helpers" rather than inventing exact lines — because those depend on the local factory/helper forms that must be read from the actual files; the symbol names (`nebula_wake_vs`/`_fs`) and the test's fixed intent (brighten; empty = byte-identical no-op) are pinned. All other steps carry complete code.

**Type consistency:** `g_nebula_wake` is `std::vector<glm::vec4>` (xyz=pos, w=strength) end-to-end — produced by the kept `set_nebula_wake` binding (retained from the in-raymarch work, kept by Task 1), consumed by `NebulaWakePass::render(..., const std::vector<glm::vec4>& wake, float time_s)` (B2). The pass's `render` signature, the `g_nebula_wake_pass` global type, the `nebula_wake_shader()` accessor, and the embedded symbols `nebula_wake_vs`/`nebula_wake_fs` are consistent across Steps 5-10. Uniform names (`u_view/u_proj/u_center/u_size` in the vert; `u_color/u_strength/u_glow/u_softness/u_time` in the frag) match the `shader.set_*` calls in the pass.
