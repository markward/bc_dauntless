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
    //
    // a=(0,0,0), b=(1,0,0), c=(0,1e-11,0), p=(1e-6, 1e-13, 0).
    //
    // This point was found by sweeping the parameter space for a query that
    // actually reaches the interior region in float32: d1~9.99e-7, d2~1.0e-24
    // (vertex-a check fails since both aren't <= 0), and likewise every
    // vertex/edge region check fails, leaving va~9.9e-23, vb~1.0e-28,
    // vc~1.0e-24, all strictly positive so region falls through to the
    // interior branch. There, sum = va+vb+vc ~ 1.0e-22, below the 1e-20
    // epsilon, so the guard fires and returns distance to vertex a.
    //
    // Verified by instrumenting a standalone build of the real function:
    // every vertex/edge branch condition printed "no", the guard condition
    // printed "YES", and the returned distance matched length(p - a) to
    // full float32 precision (not the ~0.0 the unclamped interior formula
    // would give for this same point) -- see task-2-report.md.
    const voxel::Tri thin{glm::vec3(0.0f, 0.0f, 0.0f),
                          glm::vec3(1.0f, 0.0f, 0.0f),
                          glm::vec3(0.0f, 1e-11f, 0.0f)};
    const glm::vec3 p(1e-06f, 1e-13f, 0.0f);
    const float r = voxel::point_triangle_distance(p, thin);

    // Only correct if the guard fired and returned length(p - a): the
    // unclamped interior formula for this same point evaluates to 0.0, six
    // orders of magnitude away, so this tolerance cannot be satisfied by any
    // other branch's result.
    const float expected_distance_to_vertex_a =
        std::sqrt(p.x * p.x + p.y * p.y + p.z * p.z);
    EXPECT_TRUE(std::isfinite(r));
    EXPECT_NEAR(r, expected_distance_to_vertex_a, 1e-12f);
}

namespace {

// A CLOSED axis-aligned box as 12 triangles.
std::vector<voxel::Tri> box_tris(glm::vec3 lo, glm::vec3 hi) {
    const glm::vec3 c[8] = {
        {lo.x, lo.y, lo.z}, {hi.x, lo.y, lo.z}, {hi.x, hi.y, lo.z}, {lo.x, hi.y, lo.z},
        {lo.x, lo.y, hi.z}, {hi.x, lo.y, hi.z}, {hi.x, hi.y, hi.z}, {lo.x, hi.y, hi.z},
    };
    const int q[6][4] = {{0,1,2,3},{4,5,6,7},{0,1,5,4},{3,2,6,7},{0,3,7,4},{1,2,6,5}};
    std::vector<voxel::Tri> t;
    for (const auto& f : q) {
        t.push_back({c[f[0]], c[f[1]], c[f[2]]});
        t.push_back({c[f[0]], c[f[2]], c[f[3]]});
    }
    return t;
}

// Cell index containing a body-frame point.
glm::ivec3 cell_of(const voxel::DistanceField& f, glm::vec3 p) {
    const glm::vec3 g = (p - f.origin) / f.cell;
    return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)), int(std::floor(g.z)));
}

}  // namespace

TEST(DistanceField, SignIsNegativeInsideAndPositiveOutside) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(5.0f),
        voxel::kDefaultBandCells);
    ASSERT_FALSE(f.dist.empty());

    const glm::ivec3 mid = cell_of(f, glm::vec3(50.0f));
    EXPECT_LT(f.distance_at(mid.x, mid.y, mid.z), 0.0f) << "box centre read as outside";

    // A cell in the margin, comfortably outside the box.
    EXPECT_GT(f.distance_at(0, 0, 0), 0.0f) << "margin cell read as inside";
}

TEST(DistanceField, DepthNearAFaceMatchesGeometry) {
    // Cell 2 units so the answer is not dominated by quantisation.
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(2.0f),
        voxel::kDefaultBandCells);

    // 5 units below the +Z face, far from every other face.
    const glm::ivec3 c = cell_of(f, glm::vec3(50.0f, 50.0f, 95.0f));
    const float d = f.distance_at(c.x, c.y, c.z);
    EXPECT_LT(d, 0.0f);
    // Within one cell of the true -5.
    EXPECT_NEAR(d, -5.0f, 2.0f);
}

TEST(DistanceField, HeightAboveAFaceMatchesGeometry) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(2.0f),
        voxel::kDefaultBandCells);

    const glm::ivec3 c = cell_of(f, glm::vec3(50.0f, 50.0f, 103.0f));
    const float d = f.distance_at(c.x, c.y, c.z);
    EXPECT_GT(d, 0.0f);
    EXPECT_NEAR(d, 3.0f, 2.0f);
}

TEST(DistanceField, FarFieldSaturatesRatherThanWrapping) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(5.0f),
        voxel::kDefaultBandCells);
    // The band is 4 cells = 20 units; the box centre is 50 units from every
    // face, so it must clamp to the most negative representable value, not
    // wrap to a positive one.
    const glm::ivec3 mid = cell_of(f, glm::vec3(50.0f));
    EXPECT_NEAR(f.distance_at(mid.x, mid.y, mid.z), -127.0f * f.scale, 1e-3f);
}

TEST(DistanceField, EmptyInputYieldsAnEmptyField) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        {}, glm::vec3(5.0f), voxel::kDefaultBandCells);
    EXPECT_TRUE(f.dist.empty());
}

TEST(DistanceField, GridCoversTheHullPlusAMargin) {
    const voxel::DistanceField f = voxel::distance_field_from_tris(
        box_tris(glm::vec3(0.0f), glm::vec3(100.0f)), glm::vec3(5.0f),
        voxel::kDefaultBandCells);
    // origin sits below the hull minimum, and the far corner above its maximum.
    EXPECT_LT(f.origin.x, 0.0f);
    const float far_x = f.origin.x + f.cell.x * static_cast<float>(f.dims.x);
    EXPECT_GT(far_x, 100.0f);
}
