# Persistent Damage Decals — Phase 2 (Shading) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the Phase-1 decal ring on the hull — body-space scorch + heat-glow composited in `opaque.frag` — proving the mirroring bug is gone.

**Architecture:** `draw_model` packs each instance's active decal ring into `vec4[24]` uniform arrays (converting radius GU→model units via the world-matrix scale) plus the inverse ship matrix and a game-time clock; `opaque.frag` reconstructs the body-frame fragment position, loops the decals with a normal-aware falloff (the mirroring fix), and composites procedural-fbm spread-B scorch + a game-time blackbody ember and a transient phaser glow. A `dauntless_decals` runtime toggle (default on) gates the whole thing.

**Tech Stack:** C++20, glm, GLSL 330, GoogleTest (offscreen llvmpipe render tests), pybind11 (toggle binding). Single canonical `build/` tree (per CLAUDE.md). Module is `_dauntless_host`.

**Spec:** [`docs/superpowers/specs/2026-06-08-persistent-damage-decals-phase2-shading-design.md`](../specs/2026-06-08-persistent-damage-decals-phase2-shading-design.md).

**Branch:** continue on `feat/damage-decals-phase1` (Phase 2 stacks on Phase 1 — do not branch from main).

> **Shader builds:** changing a `.vert`/`.frag` requires a `cmake -B build -S .` reconfigure (shaders are embedded at configure time), not just `cmake --build`. Every task that edits a shader reconfigures.

---

## File Structure

**Modified:**
- `native/src/renderer/frame.cc` — add the `dauntless_decals` toggle namespace; extend `draw_model` to pack decal uniforms (incl. radius GU→model conversion + game clock); thread `decal_time` through `submit_opaque` / `submit_opaque_in_pass`.
- `native/src/renderer/include/renderer/frame.h` — add the trailing `decal_time` param (defaulted) to the two submit methods.
- `native/src/renderer/shaders/opaque.frag` — decal uniforms + `apply_damage_decals(...)` recipe.
- `native/src/host/host_bindings.cc` — `g_decal_game_time` global captured in `damage_decals_tick`; pass it into `submit_opaque_in_pass`; `dauntless_decals` forward-decl + `decals_set_enabled` binding.
- `native/tests/renderer/frame_test.cc` — update existing `submit_opaque*` call sites if needed (defaulted param means no change required) and add the decal render tests. (If this file grows unwieldy, a sibling `decal_shading_test.cc` is acceptable — see Task 3.)

No change to `opaque.vert` (`v_position_ws` / `v_normal_ws` already exist), the Phase-1 ring, the combat/emission path, or the host loop's per-tick structure.

---

## Task 1: `dauntless_decals` toggle + host binding

Mirror the existing `dauntless_specular` toggle exactly.

**Files:**
- Modify: `native/src/renderer/frame.cc` (toggle namespace, near the other toggles ~line 25-55)
- Modify: `native/src/host/host_bindings.cc` (forward-decl ~line 366-372; binding near `specular_set_enabled`)
- Test: `native/tests/renderer/frame_test.cc` (toggle round-trip)

- [ ] **Step 1: Write the failing test**

