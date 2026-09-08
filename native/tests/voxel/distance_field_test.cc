// native/tests/voxel/distance_field_test.cc
//
// The signed distance field that replaces BC's occupancy grid. Distance is the
// whole point: every damage threshold becomes a real length instead of a cell
// count, which is what made the Warbird misbehave (its cells are 25 model units
// against everyone else's 15, so a threshold of "2 cells" meant 50 units there
// and 30 elsewhere).
#include <gtest/gtest.h>

#include <voxel/distance_field.h>
#include <voxel/voxelize.h>

#include <cmath>
#include <vector>

namespace {

// Triangle in the z = 0 plane: (0,0,0), (10,0,0), (0,10,0).
voxel::Tri flat_tri() {
    return voxel::Tri{glm::vec3(0.0f, 0.0f, 0.0f),
                      glm::vec3(10.0f, 0.0f, 0.0f),
                      glm::vec3(0.0f, 10.0f, 0.0f)};
}

}  // namespace

TEST(PointTriangleDistance, PointOnTheFaceIsZero) {
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(2.0f, 2.0f, 0.0f),
                                               flat_tri()), 0.0f, 1e-4f);
}

TEST(PointTriangleDistance, PointAboveTheFaceIsThePerpendicular) {
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(2.0f, 2.0f, 7.0f),
                                               flat_tri()), 7.0f, 1e-4f);
}

TEST(PointTriangleDistance, DistanceIsUnsignedBelowTheFaceToo) {
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(2.0f, 2.0f, -7.0f),
                                               flat_tri()), 7.0f, 1e-4f);
}

TEST(PointTriangleDistance, NearestFeatureIsAVertexWhenBeyondACorner) {
    // Well outside the (0,0) corner, along -x -y: nearest point is that vertex.
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(-3.0f, -4.0f, 0.0f),
                                               flat_tri()), 5.0f, 1e-4f);
}

TEST(PointTriangleDistance, NearestFeatureIsAnEdgeWhenBesideOne) {
    // Beside the a-b edge (which lies along +x), 4 units away in -y.
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(5.0f, -4.0f, 0.0f),
                                               flat_tri()), 4.0f, 1e-4f);
}

TEST(PointTriangleDistance, DegenerateTriangleDoesNotProduceNaN) {
    const voxel::Tri d{glm::vec3(1.0f), glm::vec3(1.0f), glm::vec3(1.0f)};
    const float r = voxel::point_triangle_distance(glm::vec3(1.0f, 1.0f, 4.0f), d);
    EXPECT_TRUE(std::isfinite(r));
    EXPECT_NEAR(r, 3.0f, 1e-4f);
}
