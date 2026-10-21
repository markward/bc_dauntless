// native/src/renderer/carve_field_cache.cc
#include <renderer/carve_field_cache.h>

#include <glad/glad.h>

#include <algorithm>
#include <cmath>
#include <memory>
#include <string>
#include <system_error>
#include <unordered_map>

namespace renderer {

bool carve_has_backing(const voxel::VoxelVolume& fill,
                       const glm::vec3& center_body,
                       const glm::vec3& normal_body) {
    if (fill.occ.empty()) return true;      // no volume to consult → don't gate
    if (fill.cell.x <= 0.0f) return true;
    const float reach = CarveFieldCache::kBackingCells * fill.cell.x;
    for (int t = 1; t <= CarveFieldCache::kBackingTaps; ++t) {
        const float d =
            reach * static_cast<float>(t) / CarveFieldCache::kBackingTaps;
        const glm::vec3 p = center_body - normal_body * d;
        const glm::vec3 g = (p - fill.origin) / fill.cell;
        const glm::ivec3 c(static_cast<int>(std::floor(g.x)),
                           static_cast<int>(std::floor(g.y)),
                           static_cast<int>(std::floor(g.z)));
        if (c.x < 0 || c.y < 0 || c.z < 0 ||
            c.x >= fill.dims.x || c.y >= fill.dims.y || c.z >= fill.dims.z)
            continue;                       // outside the grid: genuinely nothing
        if (fill.occ[fill.index(c.x, c.y, c.z)] >=
            CarveFieldCache::kBackingIsovalue)
            return true;
    }
    return false;
}

float carve_cavity_depth_cells(const voxel::VoxelVolume& fill,
                               const glm::vec3& center_body,
                               const glm::vec3& normal_body) {
    // No volume to consult means no opinion — a mod ship with no _vox.nif keeps
    // its scoop rather than losing it to a probe with nothing to say. Same
    // contract as carve_has_backing's empty-volume case.
    if (fill.occ.empty() || fill.cell.x <= 0.0f)
        return CarveFieldCache::kCavityMaxCells;

    const float reach = CarveFieldCache::kCavityMaxCells * fill.cell.x;
    int hits = 0;
    for (int t = 1; t <= CarveFieldCache::kCavityTaps; ++t) {
        const float d =
            reach * static_cast<float>(t) / CarveFieldCache::kCavityTaps;
        const glm::vec3 p = center_body - normal_body * d;
        const glm::vec3 g = (p - fill.origin) / fill.cell;
        const glm::ivec3 c(static_cast<int>(std::floor(g.x)),
                           static_cast<int>(std::floor(g.y)),
                           static_cast<int>(std::floor(g.z)));
        if (c.x < 0 || c.y < 0 || c.z < 0 ||
            c.x >= fill.dims.x || c.y >= fill.dims.y || c.z >= fill.dims.z)
            continue;                       // off the grid: no material here
        if (fill.occ[fill.index(c.x, c.y, c.z)] >=
            CarveFieldCache::kBackingIsovalue)
            ++hits;
    }
    return CarveFieldCache::kCavityMaxCells * static_cast<float>(hits)
           / CarveFieldCache::kCavityTaps;
}

namespace {
std::unordered_map<std::string, float>& resolution_table() {
    static std::unordered_map<std::string, float> t;
    return t;
}
}  // namespace

void set_hull_volume_resolution(const std::filesystem::path& source, float authored_res) {
    if (source.empty() || !(authored_res > 0.0f)) return;
    resolution_table()[source.string()] = authored_res;
}

float hull_volume_resolution(const std::filesystem::path& source) {
    auto it = resolution_table().find(source.string());
    return (it == resolution_table().end()) ? 0.0f : it->second;
}

namespace {
std::filesystem::path& mutable_hull_volume_cache_root() {
    static std::filesystem::path root;  // empty until set_hull_volume_cache_root runs
    return root;
}

// Best-effort fallback when nothing configured a root before the first bake:
// the system temp directory, so a missing/never-called boot step degrades to
// "no cross-run persistence" rather than a crash or a write into cwd. If even
// that is unavailable (sandboxed environment, no TMPDIR), fall back to a
// relative path -- HullVolumeCache::get and dhv.h's write_dhv are already
// best-effort about a missing/unwritable directory.
std::filesystem::path fallback_hull_volume_cache_root() {
    std::error_code ec;
    std::filesystem::path tmp = std::filesystem::temp_directory_path(ec);
    if (ec || tmp.empty()) return "dauntless_hull_volumes_cache";
    return tmp / "dauntless_hull_volumes_cache";
}
}  // namespace

void set_hull_volume_cache_root(const std::filesystem::path& root) {
    mutable_hull_volume_cache_root() = root;
}

std::filesystem::path effective_hull_volume_cache_root() {
    std::filesystem::path root = mutable_hull_volume_cache_root();
    if (root.empty()) root = fallback_hull_volume_cache_root();
    return root;
}

voxel::HullVolumeCache& hull_volume_cache() {
    // Magic-static lambda: computed once, the first time this is called, using
    // whatever set_hull_volume_cache_root configured at that moment. A
    // std::unique_ptr rather than a by-value static because HullVolumeCache
    // has no default constructor -- its root is only known at first use.
    static std::unique_ptr<voxel::HullVolumeCache> instance = [] {
        return std::make_unique<voxel::HullVolumeCache>(
            effective_hull_volume_cache_root());
    }();
    return *instance;
}

CarveFieldCache::~CarveFieldCache() {
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

void CarveFieldCache::upload_texture(Entry& e, const voxel::VoxelVolume& vol) {
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
    // GL_R8: byte b samples as b/255.0 in [0,1]. The shader's u_fill_iso is
    // kIsovalue/255.0 so the fill mask and the original isovalue match.
    // LINEAR gives a smoother mask edge between cells.
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

void CarveFieldCache::worker_main() {
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

void CarveFieldCache::prefetch(const std::filesystem::path& source) {
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

const CarveFieldCache::Entry* CarveFieldCache::get_for_source(
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

const CarveFieldCache::Entry* CarveFieldCache::put_for_source(
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
