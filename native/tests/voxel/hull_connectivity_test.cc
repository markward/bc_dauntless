// native/tests/voxel/hull_connectivity_test.cc
#include <gtest/gtest.h>
#include <voxel/hull_connectivity.h>

#include <chrono>
#include <iostream>

namespace {

// A dumbbell: two 5x5x5 blobs on the x axis joined by a one-cell neck.
// Everything else is "outside" (+127 in the baked field).
voxel::DistanceField make_dumbbell_baked() {
    voxel::DistanceField f;
    f.dims = glm::ivec3(17, 7, 7);
    f.cell = glm::vec3(1.0f);
    f.origin = glm::vec3(0.0f);
    f.scale = 1.0f;
    f.dist.assign(17u * 7u * 7u, static_cast<std::int8_t>(127));
    auto inside = [&](int x, int y, int z) { f.dist[f.index(x, y, z)] = -10; };
    for (int z = 1; z <= 5; ++z)
    for (int y = 1; y <= 5; ++y) {
        for (int x = 1; x <= 5; ++x)   inside(x, y, z);      // left blob
        for (int x = 11; x <= 15; ++x) inside(x, y, z);      // right blob
    }
    for (int x = 6; x <= 10; ++x) inside(x, 3, 3);            // the neck
    return f;
}

voxel::DistanceField undamaged_like(const voxel::DistanceField& baked) {
    voxel::DistanceField d = baked;
    d.dist.assign(baked.dist.size(), static_cast<std::int8_t>(-127));
    return d;
}

}  // namespace

TEST(HullConnectivity, IntactDumbbellIsOneBody) {
    const auto baked = make_dumbbell_baked();
    const auto damage = undamaged_like(baked);
    const auto r = voxel::hull_connectivity(baked, damage);
    EXPECT_EQ(r.main_body_cells, 125u + 125u + 5u);
    EXPECT_TRUE(r.detached.empty());
}

TEST(HullConnectivity, SeveringTheNeckDetachesTheFarBlob) {
    const auto baked = make_dumbbell_baked();
    auto damage = undamaged_like(baked);
    damage.dist[damage.index(8, 3, 3)] = 127;   // cut the neck at its middle
    const auto r = voxel::hull_connectivity(baked, damage);
    // Both halves are 127 cells (each blob plus two neck cells). The main
    // body is the LARGEST component; on a tie the lowest label wins, and
    // labels are assigned in lattice scan order (x fastest), so the LEFT
    // blob is label 1 and stays the ship; the right blob detaches.
    EXPECT_EQ(r.main_body_cells, 125u + 2u);
    EXPECT_EQ(r.main_body_label, 1u);
    ASSERT_EQ(r.detached.size(), 1u);
    const auto& c = r.detached[0];
    EXPECT_EQ(c.label, 2u);
    EXPECT_EQ(c.cells, 125u + 2u);
    EXPECT_EQ(c.cell_list.size(), c.cells);
    // Centroid of the right blob (x 11..15, centres 11.5..15.5 -> 13.5) is
    // pulled slightly left by the two neck cells at x=9,10.
    EXPECT_NEAR(c.centroid_body.x, (125.0f * 13.5f + 9.5f + 10.5f) / 127.0f, 1e-4f);
    EXPECT_NEAR(c.centroid_body.y, 3.5f, 1e-4f);
    EXPECT_NEAR(c.centroid_body.z, 3.5f, 1e-4f);
    EXPECT_FLOAT_EQ(c.bounds_min_body.x, 9.5f);
    EXPECT_FLOAT_EQ(c.bounds_max_body.x, 15.5f);
}

TEST(HullConnectivity, CarvedSeedFallsBackToAnOccupiedCell) {
    // Carve everything near the origin; the fill must still find the body.
    const auto baked = make_dumbbell_baked();
    auto damage = undamaged_like(baked);
    for (int z = 1; z <= 5; ++z) for (int y = 1; y <= 5; ++y)
        damage.dist[damage.index(1, y, z)] = 127;
    const auto r = voxel::hull_connectivity(baked, damage);
    EXPECT_EQ(r.main_body_cells, 100u + 125u + 5u);
    EXPECT_TRUE(r.detached.empty());
}

