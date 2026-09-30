// native/tests/assets/cpu/gltf_fixture.h
//
// Shared glTF fixture-writer for assets_tests. Writes a minimal `.gltf` JSON
// with an embedded `data:application/octet-stream;base64,` buffer into a temp
// dir, so no binary fixtures are committed. `write_fixture`'s signature is
// intentionally stable across tasks -- Task 2 adds a fifth `with_texture`
// parameter without changing the first four.
//
// `with_texture=true` also writes a real 2x2 PNG (via stb_image_write) next
// to the .gltf and wires it in as the mesh's sole material's baseColorTexture.
// Only the DECLARATIONS are needed here; exactly one assets_tests TU
// (gltf_model_test.cc) defines STB_IMAGE_WRITE_IMPLEMENTATION before pulling
// in this header, so the symbols this file calls resolve at link time.
#pragma once

#include <nlohmann/json.hpp>
#include <stb_image_write.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

inline std::string b64(const std::vector<unsigned char>& in) {
    static const char* t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out; int val = 0, bits = -6;
    for (unsigned char c : in) { val = (val << 8) + c; bits += 8;
        while (bits >= 0) { out.push_back(t[(val >> bits) & 0x3F]); bits -= 6; } }
    if (bits > -6) out.push_back(t[((val << 8) >> (bits + 8)) & 0x3F]);
    while (out.size() % 4) out.push_back('=');
    return out;
}
template <class T> void put(std::vector<unsigned char>& b, const T& v) {
    auto* p = reinterpret_cast<const unsigned char*>(&v); b.insert(b.end(), p, p + sizeof(T));
}
// A valid 2x2 RGBA PNG (red, green, blue, yellow pixels), byte-for-byte
// identical to what write_fixture's with_texture branch writes via
// stbi_write_png. Hand-encoded (not generated with stb_image_write) so this
// header never needs the STB_IMAGE_WRITE_IMPLEMENTATION TU to build or link
// -- native/tests/voxel links no such TU, and its two tests that include this
// header (source_cache_test.cc, hull_volume_cache_test.cc) must keep linking.
inline constexpr unsigned char kFixturePng[] = {
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
    0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02,
    0x08, 0x06, 0x00, 0x00, 0x00, 0x72, 0xb6, 0x0d, 0x24, 0x00, 0x00, 0x00,
    0x14, 0x49, 0x44, 0x41, 0x54, 0x78, 0xda, 0x63, 0xf8, 0xcf, 0xc0, 0xf0,
    0x1f, 0x0c, 0x81, 0x34, 0x10, 0x30, 0xfc, 0x07, 0x00, 0x47, 0xca, 0x08,
    0xf8, 0x5b, 0x9a, 0xa4, 0xbe, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e,
    0x44, 0xae, 0x42, 0x60, 0x82,
};
// One triangle with markers: v0 on +X (glTF), v1 on +Y (up), v2 on +Z (front).
// `node` is merged into nodes[0]; `extras` into asset.extras. `with_texture`
// adds a material (baseColorTexture -> a real 2x2 PNG written beside the
// .gltf) and points the sole primitive at it.
inline fs::path write_fixture(const fs::path& dir, nlohmann::json node = {},
                       nlohmann::json extras = nullptr, bool with_position = true,
                       bool with_texture = false, bool with_data_uri_texture = false) {
    fs::create_directories(dir);
    std::vector<unsigned char> buf;
    float pos[9] = {1,0,0, 0,2,0, 0,0,3};
    float nrm[9] = {0,0,1, 0,0,1, 0,0,1};
    for (float f : pos) put(buf, f);
    for (float f : nrm) put(buf, f);
    std::uint16_t idx[3] = {0,1,2}; for (auto i : idx) put(buf, i);
    put(buf, std::uint16_t{0});                         // pad to 4
    nlohmann::json attrs = {{"NORMAL", 1}};
    if (with_position) attrs["POSITION"] = 0;
    nlohmann::json prim = {{"attributes", attrs}, {"indices", 2}};
    if (with_texture || with_data_uri_texture) prim["material"] = 0;
    nlohmann::json j = {
      {"asset", {{"version", "2.0"}}},
      {"buffers", {{{"byteLength", buf.size()},
                    {"uri", "data:application/octet-stream;base64," + b64(buf)}}}},
      {"bufferViews", {{{"buffer",0},{"byteOffset",0},{"byteLength",36}},
                       {{"buffer",0},{"byteOffset",36},{"byteLength",36}},
                       {{"buffer",0},{"byteOffset",72},{"byteLength",6}}}},
      {"accessors", {{{"bufferView",0},{"componentType",5126},{"count",3},{"type","VEC3"},
                      {"min",{0,0,0}},{"max",{1,2,3}}},
                     {{"bufferView",1},{"componentType",5126},{"count",3},{"type","VEC3"}},
                     {{"bufferView",2},{"componentType",5123},{"count",3},{"type","SCALAR"}}}},
      {"meshes", {{{"primitives", {prim}}}}},
      {"nodes", {nlohmann::json{{"mesh",0}}}},
      {"scenes", {{{"nodes",{0}}}}}, {"scene", 0}};
    if (with_texture) {
        // A real 2x2 RGBA PNG, written next to the .gltf so gltf::load_cpu's
        // relative-URI resolution finds it.
        const unsigned char pixels[2 * 2 * 4] = {
            255, 0,   0,   255,   0, 255,   0, 255,
              0, 0, 255,   255, 255, 255,   0, 255,
        };
        auto png_path = dir / "tex.png";
        stbi_write_png(png_path.string().c_str(), 2, 2, 4, pixels, 2 * 4);
        j["images"] = {{{"uri", "tex.png"}}};
        j["textures"] = {{{"source", 0}}};
        j["materials"] = {{{"pbrMetallicRoughness",
                             {{"baseColorTexture", {{"index", 0}}}}}}};
    }
    if (with_data_uri_texture) {
        // The same 2x2 PNG as with_texture, embedded as a base64 data URI
        // instead of written to a sidecar file.
        std::vector<unsigned char> png(std::begin(kFixturePng), std::end(kFixturePng));
        j["images"] = {{{"uri", "data:image/png;base64," + b64(png)}}};
        j["textures"] = {{{"source", 0}}};
        j["materials"] = {{{"pbrMetallicRoughness",
                             {{"baseColorTexture", {{"index", 0}}}}}}};
    }
    for (auto& [k, v] : node.items()) j["nodes"][0][k] = v;
    if (!extras.is_null()) j["asset"]["extras"] = extras;
    auto p = dir / "fixture.gltf";
    std::ofstream(p) << j.dump();
    return p;
}
inline fs::path tmpdir(const char* name) {
    auto d = fs::temp_directory_path() / ("gltf_load_test_" + std::string(name));
    fs::remove_all(d); return d;
}