Add to `native/tests/renderer/frame_test.cc` (after the includes; it needs no GL context, so it's a plain `TEST`, not `TEST_F`):

```cpp
// dauntless_decals toggle is declared in frame.cc; forward-declare both here.
namespace dauntless_decals { bool enabled(); void set_enabled(bool); }

TEST(DauntlessDecalsToggle, DefaultsOnAndRoundTrips) {
    EXPECT_TRUE(dauntless_decals::enabled());     // default on
    dauntless_decals::set_enabled(false);
    EXPECT_FALSE(dauntless_decals::enabled());
    dauntless_decals::set_enabled(true);          // restore for other tests
    EXPECT_TRUE(dauntless_decals::enabled());
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests
```

Expected: LINK error — `dauntless_decals::enabled()` / `set_enabled` undefined.

- [ ] **Step 3: Add the toggle namespace in frame.cc**

In `native/src/renderer/frame.cc`, immediately after the `dauntless_hdr` namespace block (the one that ends around line 55, before `namespace renderer {`), add:

```cpp
// Toggle for the opaque-pass persistent damage decals (Phase 2). Default on
// so the "Modern VFX" group ships enabled. host_bindings.cc forward-declares
// set_enabled; draw_model reads enabled() per instance and uploads
// u_decal_count = 0 when off (stock-BC hull, no per-fragment decal cost).
namespace dauntless_decals {
namespace {
    bool g_decals_enabled = true;
}
    bool enabled() { return g_decals_enabled; }
    void set_enabled(bool v) { g_decals_enabled = v; }
}
```

- [ ] **Step 4: Add the host binding**

In `native/src/host/host_bindings.cc`, next to the other toggle forward-declarations (~line 366, where `dauntless_specular` / `dauntless_rim` are forward-declared), add:

```cpp
namespace dauntless_decals {
    void set_enabled(bool v);  // defined in frame.cc
}
```

Then, next to the `m.def("specular_set_enabled", ...)` binding, add:

```cpp
    m.def("decals_set_enabled",
          [](bool enabled) { dauntless_decals::set_enabled(enabled); },
          py::arg("enabled"),
          "Enable/disable persistent hull damage decals (default on).");
```

- [ ] **Step 5: Reconfigure, build, run the test**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "DauntlessDecalsToggle" --output-on-failure
```

Expected: `DauntlessDecalsToggle.DefaultsOnAndRoundTrips` PASS. Also confirm the binding:

```bash
python3 -c "import sys; sys.path.insert(0,'build/python'); import _dauntless_host as h; print('decals_set_enabled:', hasattr(h,'decals_set_enabled'))"
```

Expected: `decals_set_enabled: True`.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/frame.cc native/src/host/host_bindings.cc native/tests/renderer/frame_test.cc
git commit -m "$(printf 'feat(renderer): dauntless_decals runtime toggle + binding\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 2: Decal upload plumbing (C++) — no shader read yet

Pack the ring into uniforms and thread the game clock. The shader does not declare these uniforms yet, so `glGetUniformLocation` returns -1 and the `set_*` calls are harmless no-ops — i.e. **a damaged ship still renders identically to baseline**, which is exactly what the test asserts (proving the packing path is wired and crash-free).

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h` (submit signatures)
- Modify: `native/src/renderer/frame.cc` (`draw_model` packing; thread `decal_time`)
- Modify: `native/src/host/host_bindings.cc` (`g_decal_game_time` capture + pass-through)
- Test: `native/tests/renderer/frame_test.cc`

- [ ] **Step 1: Write the failing test**

Add to `native/tests/renderer/frame_test.cc` (a `TEST_F(FrameTest, ...)`, so it uses the Galaxy fixture):

```cpp
TEST_F(FrameTest, DecalUploadDoesNotAlterRenderBeforeShaderReads) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    // Seed a scorch decal in the ring (body frame). At this task's stage the
    // shader ignores decal uniforms, so this must NOT change the output.
    world.get(iid)->decals.add(glm::vec3(0, 0, 0), glm::vec3(0, 0, 1),
                               /*radius=*/200.0f, /*intensity=*/1.0f,
                               scenegraph::WeaponClass::Scorch, /*now=*/0.0f);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;

    glViewport(0, 0, 256, 256);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    submitter.submit_opaque_in_pass(world, cam, *p, lut, lighting,
                                    scenegraph::Pass::Space, /*decal_time=*/0.0f);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    unsigned char px[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    EXPECT_GT(px[0] + px[1] + px[2], 0) << "center pixel black; pack path broke the draw";
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake --build build -j --target renderer_tests
```

Expected: COMPILE error — `submit_opaque_in_pass` has no 7th `decal_time` parameter yet.

- [ ] **Step 3: Add the `decal_time` param to the submit signatures**

In `native/src/renderer/include/renderer/frame.h`, change the two declarations to add a trailing defaulted param:

```cpp
    void submit_opaque(const scenegraph::World& world,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline,
                       const ModelLookup& lookup,
                       const Lighting& lighting,
                       float decal_time = 0.0f);

    void submit_opaque_in_pass(const scenegraph::World& world,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline,
                               const ModelLookup& lookup,
                               const Lighting& lighting,
                               scenegraph::Pass pass,
                               float decal_time = 0.0f);
```

- [ ] **Step 4: Extend `draw_model` to pack decal uniforms**

In `native/src/renderer/frame.cc`, ensure the decal header is available (add near the top includes if not already transitively present):

```cpp
#include <scenegraph/damage_decals.h>
```

Change the `draw_model` signature (the free function ~line 60) to add the ring and time:

```cpp
void draw_model(const assets::Model& model,
                const glm::mat4& world,
                Shader& shader,
                GLuint white_fallback,
                GLuint black_fallback,
                bool rim_active,
                const scenegraph::DamageDecalRing& decals,
                float decal_time) {
```

At the **start** of `draw_model`'s body (before the `std::vector<glm::mat4> world_per_node` line — these are per-instance uniforms, set once for all the instance's nodes), insert:

