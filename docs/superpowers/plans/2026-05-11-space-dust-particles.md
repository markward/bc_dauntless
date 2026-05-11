# Space Dust Particles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a renderer pass that draws ~2,048 world-space dust particles around the camera with motion-proportional smear, mirroring the original BC space-dust effect.

**Architecture:** New `DustPass` class mirroring `BackdropPass` / `SunPass` — header in `native/src/renderer/include/renderer/`, impl in `native/src/renderer/`, two embedded shaders, owned by `host_bindings.cc` via `unique_ptr`. Instanced rendering: one static quad mesh + per-instance `vec4` particle buffer (xyz position, w jitter). Recycling done in the vertex shader via toroidal wrapping around the camera position uniform. Smear via a uniform vector applied to quad corners along the camera velocity direction. Depth-tested, additive blend, no depth writes.

**Tech Stack:** C++20, OpenGL 3.3 core, glm, glad, GLFW, googletest, pybind11; Python facade in `engine/renderer.py`; key binding in `engine/host_loop.py`.

**Spec:** [docs/superpowers/specs/2026-05-11-space-dust-particles-design.md](../specs/2026-05-11-space-dust-particles-design.md)

---

## Task 1: DustPass skeleton compiles

**Files:**
- Create: `native/src/renderer/include/renderer/dust_pass.h`
- Create: `native/src/renderer/dust_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `dust_pass.cc` to the `renderer` static lib)

- [ ] **Step 1: Create the header**

Write to `native/src/renderer/include/renderer/dust_pass.h`:

```cpp
// native/src/renderer/include/renderer/dust_pass.h
#pragma once

#include <glm/glm.hpp>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace assets { class Texture; }
namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

class DustPass {
public:
    // Tunable constants. Documented in the spec as the dials for visual
    // tuning. Changing these does not break correctness; it only changes
    // how the effect looks.
    static constexpr int   kParticleCount        = 2048;
    static constexpr float kVolumeRadius         = 40.0f;       // BC units
    static constexpr float kSmearSeconds         = 1.0f / 30.0f;
    static constexpr float kSizeMin              = 0.8f;        // BC units
    static constexpr float kSizeMax              = 1.4f;
    static constexpr float kBrightnessMin        = 0.5f;
    static constexpr float kBrightnessMax        = 1.0f;
    static constexpr float kVelocityClampSeconds = 0.1f;        // dt guard
    static constexpr std::uint32_t kSeed         = 0xD057C0DEu; // "DOST CODE"

    DustPass();
    ~DustPass();
    DustPass(const DustPass&) = delete;
    DustPass& operator=(const DustPass&) = delete;

    /// Render the dust pass. Caller is responsible for the scene depth
    /// buffer being populated (so ships/planets occlude dust correctly).
    /// `dt_seconds` is the host-loop frame delta used for velocity.
    void render(const scenegraph::Camera& camera,
                float dt_seconds,
                Pipeline& pipeline);

    void set_enabled(bool enabled) { enabled_ = enabled; }
    bool enabled() const { return enabled_; }

    /// Reseed the per-instance buffer with `count` particles (clamped to
    /// [0, 50000]). Used by the deferred dynamic-density work; safe to
    /// call from the same thread as render().
    void set_density(int count);

private:
    bool       enabled_      = true;
    bool       initialized_  = false;   // GL objects created lazily on first render
    glm::vec3  prev_eye_     = glm::vec3(0.0f);
    bool       have_prev_    = false;
    int        particle_count_ = kParticleCount;

    // GL objects, populated in initialize_gl(). 0 means "not yet created".
    unsigned int vao_              = 0;
    unsigned int quad_vbo_         = 0;
    unsigned int quad_ebo_         = 0;
    unsigned int instance_vbo_     = 0;

    std::unique_ptr<assets::Texture> texture_;

    void initialize_gl();
    void rebuild_instance_buffer(std::uint32_t seed, int count);
    bool ensure_texture();
};

}  // namespace renderer
```

- [ ] **Step 2: Create the impl with empty methods**

Write to `native/src/renderer/dust_pass.cc`:

```cpp
// native/src/renderer/dust_pass.cc
#include "renderer/dust_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>

#include <cstdio>

namespace renderer {

DustPass::DustPass() = default;

DustPass::~DustPass() {
    if (vao_) glDeleteVertexArrays(1, &vao_);
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_ebo_) glDeleteBuffers(1, &quad_ebo_);
    if (instance_vbo_) glDeleteBuffers(1, &instance_vbo_);
}

void DustPass::set_density(int count) {
    if (count < 0) count = 0;
    if (count > 50000) count = 50000;
    particle_count_ = count;
    if (initialized_) rebuild_instance_buffer(kSeed, particle_count_);
}

