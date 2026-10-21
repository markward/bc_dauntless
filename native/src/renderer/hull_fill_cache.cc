// native/src/renderer/hull_fill_cache.cc
#include <renderer/hull_fill_cache.h>

#include <glad/glad.h>

#include <algorithm>
#include <string>
#include <unordered_map>

namespace renderer {

HullFillCache::~HullFillCache() {
    {
        std::lock_guard<std::mutex> lk(mu_);
        stop_ = true;
    }
    cv_.notify_all();
    if (worker_.joinable()) worker_.join();
    for (auto& kv : by_source_) {
        if (kv.second.tex3d) {
            GLuint t = kv.second.tex3d;
            glDeleteTextures(1, &t);
            kv.second.tex3d = 0;
        }
    }
}

void HullFillCache::upload_texture(Entry& e, const voxel::VoxelVolume& vol) {
    if (vol.occ.empty() || vol.dims.x <= 0 || vol.dims.y <= 0 ||
        vol.dims.z <= 0) {
        return;
    }

    if (e.tex3d == 0) {
        GLuint t = 0;
        glGenTextures(1, &t);
        e.tex3d = t;
    }

    GLint prev_unpack = 0;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &prev_unpack);
    GLint prev_unit = 0;
    glGetIntegerv(GL_ACTIVE_TEXTURE, &prev_unit);
    glActiveTexture(GL_TEXTURE0);

    glBindTexture(GL_TEXTURE_3D, e.tex3d);
    // occ is one byte per cell (0..127), tightly packed x-fastest.
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    // GL_R8: byte b samples as b/255.0 in [0,1] (the interior shader's
    // u_fill_backing is kBackingIsovalue/255.0). LINEAR gives a smoother
    // mask edge between cells.
    glTexImage3D(GL_TEXTURE_3D, 0, GL_R8,
                 vol.dims.x, vol.dims.y, vol.dims.z, 0,
                 GL_RED, GL_UNSIGNED_BYTE, vol.occ.data());
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_3D, 0);
    glActiveTexture(static_cast<GLenum>(prev_unit));

    glPixelStorei(GL_UNPACK_ALIGNMENT, prev_unpack);

    e.dims   = vol.dims;
    e.origin = vol.origin;
    e.cell   = vol.cell;
}

void HullFillCache::worker_main() {
    for (;;) {
        std::string key;
        {
            std::unique_lock<std::mutex> lk(mu_);
            cv_.wait(lk, [&] { return stop_ || !queue_.empty(); });
            if (stop_) return;
            key = std::move(queue_.front());
            queue_.pop_front();
        }
        voxel::VoxelVolume vol;
        try {
            vol = voxel::decode_hull_volume(std::filesystem::path(key));
        } catch (...) {
            vol = voxel::VoxelVolume{};     // cached as "no fill"
        }
        std::lock_guard<std::mutex> lk(mu_);
        // Not stored when put_for_source superseded the request meanwhile.
        if (requested_.count(key) != 0) decoded_[key] = std::move(vol);
    }
}

void HullFillCache::prefetch(const std::filesystem::path& source) {
    if (source.empty()) return;
    const std::string key = source.string();
    if (by_source_.count(key) != 0) return;
    {
        std::lock_guard<std::mutex> lk(mu_);
        if (!requested_.insert(key).second) return;
        queue_.push_back(key);
    }
    if (!worker_.joinable()) worker_ = std::thread([this] { worker_main(); });
    cv_.notify_one();
}

const HullFillCache::Entry* HullFillCache::get_for_source(
        const std::filesystem::path& source) {
    if (source.empty()) return nullptr;

    const std::string key = source.string();
    auto it = by_source_.find(key);
    if (it != by_source_.end()) {
        // Already cached (including an attempted-but-failed upload with tex3d==0).
        return (it->second.tex3d != 0) ? &it->second : nullptr;
    }

    voxel::VoxelVolume fill;
    bool ready = false;
    {
        std::lock_guard<std::mutex> lk(mu_);
        auto d = decoded_.find(key);
        if (d != decoded_.end()) {
            fill = std::move(d->second);
            decoded_.erase(d);
            ready = true;
        }
    }
    if (!ready) {
        prefetch(source);
        return nullptr;
    }

    Entry& e = by_source_[key];
    if (fill.occ.empty()) return nullptr;
    upload_texture(e, fill);
    return (e.tex3d != 0) ? &e : nullptr;
}

const HullFillCache::Entry* HullFillCache::put_for_source(
        const std::filesystem::path& source, const voxel::VoxelVolume& fill) {
    // An empty volume is never uploaded: leave no entry, or get_for_source
    // would report this source as a failed upload forever.
    if (fill.occ.empty() || fill.dims.x <= 0 || fill.dims.y <= 0 || fill.dims.z <= 0)
        return nullptr;
    const std::string key = source.string();
    {
        // The installed fill supersedes any prefetch of this source: drop a
        // decoded volume (get_for_source will never read it now), a queued
        // job, and the request, so an in-flight decode is not stored either.
        std::lock_guard<std::mutex> lk(mu_);
        decoded_.erase(key);
        queue_.erase(std::remove(queue_.begin(), queue_.end(), key), queue_.end());
        requested_.erase(key);
    }
    Entry& e = by_source_[key];
    upload_texture(e, fill);
    return (e.tex3d != 0) ? &e : nullptr;
}

}  // namespace renderer
