#pragma once
#include <array>
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>

namespace voxel {

/// Maps an interior-node fill cell (i,j,k) on the (nx-1,ny-1,nz-1) lattice to
/// the first plane-palette index found at that cell, as decoded from the
/// NiBinaryVoxelData `bytes2` index tree + 6-byte leaf records (§6/§7 of
/// docs/original_game_reference/engine/nibinaryvoxeldata-format-v3.1.md).
class PlaneIndexMap {
public:
    /// First plane-palette index for interior-node cell (i,j,k), or -1 if the
    /// cell is out of range or has no mapped leaf record.
    int first_plane(int i, int j, int k) const;

    glm::ivec3 dims_in{0};        // interior-node dims (nx-1, ny-1, nz-1)
    std::vector<int> cell_plane;  // flat, X-fastest: i + dnx*(j + dny*k); -1 = unmapped
};

/// Parse the `bytes2` blob into a PlaneIndexMap by descending the head index
/// tree (Z->Y->X range-coded nodes, §6) to leaf runs and recording each cell's
/// first leaf planeIndex (§7). `grid_dims` are the header shorts (nx,ny,nz);
/// `trailer` is the five-word §8 trailer.
PlaneIndexMap build_plane_index(const std::vector<std::uint8_t>& bytes2,
                                glm::ivec3 grid_dims /* (nx,ny,nz) */,
                                const std::array<std::uint32_t, 5>& trailer);

}  // namespace voxel
