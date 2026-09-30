// native/tools/rock_catalogue/writer.h
//
// File-writing half of the rock_catalogue CLI: PNGs (via stb_image_write),
// per-LOD glTF + .bin pairs (via nlohmann_json, cgltf-readable), the
// catalogue.json manifest, and the review contact sheet. No GL, no randomness
// -- deterministic given deterministic inputs.
#pragma once

#include <assets/mesh.h>
#include <assets/texture.h>

#include <glm/glm.hpp>

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace rock_catalogue {

/// One rock's manifest data, gathered while writing its files. All path
/// fields are relative to the catalogue root (e.g. "majors/silicate_01/lod0.gltf").
struct RockRecord {
    std::string id;
    std::string kind;      // "major" | "fragment"
    std::string family;
    std::vector<std::string> lods;
    float bound_radius_m = 0.0f;
    glm::vec3 avg_albedo{0.0f};
    float gloss = 0.0f;
    std::string impostor_albedo;
    std::string impostor_normal;
    int impostor_grid = 4;
    int impostor_view_size = 0;
    std::string volume;
};

/// Encode `image` as a PNG and write it to `path`. Throws std::runtime_error
/// on an encode or write failure. Assumes stbi_write_png_compression_level
/// has already been set by the caller (main() sets it once at startup).
void write_png(const std::filesystem::path& path, const assets::Image& image);

/// Write one LOD's glTF + .bin pair into `dir` (must already exist), named
/// lod<lod_index>.gltf / lod<lod_index>.bin. `volume_rel` becomes
/// asset.extras.dauntless_volume (a path relative to the gltf file, e.g.
/// "volume.dvox"). References sibling "base.png"/"normal.png" -- callers are
/// expected to have written (or be about to write) those in the same `dir`.
void write_gltf_lod(const std::filesystem::path& dir, int lod_index,
                     const assets::MeshCpu& mesh, const std::string& volume_rel,
                     int tool_version);

/// Write `out_dir/catalogue.json`: tool_version, recipe_fnv1a64_hex,
/// impostor_view_dirs, contact_sheet_order (rocks' ids, in `rocks` order),
/// and the rocks array itself.
void write_catalogue(const std::filesystem::path& out_dir, int tool_version,
                      const std::string& recipe_fnv1a64_hex,
                      const std::vector<glm::vec3>& impostor_view_dirs,
                      const std::vector<RockRecord>& rocks);

/// Write `out_dir/review/contact_sheet.png`: a 4-column grid, one cell per
/// rock (in `rocks` order), each cell showing `impostor_albedos[i]`'s view-0
/// tile (its top-left `view_size`-square block) over a 12px strip beneath
/// filled with `family_colors_b[i]` (the family's second palette colour).
/// `rocks`, `impostor_albedos` and `family_colors_b` must be the same length.
void write_contact_sheet(const std::filesystem::path& out_dir,
                          const std::vector<RockRecord>& rocks,
                          const std::vector<assets::Image>& impostor_albedos,
                          const std::vector<glm::vec3>& family_colors_b);

}  // namespace rock_catalogue
