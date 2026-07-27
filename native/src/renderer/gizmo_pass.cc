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
constexpr float kCubeHalfSide = 0.06f;   // scale-handle cube: side 0.12 * length
constexpr int kRingSegments = 48;   // rotate-handle ring: segments around the circle

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
    if (cube_vbo_) glDeleteBuffers(1, &cube_vbo_);
    if (cube_vao_) glDeleteVertexArrays(1, &cube_vao_);
    if (ring_vbo_) glDeleteBuffers(1, &ring_vbo_);
    if (ring_vao_) glDeleteVertexArrays(1, &ring_vao_);
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

    // Second unit mesh: shaft + cube tip (Scale gizmo). Cube is centred at
    // z=1.0 with half-side kCubeHalfSide, drawn as its 12 edges via GL_LINES.
    std::vector<float> cube_verts;
    auto push_cube = [&cube_verts](float x, float y, float z) {
        cube_verts.push_back(x); cube_verts.push_back(y); cube_verts.push_back(z);
    };

    // Shaft.
    push_cube(0.0f, 0.0f, 0.0f);
    push_cube(0.0f, 0.0f, 1.0f - kCubeHalfSide);

    // Cube corners, centred at (0, 0, 1).
    const float h = kCubeHalfSide;
    glm::vec3 corner[8];
    int idx = 0;
    for (float sx : {-h, h})
        for (float sy : {-h, h})
            for (float sz : {-h, h})
                corner[idx++] = glm::vec3(sx, sy, 1.0f + sz);

    // 12 edges, indexed by corner bit pattern (sx<<2 | sy<<1 | sz).
    auto edge = [&](int a, int b) {
        push_cube(corner[a].x, corner[a].y, corner[a].z);
        push_cube(corner[b].x, corner[b].y, corner[b].z);
    };
    // Bottom face (sz = -h): indices 0,1,2,3 (sx,sy in {0,0},{0,1},{1,0},{1,1}).
    edge(0, 1); edge(1, 3); edge(3, 2); edge(2, 0);
    // Top face (sz = +h): indices 4,5,6,7.
    edge(4, 5); edge(5, 7); edge(7, 6); edge(6, 4);
    // Verticals.
    edge(0, 4); edge(1, 5); edge(2, 6); edge(3, 7);

    cube_vertex_count_ = static_cast<int>(cube_verts.size() / 3);

    glGenVertexArrays(1, &cube_vao_);
    glGenBuffers(1, &cube_vbo_);
    glBindVertexArray(cube_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, cube_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(cube_verts.size() * sizeof(float)),
                 cube_verts.data(), GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
    glBindVertexArray(0);

    // Third unit mesh: a segmented unit circle (radius 1) in the local XY
    // plane, normal +Z (Rotate gizmo). No shaft, no tip -- just the ring,
    // drawn as GL_LINES segment pairs closing the loop.
    std::vector<float> ring_verts;
    auto push_ring = [&ring_verts](float x, float y, float z) {
        ring_verts.push_back(x); ring_verts.push_back(y); ring_verts.push_back(z);
    };
    for (int i = 0; i < kRingSegments; ++i) {
        const float a0 = glm::two_pi<float>() * (static_cast<float>(i) / kRingSegments);
        const float a1 = glm::two_pi<float>() * (static_cast<float>(i + 1) / kRingSegments);
        push_ring(std::cos(a0), std::sin(a0), 0.0f);
        push_ring(std::cos(a1), std::sin(a1), 0.0f);
    }

    ring_vertex_count_ = static_cast<int>(ring_verts.size() / 3);

    glGenVertexArrays(1, &ring_vao_);
    glGenBuffers(1, &ring_vbo_);
    glBindVertexArray(ring_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, ring_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(ring_verts.size() * sizeof(float)),
                 ring_verts.data(), GL_STATIC_DRAW);
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

    static const glm::vec3 kAxisColor[3] = {
        {0.9f, 0.25f, 0.25f},   // X: red
        {0.35f, 0.9f, 0.35f},   // Y: green
        {0.35f, 0.55f, 1.0f},   // Z: blue
    };
    // Scale-handle colours: desaturated/brighter than the move-gizmo cones,
    // so the two tools read as visually distinct.
    static const glm::vec3 kScaleAxisColor[3] = {
        {1.0f, 0.65f, 0.55f},   // X: pale coral
        {0.75f, 1.0f, 0.65f},   // Y: pale lime
        {0.65f, 0.85f, 1.0f},   // Z: pale sky
    };

    // Rotate-handle colours: same hue family as the move/scale gizmos so the
    // three tools stay recognisable as one family, but distinct enough to
    // tell apart at a glance.
    static const glm::vec3 kRingAxisColor[3] = {
        {1.0f, 0.45f, 0.35f},   // X: warm coral
        {0.5f, 1.0f, 0.5f},     // Y: bright lime
        {0.45f, 0.7f, 1.0f},    // Z: bright sky
    };

    if (g.handle_kind == 2) {
        glBindVertexArray(ring_vao_);
        for (int k = 0; k < 3; ++k) {
            const glm::vec3 axis = glm::normalize(g.axis[k]);
            const glm::mat4 rot = rotation_onto(axis);
            const glm::mat4 model =
                glm::translate(glm::mat4(1.0f), g.origin) * rot *
                glm::scale(glm::mat4(1.0f), glm::vec3(g.length));

            glm::vec3 color = kRingAxisColor[k];
            if (k == g.highlight) color = glm::mix(color, glm::vec3(1.0f), 0.4f);

            shader_->set_vec3("u_color", color);
            shader_->set_mat4("u_mvp", vp * model);
            glDrawArrays(GL_LINES, 0, ring_vertex_count_);
        }
        glBindVertexArray(0);
        glEnable(GL_DEPTH_TEST);
        glEnable(GL_CULL_FACE);
        return;
    }

    const bool cube = (g.handle_kind == 1);
    glBindVertexArray(cube ? cube_vao_ : vao_);
    const int count = cube ? cube_vertex_count_ : vertex_count_;

    for (int k = 0; k < 3; ++k) {
        const glm::vec3 axis = glm::normalize(g.axis[k]);
        const glm::mat4 rot = rotation_onto(axis);
        const glm::mat4 model =
            glm::translate(glm::mat4(1.0f), g.origin) * rot *
            glm::scale(glm::mat4(1.0f), glm::vec3(g.length));

        glm::vec3 color = cube ? kScaleAxisColor[k] : kAxisColor[k];
        if (k == g.highlight) color = glm::mix(color, glm::vec3(1.0f), 0.4f);

        shader_->set_vec3("u_color", color);
        shader_->set_mat4("u_mvp", vp * model);
        glDrawArrays(GL_LINES, 0, count);
    }

    glBindVertexArray(0);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
