// native/src/renderer/include/renderer/system_nebula_pass.h
#pragma once

#include "renderer/nebula_atmosphere.h"

#include <glm/glm.hpp>

#include <cstdint>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;
struct NebulaVolume;
struct Lighting;

/// System-scale nebula: the whole star system as a star-centred atmosphere
/// (docs/superpowers/specs/2026-09-29-system-nebula-render-design.md).
/// DEVELOPER-ONLY for now -- host frame() gates it on --developer AND the
/// volumetric-nebula setting; without both, NebulaVolumetricPass / NebulaPass
/// render exactly as before.
///
/// Started as a copy of NebulaVolumetricPass and keeps its performance
/// machinery unchanged: quarter-resolution ping-pong target, dither step
/// offset, conservative temporal reprojection (reset on large eye deltas and
/// origin discontinuities) and the depth-aware upsample composited
/// premultiplied OVER the HDR target.
///
/// What it marches (system_nebula.frag): a near field of ~64 geometric steps
/// out to kNearRangeGu through the radial density texture (density, tau_star
/// by radius from the star) modulated by fbm "lanes", then the far field
/// from a precomputed table keyed by (radius, cos to the outward radial).
/// The table's transmittance is uploaded as OPTICAL DEPTH (tau_from_table):
/// system-scale transmittances reach ~1e-16, so the shader recovers a finite
/// segment as exp(-(tau_a - tau_b)) and never divides by a stored T.
///
/// `volumes` (local MetaNebula clumps) are density bumps in the same near
/// field: each contributes its own sphere (the volume's first, up to 8),
/// colour, fbm dials, seed and extinction (1/visibility per GU). They march
/// even with no bound profile -- a clump-only system skips the far-field
/// table lookups entirely and marches the near field for the clumps alone.

/// Live-tunable look dials (docs/superpowers/specs/2026-09-29-system-nebula-render-design.md
/// Task 7). Replaces the pass's former file-top constants (kNearRangeGu,
/// kLaneSizeGu, kLaneContrast); `veil_scale` is reserved for a future dial
/// and is not yet read anywhere. `set_dials` is the single entry point a
/// developer keybinding calls each press -- see engine/dev_nebula_dials.py.
struct SystemNebulaDials {
    float veil_scale    = 1.0f;
    float lane_size     = 15000.0f;
    float lane_contrast = 0.7f;
    float g             = 0.6f;
    float floor         = 0.03f;
    float near_range    = 30000.0f;
};

class SystemNebulaPass {
public:
    using Dials = SystemNebulaDials;

    SystemNebulaPass();
    ~SystemNebulaPass();
    SystemNebulaPass(const SystemNebulaPass&) = delete;
    SystemNebulaPass& operator=(const SystemNebulaPass&) = delete;

    /// Build the radial texels and far-field table on the CPU and upload
    /// them: radial -> GL_RG32F kRadialTexels x 1; table -> two GL_RGB32F
    /// kTableR x kTableMu (optical depth, inscatter). Needs a current context.
    void set_profile(const atmosphere::RadialProfile& profile,
                     const atmosphere::LookParams& look);
    /// Delete the profile textures; the haze stops drawing.
    void clear_profile();
    bool has_profile() const { return has_profile_; }

    /// Set the near-field/table look dials. A change to `g` or `floor` with
    /// a profile already uploaded rebuilds the far-field table (re-runs
    /// set_profile with the updated LookParams, ~1-2s); `lane_size`,
    /// `lane_contrast` and `near_range` are read directly by the shader
    /// every frame and never trigger a rebuild.
    void set_dials(const Dials& dials);
    const Dials& dials() const { return dials_; }

    /// Incremented once per set_profile() call (including the rebuild
    /// set_dials triggers) -- lets a test observe a rebuild without reading
    /// GPU texture contents back.
    int profile_rebuild_count() const { return profile_rebuild_count_; }

    /// The star centre in RENDER space (relative to the floating origin).
    void set_star(const glm::vec3& render_pos) { star_ = render_pos; }

    /// Same contract as NebulaVolumetricPass::render. Early-outs (zero GL
    /// work) when there is neither a profile nor any volume.
    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<NebulaVolume>& volumes,
                const Lighting& lighting,
                std::uint32_t hdr_color_tex,
                std::uint32_t hdr_depth_tex,
                const glm::mat4& inv_view_proj,
                const glm::vec3& eye,
                float time,
                const glm::dvec3& render_origin = glm::dvec3(0.0));

    /// Drop the temporal history (and the origin it was in): the next frame
    /// marches fresh instead of reprojecting across an origin discontinuity.
    void reset_history() {
        have_history_ = false;
        prev_origin_ = glm::dvec3(0.0);
    }
    bool has_history() const { return have_history_; }

private:
    void initialize_gl();
    /// (Re)allocate the low-res ping-pong targets to (w, h). No-op if already
    /// that size. Invalidates temporal history on a resize.
    void ensure_half_targets(int w, int h);
    void destroy_half_targets();
    void destroy_profile_textures();

    bool         initialized_ = false;
    unsigned int vao_ = 0;   // empty VAO; fullscreen triangle uses gl_VertexID

    // ── Low-res ping-pong scratch targets (RGBA16F) ────────────────────────
    int          half_w_ = 0;
    int          half_h_ = 0;
    unsigned int half_fbo_[2] = {0, 0};
    unsigned int half_tex_[2] = {0, 0};
    int          cur_ = 0;            // index written this frame

    // ── Temporal reprojection state ────────────────────────────────────────
    bool         have_history_ = false;
    glm::mat4    prev_view_proj_ = glm::mat4(1.0f);
    glm::vec3    prev_eye_ = glm::vec3(0.0f);
    glm::dvec3   prev_origin_ = glm::dvec3(0.0);

    // ── Profile ────────────────────────────────────────────────────────────
    unsigned int radial_tex_ = 0;     // RG32F: density, tau_star by u = sqrt(r/far)
    unsigned int table_tau_ = 0;      // RGB32F: far-field optical depth
    unsigned int table_S_ = 0;        // RGB32F: far-field inscatter
    bool         has_profile_ = false;
    atmosphere::RadialProfile profile_;
    atmosphere::LookParams    look_;
    glm::vec3    star_{0.0f};
    Dials        dials_;
    int          profile_rebuild_count_ = 0;
};

}  // namespace renderer
