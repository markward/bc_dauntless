// native/src/renderer/nebula_volumetric_pass.cc
#include "renderer/nebula_volumetric_pass.h"

#include "renderer/nebula_pass.h"   // NebulaVolume
#include "renderer/frame.h"          // Lighting
#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>

namespace renderer {

namespace {
constexpr int kMaxSpheres = 8;   // matches u_spheres[8] in the shader

// History is reset when the camera moves "a lot" between frames — temporal
// reprojection only holds up for small deltas. Generous thresholds: ghosting
// is the failure mode, so when in doubt we throw history away.
constexpr float kMaxEyeDeltaGu = 30.0f;    // GU of camera translation per frame
constexpr float kTemporalWeight = 0.90f;   // history blend; higher → faster noise
                                           // convergence (ghosting bounded by reset)
constexpr float kDitherAmount = 0.5f;      // half-step jitter — less per-frame
                                           // variance for temporal to resolve
}  // namespace

NebulaVolumetricPass::NebulaVolumetricPass() = default;

NebulaVolumetricPass::~NebulaVolumetricPass() {
    if (vao_ != 0) {
        glDeleteVertexArrays(1, &vao_);
        vao_ = 0;
    }
    destroy_half_targets();
}

void NebulaVolumetricPass::initialize_gl() {
    if (initialized_) return;
    // Empty VAO: the fullscreen triangle is generated entirely from
    // gl_VertexID in the vertex shader, but core profile still requires a
    // bound VAO for glDrawArrays.
    glGenVertexArrays(1, &vao_);
    initialized_ = true;
}

void NebulaVolumetricPass::destroy_half_targets() {
    for (int i = 0; i < 2; ++i) {
        if (half_tex_[i]) { glDeleteTextures(1, &half_tex_[i]); half_tex_[i] = 0; }
        if (half_fbo_[i]) { glDeleteFramebuffers(1, &half_fbo_[i]); half_fbo_[i] = 0; }
    }
    half_w_ = half_h_ = 0;
    have_history_ = false;
}

void NebulaVolumetricPass::ensure_half_targets(int w, int h) {
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

void NebulaVolumetricPass::render(const scenegraph::Camera& camera,
                                  Pipeline& pipeline,
                                  const std::vector<NebulaVolume>& volumes,
                                  const Lighting& lighting,
                                  std::uint32_t /*hdr_color_tex*/,
                                  std::uint32_t hdr_depth_tex,
                                  const glm::mat4& inv_view_proj,
                                  const glm::vec3& eye,
                                  float time) {
    // Stock-BC byte-identity: nothing to draw => zero GL work.
    if (volumes.empty()) return;
    if (!initialized_) initialize_gl();

    // Flatten the sphere-union from all volumes into a single clamped array.
    // The fbm/tint/seed are taken from the first volume (the renderer treats a
    // MetaNebula as one tinted field; multi-volume scenes are rare and share
    // the dial set). Spheres beyond kMaxSpheres are dropped.
    std::vector<glm::vec4> spheres;
    spheres.reserve(kMaxSpheres);
    for (const auto& v : volumes) {
        for (const auto& s : v.spheres) {
            if (static_cast<int>(spheres.size()) >= kMaxSpheres) break;
            spheres.push_back(s);
        }
        if (static_cast<int>(spheres.size()) >= kMaxSpheres) break;
    }
    if (spheres.empty()) return;   // all volumes had no spheres => nothing.

    const NebulaVolume& v0 = volumes.front();

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
    const float eye_delta = glm::length(eye - prev_eye_);
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

    auto& march = pipeline.nebula_volumetric_shader();
    march.use();

    // Camera / ray reconstruction.
    march.set_mat4("u_inv_view_proj", inv_view_proj);
    march.set_vec3("u_eye", eye);
    march.set_float("u_near", camera.near);
    march.set_float("u_far", camera.far);
    march.set_float("u_time", time);

    // Sphere union + field params.
    march.set_int("u_sphere_count", static_cast<int>(spheres.size()));
    march.set_vec4_array("u_spheres", spheres.data(),
                         static_cast<int>(spheres.size()));
    march.set_vec3("u_rgb", v0.rgb);
    march.set_vec3("u_fbm", v0.fbm);
    march.set_vec3("u_seed", v0.seed);

    // Up to 4 directional lights.
    int nlights = std::clamp(lighting.directional_count, 0,
                             Lighting::MaxDirectionals);
    march.set_int("u_dir_light_count", nlights);
    if (nlights > 0) {
        march.set_vec3_array("u_dir_light_dir_ws",
                             lighting.directional_dir_ws, nlights);
        march.set_vec3_array("u_dir_light_color",
                             lighting.directional_color, nlights);
    }

    // Tunable dials (defaults; live-tuning per the brief — start strong).
    // u_step x u_max_steps = 576 GU reach. Step widened 6->9 + count trimmed
    // 96->64 (same reach, ~1.5x fewer steps) as a first perf pass; the dither
    // offset + temporal hide the coarser stepping.
    march.set_float("u_step", 9.0f);
    march.set_int("u_max_steps", 64);
    march.set_float("u_density_scale", 0.06f);
    march.set_float("u_scatter", 1.2f);
    march.set_float("u_self_glow", 0.25f);
    march.set_float("u_light_steps", 0.0f);  // self-shadow OFF (perf): 0 occlusion
                                              // taps → 1 density() eval/step. Cloud
                                              // is flat-lit (less core form).

    // Perf-path dials: dither step-offset + temporal.
    // u_jitter animates the dither pattern slightly so it doesn't sit static.
    march.set_vec2("u_jitter", glm::vec2(std::fmod(time * 31.0f, 64.0f),
                                         std::fmod(time * 17.0f, 64.0f)));
    march.set_float("u_dither_amount", kDitherAmount);
    march.set_float("u_temporal_weight", temporal_ok ? kTemporalWeight : 0.0f);
    march.set_mat4("u_prev_view_proj", prev_view_proj_);
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
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, half_tex_[cur_]);
    up.set_int("u_cloud", 0);
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, hdr_depth_tex);
    up.set_int("u_depth", 1);

    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    // Leave texture unit 1 unbound / active unit back to 0 (common default).
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);

    // ── Update temporal history for next frame ─────────────────────────────
    prev_view_proj_ = view_proj;
    prev_eye_ = eye;
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
