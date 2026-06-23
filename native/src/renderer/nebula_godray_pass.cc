// native/src/renderer/nebula_godray_pass.cc
#include "renderer/nebula_godray_pass.h"
#include "renderer/pipeline.h"
#include "renderer/shader.h"
#include <scenegraph/camera.h>
#include <glad/glad.h>
#include <glm/glm.hpp>

namespace renderer {

namespace {
// Anchor projection: the flash light comes FROM `dir`, so the screen anchor is
// a far world point ALONG +dir (toward the light source). This distance just
// has to be well beyond the scene so the anchor sits at the directional light's
// vanishing point; the projection divides it out.
constexpr float kAnchorReachGu = 1.0e6f;
// Allow the anchor to drift slightly off the visible rect and still scatter —
// the shafts reach inward from screen pixels toward an anchor just past the
// edge. Beyond this pad the contribution is negligible, so we cull (and the
// shader early-outs).
constexpr float kAnchorPad = 0.25f;

// Dial defaults (live-tuned per the brief — start strong, dial at Vesuvi4).
constexpr int   kSamples  = 48;
constexpr float kDecay    = 0.96f;
constexpr float kWeight   = 0.5f;
constexpr float kExposure = 0.10f;
}  // namespace

NebulaGodrayPass::NebulaGodrayPass() = default;
NebulaGodrayPass::~NebulaGodrayPass() {
    // Safe even if initialize_gl() never ran: glDeleteVertexArrays(1, &0) is a
    // no-op per the GL spec, so the lazy-init path leaves nothing to leak.
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void NebulaGodrayPass::initialize_gl() {
    // Empty VAO: the fullscreen triangle is generated from gl_VertexID in the
    // vertex shader, but core profile still requires a bound VAO for draws.
    glGenVertexArrays(1, &vao_);
    initialized_ = true;
}

void NebulaGodrayPass::render(const scenegraph::Camera& camera,
                              Pipeline& pipeline,
                              const std::vector<GodrayFlash>& flashes,
                              std::uint32_t hdr_color_tex) {
    // Stock-BC byte-identity: nothing to draw => zero GL work.
    if (!enabled_ || flashes.empty()) return;
    if (!initialized_) initialize_gl();

    const glm::mat4 view_proj = camera.proj_matrix() * camera.view_matrix();

    // ── Set up the additive composite into the currently-bound HDR target. ───
    // Reads the HDR colour while additively blending into the SAME HDR target
    // (same-FBO read-while-write). Per the GL spec this is technically undefined,
    // but all tested desktop drivers return the pre-draw texel content — exactly
    // what the radial scatter wants, and glGetError() is clean. If a future
    // platform flags a feedback hazard, render into a half-res scratch target and
    // composite (as nebula_volumetric_pass does) instead of reading the bound HDR.
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    auto& sh = pipeline.nebula_godray_shader();
    sh.use();

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, hdr_color_tex);
    sh.set_int("u_scene", 0);
    sh.set_int("u_samples", kSamples);
    sh.set_float("u_decay", kDecay);
    sh.set_float("u_weight", kWeight);
    sh.set_float("u_exposure", kExposure);

    glBindVertexArray(vao_);

    for (const auto& f : flashes) {
        // Light comes FROM `dir`; the on-screen anchor is a far point along it.
        const glm::vec3 world = camera.eye + glm::normalize(f.dir) * kAnchorReachGu;
        const glm::vec4 clip = view_proj * glm::vec4(world, 1.0f);

        float on_screen = 0.0f;
        glm::vec2 anchor(0.5f, 0.5f);
        if (clip.w > 0.0f) {
            const glm::vec2 ndc = glm::vec2(clip.x, clip.y) / clip.w;  // [-1,1]
            anchor = ndc * 0.5f + 0.5f;                                // [0,1]
            if (anchor.x >= -kAnchorPad && anchor.x <= 1.0f + kAnchorPad &&
                anchor.y >= -kAnchorPad && anchor.y <= 1.0f + kAnchorPad) {
                on_screen = 1.0f;
            }
        }

        sh.set_vec2("u_anchor", anchor);
        sh.set_float("u_on_screen", on_screen);
        sh.set_vec3("u_color", f.color);
        sh.set_float("u_intensity", f.intensity);

        // Off-screen anchor → u_on_screen=0 → shader outputs zero (light + audio
        // still happen elsewhere; only the shafts are absent). Intended.
        glDrawArrays(GL_TRIANGLES, 0, 3);
    }

    glBindVertexArray(0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);

    // ─── RESTORE CANONICAL GL STATE ──────────────────────────────────────────
    // Leave the pipeline as later passes expect: blend disabled (func reset to
    // the common src-alpha default), depth test on, depth writes on, back-face
    // culling on. Framebuffer/viewport were never changed by this pass.
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_BLEND);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
