// native/src/renderer/include/renderer/hull_fill_cache.h
#pragma once

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>

#include <glm/glm.hpp>

#include <voxel/source_cache.h>
#include <voxel/volume.h>

namespace renderer {

/// Shared STATIC hull fill cache.
///
/// Serves a hull's ORIGINAL fill volume (BC's authored `_vox.nif`, decoded by
/// voxel::decode_hull_volume) as a GL_R8 3D texture, built once per hull
/// source path and reused across every instance of that hull. Its consumer is
/// the hull interior pass (submit_plating_interior -> HullInteriorPass), which
/// samples it for the "has the view ray left the ship?" test behind a plating
/// cut.
///
/// Was CarveFieldCache, renamed when the old voxel carve was removed (layered
/// damage phase 4): the fill outlived the carve that first used it.
///
/// Owns GL texture objects; must be constructed/destroyed while a GL context
/// is current.
class HullFillCache {
public:
    HullFillCache() = default;
    ~HullFillCache();
    HullFillCache(const HullFillCache&)            = delete;
    HullFillCache& operator=(const HullFillCache&) = delete;

    // The "is there ANY hull material here?" threshold on BC's 0..127 fill
    // field. The 3D texture is GL_R8, so byte b samples as b/255; the interior
    // shader compares against kBackingIsovalue/255 (u_fill_backing).
    //
    // Measured on stock hulls (Galaxy/Sovereign/Akira, hull-triangle
    // centroids sampled against their own _vox.nif): 39-53% of hull triangles
    // sit at or outside the solid-interior iso surface (64), so "any fill" is
    // the threshold that agrees with the hull mesh.
    static constexpr int kBackingIsovalue = 1;

    /// A cached static fill entry for one hull source path.
    struct Entry {
        unsigned int tex3d = 0;     // GL_R8 sampler3D (original fill)
        glm::ivec3 dims{0};
        glm::vec3  origin{0.0f};
        glm::vec3  cell{1.0f};
    };

    /// Start decoding `source`'s fill on the single background worker (one job
    /// at a time, later sources queued). Idempotent; no-op for an empty path or
    /// a source already cached, queued or decoded.
    void prefetch(const std::filesystem::path& source);

    /// Get the static original fill texture for the given hull source path.
    /// NEVER BLOCKS: returns nullptr while the CPU volume is still decoding
    /// (starting the prefetch if none is running); once ready, uploads the GL
    /// texture on the calling (render) thread and returns the entry. A failed
    /// decode/upload is cached as "no fill" (nullptr forever). The returned
    /// pointer is stable for the lifetime of the cache (never evicted).
    const Entry* get_for_source(const std::filesystem::path& source);

    /// Install `fill` as the fill for `source`, uploaded the same way
    /// get_for_source uploads a decoded one. For a hull with no fill on disk
    /// (tests; standalone tools). Returns nullptr when the upload fails.
    const Entry* put_for_source(const std::filesystem::path& source,
                                const voxel::VoxelVolume& fill);

    /// Decoded volumes waiting for get_for_source to upload them (tests).
    std::size_t decoded_pending() {
        std::lock_guard<std::mutex> lk(mu_);
        return decoded_.size();
    }

    /// The CPU-side original fill volume for a hull source -- the same data
    /// get_for_source uploads, before it becomes a texture. Decodes
    /// synchronously on first use (render thread). Returns an empty volume
    /// when the source has none.
    const voxel::VoxelVolume& volume_for_source(
            const std::filesystem::path& source) {
        return source_cache_.get_for_hull(source);
    }

private:
    void upload_texture(Entry& e, const voxel::VoxelVolume& vol);
    void worker_main();

    std::unordered_map<std::string, Entry> by_source_;
    // Render thread only. The worker never touches it (it calls
    // voxel::decode_hull_volume, which is cache-free).
    voxel::SourceVolumeCache source_cache_;

    // Worker state, all guarded by mu_.
    std::mutex mu_;
    std::condition_variable cv_;
    std::deque<std::string> queue_;
    std::unordered_set<std::string> requested_;
    std::unordered_map<std::string, voxel::VoxelVolume> decoded_;
    bool stop_ = false;
    std::thread worker_;
};

}  // namespace renderer
