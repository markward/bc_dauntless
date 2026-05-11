// native/src/renderer/dust_pass.cc
#include "renderer/dust_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>

#include <cmath>
#include <cstdint>

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

void DustPass::render(const scenegraph::Camera& /*camera*/,
                      float /*dt_seconds*/,
                      Pipeline& /*pipeline*/) {
    // Phase-1 placeholder: implemented incrementally in later tasks.
    (void)enabled_;
}

void DustPass::initialize_gl() {
    initialized_ = true;
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
    return false;
}

}  // namespace renderer
