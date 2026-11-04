#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

#include "dauntless/combat/k4_eligibility.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/step_scan.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

struct World {
    TransformStore store;
    Mirror m{store};
    StepScan scan;

    int64_t set() { return m.register_row(Kind::Set); }

    int64_t ship(int64_t in_set, double x, double radius, uint64_t py_id) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, x, 0.0, 0.0);
        const int64_t h = m.register_row(Kind::Object, i, g, -1, py_id);
        m.set_i(h, Field::has_real_is_dead, 1);
        m.set_i(h, Field::is_ship_class, 1);
        m.set_ref(h, Field::_containing_set, in_set);
        m.set_f(h, Field::o_radius, radius);
        return h;
    }

    // The binding's part of the scan, then the row checks.
    ScanWhy scan_ships(const std::vector<int64_t>& ships) {
        scan.begin();
        scan.ships = ships;
        return check_rows(m, scan);
    }
};

}  // namespace

// Equal scores (identical ships at one point) break by py_id, ascending,
// whatever the list order.
TEST(K4, TieBreak) {
    World w;
    const int64_t s = w.set();
    const int64_t player = w.ship(s, 0.0, 2.0, 1000);
    // py_ids deliberately out of list order.
    const uint64_t ids[] = {907, 300, 512, 120, 777, 640, 233, 450};
    std::vector<int64_t> ships{player};
    for (uint64_t id : ids) ships.push_back(w.ship(s, 5.0, 2.0, id));
    ASSERT_EQ(w.scan_ships(ships), ScanWhy::ok);
    const K4Result r = k4_eligible(w.m, w.scan, player, 6, 1.0, 1.0);
    ASSERT_TRUE(r.ok);
    // Five slots after the player: py_ids 120, 233, 300, 450, 512, which
    // sit at list indices 4, 7, 2, 8, 3.
    EXPECT_EQ(r.indices, (std::vector<int64_t>{4, 7, 2, 8, 3}));
    // max_count 1: the player alone; 0 and negative likewise.
    EXPECT_TRUE(k4_eligible(w.m, w.scan, player, 1, 1.0, 1.0).indices.empty());
    EXPECT_TRUE(k4_eligible(w.m, w.scan, player, 0, 1.0, 1.0).indices.empty());
    EXPECT_TRUE(k4_eligible(w.m, w.scan, player, -3, 1.0, 1.0).indices.empty());
    // No player: six slots, the player row is just another ship (py_id 1000
    // is the largest, so it loses every tie).
    const K4Result np = k4_eligible(w.m, w.scan, -1, 6, 1.0, 1.0);
    ASSERT_TRUE(np.ok);
    EXPECT_EQ(np.indices, (std::vector<int64_t>{4, 7, 2, 8, 3, 6}));
}

// The size term reads the SCALED radius (world_radius): a base-1.0 ship at
// scale 3 outsizes a base-2.0 one; a NaN scale falls back to the base.
TEST(K4, SizeUsesScaledRadius) {
    World w;
    const int64_t s = w.set();
    const int64_t a = w.ship(s, 1.0, 1.0, 1);
    const int64_t b = w.ship(s, 1.0, 2.0, 2);
    ASSERT_EQ(w.scan_ships({a, b}), ScanWhy::ok);
    w.m.set_f(a, Field::_scale, 3.0);
    K4Result r = k4_eligible(w.m, w.scan, -1, 1, 0.0, 1.0);
    ASSERT_TRUE(r.ok);
    EXPECT_EQ(r.indices, (std::vector<int64_t>{0}));
    w.m.set_f(a, Field::_scale, std::numeric_limits<double>::quiet_NaN());
    r = k4_eligible(w.m, w.scan, -1, 1, 0.0, 1.0);
    ASSERT_TRUE(r.ok);
    EXPECT_EQ(r.indices, (std::vector<int64_t>{1}));
}

