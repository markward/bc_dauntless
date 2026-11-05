// The subsystem stage session (subsystem_step.h) on hand-built mirror rows:
// its walk order and its skip of a row freed mid-walk. The native-vs-Python
// per-tick differential is
// tests/integration/test_native_subsystems_differential.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/subsystem_step.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kDt = 1.0 / 60.0;

struct World {
    TransformStore store;
    Mirror m{store};

    int64_t ship() {
        auto [xi, xg] = store.alloc();
        return m.register_row(Kind::Object, xi, xg);
    }
};

// (ship_pos, piece) of every record up to DONE, which must come last.
std::vector<std::pair<int64_t, SubsystemPiece>> walk(
        SubsystemSession& s, Mirror& m) {
    std::vector<std::pair<int64_t, SubsystemPiece>> out;
    for (int guard = 0; guard < 1000; ++guard) {
        const SubsystemRecord r = subsystems::next(s, m);
        if (r.type == SubsystemRecordType::DONE) return out;
        EXPECT_EQ(r.type, SubsystemRecordType::RUN_PYTHON);
        out.emplace_back(r.ship_pos, static_cast<SubsystemPiece>(r.kind));
    }
    ADD_FAILURE() << "the session never returned DONE";
    return out;
}

constexpr SubsystemPiece kOrder[] = {
    SubsystemPiece::SHIELD, SubsystemPiece::POWER, SubsystemPiece::CLOAK,
    SubsystemPiece::REPAIR, SubsystemPiece::ARTICULATION};

}  // namespace

TEST(SubsystemStep, AllPythonOrderIsShipThenKind) {
    World w;
    const std::vector<int64_t> ships = {w.ship(), w.ship(), w.ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    EXPECT_EQ(s.dt, kDt);

    std::vector<std::pair<int64_t, SubsystemPiece>> want;
    for (int64_t i = 0; i < 3; ++i)
        for (SubsystemPiece p : kOrder) want.emplace_back(i, p);

    // Each record names its ship's handle too.
    std::vector<SubsystemRecord> records;
    for (;;) {
        const SubsystemRecord r = subsystems::next(s, w.m);
        if (r.type == SubsystemRecordType::DONE) break;
        records.push_back(r);
        ASSERT_LT(records.size(), 100u);
    }
    ASSERT_EQ(records.size(), 15u);
    for (size_t k = 0; k < records.size(); ++k) {
        EXPECT_EQ(records[k].type, SubsystemRecordType::RUN_PYTHON);
        EXPECT_EQ(records[k].ship_pos, want[k].first) << k;
        EXPECT_EQ(static_cast<SubsystemPiece>(records[k].kind),
                  want[k].second) << k;
        EXPECT_EQ(records[k].ship,
                  ships[static_cast<size_t>(want[k].first)]) << k;
    }
    // DONE is the end: asking again is a protocol error.
    EXPECT_THROW(subsystems::next(s, w.m), std::logic_error);
}

TEST(SubsystemStep, SkipsAFreedRow) {
    World w;
    const std::vector<int64_t> ships = {w.ship(), w.ship(), w.ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    const SubsystemRecord first = subsystems::next(s, w.m);
    ASSERT_EQ(first.type, SubsystemRecordType::RUN_PYTHON);
    EXPECT_EQ(first.ship_pos, 0);
    // A handler run for that record destroyed the second ship.
    w.m.unregister_row(ships[1]);
    const auto rest = walk(s, w.m);
    ASSERT_EQ(rest.size(), 4u + 5u);
    for (size_t k = 0; k < 4; ++k) {
        EXPECT_EQ(rest[k].first, 0);
        EXPECT_EQ(rest[k].second, kOrder[k + 1]);
    }
    for (size_t k = 0; k < 5; ++k) {
        EXPECT_EQ(rest[4 + k].first, 2);
        EXPECT_EQ(rest[4 + k].second, kOrder[k]);
    }
}

TEST(SubsystemStep, FreedBetweenPiecesSkipsTheRestOfThatShip) {
    World w;
    const std::vector<int64_t> ships = {w.ship(), w.ship()};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    for (int k = 0; k < 2; ++k)
        ASSERT_EQ(subsystems::next(s, w.m).ship_pos, 0);
    w.m.unregister_row(ships[0]);       // its POWER handler destroyed it
    const auto rest = walk(s, w.m);
    ASSERT_EQ(rest.size(), 5u);
    for (const auto& r : rest) EXPECT_EQ(r.first, 1);
}

TEST(SubsystemStep, AShipWithNoRowIsStillPythons) {
    // A ship the mirror has no row for (-1 or a handle already stale at
    // begin) is not a freed row: the Python stage updates it, so every piece
    // is handed back.
    World w;
    const int64_t gone = w.ship();
    w.m.unregister_row(gone);
    const std::vector<int64_t> ships = {-1, gone};
    SubsystemSession s = subsystems::begin(w.m, ships, kDt);
    const auto all = walk(s, w.m);
    ASSERT_EQ(all.size(), 10u);
    for (size_t k = 0; k < all.size(); ++k) {
        EXPECT_EQ(all[k].first, static_cast<int64_t>(k / 5));
        EXPECT_EQ(all[k].second, kOrder[k % 5]);
    }
}

TEST(SubsystemStep, AnEmptyListIsDone) {
    World w;
    SubsystemSession s = subsystems::begin(w.m, {}, kDt);
    EXPECT_EQ(subsystems::next(s, w.m).type, SubsystemRecordType::DONE);
}
