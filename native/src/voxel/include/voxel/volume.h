#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>

namespace voxel {

/// Solid voxel volume — the shared output type for both the decoder and the
/// voxelizer. Holds one byte per cell in `occ`, indexed x-fastest:
///   index(x,y,z) = x + dims.x * (y + dims.y * z)
///
/// **Dual semantics of `occ`:**
///   - When produced by the voxelizer (voxelize / voxelize_into / surface_voxelize
///     + solidify): each byte is BINARY occupancy: 1 = solid, 0 = empty.
///   - When produced by the decoder (from_nif_voxel_data): each byte is the
///     0–127 fill value read from BC's 7-bit fill field for that interior node.
///     0 = empty, 127 = fully solid, 1–126 = partial fill (semantics TBD).
/// In both cases, `solid(x,y,z)` treats any nonzero byte as solid, so the same
/// downstream code (IoU, carving, solidify checks) works for both.
///
/// **Dual lattice:**
///   - The decoder produces the INTERIOR-NODE lattice: dims = (nx-1, ny-1, nz-1)
///     where (nx, ny, nz) are the header shorts from NiBinaryVoxelData. The fill
///     values live at interior nodes, not at the coarse cell corners.
///   - The voxelizer produces a CALLER-CHOSEN grid with whatever dims are passed.
/// To compare the two (e.g. via iou()), the hull must be re-voxelized onto the
/// decoded lattice explicitly:
///   voxelize_into(tris, ref.dims, ref.origin, ref.cell)
/// A naive iou(decoded, voxelize(model, header_dims)) would silently compare
/// mismatched grids ((nx-1,ny-1,nz-1) vs (nx,ny,nz)) and assert-fail or
/// produce wrong results.
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

/// Plane palette + bytes2 index + trailer decoded from a NiBinaryVoxelData block.
/// planes: plane palette in Hesse normal form (n̂.x, n̂.y, n̂.z, d), d in GU (§5).
/// bytes2: raw bytes of the cell→plane index tree + leaf records (§6/§7).
/// trailer: the five u32 trailer words (§8); trailer[3] = 4*nz, trailer[4] = 0.
struct SurfaceData {
    std::vector<glm::vec4>       planes;     // (n̂.xyz, d) Hesse form, GU (§5)
    std::vector<std::uint8_t>    bytes2;     // index tree + leaf tail (§6/§7)
    std::array<std::uint32_t, 5> trailer{};
};

/// Intersection-over-union of the SOLID sets of two volumes.
/// Requires equal dims; asserts and returns -1.0 if mismatched.
/// Returns 1.0 when both volumes are empty (vacuously identical).
/// solid(i) is defined as occ[i] != 0, so works for both binary (0/1)
/// voxelizer output and 0–127 decoder fill values.
double iou(const VoxelVolume& a, const VoxelVolume& b);

}  // namespace voxel
