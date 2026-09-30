#include "voxel/source_cache.h"
#include <voxel/voxelize.h>
#include <voxel/dvox.h>
#include <assets/cache.h>
#include <assets/gltf.h>
#include <assets/hull_source.h>
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

    const assets::HullSource h = assets::split_hull_source(hull_nif);
    VoxelVolume vol;

    if (assets::is_gltf_path(h.path)) {
        try {
            const assets::gltf::CpuScene s = assets::gltf::load_cpu(h.path, h.scale);
            if (!s.volume.empty()) {
                VoxelVolume raw;
                if (read_dvox(s.volume, raw)) vol = remap_gltf_volume_to_bc(raw, h.scale);
            }
            if (vol.occ.empty()) {
                const auto tris = collect_hull_triangles_from_source(hull_nif);
                vol = voxelize_tris(tris, glm::ivec3(48, 48, 48));
            }
        } catch (const assets::AssetError&) {
            vol = VoxelVolume{};
        }
    } else {
        const std::filesystem::path vox = vox_sibling_path(h.path);
        if (std::filesystem::exists(vox)) {
            nif::File f = nif::load(vox);
            const nif::NiBinaryVoxelData* vd = nullptr;
            for (const auto& b : f.blocks)
                if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = q;
            if (vd) vol = from_nif_voxel_data(*vd);
        }
        if (vol.occ.empty() && std::filesystem::exists(h.path)) {
            nif::File hf = nif::load(h.path);
            auto tris = collect_hull_triangles_from_nif(hf);
            vol = voxelize_tris(tris, glm::ivec3(48, 48, 48));
        }
    }

    auto [ins, _] = by_path_.emplace(key, std::move(vol));
    return ins->second;
}

const std::vector<glm::vec4>& SourceVolumeCache::planes_for_hull(
        const std::filesystem::path& hull_nif) {
    const std::string key = hull_nif.string();
    auto it = planes_by_path_.find(key);
    if (it != planes_by_path_.end()) return it->second;

    std::vector<glm::vec4> planes;  // empty by default (mod-ship / glTF graceful path)
    const assets::HullSource h = assets::split_hull_source(hull_nif);
    if (!assets::is_gltf_path(h.path)) {
        const std::filesystem::path vox = vox_sibling_path(h.path);
        if (std::filesystem::exists(vox)) {
            nif::File f = nif::load(vox);
            const nif::NiBinaryVoxelData* vd = nullptr;
            for (const auto& b : f.blocks)
                if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = q;
            if (vd) {
                SurfaceData sd = from_nif_surface(*vd);
                planes = std::move(sd.planes);
            }
        }
    }
    auto [ins, _] = planes_by_path_.emplace(key, std::move(planes));
    return ins->second;
}

}  // namespace voxel
