#include <gtest/gtest.h>
#include <voxel/dual_contour.h>
#include <glm/glm.hpp>

TEST(QEF, ThreeOrthogonalPlanesGiveCorner) {
    // three axis planes through the point (2,3,4)
    std::vector<voxel::Plane> ps = {
        {{1,0,0}, 2.0f}, {{0,1,0}, 3.0f}, {{0,0,1}, 4.0f}};
    glm::vec3 v = voxel::solve_qef(ps, /*fallback=*/glm::vec3(0,0,0));
    EXPECT_NEAR(v.x, 2.0f, 1e-3);
    EXPECT_NEAR(v.y, 3.0f, 1e-3);
    EXPECT_NEAR(v.z, 4.0f, 1e-3);
}

TEST(QEF, SinglePlaneVertexLiesOnPlaneNearSeed) {
    std::vector<voxel::Plane> ps = {{{0,0,1}, 5.0f}};   // z = 5
    glm::vec3 v = voxel::solve_qef(ps, glm::vec3(1,1,1));
    EXPECT_NEAR(v.z, 5.0f, 1e-3);                        // on the plane
    EXPECT_NEAR(v.x, 1.0f, 1e-2);                        // x,y pulled toward seed
    EXPECT_NEAR(v.y, 1.0f, 1e-2);
}

TEST(QEF, NoPlanesReturnsFallback) {
    glm::vec3 v = voxel::solve_qef({}, glm::vec3(7,8,9));
    EXPECT_NEAR(v.x,7,1e-4); EXPECT_NEAR(v.y,8,1e-4); EXPECT_NEAR(v.z,9,1e-4);
}
