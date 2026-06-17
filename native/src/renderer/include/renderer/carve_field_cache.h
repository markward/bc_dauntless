// native/src/renderer/include/renderer/carve_field_cache.h
#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <unordered_map>

#include <glm/glm.hpp>

#include <voxel/source_cache.h>
#include <voxel/volume.h>

namespace renderer {

/// Shared STATIC original-fill cache (hull-breach-2b Path C).
///
/// Serves the original (UNCARVED) hull fill as a GL_R8 3D texture, built
/// once per hull source path and reused across all instances of that hull.
/// The breach pass samples this texture as a material mask: keep a scoop
/// fragment iff fill(p_body) >= iso (solid material), else discard.
///
/// The hull clip no longer needs a fill texture (it is a pure sphere clip);
/// this cache is consumed only by the breach pass.
///
/// Owns GL texture objects; must be constructed/destroyed while a GL context
/// is current (same lifetime contract as BreachPass).
class CarveFieldCache {
public:
    CarveFieldCache() = default;
    ~CarveFieldCache();
    CarveFieldCache(const CarveFieldCache&)            = delete;
    CarveFieldCache& operator=(const CarveFieldCache&) = delete;

    // Isovalue: BC's 0..127 fill field. The 3D texture is GL_R8: occ byte
    // 0..127 samples as occ/255.0 in [0,1]. The shader compares against
    // kIsovalue/255.0 (= 64/255 ≈ 0.251).
    static constexpr int kIsovalue = 64;

    /// A cached static fill entry for one hull source path.
    struct Entry {
        unsigned int tex3d = 0;     // GL_R8 sampler3D (original/uncarved fill)
        glm::ivec3 dims{0};
        glm::vec3  origin{0.0f};
        glm::vec3  cell{1.0f};
    };

    /// Get (build if not yet cached) the static original fill texture for the
    /// given hull source path. Returns nullptr when the source fill is missing
    /// or the GL upload fails. The returned pointer is stable for the lifetime
    /// of the cache (source-keyed, never evicted).
    const Entry* get_for_source(const std::filesystem::path& source);

private:
    void upload_texture(Entry& e, const voxel::VoxelVolume& vol);

    std::unordered_map<std::string, Entry> by_source_;
    voxel::SourceVolumeCache source_cache_;
};

}  // namespace renderer
