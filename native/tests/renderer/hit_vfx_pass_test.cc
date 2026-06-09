// native/tests/renderer/hit_vfx_pass_test.cc
#include <gtest/gtest.h>
#include <renderer/hit_vfx_pass.h>
#include <scenegraph/world.h>
#include <scenegraph/instance.h>
#include <glm/glm.hpp>

#include <filesystem>
#include <fstream>

// Locks the hull-anchor resolve used by HitVfxPass: spark origin = ship.world * body_point.
TEST(HitVfxSparkAnchor, OriginTracksWorldMatrix) {
    glm::mat4 world(1.0f);
    world[3] = glm::vec4(100.0f, 0.0f, 0.0f, 1.0f);   // translate +X
    const glm::vec3 body_point(1.0f, 2.0f, 3.0f);
    glm::vec3 origin = glm::vec3(world * glm::vec4(body_point, 1.0f));
    EXPECT_FLOAT_EQ(origin.x, 101.0f);
    EXPECT_FLOAT_EQ(origin.y, 2.0f);
    EXPECT_FLOAT_EQ(origin.z, 3.0f);

    world[3] = glm::vec4(0.0f, 50.0f, 0.0f, 1.0f);    // re-place ship; origin follows
    origin = glm::vec3(world * glm::vec4(body_point, 1.0f));
    EXPECT_FLOAT_EQ(origin.x, 1.0f);
    EXPECT_FLOAT_EQ(origin.y, 52.0f);
}

// Regression guard for the texture-path bug: the renderer runs with CWD =
// project root, and HitVfxPass opens its sprites via std::ifstream on
// CWD-relative paths. A missing "game/" prefix makes load_sprite fail, the
// main texture stays id()==0, and render() early-returns — silently
// suppressing the WHOLE pass (flash + sparks). The existing render tests
// never caught this because they load assets via absolute paths, not the
// pass's CWD-relative ifstream. This test reproduces the runtime CWD and
// asserts the pass's own constant paths actually open.
TEST(HitVfxTextures, ConstantPathsResolveFromRendererCwd) {
    namespace fs = std::filesystem;
    const fs::path root = fs::path(__FILE__)
        .parent_path().parent_path().parent_path().parent_path();

    // Skip only when the BC sprite assets are genuinely absent (judged via
    // the known-good absolute locations, NOT the pass's constants — so a
    // reverted "game/" prefix FAILS here instead of masquerading as "assets
    // absent" and skipping).
    const fs::path known_flash =
        root / "game" / "data" / "Textures" / "Tactical" / "TorpedoFlares.tga";
    const fs::path known_spark = root / "game" / "data" / "rough.tga";
    if (!fs::is_regular_file(known_flash) || !fs::is_regular_file(known_spark)) {
        GTEST_SKIP() << "BC sprite assets not present under " << (root / "game");
    }

    // Emulate the renderer's runtime CWD and open the pass's verbatim paths.
    const fs::path prev = fs::current_path();
    fs::current_path(root);
    std::ifstream flash(renderer::HitVfxPass::impact_texture_path(), std::ios::binary);
    std::ifstream spark(renderer::HitVfxPass::spark_texture_path(),  std::ios::binary);
    const bool flash_ok = flash.good();
    const bool spark_ok = spark.good();
    fs::current_path(prev);

    EXPECT_TRUE(flash_ok)
        << "main flash sprite did not open from project root: "
        << renderer::HitVfxPass::impact_texture_path();
    EXPECT_TRUE(spark_ok)
        << "spark sprite did not open from project root: "
        << renderer::HitVfxPass::spark_texture_path();
}