```cpp
    // ── Per-instance damage decals (Phase 2) ───────────────────────────────
    // Pack the active ring into vec4 arrays. point_body is in NIF/model units
    // (the ship scale lives in `world`), so convert radius GU->model units via
    // the world-matrix scale s = |world's X column|. u_decal_count == 0 when
    // disabled or empty makes the shader skip the loop entirely.
    {
        glm::vec4 a[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 b[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 c[scenegraph::DamageDecalRing::kMaxDecals];
        int n = 0;
        if (dauntless_decals::enabled()) {
            const float s = glm::length(glm::vec3(world[0]));   // uniform scale
            const float inv_s = (s > 0.0f) ? (1.0f / s) : 1.0f;
            for (const auto& d : decals.slots()) {
                if (!d.active) continue;
                a[n] = glm::vec4(d.point_body, d.intensity);
                b[n] = glm::vec4(d.normal_body, d.radius * inv_s);  // GU->model
                c[n] = glm::vec4(d.birth_time,
                                 static_cast<float>(static_cast<std::uint32_t>(d.weapon_class)),
                                 0.0f, 0.0f);
                ++n;
            }
        }
        shader.set_int("u_decal_count", n);
        if (n > 0) {
            shader.set_vec4_array("u_decal_a", a, n);
            shader.set_vec4_array("u_decal_b", b, n);
            shader.set_vec4_array("u_decal_c", c, n);
            shader.set_mat4("u_ship_world_inv", glm::inverse(world));
            shader.set_float("u_decal_time", decal_time);
        }
    }
```

Then update the two `draw_model(...)` call sites inside `submit_opaque` and `submit_opaque_in_pass` to pass the ring and time. Find each `draw_model(*m, inst.world, shader, white, black, rim_active);` and change to:

```cpp
        if (m) draw_model(*m, inst.world, shader, white, black, rim_active,
                          inst.decals, decal_time);
```

Both `submit_opaque` and `submit_opaque_in_pass` must accept and forward `decal_time` (the lambda captures it). The instance in the `for_each_visible*` callback is `inst` (a `const scenegraph::Instance&`), so `inst.decals` is available.

- [ ] **Step 5: Capture the game clock in the host and pass it to the pass**

In `native/src/host/host_bindings.cc`, near the other frame-scoped globals (e.g. `g_prev_frame_time_seconds` ~line 98), add:

```cpp
float g_decal_game_time = 0.0f;  // game-time secs for decal ember; set by damage_decals_tick
```

In the `damage_decals_tick` binding lambda, capture the time (it already receives the game clock each frame):

```cpp
    m.def("damage_decals_tick",
          [](float time) {
              g_decal_game_time = time;
              g_world.for_each_alive([&](scenegraph::Instance& inst) {
                  inst.decals.tick(time);
              });
          },
          py::arg("time"),
          "Age every instance's decal ring; reclaim cold heat-glow decals.");
```

In `frame()`, change the `submit_opaque_in_pass(...)` call to pass the clock:

```cpp
    g_submitter->submit_opaque_in_pass(
        g_world, g_camera, *g_pipeline, lookup, g_lighting,
        scenegraph::Pass::Space, g_decal_game_time);
```

