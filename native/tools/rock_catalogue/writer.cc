// native/tools/rock_catalogue/writer.cc
//
// STB_IMAGE_WRITE_IMPLEMENTATION lives here and only here in this tool's
// link set (rockgen, voxel, nif, assets, stb_image carry no other TU that
// defines it -- see the design brief for the grep that confirmed this).
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include <stb_image_write.h>

#include "writer.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <system_error>
#include <vector>

namespace rock_catalogue {

namespace {

using json = nlohmann::json;
namespace fs = std::filesystem;

int channel_count(assets::Image::Format f) {
    switch (f) {
        case assets::Image::Format::RGBA8: return 4;
        case assets::Image::Format::RGB8: return 3;
        case assets::Image::Format::R8: return 1;
    }
    return 4;
}

void write_binary_file(const fs::path& path, const void* data, std::size_t size) {
    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("rock_catalogue: cannot open for write: " + path.string());
    f.write(static_cast<const char*>(data), static_cast<std::streamsize>(size));
    if (!f) throw std::runtime_error("rock_catalogue: write failed: " + path.string());
}

}  // namespace

void write_png(const fs::path& path, const assets::Image& image) {
    const int comp = channel_count(image.format);
    const int stride = static_cast<int>(image.width) * comp;

    std::vector<std::uint8_t> encoded;
    auto write_fn = [](void* context, void* data, int size) {
        auto* out = static_cast<std::vector<std::uint8_t>*>(context);
        const auto* bytes = static_cast<std::uint8_t*>(data);
        out->insert(out->end(), bytes, bytes + size);
    };

    const int ok = stbi_write_png_to_func(write_fn, &encoded, static_cast<int>(image.width),
                                           static_cast<int>(image.height), comp,
                                           image.pixels.data(), stride);
    if (!ok) throw std::runtime_error("rock_catalogue: failed to encode png: " + path.string());
    write_binary_file(path, encoded.data(), encoded.size());
}

void write_gltf_lod(const fs::path& dir, int lod_index, const assets::MeshCpu& mesh,
                     const std::string& volume_rel, int tool_version) {
    const std::string bin_name = "lod" + std::to_string(lod_index) + ".bin";
    const std::string gltf_name = "lod" + std::to_string(lod_index) + ".gltf";

    const std::size_t vertex_count = mesh.vertices.size();
    const std::size_t index_count = mesh.indices.size();

    const std::size_t pos_bytes = vertex_count * sizeof(glm::vec3);
    const std::size_t nrm_bytes = vertex_count * sizeof(glm::vec3);
    const std::size_t uv_bytes = vertex_count * sizeof(glm::vec2);
    const std::size_t idx_bytes = index_count * sizeof(std::uint32_t);

    const std::size_t pos_offset = 0;
    const std::size_t nrm_offset = pos_offset + pos_bytes;
    const std::size_t uv_offset = nrm_offset + nrm_bytes;
    const std::size_t idx_offset = uv_offset + uv_bytes;
    const std::size_t total_bytes = idx_offset + idx_bytes;

    // Write the .bin: positions, normals, uvs, indices, each already
    // 4-byte-aligned (every field is a 4-byte float or uint32).
    {
        std::ofstream bin(dir / bin_name, std::ios::binary);
        if (!bin) {
            throw std::runtime_error("rock_catalogue: cannot open for write: " +
                                      (dir / bin_name).string());
        }
        for (const auto& v : mesh.vertices)
            bin.write(reinterpret_cast<const char*>(&v.position), sizeof(glm::vec3));
        for (const auto& v : mesh.vertices)
            bin.write(reinterpret_cast<const char*>(&v.normal), sizeof(glm::vec3));
        for (const auto& v : mesh.vertices)
            bin.write(reinterpret_cast<const char*>(&v.uv), sizeof(glm::vec2));
        if (!mesh.indices.empty()) {
            bin.write(reinterpret_cast<const char*>(mesh.indices.data()),
                       static_cast<std::streamsize>(idx_bytes));
        }
        if (!bin) {
            throw std::runtime_error("rock_catalogue: write failed: " + (dir / bin_name).string());
        }
    }

    // POSITION min/max, in the glTF frame the mesh is already expressed in.
    glm::vec3 pmin(std::numeric_limits<float>::max());
    glm::vec3 pmax(std::numeric_limits<float>::lowest());
    for (const auto& v : mesh.vertices) {
        pmin = glm::min(pmin, v.position);
        pmax = glm::max(pmax, v.position);
    }
    if (mesh.vertices.empty()) pmin = pmax = glm::vec3(0.0f);

    json asset;
    asset["version"] = "2.0";
    asset["generator"] = "dauntless rock_catalogue " + std::to_string(tool_version);
    json extras;
    extras["dauntless_volume"] = volume_rel;
    asset["extras"] = extras;

    json buffer;
    buffer["uri"] = bin_name;
    buffer["byteLength"] = total_bytes;

    json bv_pos, bv_nrm, bv_uv, bv_idx;
    bv_pos["buffer"] = 0; bv_pos["byteOffset"] = pos_offset; bv_pos["byteLength"] = pos_bytes;
    bv_pos["target"] = 34962;  // ARRAY_BUFFER
    bv_nrm["buffer"] = 0; bv_nrm["byteOffset"] = nrm_offset; bv_nrm["byteLength"] = nrm_bytes;
    bv_nrm["target"] = 34962;
    bv_uv["buffer"] = 0; bv_uv["byteOffset"] = uv_offset; bv_uv["byteLength"] = uv_bytes;
    bv_uv["target"] = 34962;
    bv_idx["buffer"] = 0; bv_idx["byteOffset"] = idx_offset; bv_idx["byteLength"] = idx_bytes;
    bv_idx["target"] = 34963;  // ELEMENT_ARRAY_BUFFER

    json acc_pos, acc_nrm, acc_uv, acc_idx;
    acc_pos["bufferView"] = 0; acc_pos["byteOffset"] = 0;
    acc_pos["componentType"] = 5126;  // FLOAT
    acc_pos["count"] = vertex_count; acc_pos["type"] = "VEC3";
    acc_pos["min"] = json::array({pmin.x, pmin.y, pmin.z});
    acc_pos["max"] = json::array({pmax.x, pmax.y, pmax.z});

    acc_nrm["bufferView"] = 1; acc_nrm["byteOffset"] = 0;
    acc_nrm["componentType"] = 5126;
    acc_nrm["count"] = vertex_count; acc_nrm["type"] = "VEC3";

    acc_uv["bufferView"] = 2; acc_uv["byteOffset"] = 0;
    acc_uv["componentType"] = 5126;
    acc_uv["count"] = vertex_count; acc_uv["type"] = "VEC2";

    acc_idx["bufferView"] = 3; acc_idx["byteOffset"] = 0;
    acc_idx["componentType"] = 5125;  // UNSIGNED_INT
    acc_idx["count"] = index_count; acc_idx["type"] = "SCALAR";

    json image_base, image_normal;
    image_base["uri"] = "base.png";
    image_normal["uri"] = "normal.png";

    json sampler = json::object();

    json tex_base, tex_normal;
    tex_base["sampler"] = 0; tex_base["source"] = 0;
    tex_normal["sampler"] = 0; tex_normal["source"] = 1;

    json base_color_texture;
    base_color_texture["index"] = 0;
    json pbr;
    pbr["baseColorTexture"] = base_color_texture;
    pbr["metallicFactor"] = 0;
    pbr["roughnessFactor"] = 1;
    json normal_texture;
    normal_texture["index"] = 1;
    json material;
    material["pbrMetallicRoughness"] = pbr;
    material["normalTexture"] = normal_texture;

    json attributes;
    attributes["POSITION"] = 0;
    attributes["NORMAL"] = 1;
    attributes["TEXCOORD_0"] = 2;
    json primitive;
    primitive["attributes"] = attributes;
    primitive["indices"] = 3;
    primitive["material"] = 0;
    json mesh_j;
    mesh_j["primitives"] = json::array({primitive});

    json node;
    node["mesh"] = 0;

    json scene;
    scene["nodes"] = json::array({0});

    json root;
    root["asset"] = asset;
    root["buffers"] = json::array({buffer});
    root["bufferViews"] = json::array({bv_pos, bv_nrm, bv_uv, bv_idx});
    root["accessors"] = json::array({acc_pos, acc_nrm, acc_uv, acc_idx});
    root["images"] = json::array({image_base, image_normal});
    root["samplers"] = json::array({sampler});
    root["textures"] = json::array({tex_base, tex_normal});
    root["materials"] = json::array({material});
    root["meshes"] = json::array({mesh_j});
    root["nodes"] = json::array({node});
    root["scenes"] = json::array({scene});
    root["scene"] = 0;

    const std::string text = root.dump(1);
    write_binary_file(dir / gltf_name, text.data(), text.size());
}

void write_catalogue(const fs::path& out_dir, int tool_version,
                      const std::string& recipe_fnv1a64_hex,
                      const std::vector<glm::vec3>& impostor_view_dirs,
                      const std::vector<RockRecord>& rocks,
                      const std::vector<CollectionRecord>& collections) {
    json dirs = json::array();
    for (const auto& d : impostor_view_dirs) dirs.push_back(json::array({d.x, d.y, d.z}));

    json rocks_j = json::array();
    json order = json::array();
    for (const auto& r : rocks) {
        json impostor;
        impostor["albedo"] = r.impostor_albedo;
        impostor["normal"] = r.impostor_normal;
        impostor["grid"] = r.impostor_grid;
        impostor["view_size"] = r.impostor_view_size;

        json rj;
        rj["id"] = r.id;
        rj["kind"] = r.kind;
        rj["family"] = r.family;
        rj["lods"] = r.lods;
        rj["bound_radius_m"] = r.bound_radius_m;
        rj["avg_albedo"] = json::array({r.avg_albedo.x, r.avg_albedo.y, r.avg_albedo.z});
        rj["gloss"] = r.gloss;
        rj["impostor"] = impostor;
        rj["volume"] = r.volume;

        rocks_j.push_back(rj);
        order.push_back(r.id);
    }

    json cols_j = json::array();
    for (const auto& c : collections) {
        json impostor;
        impostor["albedo"] = c.impostor_albedo;
        impostor["normal"] = c.impostor_normal;
        impostor["grid"] = c.impostor_grid;
        impostor["view_size"] = c.impostor_view_size;

        json cj;
        cj["id"] = c.id;
        cj["variant"] = c.variant;
        cj["impostor"] = impostor;
        cj["avg_albedo"] = json::array({c.avg_albedo.x, c.avg_albedo.y, c.avg_albedo.z});
        cols_j.push_back(cj);
    }

    json root;
    root["tool_version"] = tool_version;
    root["recipe_fnv1a64"] = recipe_fnv1a64_hex;
    root["impostor_view_dirs"] = dirs;
    root["contact_sheet_order"] = order;
    root["rocks"] = rocks_j;
    root["collections"] = cols_j;

    const std::string text = root.dump(1);
    std::error_code ec;
    fs::create_directories(out_dir, ec);
    write_binary_file(out_dir / "catalogue.json", text.data(), text.size());
}

void write_contact_sheet(const fs::path& out_dir, const std::vector<RockRecord>& rocks,
                          const std::vector<assets::Image>& impostor_albedos,
                          const std::vector<glm::vec3>& family_colors_b) {
    if (rocks.empty()) return;

    constexpr int kCols = 4;
    constexpr int kStrip = 12;
    const int view_size = rocks[0].impostor_view_size;
    const int rows = static_cast<int>((rocks.size() + kCols - 1) / kCols);
    const int cell_h = view_size + kStrip;
    const int width = kCols * view_size;
    const int height = rows * cell_h;

    std::vector<std::uint8_t> canvas(static_cast<std::size_t>(width) * height * 4, 0);

    for (std::size_t i = 0; i < rocks.size(); ++i) {
        const int col = static_cast<int>(i % kCols);
        const int row = static_cast<int>(i / kCols);
        const int ox = col * view_size;
        const int oy = row * cell_h;

        const assets::Image& src = impostor_albedos[i];
        for (int y = 0; y < view_size; ++y) {
            for (int x = 0; x < view_size; ++x) {
                const std::size_t src_i =
                    (static_cast<std::size_t>(y) * src.width + static_cast<std::size_t>(x)) * 4;
                const std::size_t dst_i =
                    (static_cast<std::size_t>(oy + y) * width + static_cast<std::size_t>(ox + x)) * 4;
                for (int c = 0; c < 4; ++c) canvas[dst_i + c] = src.pixels[src_i + c];
            }
        }

        const glm::vec3& cb = family_colors_b[i];
        const auto to_byte = [](float v) {
            return static_cast<std::uint8_t>(std::clamp(v, 0.0f, 1.0f) * 255.0f + 0.5f);
        };
        const std::uint8_t r = to_byte(cb.r), g = to_byte(cb.g), b = to_byte(cb.b);
        for (int y = 0; y < kStrip; ++y) {
            for (int x = 0; x < view_size; ++x) {
                const std::size_t dst_i = (static_cast<std::size_t>(oy + view_size + y) * width +
                                            static_cast<std::size_t>(ox + x)) * 4;
                canvas[dst_i + 0] = r;
                canvas[dst_i + 1] = g;
                canvas[dst_i + 2] = b;
                canvas[dst_i + 3] = 255;
            }
        }
    }

    const fs::path review_dir = out_dir / "review";
    std::error_code ec;
    fs::create_directories(review_dir, ec);

    assets::Image img;
    img.width = static_cast<std::uint32_t>(width);
    img.height = static_cast<std::uint32_t>(height);
    img.format = assets::Image::Format::RGBA8;
    img.pixels = std::move(canvas);
    write_png(review_dir / "contact_sheet.png", img);
}

}  // namespace rock_catalogue