void DustPass::render(const scenegraph::Camera& /*camera*/,
                      float /*dt_seconds*/,
                      Pipeline& /*pipeline*/) {
    // Phase-1 placeholder: implemented incrementally in later tasks.
    (void)enabled_;
}

void DustPass::initialize_gl() {
    initialized_ = true;
}

void DustPass::rebuild_instance_buffer(std::uint32_t /*seed*/, int /*count*/) {
    // Phase-1 placeholder.
}

bool DustPass::ensure_texture() {
    return false;
}

}  // namespace renderer
```

- [ ] **Step 3: Add to the renderer CMakeLists**

Modify `native/src/renderer/CMakeLists.txt`. Find the `add_library(renderer STATIC ...)` block and add `dust_pass.cc` to the source list:

```cmake
add_library(renderer STATIC
    window.cc
    shader.cc
    pipeline.cc
    frame.cc
    sphere_mesh.cc
    backdrop_pass.cc
    sun_pass.cc
    dust_pass.cc
)
```

- [ ] **Step 4: Build to verify the skeleton compiles**

Run: `cmake --build build -j 2>&1 | tail -30`
Expected: build succeeds, no errors. `renderer` static lib relinked.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/dust_pass.h \
        native/src/renderer/dust_pass.cc \
        native/src/renderer/CMakeLists.txt
git commit -m "feat(renderer): DustPass skeleton (no rendering yet)"
```

---

## Task 2: Particle buffer generation (pure CPU, unit-testable)

**Files:**
- Modify: `native/src/renderer/dust_pass.cc` (implement `rebuild_instance_buffer` against a `std::vector<glm::vec4>` buffer)
- Create: `native/tests/renderer/dust_pass_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add the new test)

- [ ] **Step 1: Expose a free function for testing**

Add to `native/src/renderer/include/renderer/dust_pass.h`, inside `namespace renderer`, before `class DustPass`:

```cpp
/// Generate `count` particle records uniformly distributed inside a
/// sphere of radius `radius`, with deterministic per-particle jitter in
/// the w channel. Pure CPU; testable without a GL context.
///
/// Output layout: vec4(x, y, z, jitter) where jitter in [0, 1).
std::vector<glm::vec4> generate_dust_particles(std::uint32_t seed,
                                               int count,
                                               float radius);

/// C++ mirror of the GLSL toroidal-wrap formula in dust.vert. Kept
/// here as a regression guard; the shader is the source of truth for
/// rendering. If the two ever drift, visual tuning will catch it
/// before this test does.
glm::vec3 wrap_local_for_test(glm::vec3 particle_pos,
                              glm::vec3 camera_pos,
                              float radius);
```

- [ ] **Step 2: Implement the generator**

In `native/src/renderer/dust_pass.cc`, add at the top of the `namespace renderer` block (above the class methods):

```cpp
std::vector<glm::vec4> generate_dust_particles(std::uint32_t seed,
                                               int count,
                                               float radius) {
    std::vector<glm::vec4> out;
    if (count <= 0) return out;
    out.reserve(static_cast<std::size_t>(count));

    // splitmix32 — small, deterministic, no <random> overhead. Sufficient
    // for uncorrelated sample dimensions when stepped per-output.
    std::uint32_t s = seed;
    auto next_u32 = [&s]() -> std::uint32_t {
        s += 0x9E3779B9u;
        std::uint32_t z = s;
        z = (z ^ (z >> 16)) * 0x85EBCA6Bu;
        z = (z ^ (z >> 13)) * 0xC2B2AE35u;
        return z ^ (z >> 16);
    };
    auto next_unit = [&]() -> float {
        // 24 bits → float in [0, 1). 16777216.0f = 2^24.
        return static_cast<float>(next_u32() >> 8) / 16777216.0f;
    };

    for (int i = 0; i < count; ++i) {
        // Rejection sampling in a cube → uniform in sphere. Avg ~1.9
        // iterations per particle; the bounded count keeps this cheap.
        float x, y, z, r2;
        do {
            x = next_unit() * 2.0f - 1.0f;
            y = next_unit() * 2.0f - 1.0f;
            z = next_unit() * 2.0f - 1.0f;
            r2 = x*x + y*y + z*z;
        } while (r2 > 1.0f || r2 < 1e-8f);
        const float jitter = next_unit();
        out.emplace_back(x * radius, y * radius, z * radius, jitter);
    }
    return out;
}
```

- [ ] **Step 2b: Implement the wrap-math mirror**

Below `generate_dust_particles` in `native/src/renderer/dust_pass.cc`, add:

```cpp
glm::vec3 wrap_local_for_test(glm::vec3 particle_pos,
                              glm::vec3 camera_pos,
                              float radius) {
    glm::vec3 local = particle_pos - camera_pos;
    // std::fmod is not equivalent to GLSL mod() for negative dividends.
    // GLSL: mod(x, y) = x - y * floor(x / y). Always non-negative for
    // positive y. Reproduce that explicitly.
    auto glsl_mod = [](float x, float y) {
        return x - y * std::floor(x / y);
    };
    const float two_r = 2.0f * radius;
    local.x = glsl_mod(local.x + radius, two_r) - radius;
    local.y = glsl_mod(local.y + radius, two_r) - radius;
    local.z = glsl_mod(local.z + radius, two_r) - radius;
    return local;
}
```

Add `#include <cmath>` to `dust_pass.cc` if not already present.

