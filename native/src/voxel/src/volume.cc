#include <voxel/volume.h>
#include <voxel/voxelize.h>
#include <algorithm>
#include <cassert>
#include <cmath>

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

std::vector<glm::vec4> select_breach_voxels(const VoxelVolume& v,
                                            glm::vec3 center_body,
                                            float radius) {
    std::vector<glm::vec4> out;
    if (v.dims.x <= 0 || v.dims.y <= 0 || v.dims.z <= 0 || v.occ.empty() ||
        radius <= 0.0f) {
        return out;
    }
    if (v.cell.x <= 0.0f || v.cell.y <= 0.0f || v.cell.z <= 0.0f) return out;

    // Index bounding box of the sphere: convert centre±radius to index range,
    // clamp to [0, dims). A solid voxel (i,j,k) has centre
    //   origin + (vec3(i,j,k)+0.5) * cell,
    // so i = (center.x - radius - origin.x) / cell.x - 0.5 at the low end.
    auto lo_idx = [&](float c, float o, float cell) {
        return static_cast<int>(std::floor((c - radius - o) / cell - 0.5f));
    };
    auto hi_idx = [&](float c, float o, float cell) {
        return static_cast<int>(std::ceil((c + radius - o) / cell - 0.5f));
    };
    const int x0 = std::max(0, lo_idx(center_body.x, v.origin.x, v.cell.x));
    const int x1 = std::min(v.dims.x - 1, hi_idx(center_body.x, v.origin.x, v.cell.x));
    const int y0 = std::max(0, lo_idx(center_body.y, v.origin.y, v.cell.y));
    const int y1 = std::min(v.dims.y - 1, hi_idx(center_body.y, v.origin.y, v.cell.y));
    const int z0 = std::max(0, lo_idx(center_body.z, v.origin.z, v.cell.z));
    const int z1 = std::min(v.dims.z - 1, hi_idx(center_body.z, v.origin.z, v.cell.z));

    const float r2 = radius * radius;
    for (int z = z0; z <= z1; ++z) {
        for (int y = y0; y <= y1; ++y) {
            for (int x = x0; x <= x1; ++x) {
                if (!v.solid(x, y, z)) continue;
                const glm::vec3 c{
                    v.origin.x + (static_cast<float>(x) + 0.5f) * v.cell.x,
                    v.origin.y + (static_cast<float>(y) + 0.5f) * v.cell.y,
                    v.origin.z + (static_cast<float>(z) + 0.5f) * v.cell.z,
                };
                const glm::vec3 d = c - center_body;
                if (glm::dot(d, d) > r2) continue;
                out.emplace_back(c.x, c.y, c.z,
                                 static_cast<float>(v.index(x, y, z)));
            }
        }
    }
    return out;
}

}  // namespace voxel
