// The published-pose buffer (published_poses.h).
#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/published_poses.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {
struct World {
    TransformStore store;
    Mirror m{store};
    int64_t ship(double x, double vx) {
        auto [xi, xg] = store.alloc();
        store.set_position(xi, xg, x, 2.0, 3.0);
        const int64_t h = m.register_row(Kind::Object, xi, xg, 1);
        m.set_fv(h, Field::_velocity, {vx, 0.0, 0.0});
        return h;
    }
};
}  // namespace

TEST(PublishedPoses, SkipsStaleAndNone) {
    World w;
    const int64_t a = w.ship(1.0, 4.0);
    const int64_t b = w.ship(5.0, 6.0);
    const int64_t gone = w.ship(9.0, 0.0);
    w.m.unregister_row(gone);
    PublishedPoses p;
    p.publish(w.m, w.store, {a, -1, gone, 9999, b}, 7);
    EXPECT_EQ(p.tick(), 7);
    ASSERT_EQ(p.all().size(), 2u);
    ASSERT_NE(p.find(a), nullptr);
    EXPECT_EQ(p.find(a)->pos[0], 1.0);
    EXPECT_EQ(p.find(a)->vel[0], 4.0);
    EXPECT_EQ(p.find(b)->pos[0], 5.0);
    EXPECT_EQ(p.find(gone), nullptr);
    EXPECT_EQ(p.find(-1), nullptr);
}

TEST(PublishedPoses, ReplacesNotAppends) {
    World w;
    const int64_t a = w.ship(1.0, 0.0);
    const int64_t b = w.ship(2.0, 0.0);
    PublishedPoses p;
    p.publish(w.m, w.store, {a, b}, 1);
    ASSERT_EQ(p.all().size(), 2u);
    p.publish(w.m, w.store, {b}, 2);
    EXPECT_EQ(p.tick(), 2);
    ASSERT_EQ(p.all().size(), 1u);
    EXPECT_EQ(p.find(a), nullptr);
    p.clear();
    EXPECT_TRUE(p.all().empty());
}

TEST(PublishedPoses, SkipsANonPointVelocity) {
    World w;
    const int64_t a = w.ship(1.0, 0.0);
    const int64_t b = w.ship(2.0, 0.0);
    w.m.set_i(b, Field::_velocity_state, 2);
    PublishedPoses p;
    p.publish(w.m, w.store, {a, b}, 1);
    ASSERT_EQ(p.all().size(), 1u);
    EXPECT_NE(p.find(a), nullptr);
    EXPECT_EQ(p.find(b), nullptr);
}
