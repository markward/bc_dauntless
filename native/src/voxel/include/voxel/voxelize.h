// native/src/voxel/include/voxel/voxelize.h
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <voxel/volume.h>

namespace assets { struct Model; }
namespace nif { struct NiBinaryVoxelData; }

namespace voxel {

struct Tri { glm::vec3 a, b, c; };

/// Flatten every mesh in the model into one triangle soup, each vertex
/// transformed by its node's accumulated world transform (root -> node).
/// Meshes that have no retained CPU data (cpu_data() == nullopt) are skipped.
std::vector<Tri> collect_hull_triangles(const assets::Model& model);

/// Rasterize each triangle into the grid, marking every voxel the triangle
/// overlaps as solid. Voxels outside [0,dims) are skipped.
void surface_voxelize(VoxelVolume& v, const std::vector<Tri>& tris);

/// Solid-fill the interior: BFS-flood "exterior empty" from all border
/// voxels through empty space; every voxel never reached is marked solid.
/// Robust to small surface leaks (a leak lets the flood bleed inward).
void solidify(VoxelVolume& v);

/// Voxelize a hull into a solid volume at the given grid resolution.
/// Computes a tight body-frame AABB (with a 1-voxel margin), surface-
/// rasterizes the triangle soup, then flood-fill solidifies.
/// The dims parameter is provisional; a later task replaces it with the
/// BC-recovered resolution rule.
VoxelVolume voxelize(const assets::Model& model, glm::ivec3 dims);

/// Decode a NiBinaryVoxelData block into a VoxelVolume.
/// Reads the 7-bit fill field from raw_voxel_payload (LSB-plane-first bit
/// packing over the (nx-1)*(ny-1)*(nz-1) interior-node lattice) and stores
/// the 0–127 fill value per node in occ (not thresholded; solid() treats
/// nonzero as solid). Returns an empty volume if the grid is degenerate or
/// the payload is too small.
VoxelVolume from_nif_voxel_data(const nif::NiBinaryVoxelData& vd);

}  // namespace voxel
