// native/src/renderer/include/renderer/system_nebula_pass.h
#pragma once

#include "renderer/nebula_atmosphere.h"
#include "renderer/nebula_godray_pass.h"   // GodrayFlash
#include "renderer/system_nebula_cache.h"

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
/// On in production (2026-10-16): host frame() gates it on the
/// volumetric-nebula setting alone; with it off, NebulaVolumetricPass /
/// NebulaPass render exactly as before.
///
/// Started as a copy of NebulaVolumetricPass and keeps its quarter-resolution
/// target, dither step offset and depth-aware upsample composited
/// premultiplied OVER the HDR target. Its temporal reprojection was REMOVED
/// (2026-10-19): it smeared the haze on every camera sweep, and without it
/// the haze showed no shimmer (Mark, live). Each frame is its own march.
///
/// What it marches (system_nebula.frag): a near field of ~64 geometric steps
/// out to dials().near_range through the radial density texture (density,
/// tau_star by radius from the star) modulated by fbm "lanes" (value noise
/// read from a baked hash lattice, renderer/nebula_noise.h), then the far field
/// from a precomputed table keyed by (radius, cos to the outward radial).
/// The table's transmittance is uploaded as OPTICAL DEPTH (tau_from_table):
/// system-scale transmittances reach ~1e-16, so the shader recovers a finite
/// segment as exp(-(tau_a - tau_b)) and never divides by a stored T.
///
/// `volumes` (local MetaNebula clumps, at most 8) are density bumps, each a
/// union of up to 4 of the volume's spheres (the union gameplay concealment
/// reads) with its own colour, fbm dials, seed and extinction (1/visibility
/// per GU). Each clump gets its own 16-step sub-march over its ray-sphere
/// interval -- not limited to the haze's geometric steps or the near range,
/// stopped at scene depth -- and is composited into the haze march at its
/// interval's midpoint, nearest first. Clumps march even with no bound
/// profile (or no star); a clump-only run skips the haze entirely.

/// Live-tunable look dials (docs/superpowers/specs/2026-09-29-system-nebula-render-design.md
/// Task 7). Replaces the pass's former file-top constants (kNearRangeGu,
/// kLaneSizeGu, kLaneContrast). The veil is NOT here: it is a Python-side
/// dial that re-solves k_sys and re-pushes the profile (the flare veil reads
/// the same value). `set_dials` is the single entry point a developer
/// keybinding calls each press -- see engine/dev_nebula_dials.py.
struct SystemNebulaDials {
    float lane_size     = 15000.0f;
    float lane_contrast = 0.7f;
    float g             = 0.6f;
    float floor         = 0.03f;
    float near_range    = 30000.0f;
};

/// Which nebula draws frame() makes this frame (host_bindings.cc).
struct NebulaDrawPlan {
    bool system = false;   // SystemNebulaPass
    bool legacy = false;   // NebulaVolumetricPass / faithful NebulaPass
    bool wake   = false;   // NebulaWakePass, over whichever branch drew
};

/// frame()'s nebula decision, pure so it is testable without a host.
NebulaDrawPlan plan_nebula_draws(bool volumetric_setting, bool has_profile,
                                 bool have_volumes, bool have_wake);

class SystemNebulaPass {
public:
    using Dials = SystemNebulaDials;

    SystemNebulaPass();
    ~SystemNebulaPass();
    SystemNebulaPass(const SystemNebulaPass&) = delete;
    SystemNebulaPass& operator=(const SystemNebulaPass&) = delete;

    /// Upload the radial texels and far-field table: radial -> GL_RG32F
    /// kRadialTexels x 1; table -> two GL_RGB32F kTableR x kTableMu (optical
    /// depth, inscatter). The CPU build comes from the session TableCache: a
    /// hit or finished prebuild() costs only the upload; a miss builds
    /// synchronously (seconds). Needs a current context.
    void set_profile(const atmosphere::RadialProfile& profile,
                     const atmosphere::LookParams& look);
    /// Delete the profile textures and forget the profile and the star; the
    /// haze stops drawing.
    void clear_profile();
    bool has_profile() const { return has_profile_; }

