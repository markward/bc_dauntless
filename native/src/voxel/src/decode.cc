// native/src/voxel/src/decode.cc
// Decode a NiBinaryVoxelData block's fill field into a VoxelVolume.
//
// Fill-field spec (from docs/original_game_reference/engine/nif-voxel-format.md
// §"fill-field encoding"):
//
//   N = (nx-1)*(ny-1)*(nz-1)          interior node count
//   W = (N + 7) / 8                    bytes per plane (ceil(N/8))
//   L = 7 * W                          fill field byte length (first L bytes of payload)
//
// The fill field contains 7 planes, plane p occupying bytes [p*W, (p+1)*W).
// Node flat index:   idx = i + (nx-1)*(j + (ny-1)*k)
// Bit for plane p:   (payload[p*W + idx/8] >> (idx%8)) & 1   (LSB-first)
// Fill value at node: v = sum_p( bit(p,idx) << p )  => 0..127

#include <voxel/voxelize.h>
#include <voxel/volume.h>
#include <nif/block.h>
#include <cstddef>
#include <cstdint>
#include <algorithm>
#include <cstring>  // std::memcpy

namespace voxel {

VoxelVolume from_nif_voxel_data(const nif::NiBinaryVoxelData& vd) {
    const int nx = static_cast<int>(vd.dim_x);
    const int ny = static_cast<int>(vd.dim_y);
    const int nz = static_cast<int>(vd.dim_z);

    // Interior node lattice dimensions
    const int dnx = nx - 1;
    const int dny = ny - 1;
    const int dnz = nz - 1;

    // Build the result volume with clamped dims (degenerate = empty occ).
    VoxelVolume vol;
    vol.dims  = glm::ivec3(std::max(dnx, 0), std::max(dny, 0), std::max(dnz, 0));
    vol.cell  = glm::vec3(vd.cell_size, vd.cell_size, vd.cell_size);

    // Origin: interior node i sits at aabb_min + (i+1)*cell_size; with
    // VoxelVolume's convention that voxel i's center is origin + (i+0.5)*cell,
    // placing origin = aabb_min + 0.5*cell_size makes node centers align.
    // (Best-estimate positioning; Tasks 9/10 will confirm via point-dump/IoU.)
    const float half_cell = 0.5f * vd.cell_size;
    vol.origin = glm::vec3(
        vd.aabb_min[0] + half_cell,
        vd.aabb_min[1] + half_cell,
        vd.aabb_min[2] + half_cell
    );

    // Degenerate case: any interior dimension <= 0 -> empty volume, no crash.
    if (dnx <= 0 || dny <= 0 || dnz <= 0) {
        // occ stays empty
        return vol;
    }

    const std::size_t N = static_cast<std::size_t>(dnx)
                        * static_cast<std::size_t>(dny)
                        * static_cast<std::size_t>(dnz);
    const std::size_t W = (N + 7u) / 8u;   // bytes per plane
    const std::size_t L = 7u * W;           // fill field length

    // Bounds guard: malformed payload -> return empty volume rather than OOB.
    if (vd.raw_voxel_payload.size() < L) {
        return vol;  // occ stays empty
    }

    const std::uint8_t* payload = vd.raw_voxel_payload.data();

    vol.occ.resize(N, 0u);

    for (std::size_t idx = 0; idx < N; ++idx) {
        std::uint8_t v = 0;
        for (int p = 0; p < 7; ++p) {
            // Plane p occupies bytes [p*W, (p+1)*W); node idx's bit is at
            // byte idx/8, bit position idx%8 (LSB-first within each byte).
            const std::uint8_t byte_val = payload[static_cast<std::size_t>(p) * W + idx / 8u];
            const int bit = (byte_val >> (idx % 8u)) & 1;
            v = static_cast<std::uint8_t>(v | (bit << p));
        }
        vol.occ[idx] = v;
    }

    return vol;
}

SurfaceData from_nif_surface(const nif::NiBinaryVoxelData& vd) {
    const int nx = static_cast<int>(vd.dim_x);
    const int ny = static_cast<int>(vd.dim_y);
    const int nz = static_cast<int>(vd.dim_z);

    // Compute fill-field length to locate the start of the palette in the payload.
    //   N = (nx-1)*(ny-1)*(nz-1)   interior node count
    //   W = ceil(N/8)               bytes per plane
    //   L = 7*W                     fill field byte length
    // For degenerate objects (any dim <= 1) N=0, so W=0 and L=0; the cursor
    // then starts at 0 and the palette reads fail their bounds checks, returning
    // an empty SurfaceData. (The fill decoder takes a separate early-return path;
    // behavior here differs but is equally safe.)
    const int dnx = nx - 1;
    const int dny = ny - 1;
    const int dnz = nz - 1;

    std::size_t N = 0;
    if (dnx > 0 && dny > 0 && dnz > 0) {
        N = static_cast<std::size_t>(dnx)
          * static_cast<std::size_t>(dny)
          * static_cast<std::size_t>(dnz);
    }
    const std::size_t W = (N + 7u) / 8u;
    const std::size_t L = 7u * W;

    const auto& payload = vd.raw_voxel_payload;

    // Little-endian cursor helpers operating over payload bytes.
    // Returns false (and sets cursor past end) if a read would exceed payload size.
    std::size_t cursor = L;

    auto read_u32 = [&](std::uint32_t& out) -> bool {
        if (cursor + 4u > payload.size()) return false;
        std::uint32_t tmp = 0;
        std::memcpy(&tmp, payload.data() + cursor, 4u);
        // Reinterpret raw bytes as little-endian u32 (host is assumed LE on all
        // target platforms — same assumption as the existing fill decoder which
        // reads bytes directly without byte-swap).
        out = tmp;
        cursor += 4u;
        return true;
    };

    auto read_f32 = [&](float& out) -> bool {
        if (cursor + 4u > payload.size()) return false;
        std::memcpy(&out, payload.data() + cursor, 4u);
        cursor += 4u;
        return true;
    };

    // ---- numPlanes ----
    std::uint32_t numPlanes = 0;
    if (!read_u32(numPlanes)) return {};

    // ---- plane palette: numPlanes × (n.x, n.y, n.z, d) Vector4 ----
    // Guard the allocation against a malformed count before resizing (the
    // bytes2 path below checks-before-alloc the same way): 16 bytes per plane.
    if (static_cast<std::size_t>(numPlanes) > (payload.size() - cursor) / 16u)
        return {};
    SurfaceData s;
    s.planes.resize(numPlanes);
    for (std::uint32_t i = 0; i < numPlanes; ++i) {
        float x, y, z, d;
        if (!read_f32(x) || !read_f32(y) || !read_f32(z) || !read_f32(d))
            return {};
        s.planes[i] = glm::vec4(x, y, z, d);
    }

    // ---- numBytes2 ----
    std::uint32_t numBytes2 = 0;
    if (!read_u32(numBytes2)) return {};

    // ---- bytes2 blob ----
    if (cursor + numBytes2 > payload.size()) return {};
    s.bytes2.assign(payload.data() + cursor,
                    payload.data() + cursor + numBytes2);
    cursor += numBytes2;

    // ---- trailer: 5 × u32 ----
    for (int i = 0; i < 5; ++i) {
        if (!read_u32(s.trailer[static_cast<std::size_t>(i)])) return {};
    }

    return s;
}

}  // namespace voxel
