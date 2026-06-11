# Particle Backend A1 (Smoke) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stateless-analytic billboard particle renderer + a real `AnimTSParticleController` so SDK `Effects.py` smoke factories run unmodified, then wire the Spec B `ParticleBackend` so subsystem plumes render for real.

**Architecture:** Python `AnimTSParticleController` objects store keyframe curves + emit params (no simulation). A module registry snapshots active controllers to per-frame `ParticleEmitterDescriptor`s pushed to C++ (the established `set_hit_vfx` pattern). A new `ParticlePass` computes each particle's position/size/colour/alpha **analytically** from emitter age + hashing + keyframe curves, reusing the existing `hit_vfx` billboard shader (alpha-blended). Spec B's `set_backend(ParticleBackend())` flips its plumes from `NullBackend` to live.

**Tech Stack:** C++17 + OpenGL (renderer pass, gtest), pybind11 (host binding), Python 3 + pytest (controller/registry/backend), the existing `engine/appc` + `App.py` shim layer.

**Spec:** [`docs/superpowers/specs/2026-06-11-particle-backend-a1-smoke-design.md`](../specs/2026-06-11-particle-backend-a1-smoke-design.md) (Spec A, slice 1).

**Scope note:** A1 is the smoke slice only. Explosion/plume (A2) and spark/debris (A3) controllers are separate plans. Non-goals are listed in spec §8. Merging A1 makes Spec B's subsystem plumes visible in-game.

---

## File Structure

| File | Responsibility |
|---|---|
| `native/src/renderer/include/renderer/frame.h` (modify) | Add `ParticleKey` + `ParticleEmitterDescriptor` structs beside `HitVfxDescriptor`. |
| `native/src/renderer/include/renderer/particle_math.h` (create) | Pure, GL-free analytic helpers: `curve_lerp1`, `particle_max_count`, `slot_birth_age`, `particle_world_pos`. Unit-tested without GL. |
| `native/tests/renderer/particle_math_test.cc` (create) | gtest for the four pure functions. |
| `native/src/renderer/include/renderer/particle_pass.h` (create) | `ParticlePass` class declaration. |
| `native/src/renderer/particle_pass.cc` (create) | The analytic billboard pass (reuses `hit_vfx_shader`, alpha blend, per-emitter texture cache). |
| `native/src/renderer/CMakeLists.txt` (modify) | Add `particle_pass.cc` to the `renderer` library. |
| `native/tests/CMakeLists.txt` (modify) | Add `particle_math_test.cc` + `particle_pass_test.cc` to the renderer test target. |
| `native/tests/renderer/particle_pass_test.cc` (create) | `FrameTest`-style GL smoke test (GL_NO_ERROR, no-emitter baseline). |
| `native/src/host/host_bindings.cc` (modify) | `g_particle_emitters` global, `ParticlePass` construct/teardown, `render` call, `set_particle_emitters` binding. |
| `engine/appc/particles.py` (create) | `AnimTSParticleController`, the registry (`register`/`advance`/`snapshot_descriptors`/`reset`), `EffectAction_Create`, `AnimTSParticleController_Create`, `ParticleBackend`. |
| `App.py` (modify) | Import `AnimTSParticleController_Create` + `EffectAction_Create` from `engine.appc.particles`. |
| `engine/host_loop.py` (modify) | Per-frame `particles.advance(dt)` + push `set_particle_emitters`; `particles.reset()` on mission swap; install `ParticleBackend` once. |
| `tests/unit/test_particles_controller.py` (create) | Controller setters + analytic lifecycle. |
| `tests/unit/test_particles_registry.py` (create) | Registry register/advance/prune/snapshot + `EffectAction`. |
| `tests/unit/test_particles_sdk_unmodified.py` (create) | SDK `Effects.py` smoke factories run against the real controller; no stub rows. |
| `tests/unit/test_particle_backend.py` (create) | `ParticleBackend` Spec B §5 surface. |
| `tests/integration/test_particles_host_loop.py` (create) | Host-loop push + Spec B end-to-end (`set_backend` → disabled nacelle → registered smoke emitter). |

**Shared C++ test note:** the renderer test executable is registered in `native/tests/CMakeLists.txt`. Inspect that file to find the exact target name (e.g. `renderer_tests`) and append the two new `.cc` files to its `add_executable(...)` list, mirroring the existing renderer test entries.

---

## Task 1: Descriptor struct + pure analytic math (GL-free, unit-tested)

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h`
- Create: `native/src/renderer/include/renderer/particle_math.h`
- Create: `native/tests/renderer/particle_math_test.cc`
- Modify: `native/tests/CMakeLists.txt`

- [ ] **Step 1: Add the descriptor structs to `frame.h`**

Find the `struct HitVfxDescriptor { … };` block and add immediately after it:

```cpp
/// One keyframe. Colour keys use (r,g,b); alpha/size keys use `v` only.
struct ParticleKey {
    float t = 0.0f;
    float v = 0.0f;            // alpha or size
    float r = 0.0f, g = 0.0f, b = 0.0f;  // colour keys only
};

/// A single analytic particle emitter. The renderer derives every live
/// particle's state from these fields + the per-particle hash; there is no
/// per-particle state anywhere. See particle_math.h for the model.
struct ParticleEmitterDescriptor {
    scenegraph::InstanceId instance_id{};   // {0,0} sentinel => unattached
    glm::vec3 emit_pos{0.0f};               // body-frame if attached, world if not
    glm::vec3 emit_dir{0.0f, -1.0f, 0.0f};  // body-frame if attached, world if not
    glm::vec3 emit_vel_world{0.0f};         // ship world velocity (already world)
    float inherit            = 1.0f;        // SetInheritsVelocity fraction [0,1]
    float emit_velocity      = 1.0f;
    float angle_variance     = 0.0f;        // degrees
    float emit_life          = 1.0f;
    float emit_life_variance = 0.0f;
    float emit_frequency     = 0.05f;
    float effect_age         = 0.0f;
    float stop_age           = 1.0e30f;     // emission cutoff (EffectLifeTime / explicit stop)
    int   draw_old_to_new    = 1;
    int   num_color_keys = 0; ParticleKey color_keys[8];
    int   num_alpha_keys = 0; ParticleKey alpha_keys[8];
    int   num_size_keys  = 0; ParticleKey size_keys[8];
    std::string texture_path;               // CreateTarget path; pass caches by string
};
```

Ensure `frame.h` already includes `<string>` and `<glm/glm.hpp>` and `<scenegraph/instance.h>` (it includes the latter for `HitVfxDescriptor`'s `InstanceId`); add `#include <string>` if absent.

- [ ] **Step 2: Write the failing C++ math test**

Create `native/tests/renderer/particle_math_test.cc`:

