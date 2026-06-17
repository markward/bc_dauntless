// native/src/renderer/include/renderer/carve_field_cache.h
#pragma once

#include <cstdint>
#include <filesystem>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>

#include <voxel/source_cache.h>
#include <voxel/volume.h>

namespace scenegraph { class HullCarveField; }

namespace renderer {

/// Shared per-instance carved-fill cache (hull-breach-2b cross-pass unify).
///
/// ONE carved fill per damaged instance, used by BOTH:
///   (a) the opaque hull clip (opaque.frag samples the GL 3D texture and
///       discards fragments where fill < isovalue), and
///   (b) the breach pass's dual-contour interior mesh (extracted from the SAME
///       CPU carved VoxelVolume).
/// Because both consume the identical carved fill, the hull hole edge IS the
/// DC-mesh isosurface boundary — no poke, no gap, by construction.
///
/// Carve-version caching: the carved fill + its GL 3D texture are rebuilt /
/// re-uploaded ONLY when the instance's carve "version" (max active carve seq)
/// changes — never per frame.  The cache owns a voxel::SourceVolumeCache so the
/// intact source fill + plane palette are decoded once per hull and shared
/// across all instances of that hull.
///
/// Owns GL texture objects, so it must be constructed/destroyed while a GL
/// context is current (same lifetime contract as BreachPass).
class CarveFieldCache {
public:
    CarveFieldCache() = default;
    ~CarveFieldCache();
    CarveFieldCache(const CarveFieldCache&)            = delete;
    CarveFieldCache& operator=(const CarveFieldCache&) = delete;

    // Isovalue (BC's 0..127 fill field) used by BOTH the clip and the DC
    // extraction.  The 3D texture is GL_R8: occ byte 0..127 samples as
    // occ/255.0 in [0,1].  So the shader compares against kIsovalue/255.0.
    static constexpr int kIsovalue = 64;

    /// A cached per-instance carved fill + its GL 3D texture.
    struct Entry {
        std::uint64_t carve_version = 0;   // 0 = never built
        voxel::VoxelVolume carved;         // CPU carved fill (shared with DC)
        const std::vector<glm::vec4>* palette = nullptr;  // into source_cache_
        unsigned int tex3d = 0;            // GL_R8 sampler3D (occ 0..127)
        glm::ivec3 dims{0};
        glm::vec3  origin{0.0f};
        glm::vec3  cell{1.0f};
    };

    /// Resolve (build if the carve version changed) the carved fill + 3D texture
    /// for one instance.  `source` is the hull's NIF path (instance's model
    /// source).  Returns nullptr when there is no usable source fill or no
    /// active carves (caller treats that as "no clip / no breach").  The
    /// returned pointer is stable until the next get() for the SAME key with a
    /// changed version (the carved fill / texture are rebuilt in place).
    const Entry* get(std::uintptr_t instance_key,
                     const std::filesystem::path& source,
                     const scenegraph::HullCarveField& carve);

private:
    std::uint64_t carve_version(const scenegraph::HullCarveField& carve) const;
    void upload_texture(Entry& e);

    std::unordered_map<std::uintptr_t, Entry> by_instance_;
    voxel::SourceVolumeCache source_cache_;
};

}  // namespace renderer
