// native/src/renderer/include/renderer/shield_pass.h
#pragma once

#include <functional>
#include <memory>
#include <unordered_map>

#include <assets/mesh.h>
#include <assets/texture.h>
#include <scenegraph/instance.h>

#include "renderer/shield_state.h"

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }
namespace renderer { class Pipeline; }

namespace renderer {

using ModelLookup =
    std::function<const assets::Model*(scenegraph::ModelHandle)>;

/// Per-frame additive shield-flash pass. Owns the per-instance ShieldRegistry
/// and a shared ellipsoid sphere mesh.
///
/// The splash it draws is procedural — see shield_splash_shape() in
/// renderer/shield_state.h. It used to sample four shieldhit0N TGAs through a
/// tangent-plane projection; those are gone, along with the three distortions
/// that needing a 2D map forced.
class ShieldPass {
public:
    ShieldPass();
    ~ShieldPass();
    ShieldPass(const ShieldPass&) = delete;
    ShieldPass& operator=(const ShieldPass&) = delete;

    void register_ship(scenegraph::InstanceId id,
                       ShieldMode mode,
                       float decay_seconds,
                       const glm::vec4& default_color,
                       const glm::vec3& aabb_center,
                       const glm::vec3& aabb_half_extents);

    void unregister_ship(scenegraph::InstanceId id);

    /// Push a hit. Color (0,0,0,0) substitutes the ship's default color.
    /// `radius_gu` is the weapon's DamageRadiusFactor, which sizes the
    /// procedural ripple; 0 clamps up to kShieldSplashReachMin.
    void shield_hit(scenegraph::InstanceId id,
                    const glm::vec3& point_body,
                    const glm::vec4& rgba,
                    float intensity,
                    double now_seconds,
                    float radius_gu = 0.0f);

    /// Draw all ships with active hits. Caller owns blend/depth state.
    /// `now_seconds` advances the decay clock. `model_lookup` is called per
    /// skin-mode instance to resolve the source NIF for skin-mesh build;
    /// may be empty for ellipsoid-only renders.
    void submit(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                double now_seconds,
                const ModelLookup& model_lookup = {});

private:
    ShieldRegistry registry_;
    std::unique_ptr<assets::Mesh> sphere_;        // shared ellipsoid mesh

    // Per-ModelHandle skin-shield mesh cache. Built on first skin-mode
    // draw for that handle; all instances of the same ship share the GPU
    // buffer.
    std::unordered_map<scenegraph::ModelHandle, std::unique_ptr<assets::Mesh>>
        skin_cache_;

    assets::Mesh* ensure_sphere();
    assets::Mesh* ensure_skin_mesh(scenegraph::ModelHandle handle,
                                    const assets::Model& model,
                                    float inflate_distance);
};

}  // namespace renderer
