// native/src/renderer/include/renderer/frame.h
#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include <glm/glm.hpp>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; enum class Pass : std::uint8_t; }
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

struct SunDescriptor {
    glm::vec3   position;                  // world-space center
    float       radius        = 1.0f;      // body sphere radius (BC units)
    std::string base_texture_path;
    float       corona_radius = 0.0f;      // 0 = no corona; draw when > radius
    std::string flare_texture_path;        // empty = skip the SunEffect overlay
};

struct LensFlareElement {
    int         wedges       = 8;
    std::string texture_path;
    float       position     = 0.0f;   // 0=at source, 1=screen center, 2=opposite
    float       size         = 0.1f;   // fraction of viewport height
    float       freq         = 0.0f;   // Hz wobble
    float       amp          = 0.0f;   // wobble amplitude (size multiplier delta)
};

struct LensFlareDescriptor {
    glm::vec3                       source_world_pos;
    std::vector<LensFlareElement>   elements;
};

/// Torpedo render descriptor.  Populated from the SDK projectile script's
/// CreateTorpedoModel call (sdk/Build/scripts/Tactical/Projectiles/*.py).
/// Renderer composites three additive billboards (glow + flares + core) at
/// world_pos each frame.  Sizes are world-units half-sizes per layer.
struct TorpedoDescriptor {
    glm::vec3   world_pos;
    std::string core_texture;
    glm::vec4   core_color   = glm::vec4(1.0f);
    float       core_size_a  = 0.0f;
    float       core_size_b  = 0.0f;
    std::string glow_texture;
    glm::vec4   glow_color   = glm::vec4(1.0f);
    float       glow_size_a  = 0.0f;
    float       glow_size_b  = 0.0f;
    float       glow_size_c  = 0.0f;
    std::string flares_texture;
    glm::vec4   flares_color = glm::vec4(1.0f);
    int         num_flares   = 0;
    float       flares_size_a = 0.0f;
    float       flares_size_b = 0.0f;
    float       age           = 0.0f;
};

/// Hit-VFX render descriptor.  Engine ages each entry; renderer dispatches
/// per-tier constants (HULL / CRITICAL) based on `severity`.  `surface_normal`
/// is (0,0,0) when no mesh trace was available (sentinel = no normal).
struct HitVfxDescriptor {
    glm::vec3 world_pos;
    glm::vec3 surface_normal{0.0f};   // (0,0,0) sentinel = no normal
    float     age      = 0.0f;
    int       severity = 1;           // 1=HULL, 2=CRITICAL; SHIELD never reaches here
};

/// Phaser-beam render descriptor.  One entry per concentric beam layer
/// emitted by an actively-firing PhaserBank: rendered as an additive
/// N-sided prism extruded from emitter_world to target_world with
/// endpoint taper.
struct PhaserBeamDescriptor {
    glm::vec3 emitter_world;
    glm::vec3 target_world;
    glm::vec4 color;     // RGBA additive tint
    float     width;     // mid-beam half-width (= SDK MainRadius)
    float     u_tiles;   // texture repeats along beam length
    // BC-faithful geometry (SDK names retained):
    int       num_sides;        // SetNumSides — prism side count
    float     taper_radius;     // SetTaperRadius — half-width at endpoints
    float     taper_ratio;      // SetTaperRatio — fraction of length used for taper
    float     taper_min_length; // SetTaperMinLength
    float     taper_max_length; // SetTaperMaxLength
    float     perimeter_tile;   // SetPerimeterTile — V-axis texture repeats around prism
    float     texture_speed;    // SetTextureSpeed — U-axis scroll wu/sec
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
                       const Lighting& lighting,
                       float decal_time = 0.0f);

    /// Like submit_opaque but only iterates instances tagged with `pass`.
    /// Used by the space pass to exclude bridge-tagged geometry, which
    /// is drawn by BridgePass with its own camera and shaders.
    void submit_opaque_in_pass(const scenegraph::World& world,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline,
                               const ModelLookup& lookup,
                               const Lighting& lighting,
                               scenegraph::Pass pass,
                               float decal_time = 0.0f);

private:
    /// Lazily-allocated 1x1 white texture used as a fallback when a material
    /// has no Base-stage texture. Keeps the sampler bound to a valid object
    /// so the shader's texture(...) sample returns white instead of black
    /// (the GL "zero texture") and the lighting math actually shows up.
    std::uint32_t white_texture_ = 0;
    std::uint32_t ensure_white_texture();

    /// Lazily-allocated 1x1 black texture (RGBA 0,0,0,255) used as the
    /// fallback for the Glow stage when a mesh has no glow texture.
    /// Sampling it returns (0,0,0,1) so the glow term contributes nothing.
    std::uint32_t black_texture_ = 0;
    std::uint32_t ensure_black_texture();
};

}  // namespace renderer
