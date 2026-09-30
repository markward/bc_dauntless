// native/tests/assets/cpu/gltf_fixture.h
//
// Shared glTF fixture-writer for assets_tests. Writes a minimal `.gltf` JSON
// with an embedded `data:application/octet-stream;base64,` buffer into a temp
// dir, so no binary fixtures are committed. `write_fixture`'s signature is
// intentionally stable across tasks -- Task 2 adds a fifth `with_texture`
// parameter without changing the first four.
#pragma once

#include <nlohmann/json.hpp>

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
// One triangle with markers: v0 on +X (glTF), v1 on +Y (up), v2 on +Z (front).
// `node` is merged into nodes[0]; `extras` into asset.extras.
inline fs::path write_fixture(const fs::path& dir, nlohmann::json node = {},
                       nlohmann::json extras = nullptr, bool with_position = true) {
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
      {"meshes", {{{"primitives", {{{"attributes", attrs},{"indices",2}}}}}}},
      {"nodes", {nlohmann::json{{"mesh",0}}}},
      {"scenes", {{{"nodes",{0}}}}}, {"scene", 0}};
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

}  // namespace
