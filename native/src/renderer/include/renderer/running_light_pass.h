// native/src/renderer/include/renderer/running_light_pass.h
#pragma once

#include "renderer/running_light_store.h"

#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// Ship running lights: additive camera-facing soft discs. Depth-test on (the
/// hull hides far-side lights), depth-write off, GL state restored to the
/// canonical defaults. Zero GL work for an empty list.
class RunningLightPass {
public:
    RunningLightPass() = default;
    ~RunningLightPass();
    RunningLightPass(const RunningLightPass&)            = delete;
    RunningLightPass& operator=(const RunningLightPass&) = delete;

    void render(const scenegraph::Camera& camera, Pipeline& pipeline,
                const std::vector<RunningLightSprite>& sprites);

private:
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    void ensure_quad_mesh();
};

}  // namespace renderer
