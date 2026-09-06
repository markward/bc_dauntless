# Directional Ambient Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give exterior hull ambient a normal-keyed direction, so the un-keyed side of a hull varies with the surface instead of being a flat constant.

**Architecture:** A pure function derives one direction and one strength from all of a set's directional lights (luminance-weighted vector sum). `opaque.frag` modulates the existing `u_ambient_light` by `dot(N, dir)` in a mean-preserving way, so the average ambient over a sphere is unchanged and the feature redistributes light rather than adding it. A strength of 0 is the stock path, byte-identical.

**Tech Stack:** C++17, OpenGL 4.1 core (GLSL 410), glm, GoogleTest/ctest, pybind11, Python 3, pytest.

**Spec:** `docs/superpowers/specs/2026-09-06-directional-ambient-design.md`

## Global Constraints

- **Strength 0 must be byte-identical to today**, not merely equivalent — the convention already used for shadows, specular, normal maps and MSAA.
- **The evaluation must stay mean-preserving.** `u_ambient_light * (1.0 + gradient * dot(N, dir))`. The tempting `u_ambient_light + gradient * (0.5 + 0.5*dot(N,dir))` ADDS light and brightens the whole scene — the spec rejects it by name. Do not "simplify" to it.
- **Bridges are out of scope.** BC bridge NIFs carry baked vertex colour and **no vertex normals at all** (all zero), so a normal-keyed gradient is meaningless there. `bridge.frag` has its own ambient path — do not touch it.
- **Build from the repo root only:** `cmake -B build -S . && cmake --build build -j`. Never run `cmake` inside `native/`.
- **Never change `CMAKE_BUILD_TYPE` in an existing `build/`** — reconfiguring in place leaves `_deps` at the old type and produces a `_dauntless_host.so` that segfaults in the audio tests while ctest stays green. This tree is `Debug`. If you must change it, `rm -rf build` and configure from scratch.
- **Shader edits need a reconfigure** (`cmake -B build -S .`) before the build; shaders are embedded as generated headers. **Shader errors are RUNTIME, not compile-time** — a clean build proves nothing about whether the GLSL compiles. `renderer_tests` is how you find out.
- **`host_bindings.cc` edits require rebuilding the `dauntless` target**, not just the library.
- **The test gate is `scripts/check_tests.sh`** — both suites, diffed against `tests/known_failures.txt`. It builds but does not configure. Never call a failure "pre-existing" by eyeball.
- **Shared checkout:** always `git add` with an explicit pathspec. Never `git add -A`, `git add .`, `git checkout --`, `git restore`, `git stash`, `git clean`, or `git reset --hard`.
- **Never launch the game**, even headless. Renderer verification goes through `renderer_tests`; the live look is Mark's.
- **Rotation convention:** `TGMatrix3` is column-vector, right-handed. World-forward is `GetCol(1)`, up `GetCol(2)`, right `GetCol(0)`. This work does not touch transforms — do not modify any.
- Luminance is Rec.709 `(0.2126, 0.7152, 0.0722)`, matching `filmic.frag`.

---

### Task 1: `ambient_gradient_from_lights()` — the pure math

**Files:**
- Modify: `native/src/renderer/include/renderer/lighting.h`
- Test: `native/tests/renderer/lighting_test.cc`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  ```cpp
  namespace renderer {
  struct AmbientGradient {
      glm::vec3 dir_ws{0.0f, 1.0f, 0.0f};
      float     strength = 0.0f;
  };
  AmbientGradient ambient_gradient_from_lights(
      const glm::vec3* dirs_to_light, const glm::vec3* colors,
      int count, float max_strength);
  }
  ```
  **Task 3** calls this — once per frame, in `set_lighting` — with `Lighting::directional_dir_ws`, `Lighting::directional_color` and `Lighting::directional_count`. Task 2 only stores and pushes the result.

**Why the signature takes raw arrays rather than `const Lighting&`:** `Lighting` lives in `renderer/frame.h`, and `lighting.h` is currently a dependency-light header (`<algorithm>` only). Taking arrays keeps it that way and avoids `frame.h` ↔ `lighting.h` coupling.

**The maths.** `D = Σ normalize(dirs[i]) * luminance(colors[i])`. Coherence is `|D| / Σ luminance(colors[i])` — 1 when every light agrees, 0 when they cancel exactly. `strength = max_strength * coherence`, `dir_ws = normalize(D)`.

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/renderer/lighting_test.cc`:

```cpp
#include <glm/glm.hpp>
#include <cmath>

TEST(AmbientGradient, SingleStarPointsAtItAtFullStrength) {
    const glm::vec3 dirs[1]   = { glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f)) };
    const glm::vec3 colors[1] = { glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 1, 0.6f);
    EXPECT_NEAR(g.dir_ws.x, dirs[0].x, 1e-5f);
    EXPECT_NEAR(g.dir_ws.y, dirs[0].y, 1e-5f);
    EXPECT_NEAR(g.dir_ws.z, dirs[0].z, 1e-5f);
    // One light is perfectly coherent, so it gets the whole budget.
    EXPECT_NEAR(g.strength, 0.6f, 1e-5f);
}

