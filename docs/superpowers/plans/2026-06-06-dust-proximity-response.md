# Dust VFX Proximity Response Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the camera-anchored space-dust VFX brighter, denser near planets (up to 5×) and suns (up to 10×), pushed radially away from suns within 100 GU, and tinted orange near suns.

**Architecture:** All proximity logic lives in the C++ dust pass. A pure free function `compute_dust_influence()` turns the camera position + sun list + planet list into a small struct (density multiplier, nearest-sun position/radius/push/tint); `DustPass::render` consumes it to set the per-frame instance draw count and shader uniforms. Density is varied by changing `glDrawElementsInstanced`'s instance count against a buffer overseeded to the 10× ceiling — no shader cull. Planets are newly plumbed from Python to the renderer, mirroring the existing sun path.

**Tech Stack:** C++20, GLSL 330, glm, GoogleTest (`renderer_tests`), pybind11 host bindings, Python host loop.

**Spec:** `docs/superpowers/specs/2026-06-06-dust-proximity-response-design.md`

---

## Important build/run notes (read before starting)

- **One build tree only:** `cmake -B build -S . && cmake --build build -j`. Never build from inside `native/`.
- **Shader edits require a cmake *reconfigure*.** Shaders are embedded at configure time via `embed_shader(...)` in `native/src/renderer/CMakeLists.txt`. After editing any `.vert`/`.frag` you MUST re-run `cmake -B build -S .` before `cmake --build build` or the change is silently ignored.
- **Run the C++ tests:** `ctest --test-dir build -R renderer_tests --output-on-failure` (or run the `renderer_tests` binary directly). The renderer tests run under `GALLIUM_DRIVER=llvmpipe`.
- **Do NOT run the full Python `pytest` suite** — it OOMs the host (>100 GB RAM). For the one Python change here, run only the targeted test file/function shown in the relevant task.
- Game units (GU): everything spatial is GU; do not convert. See `engine/units.py`.

## File structure

- `native/src/renderer/include/renderer/dust_pass.h` — add tunable constants, the `DustInfluence` struct, and the `compute_dust_influence()` declaration; extend `DustPass::render` signature.
- `native/src/renderer/dust_pass.cc` — implement `compute_dust_influence()`; seed buffer at overseeded count; consume influence in `render()`; set new uniforms + variable draw count.
- `native/src/renderer/shaders/dust.vert` — apply sun push to world position.
- `native/src/renderer/shaders/dust.frag` — orange tint mix.
- `native/tests/renderer/dust_pass_test.cc` — unit tests for `compute_dust_influence` + overseed count.
- `native/src/renderer/include/renderer/frame.h` — (read only) source of `SunDescriptor`.
- `native/src/host/host_bindings.cc` — add `g_dust_planets`, `set_dust_planets` binding; pass suns + planets into `g_dust_pass->render(...)`.
- `engine/renderer.py` — add `set_dust_planets()` wrapper.
- `engine/host_loop.py` — add `_aggregate_planets()`; call `r.set_dust_planets(...)` next to `r.set_suns(...)`.
- `tests/test_aggregate_planets.py` — (new) Python unit test for `_aggregate_planets`.

---

## Task 1: Tunable constants + brightness boost

This is the unconditional brightness change (spec §1) plus the new constants the later tasks reference. `kBrightnessMin/Max` already feed `u_brightness_min/max`; no shader edit needed.

**Files:**
- Modify: `native/src/renderer/include/renderer/dust_pass.h`

- [ ] **Step 1: Add constants and bump brightness**

In `dust_pass.h`, inside the `// Tunable constants.` block (currently lines ~46–58), change the brightness lines and add the new proximity constants. Replace:

```cpp
    static constexpr float kBrightnessMin        = 0.5f;
    static constexpr float kBrightnessMax        = 1.0f;
```

with:

