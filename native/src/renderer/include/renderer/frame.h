// native/src/renderer/include/renderer/frame.h
#pragma once

#include <cstdint>
#include <functional>

#include <glm/glm.hpp>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }
namespace renderer { class Pipeline; }

namespace renderer {

struct Lighting {
    static constexpr int MaxDirectionals = 4;
    /// Combined color × dimmer, applied as a uniform additive term.
    glm::vec3 ambient = glm::vec3(0.1f);
    /// 0..MaxDirectionals; values past `directional_count` are ignored.
    int directional_count = 1;
    /// Direction TOWARD the light source, world space, normalized.
    glm::vec3 directional_dir_ws[MaxDirectionals] = {
        glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f))
    };
    /// Color × dimmer per directional.
    glm::vec3 directional_color[MaxDirectionals] = { glm::vec3(1.0f) };
};

class FrameSubmitter {
public:
    using ModelLookup = std::function<const assets::Model*(unsigned long long)>;

    FrameSubmitter() = default;
    ~FrameSubmitter();
    FrameSubmitter(const FrameSubmitter&) = delete;
    FrameSubmitter& operator=(const FrameSubmitter&) = delete;

    /// Iterate visible instances in `world` and draw each Mesh with the
    /// opaque shader. Caller is responsible for clearing color + depth and
    /// for swapping buffers afterward.
    void submit_opaque(const scenegraph::World& world,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline,
                       const ModelLookup& lookup,
                       const Lighting& lighting);

    /// Render the skybox model with depth-write off, depth-test LEQUAL,
    /// projection translation removed. Caller-provided `skybox_model` may be
    /// null — in which case this function is a no-op. Must run before the
    /// opaque pass.
    void submit_skybox(const assets::Model* skybox_model,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline);

private:
    /// Lazily-allocated 1x1 white texture used as a fallback when a material
    /// has no Base-stage texture. Keeps the sampler bound to a valid object
    /// so the shader's texture(...) sample returns white instead of black
    /// (the GL "zero texture") and the lighting math actually shows up.
    std::uint32_t white_texture_ = 0;
    std::uint32_t ensure_white_texture();
};

}  // namespace renderer
