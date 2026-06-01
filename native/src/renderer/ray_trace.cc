// native/src/renderer/ray_trace.cc
#include "renderer/ray_trace.h"

#include <limits>
#include <vector>

#include <assets/mesh.h>
#include <assets/model.h>
#include <glm/gtc/matrix_inverse.hpp>

#include "renderer/aabb.h"

namespace renderer {

std::optional<float> intersect_triangle(
    glm::vec3 origin, glm::vec3 direction, float max_dist,
    glm::vec3 v0, glm::vec3 v1, glm::vec3 v2)
{
    constexpr float kEps = 1e-7f;
    const glm::vec3 e1 = v1 - v0;
    const glm::vec3 e2 = v2 - v0;
    const glm::vec3 p  = glm::cross(direction, e2);
    const float det = glm::dot(e1, p);
    if (std::abs(det) < kEps) return std::nullopt;
    const float inv_det = 1.0f / det;
    const glm::vec3 s = origin - v0;
    const float u = glm::dot(s, p) * inv_det;
    if (u < 0.0f || u > 1.0f) return std::nullopt;
    const glm::vec3 q = glm::cross(s, e1);
    const float v = glm::dot(direction, q) * inv_det;
    if (v < 0.0f || u + v > 1.0f) return std::nullopt;
    const float t = glm::dot(e2, q) * inv_det;
    if (t < kEps || t > max_dist) return std::nullopt;
    return t;
}

namespace {

struct WorldSphere { glm::vec3 center; float radius; };

WorldSphere compute_world_sphere(const assets::Model& model,
                                 const glm::mat4& instance_world) {
    Aabb local = compute_model_aabb(model);
    glm::vec3 c_world = glm::vec3(instance_world * glm::vec4(local.center, 1.0f));
    glm::vec3 he = local.half_extents;
    glm::mat3 m3 = glm::mat3(instance_world);
    glm::vec3 he_world(
        std::abs(m3[0][0]) * he.x + std::abs(m3[1][0]) * he.y + std::abs(m3[2][0]) * he.z,
        std::abs(m3[0][1]) * he.x + std::abs(m3[1][1]) * he.y + std::abs(m3[2][1]) * he.z,
        std::abs(m3[0][2]) * he.x + std::abs(m3[1][2]) * he.y + std::abs(m3[2][2]) * he.z);
    return {c_world, glm::length(he_world)};
}

bool segment_hits_sphere(glm::vec3 origin, glm::vec3 direction, float max_dist,
                         glm::vec3 center, float radius) {
    if (radius <= 0.0f) return false;
    const glm::vec3 oc = origin - center;
    const float b = glm::dot(oc, direction);
    const float c = glm::dot(oc, oc) - radius * radius;
    if (c <= 0.0f) return true;
    if (b >= 0.0f) return false;
    const float disc = b * b - c;
    if (disc < 0.0f) return false;
    const float t_enter = -b - std::sqrt(disc);
    return t_enter <= max_dist;
}

std::vector<glm::mat4> build_node_world(const assets::Model& model) {
    std::vector<glm::mat4> nw(model.nodes.size(), glm::mat4(1.0f));
    if (model.nodes.empty()) return nw;
    nw[model.root_node] = model.nodes[model.root_node].local_transform;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            nw[i] = nw[node.parent_index] * node.local_transform;
        }
    }
    return nw;
}

}  // namespace

std::optional<RayHit> ray_trace_instance(
    const assets::Model& model,
    const glm::mat4& instance_world,
    glm::vec3 origin,
    glm::vec3 direction,
    float max_dist)
{
    if (model.nodes.empty() || model.meshes.empty()) return std::nullopt;

    const WorldSphere sphere = compute_world_sphere(model, instance_world);
    if (sphere.radius > 0.0f &&
        !segment_hits_sphere(origin, direction, max_dist,
                             sphere.center, sphere.radius)) {
        return std::nullopt;
    }

    const std::vector<glm::mat4> node_world = build_node_world(model);

    float best_t = std::numeric_limits<float>::infinity();
    glm::vec3 best_point(0.0f);
    glm::vec3 best_normal(0.0f);
    bool have_hit = false;

    for (std::size_t ni = 0; ni < model.nodes.size(); ++ni) {
        const auto& node = model.nodes[ni];
        for (int mesh_idx : node.meshes) {
            if (mesh_idx < 0 ||
                mesh_idx >= static_cast<int>(model.meshes.size())) continue;
            const auto& cpu_opt = model.meshes[mesh_idx].cpu_data();
            if (!cpu_opt) continue;
            const auto& cpu = *cpu_opt;
            if (cpu.indices.empty() || cpu.vertices.empty()) continue;

            const glm::mat4 mesh_world = instance_world * node_world[ni];
            const glm::mat4 mesh_world_inv = glm::inverse(mesh_world);
            const glm::vec3 origin_local =
                glm::vec3(mesh_world_inv * glm::vec4(origin, 1.0f));
            const glm::vec3 dir_local =
                glm::vec3(mesh_world_inv * glm::vec4(direction, 0.0f));
            const float dir_local_len = glm::length(dir_local);
            if (dir_local_len < 1e-12f) continue;
            const glm::vec3 dir_local_unit = dir_local / dir_local_len;
            const float max_dist_local = max_dist * dir_local_len;

            const glm::mat3 normal_matrix =
                glm::transpose(glm::mat3(mesh_world_inv));

            for (std::size_t i = 0; i + 2 < cpu.indices.size(); i += 3) {
                const glm::vec3 v0 = cpu.vertices[cpu.indices[i + 0]].position;
                const glm::vec3 v1 = cpu.vertices[cpu.indices[i + 1]].position;
                const glm::vec3 v2 = cpu.vertices[cpu.indices[i + 2]].position;
                const auto t_local = intersect_triangle(
                    origin_local, dir_local_unit, max_dist_local, v0, v1, v2);
                if (!t_local) continue;
                const float t_world = *t_local / dir_local_len;
                if (t_world >= best_t) continue;
                best_t = t_world;
                const glm::vec3 hit_local =
                    origin_local + dir_local_unit * (*t_local);
                best_point = glm::vec3(mesh_world * glm::vec4(hit_local, 1.0f));
                const glm::vec3 n_local =
                    glm::normalize(glm::cross(v1 - v0, v2 - v0));
                best_normal = glm::normalize(normal_matrix * n_local);
                have_hit = true;
            }
        }
    }

    if (!have_hit) return std::nullopt;
    if (glm::dot(best_normal, direction) > 0.0f) best_normal = -best_normal;
    return RayHit{best_point, best_normal, best_t};
}

}  // namespace renderer
