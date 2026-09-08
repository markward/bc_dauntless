// native/src/voxel/include/voxel/distance_field.h
#pragma once

#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

#include <voxel/voxelize.h>

namespace voxel {

/// Unsigned distance from `p` to triangle `t`. Always >= 0, always finite --
/// a degenerate (zero-area) triangle collapses to its vertex rather than
/// dividing by zero.
float point_triangle_distance(const glm::vec3& p, const Tri& t);

}  // namespace voxel
