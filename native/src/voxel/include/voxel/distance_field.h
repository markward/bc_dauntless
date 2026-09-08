// native/src/voxel/include/voxel/distance_field.h
#pragma once

#include <cstdint>

#include <glm/glm.hpp>

#include <voxel/voxelize.h>

namespace voxel {

/// Unsigned distance from `p` to triangle `t`. Always >= 0, always finite --
/// a degenerate (zero-area) triangle collapses to its vertex rather than
/// dividing by zero.
float point_triangle_distance(const glm::vec3& p, const Tri& t);

/// Default half-width of the accurate band, in cells. Beyond this the stored
/// value saturates: no consumer probes deeper than a few cells, so the exact
/// far-field distance carries no information anyone uses.
inline constexpr float kDefaultBandCells = 4.0f;

/// Signed distance field over a uniform body-frame lattice, model units.
///
/// NEGATIVE inside the hull, POSITIVE outside. One signed byte per cell in
/// units of `scale`, saturating at +-127.
///
/// Why signed distance rather than occupancy: every damage threshold becomes a
/// real LENGTH instead of a cell count. The cavity-depth threshold that made
/// the Warbird cut breaches into nothing was expressed in cells, and the
/// Warbird's authored cells are 25 model units against the fleet's 15 -- so
/// "2 cells" silently meant 50 units on one ship and 30 on every other.
struct DistanceField {
    glm::ivec3 dims{0};
    glm::vec3  origin{0.0f};   // body-frame position of cell (0,0,0)'s min corner
    glm::vec3  cell{1.0f};     // model units per cell
    float      scale = 1.0f;   // model units per quantisation step
    std::vector<std::int8_t> dist;

    std::size_t index(int x, int y, int z) const {
        return static_cast<std::size_t>(x)
             + static_cast<std::size_t>(dims.x)
             * (static_cast<std::size_t>(y)
             +  static_cast<std::size_t>(dims.y) * static_cast<std::size_t>(z));
    }
    float distance_at(int x, int y, int z) const {
        return static_cast<float>(dist[index(x, y, z)]) * scale;
    }
};

/// Build a signed distance field for a hull triangle soup at the given cell
/// size. Grid is the tris' AABB plus a 2-cell margin. Sign comes from flood
/// fill (BC hulls are 99.5%+ manifold -- MEASURED -- so this is sound);
/// magnitude from the nearest triangle within `band_cells`, saturating beyond.
/// Returns an empty field when `tris` is empty or `cell` is degenerate.
DistanceField distance_field_from_tris(const std::vector<Tri>& tris,
                                       glm::vec3 cell,
                                       float band_cells = kDefaultBandCells);

}  // namespace voxel
