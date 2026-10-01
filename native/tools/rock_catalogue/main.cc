// native/tools/rock_catalogue/main.cc
//
// rock_catalogue --recipe <json> --out <dir> [--only <id>]...
//
// Turns a rockgen recipe into on-disk rocks: per rock, lod<N>.gltf/.bin,
// base.png, normal.png, impostor_base.png, impostor_normal.png, volume.dvox,
// plus a catalogue.json manifest and a review/contact_sheet.png -- unless
// --only was given, in which case only the named rock(s) are (re)written and
// the manifest/contact sheet are left untouched (a drift check must never
// rewrite them).
//
// Deterministic: same recipe bytes in, byte-identical files out (rockgen's
// generation is deterministic; this tool adds no randomness or timestamps).

#include <stb_image_write.h>

#include "writer.h"

#include <rockgen/impostor.h>
#include <rockgen/recipe.h>
#include <rockgen/shape.h>
#include <rockgen/surface.h>
#include <voxel/dvox.h>
#include <voxel/voxelize.h>

#include <algorithm>
#include <cinttypes>
#include <cstdio>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <system_error>
#include <vector>

namespace fs = std::filesystem;

namespace {

std::string read_file_bytes(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) throw std::runtime_error("cannot open recipe file: " + p.string());
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

std::vector<voxel::Tri> mesh_to_tris(const assets::MeshCpu& m) {
    std::vector<voxel::Tri> tris;
    tris.reserve(m.indices.size() / 3);
    for (std::size_t i = 0; i + 2 < m.indices.size(); i += 3) {
        tris.push_back({m.vertices[m.indices[i]].position,
                         m.vertices[m.indices[i + 1]].position,
                         m.vertices[m.indices[i + 2]].position});
    }
    return tris;
}

std::string hex64(std::uint64_t v) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%016" PRIx64, v);
    return std::string(buf);
}

void print_usage() {
    std::cerr << "usage: rock_catalogue --recipe <json> --out <dir> [--only <id>]...\n";
}

}  // namespace

int main(int argc, char** argv) {
    std::string recipe_path, out_dir_str;
    std::vector<std::string> only_ids;

    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--recipe" && i + 1 < argc) {
            recipe_path = argv[++i];
        } else if (a == "--out" && i + 1 < argc) {
            out_dir_str = argv[++i];
        } else if (a == "--only" && i + 1 < argc) {
            only_ids.push_back(argv[++i]);
        } else {
            std::cerr << "rock_catalogue: unrecognized argument: " << a << "\n";
            print_usage();
            return 1;
        }
    }

    if (recipe_path.empty() || out_dir_str.empty()) {
        print_usage();
        return 1;
    }

    std::string recipe_text;
    try {
        recipe_text = read_file_bytes(recipe_path);
    } catch (const std::exception& e) {
        std::cerr << "rock_catalogue: " << e.what() << "\n";
        return 1;
    }

    rockgen::Recipe recipe;
    try {
        recipe = rockgen::parse_recipe(recipe_text);
    } catch (const std::exception& e) {
        std::cerr << "rock_catalogue: " << e.what() << "\n";
        return 1;
    }

    const std::vector<rockgen::RockSpec> all_specs = rockgen::expand_recipe(recipe);

    std::vector<rockgen::RockSpec> selected;
    if (only_ids.empty()) {
        selected = all_specs;
    } else {
        for (const auto& want : only_ids) {
            auto it = std::find_if(all_specs.begin(), all_specs.end(),
                                    [&](const rockgen::RockSpec& s) { return s.id == want; });
            if (it == all_specs.end()) {
                std::cerr << "rock_catalogue: unknown --only id: " << want << "\n";
                return 1;
            }
            selected.push_back(*it);
        }
    }

    const std::uint64_t recipe_hash = rockgen::fnv1a64(recipe_text);
    const std::string recipe_hash_hex = hex64(recipe_hash);

    const fs::path out_dir(out_dir_str);
    std::error_code ec;
    fs::create_directories(out_dir, ec);

    // Already the stb_image_write default, but the brief calls for setting it
    // explicitly: a future stb_image_write bump must not silently change the
    // committed catalogue's bytes.
    stbi_write_png_compression_level = 8;

    std::vector<rock_catalogue::RockRecord> records;
    std::vector<assets::Image> impostor_albedos;
    std::vector<glm::vec3> family_colors_b;
    records.reserve(selected.size());
    impostor_albedos.reserve(selected.size());
    family_colors_b.reserve(selected.size());

    try {
        for (const auto& spec : selected) {
            const fs::path rock_dir = out_dir / spec.id;
            fs::create_directories(rock_dir, ec);

            const std::vector<assets::MeshCpu> lods = rockgen::generate_rock_lods(spec);
            const rockgen::RockSurface surf = rockgen::generate_rock_surface(spec);
            const rockgen::Impostor imp =
                rockgen::bake_impostor(lods.at(1), surf, recipe.impostor_view_size);
            const std::vector<voxel::Tri> tris = mesh_to_tris(lods.at(0));
            const voxel::VoxelVolume vol =
                voxel::voxelize_tris(tris, glm::ivec3(recipe.volume_dims));

            rock_catalogue::RockRecord rec;
            rec.id = spec.id;
            rec.kind = spec.fragment ? "fragment" : "major";
            rec.family = spec.family->name;
            rec.bound_radius_m = spec.bound_radius_m;
            rec.avg_albedo = surf.avg_albedo;
            rec.gloss = spec.family->gloss;
            rec.impostor_grid = imp.grid;
            rec.impostor_view_size = imp.view_size;

            for (std::size_t l = 0; l < lods.size(); ++l) {
                rock_catalogue::write_gltf_lod(rock_dir, static_cast<int>(l), lods[l],
                                                "volume.dvox", recipe.tool_version);
                rec.lods.push_back(spec.id + "/lod" + std::to_string(l) + ".gltf");
            }
            rock_catalogue::write_png(rock_dir / "base.png", surf.base_color);
            rock_catalogue::write_png(rock_dir / "normal.png", surf.normal);
            rock_catalogue::write_png(rock_dir / "impostor_base.png", imp.albedo);
            rock_catalogue::write_png(rock_dir / "impostor_normal.png", imp.normal);
            if (!voxel::write_dvox(rock_dir / "volume.dvox", vol)) {
                throw std::runtime_error("failed to write volume.dvox for " + spec.id);
            }

            rec.impostor_albedo = spec.id + "/impostor_base.png";
            rec.impostor_normal = spec.id + "/impostor_normal.png";
            rec.volume = spec.id + "/volume.dvox";

            impostor_albedos.push_back(imp.albedo);
            family_colors_b.push_back(spec.family->color_b);
            records.push_back(std::move(rec));
        }

        if (only_ids.empty()) {
            rock_catalogue::write_catalogue(out_dir, recipe.tool_version, recipe_hash_hex,
                                             rockgen::impostor_view_dirs(), records);
            rock_catalogue::write_contact_sheet(out_dir, records, impostor_albedos,
                                                 family_colors_b);
        }
    } catch (const std::exception& e) {
        std::cerr << "rock_catalogue: " << e.what() << "\n";
        return 1;
    }

    return 0;
}
