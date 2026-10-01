// native/src/assets/include/assets/hull_source.h
//
// String encoding for a hull's source path plus an optional non-default
// import scale, e.g. for a rock-catalogue glTF loaded at less than its
// authored size. `Model::source` is the bare path when scale == 1.0f, else
// `<path>#s=<scale formatted %.6g>`.
#pragma once

#include <filesystem>
#include <string>

namespace assets {

struct HullSource {
    std::filesystem::path path;
    float scale = 1.0f;
};

/// Encode. `scale == 1.0f` yields the bare path (byte-identical to the path
/// alone, so every existing NIF-only caller is unaffected).
std::string hull_source_string(const std::filesystem::path& path, float scale);

/// Decode. Inverse of hull_source_string; a path with no `#s=` suffix
/// decodes to scale 1.0f.
HullSource split_hull_source(const std::filesystem::path& source);

/// True iff `p`'s extension is ".gltf" or ".glb", case-insensitive.
bool is_gltf_path(const std::filesystem::path& p);

}  // namespace assets
