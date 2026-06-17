#pragma once
#include <filesystem>
#include <string>
#include <unordered_map>
#include <voxel/volume.h>

namespace voxel {

/// "<stem>_vox<ext>" sibling of a hull nif path (preserves extension case).
std::filesystem::path vox_sibling_path(const std::filesystem::path& hull_nif);

/// Caches one intact source VoxelVolume per hull nif path. Decodes the ship's
/// *_vox.nif when present (exact BC volume); else voxelizes the hull mesh
/// (mod-ship fallback). Lazy, shared across instances.
class SourceVolumeCache {
public:
    const VoxelVolume& get_for_hull(const std::filesystem::path& hull_nif);
private:
    std::unordered_map<std::string, VoxelVolume> by_path_;
};

}  // namespace voxel
