#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <scenegraph/breach_events.h>
#include <renderer/frame.h>    // ParticleEmitterDescriptor, ParticleKey
#include <renderer/breach_venting.h>
#include <renderer/asset_path.h>

#include <cstdlib>
#include <filesystem>
#include <string>

namespace {
// Mirrors asset_path_test.cc's GameRootGuard: TextureFileExistsOnDisk below
// mutates the process-global renderer game root, and ctest runs cases in one
// process, so it must not leak into a later test.
struct GameRootGuard {
    std::string saved = renderer::game_root();
    ~GameRootGuard() { renderer::set_game_root(saved); }
};
}  // namespace

TEST(BuildVentingDescriptors, NoEventsYieldsEmptyVector) {
    scenegraph::BreachEventRing ring;
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    EXPECT_TRUE(desc.empty());
}

TEST(BuildVentingDescriptors, FreshEventYieldsOneDescriptor) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{2, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.1f);
    ASSERT_EQ(desc.size(), 1u);
}

TEST(BuildVentingDescriptors, DescriptorHasCorrectInstanceId) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 42u);
    scenegraph::InstanceId id{7, 3};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_EQ(desc[0].instance_id, id);
}

TEST(BuildVentingDescriptors, EmitPosIsBodyFrameBreachCenter) {
    scenegraph::BreachEventRing ring;
    ring.push({1.f, 2.f, 3.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_FLOAT_EQ(desc[0].emit_pos.x, 1.f);
    EXPECT_FLOAT_EQ(desc[0].emit_pos.y, 2.f);
    EXPECT_FLOAT_EQ(desc[0].emit_pos.z, 3.f);
}

TEST(BuildVentingDescriptors, StopAgeIsVentLife) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_FLOAT_EQ(desc[0].stop_age, scenegraph::kVentLife);
}

TEST(BuildVentingDescriptors, EffectAgeEqualsNowMinusBirthTime) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 1.0f /*birth*/, 1u);
    scenegraph::InstanceId id{1, 1};
    // now within the burst window (< kVentLife) so the event still vents.
    auto desc = renderer::build_venting_descriptors(ring, id, 1.3f /*now*/);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_FLOAT_EQ(desc[0].effect_age, 0.3f);
}

TEST(BuildVentingDescriptors, NoDescriptorPastVentLife) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    // At exactly kVentLife the emission stops; no descriptor needed (effect_age >= stop_age).
    auto desc = renderer::build_venting_descriptors(
        ring, id, scenegraph::kVentLife + 0.01f);
    EXPECT_TRUE(desc.empty())
        << "venting must stop producing descriptors past kVentLife";
}

TEST(BuildVentingDescriptors, AlphaKeysTaperToZero) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_GE(desc[0].num_alpha_keys, 2);
    EXPECT_FLOAT_EQ(desc[0].alpha_keys[0].v, 1.f) << "first alpha key must be 1.0";
    EXPECT_FLOAT_EQ(desc[0].alpha_keys[desc[0].num_alpha_keys - 1].v, 0.f)
        << "last alpha key must be 0.0";
}

TEST(BuildVentingDescriptors, EmitDirIsNormalized) {
    scenegraph::BreachEventRing ring;
    ring.push({1.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    const float len = glm::length(desc[0].emit_dir);
    EXPECT_NEAR(len, 1.f, 1e-4f) << "emit_dir must be normalized";
}

// Regression: emit_dir must follow the stored surface_normal, not the radial
// direction from origin.  Uses a saucer-top normal (+Y body) with a breach
// center that would give a completely different radial direction.
TEST(BuildVentingDescriptors, EmitDirFollowsSurfaceNormal) {
    scenegraph::BreachEventRing ring;
    // Breach at a point far along +X on the hull; radial would give ~{1,0,0}.
    // Surface normal points straight up (+Y = saucer top).
    const glm::vec3 normal{0.f, 1.f, 0.f};
    ring.push({10.f, 0.f, 0.f}, 1.f, normal, 0.f, 3u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    // emit_dir should be the normalized surface_normal, not normalize({10,0,0}).
    EXPECT_NEAR(desc[0].emit_dir.x, 0.f, 1e-4f);
    EXPECT_NEAR(desc[0].emit_dir.y, 1.f, 1e-4f);
    EXPECT_NEAR(desc[0].emit_dir.z, 0.f, 1e-4f);
}

TEST(BuildVentingDescriptors, SeedIsStable) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 77u);
    scenegraph::InstanceId id{1, 1};
    auto a = renderer::build_venting_descriptors(ring, id, 0.3f);
    auto b = renderer::build_venting_descriptors(ring, id, 0.3f);
    ASSERT_EQ(a.size(), 1u);
    EXPECT_FLOAT_EQ(a[0].seed, b[0].seed)
        << "seed must not change between calls with the same ring state";
}

// Sprite shape comes 100% from the texture's ALPHA channel — hit_vfx.frag has
// no radial mask — so a sprite whose alpha runs to the border draws a hard
// square. Noise3.tga (the viewscreen-static asset this emitter used to point
// at) has alpha noise edge-to-edge: border mean 125.8 vs centre 122.2, i.e. no
// falloff at all. Every vented particle was therefore a square of TV static.
TEST(BuildVentingDescriptors, TextureIsASoftRadialSprite) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_EQ(desc[0].texture_path.find("Noise"), std::string::npos)
        << "Noise*.tga is viewscreen static: alpha noise to the border, which "
           "renders as a hard square. Got: " << desc[0].texture_path;
    EXPECT_NE(desc[0].texture_path.find("rough.tga"), std::string::npos)
        << "expected the soft border-faded sprite. Got: " << desc[0].texture_path;
}

