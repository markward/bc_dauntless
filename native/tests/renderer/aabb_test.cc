#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include "renderer/aabb.h"

TEST(Aabb, ComputesCenterAndHalfExtentsFromVertexPositions) {
    std::vector<glm::vec3> verts = {
        {-1.0f, -2.0f, -3.0f},
        { 4.0f,  6.0f,  9.0f},
        { 0.0f,  0.0f,  0.0f},
    };
    renderer::Aabb box = renderer::compute_aabb(verts);
    EXPECT_FLOAT_EQ(box.center.x, 1.5f);
    EXPECT_FLOAT_EQ(box.center.y, 2.0f);
    EXPECT_FLOAT_EQ(box.center.z, 3.0f);
    EXPECT_FLOAT_EQ(box.half_extents.x, 2.5f);
    EXPECT_FLOAT_EQ(box.half_extents.y, 4.0f);
    EXPECT_FLOAT_EQ(box.half_extents.z, 6.0f);
}

TEST(Aabb, EmptyVertexListReturnsZeroBox) {
    std::vector<glm::vec3> verts;
    renderer::Aabb box = renderer::compute_aabb(verts);
    EXPECT_EQ(box.center, glm::vec3(0.0f));
    EXPECT_EQ(box.half_extents, glm::vec3(0.0f));
}
