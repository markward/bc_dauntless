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
    std::vector<glm::ivec3> cell_list;
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

}  // namespace voxel