- [ ] **Step 6: Reconfigure, build, run the test**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "FrameTest|DauntlessDecalsToggle" --output-on-failure
```

Expected: `DecalUploadDoesNotAlterRenderBeforeShaderReads` PASS (center pixel still lit; no GL error) and all pre-existing `FrameTest.*` still PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/frame.cc native/src/renderer/include/renderer/frame.h \
        native/src/host/host_bindings.cc native/tests/renderer/frame_test.cc
git commit -m "$(printf 'feat(renderer): upload decal ring uniforms in draw_model\n\nPacks active decals to vec4 arrays (radius GU->model), threads the game\nclock; shader does not read them yet. No visual change.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 3: Shader — body-space reconstruction, normal-aware falloff, flat scorch (the mirroring fix)

The architecture-proving task: decals now darken the hull, in body space, with the back-face-killing normal falloff. Flat soot only — no noise, no ember, no phaser yet.

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`
- Test: `native/tests/renderer/frame_test.cc` (decal render tests)

- [ ] **Step 1: Write the failing tests**

Add a small region-average helper and the tests to `native/tests/renderer/frame_test.cc`. (If `frame_test.cc` feels overloaded, create `native/tests/renderer/decal_shading_test.cc` instead, copying the `FrameTest` fixture's SetUp and adding the file to `native/tests/renderer/CMakeLists.txt`'s `renderer_tests` sources. Either is fine; keep one fixture.)

```cpp
namespace {
// Mean of channel-sum over a w×h block whose lower-left is (x0,y0).
double block_mean(int x0, int y0, int w, int h) {
    std::vector<unsigned char> buf(static_cast<size_t>(w) * h * 4);
    glReadPixels(x0, y0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
    double acc = 0.0;
    for (int i = 0; i < w * h; ++i)
        acc += buf[i*4] + buf[i*4+1] + buf[i*4+2];
    return acc / (w * h);
}

template <class Lut>
void render_galaxy(scenegraph::World& world, renderer::Pipeline& p,
                   Lut&& lut, float decal_time) {
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0, 0, 1500); cam.target = glm::vec3(0);
    cam.aspect = 1.0f;
    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    glViewport(0, 0, 256, 256);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    submitter.submit_opaque_in_pass(world, cam, p, lut, lighting,
                                    scenegraph::Pass::Space, decal_time);
}
}  // namespace

TEST_F(FrameTest, ScorchDecalDarkensHullAndDoesNotMirror) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // ── Baseline: undamaged ──
    scenegraph::World w0;
    auto i0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(i0, glm::mat4(1.0f));
    render_galaxy(w0, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    // Left and right saucer regions, symmetric about screen center x=128.
    const double L0 = block_mean(40, 108, 40, 40);
    const double R0 = block_mean(176, 108, 40, 40);

    // ── Damaged: scorch on the +X (right) half of the saucer top ──
    scenegraph::World w1;
    auto i1 = w1.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w1.set_world_transform(i1, glm::mat4(1.0f));
    // Body +X point on the top surface (+Z normal faces the camera). Generous
    // radius so the right region clearly registers; the −X half is far outside.
    w1.get(i1)->decals.add(glm::vec3(180.0f, 0.0f, 60.0f), glm::vec3(0, 0, 1),
                           /*radius=*/180.0f, /*intensity=*/1.0f,
                           scenegraph::WeaponClass::Scorch, 0.0f);
    render_galaxy(w1, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double L1 = block_mean(40, 108, 40, 40);
    const double R1 = block_mean(176, 108, 40, 40);

    // Right half darkened by the scorch deposit.
    EXPECT_LT(R1, R0 * 0.95) << "scorch did not darken the struck (right) half";
    // THE REGRESSION: the mirror (left) half is essentially unchanged — body-
    // frame anchoring + normal-aware falloff means no cross-contamination.
    EXPECT_NEAR(L1, L0, L0 * 0.05) << "damage leaked onto the mirror (left) half";
}

TEST_F(FrameTest, ScorchToggleOffRendersLikeUndamaged) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    scenegraph::World w;
    auto iid = w.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w.set_world_transform(iid, glm::mat4(1.0f));
    w.get(iid)->decals.add(glm::vec3(180, 0, 60), glm::vec3(0, 0, 1),
                           180.0f, 1.0f, scenegraph::WeaponClass::Scorch, 0.0f);

    dauntless_decals::set_enabled(false);
    render_galaxy(w, *p, lut, 0.0f);
    const double R_off = block_mean(176, 108, 40, 40);
    dauntless_decals::set_enabled(true);
    render_galaxy(w, *p, lut, 0.0f);
    const double R_on = block_mean(176, 108, 40, 40);
    dauntless_decals::set_enabled(true);  // leave enabled

    EXPECT_LT(R_on, R_off * 0.97) << "decals-on should differ from decals-off";
    EXPECT_GT(R_off, 0.0);
}
```

