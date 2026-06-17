#include <voxel/volume.h>
#include <cassert>

namespace voxel {

std::size_t VoxelVolume::solid_count() const {
    std::size_t n = 0;
    for (auto b : occ) n += (b != 0);
    return n;
}

double iou(const VoxelVolume& a, const VoxelVolume& b) {
    assert(a.dims == b.dims && "iou: volume dims must match");
    if (a.dims != b.dims) return -1.0;
    std::size_t inter = 0, uni = 0;
    const std::size_t n = a.occ.size();
    for (std::size_t i = 0; i < n; ++i) {
        bool sa = (a.occ[i] != 0);
        bool sb = (b.occ[i] != 0);
        inter += (sa && sb);
        uni   += (sa || sb);
    }
    return uni ? double(inter) / double(uni) : 1.0;
}

}  // namespace voxel
