// native/src/renderer/dust_pass.cc
#include "renderer/dust_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <vector>

namespace renderer {

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
        // Uniform in the cube [-radius, radius]^3. The shader wraps each
        // axis independently in a 2*radius cube, so uniform-in-cube is
        // the only seeding that survives wrap without density artifacts.
        // The fragment shader clips to the inscribed sphere, so visible
        // particles remain spherically bounded; ~48% of seeded particles
        // are in the cube's corners and get discarded — bake that into
        // kParticleCount upstream if a visible-density target matters.
        const float x = next_unit() * 2.0f - 1.0f;
        const float y = next_unit() * 2.0f - 1.0f;
        const float z = next_unit() * 2.0f - 1.0f;
        const float jitter = next_unit();
        out.emplace_back(x * radius, y * radius, z * radius, jitter);
    }
    return out;
}

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

    glm::vec3 smear = -velocity * kSmearSeconds;
    const float smear_len = glm::length(smear);
    if (smear_len > kMaxSmearLength) {
        smear *= (kMaxSmearLength / smear_len);
    }

    auto& shader = pipeline.dust_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());
    shader.set_vec3("u_camera_pos",      camera.eye);
    shader.set_vec3("u_smear",           smear);
    shader.set_float("u_radius",         kVolumeRadius);
    shader.set_float("u_size_min",       kSizeMin);
    shader.set_float("u_size_max",       kSizeMax);
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

bool DustPass::ensure_texture() {
    if (texture_) return texture_->id() != 0;
    // BC installation lives under `game/` per CLAUDE.md. Other passes
    // receive absolute paths from Python (engine/appc/backdrops.py
    // resolves them against project_root / "game"); the dust pass owns
    // its single texture, so the relative path is hardcoded here.
    const char* path = "game/data/Textures/spacedust.tga";
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

}  // namespace renderer