```cpp
#include <renderer/particle_math.h>
#include <gtest/gtest.h>

using namespace renderer;

TEST(ParticleMath, CurveLerpClampsAndInterpolates) {
    float ts[3] = {0.0f, 0.5f, 1.0f};
    float vs[3] = {0.2f, 1.0f, 0.0f};
    EXPECT_FLOAT_EQ(curve_lerp1(ts, vs, 3, -1.0f), 0.2f);   // clamp low
    EXPECT_FLOAT_EQ(curve_lerp1(ts, vs, 3, 2.0f), 0.0f);    // clamp high
    EXPECT_FLOAT_EQ(curve_lerp1(ts, vs, 3, 0.25f), 0.6f);   // midpoint of [0.2,1.0]
    EXPECT_FLOAT_EQ(curve_lerp1(ts, vs, 0, 0.5f), 1.0f);    // no keys => 1.0
}

TEST(ParticleMath, MaxCountCeils) {
    EXPECT_EQ(particle_max_count(1.0f, 0.0f, 0.25f), 4);
    EXPECT_EQ(particle_max_count(1.0f, 0.5f, 0.5f), 3);   // (1.0+0.5)/0.5 = 3
    EXPECT_EQ(particle_max_count(1.0f, 0.0f, 0.0f), 1);   // degenerate freq
}

TEST(ParticleMath, SlotBirthAgeIsLatestBirthNotAfterNow) {
    // n=4, f=0.25 => period=1.0. At effect_age=1.6, slot 0 births at 0,1,2…
    // latest <= 1.6 is 1.0 => tau=0.6.
    float b = slot_birth_age(1.6f, /*i=*/0, /*n=*/4, /*f=*/0.25f);
    EXPECT_NEAR(b, 1.0f, 1e-5f);
    // slot 1 births at 0.25,1.25,2.25 => latest <=1.6 is 1.25 => tau=0.35
    float b1 = slot_birth_age(1.6f, 1, 4, 0.25f);
    EXPECT_NEAR(b1, 1.25f, 1e-5f);
    // birth age never exceeds effect_age
    EXPECT_LE(slot_birth_age(0.1f, 3, 4, 0.25f), 0.1f + 1e-5f);
}

TEST(ParticleMath, TrailTermAppearsOnlyWhenInheritBelowOne) {
    glm::vec3 emit{0, 0, 0};
    glm::vec3 dir{0, -1, 0};
    glm::vec3 vel{10, 0, 0};          // ship moving +x
    // inherit=1 => no trail term; pos = dir*emit_velocity*tau
    glm::vec3 p_full = particle_world_pos(emit, dir, vel, /*emit_velocity=*/2.0f,
                                          /*inherit=*/1.0f, /*tau=*/0.5f);
    EXPECT_NEAR(p_full.x, 0.0f, 1e-5f);
    EXPECT_NEAR(p_full.y, -1.0f, 1e-5f);
    // inherit=0 => full lag: pos.x = -vel.x*tau = -5
    glm::vec3 p_lag = particle_world_pos(emit, dir, vel, 2.0f, 0.0f, 0.5f);
    EXPECT_NEAR(p_lag.x, -5.0f, 1e-5f);
    EXPECT_NEAR(p_lag.y, -1.0f, 1e-5f);
}
```

- [ ] **Step 3: Register the test in CMake**

In `native/tests/CMakeLists.txt`, find the renderer test executable (the `add_executable(...)` that lists `renderer/*_test.cc` files such as `renderer/bloom_pass_test.cc`) and add `renderer/particle_math_test.cc` to that list. (Add `renderer/particle_pass_test.cc` too now — it's created in Task 3; an empty/￼not-yet-existing file will break the build, so add it in Task 3's CMake step instead. For Task 1, add only `particle_math_test.cc`.)

- [ ] **Step 4: Run the test to verify it fails (header missing)**

Run: `cmake --build build -j 2>&1 | tail -20`
Expected: FAIL — `fatal error: renderer/particle_math.h: No such file or directory`.

- [ ] **Step 5: Write `particle_math.h`**

Create `native/src/renderer/include/renderer/particle_math.h`:

```cpp
// native/src/renderer/include/renderer/particle_math.h
#pragma once
#include <glm/glm.hpp>
#include <algorithm>
#include <cmath>

namespace renderer {

/// Piecewise-linear keyframe evaluation over parallel (ts[], vs[]) arrays of
/// length n, clamped outside [ts[0], ts[n-1]]. n<=0 returns 1.0 (no curve).
inline float curve_lerp1(const float* ts, const float* vs, int n, float t) {
    if (n <= 0) return 1.0f;
    if (t <= ts[0]) return vs[0];
    if (t >= ts[n - 1]) return vs[n - 1];
    for (int i = 1; i < n; ++i) {
        if (t <= ts[i]) {
            const float span = ts[i] - ts[i - 1];
            const float f = (span > 1e-9f) ? (t - ts[i - 1]) / span : 0.0f;
            return vs[i - 1] + f * (vs[i] - vs[i - 1]);
        }
    }
    return vs[n - 1];
}

/// Max simultaneously-live particles for an emitter: ceil(max_life / freq).
inline int particle_max_count(float emit_life, float emit_life_variance,
                              float emit_frequency) {
    const float max_life = emit_life + std::max(0.0f, emit_life_variance);
    if (emit_frequency <= 1e-6f) return 1;
    return std::max(1, static_cast<int>(std::ceil(max_life / emit_frequency)));
}

/// Birth age of the current occupant of slot i: the latest birth time
/// (i*freq + k*period) that is <= effect_age. Never exceeds effect_age.
inline float slot_birth_age(float effect_age, int i, int n, float emit_frequency) {
    const float period = static_cast<float>(n) * emit_frequency;
    if (period <= 1e-6f) return effect_age;
    const float phase = effect_age - static_cast<float>(i) * emit_frequency;
    const float k = std::floor(phase / period);
    return static_cast<float>(i) * emit_frequency + k * period;
}

/// World position of a particle with sub-age tau. The
/// -(1-inherit)*vel*tau term is the velocity-inherited trail.
inline glm::vec3 particle_world_pos(const glm::vec3& emit_pos_world,
                                    const glm::vec3& dir_world,
                                    const glm::vec3& emit_vel_world,
                                    float emit_velocity, float inherit,
                                    float tau) {
    return emit_pos_world
         + dir_world * (emit_velocity * tau)
         - emit_vel_world * ((1.0f - inherit) * tau);
}

}  // namespace renderer
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cmake --build build -j 2>&1 | tail -5 && ctest --test-dir build -R ParticleMath --output-on-failure 2>&1 | tail -20`
Expected: build succeeds; `ParticleMath.*` tests PASS (4 tests). (If the ctest filter name differs, run the renderer test binary directly with `--gtest_filter=ParticleMath.*`.)

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h \
        native/src/renderer/include/renderer/particle_math.h \
        native/tests/renderer/particle_math_test.cc \
        native/tests/CMakeLists.txt
git commit -m "feat(particles): emitter descriptor + analytic particle math (GL-free, tested)"
```

---

## Task 2: ParticlePass (analytic billboard renderer)

**Files:**
- Create: `native/src/renderer/include/renderer/particle_pass.h`
- Create: `native/src/renderer/particle_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt`

This pass reuses the existing `hit_vfx_shader` (camera-facing billboard with `u_world_position`/`u_size`/`u_alpha`/`u_tint`/`u_camera_right`/`u_camera_up`/`u_view_proj`/`u_texture`), so **no new GLSL** and no cmake shader reconfigure. It mirrors `native/src/renderer/hit_vfx_pass.cc`'s GL setup (quad mesh, texture loading, per-particle uniform draw) with three deltas: (1) **alpha** blend `GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA` (not additive), (2) per-emitter texture cached by path string, (3) the analytic particle loop from `particle_math.h`.

- [ ] **Step 1: Write the header**

Create `native/src/renderer/include/renderer/particle_pass.h`:

```cpp
// native/src/renderer/include/renderer/particle_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/texture.h>

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace scenegraph { struct Camera; class World; }

namespace renderer {

class Pipeline;

/// Stateless analytic billboard particle renderer (smoke, A1). Each
/// ParticleEmitterDescriptor is expanded into up to particle_max_count()
/// camera-facing alpha-blended quads whose state is computed analytically
/// from effect_age + per-particle hash + keyframe curves. Reuses the
/// hit_vfx billboard shader.
class ParticlePass {
public:
    ParticlePass();
    ~ParticlePass();
    ParticlePass(const ParticlePass&)            = delete;
    ParticlePass& operator=(const ParticlePass&) = delete;