> Note: the seed point `(180,0,60)`, the radius `180`, the sample blocks, and the `0.95`/`0.05` thresholds are first estimates against the Galaxy at this camera. If a threshold is borderline when first run, adjust the seed/region/threshold to robustly capture "right darkened, left unchanged" — the *assertions' intent* (struck side darkens, mirror side doesn't) is the contract, not the exact numbers.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cmake --build build -j --target renderer_tests && ctest --test-dir build -R "ScorchDecal|ScorchToggle" --output-on-failure
```

Expected: FAIL — the shader doesn't composite decals yet, so the right half does not darken.

- [ ] **Step 3: Add the decal recipe to `opaque.frag`**

In `native/src/renderer/shaders/opaque.frag`, add the uniforms after the existing uniform block (e.g. after the directional-light uniforms, before `out vec4 frag_color;`):

```glsl
// ── Persistent damage decals (Phase 2) ──────────────────────────────────
const int MAX_DECALS = 24;
uniform int   u_decal_count;                 // 0 disables the loop entirely
uniform vec4  u_decal_a[MAX_DECALS];         // point_body.xyz, intensity
uniform vec4  u_decal_b[MAX_DECALS];         // normal_body.xyz, radius (model units)
uniform vec4  u_decal_c[MAX_DECALS];         // birth_time, weapon_class, _, _
uniform mat4  u_ship_world_inv;              // inverse(ship world): world->body
uniform float u_decal_time;                  // game-time seconds (ember clock)

const float NORMAL_MIN = 0.15;               // back-face cutoff for falloff
const vec3  SOOT_COLOR = vec3(0.06, 0.05, 0.045);

// Flat scorch for Task 3: dark soot deposit, normal-aware, body-space.
// base_lit is composited toward soot; emissive is left untouched here
// (noise + ember + phaser land in Tasks 4-5).
void apply_damage_decals(vec3 p_body, vec3 n_body,
                         inout vec3 base_lit, inout vec3 emissive) {
    for (int i = 0; i < u_decal_count; ++i) {
        vec3  point = u_decal_a[i].xyz;
        float intensity = u_decal_a[i].w;
        vec3  dn = u_decal_b[i].xyz;
        float radius = u_decal_b[i].w;
        if (radius <= 0.0) continue;

        float r = length(p_body - point) / radius;          // 0 at center, 1 at edge
        if (r >= 1.0) continue;
        float wn = smoothstep(NORMAL_MIN, 1.0, dot(n_body, dn));  // mirroring fix
        if (wn <= 0.0) continue;

        float core = 1.0 - smoothstep(0.0, 1.0, r);          // soft radial
        float deposit = clamp(core, 0.0, 1.0) * intensity * wn;
        base_lit = mix(base_lit, SOOT_COLOR, deposit);
    }
}
```

Then, in `main()`, after the line that computes `vec3 lit = (u_ambient_light + lit_dir) * u_diffuse_color * base.rgb;`, add the body-space reconstruction and the call, and a `decal_emissive` accumulator:

```glsl
    // Reconstruct body-frame fragment pos/normal for object-space decals.
    vec3 p_body = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz;
    vec3 n_body = normalize(mat3(u_ship_world_inv) * v_normal_ws);
    vec3 decal_emissive = vec3(0.0);
    if (u_decal_count > 0) {
        apply_damage_decals(p_body, n_body, lit, decal_emissive);
    }
```

Finally, change the output line to add `decal_emissive`:

```glsl
    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a + spec + rim + decal_emissive, 1.0);
```

- [ ] **Step 4: Reconfigure, build, run the tests**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "ScorchDecal|ScorchToggle|FrameTest" --output-on-failure
```

