// native/src/renderer/include/renderer/warp_in_flash_pass.h
#pragma once

#include <renderer/frame.h>
#include <renderer/warp_in_flash_shape.h>

#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

// Draws warp-in flashes (warp-in spec 6.3): per flash a camera-facing
// billboard (core + ring) and a ribbon along the flash's forward axis
// (streak). Procedural (shaders/warp_in_flash.*), additive (ONE, ONE),
// depth-tested without depth writes, so a nearer hull or planet hides it.
// Restores the GL state it changes.
class WarpInFlashPass {
public:
    WarpInFlashPass() = default;
    ~WarpInFlashPass();

    WarpInFlashPass(const WarpInFlashPass&) = delete;
    WarpInFlashPass& operator=(const WarpInFlashPass&) = delete;

    void render(const scenegraph::Camera& cam,
                const std::vector<WarpInFlashDescriptor>& flashes,
                const WarpInFlashParams& params,
                Pipeline& pipeline);

private:
    void initialize_gl();

    bool initialized_ = false;
    unsigned int vao_ = 0;
    unsigned int vbo_ = 0;
};

}  // namespace renderer
