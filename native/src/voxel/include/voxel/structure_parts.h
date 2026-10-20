// native/src/voxel/include/voxel/structure_parts.h
//
// SPIKE (damage redesign): detect a hull's structural PARTS from its solid
// shape, so the plating layer's skeleton can follow the hull's contours
// (radial spokes + rings on a saucer, hoops + stringers on a nacelle) instead
// of the body axes. Never reads polygon edges: the hull is voxelized, every
// solid voxel gets its depth inside the hull (exact Euclidean distance
// transform). Depth ridges give the hull's medial CORE; each core voxel's
// local shape (sheet / line / blob, with its facing) splits the core into
// regions that agree, every solid voxel joins its nearest core region, and
// each region is classified by its principal axes as a disc, a cylinder or a
// box. A saucer (sheet facing up) and a neck (sheet facing sideways) split
// even where they are equally thick.
#pragma once
#include <cstdint>
#include <vector>

#include <glm/glm.hpp>
#include <voxel/volume.h>
#include <voxel/voxelize.h>

namespace voxel {

enum class PartKind : int { Box = 0, Disc = 1, Cylinder = 2 };

struct StructurePart {
    PartKind  kind = PartKind::Box;
    glm::vec3 centre{0.0f};       // body frame, model units
    /// Orthonormal, right-handed. Disc: [0] = disc normal (thin axis),
    /// [1],[2] in-plane. Cylinder: [0] = long axis. Box: principal axes,
    /// largest spread first.
    glm::vec3 axis[3] = {glm::vec3(1, 0, 0), glm::vec3(0, 1, 0), glm::vec3(0, 0, 1)};
    glm::vec3 half_extent{0.0f};  // along axis[0..2], model units
    int       voxels = 0;
    float     peak_depth = 0.0f;  // deepest voxel, model units
    glm::vec3 spread{0.0f};       // principal std-devs, largest first
};

struct StructureParams {
    int   long_axis_cells = 128;  // grid resolution along the hull's longest side
    float medial_min_depth = 1.2f; // cells: core voxels must sit at least this deep
    float shape_radius_k = 2.0f;   // local-shape box half-size = k * depth + 2 cells...
    int   shape_radius_max = 10;   // ...capped here
    float line_ratio  = 0.20f;     // core is a LINE (tube) when l2/l1 < this
    float sheet_ratio = 0.20f;     // core is a SHEET when l3/l2 < this
    float orient_tol_deg = 25.0f;  // neighbouring core voxels join within this angle
    float merge_axis_tol_deg = 20.0f; // pieces merge if the joined fit keeps kind + axis
    float disc_claim_k = 1.8f;    // a disc claims voxels within k x its half-thickness
    float min_fraction = 0.005f;  // lobes smaller than this share of the solid merge away
    // Classification on principal std-devs s1 >= s2 >= s3:
    float disc_flat  = 0.45f;     // disc needs s3/s2 below this...
    float disc_round = 0.60f;     // ...and s2/s1 above this
    float cyl_long   = 0.60f;     // cylinder needs s2/s1 below this...
    float cyl_round  = 0.55f;     // ...and s3/s2 above this
};

struct StructureSegmentation {
    VoxelVolume                vol;     // binary solid
    std::vector<float>         depth;   // per voxel, cells (0 outside)
    std::vector<std::int16_t>  label;   // per voxel, -1 outside, else index into parts
    std::vector<StructurePart> parts;
};

/// Detect structural parts of a triangle soup (body frame, model units).
StructureSegmentation detect_structure_parts(const std::vector<Tri>& tris,
                                             const StructureParams& p = {});

/// Exact squared Euclidean distance transform (Felzenszwalb-Huttenlocher),
/// in cells: each solid voxel gets the distance to the nearest EMPTY voxel
/// centre. Exposed for tests.
std::vector<float> solid_depth(const VoxelVolume& v);

}  // namespace voxel
