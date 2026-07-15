// native/src/renderer/include/renderer/torpedo_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/texture.h>

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

class TorpedoPass {
public:
    TorpedoPass();
    ~TorpedoPass();
    TorpedoPass(const TorpedoPass&)            = delete;
    TorpedoPass& operator=(const TorpedoPass&) = delete;

    /// Render the TORPEDO family (TorpedoDescriptor::is_disruptor == false)
    /// via BC's audited billboard-root construction: a camera-facing quad
    /// basis that spins about the view axis, carrying two additive glow
    /// quads, a flare star, and a core sprite -- see torpedo_pass.cc's
    /// file-top comment and renderer/torpedo_anim.h for the math. Disruptor
    /// entries are skipped (Task 7 renders those separately). Caller pushes
    /// the descriptor list via host's set_torpedoes binding before each
    /// frame.
    void render(const std::vector<TorpedoDescriptor>& torpedoes,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    // Unit-quad VAO/VBO — single shared mesh, repeated per torpedo per
    // layer with per-draw uniforms (position / size / color / texture).
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    std::unordered_map<std::string, std::unique_ptr<assets::Texture>> texture_cache_;

    void             ensure_quad_mesh();
    assets::Texture* ensure_texture(const std::string& path);
};

}  // namespace renderer
