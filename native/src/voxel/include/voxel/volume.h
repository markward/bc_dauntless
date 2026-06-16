#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>

namespace voxel {

/// Solid voxel volume. Occupancy is one byte per voxel (1 = solid), indexed
/// x-fastest then y then z. In-memory representation; the on-disk BC format
/// is bit-packed and decoded into this by from_nif_voxel_data().
struct VoxelVolume {
    glm::ivec3 dims{0};        // nx, ny, nz
    glm::vec3  origin{0.f};    // body-frame position of voxel (0,0,0) min corner
    glm::vec3  cell{1.f};      // cell size per axis
    std::vector<std::uint8_t> occ;

    std::size_t index(int x, int y, int z) const {
        return static_cast<std::size_t>(x)
             + static_cast<std::size_t>(dims.x) * (y + static_cast<std::size_t>(dims.y) * z);
    }
    bool solid(int x, int y, int z) const { return occ[index(x, y, z)] != 0; }
    void set(int x, int y, int z, bool v) { occ[index(x, y, z)] = v ? 1 : 0; }
    std::size_t solid_count() const;
};

}  // namespace voxel
