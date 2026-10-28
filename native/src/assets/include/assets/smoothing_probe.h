#pragma once

#include <nif/file.h>

#include <cstdint>
#include <vector>

namespace assets {

/// What interior normal generation made of one authored smoothing edge (the
/// shape-diff verifier's view of normal_gen.h's SmoothingReport).
struct SmoothingRow {
    int           block;    // the shape's NIF block
    std::uint16_t a, b;     // vertex indices as authored
    bool          found;    // exactly two faces of the shape on the edge
    bool          joined_a; // those faces share one normal at a
    bool          joined_b; // ... and at b
};

/// Build `file` the way an interior set loads (generate_missing_normals) with
/// stub uploaders, so no GL context is needed, and return one row per authored
/// edge. `file` should already carry its mesh fix (apply_mesh_fix).
std::vector<SmoothingRow> probe_smoothing(const nif::File& file);

}  // namespace assets
