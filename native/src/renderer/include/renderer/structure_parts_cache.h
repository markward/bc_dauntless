// native/src/renderer/include/renderer/structure_parts_cache.h
//
// SPIKE (damage redesign): per-hull-source cache of voxel::detect_structure_parts,
// computed on a worker thread the first time a hull asks (~0.3 s at 128 cells),
// so it never stalls a frame. Until it lands, callers get nullptr and the
// plating shader falls back to a body-axis box chart.
#pragma once
#include <filesystem>
#include <vector>

#include <voxel/structure_parts.h>

namespace renderer {

// The whole segmentation (volume + labels + parts); same async job and entry
// as structure_parts_for. nullptr until ready.
const voxel::StructureSegmentation* structure_segmentation_for(
    const std::filesystem::path& source);

const std::vector<voxel::StructurePart>* structure_parts_for(
    const std::filesystem::path& source);

}  // namespace renderer
