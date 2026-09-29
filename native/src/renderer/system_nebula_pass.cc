// native/src/renderer/system_nebula_pass.cc
#include "renderer/system_nebula_pass.h"

#include "renderer/nebula_pass.h"   // NebulaVolume
#include "renderer/frame.h"          // Lighting
#include "renderer/pipeline.h"
#include "renderer/render_origin.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <vector>

namespace renderer {

namespace {
// Look dials (spec: docs/superpowers/specs/2026-09-29-system-nebula-render-design.md).
// near_range/lane_size/lane_contrast/g/floor are now live-tunable -- see
// SystemNebulaDials in the header and set_dials() below. kSteps stays a
// compile-time constant: it isn't part of the Task 7 dev-tuning surface.
constexpr int   kSteps = 64;               // near-field geometric steps

// History is reset when the camera moves "a lot" between frames — temporal
// reprojection only holds up for small deltas. Generous thresholds: ghosting
// is the failure mode, so when in doubt we throw history away.
constexpr float kMaxEyeDeltaGu = 30.0f;    // GU of camera translation per frame
constexpr float kTemporalWeight = 0.90f;   // history blend; higher → faster noise
                                           // convergence (ghosting bounded by reset)
constexpr float kDitherAmount = 0.5f;      // half-step jitter — less per-frame
                                           // variance for temporal to resolve
}  // namespace

NebulaDrawPlan plan_nebula_draws(bool volumetric_setting, bool developer,
                                 bool has_profile, bool have_volumes,
                                 bool have_wake) {
    NebulaDrawPlan p;
    p.system = volumetric_setting && developer && (has_profile || have_volumes);
    p.legacy = !p.system && have_volumes;
    // Drawn over the cloud so its soft-glow billboards add on top of the
    // density -- after EITHER branch, and only when one of them drew (so
    // production, where only the legacy branch exists, is unchanged).
    p.wake = volumetric_setting && have_wake && (p.system || p.legacy);
    return p;
}

SystemNebulaPass::SystemNebulaPass() = default;

SystemNebulaPass::~SystemNebulaPass() {
    if (vao_ != 0) {
        glDeleteVertexArrays(1, &vao_);
        vao_ = 0;
    }
    destroy_half_targets();
    destroy_profile_textures();
}

namespace {
GLuint make_float_texture(GLint internal_format, GLenum format, int w, int h,
                          const float* data) {
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    glTexImage2D(GL_TEXTURE_2D, 0, internal_format, w, h, 0, format, GL_FLOAT, data);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, 0);
    return tex;
}
}  // namespace

void SystemNebulaPass::destroy_profile_textures() {
    for (unsigned int* t : {&radial_tex_, &table_tau_, &table_S_}) {
        if (*t) { glDeleteTextures(1, t); *t = 0; }
    }
}

void SystemNebulaPass::set_profile(const atmosphere::RadialProfile& profile,
                                   const atmosphere::LookParams& look) {
    namespace atm = atmosphere;
    destroy_profile_textures();
    profile_ = profile;
    look_ = look;
    // Keep dials_ in sync with whatever LookParams the pass actually renders
    // -- a per-system caller (or set_dials' own rebuild below) can pass g/
    // floor that differ from the dial struct's defaults, and dials() must
    // report the true baseline so the NEXT dev-key press steps from it
    // rather than silently clobbering the authored look.
    dials_.g = look.g;
    dials_.floor = look.floor;

    const std::vector<glm::vec2> radial = atm::build_radial_texels(profile, look);
    const atm::Table table = atm::build_table(profile, look);
    // Optical depth, never transmittance: see SystemNebulaPass / tau_from_table.
    const std::vector<glm::vec3> tau = atm::tau_from_table(table);

    radial_tex_ = make_float_texture(GL_RG32F, GL_RG, atm::kRadialTexels, 1,
                                     &radial[0].x);
    table_tau_ = make_float_texture(GL_RGB32F, GL_RGB, atm::kTableR, atm::kTableMu,
                                    &tau[0].x);
    table_S_ = make_float_texture(GL_RGB32F, GL_RGB, atm::kTableR, atm::kTableMu,
                                  &table.inscatter[0].x);
    has_profile_ = true;
    have_history_ = false;   // a new atmosphere: last frame's cloud is stale
    ++profile_rebuild_count_;
}