// E1: max(radii, default=0.0) or 1.0 -- all-zero radii (either sign) and
// an empty list divide by 1.0; a negative maximum stays.
TEST(K4, MaxROrOne) {
    World w;
    const int64_t s = w.set();
    // All zero: size 0.0 everywhere, so proximity alone decides: nearest
    // first.
    std::vector<int64_t> ships{w.ship(s, 3.0, -0.0, 1), w.ship(s, 1.0, 0.0, 2),
                               w.ship(s, 2.0, 0.0, 3)};
    const int64_t player = w.ship(s, 0.0, 0.0, 4);
    ASSERT_EQ(w.scan_ships(ships), ScanWhy::ok);
    K4Result r = k4_eligible(w.m, w.scan, player, 3, 1.0, 1.0);
    ASSERT_TRUE(r.ok);
    EXPECT_EQ(r.indices, (std::vector<int64_t>{1, 2}));
    // A NaN size would show up here: 0.0 / 0.0. With max_r 1.0 every score
    // is finite, so the call succeeds; a weight of 0 on proximity leaves
    // every score 0.0 and the order to py_id.
    r = k4_eligible(w.m, w.scan, player, 3, 0.0, 1.0);
    ASSERT_TRUE(r.ok);
    EXPECT_EQ(r.indices, (std::vector<int64_t>{0, 1}));
    // Empty list: nothing to add.
    ASSERT_EQ(w.scan_ships({}), ScanWhy::ok);
    r = k4_eligible(w.m, w.scan, player, 6, 1.0, 1.0);
    ASSERT_TRUE(r.ok);
    EXPECT_TRUE(r.indices.empty());
    // Negative radii: max_r is the (negative) maximum, not 1.0, so size =
    // r / max_r flips the order: -4 / -1 = 4 beats -1 / -1 = 1.
    World n;
    const int64_t ns = n.set();
    std::vector<int64_t> neg{n.ship(ns, 0.0, -1.0, 1), n.ship(ns, 0.0, -4.0, 2)};
    ASSERT_EQ(n.scan_ships(neg), ScanWhy::ok);
    r = k4_eligible(n.m, n.scan, -1, 1, 1.0, 1.0);
    ASSERT_TRUE(r.ok);
    EXPECT_EQ(r.indices, (std::vector<int64_t>{1}));
    // A NaN radius hands the call back.
    n.m.set_f(neg[0], Field::o_radius, std::numeric_limits<double>::quiet_NaN());
    r = k4_eligible(n.m, n.scan, -1, 1, 1.0, 1.0);
    EXPECT_FALSE(r.ok);
    EXPECT_EQ(r.why, K4Why::nonfinite);
}

// offset_between(a, a): exact zeros for a live set without a frame-table
// entry (Python never resolves it); None for no set; -2 is Python's call.
TEST(Frames, SameSetShortCircuit) {
    World w;
    const int64_t s = w.set();
    Vec3 out{9.0, 9.0, 9.0};
    ASSERT_TRUE(w.scan.frames.empty());
    EXPECT_EQ(offset_between(w.m, w.scan, s, s, out), OffsetStatus::ok);
    EXPECT_EQ(std::signbit(out[0]), false);
    EXPECT_EQ(out, (Vec3{0.0, 0.0, 0.0}));
    EXPECT_EQ(offset_between(w.m, w.scan, -1, -1, out), OffsetStatus::none);
    EXPECT_EQ(offset_between(w.m, w.scan, kRefUnrepresentable,
                             kRefUnrepresentable, out),
              OffsetStatus::unrepresentable);
    // A freed set is not a set any more.
    const int64_t gone = w.set();
    w.m.unregister_row(gone);
    EXPECT_EQ(offset_between(w.m, w.scan, gone, gone, out),
              OffsetStatus::unrepresentable);
}

// Different sets: different frame keys (or a None frame) -> None; one key
// -> b.anchor - a.anchor; a set with no entry -> missing.
TEST(Frames, DifferentKeysNone) {
    World w;
    const int64_t a = w.set(), b = w.set(), c = w.set(), d = w.set(),
                  e = w.set();
    w.scan.frames = {{a, 0, {10.0, 0.5, -2.0}},
                     {b, 0, {1000.25, 0.5, 3.0}},
                     {c, 1, {10.0, 0.5, -2.0}},
                     {d, -1, {0.0, 0.0, 0.0}}};
    Vec3 out{};
    EXPECT_EQ(offset_between(w.m, w.scan, a, c, out), OffsetStatus::none);
    EXPECT_EQ(offset_between(w.m, w.scan, a, d, out), OffsetStatus::none);
    EXPECT_EQ(offset_between(w.m, w.scan, d, a, out), OffsetStatus::none);
    EXPECT_EQ(offset_between(w.m, w.scan, a, -1, out), OffsetStatus::none);
    EXPECT_EQ(offset_between(w.m, w.scan, -1, a, out), OffsetStatus::none);
    ASSERT_EQ(offset_between(w.m, w.scan, a, b, out), OffsetStatus::ok);
    EXPECT_EQ(out, (Vec3{1000.25 - 10.0, 0.5 - 0.5, 3.0 - -2.0}));
    ASSERT_EQ(offset_between(w.m, w.scan, b, a, out), OffsetStatus::ok);
    EXPECT_EQ(out, (Vec3{10.0 - 1000.25, 0.5 - 0.5, -2.0 - 3.0}));
    EXPECT_EQ(offset_between(w.m, w.scan, a, e, out), OffsetStatus::missing);
    EXPECT_EQ(offset_between(w.m, w.scan, a, kRefUnrepresentable, out),
              OffsetStatus::unrepresentable);
}

