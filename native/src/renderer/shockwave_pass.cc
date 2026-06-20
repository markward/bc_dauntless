// native/src/renderer/shockwave_pass.cc
#include "renderer/shockwave_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace renderer {

ShockwavePass::~ShockwavePass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void ShockwavePass::initialize_gl() {
    // Unit quad in [-1, 1], two triangles, one vec2 attribute (location 0).
    static const float kQuad[] = {
        -1.0f, -1.0f,   1.0f, -1.0f,   1.0f, 1.0f,
        -1.0f, -1.0f,   1.0f,  1.0f,  -1.0f, 1.0f,
    };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuad), kQuad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    initialized_ = true;
}

void ShockwavePass::render(const scenegraph::Camera& cam,
                           const std::vector<ShockwaveDescriptor>& shockwaves,
                           Pipeline& pipeline) {
    if (shockwaves.empty()) return;
    if (!initialized_) initialize_gl();

    // Additive, camera-facing, depth-tested but not depth-writing (dust state).
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    Shader& sh = pipeline.shockwave_shader();
    sh.use();
    sh.set_mat4("u_view", cam.view_matrix());
    sh.set_mat4("u_proj", cam.proj_matrix());

    glBindVertexArray(vao_);
    for (const auto& s : shockwaves) {
        const float t = (s.lifetime > 0.0f) ? (s.age / s.lifetime) : 1.0f;
        sh.set_vec3("u_center", s.world_center);
        sh.set_float("u_max_radius", s.max_radius);
        sh.set_float("u_t", t);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
    glBindVertexArray(0);

    // Restore defaults so later passes don't inherit our state (dust_pass pattern).
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glDisable(GL_BLEND);
}

}  // namespace renderer
