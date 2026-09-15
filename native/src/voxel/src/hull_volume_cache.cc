// native/src/voxel/src/hull_volume_cache.cc
#include <voxel/hull_volume_cache.h>

#include <voxel/voxelize.h>
#include <nif/file.h>

#include <cstdio>
#include <exception>
#include <sstream>
#include <system_error>

namespace voxel {

namespace {

// Stable 64-bit hash of the key string. Only needs to avoid collisions across
// one install's hull set, and the file's own header is re-validated on read, so
// a collision degrades to a rebake rather than to a wrong volume.
std::uint64_t fnv1a(const std::string& s) {
    std::uint64_t h = 1469598103934665603ull;
    for (unsigned char c : s) { h ^= c; h *= 1099511628211ull; }
    return h;
}

std::uint32_t file_size_of(const std::filesystem::path& p) {
    std::error_code ec;
    const auto n = std::filesystem::file_size(p, ec);
    return ec ? 0u : static_cast<std::uint32_t>(n);
}

std::int64_t mtime_of(const std::filesystem::path& p) {
    std::error_code ec;
    const auto t = std::filesystem::last_write_time(p, ec);
    if (ec) return 0;
    return static_cast<std::int64_t>(t.time_since_epoch().count());
}

std::string key_string(const std::filesystem::path& hull,
                       float authored_res, float quality) {
    std::ostringstream os;
    os << hull.string() << '|' << authored_res << '|' << quality;
    return os.str();
}

std::filesystem::path cache_path_for(const std::filesystem::path& root,
                                     const std::filesystem::path& hull_nif,
                                     float authored_res, float quality) {
    char name[64];
    std::snprintf(name, sizeof name, "%016llx.dhv",
                  static_cast<unsigned long long>(
                      fnv1a(key_string(hull_nif, authored_res, quality))));
    return root / name;
}

// Accept a cache file only when the entry still describes THIS hull, at THIS
// resolution and quality. read_dhv has already rejected a wrong baker version,
// a bad magic and a short payload. source_path is checked too -- the filename
// hashes (hull, res, quality) into 64 bits, so two different tuples CAN
// collide onto the same cache file; without this check that collision would
// be caught only by size/mtime coincidentally differing. dhv.h's "diagnosis
// only, never for lookup" note is about not using source_path to LOCATE a
// file -- using it to validate one already loaded is exactly this layer's job.
bool read_valid_dhv(const std::filesystem::path& cache_file,
                    const std::filesystem::path& hull_nif,
                    float authored_res, float quality,
                    std::uint32_t size, std::int64_t mtime,
                    DistanceField& out) {
    DistanceField f;
    HullVolumeMeta m;
    if (!read_dhv(cache_file, f, m)) return false;
    if (m.source_size != size || m.source_mtime != mtime ||
        m.authored_res != authored_res || m.quality != quality ||
        m.source_path != hull_nif.string())
        return false;
    out = std::move(f);
    return true;
}

// Bake `hull_nif` (which must exist) and write the result. A hull whose file
// cannot be parsed as a NIF at all (truncated, or -- as in the headless test
// suite -- not a NIF in the first place) yields an empty field rather than
// propagating the parse exception: the cache's job is to answer "what's the
// field for this path", not to assume every path is a well-formed asset.
// Returns true when the write succeeded.
bool bake_and_write(const std::filesystem::path& cache_file,
                    const std::filesystem::path& hull_nif,
                    float authored_res, float quality,
                    std::uint32_t size, std::int64_t mtime,
                    DistanceField& field) {
    field = DistanceField{};
    try {
        nif::File f = nif::load(hull_nif);
        const std::vector<Tri> tris = collect_hull_triangles_from_nif(f);
        if (!tris.empty()) {
            const float cell = (quality > 0.0f && authored_res > 0.0f)
                             ? authored_res / quality
                             : 0.0f;
            if (cell > 0.0f) {
                field = distance_field_from_tris(tris, glm::vec3(cell));
                // The baker coarsens a lattice that would blow
                // kMaxFieldCells (FedStarbase at cell 7.5 is 28.7G cells).
                // That is the intended outcome, not a fault, but it is a
                // silent fidelity change per hull, so say so once -- this
                // runs once per (hull, res, quality) per cache lifetime.
                if (!field.empty() && field.cell.x > cell) {
                    std::fprintf(stderr,
                                 "[hull_volume] \"%s\": lattice at the "
                                 "authored cell %.2f would exceed "
                                 "kMaxFieldCells; baked at cell %.2f "
                                 "(%dx%dx%d) instead.\n",
                                 hull_nif.string().c_str(), cell,
                                 field.cell.x, field.dims.x,
                                 field.dims.y, field.dims.z);
                }
            }
        }
    } catch (const std::exception&) {
        field = DistanceField{};
    }

    HullVolumeMeta meta;
    meta.baker_version = kBakerVersion;
    meta.source_size   = size;
    meta.source_mtime  = mtime;
    meta.authored_res  = authored_res;
    meta.quality       = quality;
    meta.source_path   = hull_nif.string();
    return write_dhv(cache_file, field, meta);
}

}  // namespace

bool ensure_dhv(const std::filesystem::path& cache_root,
                const std::filesystem::path& hull_nif,
                float authored_res, float quality) {
    if (!std::filesystem::exists(hull_nif)) return false;
    const std::filesystem::path cache_file =
        cache_path_for(cache_root, hull_nif, authored_res, quality);
    const std::uint32_t size  = file_size_of(hull_nif);
    const std::int64_t  mtime = mtime_of(hull_nif);
    DistanceField f;
    if (read_valid_dhv(cache_file, hull_nif, authored_res, quality,
                       size, mtime, f))
        return true;
    return bake_and_write(cache_file, hull_nif, authored_res, quality,
                          size, mtime, f);
}

HullVolumeCache::HullVolumeCache(std::filesystem::path cache_root)
    : root_(std::move(cache_root)) {}

std::filesystem::path HullVolumeCache::path_for(
        const std::filesystem::path& hull_nif,
        float authored_res, float quality) const {
    return cache_path_for(root_, hull_nif, authored_res, quality);
}

const DistanceField& HullVolumeCache::get(
        const std::filesystem::path& hull_nif,
        float authored_res, float quality) {
    const std::string key = key_string(hull_nif, authored_res, quality);
    auto it = by_key_.find(key);
    if (it != by_key_.end()) return it->second;

    const std::filesystem::path cache_file =
        path_for(hull_nif, authored_res, quality);
    const std::uint32_t size  = file_size_of(hull_nif);
    const std::int64_t  mtime = mtime_of(hull_nif);

    DistanceField field;
    if (!read_valid_dhv(cache_file, hull_nif, authored_res, quality,
                        size, mtime, field)) {
        // A missing hull memoises an empty field in memory only: there is
        // nothing to fingerprint, so a file for it would be debris that
        // could never validate. An existing-but-unparseable hull still
        // bakes (to empty) and writes, so the next launch does not retry.
        ++bakes_;
        if (std::filesystem::exists(hull_nif)) {
            // Best effort: a read-only cache dir must not stop the game
            // loading, so the write's result is deliberately ignored.
            (void)bake_and_write(cache_file, hull_nif, authored_res, quality,
                                 size, mtime, field);
        }
    }

    auto [ins, _] = by_key_.emplace(key, std::move(field));
    return ins->second;
}

}  // namespace voxel
