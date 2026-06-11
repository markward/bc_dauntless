// native/src/renderer/include/renderer/particle_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/texture.h>

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace scenegraph { struct Camera; class World; }

namespace renderer {

class Pipeline;

/// Stateless analytic billboard particle renderer (smoke, A1). Each
/// ParticleEmitterDescriptor is expanded into up to particle_max_count()
/// camera-facing alpha-blended quads whose state is computed analytically
/// from effect_age + per-particle hash + keyframe curves. Reuses the
/// hit_vfx billboard shader.
class ParticlePass {
public:
    ParticlePass();
    ~ParticlePass();
    ParticlePass(const ParticlePass&)            = delete;
    ParticlePass& operator=(const ParticlePass&) = delete;

    void render(const std::vector<ParticleEmitterDescriptor>& emitters,
                const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    std::map<std::string, std::unique_ptr<assets::Texture>> textures_;

    void ensure_quad_mesh();
    assets::Texture* texture_for(const std::string& path);  // lazy cache, nullptr on failure
};

}  // namespace renderer
