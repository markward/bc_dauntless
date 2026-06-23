// native/src/renderer/include/renderer/nebula_volumetric_pass.h
#pragma once

#include <glm/glm.hpp>

#include <cstdint>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;
struct NebulaVolume;
struct Lighting;

/// Modern-VFX volumetric raymarch of the nebula fbm density field.
///
/// PERFORMANCE PATH (Task 6). The raymarch is too heavy to run at full
/// resolution every frame, so the pass renders into a HALF-resolution scratch
/// RGBA16F target (½ × ½ the HDR target), then a depth-aware upsample
/// composites the result into the HDR target. Three levers make the march
/// affordable at 60 Hz:
///
///   1. Half-res scratch FBO — ¼ the fragments through the expensive march.
///   2. Dither step-offset — the first march `t` is jittered per-pixel
///      (cheap hash) so the low step count doesn't band at half res.
///   3. Temporal reprojection (conservative) — the half-res result is blended
///      with the previous half-res frame reprojected by `u_prev_view_proj`,
///      with a SMALL history weight, RESET on large camera deltas (warp) or
///      off-screen reprojection. Biased toward less history (ghosting is the
///      failure mode).
///
/// Then `nebula_upsample.frag` reads the half-res cloud + the full-res depth
/// and, for each full-res pixel, picks the half-res tap whose depth best
/// matches the full-res depth (nearest-depth bilateral) so hull silhouettes
/// stay crisp. It composites PREMULTIPLIED `vec4(lit, alpha)` into the HDR
/// target via `glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)` with depth
/// test/write OFF — never sampling the HDR colour (no feedback loop).
///
/// The depth-aware hull clamp (the headline obscuration feature) is preserved
/// end-to-end: the march samples the full-res HDR depth to stop at hulls, and
/// the upsample respects the same depth so the cloud stays behind hull edges.
///
/// GL state is restored to canonical defaults (blend off, depth test on, depth
/// mask on, cull on) and the originally-bound framebuffer + viewport are
/// re-bound before returning (the scene continues rendering into HDR after).
class NebulaVolumetricPass {
public:
    NebulaVolumetricPass();
    ~NebulaVolumetricPass();
    NebulaVolumetricPass(const NebulaVolumetricPass&) = delete;
    NebulaVolumetricPass& operator=(const NebulaVolumetricPass&) = delete;

    /// Composite the volumetric cloud into the currently-bound HDR target.
    /// Early-outs (zero GL work) on empty `volumes`.
    ///
    /// `hdr_color_tex` is accepted for signature symmetry / future use but is
    /// NOT sampled (blend compositing). `hdr_depth_tex` IS sampled to clamp
    /// the march to hulls. `inv_view_proj` = inverse(proj * view); `eye` is
    /// the camera world position; `time` drives the slow density drift.
    ///
    /// The currently-bound framebuffer and viewport are captured on entry and
    /// restored on exit, so the caller's HDR target keeps receiving draws.
    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<NebulaVolume>& volumes,
                const Lighting& lighting,
                std::uint32_t hdr_color_tex,
                std::uint32_t hdr_depth_tex,
                const glm::mat4& inv_view_proj,
                const glm::vec3& eye,
                float time);

private:
    void initialize_gl();
    /// (Re)allocate the half-res ping-pong targets to (w, h). No-op if already
    /// that size. Invalidates temporal history on a resize.
    void ensure_half_targets(int w, int h);
    void destroy_half_targets();

    bool         initialized_ = false;
    unsigned int vao_ = 0;   // empty VAO; fullscreen triangle uses gl_VertexID

    // ── Half-res ping-pong scratch targets (RGBA16F) ───────────────────────
    // half_fbo_[cur_] receives the current frame's march; half_tex_[1-cur_] is
    // the previous frame's cloud, sampled for temporal reprojection.
    int          half_w_ = 0;
    int          half_h_ = 0;
    unsigned int half_fbo_[2] = {0, 0};
    unsigned int half_tex_[2] = {0, 0};
    int          cur_ = 0;            // index written this frame

    // ── Temporal reprojection state ────────────────────────────────────────
    bool         have_history_ = false;   // false on first frame / after reset
    glm::mat4    prev_view_proj_ = glm::mat4(1.0f);
    glm::vec3    prev_eye_ = glm::vec3(0.0f);
};

}  // namespace renderer
