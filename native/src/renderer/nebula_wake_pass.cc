// native/src/renderer/nebula_wake_pass.cc
#include "renderer/nebula_wake_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

namespace renderer {

namespace {

// Unit-quad corners ([-1,1]), 2 triangles — mirrors hull_discharge_pass.
constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,  +1.0f, -1.0f,  +1.0f, +1.0f,
    -1.0f, -1.0f,  +1.0f, +1.0f,  -1.0f, +1.0f,
};

// Look dials (live-tune). Decoupled from cloud density, so these directly
// control the wake's size/brightness/colour. NOTE: the billboards are ADDITIVE
// and overlap heavily along the trail, so effective brightness ≈ kWakeGlow ×
// (overlap count). kWakeGlow must stay low — perceived brightness ∝
// kWakeGlow / SPACING (denser trail = more stacking).
constexpr float kWakeSizeScale = 1.0f;               // billboard half-size = point.size × this.
                                                     // point.size IS the impulse pod's GetRadius()
                                                     // (world-scale GU), so 1.0 = matched to the
                                                     // engine. Fine-tune only; not a fudge factor.
constexpr float kWakeGlow   = 0.075f;                // per-billboard intensity (additive stack)
constexpr float kWakeSoft   = 2.0f;                  // radial falloff exponent
constexpr glm::vec3 kWakeColor{0.55f, 0.75f, 1.0f};  // soft blue-white

}  // namespace

NebulaWakePass::NebulaWakePass() = default;

NebulaWakePass::~NebulaWakePass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void NebulaWakePass::ensure_quad_mesh() {
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

void NebulaWakePass::render(const scenegraph::Camera& camera,
                            Pipeline& pipeline,
                            const std::vector<NebulaWakePoint>& wake,
                            float time_s) {
    if (!enabled_ || wake.empty()) return;   // zero GL work when idle
    ensure_quad_mesh();

    auto& shader = pipeline.nebula_wake_shader();
    shader.use();
    shader.set_mat4 ("u_view", camera.view_matrix());
    shader.set_mat4 ("u_proj", camera.proj_matrix());
    shader.set_vec3 ("u_color",    kWakeColor);
    shader.set_float("u_glow",     kWakeGlow);
    shader.set_float("u_softness", kWakeSoft);
    shader.set_float("u_time",     time_s);

    // Additive soft-glow billboards: blend GL_ONE/GL_ONE, depth-test on so
    // nearer hull occludes, depth-write off, cull off (quad faces camera).
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);
    for (const auto& p : wake) {
        if (p.strength <= 0.0f) continue;        // skip just-born (faded-in) points
        shader.set_vec3 ("u_center",   p.pos);
        shader.set_float("u_size",     p.size * kWakeSizeScale);
        shader.set_float("u_strength", p.strength);
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
