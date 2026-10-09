// Mesh-fix file model and parser: the hull name-cut fix
// (spec: docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md) and
// the bridge-shape-diff shape-edit op (spec:
// docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md).
//
// A "mesh fix" file carries "merges", "shape_edits", or both. A merge
// describes how to merge a small patch of geometry (an ID cut left over from
// BC's Federation saucer sections) back into its parent target shape at NIF
// load time. A shape edit is an opaque "BSD1" binary payload (base64 in the
// file) describing per-shape vertex moves/UV edits/additions/triangle
// add-remove, applied against a NIF in apply_mesh_fix (decode-only here;
// validation against a loaded NIF is a later phase). Fix files live at
// native/assets/mesh_fixes/<fnv1a64-of-nif-bytes>.json and are matched to a
// loaded NIF by content hash, not by filename.
#pragma once

#include <nif/file.h>

#include <glm/glm.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace assets {

// A single named/numbered NiTriShape reference inside a NIF's block list.
struct MeshFixShapeRef {
    std::uint32_t block = 0;
    std::string name;
};

// One patch-to-target merge: the patch shape's vertices are welded onto the
// target shape at the listed vertex-index pairs, with UVs (and optionally
// patch-local normals) carried over per patch vertex.
struct MeshFixMerge {
    MeshFixShapeRef patch;
    MeshFixShapeRef target;
    std::vector<std::array<float, 2>> uvs;                     // one per patch vertex
    std::vector<std::pair<std::uint32_t, std::uint32_t>> weld;  // (patch v, target v)
    // patch-local, one per patch vertex; rotated into the target shape's
    // frame the same way as the patch's own NiTriShapeData normals.
    std::optional<std::vector<std::array<float, 3>>> normals;
};

// One added vertex in a ShapeEdit's add_vertices list (shape-local space).
struct ShapeEditAddVertex {
    std::array<float, 3> pos;     // shape-local
    std::array<float, 2> uv0;
    std::array<float, 2> uv1;     // ignored if the shape has 1 UV set
    std::array<float, 4> color;   // ignored if the shape has no colours
};

// One shape's worth of edits decoded from a "BSD1" shape-edit payload.
// Structural only: ranges (e.g. vertex/triangle indices against the actual
// shape) are not checked until apply_mesh_fix.
struct ShapeEdit {
    std::uint32_t block = 0;
    std::uint16_t orig_vertex_count = 0;
    std::uint16_t orig_triangle_count = 0;
    std::vector<std::pair<std::uint16_t, std::array<float, 3>>> moves;
    std::vector<std::pair<std::uint16_t, std::array<float, 2>>> uvs;
    std::vector<ShapeEditAddVertex> add_vertices;
    std::vector<std::uint16_t> remove_triangles;
    std::vector<std::array<std::uint16_t, 3>> add_triangles;
};

// Top-level fix-file contents.
struct MeshFix {
    int format = 1;
    std::vector<MeshFixMerge> merges;
    std::vector<ShapeEdit> shape_edits;
};

// FNV-1a 64-bit hash of `bytes`, rendered as 16 lowercase hex digits.
std::string fnv1a64_hex(std::string_view bytes);

// Parse a fix file's JSON text. On failure returns nullopt and sets *error
// (if non-null) to a human-readable message.
std::optional<MeshFix> parse_mesh_fix(std::string_view json_text, std::string* error);

// Standard base64 (RFC 4648, '=' padding, no whitespace). nullopt on any
// illegal character or a length that is not a multiple of 4.
std::optional<std::string> base64_decode(std::string_view text);

// Decode a "BSD1" shape-edit payload (spec 2026-10-09-bridge-shape-diff
// §6.1). Structural checks only -- range checks against a NIF happen in
// apply_mesh_fix. Refuses bad magic, truncation and trailing bytes.
std::optional<std::vector<ShapeEdit>> decode_shape_edits(std::string_view bytes,
                                                         std::string* error);

// World transform (position + rotation + uniform scale, composed T*R*S up
// the parent chain from file.blocks[0]) of the block at `block_index`.
// Identity for a block with no NiNode ancestors.
glm::mat4 nif_block_world(const nif::File& file, std::size_t block_index);

// Apply every merge in `fix` to `file`, or none of them. Returns "" on
// success, otherwise the reason and leaves `file` unchanged.
std::string apply_mesh_fix(nif::File& file, const MeshFix& fix);

}  // namespace assets
