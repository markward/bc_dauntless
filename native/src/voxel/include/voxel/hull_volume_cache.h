// native/src/voxel/include/voxel/hull_volume_cache.h
#pragma once

#include <cstddef>
#include <filesystem>
#include <string>
#include <unordered_map>

#include <voxel/dhv.h>
#include <voxel/distance_field.h>

namespace voxel {

/// Default hull-volume quality multiplier: cell = authored_res / quality.
///
/// BC's authored SetDamageResolution is treated as the per-ship RATIO it
/// evidently is (Shuttle 6, Akira 8, Galaxy 10, Warbird 12, stations 15); this
/// sets absolute fidelity globally. 2 rather than 1 because a maximum-size
/// carve is 0.3 GU = 30 model units, which at a Galaxy's authored cell of 10 is
/// a 3-CELL radius -- too coarse to read as a torn hole. At 2x it is 6.
/// Memory is not the constraint: the whole 18-ship stock fleet is 1.0 MB
/// resident at 1x and 7.2 MB at 2x (MEASURED).
inline constexpr float kDefaultQuality = 2.0f;

/// Bakes a hull's signed distance field on first use and caches it on disk.
///
/// Lazy, in-memory-memoized, and keyed by hull path + authored resolution +
/// quality. A cached file is only used when its stored fingerprint still
/// matches the hull on disk AND its baker version matches this build --
/// otherwise it is rebaked. Serving a stale volume is worse than missing a
/// cache hit, because the damage volume would silently not match the geometry.
class HullVolumeCache {
public:
    explicit HullVolumeCache(std::filesystem::path cache_root);

    /// The field for `hull_nif` at this resolution and quality. Loads from
    /// disk when valid, else bakes and writes. The reference is stable for the
    /// lifetime of the cache. Returns an empty field when the hull cannot be
    /// read at all.
    const DistanceField& get(const std::filesystem::path& hull_nif,
                             float authored_res,
                             float quality);

    /// Where `get` would keep this entry. Public so callers (and tests) can
    /// reason about the cache without reaching into its internals.
    std::filesystem::path path_for(const std::filesystem::path& hull_nif,
                                   float authored_res,
                                   float quality) const;

    /// How many times this cache has actually BAKED rather than loaded.
    /// Diagnostics: first-load cost is the whole reason the cache exists, and
    /// a cache that silently never hits is indistinguishable from one that
    /// works except by this number.
    std::size_t bakes() const { return bakes_; }

private:
    std::filesystem::path root_;
    std::unordered_map<std::string, DistanceField> by_key_;
    std::size_t bakes_ = 0;
};

}  // namespace voxel