- [ ] **Step 3: Wire `rebuild_instance_buffer` to use it**

Replace the `rebuild_instance_buffer` body in `native/src/renderer/dust_pass.cc`:

```cpp
void DustPass::rebuild_instance_buffer(std::uint32_t seed, int count) {
    if (instance_vbo_ == 0) return;
    const auto data = generate_dust_particles(seed, count, kVolumeRadius);
    glBindBuffer(GL_ARRAY_BUFFER, instance_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(data.size() * sizeof(glm::vec4)),
                 data.empty() ? nullptr : data.data(),
                 GL_STATIC_DRAW);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    particle_count_ = count;
}
```

- [ ] **Step 4: Write the failing test**

Write to `native/tests/renderer/dust_pass_test.cc`:

```cpp
// native/tests/renderer/dust_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/dust_pass.h>

#include <glm/glm.hpp>

#include <cmath>

TEST(DustPassGen, DeterministicSeedProducesIdenticalBuffers) {
    auto a = renderer::generate_dust_particles(12345u, 100, 40.0f);
    auto b = renderer::generate_dust_particles(12345u, 100, 40.0f);
    ASSERT_EQ(a.size(), b.size());
    ASSERT_EQ(a.size(), 100u);
    for (std::size_t i = 0; i < a.size(); ++i) {
        EXPECT_EQ(a[i].x, b[i].x) << "at index " << i;
        EXPECT_EQ(a[i].y, b[i].y);
        EXPECT_EQ(a[i].z, b[i].z);
        EXPECT_EQ(a[i].w, b[i].w);
    }
}

TEST(DustPassGen, AllPositionsInsideSphereWithCorrectJitter) {
    const float R = 40.0f;
    auto particles = renderer::generate_dust_particles(0xABCDu, 2048, R);
    ASSERT_EQ(particles.size(), 2048u);
    for (const auto& p : particles) {
        const float r = std::sqrt(p.x*p.x + p.y*p.y + p.z*p.z);
        EXPECT_LE(r, R + 1e-4f);
        EXPECT_GE(p.w, 0.0f);
        EXPECT_LT(p.w, 1.0f);
    }
}

TEST(DustPassGen, ZeroCountProducesEmptyBuffer) {
    auto particles = renderer::generate_dust_particles(1u, 0, 40.0f);
    EXPECT_TRUE(particles.empty());
}

TEST(DustPassGen, DifferentSeedsProduceDifferentBuffers) {
    auto a = renderer::generate_dust_particles(1u, 50, 40.0f);
    auto b = renderer::generate_dust_particles(2u, 50, 40.0f);
    ASSERT_EQ(a.size(), b.size());
    bool any_diff = false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (a[i] != b[i]) { any_diff = true; break; }
    }
    EXPECT_TRUE(any_diff);
}

TEST(DustPassWrap, WrappedLocalAlwaysInsideCube) {
    const float R = 40.0f;
    // A grid of arbitrary (particle, camera) pairs spanning several
    // sphere-widths in both directions.
    for (float px = -200.0f; px <= 200.0f; px += 37.0f) {
        for (float cx = -200.0f; cx <= 200.0f; cx += 41.0f) {
            const auto local = renderer::wrap_local_for_test(
                {px, 0.0f, 0.0f}, {cx, 0.0f, 0.0f}, R);
            EXPECT_GE(local.x, -R);
            EXPECT_LT(local.x,  R);
        }
    }
}

TEST(DustPassWrap, ZeroCameraOffsetIsIdentityInsideSphere) {
    const float R = 40.0f;
    const glm::vec3 inside(10.0f, -5.0f, 15.0f);
    const auto local = renderer::wrap_local_for_test(inside,
                                                     glm::vec3(0.0f), R);
    EXPECT_FLOAT_EQ(local.x, inside.x);
    EXPECT_FLOAT_EQ(local.y, inside.y);
    EXPECT_FLOAT_EQ(local.z, inside.z);
}
```

- [ ] **Step 5: Add the test to the renderer test executable**

Modify `native/tests/renderer/CMakeLists.txt`. Add `dust_pass_test.cc` to the `add_executable(renderer_tests ...)` source list:

```cmake
add_executable(renderer_tests
    window_test.cc
    shader_test.cc
    pipeline_test.cc
    frame_test.cc
    backdrop_pass_test.cc
    sun_pass_test.cc
    dust_pass_test.cc
)
```

- [ ] **Step 6: Configure + build**

Run: `cmake -B build -S . 2>&1 | tail -10 && cmake --build build -j 2>&1 | tail -20`
Expected: build succeeds. `renderer_tests` executable is rebuilt.

- [ ] **Step 7: Run the new tests**

Run: `./build/native/tests/renderer/renderer_tests --gtest_filter='DustPassGen.*:DustPassWrap.*'`
Expected: 6 tests pass.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/dust_pass.h \
        native/src/renderer/dust_pass.cc \
        native/tests/renderer/dust_pass_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): deterministic dust particle generator + tests"
```

---

## Task 3: Shaders and Pipeline integration

**Files:**
- Create: `native/src/renderer/shaders/dust.vert`
- Create: `native/src/renderer/shaders/dust.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (embed both shaders)
- Modify: `native/src/renderer/include/renderer/pipeline.h` (add `dust_shader_`)
- Modify: `native/src/renderer/pipeline.cc` (instantiate it)

- [ ] **Step 1: Write the vertex shader**

Write to `native/src/renderer/shaders/dust.vert`:

```glsl
#version 330 core

// Per-vertex (the quad). 4 vertices total.
layout(location = 0) in vec2 a_corner;     // in {-1,-1}, {+1,-1}, {-1,+1}, {+1,+1}
layout(location = 1) in vec2 a_uv;         // matching UVs in [0,1]

// Per-instance (the particle). N instances.
layout(location = 2) in vec4 a_particle;   // xyz = world pos, w = jitter

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_camera_pos;
uniform vec3  u_smear;          // -camera_velocity * smear_seconds
uniform float u_radius;
uniform float u_size_min;
uniform float u_size_max;
uniform float u_brightness_min;
uniform float u_brightness_max;

out vec2  v_uv;
out float v_brightness;
out vec3  v_local;

void main() {
    // Toroidal wrap of the particle's world position into a 2R cube
    // around the camera. mod() is GLSL's true modulo (always
    // non-negative for positive divisor).
    vec3 local = a_particle.xyz - u_camera_pos;
    local = mod(local + u_radius, 2.0 * u_radius) - u_radius;
    vec3 world_pos = u_camera_pos + local;

    // Billboard basis from the inverse rotation of the view matrix.
    // For an orthonormal view rotation, inverse == transpose, so the
    // world-space camera-right vector is the first row of the rotation
    // submatrix.
    vec3 cam_right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 cam_up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);

    // Per-particle size and brightness from the jitter channel. Multiply
    // jitter by 7.0 then take the fractional part to decorrelate size
    // from brightness while staying single-channel.
    float jitter = a_particle.w;
    float size       = mix(u_size_min,       u_size_max,       fract(jitter * 7.0));
    float brightness = mix(u_brightness_min, u_brightness_max, jitter);

    vec3 offset = a_corner.x * size * cam_right
                + a_corner.y * size * cam_up;

    // Stretch the leading edge (a_corner.y > 0) and trailing edge along
    // the smear vector. Half the smear length on each side gives a total
    // streak length equal to |u_smear|.
    offset += 0.5 * a_corner.y * u_smear;

    gl_Position = u_proj * u_view * vec4(world_pos + offset, 1.0);

    v_uv = a_uv;
    v_brightness = brightness;
    v_local = local;
}
```

- [ ] **Step 2: Write the fragment shader**

Write to `native/src/renderer/shaders/dust.frag`:

```glsl
#version 330 core

in vec2  v_uv;
in float v_brightness;
in vec3  v_local;

uniform sampler2D u_dust_tex;
uniform float     u_radius;

out vec4 out_color;

void main() {
    float r = length(v_local);
    if (r > u_radius) discard;
    vec4 tex = texture(u_dust_tex, v_uv);
    float fade = 1.0 - smoothstep(u_radius * 0.85, u_radius, r);
    out_color = vec4(tex.rgb * v_brightness, tex.a * fade);
}
```

- [ ] **Step 3: Embed both shaders via CMake**

Modify `native/src/renderer/CMakeLists.txt`. Below the existing `embed_shader(SHADER_SUN_FS ...)` line, add:

```cmake
embed_shader(SHADER_DUST_VS shaders/dust.vert dust_vs)
embed_shader(SHADER_DUST_FS shaders/dust.frag dust_fs)
```

- [ ] **Step 4: Add `dust_shader_` to Pipeline header**

Modify `native/src/renderer/include/renderer/pipeline.h`. Add accessor and member alongside the existing ones:

```cpp
class Pipeline {
public:
    Pipeline();

    Shader& opaque_shader()   noexcept { return *opaque_; }
    Shader& backdrop_shader() noexcept { return *backdrop_; }
    Shader& sun_shader()      noexcept { return *sun_; }
    Shader& dust_shader()     noexcept { return *dust_; }

private:
    std::unique_ptr<Shader> opaque_;
    std::unique_ptr<Shader> backdrop_;
    std::unique_ptr<Shader> sun_;
    std::unique_ptr<Shader> dust_;
};
```

- [ ] **Step 5: Instantiate `dust_` in the Pipeline ctor**

Modify `native/src/renderer/pipeline.cc`. Add the include and the construction line:

```cpp
#include "embedded_dust_vs.h"
#include "embedded_dust_fs.h"
```

In the Pipeline ctor, alongside the existing shader assignments:

```cpp
dust_ = std::make_unique<Shader>(shader_src::dust_vs, shader_src::dust_fs);
```

- [ ] **Step 6: Build to verify shaders compile**

Run: `cmake -B build -S . 2>&1 | tail -5 && cmake --build build -j 2>&1 | tail -20`
Expected: build succeeds. If a shader compile fails it shows up at runtime, not build time — the `embed_shader` step is just configure_file copying GLSL into a header. The build verifies the C++ side compiles.

- [ ] **Step 7: Run the existing pipeline tests to verify shaders link at runtime**

Run: `./build/native/tests/renderer/renderer_tests --gtest_filter='PipelineTest.*'`
Expected: existing pipeline tests still pass (they construct a `Pipeline`, which now also compiles+links the dust shader; a GLSL error here would surface as a thrown exception from `Shader::Shader`).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/shaders/dust.vert \
        native/src/renderer/shaders/dust.frag \
        native/src/renderer/CMakeLists.txt \
        native/src/renderer/include/renderer/pipeline.h \
        native/src/renderer/pipeline.cc
git commit -m "feat(renderer): dust shader pair + Pipeline wiring"
```

---

## Task 4: GL object setup and instanced draw

**Files:**
- Modify: `native/src/renderer/dust_pass.cc` (implement `initialize_gl`, `ensure_texture`, and `render`)

- [ ] **Step 1: Implement `initialize_gl`**

Replace the `initialize_gl` body in `native/src/renderer/dust_pass.cc`:

```cpp
void DustPass::initialize_gl() {
    if (initialized_) return;

    // Quad: 4 verts, 6 indices. Corners in NDC-ish local space [-1, +1]
    // matched with UVs in [0, 1]. Layout: vec2 corner, vec2 uv.
    const float quad_verts[] = {
        // corner.xy        uv.xy
        -1.0f, -1.0f,       0.0f, 0.0f,
        +1.0f, -1.0f,       1.0f, 0.0f,
        -1.0f, +1.0f,       0.0f, 1.0f,
        +1.0f, +1.0f,       1.0f, 1.0f,
    };
    const unsigned int quad_idx[] = { 0, 1, 2, 2, 1, 3 };

    glGenVertexArrays(1, &vao_);
    glBindVertexArray(vao_);

    glGenBuffers(1, &quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad_verts), quad_verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float),
                          reinterpret_cast<void*>(2 * sizeof(float)));
    glEnableVertexAttribArray(1);

    glGenBuffers(1, &quad_ebo_);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, quad_ebo_);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(quad_idx), quad_idx,
                 GL_STATIC_DRAW);

    glGenBuffers(1, &instance_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, instance_vbo_);
    glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof(glm::vec4),
                          reinterpret_cast<void*>(0));
    glEnableVertexAttribArray(2);
    glVertexAttribDivisor(2, 1);   // per-instance

    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);

    initialized_ = true;

    // First population of the instance buffer.
    rebuild_instance_buffer(kSeed, particle_count_);
}
```

- [ ] **Step 2: Implement `ensure_texture`**

Replace the `ensure_texture` body in `native/src/renderer/dust_pass.cc`. Add the necessary includes at the top of the file:

```cpp
#include <assets/image.h>
#include <fstream>
#include <vector>
```

Body:

```cpp
bool DustPass::ensure_texture() {
    if (texture_) return texture_->id() != 0;
    const char* path = "data/Textures/spacedust.tga";
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[dust] failed to open '%s'\n", path);
        texture_ = std::make_unique<assets::Texture>();  // sentinel (id == 0)
        return false;
    }
    in.seekg(0, std::ios::end);
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    try {
        assets::Image img = assets::decode_tga(bytes);
        texture_ = std::make_unique<assets::Texture>(
            assets::upload_image(img, /*generate_mipmaps=*/true));
        return true;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[dust] failed to decode '%s': %s\n", path, e.what());
        texture_ = std::make_unique<assets::Texture>();
        return false;
    }
}
```

- [ ] **Step 3: Implement `render`**

Replace the placeholder `render` body in `native/src/renderer/dust_pass.cc`:

```cpp
void DustPass::render(const scenegraph::Camera& camera,
                      float dt_seconds,
                      Pipeline& pipeline) {
    if (!enabled_ || particle_count_ <= 0) {
        // Still update prev_eye_ tracking so we don't get a phantom huge
        // velocity on the frame after re-enabling.
        prev_eye_ = camera.eye;
        have_prev_ = true;
        return;
    }
    initialize_gl();
    if (!ensure_texture()) return;

    // Camera velocity in world units / second. First frame and abnormal
    // dt suppress the streak entirely.
    glm::vec3 velocity(0.0f);
    if (have_prev_ && dt_seconds > 0.0f && dt_seconds < kVelocityClampSeconds) {
        velocity = (camera.eye - prev_eye_) / dt_seconds;
    }
    prev_eye_ = camera.eye;
    have_prev_ = true;

    const glm::vec3 smear = -velocity * kSmearSeconds;

    auto& shader = pipeline.dust_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());
    shader.set_vec3("u_camera_pos",     camera.eye);
    shader.set_vec3("u_smear",          smear);
    shader.set_float("u_radius",        kVolumeRadius);
    shader.set_float("u_size_min",      kSizeMin);
    shader.set_float("u_size_max",      kSizeMax);
    shader.set_float("u_brightness_min", kBrightnessMin);
    shader.set_float("u_brightness_max", kBrightnessMax);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, texture_->id());
    shader.set_int("u_dust_tex", 0);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);          // additive
    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);                    // billboards face the camera

    glBindVertexArray(vao_);
    glDrawElementsInstanced(GL_TRIANGLES, 6, GL_UNSIGNED_INT, nullptr,
                            particle_count_);
    glBindVertexArray(0);

    // Restore defaults so later passes don't inherit our state.
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glDisable(GL_BLEND);
}
```

- [ ] **Step 4: Verify `Shader` has the helpers we're calling**

Run: `grep -n 'set_mat4\|set_vec3\|set_float\|set_int' native/src/renderer/include/renderer/shader.h`
Expected: each helper is present. If `set_float` or `set_vec3` is missing, add it now using the existing methods as a template.

- [ ] **Step 5: Build**

Run: `cmake --build build -j 2>&1 | tail -20`
Expected: build succeeds.

- [ ] **Step 6: Add a GL-context smoke test**

Add this test to `native/tests/renderer/dust_pass_test.cc` (after the existing tests):

```cpp
#include <renderer/dust_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace {

class DustPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        window = std::make_unique<renderer::Window>(256, 256, "dust_test", false);
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }
};

TEST_F(DustPassGLTest, RenderProducesNoGLError) {
    renderer::DustPass pass;
    scenegraph::Camera cam;
    cam.eye = {0, 0, 100};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    // First call: have_prev_ false, velocity = 0; no streaks.
    pass.render(cam, 1.0f / 60.0f, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    // Second call: real dt, velocity = 0 (eye unchanged).
    pass.render(cam, 1.0f / 60.0f, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(DustPassGLTest, DisabledPassDoesNothing) {
    renderer::DustPass pass;
    pass.set_enabled(false);
    scenegraph::Camera cam;
    cam.eye = {0, 0, 100};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    pass.render(cam, 1.0f / 60.0f, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(DustPassGLTest, SetDensityZeroIsSafe) {
    renderer::DustPass pass;
    pass.set_density(0);
    scenegraph::Camera cam;
    cam.eye = {0, 0, 100};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    pass.render(cam, 1.0f / 60.0f, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
```

- [ ] **Step 7: Build and run the new tests**

Run: `cmake --build build -j 2>&1 | tail -10 && ./build/native/tests/renderer/renderer_tests --gtest_filter='DustPassGLTest.*'`
Expected: 3 tests pass.

Note: tests will hit the `[dust] failed to open` stderr path unless they happen to find `data/Textures/spacedust.tga` relative to cwd. That's fine — the pass returns early without GL errors. The integration test in Task 5 will exercise the real-texture path.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/dust_pass.cc \
        native/tests/renderer/dust_pass_test.cc
git commit -m "feat(renderer): DustPass GL setup, instanced draw, smoke tests"
```

---

## Task 5: Wire DustPass into the host frame loop

**Files:**
- Modify: `native/src/host/host_bindings.cc` (add `g_dust_pass`, plumb dt, call render)

- [ ] **Step 1: Add include and global**

In `native/src/host/host_bindings.cc`, alongside the existing pass includes (near line 22-23):

```cpp
#include <renderer/dust_pass.h>
```

In the `namespace { ... }` block alongside `g_sun_pass` (around line 50):

```cpp
std::unique_ptr<renderer::DustPass> g_dust_pass;
```

- [ ] **Step 2: Track frame time for dt**

In the same anonymous namespace, add:

```cpp
double g_prev_frame_time_seconds = 0.0;
```

- [ ] **Step 3: Initialize the pass in `init()`**

In the `init()` function, alongside the existing pass construction (around line 110, after `g_sun_pass = std::make_unique<...>()`):

```cpp
g_dust_pass = std::make_unique<renderer::DustPass>();
g_prev_frame_time_seconds = glfwGetTime();
```

- [ ] **Step 4: Reset in `shutdown()`**

In the `shutdown()` function, alongside `g_sun_pass.reset()`:

```cpp
g_dust_pass.reset();
```

- [ ] **Step 5: Call render() from `frame()`**

In `frame()`, after `g_sun_pass->render(...)` and before `g_submitter->submit_opaque(...)`, add the dt computation. Actually order matters: per the spec, dust draws **after** opaque (so ships occlude dust). Place the dust render AFTER `submit_opaque` but BEFORE the UI render block:

```cpp
g_submitter->submit_opaque(g_world, g_camera, *g_pipeline, lookup, g_lighting);

const double now = glfwGetTime();
const float  dt  = static_cast<float>(now - g_prev_frame_time_seconds);
g_prev_frame_time_seconds = now;
if (g_dust_pass) g_dust_pass->render(g_camera, dt, *g_pipeline);

if (g_ui_system) {
    ...
}
```

- [ ] **Step 6: Build**

Run: `cmake --build build -j 2>&1 | tail -15`
Expected: build succeeds.

- [ ] **Step 7: Visual verification — dust is rendering**

Run: `./build/open_stbc`
Expected: faint white dots scattered around the camera, visible when stationary. When the ship moves (W key per controls), the dots elongate into short streaks oriented along the motion direction. Ships and planets correctly occlude particles behind them. Close the window when satisfied.

Document the outcome in the next commit message. If dust is not visible: check that `game/data/Textures/spacedust.tga` exists and the working directory is the project root.

- [ ] **Step 8: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): wire DustPass into frame loop (visible by default)"
```

---

## Task 6: Python toggle API

**Files:**
- Modify: `native/src/host/host_bindings.cc` (expose `dust_set_enabled`, `dust_set_density`, `KEY_F7`)
- Modify: `engine/renderer.py` (add facade functions)
- Create: `tests/engine/test_dust_facade.py`

- [ ] **Step 1: Expose `dust_set_enabled` and `dust_set_density` in pybind11**

In `native/src/host/host_bindings.cc`, find the `PYBIND11_MODULE` block (search for `PYBIND11_MODULE` or `m.def(`). Alongside the existing `m.def("set_suns", ...)` etc., add:

```cpp
m.def("dust_set_enabled", [](bool enabled) {
    if (g_dust_pass) g_dust_pass->set_enabled(enabled);
}, "Toggle the space-dust pass at runtime. Default: on.");

m.def("dust_set_density", [](int count) {
    if (g_dust_pass) g_dust_pass->set_density(count);
}, "Reseed the dust particle buffer with `count` particles "
   "(clamped to [0, 50000]).");
```

- [ ] **Step 2: Expose `KEY_F7`**

Find the `keys.attr("KEY_F8") = GLFW_KEY_F8;` line (around line 361). Add immediately above it:

```cpp
keys.attr("KEY_F7")    = GLFW_KEY_F7;
```

- [ ] **Step 3: Add facade in `engine/renderer.py`**

In `engine/renderer.py`, after `set_hud_state` (the last existing function), add:

```python
def set_dust_enabled(enabled: bool) -> None:
    """Toggle the space-dust pass. Default: on after init()."""
    _h.dust_set_enabled(enabled)


def set_dust_density(count: int) -> None:
    """Reseed the dust particle buffer with `count` particles
    (clamped to [0, 50000])."""
    _h.dust_set_density(count)
```

- [ ] **Step 4: Write the facade test**

Write to `tests/engine/test_dust_facade.py`:

```python
"""Coverage for engine.renderer.set_dust_enabled / set_dust_density.

Exercises the pybind11 surface only — no rendering. Uses the headless
window fixture path (OPEN_STBC_HOST_HEADLESS=1).
"""
import os

import pytest


@pytest.fixture(scope="module")
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import engine.renderer as r
    r.init(64, 64, "dust_facade_test", "")
    yield r
    r.shutdown()


def test_set_dust_enabled_accepts_both_states(host):
    host.set_dust_enabled(False)
    host.set_dust_enabled(True)
    # Just verify the call returns without raising.


def test_set_dust_density_accepts_normal_count(host):
    host.set_dust_density(1024)


def test_set_dust_density_clamps_negative(host):
    # Implementation clamps to 0 internally; we just verify no exception.
    host.set_dust_density(-5)


def test_set_dust_density_clamps_huge(host):
    host.set_dust_density(10_000_000)
```

- [ ] **Step 5: Build the extension and run the test**

Run: `cmake --build build -j 2>&1 | tail -5 && uv run pytest tests/engine/test_dust_facade.py -v`
Expected: 4 tests pass.

If the test imports fail to find `_open_stbc_host`, check `tests/conftest.py` for the `sys.path` setup that points at `build/python/`.

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc \
        engine/renderer.py \
        tests/engine/test_dust_facade.py
git commit -m "feat: Python facade for dust toggle + density"
```

---

## Task 7: F7 keybinding in the host loop

**Files:**
- Modify: `engine/host_loop.py` (add F7 → toggle dust)

- [ ] **Step 1: Add the toggle near the existing F8/F9 block**

In `engine/host_loop.py`, find the existing F-key block (around line 766-771). Add immediately above it, and add a tracking variable in scope so we know which state to flip to. Replace this block:

```python
            # F8 toggles the RmlUi debugger overlay; F9 toggles whole-UI
            # visibility (skip rendering all RmlUi documents).
            if _h is not None and _h.key_pressed(_h.keys.KEY_F8):
                _h.toggle_ui_debugger()
            if _h is not None and _h.key_pressed(_h.keys.KEY_F9):
                _h.toggle_ui_visibility()
```

with:

```python
            # F7 toggles space dust; F8 toggles the RmlUi debugger
            # overlay; F9 toggles whole-UI visibility.
            if _h is not None and _h.key_pressed(_h.keys.KEY_F7):
                _dust_enabled = not _dust_enabled
                _h.dust_set_enabled(_dust_enabled)
            if _h is not None and _h.key_pressed(_h.keys.KEY_F8):
                _h.toggle_ui_debugger()
            if _h is not None and _h.key_pressed(_h.keys.KEY_F9):
                _h.toggle_ui_visibility()
```

- [ ] **Step 2: Initialize `_dust_enabled` before the loop**

In `engine/host_loop.py`, immediately before the `while not r.should_close():` line (around line 763), add:

```python
        _dust_enabled = True   # mirrors DustPass default
```

- [ ] **Step 3: Run pyflakes/import-sanity by starting the binary**

Run: `./build/open_stbc &` then `sleep 3 && pkill open_stbc` to confirm it boots.
Expected: window opens, no Python errors in stderr. The dust is visible by default.

For interactive verification: launch `./build/open_stbc`, press `F7` repeatedly, confirm the dust toggles on and off cleanly with no flicker or hitch. Press `F8` and `F9` to confirm those bindings still work. Close.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): F7 toggles space dust"
```

---

## Task 8: Final visual verification + README/spec cross-reference

**Files:**
- Modify: `CLAUDE.md` (add a one-line reference under "Key reference material")

- [ ] **Step 1: Run the visual verification checklist**

Run: `./build/open_stbc`

Verify, in order, by eye:

1. Dust is visible as faint dots when the ship is stationary.
2. Dust elongates into short streaks when the ship accelerates.
3. Streaks aligned with camera-relative motion direction.
4. F7 toggles cleanly.
5. No popping at the sphere boundary (alpha fade working).
6. Ships and planets occlude particles behind them.
7. Sun corona still draws correctly (no state contamination).
8. F8 (UI debugger) and F9 (UI visibility) still work.

If any check fails, file a follow-up task and do not proceed.

- [ ] **Step 2: Add a CLAUDE.md reference**

Modify `CLAUDE.md`. Find the "Key reference material" table and add one row at the bottom (or in the natural alphabetical place):

```markdown
| Space dust pass | `native/src/renderer/dust_pass.cc`, `docs/superpowers/specs/2026-05-11-space-dust-particles-design.md` | Camera-anchored dust particles with motion smear |
```

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `ctest --test-dir build --output-on-failure 2>&1 | tail -20 && uv run pytest -q 2>&1 | tail -20`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: cross-reference space-dust pass from CLAUDE.md"
```

---

## Notes for the implementer

- **Do not skip the visual verification step.** Per project memory, macOS GLFW hidden windows don't reliably present BACK→FRONT swaps, so headless pixel checks would be misleading. The visible binary is the source of truth for "does it look right."
- **Do not paper over GL errors.** If `glGetError()` reports anything non-zero in a test, find the root cause — don't add `glGetError()` calls to clear queues or wrap things in try/except.
- **Tunable constants** live in `DustPass` as `static constexpr`. If during visual tuning you want to change `kVolumeRadius`, `kSmearSeconds`, etc., edit them in the header and rebuild. The spec lists initial values; final values are a visual-feel decision.
- **Do not introduce new file output paths.** Per CLAUDE.md, the build tree is `<project-root>/build/` and the binary is `build/open_stbc`. Don't run cmake from inside `native/`.