Expected: `ScorchDecalDarkensHullAndDoesNotMirror` and `ScorchToggleOffRendersLikeUndamaged` PASS; pre-existing `FrameTest.*` still PASS. If a threshold is borderline, tune per the Step-1 note and re-run (do not weaken the mirror assertion's intent).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/tests/renderer/frame_test.cc
git commit -m "$(printf 'feat(renderer): composite body-space scorch decals in opaque.frag\n\nNormal-aware falloff kills mirror-half bleed (the bug that sank the UV\napproach). Flat soot deposit; noise/ember/phaser follow.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 4: Shader — procedural noise (spread-B ejecta) + game-time blackbody ember

Promote the flat soot to the locked Phase-1 look: noise-broken radial ejecta + a white→red ember that cools over ~10 s on the game clock.

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`
- Test: `native/tests/renderer/frame_test.cc`

- [ ] **Step 1: Write the failing test**

The ember is emissive and game-time-keyed: a fresh scorch glows; an aged one does not. Add:

```cpp
TEST_F(FrameTest, ScorchEmberIsBrightWhenFreshAndCoolsWithGameTime) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    scenegraph::World w;
    auto iid = w.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w.set_world_transform(iid, glm::mat4(1.0f));
    // birth_time = 0; ember keyed on (u_decal_time - birth_time).
    w.get(iid)->decals.add(glm::vec3(180, 0, 60), glm::vec3(0, 0, 1),
                           180.0f, 1.0f, scenegraph::WeaponClass::Scorch, 0.0f);

    render_galaxy(w, *p, lut, /*decal_time=*/0.2f);   // fresh: hot ember
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double fresh = block_mean(176, 108, 40, 40);

    render_galaxy(w, *p, lut, /*decal_time=*/30.0f);  // long after T_EMBER: cold
    const double cold = block_mean(176, 108, 40, 40);

    // The fresh ember adds emissive brightness; once cold only the soot deposit
    // remains, which is darker than the glowing-fresh state.
    EXPECT_GT(fresh, cold) << "ember did not brighten the fresh scorch, or did not cool";
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
cmake --build build -j --target renderer_tests && ctest --test-dir build -R "ScorchEmber" --output-on-failure
```

Expected: FAIL — Task 3's recipe has no ember, so fresh ≈ cold.

- [ ] **Step 3: Replace `apply_damage_decals` with the noise+ember version**

In `native/src/renderer/shaders/opaque.frag`, add these helpers above `apply_damage_decals` (after the `SOOT_COLOR` const):

```glsl
const float EMBER_TIGHT = 6.0;
const float EMBER_BROAD = 2.0;
const float T_EMBER     = 10.0;   // seconds to cold
const float NOISE_SCALE = 0.03;   // 1/model-units; tuned for NIF-scale p_body

float dhash(vec2 v) { return fract(sin(dot(v, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 v) {
    vec2 i = floor(v), f = fract(v);
    float a = dhash(i), b = dhash(i + vec2(1,0));
    float c = dhash(i + vec2(0,1)), d = dhash(i + vec2(1,1));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 v) {
    float s = 0.0, amp = 0.5, freq = 1.0;
    for (int i = 0; i < 3; ++i) { s += amp * vnoise(v * freq); freq *= 2.1; amp *= 0.5; }
    return s;
}
// Blackbody-ish ramp keyed on heat 0..1 (white-hot -> red -> black).
vec3 blackbody(float heat) {
    vec3 cold = vec3(0.0);
    vec3 red  = vec3(0.59, 0.10, 0.02);
    vec3 org  = vec3(1.0, 0.45, 0.08);
    vec3 white= vec3(1.0, 0.92, 0.72);
    vec3 lo = mix(cold, red, smoothstep(0.0, 0.35, heat));
    vec3 mid= mix(lo, org, smoothstep(0.35, 0.7, heat));
    return mix(mid, white, smoothstep(0.7, 1.0, heat));
}
```

Then replace the body of `apply_damage_decals` with:

```glsl
void apply_damage_decals(vec3 p_body, vec3 n_body,
                         inout vec3 base_lit, inout vec3 emissive) {
    for (int i = 0; i < u_decal_count; ++i) {
        vec3  point = u_decal_a[i].xyz;
        float intensity = u_decal_a[i].w;
        vec3  dn = u_decal_b[i].xyz;
        float radius = u_decal_b[i].w;
        if (radius <= 0.0) continue;

        vec3  dvec = (p_body - point) / radius;
        float r = length(dvec);
        if (r >= 1.0) continue;
        float wn = smoothstep(NORMAL_MIN, 1.0, dot(n_body, dn));   // mirroring fix
        if (wn <= 0.0) continue;

        // Spread-B: dense core + noise-broken radial ejecta thinning with r.
        float core   = exp(-r * r * 3.0);
        float nval   = fbm(p_body.xy * NOISE_SCALE + p_body.z * NOISE_SCALE);
        float reach  = 0.35 + nval * 0.9;
        float ejecta = max(0.0, (reach - r) / reach) * pow(nval, 1.5) * 1.3;
        float deposit = clamp(core + ejecta, 0.0, 1.0) * intensity * wn;
        base_lit = mix(base_lit, SOOT_COLOR, deposit);

        // Game-time blackbody ember (Scorch only; weapon_class 1).
        if (u_decal_c[i].y > 0.5) {
            float age  = max(0.0, u_decal_time - u_decal_c[i].x);
            float heat = exp(-age / (T_EMBER / 3.2));            // ~0 by 10 s
            float glow = (exp(-r * r * EMBER_BROAD) + exp(-r * r * EMBER_TIGHT));
            emissive += blackbody(heat) * glow * heat * wn * intensity;
        }
    }
}
```

- [ ] **Step 4: Reconfigure, build, run**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "ScorchEmber|ScorchDecal|ScorchToggle|FrameTest" --output-on-failure
```

Expected: `ScorchEmberIsBrightWhenFreshAndCoolsWithGameTime` PASS, and the Task-3 tests (`ScorchDecalDarkensHullAndDoesNotMirror`, toggle) still PASS. Tune `NOISE_SCALE` / ember constants if the mirror or darken thresholds drift; keep all assertions' intent intact.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/tests/renderer/frame_test.cc
git commit -m "$(printf 'feat(renderer): noise ejecta + game-time blackbody ember for scorch\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 5: Shader — phaser heat-glow class

Add the transient phaser branch: additive emissive bloom, no deposit, fades by `T_GLOW`.

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`
- Test: `native/tests/renderer/frame_test.cc`

- [ ] **Step 1: Write the failing test**

```cpp
TEST_F(FrameTest, PhaserHeatGlowIsTransientAndLeavesNoScar) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    scenegraph::World w;
    auto iid = w.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w.set_world_transform(iid, glm::mat4(1.0f));
    w.get(iid)->decals.add(glm::vec3(180, 0, 60), glm::vec3(0, 0, 1),
                           180.0f, 1.0f, scenegraph::WeaponClass::HeatGlow, 0.0f);

    // Undamaged baseline for the same region.
    scenegraph::World w0;
    auto i0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(i0, glm::mat4(1.0f));
    render_galaxy(w0, *p, lut, 0.0f);
    const double base = block_mean(176, 108, 40, 40);

    render_galaxy(w, *p, lut, /*decal_time=*/0.1f);   // fresh glow
    const double fresh = block_mean(176, 108, 40, 40);
    render_galaxy(w, *p, lut, /*decal_time=*/2.0f);   // past T_GLOW (1.2s)
    const double faded = block_mean(176, 108, 40, 40);

    EXPECT_GT(fresh, base * 1.02) << "fresh phaser glow should brighten the hull";
    EXPECT_NEAR(faded, base, base * 0.03) << "phaser glow should leave no scar after T_GLOW";
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
cmake --build build -j --target renderer_tests && ctest --test-dir build -R "PhaserHeatGlow" --output-on-failure
```

Expected: FAIL — HeatGlow decals (`weapon_class == 0`) currently fall through the Scorch path: they deposit soot (a scar) and have no transient additive glow, so `faded` won't return to baseline.

- [ ] **Step 3: Branch on weapon class in `apply_damage_decals`**

In `native/src/renderer/shaders/opaque.frag`, add the glow constant near the others:

```glsl
const float T_GLOW = 1.2;   // seconds; phaser heat-glow lifetime
```

In `apply_damage_decals`, replace the deposit/ember section (everything after the `wn` early-out) so Scorch and HeatGlow take different branches:

```glsl
        if (u_decal_c[i].y < 0.5) {
            // HeatGlow (phaser): additive emissive bloom, NO deposit, fades by T_GLOW.
            float age = max(0.0, u_decal_time - u_decal_c[i].x);
            float life = clamp(1.0 - age / T_GLOW, 0.0, 1.0);
            float glow = exp(-r * r * 5.0) * life;
            emissive += blackbody(0.6 + 0.4 * life) * glow * wn * intensity;
            continue;
        }

        // Scorch (torpedo/disruptor): deposit + ember.
        float core   = exp(-r * r * 3.0);
        float nval   = fbm(p_body.xy * NOISE_SCALE + p_body.z * NOISE_SCALE);
        float reach  = 0.35 + nval * 0.9;
        float ejecta = max(0.0, (reach - r) / reach) * pow(nval, 1.5) * 1.3;
        float deposit = clamp(core + ejecta, 0.0, 1.0) * intensity * wn;
        base_lit = mix(base_lit, SOOT_COLOR, deposit);

        float age2  = max(0.0, u_decal_time - u_decal_c[i].x);
        float heat  = exp(-age2 / (T_EMBER / 3.2));
        float eglow = (exp(-r * r * EMBER_BROAD) + exp(-r * r * EMBER_TIGHT));
        emissive += blackbody(heat) * eglow * heat * wn * intensity;
```

(Remove the old `if (u_decal_c[i].y > 0.5) { ... }` ember block from Task 4 — its logic now lives in the Scorch branch above. The function keeps the loop header, the unpack, the `radius<=0`/`r>=1`/`wn` early-outs from Task 4, then this branch.)

- [ ] **Step 4: Reconfigure, build, run all decal tests**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "Phaser|Scorch|FrameTest" --output-on-failure
```

Expected: `PhaserHeatGlowIsTransientAndLeavesNoScar` PASS and all Scorch/Frame tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/tests/renderer/frame_test.cc
git commit -m "$(printf 'feat(renderer): transient phaser heat-glow decal class\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 6: Full Phase 2 verification

No new code — confirm the whole slice builds and renders.

- [ ] **Step 1: Clean reconfigure + build**

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: `build/dauntless` + `build/python/_dauntless_host.cpython-*.so` build clean.

- [ ] **Step 2: Run the full renderer + scenegraph test set**

```bash
ctest --test-dir build -R "Decal|Scorch|Phaser|Frame|DamageDecal|World" --output-on-failure
```

Expected: all PASS — the Phase-1 ring tests, the toggle, the upload no-op test, and the four decal render tests (mirroring regression, toggle-off, ember cooling, phaser transient).

- [ ] **Step 3: Confirm the toggle binding on the built module**

```bash
python3 -c "import sys; sys.path.insert(0,'build/python'); import _dauntless_host as h; print('decals_set_enabled:', hasattr(h,'decals_set_enabled'))"
```

Expected: `decals_set_enabled: True`.

- [ ] **Step 4: Confirm clean tree**

```bash
git status --short
```

Expected: clean (all committed). Phase 2 complete.

---

## Done criteria

- Hull renders body-space scorch (noise ejecta + game-time blackbody ember) and transient phaser heat-glow, composited inline in `opaque.frag`.
- **The mirroring regression test is green** — a +X decal darkens the struck half and leaves the −X mirror unchanged. This is the proof the object-space pivot fixed the bug that sank the UV approach.
- `dauntless_decals` toggle (default on) flips decals off → stock-BC hull; undamaged ships unaffected.
- Ember cools on the game clock (frozen on pause), consistent with `birth_time`.
- Radius unit conversion (GU→model) is applied at pack time; decals are correctly sized in-game.

When Phase 2 merges, annotate the parent spec's Phase 2 section `shipped <date>` and fold the final tuning constants into the Phase-2 spec §6.

## Note for the implementer on render-test thresholds

The render tests assert *relative* brightness changes (struck region darker; mirror region unchanged; ember fresh>cold; glow fades to baseline). The seed points, sample blocks, and percentage thresholds are first estimates against the Galaxy at the fixed test camera. The asset is real (loaded from `game/`), so exact pixel values depend on the model; if a threshold is marginal on first run, adjust seed/region/threshold to robustly capture the stated intent — never weaken the **mirror-half-unchanged** assertion, which is the whole point of the phase. If BC assets are absent the tests `GTEST_SKIP` (same as the existing `FrameTest`).