    /// Start building (profile, look)'s table on a worker thread so a later
    /// set_profile with the same inputs costs only the upload. No GL; a
    /// no-op when already built or building.
    void prebuild(const atmosphere::RadialProfile& profile,
                  const atmosphere::LookParams& look) { cache_.prebuild(profile, look); }
    /// True once (profile, look)'s table is built (never blocks).
    bool prebuilt(const atmosphere::RadialProfile& profile,
                  const atmosphere::LookParams& look) { return cache_.ready(profile, look); }

    /// Set the near-field/table look dials. A change to `g` or `floor` with
    /// a profile already uploaded rebuilds the far-field table (re-runs
    /// set_profile with the updated LookParams; measured ~7 s for Vesuvi
    /// (15 rows) on the Debug build, ~0.2 s for 3-row systems; cached per
    /// session and prebuilt during the warp tunnel); `lane_size`,
    /// `lane_contrast` and `near_range` are read directly by the shader
    /// every frame and never trigger a rebuild.
    void set_dials(const Dials& dials);
    const Dials& dials() const { return dials_; }

    /// Incremented once per set_profile() call (including the rebuild
    /// set_dials triggers) -- lets a test observe a rebuild without reading
    /// GPU texture contents back.
    int profile_rebuild_count() const { return profile_rebuild_count_; }

    /// The star centre in RENDER space (relative to the floating origin).
    /// The host pushes it every frame, or clear_star() when the viewed set
    /// has no sun: with no star the forward-scatter term is zero (clumps are
    /// lit by the emissive floor alone) and the star-CENTRED profile haze is
    /// not drawn at all -- there is nowhere to centre it.
    void set_star(const glm::vec3& render_pos) { star_ = render_pos; has_star_ = true; }
    void clear_star() { star_ = glm::vec3(0.0f); has_star_ = false; }
    bool has_star() const { return has_star_; }

    /// Active lightning flashes that light the cloud (both the haze
    /// near-march and every clump sub-march), up to kMaxFlashes; extras are
    /// dropped. `dir` is the render-space unit vector TOWARD the flash, the
    /// shader adds colour x intensity x HG(kFlashG) per sample. Empty (the
    /// default, and after clear_profile) renders exactly as with no flash
    /// feature at all. Pushed per frame by the host (set_system_nebula_flashes).
    static constexpr int kMaxFlashes = 4;
    void set_flashes(const std::vector<GodrayFlash>& flashes);
    int flash_count() const { return static_cast<int>(flashes_.size()); }

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

private:
    void initialize_gl();
    /// (Re)allocate the low-res target to (w, h). No-op if already that size.
    void ensure_half_targets(int w, int h);
    void destroy_half_targets();
    void destroy_profile_textures();

    bool         initialized_ = false;
    unsigned int vao_ = 0;   // empty VAO; fullscreen triangle uses gl_VertexID
    unsigned int lattice_tex_ = 0;   // R16F kLatticeN^3 hash lattice (nebula_noise.h)

    // ── Low-res scratch target (RGBA16F) ───────────────────────────────────
    int          half_w_ = 0;
    int          half_h_ = 0;
    unsigned int half_fbo_ = 0;
    unsigned int half_tex_ = 0;

    // ── Profile ────────────────────────────────────────────────────────────
    unsigned int radial_tex_ = 0;     // RG32F: density, tau_star by u = sqrt(r/far)
    unsigned int table_tau_ = 0;      // RGB32F: far-field optical depth
    unsigned int table_S_ = 0;        // RGB32F: far-field inscatter
    bool         has_profile_ = false;
    atmosphere::RadialProfile profile_;
    atmosphere::LookParams    look_;
    glm::vec3    star_{0.0f};
    bool         has_star_ = false;
    std::vector<GodrayFlash> flashes_;
    Dials        dials_;
    int          profile_rebuild_count_ = 0;
    atmosphere::TableCache cache_;   // built tables, per session (never evicted)
};

}  // namespace renderer