    void render(const std::vector<ParticleEmitterDescriptor>& emitters,
                const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    std::map<std::string, std::unique_ptr<assets::Texture>> textures_;

    void ensure_quad_mesh();
    assets::Texture* texture_for(const std::string& path);  // lazy cache, nullptr on failure
};

}  // namespace renderer
```

- [ ] **Step 2: Write the implementation**

Create `native/src/renderer/particle_pass.cc`. Mirror `hit_vfx_pass.cc` for `ensure_quad_mesh()` and the texture-loading body (copy its `load_sprite` logic into `texture_for`, keyed by path into `textures_`). The novel `render()`:

```cpp
// native/src/renderer/particle_pass.cc
#include <renderer/particle_pass.h>

#include <renderer/particle_math.h>
#include <renderer/pipeline.h>
#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <assets/image.h>

#include <glad/glad.h>   // match the GL loader include used by hit_vfx_pass.cc
#include <glm/glm.hpp>

#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <vector>

namespace renderer {
namespace {

// Duplicated minimally from hit_vfx_pass.cc (kept local to avoid touching that
// pass). Per-particle deterministic 2D hash in [0,1).
inline glm::vec2 hash3(const glm::vec3& p, int i) {
    auto bits = [](float f) -> std::uint32_t {
        std::uint32_t u; std::memcpy(&u, &f, sizeof(u)); return u;
    };
    std::uint32_t h = bits(p.x) ^ (bits(p.y) * 0x9E3779B9u)
                    ^ (bits(p.z) * 0x85EBCA6Bu) ^ (std::uint32_t(i) * 0xC2B2AE35u);
    std::uint32_t h2 = h * 0x1B873593u;
    auto to_unit = [](std::uint32_t x) {
        return static_cast<float>(x & 0xFFFFFFu) / static_cast<float>(0x1000000u);
    };
    return glm::vec2{to_unit(h), to_unit(h2)};
}

// Jitter `base` within a cone of half-angle `cone_deg` using camera basis.
glm::vec3 cone_jitter(const glm::vec3& base, const glm::vec3& cam_up,
                      const glm::vec3& cam_right, glm::vec2 jitter, float cone_deg) {
    const float k = cone_deg * 0.0174532925f;  // deg->rad scale (matches hit_vfx feel)
    glm::vec3 v = base + cam_right * std::sin((jitter.x - 0.5f) * k)
                       + cam_up    * std::sin((jitter.y - 0.5f) * k);
    const float len = glm::length(v);
    return (len > 1e-6f) ? v / len : base;
}

}  // namespace

ParticlePass::ParticlePass() = default;
ParticlePass::~ParticlePass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

// ensure_quad_mesh(): copy verbatim from HitVfxPass::ensure_quad_mesh (same
// unit quad, 6 verts). texture_for(path): copy the load_sprite body from
// hit_vfx_pass.cc but cache into textures_[path]; return the cached pointer
// (nullptr if decode/open failed). [Implementer: mirror those two helpers.]

void ParticlePass::render(const std::vector<ParticleEmitterDescriptor>& emitters,
                          const scenegraph::World& world,
                          const scenegraph::Camera& camera,
                          Pipeline& pipeline) {
    if (emitters.empty()) return;
    ensure_quad_mesh();

    auto& shader = pipeline.hit_vfx_shader();
    shader.use();

    const glm::mat4 vp   = camera.proj_matrix() * camera.view_matrix();
    const glm::mat4 view = camera.view_matrix();
    const glm::vec3 cam_right = glm::vec3(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up    = glm::vec3(view[0][1], view[1][1], view[2][1]);
    shader.set_mat4("u_view_proj",    vp);
    shader.set_vec3("u_camera_right", cam_right);
    shader.set_vec3("u_camera_up",    cam_up);
    shader.set_int ("u_texture",      0);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);   // alpha-blended smoke
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);

    // Scratch arrays for curve_lerp1.
    float kt[8], kv[8], kr[8], kg[8], kb[8];

    for (const auto& e : emitters) {
        assets::Texture* tex = texture_for(e.texture_path);
        if (!tex || tex->id() == 0) continue;

        // Resolve the emit frame. Attached => transform body emit point/dir
        // through the ship's live world matrix (the spark path).
        glm::vec3 emit_pos_world = e.emit_pos;
        glm::vec3 emit_dir_world = e.emit_dir;
        if (!(e.instance_id == scenegraph::InstanceId{})) {
            const scenegraph::Instance* inst = world.get(e.instance_id);
            if (inst == nullptr) continue;  // ship gone this frame
            emit_pos_world = glm::vec3(inst->world * glm::vec4(e.emit_pos, 1.0f));
            emit_dir_world = glm::mat3(inst->world) * e.emit_dir;
        }
        const float dlen = glm::length(emit_dir_world);
        emit_dir_world = (dlen > 1e-6f) ? emit_dir_world / dlen : glm::vec3(0, -1, 0);

        // Unpack colour keys into parallel arrays once per emitter.
        for (int i = 0; i < e.num_color_keys && i < 8; ++i) {
            kt[i] = e.color_keys[i].t; kr[i] = e.color_keys[i].r;
            kg[i] = e.color_keys[i].g; kb[i] = e.color_keys[i].b;
        }
        float at[8], av[8], st[8], sv[8];
        for (int i = 0; i < e.num_alpha_keys && i < 8; ++i) { at[i] = e.alpha_keys[i].t; av[i] = e.alpha_keys[i].v; }
        for (int i = 0; i < e.num_size_keys  && i < 8; ++i) { st[i] = e.size_keys[i].t;  sv[i] = e.size_keys[i].v; }

        const int n = particle_max_count(e.emit_life, e.emit_life_variance, e.emit_frequency);
        for (int i = 0; i < n; ++i) {
            const float b   = slot_birth_age(e.effect_age, i, n, e.emit_frequency);
            const float tau = e.effect_age - b;
            const glm::vec2 jit = hash3(emit_pos_world, i);
            const float life_i  = e.emit_life + jit.x * std::max(0.0f, e.emit_life_variance);
            if (tau < 0.0f || tau > life_i) continue;   // not currently alive
            if (b < 0.0f || b > e.stop_age) continue;    // before start / after emission stopped

            const glm::vec3 dir = cone_jitter(emit_dir_world, cam_up, cam_right, jit, e.angle_variance);
            const glm::vec3 pos = particle_world_pos(emit_pos_world, dir, e.emit_vel_world,
                                                     e.emit_velocity, e.inherit, tau);
            const float t     = (life_i > 1e-6f) ? (tau / life_i) : 0.0f;
            const float size  = curve_lerp1(st, sv, e.num_size_keys, t);
            const float alpha = curve_lerp1(at, av, e.num_alpha_keys, t);
            const float r = curve_lerp1(kt, kr, e.num_color_keys, t);
            const float g = curve_lerp1(kt, kg, e.num_color_keys, t);
            const float bl= curve_lerp1(kt, kb, e.num_color_keys, t);

            glBindTexture(GL_TEXTURE_2D, tex->id());
            shader.set_vec4 ("u_tint",           glm::vec4(r, g, bl, 1.0f));
            shader.set_vec3 ("u_world_position", pos);
            shader.set_float("u_size",           size);
            shader.set_float("u_alpha",          alpha);
            glDrawArrays(GL_TRIANGLES, 0, 6);
        }
    }

    glBindTexture(GL_TEXTURE_2D, 0);
    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}

}  // namespace renderer
```

Notes for the implementer:
- Copy `ensure_quad_mesh()` and the sprite-loading body **verbatim** from `hit_vfx_pass.cc` (the `load_sprite` helper), adapting the loader to write into `textures_[path]` and return the cached pointer. Match its exact `#include` for the GL loader (it may be `<glad/glad.h>` or similar — use whatever `hit_vfx_pass.cc` uses).
- `InstanceId{}` equality: if `scenegraph::InstanceId` has no `operator==`, compare its fields (e.g. `e.instance_id.index == 0 && e.instance_id.generation == 0`); check `scenegraph/instance.h` for the exact field names (the spark path in `hit_vfx_pass.cc` shows how an `InstanceId` is used with `world.get(...)`).

- [ ] **Step 3: Add to the renderer CMake**

In `native/src/renderer/CMakeLists.txt`, add `particle_pass.cc` to the `add_library(renderer STATIC …)` source list (next to `hit_vfx_pass.cc` if present, else alphabetically near the other `*_pass.cc`).