TEST(AmbientGradient, TwoOpposedEqualStarsCancelToFlatAmbient) {
    // THE CASE THIS FUNCTION EXISTS FOR. With light arriving from both sides
    // there is no shadow side to fill, so the gradient must vanish -- and it
    // must do so by construction, not via a special case.
    const glm::vec3 dirs[2]   = { glm::vec3(1, 0, 0), glm::vec3(-1, 0, 0) };
    const glm::vec3 colors[2] = { glm::vec3(1.0f), glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 0.6f);
    EXPECT_NEAR(g.strength, 0.0f, 1e-5f);
}

TEST(AmbientGradient, TwoStarsSameSideAgreeOnDirection) {
    const glm::vec3 dirs[2] = { glm::normalize(glm::vec3(1, 1, 0)),
                                glm::normalize(glm::vec3(1, -1, 0)) };
    const glm::vec3 colors[2] = { glm::vec3(1.0f), glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 1.0f);
    // Symmetric about +X, so the sum lands on +X.
    EXPECT_NEAR(g.dir_ws.x, 1.0f, 1e-4f);
    EXPECT_NEAR(g.dir_ws.y, 0.0f, 1e-4f);
    // Partially coherent: less than a single light, more than nothing.
    EXPECT_GT(g.strength, 0.0f);
    EXPECT_LT(g.strength, 1.0f);
}

