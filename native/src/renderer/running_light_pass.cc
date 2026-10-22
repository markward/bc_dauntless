// native/src/renderer/running_light_pass.cc
#include "renderer/running_light_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace renderer {

namespace {
constexpr float kQuadCorners[] = {
    -1.0f, -1.0f,  +1.0f, -1.0f,  +1.0f, +1.0f,
    -1.0f, -1.0f,  +1.0f, +1.0f,  -1.0f, +1.0f,
};
}  // namespace

RunningLightPass::~RunningLightPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void RunningLightPass::ensure_quad_mesh() {
    if (quad_vao_ != 0) return;
    glGenVertexArrays(1, &quad_vao_);
    glBindVertexArray(quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuadCorners), kQuadCorners, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glBindVertexArray(0);
}

void RunningLightPass::render(const scenegraph::Camera& camera, Pipeline& pipeline,
                              const std::vector<RunningLightSprite>& sprites,
                              bool depth_test) {
    if (sprites.empty()) return;
    ensure_quad_mesh();
    auto& shader = pipeline.running_light_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());

    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    if (depth_test) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
    glBindVertexArray(quad_vao_);
    for (const auto& s : sprites) {
        shader.set_vec3 ("u_center",    s.world_pos);
        shader.set_float("u_half_size", s.half_size);
        shader.set_vec3 ("u_color",     s.color);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
    glBindVertexArray(0);
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
}

}  // namespace renderer
