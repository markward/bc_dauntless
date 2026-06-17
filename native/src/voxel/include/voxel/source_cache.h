#pragma once
#include <filesystem>
#include <string>
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>
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

    /// The Hesse-form plane palette (n̂.xyz, d) decoded from the hull's *_vox
    /// sibling — the sharp-feature data dual_contour() needs. Cached per path.
    /// Returns an EMPTY vector when the ship has no *_vox sibling or no palette
    /// (mod-ship graceful degradation: dual_contour then uses its gradient
    /// fallback, yielding a smoother but still solid interior).
    const std::vector<glm::vec4>& planes_for_hull(
        const std::filesystem::path& hull_nif);

private:
    std::unordered_map<std::string, VoxelVolume> by_path_;
    std::unordered_map<std::string, std::vector<glm::vec4>> planes_by_path_;
};

}  // namespace voxel
