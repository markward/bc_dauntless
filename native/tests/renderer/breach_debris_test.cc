#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <scenegraph/breach_events.h>
#include <renderer/frame.h>
#include <renderer/breach_debris.h>

TEST(BuildDebrisDescriptors, NoEventsYieldsEmptyVector) {
    scenegraph::BreachEventRing ring;
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    EXPECT_TRUE(desc.empty());
}

TEST(BuildDebrisDescriptors, FreshEventYieldsOneDescriptor) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{2, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.1f);
    ASSERT_EQ(desc.size(), 1u);
}

TEST(BuildDebrisDescriptors, DescriptorHasCorrectInstanceId) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 42u);
    scenegraph::InstanceId id{7, 3};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_EQ(desc[0].instance_id, id);
}

TEST(BuildDebrisDescriptors, EmitDirFollowsSurfaceNormal) {
    scenegraph::BreachEventRing ring;
    const glm::vec3 normal{0.f, 1.f, 0.f};
    ring.push({10.f, 0.f, 0.f}, 1.f, normal, 0.f, 3u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_NEAR(desc[0].emit_dir.x, 0.f, 1e-4f);
    EXPECT_NEAR(desc[0].emit_dir.y, 1.f, 1e-4f);
    EXPECT_NEAR(desc[0].emit_dir.z, 0.f, 1e-4f);
}

TEST(BuildDebrisDescriptors, EffectAgeEqualsNowMinusBirthTime) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 1.0f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 2.0f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_FLOAT_EQ(desc[0].effect_age, 1.0f);
}

TEST(BuildDebrisDescriptors, BlendModeIsAlpha) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_EQ(desc[0].blend_mode, 0) << "debris must use alpha blend (0), not additive";
}

TEST(BuildDebrisDescriptors, FirstSizeKeyIsSmall) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_GE(desc[0].num_size_keys, 1);
    EXPECT_NEAR(desc[0].size_keys[0].v, 0.07f, 0.01f)
        << "first size key should be ~0.07 (tiny solid bit)";
}

TEST(BuildDebrisDescriptors, AlphaHoldsThenTapers) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    ASSERT_GE(desc[0].num_alpha_keys, 3);
    // Key at t~0.85 should still be ~1.0
    EXPECT_NEAR(desc[0].alpha_keys[1].t, 0.85f, 0.01f);
    EXPECT_NEAR(desc[0].alpha_keys[1].v, 1.0f, 0.01f);
    // Last key should be 0.0
    EXPECT_FLOAT_EQ(desc[0].alpha_keys[desc[0].num_alpha_keys - 1].v, 0.f);
}

TEST(BuildDebrisDescriptors, ColorKeysAreHullGrey) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    ASSERT_GE(desc[0].num_color_keys, 2);
    // First key: warm grey (r > b)
    EXPECT_GT(desc[0].color_keys[0].r, desc[0].color_keys[0].b)
        << "first color key should be warmer (r > b)";
    // Last key: cool grey (roughly equal or b >= r)
    EXPECT_NEAR(desc[0].color_keys[1].r, desc[0].color_keys[1].b, 0.05f)
        << "last color key should be neutral/cool grey";
}

TEST(BuildDebrisDescriptors, SeedDiffersFromVentingBuilder) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 77u);
    scenegraph::InstanceId id{1, 1};
    // Build debris seed
    auto debris = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(debris.size(), 1u);
    // Compute what venting seed would be for the same event seed=77
    // venting: (77 ^ 0x517cc1b727220a95ull) >> 11, scaled
    // debris:  ((77 ^ 0x9e3779b97f4a7c15ull) ^ 0x517cc1b727220a95ull) >> 11, scaled
    const std::uint64_t vent_raw = (77ull ^ 0x517cc1b727220a95ull) >> 11;
    const float vent_seed = static_cast<float>(vent_raw)
        * (1.f / static_cast<float>(1ull << 53));
    EXPECT_NE(debris[0].seed, vent_seed)
        << "debris seed must differ from venting seed for the same event";
}

TEST(BuildDebrisDescriptors, SeedIsStable) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 77u);
    scenegraph::InstanceId id{1, 1};
    auto a = renderer::build_debris_descriptors(ring, id, 0.3f);
    auto b = renderer::build_debris_descriptors(ring, id, 0.3f);
    ASSERT_EQ(a.size(), 1u);
    EXPECT_FLOAT_EQ(a[0].seed, b[0].seed)
        << "seed must not change between calls with the same ring state";
}

TEST(BuildDebrisDescriptors, EventPastDebrisLifeYieldsEmpty) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(
        ring, id, scenegraph::kDebrisLife + 0.01f);
    EXPECT_TRUE(desc.empty())
        << "must not produce descriptors past kDebrisLife";
}
