#pragma once
#include <vector>
#include <glm/glm.hpp>

namespace voxel {

// A plane in Hesse normal form: { p : dot(n, p) == d }, |n| == 1.
struct Plane {
    glm::vec3 n;
    float d;
};

// Minimize sum_i (dot(n_i, v) - d_i)^2 with Tikhonov regularization toward
// `fallback` for stability when the system is under-constrained (e.g. fewer
// than 3 independent planes). Returns `fallback` immediately when planes is
// empty.
glm::vec3 solve_qef(const std::vector<Plane>& planes, glm::vec3 fallback);

}  // namespace voxel
