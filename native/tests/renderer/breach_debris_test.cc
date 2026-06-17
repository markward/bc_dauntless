#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <scenegraph/breach_events.h>
#include <renderer/frame.h>
#include <renderer/breach_debris.h>

// build_debris_descriptors emits TWO descriptors per active event:
//   [0] hull chunks — square.tga, alpha blend, grey.
//   [1] sparks      — spark.tga, additive blend, bright orange.

TEST(BuildDebrisDescriptors, NoEventsYieldsEmptyVector) {
    scenegraph::BreachEventRing ring;
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    EXPECT_TRUE(desc.empty());
}

TEST(BuildDebrisDescriptors, FreshEventYieldsChunkAndSpark) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{2, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.1f);
    ASSERT_EQ(desc.size(), 2u) << "one chunk emitter + one spark emitter";
    EXPECT_EQ(desc[0].texture_path, "game/data/square.tga");
    EXPECT_EQ(desc[1].texture_path, "game/data/spark.tga");
}

TEST(BuildDebrisDescriptors, BothAttachedToInstance) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 42u);
    scenegraph::InstanceId id{7, 3};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 2u);
    EXPECT_EQ(desc[0].instance_id, id);
    EXPECT_EQ(desc[1].instance_id, id);
}

TEST(BuildDebrisDescriptors, BothEmitAlongSurfaceNormal) {
    scenegraph::BreachEventRing ring;
    const glm::vec3 normal{0.f, 1.f, 0.f};
    ring.push({10.f, 0.f, 0.f}, 1.f, normal, 0.f, 3u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 2u);
    for (const auto& d : desc) {
        EXPECT_NEAR(d.emit_dir.x, 0.f, 1e-4f);
        EXPECT_NEAR(d.emit_dir.y, 1.f, 1e-4f);
        EXPECT_NEAR(d.emit_dir.z, 0.f, 1e-4f);
    }
}

TEST(BuildDebrisDescriptors, EffectAgeEqualsNowMinusBirthTime) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 1.0f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 2.0f);
    ASSERT_EQ(desc.size(), 2u);
    EXPECT_FLOAT_EQ(desc[0].effect_age, 1.0f);
    EXPECT_FLOAT_EQ(desc[1].effect_age, 1.0f);
}

TEST(BuildDebrisDescriptors, ChunksAlphaSparksAdditive) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 2u);
    EXPECT_EQ(desc[0].blend_mode, 0) << "chunks: alpha blend";
    EXPECT_EQ(desc[1].blend_mode, 1) << "sparks: additive blend (brighter)";
}

TEST(BuildDebrisDescriptors, ChunkSizeKeysAreSmall) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 2u);
    ASSERT_GE(desc[0].num_size_keys, 1);
    EXPECT_NEAR(desc[0].size_keys[0].v, 0.07f, 0.02f);
}

TEST(BuildDebrisDescriptors, ChunkAlphaHoldsThenTapers) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 2u);
    ASSERT_GE(desc[0].num_alpha_keys, 3);
    EXPECT_NEAR(desc[0].alpha_keys[1].t, 0.85f, 0.01f);
    EXPECT_NEAR(desc[0].alpha_keys[1].v, 1.0f, 0.01f);
    EXPECT_FLOAT_EQ(desc[0].alpha_keys[desc[0].num_alpha_keys - 1].v, 0.f);
}

TEST(BuildDebrisDescriptors, ChunkGreySparkOrange) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 2u);
    // Chunk: neutral-ish grey (channels close, last key near-neutral).
    ASSERT_GE(desc[0].num_color_keys, 2);
    EXPECT_NEAR(desc[0].color_keys[1].r, desc[0].color_keys[1].b, 0.05f);
    // Spark: hot orange — r clearly > g > b.
    ASSERT_GE(desc[1].num_color_keys, 1);
    EXPECT_GT(desc[1].color_keys[0].r, desc[1].color_keys[0].g);
    EXPECT_GT(desc[1].color_keys[0].g, desc[1].color_keys[0].b);
}

TEST(BuildDebrisDescriptors, ChunkAndSparkSeedsDiffer) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 77u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 2u);
    EXPECT_NE(desc[0].seed, desc[1].seed)
        << "chunk and spark emitters must not share a per-particle hash";
    // And the chunk seed must differ from what the venting builder uses.
    const std::uint64_t vent_raw = (77ull ^ 0x517cc1b727220a95ull) >> 11;
    const float vent_seed = static_cast<float>(vent_raw)
        * (1.f / static_cast<float>(1ull << 53));
    EXPECT_NE(desc[0].seed, vent_seed);
}

TEST(BuildDebrisDescriptors, SeedsAreStable) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 77u);
    scenegraph::InstanceId id{1, 1};
    auto a = renderer::build_debris_descriptors(ring, id, 0.3f);
    auto b = renderer::build_debris_descriptors(ring, id, 0.3f);
    ASSERT_EQ(a.size(), 2u);
    ASSERT_EQ(b.size(), 2u);
    EXPECT_FLOAT_EQ(a[0].seed, b[0].seed);
    EXPECT_FLOAT_EQ(a[1].seed, b[1].seed);
}

TEST(BuildDebrisDescriptors, EventPastDebrisLifeYieldsEmpty) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, {0.f, 0.f, 1.f}, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_debris_descriptors(
        ring, id, scenegraph::kDebrisLife + 0.01f);
    EXPECT_TRUE(desc.empty());
}
