#include <assets/gltf.h>
#include <assets/cache.h>   // AssetError
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "gltf_fixture.h"

TEST(GltfLoad, AxisMapPlacesMarkersOnBcAxes) {
    auto s = assets::gltf::load_cpu(write_fixture(tmpdir("axis")));
    ASSERT_EQ(s.meshes.size(), 1u);
    const auto& v = s.meshes[0].vertices;
    const float k = assets::gltf::kMetresToModelUnits;
    // glTF +X (1 m) -> BC -X; glTF +Y up (2 m) -> BC +Z; glTF +Z front (3 m) -> BC +Y.
    EXPECT_NEAR(v[0].position.x, -1.0f * k, 1e-6f);
    EXPECT_NEAR(v[1].position.z,  2.0f * k, 1e-6f);
    EXPECT_NEAR(v[2].position.y,  3.0f * k, 1e-6f);
    // Normal +Z (glTF front) -> BC +Y, unit length, not unit-converted.
    EXPECT_NEAR(v[0].normal.y, 1.0f, 1e-6f);
}

TEST(GltfLoad, WindingPreserved) {
    // det(+1) map: the triangle's BC-frame normal (right-hand rule over indices)
    // must equal the mapped glTF face normal.
    auto s = assets::gltf::load_cpu(write_fixture(tmpdir("wind")));
    const auto& m = s.meshes[0];
    glm::vec3 a = m.vertices[m.indices[0]].position, b = m.vertices[m.indices[1]].position,
              c = m.vertices[m.indices[2]].position;
    glm::vec3 n_bc = glm::normalize(glm::cross(b - a, c - a));
    glm::vec3 ga{1,0,0}, gb{0,2,0}, gc{0,0,3};
    glm::vec3 n_gltf = glm::normalize(glm::cross(gb - ga, gc - ga));
    glm::vec3 expect = assets::gltf::to_bc_frame(n_gltf);
    EXPECT_NEAR(glm::dot(n_bc, expect), 1.0f, 1e-5f);
}

TEST(GltfLoad, MetreCubeConvertsToModelUnits) {
    // A 1.75 m extent along glTF +X must be exactly 1 BC model unit.
    auto p = write_fixture(tmpdir("metre"), {{"scale", {1.75, 1.0, 1.0}}});
    auto s = assets::gltf::load_cpu(p);
    EXPECT_NEAR(std::abs(s.meshes[0].vertices[0].position.x), 1.0f, 1e-5f);
}

TEST(GltfLoad, ScaleMultipliesPositionsNotNormals) {
    auto s = assets::gltf::load_cpu(write_fixture(tmpdir("scale")), 2.0f);
    EXPECT_NEAR(s.meshes[0].vertices[0].position.x, -2.0f * assets::gltf::kMetresToModelUnits, 1e-6f);
    EXPECT_NEAR(glm::length(s.meshes[0].vertices[0].normal), 1.0f, 1e-5f);
}

TEST(GltfLoad, NodeTransformIsBaked) {
    // Translation (glTF) 10 m along +Y (up) -> BC +Z.
    auto s = assets::gltf::load_cpu(write_fixture(tmpdir("node"), {{"translation", {0.0, 10.0, 0.0}}}));
    EXPECT_NEAR(s.meshes[0].vertices[0].position.z, 10.0f * assets::gltf::kMetresToModelUnits, 1e-5f);
}

TEST(GltfLoad, MissingPositionThrows) {
    EXPECT_THROW(assets::gltf::load_cpu(write_fixture(tmpdir("nopos"), {}, nullptr, false)),
                 assets::AssetError);
}

TEST(GltfLoad, ExtrasVolumeResolvedRelativeToFile) {
    auto d = tmpdir("extras");
    auto s = assets::gltf::load_cpu(write_fixture(d, {}, {{"dauntless_volume", "volume.dvox"}}));
    EXPECT_EQ(s.volume, d / "volume.dvox");
}

