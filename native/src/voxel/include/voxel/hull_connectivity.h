// native/src/voxel/include/voxel/hull_connectivity.h
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

#include <voxel/distance_field.h>

namespace voxel {

/// One detached piece of hull: every occupied cell NOT reachable from the
/// main body's seed by 6-connectivity.
struct HullComponent {
    std::uint32_t label = 0;                 // 1..N (0 is the main body)
    std::size_t   cells = 0;
    glm::vec3     centroid_body{0.0f};       // model units, body frame
    glm::vec3     bounds_min_body{0.0f};     // cell-centre extents
    glm::vec3     bounds_max_body{0.0f};
    std::vector<glm::ivec3> cell_list;
};

struct ConnectivityResult {
    std::size_t main_body_cells = 0;
    std::vector<HullComponent> detached;     // empty when nothing severed
};

/// Connected components of the hull that remains after damage.
///
/// A cell is OCCUPIED iff `baked.dist <= 0` (inside the authored hull) AND
/// `damage.dist <= 0` (not carved -- the same "not past the iso" test the
/// hull clip makes, in stored int8 units). The main body is the 6-connected
/// region containing the seed: the occupied cell whose centre is nearest the
/// body-frame origin. Everything occupied but unreached is a detached
/// component.
///
/// Both fields MUST share one lattice (dims/origin/cell). The per-instance
/// damage field copies the baked field's lattice by construction
/// (renderer/instance_field_cache.cc), so a mismatch is a caller bug: this
/// returns an empty result rather than reading out of bounds.
ConnectivityResult hull_connectivity(const DistanceField& baked,
                                     const DistanceField& damage);

}  // namespace voxel
