// native/src/voxel/include/voxel/dhv.h
#pragma once

#include <cstdint>
#include <filesystem>
#include <string>

#include <voxel/distance_field.h>

namespace voxel {

/// Bump whenever bake OUTPUT changes for the same inputs. Every cached file
/// carries it, and read_dhv rejects any mismatch, so a baker change
/// invalidates the whole cache without anyone having to remember to clear it.
inline constexpr std::uint16_t kBakerVersion = 1;

/// Provenance stored alongside the field, so a cache entry can be validated
/// against the hull it claims to describe.
struct HullVolumeMeta {
    std::uint16_t baker_version = kBakerVersion;
    std::uint32_t source_size   = 0;   // hull nif size in bytes
    std::int64_t  source_mtime  = 0;   // hull nif mtime, unix seconds
    float         authored_res  = 0.0f;  // SetDamageResolution, as given
    float         quality       = 0.0f;  // cell = authored_res / quality
    std::string   source_path;           // diagnosis only, never for lookup
};

/// Write `field` + `meta` to `path`, creating parent directories. Writes to a
/// sibling temporary and renames, so a crash mid-write cannot leave a
/// half-written file where a valid one is expected. False on any I/O failure.
bool write_dhv(const std::filesystem::path& path,
               const DistanceField& field,
               const HullVolumeMeta& meta);

/// Read `path`. Returns false -- and leaves the outputs untouched -- for a
/// missing file, a bad magic, a format or baker version mismatch, an
/// implausibly long source_path, implausible dimensions, or a payload
/// shorter than the header says. The caller's only correct response to
/// false is to rebake.
bool read_dhv(const std::filesystem::path& path,
              DistanceField& out_field,
              HullVolumeMeta& out_meta);

}  // namespace voxel
