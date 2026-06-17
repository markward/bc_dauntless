#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <glm/glm.hpp>
#include <voxel/volume.h>

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

// An indexed triangle mesh (CPU-side, GL-free).
//
// WINDING: triangle indices wind INWARD (toward the hull interior) while vertex
// `normals` point OUTWARD (hull-exterior, from the palette planes) — the two are
// intentionally opposite. The breach interior pass therefore renders this mesh
// DOUBLE-SIDED (cull disabled) and triplanar-textures it (normal used only via
// abs()/faceforward), so winding is moot. A consumer that backface-culls must
// flip indices or disable culling.
struct Mesh {
    std::vector<glm::vec3> positions;
    std::vector<glm::vec3> normals;
    std::vector<std::uint32_t> indices;   // triangles (inward winding — see above)
};

// Path-B dual-contouring extractor (§10 of the NiBinaryVoxelData v3.1 spec).
//
// Turns the 0..127 scalar fill field of `fill` into a triangle mesh with sharp
// hull facets, using `palette` (Hesse-form planes (n̂.xyz, d) in the same GU
// body frame as the fill) as the sharp-feature (Hermite) data.
//
// We do NOT use BC's bytes2 leaf index. Instead, per surface cell we pick the
// nearest palette plane(s) ourselves by point-to-plane distance |n̂·p − d|.
//
//   1. A cell straddles the surface if some of its 8 corner fill values are
//      < isovalue and some >= isovalue.
//   2. The cell's surface point p = average of the linearly-interpolated
//      isosurface edge-crossing points on the cell's 12 edges (fallback: cell
//      center).
//   3. Match palette planes with |n̂·p − d| below ~1 cell size; keep up to a
//      few with distinct normals (sharp corner). If none match, fall back to a
//      single plane from the fill gradient through p so the mesh stays
//      watertight.
//   4. solve_qef(matched, fallback=p) → the cell vertex.
//
// Quads: for each interior grid edge that crosses the isovalue, emit a quad
// (two triangles) connecting the up-to-4 incident cells' vertices, oriented by
// the edge's sign direction.
Mesh dual_contour(const VoxelVolume& fill, int isovalue,
                  const std::vector<glm::vec4>& palette);

// Debug: dump a Mesh to a Wavefront OBJ (v / vn / f). Best-effort; silently
// does nothing if the file can't be opened.
void write_obj(const Mesh& m, const std::string& path);

}  // namespace voxel
