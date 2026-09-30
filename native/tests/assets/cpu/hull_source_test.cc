#include <assets/hull_source.h>
#include <gtest/gtest.h>

TEST(HullSource, UnitScaleIsBarePath) {
    EXPECT_EQ(assets::hull_source_string("/a/b.nif", 1.0f), "/a/b.nif");
}
TEST(HullSource, RoundTripsScale) {
    auto s = assets::hull_source_string("/r/lod0.gltf", 0.402f);
    EXPECT_EQ(s, "/r/lod0.gltf#s=0.402");
    auto h = assets::split_hull_source(s);
    EXPECT_EQ(h.path, std::filesystem::path("/r/lod0.gltf"));
    EXPECT_FLOAT_EQ(h.scale, 0.402f);
}
TEST(HullSource, BarePathSplitsToScaleOne) {
    auto h = assets::split_hull_source("/a/b.NIF");
    EXPECT_EQ(h.path, std::filesystem::path("/a/b.NIF"));
    EXPECT_FLOAT_EQ(h.scale, 1.0f);
}
TEST(HullSource, GltfDetectionIsCaseInsensitive) {
    EXPECT_TRUE(assets::is_gltf_path("x/Y.GLTF"));
    EXPECT_TRUE(assets::is_gltf_path("x/y.glb"));
    EXPECT_FALSE(assets::is_gltf_path("x/y.nif"));
}
