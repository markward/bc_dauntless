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

}  // namespace
