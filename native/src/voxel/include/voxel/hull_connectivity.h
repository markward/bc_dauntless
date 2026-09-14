// native/src/voxel/include/voxel/hull_connectivity.h
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

#include <voxel/distance_field.h>

namespace voxel {

/// One detached piece of hull: a 6-connected component of the occupied
/// cells that is not the main body.
struct HullComponent {
    std::uint32_t label = 0;                 // 1..N, lattice scan order; the
                                             // main body's label is absent
    std::size_t   cells = 0;
    glm::vec3     centroid_body{0.0f};       // model units, body frame
    glm::vec3     bounds_min_body{0.0f};     // cell-centre extents
    glm::vec3     bounds_max_body{0.0f};
    std::vector<glm::ivec3> cell_list;       // DETACHED components only --
                                             // the main body's is never
                                             // read, and on a Warbird it was
                                             // 185k ivec3s per check
};

struct ConnectivityResult {
    std::size_t   main_body_cells = 0;
    std::uint32_t main_body_label = 0;       // 0 when nothing is occupied
    std::vector<HullComponent> detached;     // empty when nothing severed
};

/// Connected components of the hull that remains after damage.
///
/// A cell is OCCUPIED iff `baked.dist <= 0` (inside the authored hull) AND
/// `damage.dist <= 0` (not carved -- the same "not past the iso" test the
/// hull clip makes, in stored int8 units). Every occupied cell is labelled
/// into a 6-connected component first, with no privileged seed; the main
/// body is then the LARGEST component (ties: lowest label, i.e. first in
/// lattice scan order), and every other component is detached. Seeding at
/// the cell nearest the origin was wrong: a cascade capsule that hollows
/// the centre leaves a small fragment there, and the whole remaining hull
/// would have spawned as a chunk of it.
///
/// Both fields MUST share one lattice (dims/origin/cell). The per-instance
/// damage field copies the baked field's lattice by construction
/// (renderer/instance_field_cache.cc), so a mismatch is a caller bug: this
/// returns an empty result rather than reading out of bounds.
ConnectivityResult hull_connectivity(const DistanceField& baked,
                                     const DistanceField& damage);

/// What hull_severance_local can say about one carve.
enum class Severance {
    kConnected,   // PROVEN: nothing was cut off by the carve in `box`
    kUnknown      // not proven either way -- run hull_connectivity
};

/// Default visit budget for hull_severance_local, as a multiple of the
/// (one-cell-expanded) box volume. A carve on solid hull reconnects its
/// shell within a handful of cells; a hit on a pylon whose sides rejoin
/// only via the saucer walks far more than this, trips the cap and takes
/// the full BFS -- correct, just not cheap.
inline constexpr std::size_t kSeveranceVisitFactor = 8;

/// Local answer to "did the carve inside `box` sever anything?", so the
/// full-lattice BFS runs only when it might have (it was 18 ms per check on
/// a Galaxy at -O0, 68 ms on a Warbird, at 2 checks/s per damaged ship).
///
/// Takes every occupied cell in `box` grown by one cell -- the shell around
/// the carve plus whatever survived inside it -- and floods from one of them
/// over occupied cells (6-connected, anywhere in the lattice). If every
/// target is reached within `visit_cap` visited cells, the material on all
/// sides of the carve is still one piece and nothing inside it is an
/// island: kConnected. Anything else is kUnknown.
///
/// Sound ONLY under the invariant the split path maintains: before this
/// carve, the damage field held exactly ONE component (every earlier
/// detachment was split out or removed). The first check on a fresh
/// instance must therefore be the full BFS -- a hull whose BAKE is several
/// components would otherwise never shed the extra ones.
///
/// `visit_cap` 0 means kSeveranceVisitFactor x the expanded box's volume --
/// and a box so large that this budget would cover the lattice (a cascade
/// capsule across the hull) is kUnknown at once, since there is nothing
/// local left to exploit. An empty box or a lattice mismatch is kUnknown
/// (never a false kConnected); no occupied cell near the box is kConnected.
Severance hull_severance_local(const DistanceField& baked,
                               const DistanceField& damage,
                               const CellBox& box,
                               std::size_t visit_cap = 0);

}  // namespace voxel