void SystemNebulaPass::set_dials(const Dials& dials) {
    // g/floor feed the far-field table (build_table bakes them into every
    // cell's HG phase + floor), so a change needs the table rebuilt; the
    // OTHER dials (lane_size, lane_contrast, near_range) are read directly
    // by the shader every frame and never touch the table.
    const bool look_changed = (dials.g != dials_.g) || (dials.floor != dials_.floor);
    dials_ = dials;
    if (look_changed) {
        look_.g = dials.g;
        look_.floor = dials.floor;
        if (has_profile_) {
            // Re-upload with the SAME profile, updated LookParams -- exactly
            // what a fresh set_profile(profile_, look_) does, including the
            // rebuild counter and the temporal-history reset.
            set_profile(profile_, look_);
        }
    }
}

void SystemNebulaPass::clear_profile() {
    destroy_profile_textures();
    has_profile_ = false;
    profile_ = atmosphere::RadialProfile{};
    clear_star();
    have_history_ = false;
}

void SystemNebulaPass::initialize_gl() {
    if (initialized_) return;
    // Empty VAO: the fullscreen triangle is generated entirely from
    // gl_VertexID in the vertex shader, but core profile still requires a
    // bound VAO for glDrawArrays.
    glGenVertexArrays(1, &vao_);
    initialized_ = true;
}

void SystemNebulaPass::destroy_half_targets() {
    for (int i = 0; i < 2; ++i) {
        if (half_tex_[i]) { glDeleteTextures(1, &half_tex_[i]); half_tex_[i] = 0; }
        if (half_fbo_[i]) { glDeleteFramebuffers(1, &half_fbo_[i]); half_fbo_[i] = 0; }
    }
    half_w_ = half_h_ = 0;
    have_history_ = false;
}

void SystemNebulaPass::ensure_half_targets(int w, int h) {
    if (w < 1) w = 1;
    if (h < 1) h = 1;
    if (w == half_w_ && h == half_h_ && half_fbo_[0] != 0) return;
    destroy_half_targets();   // also clears history (different size => no reuse)
    half_w_ = w; half_h_ = h;
    for (int i = 0; i < 2; ++i) {
        glGenTextures(1, &half_tex_[i]);
        glBindTexture(GL_TEXTURE_2D, half_tex_[i]);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, nullptr);
        // LINEAR so the temporal reprojection bilinearly samples the previous
        // frame; the upsample does its own depth-aware tap selection.
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

        glGenFramebuffers(1, &half_fbo_[i]);
        glBindFramebuffer(GL_FRAMEBUFFER, half_fbo_[i]);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, half_tex_[i], 0);
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

