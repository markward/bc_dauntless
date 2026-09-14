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

// ── Local severance check ───────────────────────────────────────────────────
// hull_severance_local answers "could the carve in `box` have cut anything
// off?" by flooding from the box's shell, without walking the hull. It may
// only ever say kConnected when nothing was severed; kUnknown hands the
// question to the full BFS.

namespace {

// A hollow square ring, one cell thick, in the z=1 plane of a 63x63x3
// lattice -- 244 cells round: the long-detour case. Cutting one ring cell
// leaves the two sides joined only the long way round, further than the
// default budget for a one-cell box (8 x 27 = 216 visits), which is what a
// pylon hit looks like from inside its own carve box.
voxel::DistanceField make_ring_baked() {
    voxel::DistanceField f;
    f.dims = glm::ivec3(63, 63, 3);
    f.cell = glm::vec3(1.0f);
    f.origin = glm::vec3(0.0f);
    f.scale = 1.0f;
    f.dist.assign(63u * 63u * 3u, static_cast<std::int8_t>(127));
    for (int i = 1; i <= 61; ++i) {
        f.dist[f.index(i, 1, 1)] = -10;  f.dist[f.index(i, 61, 1)] = -10;
        f.dist[f.index(1, i, 1)] = -10;  f.dist[f.index(61, i, 1)] = -10;
    }
    return f;
}

}  // namespace

TEST(HullSeveranceLocal, CarveInTheMiddleOfABlobIsConnected) {
    const auto baked = make_dumbbell_baked();
    auto damage = undamaged_like(baked);
    damage.dist[damage.index(3, 3, 3)] = 127;         // centre of the left blob
    const voxel::CellBox box{glm::ivec3(3, 3, 3), glm::ivec3(3, 3, 3)};
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box),
              voxel::Severance::kConnected);
}

TEST(HullSeveranceLocal, CuttingTheNeckIsNotConnected) {
    const auto baked = make_dumbbell_baked();
    auto damage = undamaged_like(baked);
    damage.dist[damage.index(8, 3, 3)] = 127;
    const voxel::CellBox box{glm::ivec3(8, 3, 3), glm::ivec3(8, 3, 3)};
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box),
              voxel::Severance::kUnknown);
}

TEST(HullSeveranceLocal, AnIslandLeftInsideTheBoxIsNotConnected) {
    // Carve a 3x3x3 shell inside the left blob, leaving its centre cell as an
    // island that touches nothing. The shell around the box is all still
    // joined -- only the interior target is unreachable.
    const auto baked = make_dumbbell_baked();
    auto damage = undamaged_like(baked);
    for (int z = 2; z <= 4; ++z) for (int y = 2; y <= 4; ++y) for (int x = 2; x <= 4; ++x)
        if (!(x == 3 && y == 3 && z == 3)) damage.dist[damage.index(x, y, z)] = 127;
    const voxel::CellBox box{glm::ivec3(2, 2, 2), glm::ivec3(4, 4, 4)};
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box),
              voxel::Severance::kUnknown);
    // And the full BFS agrees that something came off.
    EXPECT_EQ(voxel::hull_connectivity(baked, damage).detached.size(), 1u);
}

TEST(HullSeveranceLocal, LongDetourExceedsTheCapAndReportsUnknown) {
    const auto baked = make_ring_baked();
    auto damage = undamaged_like(baked);
    damage.dist[damage.index(31, 1, 1)] = 127;        // cut the bottom side
    const voxel::CellBox box{glm::ivec3(31, 1, 1), glm::ivec3(31, 1, 1)};
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box),
              voxel::Severance::kUnknown)
        << "the two sides reconnect only 240 cells away, past the visit cap";
    EXPECT_TRUE(voxel::hull_connectivity(baked, damage).detached.empty())
        << "kUnknown is 'ask the BFS', not 'severed' -- the ring is still one piece";
    // With an explicit cap big enough to walk the ring, the local check does
    // reach every shell cell and says so.
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box, 1000),
              voxel::Severance::kConnected);
}

TEST(HullSeveranceLocal, NothingOccupiedNearTheBoxIsConnected) {
    const auto baked = make_dumbbell_baked();
    const auto damage = undamaged_like(baked);
    const voxel::CellBox box{glm::ivec3(8, 0, 0), glm::ivec3(8, 0, 0)};   // empty corner
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box),
              voxel::Severance::kConnected);
}

TEST(HullSeveranceLocal, EmptyBoxOrMismatchedLatticeIsUnknown) {
    const auto baked = make_dumbbell_baked();
    const auto damage = undamaged_like(baked);
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, voxel::CellBox{}),
              voxel::Severance::kUnknown);
    auto other = damage;
    other.dims.x += 1;
    EXPECT_EQ(voxel::hull_severance_local(baked, other,
                                          voxel::CellBox{glm::ivec3(3), glm::ivec3(3)}),
              voxel::Severance::kUnknown);
}

TEST(HullSeveranceLocal, BoxOnTheLatticeEdgeDoesNotReadOutOfBounds) {
    const auto baked = make_dumbbell_baked();
    auto damage = undamaged_like(baked);
    const voxel::CellBox box{glm::ivec3(0, 0, 0), glm::ivec3(16, 6, 6)};   // whole lattice
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box, 100000),
              voxel::Severance::kConnected);
}

TEST(HullSeveranceLocal, ABoxCoveringMostOfTheLatticeHandsOffAtOnce) {
    // With the default budget a near-whole-lattice box is the BFS's job:
    // kUnknown without flooding. An explicit budget still runs the flood.
    const auto baked = make_dumbbell_baked();
    const auto damage = undamaged_like(baked);
    const voxel::CellBox box{glm::ivec3(0, 0, 0), glm::ivec3(16, 6, 6)};
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box),
              voxel::Severance::kUnknown);
    EXPECT_EQ(voxel::hull_severance_local(baked, damage, box, 100000),
              voxel::Severance::kConnected);
}