- [ ] **Step 4: Build to verify it compiles**

Run: `cmake -B build -S . >/dev/null 2>&1; cmake --build build -j 2>&1 | tail -20`
Expected: builds cleanly (no link/compile errors for `particle_pass.cc`). There is no behavioural test yet — the host wiring + render test come in Task 3.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/particle_pass.h \
        native/src/renderer/particle_pass.cc \
        native/src/renderer/CMakeLists.txt
git commit -m "feat(particles): ParticlePass analytic billboard renderer (reuses hit_vfx shader)"
```

---

## Task 3: Host binding + render call + GL smoke test

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Create: `native/tests/renderer/particle_pass_test.cc`
- Modify: `native/tests/CMakeLists.txt`

- [ ] **Step 1: Wire the pass into the host like `hit_vfx`**

In `native/src/host/host_bindings.cc`, mirror every `g_hit_vfx` / `g_hit_vfx_pass` site:

1. Globals (next to `g_hit_vfx`):
```cpp
std::vector<renderer::ParticleEmitterDescriptor> g_particle_emitters;
std::unique_ptr<renderer::ParticlePass>          g_particle_pass;
```
2. Construct (next to `g_hit_vfx_pass = std::make_unique<...>()`):
```cpp
g_particle_pass = std::make_unique<renderer::ParticlePass>();
```
3. Teardown (next to `g_hit_vfx.clear(); g_hit_vfx_pass.reset();`):
```cpp
g_particle_emitters.clear();
g_particle_pass.reset();
```
4. Render in `frame()` (immediately after the `g_hit_vfx_pass->render(...)` line):
```cpp
if (g_particle_pass) g_particle_pass->render(g_particle_emitters, g_world, g_camera, *g_pipeline);
```
5. Add `#include <renderer/particle_pass.h>` near `#include <renderer/hit_vfx_pass.h>`.

- [ ] **Step 2: Add the `set_particle_emitters` binding**

After the `m.def("set_hit_vfx", …)` block, add (mirroring it; each dict mirrors `ParticleEmitterDescriptor`):

```cpp
    m.def("set_particle_emitters",
          [](const std::vector<py::dict>& descs) {
              g_particle_emitters.clear();
              g_particle_emitters.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::ParticleEmitterDescriptor e;
                  if (d.contains("instance_id") && !d["instance_id"].is_none())
                      e.instance_id = d["instance_id"].cast<scenegraph::InstanceId>();
                  auto p = d["emit_pos"].cast<std::tuple<float,float,float>>();
                  e.emit_pos = {std::get<0>(p), std::get<1>(p), std::get<2>(p)};
                  auto dir = d["emit_dir"].cast<std::tuple<float,float,float>>();
                  e.emit_dir = {std::get<0>(dir), std::get<1>(dir), std::get<2>(dir)};
                  auto vel = d["emit_vel_world"].cast<std::tuple<float,float,float>>();
                  e.emit_vel_world = {std::get<0>(vel), std::get<1>(vel), std::get<2>(vel)};
                  e.inherit            = d["inherit"].cast<float>();
                  e.emit_velocity      = d["emit_velocity"].cast<float>();
                  e.angle_variance     = d["angle_variance"].cast<float>();
                  e.emit_life          = d["emit_life"].cast<float>();
                  e.emit_life_variance = d["emit_life_variance"].cast<float>();
                  e.emit_frequency     = d["emit_frequency"].cast<float>();
                  e.effect_age         = d["effect_age"].cast<float>();
                  e.stop_age           = d["stop_age"].cast<float>();
                  e.draw_old_to_new    = d["draw_old_to_new"].cast<int>();
                  e.texture_path       = d["texture_path"].cast<std::string>();
                  auto load_keys = [&](const char* key, int& count, renderer::ParticleKey* out, bool color) {
                      count = 0;
                      if (!d.contains(key)) return;
                      for (const auto& k : d[key].cast<std::vector<py::tuple>>()) {
                          if (count >= 8) break;
                          renderer::ParticleKey pk;
                          pk.t = k[0].cast<float>();
                          if (color) { pk.r = k[1].cast<float>(); pk.g = k[2].cast<float>(); pk.b = k[3].cast<float>(); }
                          else       { pk.v = k[1].cast<float>(); }
                          out[count++] = pk;
                      }
                  };
                  load_keys("color_keys", e.num_color_keys, e.color_keys, true);
                  load_keys("alpha_keys", e.num_alpha_keys, e.alpha_keys, false);
                  load_keys("size_keys",  e.num_size_keys,  e.size_keys,  false);
                  g_particle_emitters.push_back(std::move(e));
              }
          },
          py::arg("emitters"),
          "Set the active particle-emitter list, applied each frame().");
```

- [ ] **Step 3: Write the GL smoke test**

Create `native/tests/renderer/particle_pass_test.cc`. Model it on the existing `FrameTest`-style renderer tests (e.g. `native/tests/renderer/bloom_pass_test.cc` or `resolve_pass_test.cc` — open one to copy the offscreen-context fixture + `GTEST_SKIP` when assets/GL are unavailable):

```cpp
#include <renderer/particle_pass.h>
#include <gtest/gtest.h>
// + the offscreen GL fixture headers used by the sibling *_pass_test.cc files.

// Mirror the sibling renderer tests' fixture (offscreen context + Pipeline +
// World + Camera). If GL/assets are unavailable, GTEST_SKIP like they do.
TEST(ParticlePass, RendersWithoutGlError) {
    // [Build the same offscreen fixture as bloom_pass_test.cc.]
    // ParticlePass pass;
    // std::vector<renderer::ParticleEmitterDescriptor> emitters(1);
    // emitters[0].texture_path = "game/data/Textures/Effects/ExplosionB.tga";
    // emitters[0].num_size_keys = 1; emitters[0].size_keys[0] = {0.0f, 1.0f};
    // emitters[0].num_alpha_keys = 1; emitters[0].alpha_keys[0] = {0.0f, 1.0f};
    // emitters[0].effect_age = 0.1f;
    // pass.render(emitters, world, camera, pipeline);
    // EXPECT_EQ(glGetError(), GL_NO_ERROR);
    // An empty emitter list must early-out and also leave GL_NO_ERROR.
    // pass.render({}, world, camera, pipeline);
    // EXPECT_EQ(glGetError(), GL_NO_ERROR);
    GTEST_SKIP() << "fill in offscreen fixture per sibling *_pass_test.cc";
}
```

Implementer: replace the `GTEST_SKIP` body with the real offscreen fixture copied from a sibling renderer test, asserting `glGetError() == GL_NO_ERROR` after rendering one emitter and after rendering an empty list. Keep the `GTEST_SKIP` fallback for environments without the BC asset (the sibling tests show the exact skip predicate).

Then add `renderer/particle_pass_test.cc` to the renderer test executable in `native/tests/CMakeLists.txt`.

- [ ] **Step 4: Build and run**

Run: `cmake -B build -S . >/dev/null 2>&1; cmake --build build -j 2>&1 | tail -15 && ctest --test-dir build -R ParticlePass --output-on-failure 2>&1 | tail -20`
Expected: builds; `ParticlePass.RendersWithoutGlError` passes or skips (skip is acceptable if the offscreen context/asset is unavailable in this environment).

- [ ] **Step 5: Verify the Python binding exists**

Run: `cmake --build build -j >/dev/null 2>&1 && uv run python -c "import sys; sys.path.insert(0,'build/python'); import _open_stbc_host as h; print(hasattr(h,'set_particle_emitters'))"`
Expected: prints `True`. (If the module path differs, use the canonical `build/python/_open_stbc_host*.so` per CLAUDE.md.)

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc native/tests/renderer/particle_pass_test.cc native/tests/CMakeLists.txt
git commit -m "feat(particles): host binding set_particle_emitters + ParticlePass render call"
```

---

## Task 4: Python `AnimTSParticleController`

**Files:**
- Create: `engine/appc/particles.py`
- Test: `tests/unit/test_particles_controller.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_particles_controller.py
from engine.appc.particles import AnimTSParticleController


