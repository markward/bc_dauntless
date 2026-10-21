// native/src/renderer/include/renderer/structure_parts_cache.h
//
// SPIKE (damage redesign): per-hull-source cache of voxel::detect_structure_parts,
// computed on a worker thread (~0.3 s at 128 cells), so it never stalls a
// frame. Until it lands, callers get nullptr and the plating shader falls back
// to a body-axis box chart.
//
// Layered damage phase 4 §2.2: the worker starts when the ship's model is
// realised or warp-preloaded (prefetch_structure_parts), and -- once a cache
// root is pushed -- reads the segmentation from
// <root>/<fnv1a64 hex of the NIF's bytes>-v<kStructurePartsVersion>.sps
// instead of detecting, writing that file after a detection (a hull with no
// parts included; a failed detection or one with no grid is never written). A
// missing or corrupt file is detected and rewritten. With no root, nothing
// touches disk.
#pragma once
#include <filesystem>
#include <functional>
#include <vector>

#include <voxel/structure_parts.h>

namespace renderer {

/// Where `.sps` files live (paths.structure_parts_cache_root(), pushed from
/// Python at boot). Empty = no disk I/O. Read when a source's job starts.
void set_structure_parts_cache_root(const std::filesystem::path& root);

/// `source`'s cache file, or empty when there is no root, the source is a
/// glTF (catalogue rock) or a scaled load (`#s=`), or its NIF is unreadable:
/// those detect lazily with no disk I/O, as before. Reads the NIF to hash it.
std::filesystem::path structure_parts_cache_file(const std::filesystem::path& source);

/// Start `source`'s job now (read the cache file, else detect) instead of at
/// its first damaged draw. Never blocks. A no-op for an empty source, a
/// glTF (rocks never sever; their detection stays lazy) or one already started.
void prefetch_structure_parts(const std::filesystem::path& source);

// The whole segmentation (volume + labels + parts); same async job and entry
// as structure_parts_for. nullptr until ready.
const voxel::StructureSegmentation* structure_segmentation_for(
    const std::filesystem::path& source);

const std::vector<voxel::StructurePart>* structure_parts_for(
    const std::filesystem::path& source);

// Test seam: `seg` becomes `source`'s ready segmentation, replacing any
// entry (a synthetic hull with known parts, no detection job).
void set_structure_segmentation_for_test(const std::filesystem::path& source,
                                         voxel::StructureSegmentation seg);

// Test seam: jobs started from now on detect with `detect` (it may throw, as
// a real detection can) instead of reading the hull's triangles. Empty = the
// real detector. The cache-file read before it and the write after it are
// unchanged, so a test drives what gets cached.
using StructureDetector =
    std::function<voxel::StructureSegmentation(const std::filesystem::path& source)>;
void set_structure_detector_for_test(StructureDetector detect);

}  // namespace renderer
