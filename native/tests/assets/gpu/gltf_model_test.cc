// native/tests/assets/gpu/gltf_model_test.cc
//
// Task 2 of the rock-catalogue plan: build an assets::Model from a glTF file
// through AssetCache (build_model_from_gltf), with a per-load scale baked
// into vertices and folded into the cache key. See
// .superpowers/sdd/2026-09-30-rock-catalogue/task-2-brief.md.
//
// This is the one assets_tests TU that defines STB_IMAGE_WRITE_IMPLEMENTATION
// (grepped: no other TU in this binary does). Defined and undef'd BEFORE
// gltf_fixture.h's own #include <stb_image_write.h>, so that header only ever
// sees the declarations, never a second implementation in this TU.
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include <stb_image_write.h>
#undef STB_IMAGE_WRITE_IMPLEMENTATION

#include <assets/cache.h>
#include <assets/material.h>
#include <gtest/gtest.h>

#include "gl_fixture.h"
#include "../cpu/gltf_fixture.h"

#include <filesystem>
#include <vector>

class GltfModelTest : public assets_test::GLContext {};

TEST_F(GltfModelTest, GltfLoadsThroughAssetCache) {
    auto p = write_fixture(tmpdir("gltf_model_cache"), {}, nullptr, true, /*with_texture=*/true);
    assets::AssetCache::Config cfg; cfg.keep_cpu_data = true;
    assets::AssetCache cache(cfg);
    auto m = cache.load(p, std::vector<std::filesystem::path>{}, {}, {}, 1.0f);
    ASSERT_TRUE(m);
    EXPECT_EQ(m->source, p);
    ASSERT_EQ(m->meshes.size(), 1u);
    ASSERT_TRUE(m->meshes[0].cpu_data().has_value());
    ASSERT_EQ(m->materials.size(), 1u);
    using S = assets::Material::StageSlot;
    EXPECT_GE(m->materials[0].stages[static_cast<size_t>(S::Base)].texture_index, 0);
}

TEST_F(GltfModelTest, ScaleIsPartOfCacheKey) {
    auto p = write_fixture(tmpdir("gltf_model_scalekey"));
    assets::AssetCache::Config cfg; cfg.keep_cpu_data = true;
    assets::AssetCache cache(cfg);
    auto a = cache.load(p, std::vector<std::filesystem::path>{}, {}, {}, 1.0f);
    auto b = cache.load(p, std::vector<std::filesystem::path>{}, {}, {}, 2.0f);
    EXPECT_NE(a.get(), b.get());
    EXPECT_EQ(b->source.string(), p.string() + "#s=2");
    const float ax = a->meshes[0].cpu_data()->vertices[0].position.x;
    const float bx = b->meshes[0].cpu_data()->vertices[0].position.x;
    EXPECT_NEAR(bx, 2.0f * ax, 1e-5f);
}

TEST_F(GltfModelTest, NifPathStillGoesToNifLoader) {
    // An unreadable .nif must still throw from the NIF path (not the glTF
    // reader), and scale == 1.0f (the default for every existing caller)
    // must not trip the "scale is only supported for glTF" guard.
    assets::AssetCache cache;
    EXPECT_ANY_THROW(cache.load("/nonexistent/x.nif", std::vector<std::filesystem::path>{}, {}, {}, 1.0f));
}
