// native/src/renderer/include/renderer/cloak_pass.h
#pragma once

#include <functional>
#include <vector>

#include <glm/glm.hpp>

#include <scenegraph/instance.h>  // InstanceId, ModelHandle

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }

namespace renderer {

class Pipeline;

/// One cloaking ship to draw as a refractive shell this frame. `instance` is
/// the real scenegraph instance (geometry + world transform are re-drawn);
/// `frac` is the cloak transition progress in [0, 1] (0 = visible, 1 = fully
/// cloaked) and drives the refraction / dispersion strength.
struct CloakShipDescriptor {
    scenegraph::InstanceId instance{};
    float                  frac = 0.0f;
};

/// Screen-space refraction with chromatic dispersion for cloaking ships.
///
/// For each cloaking ship it copies the live HDR colour into a scratch texture
/// (so reading + writing the bound HDR target is never a same-FBO feedback
/// loop — the nebula god-ray pass uses the same trick), then re-draws the hull
/// mesh sampling that copy at a per-channel screen offset along the hull
/// normal. The result is the background bending and splitting into spectral
/// fringes through the cloak field. Dials are live-tunable.
class CloakRefractionPass {
public:
    using ModelLookup =
        std::function<const assets::Model*(scenegraph::ModelHandle)>;

    CloakRefractionPass()                                      = default;
    ~CloakRefractionPass();
    CloakRefractionPass(const CloakRefractionPass&)            = delete;
    CloakRefractionPass& operator=(const CloakRefractionPass&) = delete;

    /// Draw every descriptor into the currently-bound HDR target. No-op on an
    /// empty list. Restores canonical opaque-pass GL state on exit.
    void render(const std::vector<CloakShipDescriptor>& ships,
                const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup);

    void set_strength(float s)          { strength_ = s; }
    void set_dispersion(float d)        { dispersion_ = d; }
    void set_tint(const glm::vec3& t)   { tint_ = t; }
    float strength() const              { return strength_; }
    float dispersion() const            { return dispersion_; }

private:
    void ensure_scene_copy(int w, int h);

    unsigned int scene_copy_tex_ = 0;
    int copy_w_ = 0, copy_h_ = 0;

    // Live-tunable dials (Mark calibrates these by eye).
    float     strength_   = 0.04f;                       // max screen-UV offset
    float     dispersion_ = 0.50f;                       // prism split
    glm::vec3 tint_       = glm::vec3(0.20f, 0.85f, 0.55f);  // cloak green
};

}  // namespace renderer
