// native/src/renderer/nebula_godray_pass.cc
#include "renderer/nebula_godray_pass.h"
#include "renderer/pipeline.h"
#include "renderer/shader.h"
#include <scenegraph/camera.h>
#include <glad/glad.h>
#include <glm/glm.hpp>
#include <algorithm>

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
constexpr float kJitter   = 0.004f;  // small god-ray sample-uv jitter; insurance
                                      // against residual cloud-grid amplification
                                      // (the upsample fix is the real solution)
// Geometry nearer than this fraction of the light's body's distance is an
// occluder, never a source. Generous on purpose: a ship is a few GU from the
// eye and a star thousands, so anything in between (a planet half-way to the
// star) keeps scattering as it always did.
constexpr float kOccluderFraction = 0.5f;
// solve_virtual_placement's remap of a body beyond the far plane.
constexpr float kVirtualFarFraction = 0.95f;
}  // namespace

float godray_source_depth(const scenegraph::Camera& camera,
                          const GodrayFlash& flash) {
    if (flash.distance <= 0.0f) return 1.0f;   // no body: sky only
    // Where the body is DRAWN: where it is inside the far plane, else just
    // inside it (sun_pass.cc's solve_virtual_placement).
    const float drawn = flash.distance <= camera.far
        ? flash.distance : camera.far * kVirtualFarFraction;
    // View-space depth of the body's centre, so the cut holds off-axis too.
    const glm::vec3 fwd = glm::normalize(camera.target - camera.eye);
    const float body_z = drawn * glm::dot(glm::normalize(flash.dir), fwd);
    if (body_z <= camera.near) return 1.0f;    // behind the eye: sky only
    const float cut_z = std::max(camera.near, kOccluderFraction * body_z);
    const glm::vec4 clip =
        camera.proj_matrix() * glm::vec4(0.0f, 0.0f, -cut_z, 1.0f);
    return std::min(1.0f, (clip.z / clip.w) * 0.5f + 0.5f);
}

NebulaGodrayPass::NebulaGodrayPass() = default;
NebulaGodrayPass::~NebulaGodrayPass() {
    // Safe even if initialize_gl() never ran: deleting name 0 is a no-op per
    // the GL spec, so the lazy-init path leaves nothing to leak.
    if (vao_) glDeleteVertexArrays(1, &vao_);
    destroy_half_targets();
}

void NebulaGodrayPass::initialize_gl() {
    // Empty VAO: the fullscreen triangle is generated from gl_VertexID in the
    // vertex shader, but core profile still requires a bound VAO for draws.
    glGenVertexArrays(1, &vao_);
    initialized_ = true;
}

void NebulaGodrayPass::destroy_half_targets() {
    for (unsigned int* t : {&mask_tex_, &rays_tex_})
        if (*t) { glDeleteTextures(1, t); *t = 0; }
    for (unsigned int* f : {&mask_fbo_, &rays_fbo_})
        if (*f) { glDeleteFramebuffers(1, f); *f = 0; }
    half_w_ = half_h_ = 0;
}

namespace {
// One half-res colour target. R11G11B10F: unsigned HDR at half the bandwidth
// of RGBA16F -- the 48-step march is fetch-bound on the source image.
void make_half_target(int w, int h, unsigned int& tex, unsigned int& fbo) {
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R11F_G11F_B10F, w, h, 0, GL_RGB, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
}
}  // namespace

void NebulaGodrayPass::ensure_half_targets(int w, int h) {
    if (mask_fbo_ && w == half_w_ && h == half_h_) return;
    destroy_half_targets();
    make_half_target(w, h, mask_tex_, mask_fbo_);
    make_half_target(w, h, rays_tex_, rays_fbo_);
    glBindTexture(GL_TEXTURE_2D, 0);
    half_w_ = w; half_h_ = h;
}

