// native/src/renderer/nebula_godray_pass.cc
#include "renderer/nebula_godray_pass.h"
#include "renderer/pipeline.h"
#include <scenegraph/camera.h>
#include <glad/glad.h>

namespace renderer {

NebulaGodrayPass::NebulaGodrayPass() = default;
NebulaGodrayPass::~NebulaGodrayPass() {
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void NebulaGodrayPass::initialize_gl() {
    glGenVertexArrays(1, &vao_);
    initialized_ = true;
}

void NebulaGodrayPass::render(const scenegraph::Camera& camera,
                              Pipeline& pipeline,
                              const std::vector<GodrayFlash>& flashes,
                              std::uint32_t hdr_color_tex) {
    (void)camera; (void)pipeline; (void)hdr_color_tex;
    if (!enabled_ || flashes.empty()) return;
    if (!initialized_) initialize_gl();
    // Task 5 draws the radial scatter here.
}

}  // namespace renderer
