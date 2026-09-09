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
///
/// Fingerprint limitation: (source_size, source_mtime) cannot detect an edit
/// that happens to keep the byte count identical AND lands within the same
/// mtime tick -- plausible on a filesystem with coarse mtime resolution (some
/// report only 1-2 second granularity). Such an edit would be served stale.
/// This is a known, accepted gap in the fingerprint scheme, not something a
/// caller can work around; do not silently widen it (e.g. by relaxing the
/// size/mtime comparison further) without addressing this note.
struct HullVolumeMeta {
    std::uint16_t baker_version = kBakerVersion;
    std::uint32_t source_size   = 0;   // hull nif size in bytes
    // hull nif mtime -- NOT unix seconds. It is
    // std::filesystem::last_write_time(...).time_since_epoch().count(): raw
    // filesystem-clock ticks, whose unit and epoch are implementation-defined
    // (see hull_volume_cache.cc's mtime_of). Only ever compared for equality
    // against a fresh read of the same file on the same build, never
    // interpreted as a real timestamp, so this is harmless -- but a toolchain
    // change to the clock's epoch or tick period invalidates the whole cache
    // (it just rebakes, which should not surprise anyone reading this field).
    std::int64_t  source_mtime  = 0;
    float         authored_res  = 0.0f;  // SetDamageResolution, as given
    float         quality       = 0.0f;  // cell = authored_res / quality
    // Diagnosis, AND a validation check once a file is already loaded (a
    // hashed cache filename can collide across distinct (hull, res, quality)
    // tuples) -- never for LOOKUP: nothing may scan the cache directory by
    // source_path to find an entry.
    std::string   source_path;
};

/// Write `field` + `meta` to `path`, creating parent directories. Writes to a
/// sibling temporary and renames, so a crash mid-write cannot leave a
/// half-written file where a valid one is expected. False on any I/O failure.
bool write_dhv(const std::filesystem::path& path,
               const DistanceField& field,
               const HullVolumeMeta& meta);

/// Read `path`. Returns false -- and leaves the outputs untouched -- for a
/// missing file, a bad magic, a format or baker version mismatch, an
/// implausibly long source_path, implausible dimensions, a non-finite or
/// non-positive `cell` component, a non-finite or non-positive `scale`, or a
/// payload shorter than the header says. The caller's only correct response
/// to false is to rebake.
///
/// The cell/scale checks matter because this file is untrusted input: a
/// corrupt `scale` makes DistanceField::distance_at return NaN for every
/// cell, and a zero or negative `cell` component divides through in any
/// consumer converting a body-frame point to a cell index.
///
/// "Implausible dimensions" has one deliberate exemption: dims == (0,0,0) is
/// accepted, not rejected, because it is the documented return of
/// distance_field_from_tris() for a hull with no triangles (missing source,
/// unparseable NIF, or a genuinely empty mesh) -- see distance_field.h. That
/// is a legitimate bake result and must round-trip like any other. Only a
/// MIXED zero/negative combination (one axis zero or negative while another
/// is not) is still rejected as a malformed grid.
bool read_dhv(const std::filesystem::path& path,
              DistanceField& out_field,
              HullVolumeMeta& out_meta);

}  // namespace voxel
