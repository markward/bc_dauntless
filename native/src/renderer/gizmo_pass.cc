// native/src/renderer/gizmo_pass.cc
#include "renderer/gizmo_pass.h"
#include "renderer/shader.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/constants.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <cmath>
#include <string>
#include <vector>

namespace renderer {

namespace {

constexpr int kHeadSegments = 8;   // spokes around the arrow-head cone
constexpr float kShaftEnd = 0.85f;   // unit arrow: shaft 0 -> kShaftEnd
constexpr float kHeadRadius = 0.05f;

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

GizmoPass::GizmoPass() = default;

GizmoPass::~GizmoPass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void GizmoPass::ensure_resources() {
    if (vao_) return;
    shader_ = std::make_unique<Shader>(kVs, kFs);

    // Unit arrow along local +Z: a shaft line from the origin to kShaftEnd,
    // plus a small cone of GL_LINES spokes from a base ring (z=kShaftEnd,
    // radius kHeadRadius) to the tip (z=1.0), with the ring edges drawn too
    // so the head reads as a cone silhouette.
    std::vector<float> verts;
    auto push = [&verts](float x, float y, float z) {
        verts.push_back(x); verts.push_back(y); verts.push_back(z);
    };

    // Shaft.
    push(0.0f, 0.0f, 0.0f);
    push(0.0f, 0.0f, kShaftEnd);

    // Cone head: ring -> tip spokes, and ring -> ring edges.
    for (int i = 0; i < kHeadSegments; ++i) {
        const float a0 = glm::two_pi<float>() * (static_cast<float>(i) / kHeadSegments);
        const float a1 = glm::two_pi<float>() * (static_cast<float>(i + 1) / kHeadSegments);
        const float x0 = kHeadRadius * std::cos(a0), y0 = kHeadRadius * std::sin(a0);
        const float x1 = kHeadRadius * std::cos(a1), y1 = kHeadRadius * std::sin(a1);

        // Spoke: ring point -> tip.
        push(x0, y0, kShaftEnd);
        push(0.0f, 0.0f, 1.0f);

        // Ring edge: ring point -> next ring point.
        push(x0, y0, kShaftEnd);
        push(x1, y1, kShaftEnd);
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

namespace {

// Rotation matrix that maps local +Z onto the given unit axis `a`.
glm::mat4 rotation_onto(const glm::vec3& a) {
    const glm::vec3 z(0.0f, 0.0f, 1.0f);
    const float d = glm::dot(z, a);
    if (d > 0.9999f) return glm::mat4(1.0f);
    if (d < -0.9999f)
        return glm::rotate(glm::mat4(1.0f), glm::pi<float>(), glm::vec3(1, 0, 0));
    const glm::vec3 axis = glm::normalize(glm::cross(z, a));
    const float angle = std::acos(d);
    return glm::rotate(glm::mat4(1.0f), angle, axis);
}

}  // namespace

void GizmoPass::render(const Gizmo& g, const scenegraph::Camera& camera) {
    if (g.length <= 0.0f) return;
    ensure_resources();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader_->use();

    glDisable(GL_DEPTH_TEST);   // always visible in the SPV overlay
    glDisable(GL_CULL_FACE);
    glLineWidth(2.0f);
    glBindVertexArray(vao_);

    static const glm::vec3 kAxisColor[3] = {
        {0.9f, 0.25f, 0.25f},   // X: red
        {0.35f, 0.9f, 0.35f},   // Y: green
        {0.35f, 0.55f, 1.0f},   // Z: blue
    };

    for (int k = 0; k < 3; ++k) {
        const glm::vec3 axis = glm::normalize(g.axis[k]);
        const glm::mat4 rot = rotation_onto(axis);
        const glm::mat4 model =
            glm::translate(glm::mat4(1.0f), g.origin) * rot *
            glm::scale(glm::mat4(1.0f), glm::vec3(g.length));

        glm::vec3 color = kAxisColor[k];
        if (k == g.highlight) color = glm::mix(color, glm::vec3(1.0f), 0.4f);

        shader_->set_vec3("u_color", color);
        shader_->set_mat4("u_mvp", vp * model);
        glDrawArrays(GL_LINES, 0, vertex_count_);
    }

    glBindVertexArray(0);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