// Regression for the historical "ExplosionNoise.tga" bug: the pass silently
// skips emitters whose texture fails to load, so a typo'd path means venting
// never draws at all and nothing complains. The BC install no longer lives
// under the project root -- it is optional in this checkout -- so skip when
// it is genuinely absent rather than failing a clean checkout. The skip gate
// below only checks whether *a* game root is configured, independent of the
// specific texture path under test, so a broken constant still FAILS here
// instead of masquerading as "no install".
TEST(BuildVentingDescriptors, TextureFileExistsOnDisk) {
    namespace fs = std::filesystem;
    const fs::path root = std::filesystem::path(__FILE__)
        .parent_path().parent_path().parent_path().parent_path();

    GameRootGuard guard;
    // Honour the same env var engine/paths.py reads as its second-precedence
    // source, so this test runs against a real install wherever it is; fall
    // back to the legacy in-project relative "game" when unset.
    if (const char* env = std::getenv("DAUNTLESS_GAME_DIR")) {
        renderer::set_game_root(env);
    }
    fs::path game_dir = renderer::game_root();
    if (game_dir.is_relative()) game_dir = root / game_dir;
    if (!fs::exists(game_dir)) {
        GTEST_SKIP() << "no BC install under \"" << renderer::game_root()
                     << "\" -- set DAUNTLESS_GAME_DIR to run this test";
    }

    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);

    // texture_path is root-relative (e.g. "data/rough.tga"), resolved later
    // by particle_pass.cc's resolve_asset_path at draw time -- resolve it the
    // same way here, anchoring a relative root at the project root like the
    // renderer's runtime CWD does.
    fs::path resolved = renderer::resolve_asset_path(desc[0].texture_path);
    if (resolved.is_relative()) resolved = root / resolved;
    EXPECT_TRUE(fs::exists(resolved))
        << "venting texture does not exist: " << resolved;
}

// With zero colour keys curve_lerp1 returns 1.0 (particle_math.h), so the tint
// was pure white — an additive white jet with no cooling. Match the molten rim,
// which already cools over kRimLife: hot white-blue -> blue -> dim.
TEST(BuildVentingDescriptors, ColorKeysCoolFromHotWhiteBlue) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    const auto& d = desc[0];
    ASSERT_GE(d.num_color_keys, 2) << "venting must not fall back to white tint";

    const auto& first = d.color_keys[0];
    const auto& last  = d.color_keys[d.num_color_keys - 1];
    EXPECT_GT(first.b, first.r)   << "plasma front must be blue-dominant";
    EXPECT_GT(first.r + first.g + first.b, 3.f)
        << "front must exceed unit brightness so the HDR chain blooms it";
    EXPECT_LT(last.r + last.g + last.b, first.r + first.g + first.b)
        << "the jet must cool, not brighten";

    EXPECT_FLOAT_EQ(d.color_keys[0].t, 0.f);
    EXPECT_FLOAT_EQ(last.t, 1.f);
    for (int i = 1; i < d.num_color_keys; ++i) {
        EXPECT_GT(d.color_keys[i].t, d.color_keys[i - 1].t)
            << "colour key times must strictly increase (curve_lerp1 assumes it)";
    }
}