void SystemNebulaPass::render(const scenegraph::Camera& /*camera*/,
                              Pipeline& pipeline,
                              const std::vector<NebulaVolume>& volumes,
                              const Lighting& /*lighting: the star lights the haze*/,
                              std::uint32_t /*hdr_color_tex*/,
                              std::uint32_t hdr_depth_tex,
                              const glm::mat4& inv_view_proj,
                              const glm::vec3& eye,
                              float time,
                              const glm::dvec3& origin) {
    // The profile haze is star-centred: without a star it cannot be placed.
    const bool draw_haze = has_profile_ && has_star_;
    // Nothing to draw => zero GL work.
    if (!draw_haze && volumes.empty()) return;
    if (!initialized_) initialize_gl();

    // ── Local MetaNebula clumps: at most kMaxClumps volumes, each a union of
    // up to kSpheresPerClump spheres (unused slots padded with radius 0, which
    // the shader skips). Extinction per GU per unit clump density is
    // 1/visibility (spec). Must match system_nebula.frag's array sizes.
    constexpr int kMaxClumps = 8;
    constexpr int kSpheresPerClump = 4;
    std::vector<glm::vec4> clump_sphere;
    std::vector<glm::vec3> clump_rgb;
    std::vector<glm::vec3> clump_fbm;
    std::vector<glm::vec3> clump_seed;
    std::vector<float>     clump_ext;
    for (const NebulaVolume& v : volumes) {
        if (static_cast<int>(clump_rgb.size()) >= kMaxClumps) break;
        if (v.spheres.empty()) continue;   // intentional: no sphere, no clump to draw
        for (int k = 0; k < kSpheresPerClump; ++k) {
            clump_sphere.push_back(k < static_cast<int>(v.spheres.size())
                                       ? v.spheres[k] : glm::vec4(0.0f));
        }
        clump_rgb.push_back(v.rgb);
        clump_fbm.push_back(v.fbm);
        clump_seed.push_back(v.seed);
        clump_ext.push_back(1.0f / std::max(v.visibility, 1.0f));
    }
    const int clump_count = static_cast<int>(clump_rgb.size());

    // ── Capture the currently-bound framebuffer + viewport ─────────────────
    // The caller (render_space) has the HDR target bound; everything below
    // must restore exactly this before returning so the scene keeps drawing
    // into HDR. The viewport gives us the full-res dimensions.
    GLint prev_fbo = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev_fbo);
    GLint prev_vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, prev_vp);
    const int full_w = prev_vp[2];
    const int full_h = prev_vp[3];
    if (full_w < 1 || full_h < 1) return;   // degenerate viewport; nothing to do

    // Half-res scratch (½ × ½, at least 1×1). (Re)allocated on size change.
    // Quarter-resolution raymarch (1/4 linear = 1/16 the pixels). The cloud is
    // low-frequency so this holds up; the depth-aware upsample keeps hull edges
    // crisp. (half_* members keep their name — they're just the low-res target.)
    const int hw = std::max(1, full_w / 4);
    const int hh = std::max(1, full_h / 4);
    ensure_half_targets(hw, hh);

    // ── Temporal validity ──────────────────────────────────────────────────
    // Reset history on a large camera delta (warp / big cut). The current
    // proj*view is reconstructed from inv_view_proj; we only need the previous
    // one for the reprojection, which is stored in prev_view_proj_.
    const glm::mat4 view_proj = glm::inverse(inv_view_proj);
    // The WORLD eye's travel, and last frame's matrix in THIS frame's render
    // space: the floating origin moves with the camera (render_origin.h).
    const float eye_delta = glm::length(
        render_origin::eye_travel(eye, prev_eye_, origin, prev_origin_));
    const glm::mat4 prev_view_proj =
        render_origin::rebase_prev_viewproj(prev_view_proj_, prev_origin_,
                                            origin);
    const bool temporal_ok = have_history_ && (eye_delta <= kMaxEyeDeltaGu);

    // ── PASS A: raymarch into the half-res target (overwrite, no blend) ─────
    cur_ ^= 1;                       // write target ping-pongs each frame
    const int prev_idx = cur_ ^ 1;   // previous frame's cloud

    glBindFramebuffer(GL_FRAMEBUFFER, half_fbo_[cur_]);
    glViewport(0, 0, hw, hh);
    glDisable(GL_BLEND);             // overwrite: the shader composes premultiplied
    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    auto& march = pipeline.system_nebula_shader();
    march.use();

    // Camera / ray reconstruction.
    march.set_mat4("u_inv_view_proj", inv_view_proj);
    march.set_vec3("u_eye", eye);

    // Atmosphere: star-centred profile + look dials.
    march.set_int("u_has_profile", draw_haze ? 1 : 0);
    march.set_int("u_has_star", has_star_ ? 1 : 0);
    march.set_vec3("u_star", star_);
    march.set_float("u_far_gu", look_.far_gu);
    march.set_float("u_k_sys", profile_.k_sys);
    march.set_vec3("u_cloud_rgb", profile_.cloud_rgb);
    march.set_vec3("u_star_rgb", profile_.star_rgb);
    march.set_float("u_g", look_.g);
    march.set_float("u_floor", look_.floor);
    march.set_float("u_scatter", look_.scatter);
    march.set_float("u_near_range", dials_.near_range);
    march.set_int("u_steps", kSteps);
    march.set_float("u_lane_size", dials_.lane_size);
    march.set_float("u_lane_contrast", dials_.lane_contrast);
    // The lanes' fbm is sampled at the WORLD point, p + origin, so the
    // structure stays put while the origin follows the camera.
    march.set_vec3("u_noise_origin", glm::vec3(origin));
    // Slow fbm drift for clumps only, matching nebula_volumetric.frag's
    // density(): gameplay concealment (engine/appc/nebula_density.py) reads
    // the same drifting field, so the visual clump must drift identically.
    march.set_float("u_time", time);

    // Local MetaNebula clumps: density bumps that add on top of (or, with no
    // profile, are the entire density of) the near field.
    march.set_int("u_clump_count", clump_count);
    if (clump_count > 0) {
        march.set_vec4_array("u_clump_sphere", clump_sphere.data(),
                             clump_count * kSpheresPerClump);
        march.set_vec3_array("u_clump_rgb", clump_rgb.data(), clump_count);
        march.set_vec3_array("u_clump_fbm", clump_fbm.data(), clump_count);
        march.set_vec3_array("u_clump_seed", clump_seed.data(), clump_count);
        march.set_float_array("u_clump_ext", clump_ext.data(), clump_count);
    }

    // Perf-path dials: dither step-offset + temporal.
    // u_jitter animates the dither pattern slightly so it doesn't sit static.
    march.set_vec2("u_jitter", glm::vec2(std::fmod(time * 31.0f, 64.0f),
                                         std::fmod(time * 17.0f, 64.0f)));
    march.set_float("u_dither_amount", kDitherAmount);
    march.set_float("u_temporal_weight", temporal_ok ? kTemporalWeight : 0.0f);
    march.set_mat4("u_prev_view_proj", prev_view_proj);
    march.set_vec2("u_half_texel",
                   glm::vec2(1.0f / static_cast<float>(hw),
                             1.0f / static_cast<float>(hh)));

    // Texture units: 0 = full-res HDR depth, 1 = previous half-res cloud.
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, hdr_depth_tex);
    march.set_int("u_depth", 0);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, half_tex_[prev_idx]);
    march.set_int("u_prev", 1);
    // 2 = radial (density, tau_star), 3 = far-field optical depth,
    // 4 = far-field inscatter.
    glActiveTexture(GL_TEXTURE2);
    glBindTexture(GL_TEXTURE_2D, radial_tex_);
    march.set_int("u_radial", 2);
    glActiveTexture(GL_TEXTURE3);
    glBindTexture(GL_TEXTURE_2D, table_tau_);
    march.set_int("u_table_tau", 3);
    glActiveTexture(GL_TEXTURE4);
    glBindTexture(GL_TEXTURE_2D, table_S_);
    march.set_int("u_table_S", 4);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // ── PASS B: depth-aware upsample composited into the HDR target ────────
    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(prev_fbo));
    glViewport(prev_vp[0], prev_vp[1], prev_vp[2], prev_vp[3]);

    // Premultiplied OVER blend into HDR, depth test/write OFF, no cull.
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);

    auto& up = pipeline.nebula_upsample_shader();
    up.use();
    up.set_vec2("u_half_texel",
                glm::vec2(1.0f / static_cast<float>(hw),
                          1.0f / static_cast<float>(hh)));
    up.set_vec2("u_full_texel",
                glm::vec2(1.0f / static_cast<float>(full_w),
                          1.0f / static_cast<float>(full_h)));
    // Joint-bilateral depth-edge sharpness: higher snaps harder at hull
    // silhouettes, lower blends smoother (hides the low-res grid better).
    up.set_float("u_depth_sharpness", 64.0f);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, half_tex_[cur_]);
    up.set_int("u_cloud", 0);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, hdr_depth_tex);
    up.set_int("u_depth", 1);

    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    // Unbind the profile units so no later pass inherits them.
    for (GLenum unit : {GL_TEXTURE4, GL_TEXTURE3, GL_TEXTURE2}) {
        glActiveTexture(unit);
        glBindTexture(GL_TEXTURE_2D, 0);
    }
    glActiveTexture(GL_TEXTURE1);

    // Leave texture unit 1 unbound / active unit back to 0 (common default).
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);

    // ── Update temporal history for next frame ─────────────────────────────
    prev_view_proj_ = view_proj;
    prev_eye_ = eye;
    prev_origin_ = origin;
    have_history_ = true;

    // ─── RESTORE CANONICAL GL STATE ──────────────────────────────────────────
    // Leave the pipeline as the next pass (lens flare / torpedo / phaser)
    // expects: blend disabled (func reset to the common src-alpha default),
    // depth test on, depth writes on, back-face culling on. The framebuffer
    // and viewport were already restored to the captured HDR target above.
    // NOTE: depth func is NOT touched — the pass never changes it.
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_BLEND);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
