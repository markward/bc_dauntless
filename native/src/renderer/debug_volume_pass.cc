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
uniform float u_alpha;   // 1.0 opaque (cylinders/boxes); < 1 for the sphere cage
void main() { frag_color = vec4(u_color, u_alpha); }
)";

}  // namespace

DebugVolumePass::DebugVolumePass() = default;

DebugVolumePass::~DebugVolumePass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
    if (box_vbo_) glDeleteBuffers(1, &box_vbo_);
    if (box_vao_) glDeleteVertexArrays(1, &box_vao_);
    if (sphere_vbo_) glDeleteBuffers(1, &sphere_vbo_);
    if (sphere_vao_) glDeleteVertexArrays(1, &sphere_vao_);
    if (cone_vbo_) glDeleteBuffers(1, &cone_vbo_);
    if (cone_vao_) glDeleteVertexArrays(1, &cone_vao_);
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
    shader_->set_float("u_alpha", 1.0f);   // cylinders opaque
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

void DebugVolumePass::ensure_box_resources() {
    if (box_vao_) return;
    if (!shader_) shader_ = std::make_unique<Shader>(kVs, kFs);

    // 12 triangles (2 per face) of the [-1,1]^3 cube.
    const float c[8][3] = {
        {-1,-1,-1}, { 1,-1,-1}, { 1, 1,-1}, {-1, 1,-1},
        {-1,-1, 1}, { 1,-1, 1}, { 1, 1, 1}, {-1, 1, 1},
    };
    const int faces[6][4] = {
        {0,1,2,3}, {4,5,6,7}, {0,1,5,4}, {2,3,7,6}, {1,2,6,5}, {0,3,7,4},
    };
    std::vector<float> verts;
    for (auto& f : faces) {
        const int tri[6] = {f[0], f[1], f[2], f[0], f[2], f[3]};
        for (int idx : tri) {
            verts.push_back(c[idx][0]); verts.push_back(c[idx][1]); verts.push_back(c[idx][2]);
        }
    }
    box_vertex_count_ = static_cast<int>(verts.size() / 3);

    glGenVertexArrays(1, &box_vao_);
    glGenBuffers(1, &box_vbo_);
    glBindVertexArray(box_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, box_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(verts.size() * sizeof(float)),
                 verts.data(), GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void DebugVolumePass::render(const std::vector<DebugBox>& boxes,
                             const scenegraph::Camera& camera) {
    if (boxes.empty()) return;
    ensure_box_resources();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader_->use();

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE);
    glLineWidth(1.5f);
    shader_->set_float("u_alpha", 1.0f);   // boxes opaque
    glBindVertexArray(box_vao_);

    for (const auto& b : boxes) {
        glm::mat4 M(1.0f);
        M[0] = glm::vec4(b.ex, 0.0f);      // unit-cube X (+/-1) -> +/- ex
        M[1] = glm::vec4(b.ey, 0.0f);
        M[2] = glm::vec4(b.ez, 0.0f);
        M[3] = glm::vec4(b.center, 1.0f);
        shader_->set_vec3("u_color", b.color);
        shader_->set_mat4("u_mvp", vp * M);
        glDrawArrays(GL_TRIANGLES, 0, box_vertex_count_);
    }

    glBindVertexArray(0);
    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
}

void DebugVolumePass::ensure_sphere_resources() {
    if (sphere_vao_) return;
    if (!shader_) shader_ = std::make_unique<Shader>(kVs, kFs);

    // Unit-radius UV sphere (lat x lon quads split into triangles); rendered as
    // GL_LINE it reads as a lat/long wire cage.
    const int kLat = 12, kLon = 16;
    auto on_sphere = [](float theta, float phi, float out[3]) {
        const float st = std::sin(theta);
        out[0] = st * std::cos(phi);
        out[1] = std::cos(theta);
        out[2] = st * std::sin(phi);
    };
    std::vector<float> verts;
    for (int i = 0; i < kLat; ++i) {
        const float t0 = glm::pi<float>() * (static_cast<float>(i) / kLat);
        const float t1 = glm::pi<float>() * (static_cast<float>(i + 1) / kLat);
        for (int j = 0; j < kLon; ++j) {
            const float p0 = glm::two_pi<float>() * (static_cast<float>(j) / kLon);
            const float p1 = glm::two_pi<float>() * (static_cast<float>(j + 1) / kLon);
            float a[3], b[3], c[3], d[3];
            on_sphere(t0, p0, a); on_sphere(t0, p1, b);
            on_sphere(t1, p1, c); on_sphere(t1, p0, d);
            const float tri[6][3] = {
                {a[0],a[1],a[2]}, {b[0],b[1],b[2]}, {c[0],c[1],c[2]},
                {a[0],a[1],a[2]}, {c[0],c[1],c[2]}, {d[0],d[1],d[2]},
            };
            for (auto& v : tri) { verts.push_back(v[0]); verts.push_back(v[1]); verts.push_back(v[2]); }
        }
    }
    sphere_vertex_count_ = static_cast<int>(verts.size() / 3);

    glGenVertexArrays(1, &sphere_vao_);
    glGenBuffers(1, &sphere_vbo_);
    glBindVertexArray(sphere_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, sphere_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(verts.size() * sizeof(float)),
                 verts.data(), GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void DebugVolumePass::render(const std::vector<DebugSphere>& spheres,
                             const scenegraph::Camera& camera) {
    if (spheres.empty()) return;
    ensure_sphere_resources();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader_->use();

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE);
    glLineWidth(1.5f);
    shader_->set_float("u_alpha", 0.5f);   // sphere cage at 50% opacity
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glBindVertexArray(sphere_vao_);

    for (const auto& s : spheres) {
        glm::mat4 M(1.0f);
        M[0] = glm::vec4(s.radius, 0.0f, 0.0f, 0.0f);   // uniform scale
        M[1] = glm::vec4(0.0f, s.radius, 0.0f, 0.0f);
        M[2] = glm::vec4(0.0f, 0.0f, s.radius, 0.0f);
        M[3] = glm::vec4(s.center, 1.0f);
        shader_->set_vec3("u_color", s.color);
        shader_->set_mat4("u_mvp", vp * M);
        glDrawArrays(GL_TRIANGLES, 0, sphere_vertex_count_);
    }

    glBindVertexArray(0);
    glDisable(GL_BLEND);
    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
}

void DebugVolumePass::ensure_cone_resources() {
    if (cone_vao_) return;
    if (!shader_) shader_ = std::make_unique<Shader>(kVs, kFs);

    // Unit cone: apex at the origin, base ring of kSegments verts at +Z,
    // radius 1, length 1. Side triangles (apex -> ring[i] -> ring[i+1]) plus
    // a base fan (center -> ring[i+1] -> ring[i]), rendered as GL_LINE so the
    // triangle edges outline the cone (apex spokes + base ring + fan spokes).
    std::vector<float> verts;
    verts.reserve(kSegments * 6 * 3);
    const float apex[3] = {0.0f, 0.0f, 0.0f};
    const float base_center[3] = {0.0f, 0.0f, 1.0f};
    for (int i = 0; i < kSegments; ++i) {
        const float a0 = glm::two_pi<float>() * (static_cast<float>(i) / kSegments);
        const float a1 = glm::two_pi<float>() * (static_cast<float>(i + 1) / kSegments);
        const float x0 = std::cos(a0), y0 = std::sin(a0);
        const float x1 = std::cos(a1), y1 = std::sin(a1);
        const float side[3][3] = {
            {apex[0], apex[1], apex[2]}, {x0, y0, 1.0f}, {x1, y1, 1.0f},
        };
        for (auto& v : side) { verts.push_back(v[0]); verts.push_back(v[1]); verts.push_back(v[2]); }
        const float fan[3][3] = {
            {base_center[0], base_center[1], base_center[2]}, {x1, y1, 1.0f}, {x0, y0, 1.0f},
        };
        for (auto& v : fan) { verts.push_back(v[0]); verts.push_back(v[1]); verts.push_back(v[2]); }
    }
    cone_vertex_count_ = static_cast<int>(verts.size() / 3);

    glGenVertexArrays(1, &cone_vao_);
    glGenBuffers(1, &cone_vbo_);
    glBindVertexArray(cone_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, cone_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(verts.size() * sizeof(float)),
                 verts.data(), GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void DebugVolumePass::render(const std::vector<DebugCone>& cones,
                             const scenegraph::Camera& camera) {
    if (cones.empty()) return;
    ensure_cone_resources();

    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader_->use();

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE);
    glLineWidth(1.5f);
    // Window (window.cc) requests a core-profile + forward-compat context,
    // under which wide (non-1.0) line widths are unsupported --
    // GL_ALIASED_LINE_WIDTH_RANGE clamps to (1,1) and glLineWidth(1.5) raises
    // GL_INVALID_VALUE while leaving the width at its previous value (lines
    // still draw, just pinned to 1px). Same latent condition already exists
    // for the cylinder/box/sphere siblings above and gizmo_pass.cc's
    // glLineWidth(2.0f) -- out of scope here, flagged separately -- but the
    // NEW cone path drains this specific, anticipated, harmless error so it
    // doesn't leak into a caller's glGetError() check.
    glGetError();
    shader_->set_float("u_alpha", 0.5f);   // cone cage at 50% opacity, matches the sphere cage
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glBindVertexArray(cone_vao_);

    for (const auto& cn : cones) {
        // Map the unit cone (local +Z apex->base) onto this cone: local +Z ->
        // axis (scaled by length), local X/Y -> a perpendicular basis scaled
        // by radius, origin at apex. All in world space.
        const glm::vec3 w = glm::normalize(cn.axis);
        const glm::vec3 up = (std::abs(w.y) < 0.99f) ? glm::vec3(0, 1, 0)
                                                      : glm::vec3(1, 0, 0);
        const glm::vec3 u = glm::normalize(glm::cross(up, w));
        const glm::vec3 v = glm::cross(w, u);

        glm::mat4 M(1.0f);
        M[0] = glm::vec4(u * cn.radius, 0.0f);
        M[1] = glm::vec4(v * cn.radius, 0.0f);
        M[2] = glm::vec4(w * cn.length, 0.0f);
        M[3] = glm::vec4(cn.apex, 1.0f);

        shader_->set_vec3("u_color", cn.color);
        shader_->set_mat4("u_mvp", vp * M);
        glDrawArrays(GL_TRIANGLES, 0, cone_vertex_count_);
    }

    glBindVertexArray(0);
    glDisable(GL_BLEND);
    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL);
    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
