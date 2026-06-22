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
    // Unit world-space direction pointing radially OUTWARD from the
    // nearest sun (sun → camera). Zero when no sun is in range. Drives the
    // animated solar-wind drift; the drift rate is sun_tint (closeness).
    glm::vec3 sun_dir      = glm::vec3(0.0f);
    float     sun_tint     = 0.0f;           // [0,1] sun closeness: orange-mix factor AND drift rate
};

/// Evaluate density/tint/drift response for the camera against the active
/// suns and planets. Pure function — no GL, fully unit-testable.
///
/// `planets` are packed as vec4(x, y, z, radius). Density uses the
/// strongest body: a sun in range wins over any planet (spec §2-3 "sun
/// precedence"). Tint and the outward drift direction use the nearest
/// (greatest-closeness) sun.
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
    // Buffer is overseeded to the density ceiling; the per-frame draw
    // count scales between kParticleCount and this.
    static constexpr int   kSeededCount          = kParticleCount * kMaxDensityMult;
    static constexpr float kPlanetPeakMult       = 5.0f;   // density near planets
    static constexpr float kSunPeakMult          = 10.0f;  // density near suns
    // Closeness ramps from 1 at a body's surface to 0 at this multiple of
    // its radius. Used by density, tint, AND the solar-wind drift.
    static constexpr float kInfluenceRadii       = 5.0f;
    // Solar-wind drift: dust streams radially away from the nearest sun.
    // Speed (GU/s) at the surface (closeness 1); scales down by closeness
    // so it ramps in over the radius-relative influence zone. Folded into
    // the toroidal wrap, so the field recycles seamlessly at any speed.
    static constexpr float kSunDriftSpeed        = 25.0f;  // GU/s at closeness 1
    // Warp fly-past drift: particles stream PAST the (near-stationary) camera
    // along the travel axis during warp, recycling via the toroidal wrap.
    // Speed (GU/s) scaled by streak intensity. Tunable.
    static constexpr float kWarpDriftSpeed       = 75.0f; // GU/s at streak 1
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
                Pipeline& pipeline,
                const std::vector<SunDescriptor>& suns,
                const std::vector<glm::vec4>& planets,
                float warp_streak = 0.0f,
                glm::vec3 warp_travel = glm::vec3(0.0f, 1.0f, 0.0f));

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
    int        particle_count_ = kSeededCount;
    // Accumulated solar-wind drift distance (GU), wrapped to [0, 2*kVolumeRadius)
    // so it stays precise over long sessions. Multiplied by the outward
    // direction and folded into the toroidal wrap each frame.
    float      sun_drift_phase_ = 0.0f;
    // Accumulated warp fly-past drift distance (GU), wrapped to
    // [0, 2*kVolumeRadius). Mirrors sun_drift_phase_; reset to 0 when not
    // warping so off-parity (streak 0) leaves zero residual drift.
    float      warp_drift_phase_ = 0.0f;

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
