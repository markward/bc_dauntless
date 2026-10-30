#include <gtest/gtest.h>
#include "dauntless/torpedo_scan.h"
#include "dauntless/transform_store.h"

#include <cstdint>
#include <vector>

using dauntless::TorpedoScan;
using dauntless::TransformStore;

namespace {

constexpr std::int64_t kSet = 7;

struct Fixture {
    TransformStore store;
    TorpedoScan scan{store};

    // A torpedo at `pos` moving `vel`, in group kSet unless told otherwise.
    void torp(std::int64_t id, double x, double y, double z,
              double vx, double vy, double vz,
              std::int64_t group = kSet, bool has_source = false,
              std::int64_t source = 0) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, y, z);
        scan.add(id, i, g, vx, vy, vz, has_source, source, group);
    }

    std::vector<std::int64_t> incoming(
            double threshold, bool match = false, std::int64_t firing = 0,
            std::vector<TorpedoScan::GroupOffset> offsets = {{kSet, {0, 0, 0}}}) {
        const double o[3] = {0, 0, 0};
        const double ov[3] = {0, 0, 0};
        return scan.incoming(o, ov, threshold, match, firing, offsets);
    }
};

}  // namespace

TEST(TorpedoScanTest, ListsOnlyTorpedoesClosingWithinTheThreshold) {
    Fixture f;
    f.torp(1, 0, 100, 0, 0, -50, 0);     // ETA 2 s
    f.torp(2, 0, 100, 0, 0, 50, 0);      // receding
    f.torp(3, 0, 1000, 0, 0, -10, 0);    // ETA 100 s
    EXPECT_EQ(f.incoming(18.0), (std::vector<std::int64_t>{1}));
}

TEST(TorpedoScanTest, ATorpedoOnTopOfTheObserverIsIncoming) {
    Fixture f;
    f.torp(1, 0, 0, 0, 0, 0, 0);
    EXPECT_EQ(f.incoming(0.0), (std::vector<std::int64_t>{1}));
}

TEST(TorpedoScanTest, ObserverVelocityIsSubtracted) {
    Fixture f;
    f.torp(1, 0, 100, 0, 0, 0, 0);       // parked torpedo
    const double o[3] = {0, 0, 0};
    const double ov[3] = {0, 50, 0};      // observer flying into it
    std::vector<TorpedoScan::GroupOffset> offs = {{kSet, {0, 0, 0}}};
    EXPECT_EQ(f.scan.incoming(o, ov, 18.0, false, 0, offs),
              (std::vector<std::int64_t>{1}));
}

TEST(TorpedoScanTest, GroupsWithoutAnOffsetAreNeverIncoming) {
    Fixture f;
    f.torp(1, 0, 100, 0, 0, -50, 0, /*group=*/kSet);
    f.torp(2, 0, 100, 0, 0, -50, 0, /*group=*/99);
    EXPECT_EQ(f.incoming(18.0), (std::vector<std::int64_t>{1}));
}

TEST(TorpedoScanTest, AGroupOffsetMovesTheTorpedoIntoTheObserversFrame) {
    Fixture f;
    // Set-local (0, 1100, 0) in a region 1000 GU further back on Y: at the
    // observer's (0, 100, 0) once shifted, ETA 2 s.
    f.torp(1, 0, 1100, 0, 0, -50, 0);
    EXPECT_EQ(f.incoming(18.0, false, 0, {{kSet, {0, -1000, 0}}}),
              (std::vector<std::int64_t>{1}));
    EXPECT_TRUE(f.incoming(18.0).empty());
}

TEST(TorpedoScanTest, AnArmedSourceFilterMatchesOnlyThatShooter) {
    Fixture f;
    f.torp(1, 0, 100, 0, 0, -50, 0, kSet, true, 40);
    f.torp(2, 0, 100, 0, 0, -50, 0, kSet, true, 41);
    f.torp(3, 0, 100, 0, 0, -50, 0, kSet, false, 0);
    EXPECT_EQ(f.incoming(18.0, true, 40), (std::vector<std::int64_t>{1}));
    EXPECT_EQ(f.incoming(18.0).size(), 3u);
}

TEST(TorpedoScanTest, ResultsKeepInsertionOrderAcrossRemovalAndCompaction) {
    Fixture f;
    for (std::int64_t id = 1; id <= 200; ++id) f.torp(id, 0, 100, 0, 0, -50, 0);
    for (std::int64_t id = 1; id <= 200; id += 2) EXPECT_TRUE(f.scan.remove(id));
    f.torp(500, 0, 100, 0, 0, -50, 0);
    std::vector<std::int64_t> want;
    for (std::int64_t id = 2; id <= 200; id += 2) want.push_back(id);
    want.push_back(500);
    EXPECT_EQ(f.incoming(18.0), want);
    EXPECT_EQ(f.scan.size(), want.size());
}

TEST(TorpedoScanTest, UpdatesReachTheRow) {
    Fixture f;
    f.torp(1, 0, 100, 0, 0, 50, 0);      // receding
    EXPECT_TRUE(f.incoming(18.0).empty());
    f.scan.set_velocity(1, 0, -50, 0);
    EXPECT_EQ(f.incoming(18.0).size(), 1u);
    f.scan.set_group(1, 99);
    EXPECT_TRUE(f.incoming(18.0).empty());
    f.scan.set_group(1, kSet);
    f.scan.set_source(1, true, 40);
    EXPECT_TRUE(f.incoming(18.0, true, 41).empty());
    EXPECT_EQ(f.incoming(18.0, true, 40).size(), 1u);
}

TEST(TorpedoScanTest, UnknownIdsAreIgnored) {
    Fixture f;
    EXPECT_FALSE(f.scan.remove(5));
    f.scan.set_velocity(5, 1, 2, 3);
    f.scan.set_group(5, 1);
    f.scan.set_source(5, true, 1);
    EXPECT_EQ(f.scan.size(), 0u);
}

TEST(TorpedoScanTest, PositionsAreReadLiveFromTheStore) {
    Fixture f;
    auto [i, g] = f.store.alloc();
    f.store.set_position(i, g, 0, 1000, 0);
    f.scan.add(1, i, g, 0, -50, 0, false, 0, kSet);
    EXPECT_TRUE(f.incoming(18.0).empty());   // ETA 20 s
    f.store.set_position(i, g, 0, 100, 0);
    EXPECT_EQ(f.incoming(18.0).size(), 1u);
}

TEST(TorpedoScanTest, AStaleTransformIsSkipped) {
    Fixture f;
    auto [i, g] = f.store.alloc();
    f.store.set_position(i, g, 0, 100, 0);
    f.scan.add(1, i, g, 0, -50, 0, false, 0, kSet);
    f.store.free(i, g);
    EXPECT_TRUE(f.incoming(18.0).empty());
}

TEST(TorpedoScanTest, ClearEmptiesTheTable) {
    Fixture f;
    f.torp(1, 0, 100, 0, 0, -50, 0);
    f.scan.clear();
    EXPECT_EQ(f.scan.size(), 0u);
    EXPECT_TRUE(f.incoming(18.0).empty());
}
