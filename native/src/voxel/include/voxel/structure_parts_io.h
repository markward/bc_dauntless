// native/src/voxel/include/voxel/structure_parts_io.h
//
// `.sps` disk cache for one hull's StructureSegmentation (layered damage
// phase 4, spec 2026-10-22-layered-damage-p4-finish-design.md §2.2), so
// detection (~0.3 s per hull at 128 cells) runs once per hull, not once per
// launch. renderer/structure_parts_cache names the file
// (<root>/<fnv1a64 hex of the NIF's bytes>-v<kStructurePartsVersion>.sps) and
// reads / writes it on its worker.
//
// Layout (little-endian, written byte by byte, never a struct memcpy):
//   char  magic[4] = "SPS1"
//   u32   version  = kStructurePartsVersion
//   i32   dims[3]
//   f32   origin[3]
//   f32   cell[3]
//   u32   label count (= dims.x*dims.y*dims.z)
//   RLE   (i16 value, u32 run) pairs, x-fastest, runs summing to the count.
//         value = the voxel's label (>= 0), -1 for an EMPTY voxel, -2 for a
//         SOLID voxel with no part (label -1); the occupancy grid is
//         recovered from it (occ = value != -1).
//   u32   part count
//   per part: i32 kind, f32 centre[3], f32 axis[3][3], f32 half_extent[3],
//             i32 voxels, f32 peak_depth, f32 spread[3]
//   u64   FNV-1a 64 of every byte above
//
// `depth` is NOT stored: the cache drops it once detection lands (no reader
// uses it), so a read returns it empty.
#pragma once

#include <cstdint>
#include <filesystem>
#include <optional>

#include <voxel/structure_parts.h>

namespace voxel {

/// Bump on ANY change to the layout or to detect_structure_parts' output
/// (its algorithm or its default StructureParams): it is in the file name,
/// so every older cache file simply stops matching and is rebuilt.
inline constexpr std::uint32_t kStructurePartsVersion = 1;

/// Write `seg` to `path` through a temp file of its own (`<path>.<pid>-<n>.tmp`)
/// + rename, so a crash mid-write never leaves a half file where a whole one
/// is expected and two concurrent writers of one path both succeed (the last
/// rename wins; the bytes are the same). A segmentation with a grid but no
/// parts is written like any other (nparts 0). False for an
/// empty path or a segmentation with no grid (nothing to cache; not
/// reported), or for any I/O failure, which prints
/// `[dauntless] could not write <path>: <why>` to stderr once per path per
/// process.
bool write_structure_parts(const std::filesystem::path& path,
                           const StructureSegmentation& seg);

/// Read `path`. nullopt -- the caller detects and rewrites -- for a missing
/// file, a bad magic, version or checksum, a short or over-long payload, or
/// a label naming no part.
std::optional<StructureSegmentation> read_structure_parts(
    const std::filesystem::path& path);

}  // namespace voxel
