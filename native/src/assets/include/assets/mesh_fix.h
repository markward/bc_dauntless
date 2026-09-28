// Mesh-fix file model and parser: the hull name-cut fix
// (spec: docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md).
//
// A "mesh fix" describes how to merge a small patch of geometry (an ID cut
// left over from BC's Federation saucer sections) back into its parent
// target shape at NIF load time. Fix files live at
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
    std::optional<std::vector<std::array<float, 3>>> normals;   // patch-local, one per patch vertex
};

// Top-level fix-file contents.
struct MeshFix {
    int format = 1;
    std::vector<MeshFixMerge> merges;
};

// FNV-1a 64-bit hash of `bytes`, rendered as 16 lowercase hex digits.
std::string fnv1a64_hex(std::string_view bytes);

// Parse a fix file's JSON text. On failure returns nullopt and sets *error
// (if non-null) to a human-readable message.
std::optional<MeshFix> parse_mesh_fix(std::string_view json_text, std::string* error);

// World transform (position + rotation + uniform scale, composed T*R*S up
// the parent chain from file.blocks[0]) of the block at `block_index`.
// Identity for a block with no NiNode ancestors.
glm::mat4 nif_block_world(const nif::File& file, std::size_t block_index);

// Apply every merge in `fix` to `file`, or none of them. Returns "" on
// success, otherwise the reason and leaves `file` unchanged.
std::string apply_mesh_fix(nif::File& file, const MeshFix& fix);

}  // namespace assets
