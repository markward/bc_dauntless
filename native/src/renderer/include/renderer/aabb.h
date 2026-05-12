// native/src/renderer/include/renderer/aabb.h
#pragma once

#include <span>
#include <vector>
#include <glm/glm.hpp>

namespace renderer {

struct Aabb {
    glm::vec3 center{0.0f};
    glm::vec3 half_extents{0.0f};
};

Aabb compute_aabb(std::span<const glm::vec3> positions);

inline Aabb compute_aabb(const std::vector<glm::vec3>& v) {
    return compute_aabb(std::span<const glm::vec3>(v));
}

}  // namespace renderer
