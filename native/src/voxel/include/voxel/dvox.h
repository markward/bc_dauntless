// native/src/voxel/include/voxel/dvox.h
//
// `.dvox` sidecar: a pre-authored BINARY occupancy volume for one hull,
// stored in the hull's OWN frame and units (glTF: metres, glTF axes -- no
// BC-frame conversion baked in, so a catalogue asset ships one file
// regardless of import scale). `remap_gltf_volume_to_bc` performs that
// conversion at load time.
//
// Layout (little-endian):
//   char     magic[4]  = "DVX1"
//   u16      version   = 1
//   i32      dims[3]
//   f32      origin[3]
//   f32      cell[3]
//   u8[ceil(N/8)] occupancy bits, N = dims.x*dims.y*dims.z, x-fastest
//     (index = x + dims.x*(y + dims.y*z)); bit i lives at byte i>>3, mask
//     1<<(i&7).
#pragma once

#include <filesystem>
#include <voxel/volume.h>

namespace voxel {

/// Write `v`'s occupancy (occ != 0) as a `.dvox` file at `p`. Writes to a
/// sibling temporary and renames into place (mirrors dhv.cc), so a crash
/// mid-write cannot leave a half-written file where a valid one is expected.
/// False for a non-positive dim or an `occ` size inconsistent with `dims`.
bool write_dvox(const std::filesystem::path& p, const VoxelVolume& v);

/// Read `p` into `out` (occ bytes 0/1). False -- leaving `out` untouched --
/// for a missing file, a short payload, a bad magic, a version other than 1,
/// a non-positive dim, or an implausibly large cell count.
bool read_dvox(const std::filesystem::path& p, VoxelVolume& out);

/// Re-index (not resample) a glTF-frame, metre volume into BC's frame and
/// model units at import `scale`: axis map (x,y,z)_gltf -> (-x,z,y)_BC (same
/// as assets::gltf::to_bc_frame), lengths scaled by
/// assets::gltf::kMetresToModelUnits * scale.
VoxelVolume remap_gltf_volume_to_bc(const VoxelVolume& v_gltf, float scale);

}  // namespace voxel
