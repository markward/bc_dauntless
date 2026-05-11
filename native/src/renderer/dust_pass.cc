// native/src/renderer/dust_pass.cc
#include "renderer/dust_pass.h"

#include "renderer/pipeline.h"

#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>

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
