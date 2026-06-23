// native/src/renderer/nebula_volumetric_pass.cc
#include "renderer/nebula_volumetric_pass.h"

#include "renderer/nebula_pass.h"   // NebulaVolume
#include "renderer/frame.h"          // Lighting
#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <algorithm>

namespace renderer {

namespace {
constexpr int kMaxSpheres = 8;   // matches u_spheres[8] in the shader
}

NebulaVolumetricPass::NebulaVolumetricPass() = default;

NebulaVolumetricPass::~NebulaVolumetricPass() {
    if (vao_ != 0) {
        glDeleteVertexArrays(1, &vao_);
        vao_ = 0;
    }
}

void NebulaVolumetricPass::initialize_gl() {
    if (initialized_) return;
    // Empty VAO: the fullscreen triangle is generated entirely from
    // gl_VertexID in the vertex shader, but core profile still requires a
    // bound VAO for glDrawArrays.
    glGenVertexArrays(1, &vao_);
    initialized_ = true;
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

    auto& shader = pipeline.nebula_volumetric_shader();
    shader.use();

    // Camera / ray reconstruction.
    shader.set_mat4("u_inv_view_proj", inv_view_proj);
    shader.set_vec3("u_eye", eye);
    shader.set_float("u_near", camera.near);
    shader.set_float("u_far", camera.far);
    shader.set_float("u_time", time);

    // Sphere union + field params.
    shader.set_int("u_sphere_count", static_cast<int>(spheres.size()));
    shader.set_vec4_array("u_spheres", spheres.data(),
                          static_cast<int>(spheres.size()));
    shader.set_vec3("u_rgb", v0.rgb);
    shader.set_vec3("u_fbm", v0.fbm);
    shader.set_vec3("u_seed", v0.seed);

    // Up to 4 directional lights.
    int nlights = std::clamp(lighting.directional_count, 0,
                             Lighting::MaxDirectionals);
    shader.set_int("u_dir_light_count", nlights);
    if (nlights > 0) {
        shader.set_vec3_array("u_dir_light_dir_ws",
                              lighting.directional_dir_ws, nlights);
        shader.set_vec3_array("u_dir_light_color",
                              lighting.directional_color, nlights);
    }

    // Tunable dials (defaults; live-tuning per the brief — start strong).
    shader.set_float("u_step", 6.0f);
    shader.set_int("u_max_steps", 96);
    shader.set_float("u_density_scale", 0.06f);
    shader.set_float("u_scatter", 1.2f);
    shader.set_float("u_self_glow", 0.25f);
    shader.set_float("u_light_steps", 3.0f);

    // HDR depth texture (read-only): clamps the march to hulls.
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, hdr_depth_tex);
    shader.set_int("u_depth", 0);

    // Composite state: premultiplied OVER blend, depth test/write OFF.
    // Disable culling: the fullscreen triangle winding must survive regardless
    // of whatever glFrontFace / cull-mode a prior pass left active.
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    // ─── RESTORE CANONICAL GL STATE ──────────────────────────────────────────
    // Leave the pipeline as the next pass (lens flare / torpedo / phaser)
    // expects: blend disabled (func reset to the common src-alpha default),
    // depth test on, depth writes on, back-face culling on.
    // NOTE: depth func is NOT touched here — the pass never changes it, so
    // restoring it would imply false ownership and could clobber a future pass.
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_BLEND);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
