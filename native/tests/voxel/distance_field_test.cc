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

namespace {

// Symmetric triangle in the z = 0 plane: (0,0,0), (10,0,0), (0,10,0).
// Used to test interior region and basic perpendicular distance.
voxel::Tri flat_tri() {
    return voxel::Tri{glm::vec3(0.0f, 0.0f, 0.0f),
                      glm::vec3(10.0f, 0.0f, 0.0f),
                      glm::vec3(0.0f, 10.0f, 0.0f)};
}

// Asymmetric triangle in the z = 0 plane: (0,0,0), (10,0,0), (0,5,0).
// Used to test all six regions (three vertices and three edges).
// Vertices are distinguishable: a=(0,0,0), b=(10,0,0), c=(0,5,0).
voxel::Tri asymmetric_tri() {
    return voxel::Tri{glm::vec3(0.0f, 0.0f, 0.0f),
                      glm::vec3(10.0f, 0.0f, 0.0f),
                      glm::vec3(0.0f, 5.0f, 0.0f)};
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

// Region coverage tests for all six regions using an asymmetric triangle.
// Triangle vertices: a=(0,0,0), b=(10,0,0), c=(0,5,0).

TEST(PointTriangleDistance, ReachesVertexB) {
    // Point (15,-3,0) is beyond vertex b=(10,0,0).
    // Distance = sqrt((15-10)^2 + (-3-0)^2) = sqrt(25 + 9) = sqrt(34).
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(15.0f, -3.0f, 0.0f),
                                               asymmetric_tri()),
                std::sqrt(34.0f), 1e-4f);
}

TEST(PointTriangleDistance, ReachesVertexC) {
    // Point (-2,8,0) is beyond vertex c=(0,5,0).
    // Distance = sqrt((-2-0)^2 + (8-5)^2) = sqrt(4 + 9) = sqrt(13).
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(-2.0f, 8.0f, 0.0f),
                                               asymmetric_tri()),
                std::sqrt(13.0f), 1e-4f);
}

TEST(PointTriangleDistance, ReachesEdgeAC) {
    // Point (-3,2.5,0) is beside the edge from a=(0,0,0) to c=(0,5,0).
    // Edge ac lies along the y-axis at x=0. Closest point is (0,2.5,0).
    // Distance = 3.
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(-3.0f, 2.5f, 0.0f),
                                               asymmetric_tri()),
                3.0f, 1e-4f);
}

TEST(PointTriangleDistance, ReachesEdgeBC) {
    // Point (8,3,0) is beside the edge from b=(10,0,0) to c=(0,5,0).
    // Edge parameterized as b + t*(c-b) = (10,0,0) + t*(-10,5,0).
    // Projection: closest parameter t = 0.28, giving point (7.2, 1.4, 0).
    // Distance = sqrt((8-7.2)^2 + (3-1.4)^2) = sqrt(0.64 + 2.56) = sqrt(3.2).
    EXPECT_NEAR(voxel::point_triangle_distance(glm::vec3(8.0f, 3.0f, 0.0f),
                                               asymmetric_tri()),
                std::sqrt(3.2f), 1e-4f);
}

TEST(PointTriangleDistance, FullyCollapsedTriangleReturnsDistanceToVertex) {
    // When all three vertices coincide, the triangle is degenerate and collapses
    // to a single point. The distance is to that point (catches vertex-a check).
    const voxel::Tri d{glm::vec3(1.0f), glm::vec3(1.0f), glm::vec3(1.0f)};
    const float r = voxel::point_triangle_distance(glm::vec3(1.0f, 1.0f, 4.0f), d);
    EXPECT_TRUE(std::isfinite(r));
    EXPECT_NEAR(r, 3.0f, 1e-4f);
}

TEST(PointTriangleDistance, UltraThinTriangleFallsBackToVertexDistance) {
    // Test the guard fallback path: an ultra-thin triangle where sum = (2*Area)^2
    // can drop below the 1e-20 epsilon even though the interior is geometrically real.
    // a=(0,0,0), b=(1,0,0), c=(0,1e-11,0) → area ≈ 5e-12, sum ≈ 1e-22
    // Point (0.5, 0.5e-11, 1) targets the interior above the thin triangle.
    // The guard fires (sum < 1e-20) and returns distance to vertex a.
    const voxel::Tri thin{glm::vec3(0.0f, 0.0f, 0.0f),
                          glm::vec3(1.0f, 0.0f, 0.0f),
                          glm::vec3(0.0f, 1e-11f, 0.0f)};
    const float r = voxel::point_triangle_distance(glm::vec3(0.5f, 0.5e-11f, 1.0f), thin);
    // Result must be finite (guard prevents division by ~zero).
    // Exact value depends on which region catches the point in float precision,
    // but must be close to distance-to-vertex-a = sqrt(0.5^2 + (0.5e-11)^2 + 1^2).
    EXPECT_TRUE(std::isfinite(r));
    EXPECT_GT(r, 0.999f);  // At minimum, vertical component
    EXPECT_LT(r, 1.2f);    // Upper bound to catch gross errors
}
