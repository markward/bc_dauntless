// native/src/renderer/include/renderer/phaser_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/texture.h>

#include <memory>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

class PhaserPass {
public:
    PhaserPass();
    ~PhaserPass();
    PhaserPass(const PhaserPass&)            = delete;
    PhaserPass& operator=(const PhaserPass&) = delete;

    /// Render every active beam as an additive camera-aligned quad.
    void render(const std::vector<PhaserBeamDescriptor>& beams,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    // Per-beam VAO/VBO — rebuilt each frame from the descriptor list.
    unsigned int beam_vao_ = 0;
    unsigned int beam_vbo_ = 0;
    std::unique_ptr<assets::Texture> texture_;
    bool texture_loaded_ = false;

    void ensure_mesh(const std::vector<PhaserBeamDescriptor>& beams);
    void ensure_texture();
};

}  // namespace renderer
