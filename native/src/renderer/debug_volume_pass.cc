// native/src/renderer/debug_volume_pass.cc
#include "renderer/debug_volume_pass.h"
#include "renderer/shader.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/constants.hpp>

#include <cmath>
#include <string>
#include <vector>

namespace renderer {

namespace {

constexpr int kSegments = 24;   // circular resolution of the debug cylinder

const std::string kVs = R"(#version 330 core
layout(location = 0) in vec3 a_pos;
uniform mat4 u_mvp;
void main() { gl_Position = u_mvp * vec4(a_pos, 1.0); }
)";

const std::string kFs = R"(#version 330 core
out vec4 frag_color;
uniform vec3 u_color;
void main() { frag_color = vec4(u_color, 1.0); }
)";

}  // namespace

DebugVolumePass::DebugVolumePass() = default;

DebugVolumePass::~DebugVolumePass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void DebugVolumePass::ensure_resources() {
    if (vao_) return;
    shader_ = std::make_unique<Shader>(kVs, kFs);

    // Unit cylinder: radius 1 in the XY plane, extruded along +Z from 0 to 1.
    // Side quads split into triangles; rendered as wireframe (glPolygonMode
    // GL_LINE) so the triangle edges outline the tube (both end rings + spokes).
    std::vector<float> verts;
    verts.reserve(kSegments * 6 * 3);
    for (int i = 0; i < kSegments; ++i) {
        const float a0 = glm::two_pi<float>() * (static_cast<float>(i) / kSegments);
        const float a1 = glm::two_pi<float>() * (static_cast<float>(i + 1) / kSegments);
        const float x0 = std::cos(a0), y0 = std::sin(a0);
        const float x1 = std::cos(a1), y1 = std::sin(a1);
        const float quad[6][3] = {
            {x0, y0, 0.0f}, {x1, y1, 0.0f}, {x1, y1, 1.0f},
            {x0, y0, 0.0f}, {x1, y1, 1.0f}, {x0, y0, 1.0f},
        };
        for (auto& v : quad) { verts.push_back(v[0]); verts.push_back(v[1]); verts.push_back(v[2]); }
    }
    vertex_count_ = static_cast<int>(verts.size() / 3);

    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(verts.size() * sizeof(float)),
                 verts.data(), GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void DebugVolumePass::render(const std::vector<DebugCylinder>& cylinders,
                             const scenegraph::Camera& camera) {
    if (cylinders.empty()) return;
    ensure_resources();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader_->use();

    glDisable(GL_DEPTH_TEST);   // always visible, drawn over the hull
    glDisable(GL_CULL_FACE);
    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE);
    glLineWidth(1.5f);
    glBindVertexArray(vao_);

    for (const auto& c : cylinders) {
        // Map the unit cylinder (local +Z, radius 1) onto this cylinder: local
        // +Z -> axis (scaled by length), local X/Y -> a perpendicular basis
        // scaled by radius, origin at center. All in world space.
        const glm::vec3 w = glm::normalize(c.axis);
        const glm::vec3 up = (std::abs(w.y) < 0.99f) ? glm::vec3(0, 1, 0)
                                                     : glm::vec3(1, 0, 0);
        const glm::vec3 u = glm::normalize(glm::cross(up, w));
        const glm::vec3 v = glm::cross(w, u);

        glm::mat4 M(1.0f);
        M[0] = glm::vec4(u * c.radius, 0.0f);
        M[1] = glm::vec4(v * c.radius, 0.0f);
        M[2] = glm::vec4(w * c.length, 0.0f);
        M[3] = glm::vec4(c.center, 1.0f);

        shader_->set_vec3("u_color", c.color);
        shader_->set_mat4("u_mvp", vp * M);
        glDrawArrays(GL_TRIANGLES, 0, vertex_count_);
    }

    glBindVertexArray(0);
    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
