// native/tests/scenegraph/world_test.cc
#include <gtest/gtest.h>

#include <scenegraph/world.h>

#include <glm/glm.hpp>

namespace {

TEST(World, CreateAndLookup) {
    scenegraph::World w;
    auto id = w.create_instance(/*model_handle=*/42);
    EXPECT_TRUE(w.is_valid(id));
    auto* inst = w.get(id);
    ASSERT_NE(inst, nullptr);
    EXPECT_EQ(inst->model_handle, 42u);
    EXPECT_TRUE(inst->visible);
}

TEST(World, DestroyInvalidatesHandle) {
    scenegraph::World w;
    auto id = w.create_instance(7);
    w.destroy_instance(id);
    EXPECT_FALSE(w.is_valid(id));
    EXPECT_EQ(w.get(id), nullptr);
}

TEST(World, ReusedSlotHasNewGeneration) {
    scenegraph::World w;
    auto a = w.create_instance(1);
    w.destroy_instance(a);
    auto b = w.create_instance(2);
    // Slot may be reused, but generations must differ.
    EXPECT_NE(a.generation, b.generation);
    EXPECT_FALSE(w.is_valid(a));  // old handle stays invalid
    EXPECT_TRUE(w.is_valid(b));
}

TEST(World, SetTransformPropagatesToInstance) {
    scenegraph::World w;
    auto id = w.create_instance(0);
    glm::mat4 m(1.0f);
    m[3].x = 5.0f;
    w.set_world_transform(id, m);
    EXPECT_FLOAT_EQ(w.get(id)->world[3].x, 5.0f);
}

TEST(World, SetVisibleFlipsFlag) {
    scenegraph::World w;
    auto id = w.create_instance(0);
    w.set_visible(id, false);
    EXPECT_FALSE(w.get(id)->visible);
}

TEST(World, NewInstanceDefaultsToSpacePass) {
    scenegraph::World w;
    auto id = w.create_instance(7);
    auto* inst = w.get(id);
    ASSERT_NE(inst, nullptr);
    EXPECT_EQ(inst->pass, scenegraph::Pass::Space);
}

TEST(World, SetPassUpdatesField) {
    scenegraph::World w;
    auto id = w.create_instance(7);
    w.set_pass(id, scenegraph::Pass::Bridge);
    EXPECT_EQ(w.get(id)->pass, scenegraph::Pass::Bridge);
}

TEST(World, ForEachVisibleInPassFiltersByPass) {
    scenegraph::World w;
    auto a = w.create_instance(1);
    auto b = w.create_instance(2);
    auto c = w.create_instance(3);
    w.set_pass(b, scenegraph::Pass::Bridge);
    // Only c stays in Space; b is in Bridge; a is default (Space).
    (void)a; (void)c;

    std::vector<scenegraph::ModelHandle> seen_space;
    w.for_each_visible_in_pass(scenegraph::Pass::Space,
                               [&](const scenegraph::Instance& i) {
        seen_space.push_back(i.model_handle);
    });
    std::vector<scenegraph::ModelHandle> seen_bridge;
    w.for_each_visible_in_pass(scenegraph::Pass::Bridge,
                               [&](const scenegraph::Instance& i) {
        seen_bridge.push_back(i.model_handle);
    });

    EXPECT_EQ(seen_space.size(), 2u);
    EXPECT_EQ(seen_bridge.size(), 1u);
    EXPECT_EQ(seen_bridge[0], 2u);
}

TEST(World, ForEachVisibleInPassRespectsVisibilityFlag) {
    scenegraph::World w;
    auto a = w.create_instance(1);
    w.set_pass(a, scenegraph::Pass::Bridge);
    w.set_visible(a, false);
    int count = 0;
    w.for_each_visible_in_pass(scenegraph::Pass::Bridge,
                               [&](const scenegraph::Instance&) { ++count; });
    EXPECT_EQ(count, 0);
}

TEST(World, NewInstanceDefaultsRimIneligible) {
    scenegraph::World w;
    auto id = w.create_instance(7);
    auto* inst = w.get(id);
    ASSERT_NE(inst, nullptr);
    EXPECT_FALSE(inst->rim_eligible);
}

TEST(World, SetRimEligibleUpdatesField) {
    scenegraph::World w;
    auto id = w.create_instance(7);
    w.set_rim_eligible(id, true);
    EXPECT_TRUE(w.get(id)->rim_eligible);
    w.set_rim_eligible(id, false);
    EXPECT_FALSE(w.get(id)->rim_eligible);
}

}  // namespace
