// native/src/renderer/include/renderer/torpedo_pass.h
#pragma once

#include <renderer/frame.h>
#include <renderer/torpedo_sprites.h>
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

    /// Render BOTH projectile families from one descriptor list: TORPEDO
    /// entries (TorpedoDescriptor::is_disruptor == false) via BC's audited
    /// billboard-root construction (camera-facing quad basis spinning about
    /// the view axis, carrying two additive glow quads, a flare star, and a
    /// core sprite), and DISRUPTOR entries (is_disruptor == true) via a
    /// procedural tapered-tube mesh re-oriented onto the velocity vector
    /// every frame -- see torpedo_pass.cc's file-top comment and
    /// renderer/torpedo_anim.h for the math of both. Caller pushes the
    /// descriptor list via host's set_torpedoes binding before each frame.
    void render(const std::vector<TorpedoDescriptor>& torpedoes,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    // Unit-quad VAO/VBO -- one shared mesh, instanced once per torpedo
    // layer: instance_vbo_ carries every quad of the frame (TorpedoSprite,
    // attributes 1-4), uploaded once and drawn one texture batch at a time.
    unsigned int quad_vao_     = 0;
    unsigned int quad_vbo_     = 0;
    unsigned int instance_vbo_ = 0;
    std::vector<TorpedoSpriteBatch> batches_;   // reused frame to frame
    std::vector<TorpedoSprite>      staging_;   // batches_ back to back
    std::unordered_map<std::string, std::unique_ptr<assets::Texture>> texture_cache_;

    // Unit tapered-tube VAO/VBO/EBO (renderer::build_bolt_mesh) — single
    // shared mesh, lazily uploaded on first disruptor draw, reused for both
    // the shell and core concentric sub-draws of every bolt.
    unsigned int bolt_vao_         = 0;
    unsigned int bolt_vbo_         = 0;
    unsigned int bolt_ebo_         = 0;
    int          bolt_index_count_ = 0;

    void             ensure_quad_mesh();
    void             ensure_bolt_mesh();
    assets::Texture* ensure_texture(const std::string& path);
};

}  // namespace renderer
