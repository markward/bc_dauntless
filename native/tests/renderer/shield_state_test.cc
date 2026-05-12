#include <gtest/gtest.h>
#include <cmath>
#include "renderer/shield_state.h"
#include "scenegraph/instance.h"

using namespace renderer;

namespace {
ShieldState make_state(float decay = 1.0f) {
    ShieldState s;
    s.mode = ShieldMode::Ellipsoid;
    s.decay_seconds = decay;
    s.default_color = glm::vec4(0.2f, 0.4f, 1.0f, 1.0f);
    s.aabb_center = glm::vec3(0.0f);
    s.aabb_half_extents = glm::vec3(10.0f);
    return s;
}
}

TEST(ShieldState, PushHitStoresColorAndPoint) {
    auto s = make_state();
    s.push_hit({1.0f, 2.0f, 3.0f}, {0.5f, 0.6f, 0.7f, 1.0f}, 1.0f, 0.0, 2);
    EXPECT_EQ(s.active_count(), 1u);
    // Find the populated slot (push_hit may pick any empty slot).
    int found = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { found = static_cast<int>(i); break; }
    }
    ASSERT_NE(found, -1);
    EXPECT_EQ(s.slot(found).point_world, glm::vec3(1.0f, 2.0f, 3.0f));
    EXPECT_FLOAT_EQ(s.slot(found).color_rgba.r, 0.5f);
    EXPECT_EQ(s.slot(found).texture_index, 2);
}

TEST(ShieldState, ZeroRgbaSubstitutesDefaultColor) {
    auto s = make_state();
    s.push_hit({0,0,0}, {0,0,0,0}, 1.0f, 0.0, 0);
    int found = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { found = static_cast<int>(i); break; }
    }
    ASSERT_NE(found, -1);
    EXPECT_EQ(s.slot(found).color_rgba, s.default_color);
}

TEST(ShieldState, IntensityDecaysExponentiallyWithDecaySeconds) {
    auto s = make_state(/*decay=*/2.0f);
    s.push_hit({0,0,0}, {1,1,1,1}, 1.0f, 0.0, 0);
    s.tick(/*now=*/2.0);  // one decay period
    int found = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { found = static_cast<int>(i); break; }
    }
    ASSERT_NE(found, -1);
    EXPECT_NEAR(s.slot(found).current_intensity, std::exp(-1.0f), 1e-5);
}

TEST(ShieldState, ExpiredSlotsBecomeEmpty) {
    auto s = make_state(/*decay=*/0.1f);
    s.push_hit({0,0,0}, {1,1,1,1}, 1.0f, 0.0, 0);
    s.tick(/*now=*/10.0);  // far past decay
    EXPECT_EQ(s.active_count(), 0u);
}

TEST(ShieldState, FullBufferEvictsDimmestHit) {
    auto s = make_state(/*decay=*/100.0f);
    // Fill all 8 slots with hits at t=0..7 seconds (slot 0 is dimmest at t=8).
    for (int i = 0; i < 8; ++i) {
        s.push_hit({float(i), 0, 0}, {1, 1, 1, 1}, 1.0f, double(i), 0);
    }
    s.tick(/*now=*/8.0);
    // 9th hit — the dimmest is the one pushed at t=0 (longest decayed).
    s.push_hit({99, 0, 0}, {1, 1, 1, 1}, 1.0f, 8.0, 0);
    EXPECT_EQ(s.active_count(), 8u);
    // Verify the x=0 hit is gone, x=99 is present.
    bool found_zero = false, found_99 = false;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity < 0.01f) continue;
        if (s.slot(i).point_world.x == 0.0f)  found_zero = true;
        if (s.slot(i).point_world.x == 99.0f) found_99 = true;
    }
    EXPECT_FALSE(found_zero);
    EXPECT_TRUE(found_99);
}

TEST(ShieldRegistry, RegisterCreatesStateForInstance) {
    ShieldRegistry reg;
    scenegraph::InstanceId id{42, 1};
    reg.register_instance(id, ShieldMode::Skin, 2.0f,
                          glm::vec4(0.1f, 0.2f, 0.3f, 1.0f),
                          glm::vec3(0.0f), glm::vec3(5.0f));
    auto* s = reg.find(id);
    ASSERT_NE(s, nullptr);
    EXPECT_EQ(s->mode, ShieldMode::Skin);
    EXPECT_FLOAT_EQ(s->decay_seconds, 2.0f);
}

TEST(ShieldRegistry, FindReturnsNullForUnknownInstance) {
    ShieldRegistry reg;
    EXPECT_EQ(reg.find(scenegraph::InstanceId{999, 0}), nullptr);
}

TEST(ShieldRegistry, PushHitDropsSilentlyForUnknownInstance) {
    ShieldRegistry reg;
    // Must not crash, must not throw.
    reg.push_hit(scenegraph::InstanceId{999, 0}, {0, 0, 0}, {1, 1, 1, 1}, 1.0f, 0.0);
    SUCCEED();
}

TEST(ShieldRegistry, PushHitRoutesToCorrectInstance) {
    ShieldRegistry reg;
    scenegraph::InstanceId a{1, 0}, b{2, 0};
    reg.register_instance(a, ShieldMode::Ellipsoid, 1.0f, glm::vec4(1, 0, 0, 1), {}, glm::vec3(1));
    reg.register_instance(b, ShieldMode::Ellipsoid, 1.0f, glm::vec4(0, 1, 0, 1), {}, glm::vec3(1));
    reg.push_hit(a, {1, 1, 1}, {0, 0, 0, 0}, 1.0f, 0.0);  // 0-rgba → default for A = red
    // A should have an active hit colored red.
    int found_a = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (reg.find(a)->slot(i).current_intensity > 0.0f) { found_a = static_cast<int>(i); break; }
    }
    ASSERT_NE(found_a, -1);
    EXPECT_EQ(reg.find(a)->slot(found_a).color_rgba, glm::vec4(1, 0, 0, 1));
    EXPECT_EQ(reg.find(b)->active_count(), 0u);
}

TEST(ShieldRegistry, UnregisterRemovesState) {
    ShieldRegistry reg;
    scenegraph::InstanceId id{7, 3};
    reg.register_instance(id, ShieldMode::Ellipsoid, 1.0f, glm::vec4(1), {}, glm::vec3(1));
    reg.unregister_instance(id);
    EXPECT_EQ(reg.find(id), nullptr);
}

TEST(ShieldState, TextureIndexStableAcrossTicks) {
    auto s = make_state();
    s.push_hit({0,0,0}, {1,1,1,1}, 1.0f, 0.0, 3);
    int idx_before = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { idx_before = s.slot(i).texture_index; break; }
    }
    s.tick(/*now=*/0.5);
    int idx_after = -1;
    for (std::size_t i = 0; i < ShieldState::MaxHits; ++i) {
        if (s.slot(i).current_intensity > 0.0f) { idx_after = s.slot(i).texture_index; break; }
    }
    EXPECT_EQ(idx_before, 3);
    EXPECT_EQ(idx_after, 3);
}