TEST(HullConnectivity, LargestComponentIsTheMainBodyNotTheOneNearestTheOrigin) {
    // A cascade capsule that hollows the centre leaves a small fragment at
    // the origin and the bulk of the hull further out. Seeding at the cell
    // nearest the origin made the FRAGMENT the "main body" and spawned the
    // whole remaining hull as a chunk. The main body is the largest
    // component, wherever it sits.
    voxel::DistanceField f;
    f.dims = glm::ivec3(17, 7, 7);
    f.cell = glm::vec3(1.0f);
    f.origin = glm::vec3(0.0f);
    f.scale = 1.0f;
    f.dist.assign(17u * 7u * 7u, static_cast<std::int8_t>(127));
    auto inside = [&](int x, int y, int z) { f.dist[f.index(x, y, z)] = -10; };
    for (int z = 0; z < 3; ++z) for (int y = 0; y < 3; ++y) for (int x = 0; x < 3; ++x)
        inside(x, y, z);                                          // 27 cells at the origin
    for (int z = 1; z <= 5; ++z) for (int y = 1; y <= 5; ++y) for (int x = 11; x <= 15; ++x)
        inside(x, y, z);                                          // 125 cells far out
    const auto damage = undamaged_like(f);
    const auto r = voxel::hull_connectivity(f, damage);
    EXPECT_EQ(r.main_body_cells, 125u);
    EXPECT_EQ(r.main_body_label, 2u);          // scan order: the origin cube is label 1
    ASSERT_EQ(r.detached.size(), 1u);
    EXPECT_EQ(r.detached[0].label, 1u);
    EXPECT_EQ(r.detached[0].cells, 27u);
    EXPECT_EQ(r.detached[0].cell_list.size(), 27u);
    EXPECT_NEAR(r.detached[0].centroid_body.x, 1.5f, 1e-4f);
    EXPECT_FLOAT_EQ(r.detached[0].bounds_min_body.x, 0.5f);
    EXPECT_FLOAT_EQ(r.detached[0].bounds_max_body.x, 2.5f);
}

TEST(HullConnectivity, MismatchedLatticesReturnEmpty) {
    const auto baked = make_dumbbell_baked();
    voxel::DistanceField damage = undamaged_like(baked);
    damage.dims = glm::ivec3(16, 7, 7);
    damage.dist.resize(16u * 7u * 7u);
    const auto r = voxel::hull_connectivity(baked, damage);
    EXPECT_EQ(r.main_body_cells, 0u);
    EXPECT_TRUE(r.detached.empty());
}

TEST(HullConnectivity, MismatchedOriginReturnsEmpty) {
    // Same dims and cell size as the baked field, but a different origin --
    // the header's contract is "MUST share one lattice (dims/origin/cell)",
    // not just matching dims. This must return gracefully in every build,
    // never assert/abort (a Debug build has NDEBUG undefined).
    const auto baked = make_dumbbell_baked();
    voxel::DistanceField damage = undamaged_like(baked);
    damage.origin = glm::vec3(1.0f, 0.0f, 0.0f);
    const auto r = voxel::hull_connectivity(baked, damage);
    EXPECT_EQ(r.main_body_cells, 0u);
    EXPECT_TRUE(r.detached.empty());
}

TEST(HullConnectivity, GalaxySizedLatticeIsFastEnough) {
    voxel::DistanceField baked;
    baked.dims = glm::ivec3(101, 137, 37);
    baked.cell = glm::vec3(5.0f);
    baked.origin = glm::vec3(0.0f);
    baked.scale = 1.0f;
    baked.dist.assign(101u * 137u * 37u, static_cast<std::int8_t>(127));
    for (int z = 5; z < 32; ++z) for (int y = 20; y < 120; ++y) for (int x = 10; x < 90; ++x)
        baked.dist[baked.index(x, y, z)] = -10;
    voxel::DistanceField damage = baked;
    damage.dist.assign(baked.dist.size(), static_cast<std::int8_t>(-127));

    const auto t0 = std::chrono::steady_clock::now();
    const auto r = voxel::hull_connectivity(baked, damage);
    const auto ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - t0).count();
    std::cout << "[hull_connectivity] Galaxy-sized lattice: " << ms << " ms, "
              << r.main_body_cells << " cells\n";
    EXPECT_EQ(r.main_body_cells, 80u * 100u * 27u);
    EXPECT_LT(ms, 50.0);
}