def test_setters_round_trip():
    c = AnimTSParticleController()
    c.AddColorKey(0.0, 1.0, 0.5, 0.25)
    c.AddAlphaKey(0.0, 0.6); c.AddAlphaKey(1.0, 0.0)
    c.AddSizeKey(0.0, 0.2); c.AddSizeKey(1.0, 2.0)
    c.SetEmitVelocity(3.0); c.SetAngleVariance(60.0)
    c.SetEmitLife(1.5); c.SetEmitLifeVariance(0.3)
    c.SetEmitFrequency(0.05); c.SetEffectLifeTime(10.0)
    c.SetInheritsVelocity(1); c.SetDrawOldToNew(0)
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    assert c._color_keys == [(0.0, 1.0, 0.5, 0.25)]
    assert c._alpha_keys == [(0.0, 0.6), (1.0, 0.0)]
    assert c._size_keys == [(0.0, 0.2), (1.0, 2.0)]
    assert c._emit_velocity == 3.0 and c._angle_variance == 60.0
    assert c._emit_life == 1.5 and c._emit_life_variance == 0.3
    assert c._emit_frequency == 0.05 and c._effect_life_time == 10.0
    assert c._inherit == 1.0 and c._draw_old_to_new == 0
    assert c._texture_path.endswith("ExplosionB.tga")


def test_inherits_velocity_zero_is_no_inherit():
    c = AnimTSParticleController()
    c.SetInheritsVelocity(0)
    assert c._inherit == 0.0


def test_unknown_setter_is_noop_not_crash():
    c = AnimTSParticleController()
    c.SetSomeFutureSDKKnob(1, 2, 3)   # must not raise
    c.AddMysteryKey(0.5)              # must not raise


def test_stop_and_has_live_particles_timeline():
    c = AnimTSParticleController()
    c.SetEmitLife(1.0); c.SetEmitLifeVariance(0.0); c.SetEffectLifeTime(100.0)
    c._effect_age = 5.0
    assert c.has_live_particles() is True      # never stopped
    c.stop_emitting()                          # stop_age = 5.0
    c._effect_age = 5.5
    assert c.has_live_particles() is True       # within max_life
    c._effect_age = 6.5                          # 5.0 + 1.0 = 6.0 < 6.5
    assert c.has_live_particles() is False


def test_effect_life_time_caps_emission_for_has_live():
    c = AnimTSParticleController()
    c.SetEmitLife(1.0); c.SetEffectLifeTime(2.0)   # emission auto-stops at 2.0
    c._effect_age = 2.5
    assert c.has_live_particles() is True            # 2.0 + 1.0 = 3.0 > 2.5
    c._effect_age = 3.5
    assert c.has_live_particles() is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_particles_controller.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.particles'`.

- [ ] **Step 3: Write the controller**

Create `engine/appc/particles.py` with the controller (registry/factory/backend come in later tasks):

```python
# engine/appc/particles.py
"""Real particle controllers behind the SDK Effects.py factory names (Spec A1).

A controller stores keyframe curves + emit params; it does NOT simulate
particles. The renderer (ParticlePass) derives every particle analytically
from these fields each frame. See
docs/superpowers/specs/2026-06-11-particle-backend-a1-smoke-design.md.
"""


class AnimTSParticleController:
    def __init__(self):
        self._color_keys = []   # (t, r, g, b)
        self._alpha_keys = []   # (t, a)
        self._size_keys  = []   # (t, s)
        self._emit_velocity = 1.0
        self._angle_variance = 0.0
        self._emit_life = 1.0
        self._emit_life_variance = 0.0
        self._emit_frequency = 0.05
        self._effect_life_time = 1.0
        self._inherit = 1.0
        self._draw_old_to_new = 1
        self._texture_path = ""
        self._emit_from = None     # AV object / ship handle (SetEmitFromObject)
        self._attach_node = None   # AttachEffect target
        self._emit_pos = None      # body-frame (attached) or world (SetEmitPositionAndDirection)
        self._emit_dir = None
        # runtime, owned by the registry
        self._effect_age = 0.0
        self._stop_age = None      # None => still emitting

    # ---- SDK setters --------------------------------------------------
    def AddColorKey(self, t, r, g, b): self._color_keys.append((t, r, g, b))
    def AddAlphaKey(self, t, a):       self._alpha_keys.append((t, a))
    def AddSizeKey(self, t, s):        self._size_keys.append((t, s))
    def SetEmitVelocity(self, v):      self._emit_velocity = v
    def SetAngleVariance(self, deg):   self._angle_variance = deg
    def SetEmitLife(self, l):          self._emit_life = l
    def SetEmitLifeVariance(self, v):  self._emit_life_variance = v
    def SetEmitFrequency(self, f):     self._emit_frequency = f
    def SetEffectLifeTime(self, t):    self._effect_life_time = t
    def SetInheritsVelocity(self, on): self._inherit = 1.0 if on else 0.0
    def SetDrawOldToNew(self, on):     self._draw_old_to_new = 1 if on else 0
    def CreateTarget(self, path):      self._texture_path = path
    def SetEmitFromObject(self, obj):  self._emit_from = obj
    def AttachEffect(self, node):      self._attach_node = node
    def SetEmitPositionAndDirection(self, pos, d):
        self._emit_pos = pos
        self._emit_dir = d

    def __getattr__(self, name):
        # Tolerate any other SDK Set*/Add* call as a harmless no-op so future
        # Effects.py code never crashes the controller. Real attributes are
        # found before __getattr__ fires.
        if name.startswith("Set") or name.startswith("Add"):
            return lambda *a, **k: None
        raise AttributeError(name)

    # ---- analytic lifecycle (used by the registry + the Spec B handle) -
    def _effective_stop_age(self):
        explicit = self._stop_age if self._stop_age is not None else float("inf")
        return min(explicit, self._effect_life_time)

    def stop_emitting(self):
        self._stop_age = self._effect_age

    def has_live_particles(self):
        max_life = self._emit_life + max(0.0, self._emit_life_variance)
        return self._effective_stop_age() + max_life > self._effect_age
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_particles_controller.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/particles.py tests/unit/test_particles_controller.py
git commit -m "feat(particles): AnimTSParticleController (keyframes, params, analytic lifecycle)"
```

---

## Task 5: Registry + `EffectAction_Create`