TEST(GltfLoad, NoExtrasMeansNoVolume) {
    EXPECT_TRUE(assets::gltf::load_cpu(write_fixture(tmpdir("noextras"))).volume.empty());
}

TEST(GltfLoad, UnsupportedFeaturesWarnOnceAndStillLoad) {
    // A camera and an unknown extension are ignored with one warning per file per
    // feature, and the static mesh still loads.
    auto d = tmpdir("unsupported");
    auto p = write_fixture(d);
    auto j = nlohmann::json::parse(std::ifstream(p));
    j["cameras"] = {{{"type", "perspective"}, {"perspective", {{"yfov", 1.0}, {"znear", 0.1}}}}};
    j["extensionsUsed"] = {"KHR_materials_unlit"};
    std::ofstream(p) << j.dump();
    testing::internal::CaptureStderr();
    auto s1 = assets::gltf::load_cpu(p);
    auto s2 = assets::gltf::load_cpu(p);
    std::string err = testing::internal::GetCapturedStderr();
    EXPECT_EQ(s1.meshes.size(), 1u);
    auto count = [&](const std::string& needle) {
        size_t n = 0, at = 0; while ((at = err.find(needle, at)) != std::string::npos) { ++n; ++at; } return n; };
    EXPECT_EQ(count("ignoring cameras"), 1u);
    EXPECT_EQ(count("ignoring extensions"), 1u);
}

TEST(GltfLoad, UnreadableFileThrows) {
    EXPECT_THROW(assets::gltf::load_cpu("/nonexistent/x.gltf"), assets::AssetError);
}

TEST(GltfLoad, SparsePositionOverridesAreApplied) {
    // A sparse accessor patches ONE element (vertex 1) of the base POSITION
    // accessor to (0, 5, 0) in glTF space; vertices 0 and 2 keep their base
    // values. Reading sparse accessors correctly (via
    // cgltf_accessor_unpack_floats, not per-element cgltf_accessor_read_float)
    // matters because the latter silently returns 0 for a sparse accessor.
    auto d = tmpdir("sparse");
    auto p = write_fixture(d);
    auto j = nlohmann::json::parse(std::ifstream(p));

    // Second buffer: 2-byte sparse index (1) + 2 bytes pad (4-byte align) +
    // 12-byte VEC3 override value (0, 5, 0).
    std::vector<unsigned char> sparse_buf;
    put(sparse_buf, std::uint16_t{1});
    put(sparse_buf, std::uint16_t{0});
    float over[3] = {0.0f, 5.0f, 0.0f};
    for (float f : over) put(sparse_buf, f);

    j["buffers"].push_back({{"byteLength", sparse_buf.size()},
                             {"uri", "data:application/octet-stream;base64," + b64(sparse_buf)}});
    j["bufferViews"].push_back({{"buffer", 1}, {"byteOffset", 0}, {"byteLength", 2}});
    j["bufferViews"].push_back({{"buffer", 1}, {"byteOffset", 4}, {"byteLength", 12}});
    j["accessors"][0]["sparse"] = {
        {"count", 1},
        {"indices", {{"bufferView", 3}, {"componentType", 5123}, {"byteOffset", 0}}},
        {"values", {{"bufferView", 4}, {"byteOffset", 0}}},
    };
    std::ofstream(p) << j.dump();

    auto s = assets::gltf::load_cpu(p);
    const auto& v = s.meshes[0].vertices;
    const float k = assets::gltf::kMetresToModelUnits;
    glm::vec3 expect_v1 = assets::gltf::to_bc_frame({0.0f, 5.0f, 0.0f}) * k;
    EXPECT_NEAR(v[1].position.x, expect_v1.x, 1e-6f);
    EXPECT_NEAR(v[1].position.y, expect_v1.y, 1e-6f);
    EXPECT_NEAR(v[1].position.z, expect_v1.z, 1e-6f);
    // Vertices 0 and 2 are untouched by the sparse patch.
    EXPECT_NEAR(v[0].position.x, -1.0f * k, 1e-6f);
    EXPECT_NEAR(v[2].position.y, 3.0f * k, 1e-6f);
}