// A closed, 12-triangle cube (2 tris/face), CCW outward-facing winding, in
// glTF metres, centred on the origin with half-extent `half_m`. POSITION
// only (no NORMAL/TEXCOORD) -- the loader derives flat per-triangle normals.
// `extras` is merged into asset.extras (e.g. {{"dauntless_volume", "..."}})
// exactly as write_fixture does; pass nullptr for none.
inline fs::path write_cube_fixture(const fs::path& dir, float half_m,
                                    nlohmann::json extras = nullptr) {
    fs::create_directories(dir);
    const float h = half_m;
    const float corners[8][3] = {
        {-h,-h,-h}, {h,-h,-h}, {h,h,-h}, {-h,h,-h},
        {-h,-h, h}, {h,-h, h}, {h,h, h}, {-h,h, h},
    };
    std::vector<unsigned char> buf;
    for (const auto& c : corners) for (float f : c) put(buf, f);
    const std::size_t pos_bytes = buf.size();  // 8 * 3 * 4 = 96

    const std::uint16_t idx[36] = {
        0,3,2, 0,2,1,   // -Z
        4,5,6, 4,6,7,   // +Z
        0,1,5, 0,5,4,   // -Y
        2,3,7, 2,7,6,   // +Y
        0,4,7, 0,7,3,   // -X
        1,2,6, 1,6,5,   // +X
    };
    for (auto i : idx) put(buf, i);
    const std::size_t idx_bytes = buf.size() - pos_bytes;  // 36 * 2 = 72

    nlohmann::json prim = {{"attributes", {{"POSITION", 0}}}, {"indices", 1}};
    nlohmann::json j = {
      {"asset", {{"version", "2.0"}}},
      {"buffers", {{{"byteLength", buf.size()},
                    {"uri", "data:application/octet-stream;base64," + b64(buf)}}}},
      {"bufferViews", {{{"buffer",0},{"byteOffset",0},{"byteLength",pos_bytes}},
                       {{"buffer",0},{"byteOffset",pos_bytes},{"byteLength",idx_bytes}}}},
      {"accessors", {{{"bufferView",0},{"componentType",5126},{"count",8},{"type","VEC3"},
                      {"min",{-h,-h,-h}},{"max",{h,h,h}}},
                     {{"bufferView",1},{"componentType",5123},{"count",36},{"type","SCALAR"}}}},
      {"meshes", {{{"primitives", {prim}}}}},
      {"nodes", {nlohmann::json{{"mesh",0}}}},
      {"scenes", {{{"nodes",{0}}}}}, {"scene", 0}};
    if (!extras.is_null()) j["asset"]["extras"] = extras;
    auto p = dir / "cube.gltf";
    std::ofstream(p) << j.dump();
    return p;
}

