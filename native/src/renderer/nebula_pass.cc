// native/src/renderer/nebula_pass.cc
#include "renderer/nebula_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace renderer {

NebulaPass::NebulaPass() = default;
NebulaPass::~NebulaPass() = default;

void NebulaPass::initialize_gl() {
    // GL objects created here in Task 6 (VAO/quad/instance buffers).
    initialized_ = true;
}

void NebulaPass::render(const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const std::vector<NebulaVolume>& volumes) {
    (void)camera;
    (void)pipeline;
    if (!enabled_ || volumes.empty()) return;
    if (!initialized_) initialize_gl();
    // Task 6 (inside fog) and Task 7 (outside shell) draw here.
}

}  // namespace renderer
