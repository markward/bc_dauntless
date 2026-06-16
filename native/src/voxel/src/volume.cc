#include <voxel/volume.h>

namespace voxel {

std::size_t VoxelVolume::solid_count() const {
    std::size_t n = 0;
    for (auto b : occ) n += (b != 0);
    return n;
}

}  // namespace voxel
