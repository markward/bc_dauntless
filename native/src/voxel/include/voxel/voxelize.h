// native/src/voxel/include/voxel/voxelize.h
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <voxel/volume.h>

namespace assets { struct Model; }
namespace nif { struct File; struct NiBinaryVoxelData; }

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

/// Voxelize a triangle soup into a grid with EXPLICITLY given dims/origin/cell.
/// Builds a VoxelVolume from the supplied grid parameters (does not compute a
/// bbox; uses the caller's lattice as-is), zeroes occ, runs surface_voxelize
/// then solidify, and returns the result. This allows matching an external
/// reference lattice (e.g. from from_nif_voxel_data) exactly.
VoxelVolume voxelize_into(const std::vector<Tri>& tris,
                          glm::ivec3 dims,
                          glm::vec3  origin,
                          glm::vec3  cell);

/// Decode a NiBinaryVoxelData block into a VoxelVolume.
/// Reads the 7-bit fill field from raw_voxel_payload (LSB-plane-first bit
/// packing over the (nx-1)*(ny-1)*(nz-1) interior-node lattice) and stores
/// the 0–127 fill value per node in occ (not thresholded; solid() treats
/// nonzero as solid). Returns an empty volume if the grid is degenerate or
/// the payload is too small.
VoxelVolume from_nif_voxel_data(const nif::NiBinaryVoxelData& vd);

/// GL-free NiNode-tree walk: collect every world-transformed triangle from
/// every NiTriShapeData in the NIF into a triangle soup. Walks the scene
/// from the root block (or all top-level blocks if no root is set). Uses the
/// same T*R*S accumulation as voxel_inspect's hull_tris(). No GL or assets
/// dependency; links only against `nif`. Used by voxel_inspect and by tests
/// that need hull geometry without a renderer.
std::vector<Tri> collect_hull_triangles_from_nif(const nif::File& f);

/// Voxelize a raw triangle soup into a solid volume at the given grid
/// resolution. Computes the tris' AABB, derives a 1-voxel margin lattice, then
/// calls voxelize_into. Returns an all-empty volume (with the given dims) when
/// tris is empty.
VoxelVolume voxelize_tris(const std::vector<Tri>& tris, glm::ivec3 dims);

/// Select the SOLID voxels of `v` whose body-frame centre lies within `radius`
/// of `center_body` (both in the NIF/model body frame; radius in model units).
/// Returns one vec4 per matching voxel: `xyz` = the voxel's body-frame centre
/// (origin + (i+0.5)*cell), `w` = a stable per-voxel seed (the flat occ index
/// as a float) the breach shader hashes into a colour. Iterates only the voxel
/// index bounding box of the sphere (clamped to dims), never the whole grid.
/// Returns an empty vector when the volume is degenerate or nothing matches.
std::vector<glm::vec4> select_breach_voxels(const VoxelVolume& v,
                                            glm::vec3 center_body,
                                            float radius);

}  // namespace voxel
