// native/src/renderer/hull_discharge_pass.cc
#include "renderer/hull_discharge_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>

namespace renderer {

namespace {

// Unit-quad corners ([-1,1]), 2 triangles — mirrors hit_vfx_pass.
constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,
    +1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, -1.0f,
    +1.0f, +1.0f,
    -1.0f, +1.0f,
};

// Procedural electric dials (start strong; live-tune at Vesuvi4).
constexpr int   kFilaments = 5;
constexpr float kJag       = 6.0f;
constexpr float kThick     = 0.06f;
constexpr float kCore      = 0.25f;

// Fraction of life over which the billboard eases 0 -> full size.
constexpr float kSpawnFrac    = 0.20f;
// Stutter period (s): an on/off flicker that sells the "crackle".
constexpr float kStutterPeriod = 0.03f;

}  // namespace

HullDischargePass::HullDischargePass() = default;

HullDischargePass::~HullDischargePass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void HullDischargePass::ensure_quad_mesh() {
    if (quad_vao_ != 0) return;
    glGenVertexArrays(1, &quad_vao_);
    glBindVertexArray(quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuadCorners), kQuadCorners,
                 GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glBindVertexArray(0);
}

void HullDischargePass::render(const scenegraph::Camera& camera,
                               Pipeline& pipeline,
                               const std::vector<HullDischarge>& discharges) {
    if (!enabled_ || discharges.empty()) return;   // zero GL work when idle
    ensure_quad_mesh();

    auto& shader = pipeline.hull_discharge_shader();
    shader.use();

    const glm::mat4 view = camera.view_matrix();
    const glm::mat4 proj = camera.proj_matrix();
    shader.set_mat4("u_view", view);
    shader.set_mat4("u_proj", proj);
    // Procedural dials are constant across discharges this frame.
    shader.set_int  ("u_filaments", kFilaments);
    shader.set_float("u_jag",       kJag);
    shader.set_float("u_thick",     kThick);
    shader.set_float("u_core",      kCore);

    // Additive electric billboards: blend GL_ONE/GL_ONE, depth-test on so
    // nearer hull occludes, depth-write off so sprites don't pollute depth,
    // cull off (the quad faces the camera either winding).
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);

    for (const auto& h : discharges) {
        const float life = (h.life > 1e-6f) ? h.life : 1e-6f;
        const float age  = std::max(0.0f, h.age);
        const float t    = std::min(1.0f, age / life);   // life progress [0,1]

        // Fast size ease 0 -> full over the first kSpawnFrac of life.
        const float ease = std::min(1.0f, t / std::max(1e-6f, kSpawnFrac));
        const float size = h.size * ease;
        const float alpha = std::max(0.0f, 1.0f - t);
        // 2-step on/off stutter from the discharge's own age.
        const float stutter =
            (((static_cast<int>(age / kStutterPeriod) & 1) == 0) ? 1.0f : 0.0f);

        // Per-descriptor uniforms (set inside the loop — no stale carry).
        shader.set_vec3 ("u_center",  h.world_pos);
        shader.set_float("u_size",    size);
        shader.set_vec3 ("u_color",   h.color);
        shader.set_float("u_alpha",   alpha);
        shader.set_float("u_stutter", stutter);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }

    glBindVertexArray(0);

    // Restore canonical GL defaults so later passes aren't corrupted.
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
}

}  // namespace renderer
