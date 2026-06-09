// native/tests/renderer/hit_vfx_pass_test.cc
#include <gtest/gtest.h>
#include <scenegraph/world.h>
#include <scenegraph/instance.h>
#include <glm/glm.hpp>

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
