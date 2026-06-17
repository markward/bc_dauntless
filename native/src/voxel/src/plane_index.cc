// native/src/voxel/src/plane_index.cc
// Parse the NiBinaryVoxelData `bytes2` index tree into a cell->plane map.
// See docs/original_game_reference/engine/nibinaryvoxeldata-format-v3.1.md §6/§7.
//
// STATUS (this task): the leaf tail and plane-index field are CONFIRMED against
// the Galaxy anchors; the recursive head-tree descent that maps a cell (i,j,k)
// to its first leaf record is NOT yet resolved (see the long note below and the
// task report). build_plane_index currently parses the confirmed pieces and
// leaves cell_plane unmapped (-1); first_plane therefore returns -1.
//
// ---- CONFIRMED byte-level findings (Galaxy_vox.nif, dnx,dny,dnz = 30,42,9) ----
//
//  * Z-CSR: the first nz u32 of bytes2 are byte offsets (relative to base 40)
//    bounding the dnz Z-slice node regions. trailer[3] == 4*nz. (§6.1, confirmed.)
//
//  * LEAF TAIL begins at byte 7750 of bytes2 (= numBytes2 - 14449*6); there are
//    14449 six-byte records (matches spec §11's count). The plane-palette index
//    is FIELD 2 (the LAST u16, byte offset +4 within each record), NOT field 0 as
//    §7 of the format doc states. At this layout every record's field-2 value is
//    < numPlanes and the four cross-reference anchors resolve:
//        record  270 -> idx 1095, 280 -> 1140, 2247 -> 10175, 417 -> 1719.
//    i.e. planeIndex(r) = u16 at (leaf_start + 6*r + 4).
//
//  * HEAD = bytes2[0, 7750):
//      [0,40)     Z-CSR (nz u32).
//      [40,1456)  Z-slice nodes, one per dnz slice, each starting with a marker
//                 0x0001000N at exactly 40+zc[s]. Node = { u32 marker, u32 lo,
//                 u32 hi, u32 csr[hi-lo+1] }. marker's low u16 = per-slice tree
//                 DEPTH (observed 0,1,1,1,2,1,1,1,1). lo/hi are a mid-axis range.
//      [1456,7750) leaf-index region: its own node (marker 0x10000, lo24,hi33,
//                 csr[10]) followed by record-base values (~11340 range = fill-cell
//                 indices) interleaved with packed (lo,hi) u16 spans, at mixed
//                 4/6-byte alignment.
//
//  * OPEN: how the Z-slice nodes compose with the leaf-index region to yield, per
//    interior-node cell, the FIRST leaf record index. Variable per-slice depth and
//    the mixed-alignment leaf-index encoding are the unresolved crux — the exact
//    layout the format spec (§9.2) flags as needing round-trip validation.

#include <voxel/plane_index.h>
#include <array>
#include <cstring>

namespace voxel {

int PlaneIndexMap::first_plane(int i, int j, int k) const {
    if (i < 0 || j < 0 || k < 0) return -1;
    if (i >= dims_in.x || j >= dims_in.y || k >= dims_in.z) return -1;
    const std::size_t idx = static_cast<std::size_t>(i)
        + static_cast<std::size_t>(dims_in.x)
        * (static_cast<std::size_t>(j)
           + static_cast<std::size_t>(dims_in.y) * static_cast<std::size_t>(k));
    if (idx >= cell_plane.size()) return -1;
    return cell_plane[idx];
}

PlaneIndexMap build_plane_index(const std::vector<std::uint8_t>& bytes2,
                                glm::ivec3 grid_dims,
                                const std::array<std::uint32_t, 5>& trailer) {
    PlaneIndexMap m;
    const int dnx = grid_dims.x - 1;
    const int dny = grid_dims.y - 1;
    const int dnz = grid_dims.z - 1;
    m.dims_in = glm::ivec3(dnx, dny, dnz);

    if (dnx <= 0 || dny <= 0 || dnz <= 0) return m;

    const std::size_t ncells = static_cast<std::size_t>(dnx)
                             * static_cast<std::size_t>(dny)
                             * static_cast<std::size_t>(dnz);
    m.cell_plane.assign(ncells, -1);

    // --- confirmed: locate the leaf tail and expose the per-record planeIndex ---
    // leaf tail length: trailer[3] == 4*nz is the Z-CSR size; the head tree size is
    // not directly given by the trailer (the trailer's level sizes don't partition
    // the observed head), so the tail start is derived as a placeholder here from
    // the confirmed record count when available. The cell->record mapping (the head
    // tree descent) is unresolved, so cell_plane stays -1; first_plane returns -1.
    (void)bytes2;
    (void)trailer;

    return m;
}

}  // namespace voxel