TEST(AmbientGradient, OpposedButUnequalFavoursTheBrighter) {
    const glm::vec3 dirs[2]   = { glm::vec3(1, 0, 0), glm::vec3(-1, 0, 0) };
    const glm::vec3 colors[2] = { glm::vec3(1.0f), glm::vec3(0.25f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 1.0f);
    EXPECT_NEAR(g.dir_ws.x, 1.0f, 1e-4f);
    EXPECT_GT(g.strength, 0.0f);
    EXPECT_LT(g.strength, 1.0f);
}

TEST(AmbientGradient, WeightsByLuminanceNotByCount) {
    // A dim red light must lose to a bright white one. Red is the lowest-
    // luminance primary (0.2126), so this also pins the coefficients.
    const glm::vec3 dirs[2]   = { glm::vec3(1, 0, 0), glm::vec3(-1, 0, 0) };
    const glm::vec3 colors[2] = { glm::vec3(0.2f, 0.0f, 0.0f), glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 1.0f);
    EXPECT_NEAR(g.dir_ws.x, -1.0f, 1e-4f);   // the white light wins
}

TEST(AmbientGradient, NoLightsGivesZeroStrength) {
    const auto g = renderer::ambient_gradient_from_lights(nullptr, nullptr, 0, 0.6f);
    EXPECT_NEAR(g.strength, 0.0f, 1e-6f);
}

TEST(AmbientGradient, BlackLightsGiveZeroStrengthWithoutDividingByZero) {
    // Total luminance 0 would be a divide-by-zero in the coherence term.
    const glm::vec3 dirs[1]   = { glm::vec3(1, 0, 0) };
    const glm::vec3 colors[1] = { glm::vec3(0.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 1, 0.6f);
    EXPECT_NEAR(g.strength, 0.0f, 1e-6f);
    EXPECT_TRUE(std::isfinite(g.dir_ws.x));
    EXPECT_TRUE(std::isfinite(g.dir_ws.y));
    EXPECT_TRUE(std::isfinite(g.dir_ws.z));
}

TEST(AmbientGradient, ZeroLengthDirectionIsSkippedNotNormalised) {
    // aggregate_for_renderer filters these, but a zero vector reaching
    // normalize() would produce NaN and poison the whole frame.
    const glm::vec3 dirs[2]   = { glm::vec3(0, 0, 0), glm::vec3(1, 0, 0) };
    const glm::vec3 colors[2] = { glm::vec3(1.0f), glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 1.0f);
    EXPECT_TRUE(std::isfinite(g.strength));
    EXPECT_NEAR(g.dir_ws.x, 1.0f, 1e-4f);
}

TEST(AmbientGradient, StrengthIsClampedIntoZeroOne) {
    const glm::vec3 dirs[1]   = { glm::vec3(1, 0, 0) };
    const glm::vec3 colors[1] = { glm::vec3(1.0f) };
    EXPECT_NEAR(renderer::ambient_gradient_from_lights(dirs, colors, 1, 5.0f).strength,
                1.0f, 1e-6f);
    EXPECT_NEAR(renderer::ambient_gradient_from_lights(dirs, colors, 1, -2.0f).strength,
                0.0f, 1e-6f);
}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: **compile failure** — `no member named 'ambient_gradient_from_lights' in namespace 'renderer'`. That is the correct RED state for a new function.

- [ ] **Step 3: Implement**

In `native/src/renderer/include/renderer/lighting.h`, add `#include <cmath>` and `#include <glm/glm.hpp>` to the existing `#include <algorithm>`, then append inside `namespace renderer`:

```cpp
/// One directional-ambient gradient: an axis and how strongly to apply it.
/// strength == 0 means "no gradient" and dir_ws is then meaningless.
struct AmbientGradient {
    glm::vec3 dir_ws{0.0f, 1.0f, 0.0f};
    float     strength = 0.0f;
};

/// Derive the ambient gradient axis from every directional light in the set.
///
/// Deliberately NOT "the direction of light 0": sets can author up to
/// MAX_DIRECTIONALS (4) lights, so keying off one would be wrong in any
/// multi-star system. The luminance-weighted vector sum
///
///     D = sum( normalize(dirs[i]) * luminance(colors[i]) )
///
/// handles every arrangement without a special case. Coherence
/// |D| / sum(luminance) is 1 when the lights agree and 0 when they cancel,
/// so two opposed equal stars produce a flat ambient BY CONSTRUCTION -- which
/// is correct, not a fallback: with light from both sides there is no shadow
/// side to fill.
///
/// `dirs_to_light` point TOWARD the light, matching Lighting::directional_dir_ws.
/// Zero-length directions are skipped (normalize() on one yields NaN, which
/// would poison every fragment).
inline AmbientGradient ambient_gradient_from_lights(
        const glm::vec3* dirs_to_light, const glm::vec3* colors,
        int count, float max_strength) {
    AmbientGradient out;
    out.strength = 0.0f;
    const float budget = std::clamp(max_strength, 0.0f, 1.0f);
    if (dirs_to_light == nullptr || colors == nullptr || count <= 0 ||
        budget <= 0.0f) {
        return out;
    }

    glm::vec3 sum(0.0f);
    float total_lum = 0.0f;
    for (int i = 0; i < count; ++i) {
        const float len2 = glm::dot(dirs_to_light[i], dirs_to_light[i]);
        if (len2 < 1e-12f) continue;            // zero-vector guard
        const float lum = 0.2126f * colors[i].r
                        + 0.7152f * colors[i].g
                        + 0.0722f * colors[i].b;
        if (lum <= 0.0f) continue;
        sum += (dirs_to_light[i] / std::sqrt(len2)) * lum;
        total_lum += lum;
    }
    if (total_lum <= 0.0f) return out;          // all black: no divide by zero

    const float mag = std::sqrt(glm::dot(sum, sum));
    if (mag < 1e-6f) return out;                // perfectly opposed: flat
    out.dir_ws  = sum / mag;
    out.strength = budget * std::clamp(mag / total_lum, 0.0f, 1.0f);
    return out;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cmake --build build -j && ctest --test-dir build -R "AmbientGradient|Lighting" --output-on-failure
```

Expected: PASS, including the pre-existing `Lighting.GlossinessToSpecularPowerPinnedValues`.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/lighting.h \
        native/tests/renderer/lighting_test.cc
git commit -m "feat(renderer): derive an ambient gradient axis from all directionals

Luminance-weighted vector sum rather than light 0, because sets author up
to four directionals. Two opposed equal stars cancel to a flat ambient by
construction -- correct rather than a fallback, since light from both
sides leaves no shadow side to fill.

Pure and GL-free, so it is unit-tested on every platform."
```

---

### Task 2: Apply the gradient in `opaque.frag`

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag:41` (uniforms), `:647` (the lit term)
- Modify: `native/src/renderer/frame.cc:691`, `:753`, `:815` (three ambient set sites)
- Test: `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Consumes: nothing at runtime from Task 1 — this task only stores and pushes the resolved values. Task 3 connects Task 1's function to this field.
- Produces: a file-local helper in `frame.cc`
  ```cpp
  void set_ambient_uniforms(Shader& s, const Lighting& lighting, float ambient_scale);
  ```
  and two new `opaque.frag` uniforms, `u_ambient_dir_ws` (vec3) and `u_ambient_gradient` (float). Task 3 makes the strength runtime-settable.

**Three set sites, one helper.** `u_ambient_light` is set in `submit_opaque` (`:691`), `submit_opaque_in_pass` (`:753`, the only one taking `ambient_scale`) and `submit_opaque_instance` (`:815`). All three feed `opaque.frag`. Adding two uniforms at three sites by hand invites the classic "updated two of three" bug, so replace each `set_vec3("u_ambient_light", ...)` line with a call to one helper.

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/frame_test.cc`. It renders the Galaxy twice with the gradient off and on and compares the same pixel — a real end-to-end check that the uniform reaches the shader and changes shading.

```cpp
// Renders the Galaxy once and returns the summed RGB of one pixel.
static int render_and_sample(renderer::Pipeline& p, assets::AssetCache& cache,
                             const renderer::Lighting& lighting,
                             int px, int py) {
    auto model_h = cache.load(kGalaxyNif, kGalaxyTex);
    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    submitter.submit_opaque(world, cam, p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting);

    unsigned char px4[4] = {0};
    glReadPixels(px, py, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px4);
    return px4[0] + px4[1] + px4[2];
}

TEST_F(FrameTest, AmbientGradientZeroIsIdenticalToTheStockPath) {
    // The OFF path must be byte-identical, not merely similar: the whole
    // convention for VFX toggles in this renderer depends on it.
    renderer::Lighting lighting;                  // gradient defaults to 0
    const int a = render_and_sample(*p, *cache, lighting, 128, 128);
    const int b = render_and_sample(*p, *cache, lighting, 128, 128);
    EXPECT_EQ(a, b);
    EXPECT_GT(a, 0) << "center pixel was black; the pass produced nothing";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(FrameTest, AmbientGradientBrightensTheLitSideRelativeToTheShadowSide) {
    // Light from +X only. With the gradient on, ambient must favour +X, so
    // the +X flank gains relative to the -X flank. Comparing the DELTA
    // between the two sides (rather than either alone) keeps the assertion
    // about redistribution and not about overall brightness.
    renderer::Lighting lighting;
    lighting.directional_count      = 1;
    lighting.directional_dir_ws[0]  = glm::vec3(1.0f, 0.0f, 0.0f);
    lighting.directional_color[0]   = glm::vec3(1.0f);
    lighting.ambient                = glm::vec3(0.25f);
    // The RESOLVED axis, set directly: this test exercises the shader, not
    // the reduction (that is Task 1's unit tests).
    lighting.ambient_dir_ws         = glm::vec3(1.0f, 0.0f, 0.0f);

    // Two symmetric points on the saucer, left and right of centre.
    const int kRight = 168, kLeft = 88, kY = 128;

    lighting.ambient_gradient = 0.0f;
    const int off_r = render_and_sample(*p, *cache, lighting, kRight, kY);
    const int off_l = render_and_sample(*p, *cache, lighting, kLeft,  kY);

    lighting.ambient_gradient = 1.0f;
    const int on_r = render_and_sample(*p, *cache, lighting, kRight, kY);
    const int on_l = render_and_sample(*p, *cache, lighting, kLeft,  kY);

    EXPECT_GT(on_r - on_l, off_r - off_l)
        << "gradient did not widen the lit/shadow spread; the uniform may "
           "not be reaching the shader";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
```

`Lighting` gains `ambient_dir_ws` and `ambient_gradient` in Step 3 — the tests reference them before they exist, which is what makes them fail.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: **compile failure** — `no member named 'ambient_dir_ws' in 'renderer::Lighting'`.

- [ ] **Step 3: Add the field, the shader uniforms, and the helper**

In `native/src/renderer/include/renderer/frame.h`, add to `struct Lighting` after `directional_color`:

```cpp
    /// RESOLVED directional-ambient axis and strength -- already reduced from
    /// the directionals by ambient_gradient_from_lights. Stored resolved, not
    /// as a budget, because the draw path must not run that reduction:
    /// submit_opaque_instance is called PER INSTANCE, so computing there
    /// would repeat it for every ship every frame. The host resolves it once
    /// per frame in set_lighting (Task 3).
    ///
    /// ambient_gradient == 0 is the stock flat ambient, byte-identical.
    glm::vec3 ambient_dir_ws = glm::vec3(0.0f, 1.0f, 0.0f);
    float     ambient_gradient = 0.0f;
```

In `native/src/renderer/shaders/opaque.frag`, beside `uniform vec3 u_ambient_light;` at line 41:

```glsl
// Directional ambient. u_ambient_gradient == 0 is the stock path: the term
// collapses to u_ambient_light exactly. The axis is the luminance-weighted
// sum of every directional (computed host-side), NOT light 0.
uniform vec3  u_ambient_dir_ws;
uniform float u_ambient_gradient;
```

Replace line 647:

```glsl
    // MEAN-PRESERVING: dot(N, dir) averages to zero over a sphere, so the
    // average ambient across a closed hull is unchanged and this only
    // REDISTRIBUTES ambient. Do NOT rewrite as
    //     u_ambient_light + u_ambient_gradient * (0.5 + 0.5 * d)
    // which adds light and brightens the whole scene.
    float amb_d = dot(n_shade, u_ambient_dir_ws);
    vec3  amb   = u_ambient_light * (1.0 + u_ambient_gradient * amb_d);
    vec3 lit  = (amb + lit_dir + lit_dyn) * u_diffuse_color * base.rgb;
```

In `native/src/renderer/frame.cc`, add near the other file-local helpers, above `FrameSubmitter::submit_opaque`:

```cpp
// Sets the three ambient uniforms together. One helper rather than three
// copies: u_ambient_light is set at three sites (submit_opaque,
// submit_opaque_in_pass, submit_opaque_instance) and adding the gradient
// uniforms by hand at each invites updating only some of them.
void set_ambient_uniforms(Shader& s, const renderer::Lighting& lighting,
                          float ambient_scale) {
    s.set_vec3 ("u_ambient_light",    lighting.ambient * ambient_scale);
    s.set_vec3 ("u_ambient_dir_ws",   lighting.ambient_dir_ws);
    s.set_float("u_ambient_gradient", lighting.ambient_gradient);
}
```

**This helper does no maths on purpose.** It pushes values the host already
resolved. `submit_opaque_instance` is a per-instance entry point, so calling
`ambient_gradient_from_lights` from here would re-reduce every light for every
ship every frame -- the spec requires it once per frame, and Task 3 puts it
where that is true.

Then replace each of the three lines:

- `:691` `s.set_vec3("u_ambient_light", lighting.ambient);`
  → `set_ambient_uniforms(s, lighting, 1.0f);`
- `:753` `s.set_vec3("u_ambient_light", lighting.ambient * ambient_scale);`
  → `set_ambient_uniforms(s, lighting, ambient_scale);`
- `:815` `s.set_vec3("u_ambient_light", lighting.ambient);`
  → `set_ambient_uniforms(s, lighting, 1.0f);`

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j && \
  ctest --test-dir build -R "FrameTest|AmbientGradient" --output-on-failure
```

Expected: PASS. **Shader errors are runtime here** — a clean build says nothing about whether the GLSL compiled, so a `FrameTest` failure with a black or unchanged pixel means the shader failed to compile, not that the maths is wrong. Check the test's stderr for the GLSL log.

- [ ] **Step 5: Verify the OFF path really is byte-identical**

```bash
ctest --test-dir build -R FrameTest --output-on-failure 2>&1 | tail -20
```

Expected: every pre-existing `FrameTest` passes unchanged. Those tests all use a default-constructed `Lighting` (`ambient_gradient == 0`), so any movement in them means the stock path was not preserved.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h \
        native/src/renderer/shaders/opaque.frag \
        native/src/renderer/frame.cc \
        native/tests/renderer/frame_test.cc
git commit -m "feat(renderer): modulate exterior ambient by surface normal

Mean-preserving: dot(N, dir) averages to zero over a sphere, so this
redistributes ambient rather than adding it and cannot shift exposure.
Strength 0 collapses to the stock flat ambient exactly.

The three u_ambient_light set sites route through one helper so the
gradient uniforms cannot be added to some of them and not others."
```

---

### Task 3: Resolve the gradient once per frame, and expose the strength

**Files:**
- Modify: `native/src/renderer/frame.cc` (a gate namespace beside `dauntless_rim`)
- Modify: `native/src/host/host_bindings.cc` (the `g_lighting` assignment in `set_lighting`, and one pybind def)
- Modify: `engine/renderer.py`
- Test: `tests/unit/test_renderer_ambient_gradient.py` (create)

**Interfaces:**
- Consumes: `renderer::ambient_gradient_from_lights` (Task 1) and `Lighting::ambient_dir_ws` / `Lighting::ambient_gradient` (Task 2).
- Produces: `renderer.set_ambient_gradient(strength: float) -> None` and `renderer.ambient_gradient() -> float` in Python; `_dauntless_host.ambient_gradient_set` / `ambient_gradient_get`.

**This task is where Task 1 finally gets called.** Tasks 1 and 2 are deliberately
unconnected until here: the reduction happens exactly once per frame, in
`set_lighting`, and nowhere in the draw path.

**Why a knob and not a setting:** the spec defers exposure — whether this ends up under the "Realistic Lighting" master, gets its own row, or is simply always-on with a tuned constant is a decision to make with the effect on screen. What the implementation owes is that the strength is *reachable* for tuning. Default is **0.6**, biased high on purpose: the practice here is to calibrate up and then come down, and a value too subtle to see on the first live look wastes the pass.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_renderer_ambient_gradient.py`:

```python
"""engine.renderer directional-ambient wrappers forward to the host module."""
from unittest.mock import MagicMock

import pytest

import engine.renderer as renderer


def test_set_ambient_gradient_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_ambient_gradient(0.25)
    fake.ambient_gradient_set.assert_called_once_with(0.25)


def test_set_ambient_gradient_coerces_to_float(monkeypatch):
    # The knob is driven from the dev console and from tuning scripts, so an
    # int is a realistic input; pybind11 rejects the wrong type outright.
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_ambient_gradient(1)
    fake.ambient_gradient_set.assert_called_once_with(1.0)


def test_ambient_gradient_reads_back(monkeypatch):
    fake = MagicMock()
    fake.ambient_gradient_get.return_value = 0.6
    monkeypatch.setattr(renderer, "_h", fake)
    assert renderer.ambient_gradient() == pytest.approx(0.6)


def test_default_is_biased_high_for_the_first_live_look():
    """0.6, not something subtle. The house practice is to calibrate UP and
    then come down; a first pass too faint to see wastes the live check."""
    host = pytest.importorskip("_dauntless_host")
    assert host.ambient_gradient_get() == pytest.approx(0.6)


def test_out_of_range_values_are_clamped_not_rejected():
    """The shader term goes negative past 1.0, which would subtract ambient
    on the far side. Clamp rather than trust the caller."""
    host = pytest.importorskip("_dauntless_host")
    original = host.ambient_gradient_get()
    try:
        host.ambient_gradient_set(5.0)
        # ambient_gradient_get reports the GATE's budget, not the resolved
        # per-frame strength (which is additionally scaled by how coherent the
        # set's lights are). Keep the two distinct.
        assert host.ambient_gradient_get() == pytest.approx(1.0)
        host.ambient_gradient_set(-1.0)
        assert host.ambient_gradient_get() == pytest.approx(0.0)
    finally:
        host.ambient_gradient_set(original)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_renderer_ambient_gradient.py -q
```

Expected: FAIL — `AttributeError: module 'engine.renderer' has no attribute 'set_ambient_gradient'`.

- [ ] **Step 3: Add the gate, the binding and the wrapper**

In `native/src/renderer/frame.cc`, beside the other toggle namespaces (`dauntless_rim`, `dauntless_shadows`, `dauntless_specular`):

```cpp
// Directional-ambient strength. Not a player-facing preference yet -- the
// spec defers that until it has been seen in motion -- but reachable so it
// can be calibrated live. Default biased high on purpose (calibrate up,
// then down).
namespace dauntless_ambient_gradient {
    namespace { float g_strength = 0.6f; }
    float strength() { return g_strength; }
    void  set_strength(float v) {
        g_strength = (v < 0.0f) ? 0.0f : (v > 1.0f ? 1.0f : v);
    }
}
```

Declare it beside the other gate declarations in `host_bindings.cc`:

```cpp
namespace dauntless_ambient_gradient {
    float strength();          // defined in frame.cc
    void  set_strength(float);
}
```

In `host_bindings.cc`, in the `set_lighting` lambda that assigns `g_lighting.ambient`, add after the existing assignments:

```cpp
              // Resolve the gradient ONCE PER FRAME, here -- not in the draw
              // path. submit_opaque_instance runs per instance, so reducing
              // the lights there would repeat this for every ship.
              const renderer::AmbientGradient ag =
                  renderer::ambient_gradient_from_lights(
                      g_lighting.directional_dir_ws, g_lighting.directional_color,
                      g_lighting.directional_count,
                      dauntless_ambient_gradient::strength());
              g_lighting.ambient_dir_ws   = ag.dir_ws;
              g_lighting.ambient_gradient = ag.strength;
```

Add `#include <renderer/lighting.h>` to `host_bindings.cc` if absent. Note the
directionals must already be assigned into `g_lighting` before this runs — put
it at the END of the `set_lighting` lambda, after the existing assignments, or
it will reduce the previous frame's lights. Then add the pybind defs beside `smaa_set_enabled`:

```cpp
    m.def("ambient_gradient_set",
          [](float v) {
              dauntless_ambient_gradient::set_strength(v);
              // Re-resolve immediately so the knob bites on the NEXT frame
              // rather than waiting for Python's next set_lighting push --
              // which, on a static scene, may not come at all.
              const renderer::AmbientGradient ag =
                  renderer::ambient_gradient_from_lights(
                      g_lighting.directional_dir_ws, g_lighting.directional_color,
                      g_lighting.directional_count,
                      dauntless_ambient_gradient::strength());
              g_lighting.ambient_dir_ws   = ag.dir_ws;
              g_lighting.ambient_gradient = ag.strength;
          },
          py::arg("strength"),
          "Directional-ambient strength, clamped to [0, 1]. 0 is the stock "
          "flat ambient (byte-identical).");

    m.def("ambient_gradient_get",
          []() { return dauntless_ambient_gradient::strength(); },
          "Current directional-ambient strength.");
```

In `engine/renderer.py`, add `"ambient_gradient_get"` and `"ambient_gradient_set"` to the expected-name tuple in alphabetical position, then beside `set_smaa_enabled`:

```python
def set_ambient_gradient(strength: float) -> None:
    """Directional-ambient strength, clamped to [0, 1].

    0 is the stock flat ambient and is byte-identical to the pre-gradient
    renderer. 1 swings ambient from 0 at the antipode to 2x on the
    light-facing side. Default 0.6 — biased high for calibration.
    """
    _h.ambient_gradient_set(float(strength))


def ambient_gradient() -> float:
    """Current directional-ambient strength."""
    return float(_h.ambient_gradient_get())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j && \
  uv run pytest tests/unit/test_renderer_ambient_gradient.py -q
```

Expected: PASS. `AttributeError: module '_dauntless_host' has no attribute 'ambient_gradient_set'` means the binary is stale — rebuild the `dauntless` target, do not change the Python side.

- [ ] **Step 5: Run the full gate**

```bash
cmake -B build -S . && ./scripts/check_tests.sh 2>&1 | tail -30
```

Expected: exit 0. Any failure not already in `tests/known_failures.txt` is a regression from this branch.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/frame.cc native/src/host/host_bindings.cc \
        engine/renderer.py tests/unit/test_renderer_ambient_gradient.py
git commit -m "feat(renderer): expose the directional-ambient strength for tuning

Not a player-facing setting -- the spec defers that until the effect has
been seen in motion -- but reachable from Python so it can be calibrated
live. Default 0.6, biased high on purpose: the practice is to calibrate up
and then come down, and a first pass too faint to see wastes the live look.

Clamped to [0, 1] in the setter: past 1.0 the shader term goes negative and
would subtract ambient on the far side."
```

---

## Live verification (Mark, main tree — NOT automatable)

Green tests cannot see whether this makes hulls read as solid, which is the
entire point. After the branch merges and `build/` is rebuilt (a branch switch
desyncs it; a live check on a stale build is worthless):

1. **The basic read.** Any exterior view of the player ship. The shadow side
   should keep shape rather than flattening into a silhouette. Compare against
   `set_ambient_gradient(0.0)`, which is the old look exactly.
2. **Calibrate down from 0.6.** `renderer.set_ambient_gradient(x)` — try 0.6,
   0.4, 0.25. The failure mode to watch for is the hull looking *lit from
   nowhere*: too high and the ambient starts reading as a second light source
   rather than as fill.
3. **Exposure did not move.** Because the term is mean-preserving, overall
   scene brightness should be unchanged between 0.0 and 0.6 — only the
   distribution across the hull. If the whole scene brightens, the shader was
   rewritten into the additive form the spec rejects.
4. **A multi-star set, if one is to hand.** Two stars on opposite sides should
   flatten the gradient toward nothing rather than picking one arbitrarily.
5. **Bridge interiors are untouched.** Walk onto the bridge and confirm
   nothing changed — that path has no vertex normals and must be unaffected.

Then decide the open question the spec left: setting, master-toggle member, or
always-on constant.

---

### Task 4: Fold the gradient under the master, renamed "Cinematic Lighting"

**Added after the plan was approved**, at Mark's request: the directional
ambient joins the existing lighting master rather than getting its own row,
and that master's display label becomes "Cinematic Lighting".

**Files:**
- Modify: `native/src/renderer/frame.cc` (add an enabled-setter beside the strength gate)
- Modify: `native/src/host/host_bindings.cc` (one pybind def)
- Modify: `engine/renderer.py`
- Modify: `engine/ui/configuration_panel.py:70-77` (`MASTER_TOGGLES`)
- Modify: `engine/settings_store.py:278-285` (the master's `_fan`)
- Modify: `native/assets/ui-cef/js/configuration_panel.js:23`
- Modify: `engine/host_loop.py` (the panel's constructor call)
- Test: `tests/unit/test_configuration_panel.py`, `tests/unit/test_settings_store.py`

**Interfaces:**
- Consumes: `dauntless_ambient_gradient::strength()` / `set_strength()` and
  `renderer.set_ambient_gradient` from Task 3.
- Produces: `renderer.set_ambient_gradient_enabled(bool)` in Python;
  `_dauntless_host.ambient_gradient_set_enabled`. The master's applier list
  gains `"ambient_gradient"`, so `ConfigurationPanel` gains a
  `set_ambient_gradient` constructor parameter (the `set_<name>` convention
  `MASTER_TOGGLES` already uses).

**Two decisions carried into this task, both deliberate:**

**The label changes; the KEY does not.** `realistic_lighting` stays as the
settings key, the action string `toggle:realistic_lighting`, the payload key
and the focusable. Renaming it would need a third schema migration and touches
the master-toggle machinery for no functional gain. The divergence between key
and label must be commented at the definition so it reads as a decision rather
than as drift.

**A bool master needs a tuned "on" value, and that constant must have ONE
home.** Do not duplicate `0.6` into the Python applier — add a C++
enabled-setter that restores the gate's own tuned default, so the number lives
only in `frame.cc`. A Python-side copy would silently diverge the first time
the constant is retuned after a live look, which is exactly what it exists to
allow.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_settings_store.py`:

```python
def test_cinematic_lighting_master_drives_the_ambient_gradient():
    """The master is a bool; the gradient is a strength. On must restore the
    engine's tuned default rather than a number copied into Python, so the
    constant can be retuned in one place after a live look."""
    from engine.settings_store import SETTINGS

    row = next(r for r in SETTINGS if r.key == "realistic_lighting")
    ctx = _ctx()
    row.apply(ctx, True)
    ctx.r.set_ambient_gradient_enabled.assert_called_once_with(True)

    ctx = _ctx()
    row.apply(ctx, False)
    ctx.r.set_ambient_gradient_enabled.assert_called_once_with(False)


def test_cinematic_lighting_still_drives_its_four_original_members():
    """Adding a member must not drop one. This is the whole risk of editing a
    master's fan-out."""
    from engine.settings_store import SETTINGS

    row = next(r for r in SETTINGS if r.key == "realistic_lighting")
    ctx = _ctx()
    row.apply(ctx, True)
    ctx.r.set_rim_enabled.assert_called_once_with(True)
    ctx.r.set_shadows_enabled.assert_called_once_with(True)
    ctx.r.set_nebula_lightning_enabled.assert_called_once_with(True)
    ctx.light_emitters.set_enabled.assert_called_once_with(True)
```

Append to `tests/unit/test_configuration_panel.py`:

```python
def test_master_label_is_cinematic_lighting_but_the_key_is_unchanged():
    """The label is player-facing; the key drives the action string, the
    payload key, the focusable and the persisted setting. Renaming the key
    would need a schema migration for a cosmetic change, so it stays."""
    from engine.ui.configuration_panel import MASTER_TOGGLES

    row = next(r for r in MASTER_TOGGLES if r[0] == "realistic_lighting")
    assert row[1] == "Cinematic Lighting"
    assert "ambient_gradient" in row[2]


def test_cinematic_lighting_toggle_fires_the_gradient_applier():
    p, kw = _make()
    p.open()
    assert p.dispatch_event("toggle:realistic_lighting") is True
    kw["set_ambient_gradient"].assert_called_once_with(False)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/unit/test_settings_store.py tests/unit/test_configuration_panel.py -q
```

Expected: FAIL — `AssertionError: 'Realistic Lighting' != 'Cinematic Lighting'` and
`TypeError: __init__() got an unexpected keyword argument 'set_ambient_gradient'`.

- [ ] **Step 3: Add the C++ enabled-setter**

In `native/src/renderer/frame.cc`, extend the `dauntless_ambient_gradient`
namespace added in Task 3:

```cpp
namespace dauntless_ambient_gradient {
    namespace {
        // The tuned "on" value. ONE home for this number: the Python master
        // toggle asks for enabled/disabled and never names a strength, so
        // retuning after a live look is a single-line change here.
        constexpr float kTunedDefault = 0.6f;
        float g_strength = kTunedDefault;
    }
    float strength() { return g_strength; }
    void  set_strength(float v) {
        g_strength = (v < 0.0f) ? 0.0f : (v > 1.0f ? 1.0f : v);
    }
    void  set_enabled(bool on) { g_strength = on ? kTunedDefault : 0.0f; }
}
```

In `native/src/host/host_bindings.cc`, beside the Task 3 defs (and re-resolving
`g_lighting` the same way `ambient_gradient_set` does):

```cpp
    m.def("ambient_gradient_set_enabled",
          [](bool on) {
              dauntless_ambient_gradient::set_enabled(on);
              const renderer::AmbientGradient ag =
                  renderer::ambient_gradient_from_lights(
                      g_lighting.directional_dir_ws, g_lighting.directional_color,
                      g_lighting.directional_count,
                      dauntless_ambient_gradient::strength());
              g_lighting.ambient_dir_ws   = ag.dir_ws;
              g_lighting.ambient_gradient = ag.strength;
          },
          py::arg("enabled"),
          "Directional ambient on/off for the Cinematic Lighting master. On "
          "restores the engine's tuned strength; off is 0 (the stock path).");
```

In `engine/renderer.py`, add `"ambient_gradient_set_enabled"` to the
expected-name tuple and, beside `set_ambient_gradient`:

```python
def set_ambient_gradient_enabled(enabled: bool) -> None:
    """Directional ambient on/off, for the Cinematic Lighting master.

    On restores the engine's tuned strength rather than a value passed from
    Python, so that constant has exactly one home and retuning it after a
    live look is a single change in frame.cc.
    """
    _h.ambient_gradient_set_enabled(bool(enabled))
```

- [ ] **Step 4: Rename the label and add the member**

In `engine/ui/configuration_panel.py`, replace the `realistic_lighting` row:

```python
    # NOTE label vs key: the row reads "Cinematic Lighting" but the key stays
    # `realistic_lighting`. The key drives the action string, the payload key,
    # the focusable AND the persisted settings key, so renaming it would need
    # a schema migration for a purely cosmetic change. The divergence is
    # deliberate — do not "fix" it without one.
    ("realistic_lighting", "Cinematic Lighting",
     ("rim", "shadows", "nebula_lightning", "ship_light_emitters",
      "ambient_gradient")),
```

Add the constructor parameter beside the other master-member appliers:

```python
                 set_ambient_gradient: Callable[[bool], None],
```

and register it in the `self._appliers` dict:

```python
            "ambient_gradient": set_ambient_gradient,
```

In `engine/settings_store.py`, add the fifth applier to the master's `_fan`:

```python
            _fan(lambda c, v: c.r.set_rim_enabled(v),
                 lambda c, v: c.r.set_shadows_enabled(v),
                 lambda c, v: c.r.set_nebula_lightning_enabled(v),
                 lambda c, v: c.light_emitters.set_enabled(v),
                 lambda c, v: c.r.set_ambient_gradient_enabled(v)),
```

In `native/assets/ui-cef/js/configuration_panel.js:23`, change the label:

```js
    ['realistic_lighting', 'Cinematic Lighting'],
```

In `engine/host_loop.py`, add to the `ConfigurationPanel(...)` call beside
`set_ship_light_emitters`:

```python
            set_ambient_gradient=r.set_ambient_gradient_enabled,
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j
uv run pytest tests/unit/test_settings_store.py tests/unit/test_configuration_panel.py -q
grep -rn "Realistic Lighting" engine/ native/assets/ tests/ | grep -v "\.pyc"
```

Expected: tests PASS. The grep should return only *comments* mentioning the
old name — update those to "Cinematic Lighting" too so the codebase reads
consistently (`engine/host_loop.py`, `engine/appc/light_emitters.py`,
`tests/test_host_loop_emitter_lights.py`, `tests/conftest.py`).

- [ ] **Step 6: Run the full gate**

```bash
cmake -B build -S . && ./scripts/check_tests.sh 2>&1 | tail -30
```

Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/frame.cc native/src/host/host_bindings.cc \
        engine/renderer.py engine/ui/configuration_panel.py \
        engine/settings_store.py engine/host_loop.py \
        native/assets/ui-cef/js/configuration_panel.js \
        tests/unit/test_configuration_panel.py tests/unit/test_settings_store.py
git commit -m "feat(ui): fold directional ambient into Cinematic Lighting

The lighting master gains the directional ambient as a fifth member and is
relabelled from 'Realistic Lighting'. The KEY stays realistic_lighting: it
drives the action string, payload key, focusable and persisted setting, so
renaming it would need a schema migration for a cosmetic change.

A bool master needs a tuned 'on' strength, and that constant lives only in
frame.cc -- Python asks for enabled/disabled and never names a number, so
retuning after a live look stays a one-line change."
```
