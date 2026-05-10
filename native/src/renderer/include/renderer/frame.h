// native/src/renderer/include/renderer/frame.h
#pragma once

#include <cstdint>
#include <functional>
#include <string>

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

enum class BackdropKind { Star, Backdrop };

struct Backdrop {
    /// Source descriptor; matched against the renderer's per-texture
    /// cache. The renderer uploads on first sight and reuses thereafter.
    std::string texture_path;
    BackdropKind kind = BackdropKind::Star;
    float h_tile = 1.0f;
    float v_tile = 1.0f;
    float h_span = 1.0f;
    float v_span = 1.0f;
    glm::mat3 world_rotation = glm::mat3(1.0f);
    int target_poly_count = 256;
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

private:
    /// Lazily-allocated 1x1 white texture used as a fallback when a material
    /// has no Base-stage texture. Keeps the sampler bound to a valid object
    /// so the shader's texture(...) sample returns white instead of black
    /// (the GL "zero texture") and the lighting math actually shows up.
    std::uint32_t white_texture_ = 0;
    std::uint32_t ensure_white_texture();
};

}  // namespace renderer
