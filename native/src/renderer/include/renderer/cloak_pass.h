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
struct Lighting;

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
/// mesh: the fragment samples that copy at a per-channel screen offset driven
/// by the hull normal (bending + splitting the background into spectral
/// fringes) AND composites the hull's own base/glow textures at a glow-keyed
/// opacity (dark hull ≈ `opacity_floor` ~10%, glowing surfaces up to
/// `opacity_ceiling` ~50%), eased in across the transition so opacity blends
/// smoothly rather than popping. An animated screen-space wobble plus a vertex
/// displacement give the cloak a live shimmer. All dials are live-tunable.
class CloakRefractionPass {
public:
    using ModelLookup =
        std::function<const assets::Model*(scenegraph::ModelHandle)>;

    CloakRefractionPass()                                      = default;
    ~CloakRefractionPass();
    CloakRefractionPass(const CloakRefractionPass&)            = delete;
    CloakRefractionPass& operator=(const CloakRefractionPass&) = delete;

    /// Draw every descriptor into the currently-bound HDR target. No-op on an
    /// empty list. `time` is the wall clock in seconds (drives the shimmer).
    /// `lighting` + `ambient_scale` match the opaque pass so the cloaked hull
    /// shades identically (no lit/unlit brightness pop at the transition).
    /// Restores canonical opaque-pass GL state on exit.
    void render(const std::vector<CloakShipDescriptor>& ships,
                const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                float time,
                const Lighting& lighting,
                float ambient_scale);

    void set_strength(float s)          { strength_ = s; }
    void set_dispersion(float d)        { dispersion_ = d; }
    void set_tint(const glm::vec3& t)   { tint_ = t; }
    void set_opacity_floor(float f)     { opacity_floor_ = f; }
    void set_opacity_ceiling(float c)   { opacity_ceiling_ = c; }
    void set_shimmer_amp(float a)       { shimmer_amp_ = a; }
    void set_shimmer_speed(float s)     { shimmer_speed_ = s; }
    void set_vertex_wobble(float w)     { vertex_wobble_ = w; }
    void set_normal_bias(float b)       { normal_bias_ = b; }
    float strength() const              { return strength_; }
    float dispersion() const            { return dispersion_; }

private:
    void ensure_scene_copy(int w, int h);
    void ensure_fallbacks();

    unsigned int scene_copy_tex_   = 0;
    int copy_w_ = 0, copy_h_ = 0;
    unsigned int white_fallback_   = 0;  // 1×1 white — base-colour stand-in
    unsigned int black_fallback_   = 0;  // 1×1 black — glow stand-in (no glow)

    // Live-tunable dials (Mark calibrates these by eye — biased strong first).
    float     strength_        = 0.04f;   // max screen-UV refraction offset
    float     dispersion_      = 0.50f;   // prism split
    glm::vec3 tint_            = glm::vec3(0.20f, 0.85f, 0.55f);  // cloak green
    float     opacity_floor_   = 0.10f;   // dark-hull alpha when fully cloaked
    float     opacity_ceiling_ = 0.50f;   // glowing-surface alpha ceiling
    float     shimmer_amp_     = 0.010f;  // animated screen-space wobble (UV)
    float     shimmer_speed_   = 6.0f;    // shimmer angular frequency (rad/s)
    float     vertex_wobble_   = 0.05f;   // animated vertex displacement (GU)
    float     normal_bias_     = 1.0f;    // 0 = flat, 1 = fully grazing-weighted
};

}  // namespace renderer