```cpp
    // Brightness boosted ~1.6x (spec §1, "moderate").
    static constexpr float kBrightnessMin        = 0.8f;
    static constexpr float kBrightnessMax        = 1.6f;

    // ── Proximity response (spec §2-5) ───────────────────────────────
    // Density ceiling near suns AND the overseed factor for the instance
    // buffer. Base visible target stays kParticleCount; the buffer is
    // seeded with kParticleCount * kMaxDensityMult particles and the
    // per-frame draw count scales between the two.
    static constexpr int   kMaxDensityMult       = 10;
    static constexpr float kPlanetPeakMult       = 5.0f;   // density near planets
    static constexpr float kSunPeakMult          = 10.0f;  // density near suns
    // Closeness ramps from 1 at a body's surface to 0 at this multiple of
    // its radius.
    static constexpr float kInfluenceRadii       = 5.0f;
    // Sun push: absolute 100 GU from the sun SURFACE, max displacement 8 GU
    // (inside the 40 GU volume so pushed specks stay in-field).
    static constexpr float kSunPushRange         = 100.0f; // GU, absolute
    static constexpr float kSunPushMax           = 8.0f;   // GU
```

- [ ] **Step 2: Build**

Run: `cmake --build build -j`
Expected: compiles clean (header-only change; no reconfigure needed for `.h`).

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/include/renderer/dust_pass.h
git commit -m "feat(dust): brighten dust + add proximity tunables"
```

---

## Task 2: `DustInfluence` struct + `compute_dust_influence` declaration

Pure CPU function, testable without GL. Declares the data contract the shader/draw code consumes.

**Files:**
- Modify: `native/src/renderer/include/renderer/dust_pass.h`

- [ ] **Step 1: Add include + declarations**

At the top of `dust_pass.h`, after `#include <glm/glm.hpp>`, add:

```cpp
#include <renderer/frame.h>   // renderer::SunDescriptor
```

Then, in `namespace renderer {` *before* `class DustPass`, add:

```cpp
/// Result of evaluating dust proximity to nearby bodies for one frame.
/// Pure data; produced by compute_dust_influence (no GL).
struct DustInfluence {
    float     density_mult = 1.0f;          // [1, kMaxDensityMult]
    glm::vec3 sun_pos      = glm::vec3(0.0f);// nearest sun centre (world)
    float     sun_radius   = 0.0f;          // nearest sun radius
    float     sun_push     = 0.0f;          // GU; 0 when no sun in range
    float     sun_tint     = 0.0f;          // [0,1] orange-mix factor
};

/// Evaluate density/push/tint response for the camera against the active
/// suns and planets. Pure function — no GL, fully unit-testable.
///
/// `planets` are packed as vec4(x, y, z, radius). Density uses the
/// strongest body: a sun in range wins over any planet (spec §2-3 "sun
/// precedence"). Push and tint use the nearest (greatest-closeness) sun.
DustInfluence compute_dust_influence(
    const glm::vec3& camera_pos,
    const std::vector<SunDescriptor>& suns,
    const std::vector<glm::vec4>& planets);
```

- [ ] **Step 2: Build**

Run: `cmake --build build -j`
Expected: compiles (declaration only; `compute_dust_influence` not yet defined, but nothing calls it).

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/include/renderer/dust_pass.h
git commit -m "feat(dust): declare DustInfluence + compute_dust_influence"
```

---

## Task 3: Test `compute_dust_influence` — far field (baseline)

TDD: start with the no-bodies / far-field case.

**Files:**
- Test: `native/tests/renderer/dust_pass_test.cc`

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/dust_pass_test.cc` (after the existing `DustPassWrap` tests, before the `// --- GL-context smoke tests` divider):