**Files:**
- Modify: `engine/appc/particles.py`
- Test: `tests/unit/test_particles_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_particles_registry.py
from engine.appc import particles as P
from engine.appc.particles import AnimTSParticleController


def _smoke(life=1.0, freq=0.05, eff=100.0):
    c = AnimTSParticleController()
    c.SetEmitLife(life); c.SetEmitFrequency(freq); c.SetEffectLifeTime(eff)
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    c.AddSizeKey(0.0, 1.0); c.AddAlphaKey(0.0, 0.5)
    return c


def test_effect_action_start_registers_stop_deregisters():
    P.reset()
    c = _smoke()
    action = P.EffectAction_Create(c)
    assert P.active_count() == 0
    action.Start()
    assert P.active_count() == 1
    action.Stop()
    assert P.active_count() == 0


def test_advance_ages_and_prunes_after_lifetime_and_death():
    P.reset()
    c = _smoke(life=1.0, eff=2.0)
    P.EffectAction_Create(c).Start()
    P.advance(1.0)
    assert P.active_count() == 1 and c._effect_age == 1.0
    P.advance(1.5)   # age 2.5 > EffectLifeTime 2.0 but particles live to 3.0
    assert P.active_count() == 1
    P.advance(1.0)   # age 3.5 > 3.0 => pruned
    assert P.active_count() == 0


def test_snapshot_unattached_emits_world_descriptor():
    P.reset()
    c = _smoke()
    c.SetEmitPositionAndDirection((1.0, 2.0, 3.0), (0.0, -1.0, 0.0))
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    descs = P.snapshot_descriptors()
    assert len(descs) == 1
    d = descs[0]
    assert d["instance_id"] is None
    assert d["emit_pos"] == (1.0, 2.0, 3.0)
    assert d["emit_vel_world"] == (0.0, 0.0, 0.0)
    assert d["texture_path"].endswith("ExplosionB.tga")
    assert d["size_keys"] == [(0.0, 1.0)]
    assert d["effect_age"] == 0.1


def test_snapshot_attached_uses_resolver():
    P.reset()
    c = _smoke()
    ship = object()
    c.SetEmitFromObject(ship)
    c.SetEmitPositionAndDirection((0.0, 1.0, 0.0), (0.0, -1.0, 0.0))
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    def resolve(emit_from):
        assert emit_from is ship
        return {"instance_id": (7, 1), "velocity": (5.0, 0.0, 0.0)}
    d = P.snapshot_descriptors(resolve_attach=resolve)[0]
    assert d["instance_id"] == (7, 1)
    assert d["emit_vel_world"] == (5.0, 0.0, 0.0)
    assert d["emit_pos"] == (0.0, 1.0, 0.0)   # body-frame, resolved in the pass


def test_reset_clears_active():
    P.reset()
    P.EffectAction_Create(_smoke()).Start()
    assert P.active_count() == 1
    P.reset()
    assert P.active_count() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_particles_registry.py -q`
Expected: FAIL — `AttributeError: module 'engine.appc.particles' has no attribute 'reset'` (or `EffectAction_Create`).

- [ ] **Step 3: Write the registry + action**

Append to `engine/appc/particles.py`:

```python
# ---- active registry -------------------------------------------------------

_active = []   # list[AnimTSParticleController]


def reset():
    """Drop all active controllers (mission swap / load)."""
    _active.clear()


def active_count():
    return len(_active)


def register(controller):
    controller._effect_age = 0.0
    controller._stop_age = None
    if controller not in _active:
        _active.append(controller)


def deregister(controller):
    if controller in _active:
        _active.remove(controller)


def advance(dt):
    """Age every active controller; prune those past EffectLifeTime whose
    particles have all expired."""
    dt = float(dt)
    survivors = []
    for c in _active:
        c._effect_age += dt
        if c._effect_age <= c._effect_life_time or c.has_live_particles():
            survivors.append(c)
    _active[:] = survivors


def _vec3(p, default=(0.0, 0.0, 0.0)):
    if p is None:
        return default
    if hasattr(p, "x"):
        return (p.x, p.y, p.z)
    return (p[0], p[1], p[2])


def _descriptor_for(c, resolve_attach):
    instance_id = None
    emit_vel_world = (0.0, 0.0, 0.0)
    emit_pos = _vec3(c._emit_pos)
    emit_dir = _vec3(c._emit_dir, default=(0.0, -1.0, 0.0))
    if c._emit_from is not None and resolve_attach is not None:
        r = resolve_attach(c._emit_from)
        if r is not None:
            instance_id = r.get("instance_id")
            emit_vel_world = tuple(r.get("velocity", (0.0, 0.0, 0.0)))
            # emit_pos/emit_dir stay body-frame; the pass resolves them.
    return {
        "instance_id":       instance_id,
        "emit_pos":          emit_pos,
        "emit_dir":          emit_dir,
        "emit_vel_world":    emit_vel_world,
        "inherit":           float(c._inherit),
        "emit_velocity":     float(c._emit_velocity),
        "angle_variance":    float(c._angle_variance),
        "emit_life":         float(c._emit_life),
        "emit_life_variance":float(c._emit_life_variance),
        "emit_frequency":    float(c._emit_frequency),
        "effect_age":        float(c._effect_age),
        "stop_age":          float(c._effective_stop_age()),
        "draw_old_to_new":   int(c._draw_old_to_new),
        "color_keys":        list(c._color_keys),
        "alpha_keys":        list(c._alpha_keys),
        "size_keys":         list(c._size_keys),
        "texture_path":      c._texture_path,
    }


def snapshot_descriptors(resolve_attach=None):
    """Build one render descriptor per active controller. `resolve_attach`
    maps an emit-from object -> {'instance_id', 'velocity'} or None."""
    return [_descriptor_for(c, resolve_attach) for c in _active]


class EffectAction:
    """Mirror of the SDK action wrapper: Start() registers the controller in
    the active set, Stop() deregisters it."""
    def __init__(self, controller):
        self._controller = controller

    def Start(self):
        register(self._controller)

    def Stop(self):
        deregister(self._controller)

    def GetController(self):
        return self._controller


def EffectAction_Create(controller):
    return EffectAction(controller)
```

Note: `stop_age` in the descriptor is `_effective_stop_age()` (min of explicit stop and EffectLifeTime). When neither is finite for a sustained plume, the backend sets a large `EffectLifeTime`, so `stop_age` is finite-large until `stop_emitting()` is called.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_particles_registry.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/particles.py tests/unit/test_particles_registry.py
git commit -m "feat(particles): active registry, snapshot_descriptors, EffectAction"
```

---

## Task 6: `App.py` wiring + SDK-`Effects.py`-unmodified proof

**Files:**
- Modify: `App.py`
- Test: `tests/unit/test_particles_sdk_unmodified.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_particles_sdk_unmodified.py
"""The SDK Effects.py smoke factories must run UNMODIFIED against our real
controller and register a controller with the SDK's exact recipe."""
import App
from engine.appc import particles as P


def _make_emit_from():
    # CreateSmokeHigh takes (fVelocity, fLife, fSize, pEmitFrom, kEmitPos,
    # kEmitDir, pAttachTo). For this headless test the object handles can be
    # plain sentinels — the controller just stores them.
    return object()


def test_create_smoke_high_builds_real_controller():
    import Effects
    P.reset()
    pEmitFrom = _make_emit_from()
    action = Effects.CreateSmokeHigh(2.0, 1.5, 0.6, pEmitFrom, None, None, object())
    # EffectAction_Create returned a real action; starting it registers a controller.
    action.Start()
    assert P.active_count() == 1
    # The controller carries the SDK's smoke recipe:
    from engine.appc.particles import AnimTSParticleController
    ctrl = P._active[0]
    assert isinstance(ctrl, AnimTSParticleController)
    assert ctrl._emit_velocity == 2.0
    assert ctrl._texture_path.endswith("ExplosionB.tga")
    assert len(ctrl._alpha_keys) >= 2 and len(ctrl._size_keys) >= 2


def test_no_stub_rows_for_controller_methods():
    """If the controller factory were still a _NamedStub, the App stub tracker
    would record AnimTSParticleController_Create rows. It must not."""
    import Effects
    App._stub_tracker.set_mission("particles-a1")
    try:
        Effects.CreateSmokeHigh(2.0, 1.5, 0.6, object(), None, None, object())
        report = App._stub_tracker.report()
    finally:
        App._stub_tracker.reset_mission()
    assert "AnimTSParticleController_Create" not in report
    assert "EffectAction_Create" not in report
```

If `App._stub_tracker`'s API differs (method names for `set_mission`/`report`/`reset_mission`), adapt this test to the real surface — inspect `App.py`'s `_stub_tracker` (the object-emitter spec references the same tracker). The intent is: no `AnimTSParticleController_Create` / `EffectAction_Create` rows after the call.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_particles_sdk_unmodified.py -q`
Expected: FAIL — `Effects.CreateSmokeHigh` builds a `_NamedStub` (no real controller registered; `active_count()==0`), and/or stub rows appear.

- [ ] **Step 3: Wire the factories into `App.py`**

Find the block in `App.py` where sibling factories are imported from `engine.appc` modules (e.g. the `ObjectEmitterProperty_Create` import block referenced in the object-emitter spec, or the `properties.py` factory imports). Add:

```python
from engine.appc.particles import (
    AnimTSParticleController_Create,
    EffectAction_Create,
)
```

And in `engine/appc/particles.py`, add the controller factory (next to `EffectAction_Create`):

```python
def AnimTSParticleController_Create():
    return AnimTSParticleController()
```

(`EffectAction_Create` already exists from Task 5.) These names now shadow `App.__getattr__`'s `_NamedStub`, so SDK `Effects.py`'s `App.AnimTSParticleController_Create()` and `App.EffectAction_Create(...)` resolve to the real implementations — the factory bodies run unmodified.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_particles_sdk_unmodified.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add App.py engine/appc/particles.py tests/unit/test_particles_sdk_unmodified.py
git commit -m "feat(particles): wire real controller factories into App so Effects.py runs unmodified"
```

---

## Task 7: Host-loop wiring (advance + push + reset)

**Files:**
- Modify: `engine/host_loop.py`
- Test: `tests/integration/test_particles_host_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_particles_host_loop.py
from engine.appc import particles as P
from engine.appc.particles import AnimTSParticleController


def test_build_particle_render_data_snapshots_active():
    import engine.host_loop as hl
    P.reset()
    c = AnimTSParticleController()
    c.SetEmitPositionAndDirection((1.0, 0.0, 0.0), (0.0, -1.0, 0.0))
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga")
    c.AddSizeKey(0.0, 1.0)
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    data = hl._build_particle_render_data()
    assert len(data) == 1
    assert data[0]["emit_pos"] == (1.0, 0.0, 0.0)
    assert data[0]["texture_path"].endswith("ExplosionB.tga")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_particles_host_loop.py -q`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_build_particle_render_data'`.

- [ ] **Step 3: Wire the host loop**

In `engine/host_loop.py`:

1. Add the render-data builder next to `_build_hit_vfx_render_data`:
```python
def _build_particle_render_data():
    from engine.appc import particles
    return particles.snapshot_descriptors(resolve_attach=_resolve_emit_attach)


def _resolve_emit_attach(emit_from):
    """Map a controller's emit-from object to its renderer instance + world
    velocity. Returns None when the object isn't a live ship (=> unattached)."""
    try:
        from engine.appc import ships as _ships  # noqa: F401
    except Exception:
        return None
    inst = _emit_from_instance_id(emit_from)
    if inst is None:
        return None
    vel = (0.0, 0.0, 0.0)
    if hasattr(emit_from, "GetWorldVelocity"):
        v = emit_from.GetWorldVelocity()
        vel = (v.x, v.y, v.z)
    return {"instance_id": inst, "velocity": vel}
```

2. Implement `_emit_from_instance_id(emit_from)` to map the emit-from object to the renderer instance id. Inspect how `_build_hit_vfx_render_data` / the spark path obtains `instance_id` from a ship (there is an existing ship→instance map in the host loop — the same `ship_instances` used by combat/`set_hit_vfx`). Reuse that map: if `emit_from` is (or wraps) a ship in `ship_instances`, return its id; else `None`. Do **not** build a second map.

3. In the same per-tick block that calls `hit_vfx.update_ages(dt)` / pushes `set_hit_vfx`, add:
```python
    from engine.appc import particles
    particles.advance(dt)
```
and where `host.set_hit_vfx(...)` is pushed (the `if host is not None and hasattr(host, "set_hit_vfx")` block), add alongside:
```python
    if host is not None and hasattr(host, "set_particle_emitters"):
        host.set_particle_emitters(_build_particle_render_data())
```

4. In the mission-swap reset path (`_drain_pending_swap`, next to `subsystem_emitters.reset_manager()`), add:
```python
        from engine.appc import particles
        particles.reset()
```

If `host` doesn't expose `set_particle_emitters` (older binding), the `hasattr` guard makes this a safe no-op — consistent with the existing `set_hit_vfx` guard.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_particles_host_loop.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Regression — the real tick still runs**

Run: `uv run pytest tests/integration/test_host_loop_m3gameflow.py -q`
Expected: PASS (the per-frame `particles.advance` + push must not raise).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/integration/test_particles_host_loop.py
git commit -m "feat(particles): host-loop advance + push set_particle_emitters + swap reset"
```

---

## Task 8: `ParticleBackend` + Spec B `set_backend` + end-to-end

**Files:**
- Modify: `engine/appc/particles.py`
- Modify: `engine/host_loop.py`
- Test: `tests/unit/test_particle_backend.py`
- Test: `tests/integration/test_particles_host_loop.py` (extend)

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/test_particle_backend.py
from engine.appc import particles as P
from engine.appc import subsystem_emitters as se
from engine.appc.particles import ParticleBackend


def test_create_registers_controller_and_returns_handle():
    P.reset()
    b = ParticleBackend()
    ship = object()
    h = b.create("CreateSmokeHigh", {"fVelocity": 2.0, "fLife": 1.2, "fSize": 0.6},
                 emit_pos_body=(1.0, -2.0, 0.0), emit_dir=(0.0, -1.0, 0.0),
                 direction_mode=se.DirectionMode.FIXED_BODY_VECTOR, ship=ship)
    assert P.active_count() == 1
    # handle drives the controller
    assert h.has_live_particles() is True
    h.stop_emitting()
    ctrl = P._active[0]
    assert ctrl._stop_age is not None


def test_create_spherical_widens_angle_variance():
    P.reset()
    b = ParticleBackend()
    h = b.create("CreateSmokeHigh", {"fVelocity": 1.0, "fLife": 2.0, "fSize": 1.0},
                 emit_pos_body=(0.0, 1.0, 0.0), emit_dir=None,
                 direction_mode=se.DirectionMode.SPHERICAL, ship=object())
    ctrl = P._active[0]
    assert ctrl._angle_variance >= 120.0   # wide/omni spread for spherical


def test_fire_one_shot_registers_short_lived_controller():
    P.reset()
    b = ParticleBackend()
    b.fire_one_shot("CreateSmokeHigh", emit_pos_body=(0.0, 0.0, 0.0),
                    emit_dir=(0.0, -1.0, 0.0), ship=object())
    assert P.active_count() == 1
    assert P._active[0]._effect_life_time <= 2.0   # short one-shot
```

The `ParticleBackend.create` signature here adds a `ship` kwarg over Spec B's documented `create(factory, params, emit_pos_body, emit_dir, direction_mode)`. **Reconcile this**: Spec B's `PlumeManager._spawn` calls `self.backend.create(descriptor.factory, descriptor.params, emit_pos_body, emit_dir, descriptor.direction_mode)` — no `ship`. The backend needs the ship to set `SetEmitFromObject`. Resolve by having the backend's `create` accept the ship via a thread-through: extend `PlumeManager._spawn` to pass `ship=ship` **only if** the backend's `create` accepts it. Simplest robust approach: give `ParticleBackend.create` the signature `create(self, factory, params, emit_pos_body, emit_dir, direction_mode, ship=None)` and have `PlumeManager._spawn` pass `ship=ship`. Update Spec B's `_spawn` call accordingly (it already holds `ship`). Adjust the §5 interface note in a one-line code comment. (NullBackend.create must also accept the optional `ship=None`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_particle_backend.py -q`
Expected: FAIL — `ImportError: cannot import name 'ParticleBackend'`.

- [ ] **Step 3: Implement `ParticleBackend`**

Append to `engine/appc/particles.py`:

```python
import importlib


_SPHERICAL_ANGLE = 150.0   # wide spread approximating omni for SPHERICAL plumes


def _call_factory(factory_name, fVelocity, fLife, fSize, emit_from, emit_pos, emit_dir):
    """Call the SDK Effects.py factory by name and return its EffectAction."""
    Effects = importlib.import_module("Effects")
    fn = getattr(Effects, factory_name)
    # The smoke factories share (… , pEmitFrom, kEmitPos, kEmitDir, pAttachTo).
    return fn(fVelocity, fLife, fSize, emit_from, emit_pos, emit_dir, emit_from)


class _ControllerHandle:
    """Spec B handle wrapping a live controller."""
    def __init__(self, controller):
        self._c = controller

    def stop_emitting(self):
        self._c.stop_emitting()

    def has_live_particles(self):
        return self._c.has_live_particles()


class ParticleBackend:
    """Spec A1 implementation of the Spec B §5 backend interface."""

    def create(self, factory, params, emit_pos_body, emit_dir, direction_mode,
               ship=None):
        from engine.appc import subsystem_emitters as se
        fVel = float(params.get("fVelocity", 1.0))
        fLife = float(params.get("fLife", 1.0))
        fSize = float(params.get("fSize", 1.0))
        action = _call_factory(factory, fVel, fLife, fSize, ship,
                               emit_pos_body, emit_dir)
        controller = action.GetController()
        if direction_mode == se.DirectionMode.SPHERICAL:
            controller.SetAngleVariance(max(controller._angle_variance, _SPHERICAL_ANGLE))
        # Sustained plume: emit until explicitly stopped (large EffectLifeTime).
        controller.SetEffectLifeTime(1.0e9)
        action.Start()
        return _ControllerHandle(controller)

    def fire_one_shot(self, factory, emit_pos_body, emit_dir, ship=None):
        action = _call_factory(factory, 1.0, 1.0, 1.0, ship,
                               emit_pos_body, emit_dir)
        controller = action.GetController()
        controller.SetEffectLifeTime(min(controller._effect_life_time, 1.5))
        action.Start()
```

Note: `_call_factory` passes `emit_pos`/`emit_dir` straight to the SDK factory's `kEmitPos`/`kEmitDir`; the SDK factory forwards them to `SetEmitPositionAndDirection`. When `ship` (`pEmitFrom`) is non-None the controller is attached and the host resolver supplies the instance + velocity. For SPHERICAL, `emit_dir` may be `None`; the SDK factory tolerates it (it forwards to the controller, and the renderer falls back to a default dir + the wide angle variance gives the omni look).

- [ ] **Step 4: Reconcile Spec B `_spawn` + `NullBackend` to pass `ship`**

In `engine/appc/subsystem_emitters.py`:
- `NullBackend.create` signature → `def create(self, factory, params, emit_pos_body, emit_dir, direction_mode, ship=None):` (accept + ignore).
- `PlumeManager._spawn`: change the backend call to pass the ship:
```python
    def _spawn(self, key, ship, sub, tier, descriptor):
        emit_pos_body, emit_dir = _emit_frame(ship, sub, descriptor)
        handle = self.backend.create(descriptor.factory, descriptor.params,
                                     emit_pos_body, emit_dir, descriptor.direction_mode,
                                     ship=ship)
        self._active[key] = _ActiveEmitter(tier, handle)
```
- `_go_destroyed`'s `fire_one_shot` call → pass `ship=ship`:
```python
            self.backend.fire_one_shot(puff, (p.x, p.y, p.z), None, ship=ship)
```
(`NullBackend.fire_one_shot` → `def fire_one_shot(self, factory, emit_pos_body, emit_dir, ship=None):`.)

Run the Spec B suite to confirm no regression:
Run: `uv run pytest tests/unit/test_subsystem_emitters_transitions.py tests/unit/test_subsystem_emitters_budget.py tests/unit/test_subsystem_emitters_persistence.py tests/unit/test_subsystem_emitters_anchor.py -q`
Expected: all pass (the added `ship=` kwarg is backward-compatible; `_go_destroyed` already has `ship`).

- [ ] **Step 5: Run the backend unit test**

Run: `uv run pytest tests/unit/test_particle_backend.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Install the backend + end-to-end test**

In `engine/host_loop.py`, where the host is initialised (once, near where other one-time engine setup runs — e.g. alongside the renderer/host bring-up), install the backend:
```python
    from engine.appc import subsystem_emitters, particles
    subsystem_emitters.set_backend(particles.ParticleBackend())
```
Pick the same one-time init site that already wires engine singletons; if there is no single obvious site, place it in the host-loop module import-time setup guarded so tests that import `host_loop` get the real backend. (A module-level call at the bottom of `host_loop.py` is acceptable if it has no import side effects beyond setting the backend.)

Extend `tests/integration/test_particles_host_loop.py`:

```python
def test_spec_b_plume_renders_through_particle_backend():
    from engine.appc import subsystem_emitters as se
    from engine.appc import particles as P
    from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
    se.reset_registry()
    se.reset_manager()
    P.reset()
    se.set_backend(P.ParticleBackend())
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    ship = FakeShip(subs=[sub])
    se.pump([ship], camera_pos=None, dt=0.1)
    # Spec B -> ParticleBackend -> a real smoke controller is now active.
    assert P.active_count() == 1
    assert P._active[0]._texture_path.endswith("ExplosionB.tga")
```

`FakeShip` needs to be acceptable as `pEmitFrom` to the SDK `CreateSmokeHigh` (it just stores it) — it is (a plain object). If the SDK factory calls a method on `pEmitFrom` that `FakeShip` lacks, extend `FakeShip` minimally in the test or pass a tolerant stub; the controller only stores the handle.

- [ ] **Step 7: Run the end-to-end + regression**

Run: `uv run pytest tests/integration/test_particles_host_loop.py tests/unit/test_particle_backend.py tests/unit/test_subsystem_emitters_transitions.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/particles.py engine/appc/subsystem_emitters.py engine/host_loop.py \
        tests/unit/test_particle_backend.py tests/integration/test_particles_host_loop.py
git commit -m "feat(particles): ParticleBackend + Spec B set_backend (plumes render for real)"
```

---

## Final verification

- [ ] **Run the full A1 Python suite + Spec B regression (focused — NEVER the whole suite; it OOMs the host):**

Run:
```
uv run pytest tests/unit/test_particles_controller.py tests/unit/test_particles_registry.py \
  tests/unit/test_particles_sdk_unmodified.py tests/unit/test_particle_backend.py \
  tests/integration/test_particles_host_loop.py \
  tests/unit/test_subsystem_emitters_transitions.py tests/unit/test_subsystem_emitters_budget.py \
  tests/unit/test_subsystem_emitters_persistence.py tests/integration/test_host_loop_m3gameflow.py -q
```
Expected: ALL PASS.

- [ ] **Build the native side + run renderer tests:**

Run: `cmake -B build -S . >/dev/null 2>&1; cmake --build build -j 2>&1 | tail -5 && ctest --test-dir build -R "Particle" --output-on-failure 2>&1 | tail -20`
Expected: build clean; `ParticleMath.*` pass; `ParticlePass.*` pass or skip (no offscreen GL/assets).

- [ ] **Confirm the developer can SEE it (manual, optional):** launch `./build/dauntless`, load a mission, damage a nacelle; a smoke plume should vent. (Gated on BC assets; not a CI check.)

---

## Notes for the implementer

- **Test memory:** never run the bare `uv run pytest` — it uses >100 GB RAM and freezes macOS. Use the focused file lists above.
- **Shader reconfigure:** A1 adds **no** shaders (reuses `hit_vfx_shader`), so `cmake --build` suffices for `.cc` changes. Only re-run `cmake -B build -S .` when adding the new `.cc`/test files to CMake (Tasks 1–3).
- **Mirror, don't reinvent:** the renderer GL boilerplate (`ensure_quad_mesh`, sprite loading, offscreen test fixture) is copied from `hit_vfx_pass.cc` and a sibling `*_pass_test.cc`. Read those first; the only novel renderer code is the analytic loop (Task 2) and the GL-free math (Task 1).
- **Art values are tune-by-eye** (spec §7). The numbers in the SDK factories are the starting point; do not treat them as final.
- **Backend `ship=` kwarg:** Task 8 extends Spec B's `create`/`fire_one_shot` calls with `ship=`. This is the one Spec B edit; it's additive and backward-compatible (NullBackend ignores it).
