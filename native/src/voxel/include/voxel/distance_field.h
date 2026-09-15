// native/src/voxel/include/voxel/distance_field.h
#pragma once

#include <cstddef>
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

/// Ceiling on the number of cells in one baked lattice. The grid is derived
/// from hull extent / cell with nothing else bounding it, and BC's FedStarbase
/// (19300 x 19336 x 32136 model units) at the authored resolution's 7.5-unit
/// cell is 28.7 BILLION cells -- an allocation that trapped inside CEF's
/// operator-new shim the moment E1M1 warped the player to Starbase 12. Above
/// this budget the baker coarsens the cell uniformly until the lattice fits
/// (see distance_field_from_tris), which is what BC's own authored volumes
/// do: every shipped station _vox.nif uses cell 85 against the authored 15,
/// and the largest volume in the whole corpus is 206k cells.
///
/// 2^24 sits just above the largest lattice any hull with a BC _vox produces
/// at the authored resolution (SpaceFacility / FedOutpost: 153 x 283 x 310 =
/// 13.4M, live-verified), so every hull BC voxelised bakes exactly as before
/// and only FedStarbase (350x larger than the next hull) is coarsened.
///
/// This is a bake INPUT: changing it changes the output for hulls above the
/// old or new value, so bump dhv.h's kBakerVersion in the same change.
inline constexpr std::size_t kMaxFieldCells = std::size_t{1} << 24;

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
/// An inclusive box of lattice cells, the unit every incremental consumer of
/// a DistanceField works in: the brushes return the box they wrote, the atlas
/// upload re-encodes only that box, and the severance check floods from its
/// shell. Empty (lo > hi) means "no cell" -- the default, and what a no-op
/// brush returns -- so a consumer can `include()` boxes blindly and test
/// `empty()` once at the end.
struct CellBox {
    glm::ivec3 lo{1, 1, 1};
    glm::ivec3 hi{0, 0, 0};

    bool empty() const { return lo.x > hi.x || lo.y > hi.y || lo.z > hi.z; }
    bool contains(const glm::ivec3& c) const {
        return !empty() && c.x >= lo.x && c.y >= lo.y && c.z >= lo.z &&
               c.x <= hi.x && c.y <= hi.y && c.z <= hi.z;
    }
    /// Grow to the union with `other`; an empty `other` changes nothing and
    /// an empty `this` becomes `other`.
    void include(const CellBox& other) {
        if (other.empty()) return;
        if (empty()) { *this = other; return; }
        lo = glm::min(lo, other.lo);
        hi = glm::max(hi, other.hi);
    }
    /// Cell count, 0 when empty.
    std::size_t volume() const {
        if (empty()) return 0;
        return static_cast<std::size_t>(hi.x - lo.x + 1)
             * static_cast<std::size_t>(hi.y - lo.y + 1)
             * static_cast<std::size_t>(hi.z - lo.z + 1);
    }
};

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

    /// True when this field holds no data -- the documented sentinel
    /// distance_field_from_tris() returns for a hull with no triangles
    /// (missing source, unparseable NIF, or a genuinely empty mesh), and what
    /// HullVolumeCache::get serves (and caches) for a hull it cannot read at
    /// all. Callers MUST check this before calling distance_at(): index()
    /// still resolves to 0 for a default-constructed (dims == {0,0,0})
    /// field, and dist[0] on an empty vector is out of bounds.
    bool empty() const { return dist.empty(); }

    /// Distance at cell (x,y,z), in model units, negative inside the hull.
    /// UNDEFINED BEHAVIOUR if this field is empty() -- see empty()'s doc.
    /// Callers must check empty() first (or otherwise know the field was
    /// baked from a non-empty triangle set) before calling this.
    float distance_at(int x, int y, int z) const {
        return static_cast<float>(dist[index(x, y, z)]) * scale;
    }
};

/// Build a signed distance field for a hull triangle soup at the given cell
/// size. Grid is the tris' AABB plus a margin sized to the FULL outside band
/// (symmetric, per axis, derived from `band_cells` -- never a fixed cell
/// count) so that a point up to `band_cells` cells beyond the hull surface,
/// on any face, still lands inside the grid rather than off its edge. Sign
/// comes from flood fill (BC hulls are 99.5%+ manifold -- MEASURED -- so this
/// is sound); magnitude from the nearest triangle within `band_cells`,
/// saturating beyond. Returns an empty field when `tris` is empty or `cell`
/// is degenerate.
///
/// `max_cells` bounds the lattice: when the grid the requested `cell` implies
/// (margins included) would exceed it, `cell` is scaled up UNIFORMLY -- every
/// axis by the same factor, so an isotropic request stays isotropic -- to the
/// smallest cell whose grid fits, and the returned field's `cell` reports
/// what was actually used. Consumers must always read the field's own `cell`
/// rather than recomputing it from the request.
DistanceField distance_field_from_tris(const std::vector<Tri>& tris,
                                       glm::vec3 cell,
                                       float band_cells = kDefaultBandCells,
                                       std::size_t max_cells = kMaxFieldCells);

}  // namespace voxel