// The Task 1 triangle fixture, written as a real `.glb` binary: a 12-byte
// header (magic "glTF", version 2, total length), a JSON chunk (type
// 0x4E4F534A "JSON", space-padded to a multiple of 4), then a BIN chunk
// (type 0x004E4942 "BIN\0", zero-padded to a multiple of 4) holding the
// triangle's geometry and, when `embed_texture`, `kFixturePng` referenced by
// `images[0] = {bufferView, mimeType: "image/png"}`.
inline fs::path write_glb_fixture(const fs::path& dir, bool embed_texture) {
    fs::create_directories(dir);

    std::vector<unsigned char> bin;
    float pos[9] = {1, 0, 0, 0, 2, 0, 0, 0, 3};
    float nrm[9] = {0, 0, 1, 0, 0, 1, 0, 0, 1};
    for (float f : pos) put(bin, f);
    for (float f : nrm) put(bin, f);
    std::uint16_t idx[3] = {0, 1, 2};
    for (auto i : idx) put(bin, i);
    put(bin, std::uint16_t{0});  // pad to 4

    nlohmann::json j = {
      {"asset", {{"version", "2.0"}}},
      {"buffers", {{{"byteLength", bin.size()}}}},  // no "uri": GLB BIN chunk
      {"bufferViews", {{{"buffer",0},{"byteOffset",0},{"byteLength",36}},
                       {{"buffer",0},{"byteOffset",36},{"byteLength",36}},
                       {{"buffer",0},{"byteOffset",72},{"byteLength",6}}}},
      {"accessors", {{{"bufferView",0},{"componentType",5126},{"count",3},{"type","VEC3"},
                      {"min",{0,0,0}},{"max",{1,2,3}}},
                     {{"bufferView",1},{"componentType",5126},{"count",3},{"type","VEC3"}},
                     {{"bufferView",2},{"componentType",5123},{"count",3},{"type","SCALAR"}}}},
      {"meshes", {{{"primitives", {{{"attributes", {{"POSITION",0},{"NORMAL",1}}},
                                    {"indices",2}}}}}}},
      {"nodes", {nlohmann::json{{"mesh",0}}}},
      {"scenes", {{{"nodes",{0}}}}}, {"scene", 0}};

    if (embed_texture) {
        const std::size_t png_offset = bin.size();
        bin.insert(bin.end(), std::begin(kFixturePng), std::end(kFixturePng));
        j["bufferViews"].push_back({{"buffer",0},{"byteOffset",png_offset},
                                     {"byteLength", sizeof(kFixturePng)}});
        j["images"] = {{{"bufferView", 3}, {"mimeType", "image/png"}}};
        j["textures"] = {{{"source", 0}}};
        j["materials"] = {{{"pbrMetallicRoughness",
                             {{"baseColorTexture", {{"index", 0}}}}}}};
        j["meshes"][0]["primitives"][0]["material"] = 0;
        j["buffers"][0]["byteLength"] = bin.size();
    }

    while (bin.size() % 4 != 0) bin.push_back(0);  // BIN chunk padding (zeros)

    std::string json_str = j.dump();
    while (json_str.size() % 4 != 0) json_str.push_back(' ');  // JSON chunk padding (spaces)

    const std::uint32_t json_chunk_len = static_cast<std::uint32_t>(json_str.size());
    const std::uint32_t bin_chunk_len = static_cast<std::uint32_t>(bin.size());
    const std::uint32_t total_len =
        12 + 8 + json_chunk_len + 8 + bin_chunk_len;

    std::vector<unsigned char> glb;
    glb.insert(glb.end(), {'g', 'l', 'T', 'F'});
    put(glb, std::uint32_t{2});
    put(glb, total_len);
    put(glb, json_chunk_len);
    put(glb, std::uint32_t{0x4E4F534Au});  // "JSON"
    glb.insert(glb.end(), json_str.begin(), json_str.end());
    put(glb, bin_chunk_len);
    put(glb, std::uint32_t{0x004E4942u});  // "BIN\0"
    glb.insert(glb.end(), bin.begin(), bin.end());

    auto p = dir / "fixture.glb";
    std::ofstream out(p, std::ios::binary);
    out.write(reinterpret_cast<const char*>(glb.data()), static_cast<std::streamsize>(glb.size()));
    return p;
}

}  // namespace
