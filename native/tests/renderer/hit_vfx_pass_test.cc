// native/tests/renderer/hit_vfx_pass_test.cc
#include <gtest/gtest.h>
#include <renderer/hit_vfx_pass.h>
#include <renderer/asset_path.h>
#include <scenegraph/world.h>
#include <scenegraph/instance.h>
#include <glm/glm.hpp>

#include <cstdlib>
#include <filesystem>
#include <fstream>

#include "support/content_root.h"
#include "support/renderer_game_root.h"

namespace {
}  // namespace

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
// paths resolved through resolve_asset_path. A missing resolve_asset_path
// call makes load_sprite fail, the main texture stays id()==0, and render()
// early-returns — silently suppressing the WHOLE pass (flash + sparks). The
// existing render tests never caught this because they load assets via
// absolute paths, not the pass's CWD-relative ifstream. This test reproduces
// the runtime CWD and asserts the pass's own constant paths, once resolved,
// actually open.
TEST(HitVfxTextures, ConstantPathsResolveFromRendererCwd) {
    namespace fs = std::filesystem;
    const fs::path root = test_support::project_root();

    // The BC install no longer lives under the project root: point the
    // renderer at the configured one (support/renderer_game_root.h).
    test_support::RendererGameRootGuard guard;
    guard.apply_configured();
    const fs::path game_dir = test_support::game_root();

    // Skip only when the BC sprite assets are genuinely absent (judged via
    // known-good absolute locations under the configured root, NOT the
    // pass's own constants — so a reverted resolve_asset_path call FAILS
    // here instead of masquerading as "assets absent" and skipping).
    const fs::path known_flash =
        game_dir / "data" / "Textures" / "Tactical" / "TorpedoFlares.tga";
    const fs::path known_spark = game_dir / "data" / "rough.tga";
    if (!fs::is_regular_file(known_flash) || !fs::is_regular_file(known_spark)) {
        GTEST_SKIP() << "no BC install under \"" << renderer::game_root()
                     << "\" -- set DAUNTLESS_GAME_DIR to run this test";
    }

    // Emulate the renderer's runtime CWD (load-bearing only for the default,
    // project-root-relative root; an absolute DAUNTLESS_GAME_DIR resolves
    // independently of it) and open the pass's constants through the same
    // resolve_asset_path call load_sprite makes.
    const fs::path prev = fs::current_path();
    fs::current_path(root);
    const std::string flash_path =
        renderer::resolve_asset_path(renderer::HitVfxPass::impact_texture_path());
    const std::string spark_path =
        renderer::resolve_asset_path(renderer::HitVfxPass::spark_texture_path());
    std::ifstream flash(flash_path, std::ios::binary);
    std::ifstream spark(spark_path, std::ios::binary);
    const bool flash_ok = flash.good();
    const bool spark_ok = spark.good();
    fs::current_path(prev);

    EXPECT_TRUE(flash_ok)
        << "main flash sprite did not open from \"" << renderer::game_root()
        << "\": " << flash_path;
    EXPECT_TRUE(spark_ok)
        << "spark sprite did not open from \"" << renderer::game_root()
        << "\": " << spark_path;
}

// ── the flash rides the hull too ──────────────────────────────────────────
//
// The spark burst resolved against the live instance matrix while the flash
// billboard in the SAME descriptor was drawn at a frozen world_pos. The flash
// lives 0.7 s, so at 6.3 GU/s it slid ~4.4 GU -- further than a Galaxy is long
// -- with the sparks sitting still beside it. Both now go through
// hit_vfx_anchor_point.

TEST(HitVfxAnchor, AnchoredDescriptorTracksTheInstanceMatrix) {
    renderer::HitVfxDescriptor v;
    v.world_pos = glm::vec3(0.0f);          // deliberately wrong, must be unused
    v.body_point = glm::vec3(1.0f, 2.0f, 3.0f);
    v.has_body_anchor = true;

    glm::mat4 world(1.0f);
    world[3] = glm::vec4(100.0f, 0.0f, 0.0f, 1.0f);
    EXPECT_EQ(renderer::hit_vfx_anchor_point(v, &world),
              glm::vec3(101.0f, 2.0f, 3.0f));

    world[3] = glm::vec4(0.0f, 50.0f, 0.0f, 1.0f);   // ship moves; anchor follows
    EXPECT_EQ(renderer::hit_vfx_anchor_point(v, &world),
              glm::vec3(1.0f, 52.0f, 3.0f));
}

TEST(HitVfxAnchor, UnanchoredDescriptorKeepsItsWorldPosition) {
    // No mesh normal / no instance: the old behaviour is the fallback.
    renderer::HitVfxDescriptor v;
    v.world_pos = glm::vec3(7.0f, 8.0f, 9.0f);
    v.body_point = glm::vec3(1.0f, 2.0f, 3.0f);
    v.has_body_anchor = false;

    glm::mat4 world(1.0f);
    world[3] = glm::vec4(100.0f, 0.0f, 0.0f, 1.0f);
    EXPECT_EQ(renderer::hit_vfx_anchor_point(v, &world), v.world_pos);
}

TEST(HitVfxAnchor, MissingInstanceFallsBackToWorldPosition) {
    // Anchored, but the instance is gone (destroyed ship, stale id).
    renderer::HitVfxDescriptor v;
    v.world_pos = glm::vec3(7.0f, 8.0f, 9.0f);
    v.body_point = glm::vec3(1.0f, 2.0f, 3.0f);
    v.has_body_anchor = true;
    EXPECT_EQ(renderer::hit_vfx_anchor_point(v, nullptr), v.world_pos);
}

TEST(HitVfxAnchor, BodyOriginIsANormalAnchorNotASentinel) {
    // A hit at the model origin has body_point (0,0,0); the flag, not the
    // value, is what says whether an anchor exists.
    renderer::HitVfxDescriptor v;
    v.world_pos = glm::vec3(7.0f, 8.0f, 9.0f);
    v.body_point = glm::vec3(0.0f);
    v.has_body_anchor = true;

    glm::mat4 world(1.0f);
    world[3] = glm::vec4(100.0f, 0.0f, 0.0f, 1.0f);
    EXPECT_EQ(renderer::hit_vfx_anchor_point(v, &world),
              glm::vec3(100.0f, 0.0f, 0.0f));
}

// Floating render origin (system-frames Plan 3 Task 6, fix round 1): the
// instance matrix is RENDER space and its translation moves every frame the
// camera does. Spark directions must be seeded from something stable in the
// hit ship's own frame, or a stationary target's sparks re-roll every frame
// the player moves (the particle pass's "mad flurry").
TEST(HitVfxSparkJitter, IdenticalUnderTwoRenderOrigins) {
    renderer::HitVfxDescriptor v;
    v.has_body_anchor = true;
    v.body_point = glm::vec3(1.25f, -0.5f, 0.75f);
    v.spark_count = 8;
    glm::mat4 world_a(1.0f), world_b(1.0f);
    world_a[3] = glm::vec4(50.0f, 0.0f, 0.0f, 1.0f);      // origin 1e6 - 50
    world_b[3] = glm::vec4(-3.0f, 12.0f, 7.0f, 1.0f);     // origin moved on
    const auto a = renderer::hit_vfx_spark_jitters(v, world_a);
    const auto b = renderer::hit_vfx_spark_jitters(v, world_b);
    ASSERT_EQ(a.size(), 8u);
    ASSERT_EQ(a, b);
    // Distinct sparks still get distinct directions.
    EXPECT_NE(a[0], a[1]);
}