void NebulaGodrayPass::render(const scenegraph::Camera& camera,
                              Pipeline& pipeline,
                              const std::vector<GodrayFlash>& flashes,
                              std::uint32_t hdr_color_tex,
                              std::uint32_t hdr_depth_tex) {
    // Stock-BC byte-identity: nothing to draw => zero GL work.
    if (!enabled_ || flashes.empty()) return;

    // Lights whose anchor projects usable: an off-screen anchor casts no
    // shafts (light + audio still happen elsewhere). Intended.
    const glm::mat4 view_proj = camera.proj_matrix() * camera.view_matrix();
    struct Lit { const GodrayFlash* f; glm::vec2 anchor; float source_depth; };
    std::vector<Lit> lit;
    for (const auto& f : flashes) {
        if (f.intensity <= 0.0f) continue;
        // Light comes FROM `dir`; the on-screen anchor is a far point along it.
        const glm::vec3 world = camera.eye + glm::normalize(f.dir) * kAnchorReachGu;
        const glm::vec4 clip = view_proj * glm::vec4(world, 1.0f);
        if (clip.w <= 0.0f) continue;
        const glm::vec2 anchor = glm::vec2(clip.x, clip.y) / clip.w * 0.5f + 0.5f;
        if (anchor.x < -kAnchorPad || anchor.x > 1.0f + kAnchorPad ||
            anchor.y < -kAnchorPad || anchor.y > 1.0f + kAnchorPad) continue;
        lit.push_back({&f, anchor, godray_source_depth(camera, f)});
    }
    if (lit.empty()) return;
    if (!initialized_) initialize_gl();

    // The caller has the HDR target bound; restore exactly it (and its
    // viewport) before the full-res composite.
    GLint prev_fbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev_fbo);
    GLint vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, vp);
    if (vp[2] < 1 || vp[3] < 1) return;
    const int hw = std::max(1, vp[2] / 2);
    const int hh = std::max(1, vp[3] / 2);
    ensure_half_targets(hw, hh);

    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
    glViewport(0, 0, hw, hh);
    glBindVertexArray(vao_);

    // The march accumulates every light additively into the rays target.
    glBindFramebuffer(GL_FRAMEBUFFER, rays_fbo_);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    auto& mask = pipeline.nebula_godray_mask_shader();
    auto& march = pipeline.nebula_godray_shader();
    float mask_depth = -1.0f;   // the source depth mask_tex_ holds, if any
    for (const Lit& l : lit) {
        // ── Source image: the masked scene at half res. Lights sharing a
        // source depth (every lightning flash: sky only) share one build.
        if (l.source_depth != mask_depth) {
            glBindFramebuffer(GL_FRAMEBUFFER, mask_fbo_);
            glDisable(GL_BLEND);
            mask.use();
            glActiveTexture(GL_TEXTURE0);
            glBindTexture(GL_TEXTURE_2D, hdr_color_tex);
            mask.set_int("u_scene", 0);
            glActiveTexture(GL_TEXTURE1);
            glBindTexture(GL_TEXTURE_2D, hdr_depth_tex);
            mask.set_int("u_depth", 1);
            mask.set_float("u_source_depth", l.source_depth);
            glDrawArrays(GL_TRIANGLES, 0, 3);
            mask_depth = l.source_depth;
        }

        // ── Radial march from the source image, added into the rays target.
        glBindFramebuffer(GL_FRAMEBUFFER, rays_fbo_);
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE);
        march.use();
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, mask_tex_);
        march.set_int("u_scene", 0);
        march.set_int("u_samples", kSamples);
        march.set_float("u_decay", kDecay);
        march.set_float("u_weight", kWeight);
        march.set_float("u_exposure", kExposure);
        march.set_float("u_jitter", kJitter);
        march.set_vec2("u_anchor", l.anchor);
        march.set_float("u_on_screen", 1.0f);
        march.set_vec3("u_color", l.f->color);
        march.set_float("u_intensity", l.f->intensity);
        glDrawArrays(GL_TRIANGLES, 0, 3);
    }

    // ── Blurred upsample, added into the HDR target. ────────────────────────
    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prev_fbo));
    glViewport(vp[0], vp[1], vp[2], vp[3]);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    auto& comp = pipeline.nebula_godray_composite_shader();
    comp.use();
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, rays_tex_);
    comp.set_int("u_rays", 0);
    comp.set_vec2("u_texel", glm::vec2(1.0f / hw, 1.0f / hh));
    glDrawArrays(GL_TRIANGLES, 0, 3);

    glBindVertexArray(0);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);

    // ─── RESTORE CANONICAL GL STATE ──────────────────────────────────────────
    // Leave the pipeline as later passes expect: blend disabled (func reset to
    // the common src-alpha default), depth test on, depth writes on, back-face
    // culling on. Framebuffer and viewport are the caller's again (above).
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_BLEND);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