```cpp
TEST(DustInfluence, NoBodiesIsBaseline) {
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(0.0f), {}, {});
    EXPECT_FLOAT_EQ(inf.density_mult, 1.0f);
    EXPECT_FLOAT_EQ(inf.sun_push, 0.0f);
    EXPECT_FLOAT_EQ(inf.sun_tint, 0.0f);
}

TEST(DustInfluence, FarBodiesAreBaseline) {
    renderer::SunDescriptor sun;
    sun.position = glm::vec3(10000.0f, 0.0f, 0.0f);
    sun.radius   = 50.0f;
    std::vector<glm::vec4> planets = {
        glm::vec4(0.0f, 9000.0f, 0.0f, 30.0f)  // far planet
    };
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(0.0f), {sun}, planets);
    EXPECT_FLOAT_EQ(inf.density_mult, 1.0f);
    EXPECT_FLOAT_EQ(inf.sun_push, 0.0f);
    EXPECT_FLOAT_EQ(inf.sun_tint, 0.0f);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: link error — `undefined reference to renderer::compute_dust_influence`.

- [ ] **Step 3: Commit the test**

```bash
git add native/tests/renderer/dust_pass_test.cc
git commit -m "test(dust): far-field baseline for compute_dust_influence"
```

---

## Task 4: Implement `compute_dust_influence`

**Files:**
- Modify: `native/src/renderer/dust_pass.cc`

- [ ] **Step 1: Add the implementation**

In `dust_pass.cc`, inside `namespace renderer {` (after `wrap_local_for_test`, before `DustPass::DustPass()`), add:

```cpp
namespace {

// Closeness ramp: 1 at/inside the body surface, smoothly 0 by
// kInfluenceRadii * radius. Returns 0 for non-positive radius.
float body_closeness(const glm::vec3& camera_pos,
                     const glm::vec3& center,
                     float radius) {
    if (radius <= 0.0f) return 0.0f;
    const float d = glm::length(camera_pos - center);
    const float far = DustPass::kInfluenceRadii * radius;
    if (d <= radius) return 1.0f;
    if (d >= far)    return 0.0f;
    // Smoothstep from surface->far, then invert so surface=1, far=0.
    const float t = (d - radius) / (far - radius);   // 0..1
    const float s = t * t * (3.0f - 2.0f * t);       // smoothstep
    return 1.0f - s;
}

}  // namespace

DustInfluence compute_dust_influence(
    const glm::vec3& camera_pos,
    const std::vector<SunDescriptor>& suns,
    const std::vector<glm::vec4>& planets) {
    DustInfluence out;

    // Nearest (greatest-closeness) sun drives push + tint + sun density.
    float best_sun_close = 0.0f;
    for (const auto& s : suns) {
        const float c = body_closeness(camera_pos, s.position, s.radius);
        if (c > best_sun_close) {
            best_sun_close = c;
            out.sun_pos    = s.position;
            out.sun_radius = s.radius;
        }
    }

    // Strongest planet closeness (density only).
    float best_planet_close = 0.0f;
    for (const auto& p : planets) {
        const float c = body_closeness(camera_pos,
                                       glm::vec3(p.x, p.y, p.z), p.w);
        if (c > best_planet_close) best_planet_close = c;
    }

    // Density: sun precedence. A sun in range wins over any planet.
    if (best_sun_close > 0.0f) {
        out.density_mult =
            1.0f + best_sun_close * (DustPass::kSunPeakMult - 1.0f);
    } else {
        out.density_mult =
            1.0f + best_planet_close * (DustPass::kPlanetPeakMult - 1.0f);
    }

    // Tint scales with nearest-sun closeness.
    out.sun_tint = best_sun_close;

    // Push strength: enabled (kSunPushMax) only when a sun is in range;
    // the per-particle falloff vs the 100 GU surface range is in the
    // vertex shader. 0 here means "no push".
    out.sun_push = (best_sun_close > 0.0f) ? DustPass::kSunPushMax : 0.0f;

    return out;
}
```

- [ ] **Step 2: Run the far-field tests**

Run: `cmake --build build -j && ctest --test-dir build -R renderer_tests --output-on-failure -R DustInfluence`
Expected: `NoBodiesIsBaseline` and `FarBodiesAreBaseline` PASS.
(If `ctest -R` filtering is awkward, run the binary directly:
`GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='DustInfluence.*'`.)

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/dust_pass.cc
git commit -m "feat(dust): implement compute_dust_influence proximity math"
```

---

## Task 5: Test density ramps + sun precedence + push/tint

**Files:**
- Test: `native/tests/renderer/dust_pass_test.cc`

- [ ] **Step 1: Write the failing tests**

Append after the `DustInfluence.FarBodiesAreBaseline` test:

```cpp
TEST(DustInfluence, PlanetSurfaceHitsPeakDensity) {
    std::vector<glm::vec4> planets = {
        glm::vec4(0.0f, 0.0f, 0.0f, 30.0f)
    };
    // Camera exactly at the surface (distance == radius) => closeness 1.
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(30.0f, 0.0f, 0.0f), {}, planets);
    EXPECT_FLOAT_EQ(inf.density_mult, renderer::DustPass::kPlanetPeakMult);
    EXPECT_FLOAT_EQ(inf.sun_tint, 0.0f);   // planets never tint
    EXPECT_FLOAT_EQ(inf.sun_push, 0.0f);   // planets never push
}

TEST(DustInfluence, SunSurfaceHitsPeakDensityAndTint) {
    renderer::SunDescriptor sun;
    sun.position = glm::vec3(0.0f);
    sun.radius   = 50.0f;
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(0.0f, 50.0f, 0.0f), {sun}, {});
    EXPECT_FLOAT_EQ(inf.density_mult, renderer::DustPass::kSunPeakMult);
    EXPECT_FLOAT_EQ(inf.sun_tint, 1.0f);
    EXPECT_FLOAT_EQ(inf.sun_push, renderer::DustPass::kSunPushMax);
    EXPECT_FLOAT_EQ(inf.sun_radius, 50.0f);
}

TEST(DustInfluence, DensityIsMonotonicWithDistance) {
    renderer::SunDescriptor sun;
    sun.position = glm::vec3(0.0f);
    sun.radius   = 50.0f;
    const float near = renderer::compute_dust_influence(
        glm::vec3(0.0f, 80.0f, 0.0f), {sun}, {}).density_mult;
    const float mid = renderer::compute_dust_influence(
        glm::vec3(0.0f, 150.0f, 0.0f), {sun}, {}).density_mult;
    const float far = renderer::compute_dust_influence(
        glm::vec3(0.0f, 260.0f, 0.0f), {sun}, {}).density_mult; // > 5*r
    EXPECT_GT(near, mid);
    EXPECT_GT(mid, far);
    EXPECT_FLOAT_EQ(far, 1.0f);
}

TEST(DustInfluence, SunWinsOverPlanetWhenBothInRange) {
    renderer::SunDescriptor sun;
    sun.position = glm::vec3(0.0f);
    sun.radius   = 50.0f;
    std::vector<glm::vec4> planets = {
        glm::vec4(0.0f, 60.0f, 0.0f, 30.0f)  // planet also near camera
    };
    // Camera at the sun surface: sun closeness 1 => sun density (10x),
    // not the planet's 5x.
    const auto inf = renderer::compute_dust_influence(
        glm::vec3(0.0f, 50.0f, 0.0f), {sun}, planets);
    EXPECT_FLOAT_EQ(inf.density_mult, renderer::DustPass::kSunPeakMult);
}
```

- [ ] **Step 2: Run to verify they pass**

Run: `cmake --build build -j && GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='DustInfluence.*'`
Expected: all `DustInfluence.*` PASS (the math in Task 4 already satisfies them).

- [ ] **Step 3: Commit**

```bash
git add native/tests/renderer/dust_pass_test.cc
git commit -m "test(dust): density ramp, sun precedence, push/tint"
```

---

## Task 6: Overseed the instance buffer + variable draw count

Seed at the 10× ceiling and wire density via the per-frame instance count. `render()` still takes only `(camera, dt, pipeline)` here; suns/planets are added in Task 9. For now `render` computes influence from **empty** lists (call site updated later), so behaviour stays at baseline density until the host passes real bodies — verify no regression.

**Files:**
- Modify: `native/src/renderer/include/renderer/dust_pass.h`
- Modify: `native/src/renderer/dust_pass.cc`

- [ ] **Step 1: Add a seeded-count helper to the header**

In `dust_pass.h`, in the `private:` section of `DustPass` (near `particle_count_`), add a static helper and change the default:

```cpp
    // Buffer is overseeded to the density ceiling; the per-frame draw
    // count scales between kParticleCount and this.
    static constexpr int kSeededCount = kParticleCount * kMaxDensityMult;
```

Place this `static constexpr` in the public tunables block next to `kMaxDensityMult` so tests can reference `DustPass::kSeededCount`. Then change the member initialiser:

```cpp
    int        particle_count_ = kSeededCount;
```

- [ ] **Step 2: Seed at kSeededCount**

In `dust_pass.cc`, `initialize_gl()` already ends with
`rebuild_instance_buffer(kSeed, particle_count_);` — since `particle_count_`
now defaults to `kSeededCount`, this seeds 5120. No change needed there, but
confirm `set_density`'s clamp ceiling (50000) still exceeds `kSeededCount`
(5120) — it does.

- [ ] **Step 3: Compute influence + variable draw count in render()**

In `dust_pass.cc::render`, replace the draw call section. Find:

```cpp
    glBindVertexArray(vao_);
    glDrawElementsInstanced(GL_TRIANGLES, 6, GL_UNSIGNED_INT, nullptr,
                            particle_count_);
    glBindVertexArray(0);
```

Replace with:

```cpp
    // Proximity response. Suns/planets are empty until the host wires
    // them in (Task 9); empty lists => baseline density, no push/tint.
    const DustInfluence inf = compute_dust_influence(camera.eye, {}, {});

    shader.set_vec3 ("u_sun_pos",    inf.sun_pos);
    shader.set_float("u_sun_radius", inf.sun_radius);
    shader.set_float("u_sun_push",   inf.sun_push);
    shader.set_float("u_sun_tint",   inf.sun_tint);

    int draw_count = static_cast<int>(
        std::lround(static_cast<float>(kParticleCount) * inf.density_mult));
    if (draw_count < 0) draw_count = 0;
    if (draw_count > particle_count_) draw_count = particle_count_;

    glBindVertexArray(vao_);
    glDrawElementsInstanced(GL_TRIANGLES, 6, GL_UNSIGNED_INT, nullptr,
                            draw_count);
    glBindVertexArray(0);
```

(`std::lround` needs `<cmath>`, already included.)

Note: the four `shader.set_*` for the new uniforms must be set every frame
*before* the draw; they reference uniforms added to the shaders in Tasks 7–8.
Setting a uniform that doesn't exist yet is a silent no-op in this codebase's
`Shader::set_*` (GL returns location -1) — so this compiles and runs even
before the shader edits land. Confirm by reading `Shader::set_vec3/set_float`
in `native/src/renderer/shader.cc` if unsure.

- [ ] **Step 4: Build + run the GL smoke tests**

Run: `cmake --build build -j && GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='DustPass*'`
Expected: `DustPassGLTest.RenderProducesNoGLError`, `DisabledPassDoesNothing`, `SetDensityZeroIsSafe`, and all `DustPassGen/DustPassWrap` PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/dust_pass.h native/src/renderer/dust_pass.cc
git commit -m "feat(dust): overseed buffer + density via per-frame draw count"
```

---

## Task 7: Vertex shader — sun push

**Files:**
- Modify: `native/src/renderer/shaders/dust.vert`

- [ ] **Step 1: Add uniforms + push to dust.vert**

In `dust.vert`, add to the uniform block (after `uniform float u_brightness_max;`):

```glsl
uniform vec3  u_sun_pos;      // nearest sun centre (world)
uniform float u_sun_radius;   // nearest sun radius
uniform float u_sun_push;     // max push (GU); 0 = no sun in range
```

Then, immediately AFTER the existing wrap lines that compute `world_pos`:

```glsl
    vec3 world_pos = u_camera_pos + local;
```

insert:

```glsl
    // Solar-wind push: shove particles radially away from the nearest sun
    // when within kSunPushRange (100 GU) of its SURFACE. Falloff is linear
    // from full push at the surface to zero at 100 GU beyond it.
    if (u_sun_push > 0.0) {
        vec3  to_part   = world_pos - u_sun_pos;
        float dist      = length(to_part);
        float surf_dist = dist - u_sun_radius;
        const float kSunPushRange = 100.0;   // GU (matches dust_pass.h)
        if (surf_dist < kSunPushRange && dist > 1e-4) {
            float falloff = 1.0 - clamp(surf_dist / kSunPushRange, 0.0, 1.0);
            world_pos += (to_part / dist) * u_sun_push * falloff;
        }
    }
```

(The `100.0` literal mirrors `kSunPushRange` in `dust_pass.h`. They are
independent constants in two languages; if you change one, change the other.
Documented in both spots.)

- [ ] **Step 2: Reconfigure (REQUIRED for shader changes) + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: configures + compiles clean. (Skipping the reconfigure silently keeps the old shader — do not skip.)

- [ ] **Step 3: Run GL smoke tests**

Run: `GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='DustPass*'`
Expected: all PASS, no GL errors (the new uniforms now exist; render path unchanged for the no-sun case).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/dust.vert
git commit -m "feat(dust): vertex shader radial push away from suns"
```

---

## Task 8: Fragment shader — orange tint

**Files:**
- Modify: `native/src/renderer/shaders/dust.frag`

- [ ] **Step 1: Add tint to dust.frag**

In `dust.frag`, add a uniform after `uniform float u_radius;`:

```glsl
uniform float u_sun_tint;   // [0,1] orange-mix factor near suns
```

Then replace the final `out_color` line. Current:

```glsl
    out_color = vec4(tex.rgb * v_brightness, tex.a * fade);
```

Replace with:

```glsl
    // Warm the dust toward orange (#FF8030) as the camera nears a sun.
    vec3 tint = mix(vec3(1.0), vec3(1.0, 0.502, 0.188), u_sun_tint);
    out_color = vec4(tex.rgb * v_brightness * tint, tex.a * fade);
```

- [ ] **Step 2: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: configures + compiles clean.

- [ ] **Step 3: Run GL smoke tests**

Run: `GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='DustPass*'`
Expected: all PASS (tint factor is 0 with no sun, so output is unchanged in the smoke tests).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/dust.frag
git commit -m "feat(dust): fragment shader orange tint near suns"
```

---

## Task 9: Plumb planets to the renderer + feed real bodies into render()

Adds the `set_dust_planets` host binding, a `g_dust_planets` store, and passes `g_suns` + `g_dust_planets` into `g_dust_pass->render(...)`. Extends `DustPass::render` to accept the lists.

**Files:**
- Modify: `native/src/renderer/include/renderer/dust_pass.h`
- Modify: `native/src/renderer/dust_pass.cc`
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Extend the render signature (header)**

In `dust_pass.h`, change the `render` declaration:

```cpp
    void render(const scenegraph::Camera& camera,
                float dt_seconds,
                Pipeline& pipeline);
```

to:

```cpp
    void render(const scenegraph::Camera& camera,
                float dt_seconds,
                Pipeline& pipeline,
                const std::vector<SunDescriptor>& suns,
                const std::vector<glm::vec4>& planets);
```

- [ ] **Step 2: Use the lists in render (impl)**

In `dust_pass.cc`, update the `DustPass::render` definition signature to match, and change the influence line from the empty-lists placeholder:

```cpp
    const DustInfluence inf = compute_dust_influence(camera.eye, {}, {});
```

to:

```cpp
    const DustInfluence inf = compute_dust_influence(camera.eye, suns, planets);
```

Also update the early-return branch at the top of `render` — it does not need
the lists, so no change there beyond the signature.

- [ ] **Step 3: Add the planet store + binding (host)**

In `native/src/host/host_bindings.cc`:

(a) Near `std::vector<renderer::SunDescriptor> g_suns;` (line ~69), add:

```cpp
std::vector<glm::vec4> g_dust_planets;   // xyz = world pos, w = radius
```

(b) In both `init()` and `shutdown()` where `g_suns.clear();` appears (lines ~168 and ~193), add alongside:

```cpp
    g_dust_planets.clear();
```

(c) Update the dust render call (line ~258):

```cpp
    if (g_dust_pass) g_dust_pass->render(g_camera, dt, *g_pipeline);
```

to:

```cpp
    if (g_dust_pass) g_dust_pass->render(g_camera, dt, *g_pipeline,
                                         g_suns, g_dust_planets);
```

(d) After the `set_suns` binding (ends ~line 532), add a new binding:

```cpp
    m.def("set_dust_planets",
          [](const std::vector<py::dict>& descs) {
              g_dust_planets.clear();
              g_dust_planets.reserve(descs.size());
              for (const auto& d : descs) {
                  auto pos = d["position"].cast<std::tuple<float,float,float>>();
                  const float radius = d["radius"].cast<float>();
                  g_dust_planets.emplace_back(std::get<0>(pos),
                                              std::get<1>(pos),
                                              std::get<2>(pos),
                                              radius);
              }
          },
          py::arg("planets"),
          "Set planet centres+radii used by the dust pass for proximity "
          "density scaling, applied each frame().");
```

- [ ] **Step 4: Build everything (host + renderer)**

Run: `cmake --build build -j`
Expected: compiles clean; `build/dauntless` and the `_open_stbc_host` module relink.

- [ ] **Step 5: Run renderer tests**

Run: `GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='DustPass*:DustInfluence*'`
Expected: all PASS. (The GL smoke tests in `dust_pass_test.cc` call the OLD 3-arg `render` — they will FAIL TO COMPILE now. Fix them in Step 6.)

- [ ] **Step 6: Update the GL smoke-test call sites**

In `native/tests/renderer/dust_pass_test.cc`, the three `DustPassGLTest` tests call `pass.render(cam, 1.0f / 60.0f, *pipeline);`. Update each of the (4 total) calls to pass empty body lists:

```cpp
    pass.render(cam, 1.0f / 60.0f, *pipeline, {}, {});
```

(There are two calls in `RenderProducesNoGLError` and one each in
`DisabledPassDoesNothing` and `SetDensityZeroIsSafe`.)

- [ ] **Step 7: Rebuild + run**

Run: `cmake --build build -j && GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='DustPass*:DustInfluence*'`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/dust_pass.h native/src/renderer/dust_pass.cc native/src/host/host_bindings.cc native/tests/renderer/dust_pass_test.cc
git commit -m "feat(dust): plumb suns+planets into the dust pass"
```

---

## Task 10: Python — `set_dust_planets` wrapper

**Files:**
- Modify: `engine/renderer.py`

- [ ] **Step 1: Add the wrapper**

In `engine/renderer.py`, after `set_dust_density` (ends ~line 141), add:

```python
def set_dust_planets(planets: list) -> None:
    """Configure planet centres+radii used by the dust pass for proximity
    density scaling. Each entry is a dict {position: (x,y,z), radius: r}
    in game units. Applied each frame()."""
    _h.set_dust_planets(planets)
```

- [ ] **Step 2: Verify import resolves**

Run: `uv run python -c "import engine.renderer as r; print(hasattr(r, 'set_dust_planets'))"`
Expected: prints `True`. (Requires the rebuilt `_open_stbc_host` from Task 9.)

- [ ] **Step 3: Commit**

```bash
git add engine/renderer.py
git commit -m "feat(dust): set_dust_planets python wrapper"
```

---

## Task 11: Python — `_aggregate_planets` + test

Mirrors `aggregate_suns_for_renderer` / `_aggregate_suns`. Walks the active set for `Planet` objects with positive radius.

**Files:**
- Modify: `engine/host_loop.py`
- Test: `tests/test_aggregate_planets.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_aggregate_planets.py`:

```python
"""Unit test for _aggregate_planets in the host loop."""
from engine.appc.planet import Planet
from engine.appc.math import TGPoint3
from engine import host_loop


class _FakeSet:
    def __init__(self, objects):
        self._objects = {i: o for i, o in enumerate(objects)}


def _planet_at(x, y, z, radius):
    p = Planet(radius, "")
    p.SetWorldLocation(TGPoint3(x, y, z))
    return p


def test_aggregate_planets_emits_position_and_radius():
    p = _planet_at(10.0, 20.0, 30.0, 45.0)
    out = host_loop._aggregate_planets([_FakeSet([p])])
    assert len(out) == 1
    assert out[0]["position"] == (10.0, 20.0, 30.0)
    assert out[0]["radius"] == 45.0


def test_aggregate_planets_drops_zero_radius():
    p = _planet_at(0.0, 0.0, 0.0, 0.0)
    out = host_loop._aggregate_planets([_FakeSet([p])])
    assert out == []
```

> `Planet` inherits `GetRadius` / `SetRadius` / `GetWorldLocation` /
> `SetWorldLocation` from `ObjectClass` (`engine/appc/objects.py:52-103`), so
> the helper above works as written.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_aggregate_planets.py -x -q`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_aggregate_planets'`.

- [ ] **Step 3: Implement `_aggregate_planets`**

In `engine/host_loop.py`, add this sibling next to `_aggregate_suns`
(`host_loop.py:1281`). Unlike `_aggregate_suns()` (which is zero-arg and
builds its own set list), `_aggregate_planets` takes `pSets` explicitly so it
is directly unit-testable; the frame loop passes the same set list in Task 12.

```python
def _aggregate_planets(pSets):
    """Return list[dict] {position, radius} for Planet objects across pSets,
    feeding the dust pass's proximity density scaling. Planets with
    radius <= 0 are dropped (they cannot define an influence sphere)."""
    from engine.appc.planet import Planet
    out = []
    for pSet in pSets:
        for obj in getattr(pSet, "_objects", {}).values():
            if not isinstance(obj, Planet):
                continue
            radius = obj.GetRadius()
            if radius <= 0:
                continue
            loc = obj.GetWorldLocation()
            out.append({
                "position": (loc.x, loc.y, loc.z),
                "radius": float(radius),
            })
    return out
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_aggregate_planets.py -x -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/test_aggregate_planets.py
git commit -m "feat(dust): _aggregate_planets host-loop helper + test"
```

---

## Task 12: Wire `_aggregate_planets` into the frame loop

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Call it next to set_suns**

In `engine/host_loop.py`, find (line ~2561):

```python
            suns = _aggregate_suns()
            r.set_suns(suns)
```

Immediately after, add (mirroring how `_aggregate_suns` builds its set list —
see `host_loop.py:1281-1287`):

```python
            import App
            planets = _aggregate_planets(
                list(App.g_kSetManager._sets.values()))
            r.set_dust_planets(planets)
```

(`App` is already imported in this scope a few lines above for
`set_bridge_wall_time`; the local `import App` is harmless if duplicated, but
you may omit it if `App` is already bound here.)

- [ ] **Step 2: Add a tick-0 debug line (optional, matches suns)**

If the `verbose and ticks == 0` block prints sun count (~line 2573), add:

```python
                print(f"[host_loop] tick 0 dust planets: "
                      f"{len(planets)} planet(s)", flush=True)
```

- [ ] **Step 3: Smoke-test the host loop import**

Run: `uv run python -c "import engine.host_loop"`
Expected: imports without error.
(Do NOT run the full pytest suite — it OOMs the host.)

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(dust): feed planets to dust pass each frame"
```

---

## Task 13: Full build + targeted verification

**Files:** none (verification only)

- [ ] **Step 1: Clean reconfigure + full build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: configures (picks up shader edits) and builds clean.

- [ ] **Step 2: Run the full renderer test binary**

Run: `GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests`
Expected: all tests PASS, including `DustInfluence.*`, `DustPassGen.*`, `DustPassWrap.*`, `DustPassGLTest.*`.

- [ ] **Step 3: Run the new Python test**

Run: `uv run pytest tests/test_aggregate_planets.py -q`
Expected: 2 passed.

- [ ] **Step 4: Manual visual check (recommended, not automated)**

Run `./build/dauntless` with a mission that has a sun and a planet. Confirm:
dust is visibly brighter; thickens approaching a planet; thickens more and
warms to orange approaching a sun; specks visibly shove outward when within
~100 GU of the sun's surface. Tune `kSunPushMax`, `kInfluenceRadii`,
`kBrightnessMin/Max`, and the orange `vec3(1.0, 0.502, 0.188)` to taste —
remember shader-constant edits (the orange, the `100.0` push range) need a
`cmake -B build -S .` reconfigure.

- [ ] **Step 5: Final commit (if any tuning changed)**

```bash
git add -A
git commit -m "chore(dust): final proximity-response tuning"
```

---

## Self-review notes (for the executor)

- **Spec coverage:** §1 brightness → Task 1; §2-3 density (overseed + draw count) → Tasks 1,6; §4 push → Tasks 1,7,9; §5 tint → Tasks 1,8; data flow (planets) → Tasks 9-12; testing → Tasks 3,5,11,13.
- **Two cross-language constants** are intentionally duplicated and documented in both places: `kSunPushRange`/`100.0` (dust_pass.h ↔ dust.vert) and the orange colour exists only in dust.frag. If you prefer, you may pass the push range as a uniform too — not required.
- **Signature consistency:** `compute_dust_influence` is declared (Task 2) and defined (Task 4) with identical params; `render`'s new 5-arg form is updated in header (Task 9 Step 1), impl (Step 2), the host call site (Step 3c), and all four test call sites (Step 6).
- `_aggregate_suns()` is zero-arg and builds its set list from `App.g_kSetManager._sets.values()` (`host_loop.py:1281`). `_aggregate_planets(pSets)` deliberately takes the list explicitly for testability; Task 12's call site supplies the same list.
