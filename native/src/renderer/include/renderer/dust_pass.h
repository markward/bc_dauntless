// native/src/renderer/include/renderer/dust_pass.h
#pragma once

#include <glm/glm.hpp>

#include <renderer/frame.h>   // renderer::SunDescriptor

#include <cstdint>
#include <memory>
#include <vector>

namespace assets { class Texture; }
namespace scenegraph { struct Camera; }

namespace renderer {

/// Result of evaluating dust proximity to nearby bodies for one frame.
/// Pure data; produced by compute_dust_influence (no GL).
struct DustInfluence {
    float     density_mult = 1.0f;           // [1, kMaxDensityMult]
    glm::vec3 sun_pos      = glm::vec3(0.0f);// nearest sun centre (world)
    float     sun_radius   = 0.0f;           // nearest sun radius
    float     sun_push     = 0.0f;           // GU; 0 when no sun in range
    float     sun_tint     = 0.0f;           // [0,1] orange-mix factor
};

/// Evaluate density/push/tint response for the camera against the active
/// suns and planets. Pure function — no GL, fully unit-testable.
///
/// `planets` are packed as vec4(x, y, z, radius). Density uses the
/// strongest body: a sun in range wins over any planet (spec §2-3 "sun
/// precedence"). Push and tint use the nearest (greatest-closeness) sun.
DustInfluence compute_dust_influence(
    const glm::vec3& camera_pos,
    const std::vector<SunDescriptor>& suns,
    const std::vector<glm::vec4>& planets);

class Pipeline;

/// Generate `count` particle records uniformly distributed inside the
/// cube [-radius, radius]^3, with deterministic per-particle jitter in
/// the w channel. Pure CPU; testable without a GL context.
///
/// Cube — not sphere — because the vertex shader's toroidal wrap
/// operates on each axis independently in a 2*radius cube. Seeding in a
/// sphere produces visible density variations as the camera moves more
/// than a fraction of `radius`. The fragment shader clips visible
/// particles to the inscribed sphere.
///
/// Output layout: vec4(x, y, z, jitter) where jitter in [0, 1).
std::vector<glm::vec4> generate_dust_particles(std::uint32_t seed,
                                               int count,
                                               float radius);

/// C++ mirror of the GLSL toroidal-wrap formula in dust.vert. Kept here
/// as a regression guard; the shader is the source of truth for
/// rendering. If the two ever drift, visual tuning will catch it before
/// this test does.
glm::vec3 wrap_local_for_test(glm::vec3 particle_pos,
                              glm::vec3 camera_pos,
                              float radius);

class DustPass {
public:
    // Tunable constants. Documented in the spec as the dials for visual
    // tuning. Changing these does not break correctness; it only changes
    // how the effect looks.
    // Sphere is ~52% of the cube the particles are seeded in; the rest
    // are discarded by the fragment shader. 512 seeded → ~265 visible.
    static constexpr int   kParticleCount        = 512;
    static constexpr float kVolumeRadius         = 40.0f;       // BC units
    static constexpr float kSmearSeconds         = 1.0f / 30.0f;
    // Hard cap on streak length so high-velocity camera motion (warp
    // exits, fast chase) doesn't stretch dust into screen-spanning lines.
    static constexpr float kMaxSmearLength       = 1.5f;        // BC units
    static constexpr float kSizeMin              = 0.02f;       // BC units
    static constexpr float kSizeMax              = 0.035f;
    // Brightness boosted ~1.6x (spec §1, "moderate").
    static constexpr float kBrightnessMin        = 0.8f;
    static constexpr float kBrightnessMax        = 1.6f;

    // ── Proximity response (spec §2-5) ───────────────────────────────
    // Density ceiling near suns AND the overseed factor for the instance
    // buffer. Base visible target stays kParticleCount; the buffer is
    // seeded with kParticleCount * kMaxDensityMult particles and the
    // per-frame draw count scales between the two.
    static constexpr int   kMaxDensityMult       = 10;
    static constexpr float kPlanetPeakMult       = 5.0f;   // density near planets
    static constexpr float kSunPeakMult          = 10.0f;  // density near suns
    // Closeness ramps from 1 at a body's surface to 0 at this multiple of
    // its radius.
    static constexpr float kInfluenceRadii       = 5.0f;
    // Sun push: absolute 100 GU from the sun SURFACE, max displacement 8 GU
    // (inside the 40 GU volume so pushed specks stay in-field).
    static constexpr float kSunPushRange         = 100.0f; // GU, absolute
    static constexpr float kSunPushMax           = 8.0f;   // GU
    static constexpr float kVelocityClampSeconds = 0.1f;        // dt guard
    static constexpr std::uint32_t kSeed         = 0xD057C0DEu;

    DustPass();
    ~DustPass();
    DustPass(const DustPass&) = delete;
    DustPass& operator=(const DustPass&) = delete;

    /// Render the dust pass. Caller is responsible for the scene depth
    /// buffer being populated (so ships/planets occlude dust correctly).
    /// `dt_seconds` is the host-loop frame delta used for velocity.
    void render(const scenegraph::Camera& camera,
                float dt_seconds,
                Pipeline& pipeline);

    void set_enabled(bool enabled) { enabled_ = enabled; }
    bool enabled() const { return enabled_; }

    /// Reseed the per-instance buffer with `count` particles (clamped to
    /// [0, 50000]). Used by the deferred dynamic-density work; safe to
    /// call from the same thread as render().
    void set_density(int count);

private:
    bool       enabled_      = true;
    bool       initialized_  = false;   // GL objects created lazily on first render
    glm::vec3  prev_eye_     = glm::vec3(0.0f);
    bool       have_prev_    = false;
    int        particle_count_ = kParticleCount;

    // GL objects, populated in initialize_gl(). 0 means "not yet created".
    unsigned int vao_              = 0;
    unsigned int quad_vbo_         = 0;
    unsigned int quad_ebo_         = 0;
    unsigned int instance_vbo_     = 0;

    std::unique_ptr<assets::Texture> texture_;

    void initialize_gl();
    void rebuild_instance_buffer(std::uint32_t seed, int count);
    bool ensure_texture();
};

}  // namespace renderer