// The row checks: a duplicate, a stale row, no real IsDead and an
// unrepresentable set each make the scan unrepresentable; the sets in play
// are the ships' then the torpedoes', distinct, in first-seen order.
TEST(StepScan, RowChecksAndSets) {
    World w;
    const int64_t s1 = w.set(), s2 = w.set(), s3 = w.set();
    const int64_t a = w.ship(s2, 0.0, 1.0, 1), b = w.ship(s1, 0.0, 1.0, 2),
                  c = w.ship(-1, 0.0, 1.0, 3), d = w.ship(s2, 0.0, 1.0, 4);
    const int64_t t = w.m.torpedoes().add(-1, -1);
    w.m.set_torpedo_ref(t, TorpField::_containing_set, s3);
    const int64_t t2 = w.m.torpedoes().add(-1, -1);
    w.m.set_torpedo_ref(t2, TorpField::_containing_set, s1);
    ASSERT_EQ(w.scan_ships({a, b, c, d}), ScanWhy::ok);
    EXPECT_TRUE(w.scan.representable);
    EXPECT_EQ(w.scan.sets, (std::vector<int64_t>{s2, s1, s3}));
    EXPECT_EQ(w.scan_ships({a, b, a}), ScanWhy::duplicate);
    EXPECT_FALSE(w.scan.representable);
    w.m.set_i(d, Field::has_real_is_dead, 0);
    EXPECT_EQ(w.scan_ships({a, d}), ScanWhy::is_dead);
    // Not a ShipClass: an engine class (ProximityCheck) may answer
    // GetRadius from another attribute.
    w.m.set_i(d, Field::has_real_is_dead, 1);
    w.m.set_i(d, Field::is_ship_class, 0);
    EXPECT_EQ(w.scan_ships({a, d}), ScanWhy::not_ship);
    w.m.set_ref(b, Field::_containing_set, kRefUnrepresentable);
    EXPECT_EQ(w.scan_ships({a, b}), ScanWhy::set);
    w.m.unregister_row(c);
    EXPECT_EQ(w.scan_ships({a, c}), ScanWhy::stale);
    const uint64_t serial = w.scan.serial;
    w.scan.begin();
    EXPECT_EQ(w.scan.serial, serial + 1);
    EXPECT_TRUE(w.scan.ships.empty() && w.scan.sets.empty() &&
                w.scan.frames.empty());
}

// A ship in another frame (or in no set) gets prox 0.0; one in the same
// system but another region is shifted by the anchor difference.
TEST(K4, CrossFrameNoProximity) {
    World w;
    const int64_t a1 = w.set(), a2 = w.set(), b1 = w.set();
    const int64_t player = w.ship(a1, 10.0, 1.0, 1);
    const int64_t other_frame = w.ship(b1, 10.0, 1.0, 2);
    const int64_t far_same = w.ship(a1, 900.0, 1.0, 3);
    const int64_t shifted = w.ship(a2, -990.0, 1.0, 4);  // 0 GU after shift
    const int64_t setless = w.ship(-1, 10.0, 1.0, 5);
    ASSERT_EQ(w.scan_ships({player, other_frame, far_same, shifted, setless}),
              ScanWhy::ok);
    // No frames yet: the cross-set compare is missing an entry.
    K4Result r = k4_eligible(w.m, w.scan, player, 3, 1.0, 1.0);
    EXPECT_FALSE(r.ok);
    EXPECT_EQ(r.why, K4Why::frame);
    w.scan.frames = {{a1, 0, {0.0, 0.0, 0.0}},
                     {a2, 0, {1000.0, 0.0, 0.0}},
                     {b1, 1, {0.0, 0.0, 0.0}}};
    r = k4_eligible(w.m, w.scan, player, 3, 1.0, 1.0);
    ASSERT_TRUE(r.ok);
    EXPECT_EQ(r.indices, (std::vector<int64_t>{3, 2}));
    // A stale player hands back.
    r = k4_eligible(w.m, w.scan, setless + 1, 3, 1.0, 1.0);
    EXPECT_FALSE(r.ok);
    EXPECT_EQ(r.why, K4Why::player);
}
