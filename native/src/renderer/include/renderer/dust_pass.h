// native/src/renderer/include/renderer/dust_pass.h
#pragma once

#include <glm/glm.hpp>

#include <cstdint>
#include <memory>
#include <vector>

namespace assets { class Texture; }
namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// Generate `count` particle records uniformly distributed inside a
/// sphere of radius `radius`, with deterministic per-particle jitter in
/// the w channel. Pure CPU; testable without a GL context.
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
    static constexpr int   kParticleCount        = 2048;
    static constexpr float kVolumeRadius         = 40.0f;       // BC units
    static constexpr float kSmearSeconds         = 1.0f / 30.0f;
    static constexpr float kSizeMin              = 0.8f;        // BC units
    static constexpr float kSizeMax              = 1.4f;
    static constexpr float kBrightnessMin        = 0.5f;
    static constexpr float kBrightnessMax        = 1.0f;
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
