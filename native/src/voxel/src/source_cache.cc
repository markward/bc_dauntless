#include "voxel/source_cache.h"
#include <voxel/voxelize.h>
#include <nif/file.h>
#include <nif/block.h>

namespace voxel {

std::filesystem::path vox_sibling_path(const std::filesystem::path& hull_nif) {
    std::filesystem::path p = hull_nif;
    const std::string ext = p.extension().string();          // ".nif" / ".NIF"
    p.replace_filename(p.stem().string() + "_vox" + ext);
    return p;
}

const VoxelVolume& SourceVolumeCache::get_for_hull(
        const std::filesystem::path& hull_nif) {
    const std::string key = hull_nif.string();
    auto it = by_path_.find(key);
    if (it != by_path_.end()) return it->second;

    VoxelVolume vol;
    const std::filesystem::path vox = vox_sibling_path(hull_nif);
    if (std::filesystem::exists(vox)) {
        nif::File f = nif::load(vox);
        const nif::NiBinaryVoxelData* vd = nullptr;
        for (const auto& b : f.blocks)
            if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = q;
        if (vd) vol = from_nif_voxel_data(*vd);
    }
    if (vol.occ.empty() && std::filesystem::exists(hull_nif)) {
        nif::File hf = nif::load(hull_nif);
        auto tris = collect_hull_triangles_from_nif(hf);
        vol = voxelize_tris(tris, glm::ivec3(48, 48, 48));
    }
    auto [ins, _] = by_path_.emplace(key, std::move(vol));
    return ins->second;
}

}  // namespace voxel
