// native/src/voxel/include/voxel/voxelize.h
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <voxel/volume.h>

namespace assets { struct Model; }

namespace voxel {

struct Tri { glm::vec3 a, b, c; };

/// Flatten every mesh in the model into one triangle soup, each vertex
/// transformed by its node's accumulated world transform (root -> node).
/// Meshes that have no retained CPU data (cpu_data() == nullopt) are skipped.
std::vector<Tri> collect_hull_triangles(const assets::Model& model);

}  // namespace voxel
