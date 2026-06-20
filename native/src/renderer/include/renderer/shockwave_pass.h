#pragma once

#include <renderer/frame.h>

#include <vector>

namespace scenegraph { class Camera; }

namespace renderer {

class Pipeline;

// Draws warp-core breach shockwaves: one additive, camera-facing billboard
// quad per descriptor; the fragment shader animates a ring + core flash from
// the descriptor's normalized age. Modeled on subsystem_pin_pass (quad) with
// dust_pass additive/depth state.
class ShockwavePass {
public:
    ShockwavePass() = default;
    ~ShockwavePass();

    ShockwavePass(const ShockwavePass&) = delete;
    ShockwavePass& operator=(const ShockwavePass&) = delete;

    void render(const scenegraph::Camera& cam,
                const std::vector<ShockwaveDescriptor>& shockwaves,
                Pipeline& pipeline);

private:
    void initialize_gl();

    bool initialized_ = false;
    unsigned int vao_ = 0;
    unsigned int vbo_ = 0;
};

}  // namespace renderer
