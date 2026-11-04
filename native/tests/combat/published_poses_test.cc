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

// The read window (native motion phase 4, Task 4): pose_for answers from the
// published copy while the window is open, keyed by the published row's
// store slot (index, generation); closed, or a slot not published, is null.
TEST(PublishedPoses, PoseForWhileOpen) {
    World w;
    const int64_t a = w.ship(1.0, 0.0);
    const ObjectRow* o = w.m.object(a);
    const auto xi = static_cast<uint32_t>(o->xform_index);
    const auto xg = static_cast<uint32_t>(o->xform_gen);
    PublishedPoses p;
    p.publish(w.m, w.store, {a}, 1);
    EXPECT_TRUE(p.is_open());
    w.store.set_position(xi, xg, 50.0, 60.0, 70.0);  // a write after publish
    const TransformStore::Transform* t = p.pose_for(xi, xg);
    ASSERT_NE(t, nullptr);
    EXPECT_EQ(t->pos[0], 1.0);
    EXPECT_EQ(t->pos[1], 2.0);
    EXPECT_EQ(t->pos[2], 3.0);
    for (int i = 0; i < 9; ++i) EXPECT_EQ(t->rot[i], w.store.at(xi).rot[i]);
}

TEST(PublishedPoses, ClosedReturnsNull) {
    World w;
    const int64_t a = w.ship(1.0, 0.0);
    const ObjectRow* o = w.m.object(a);
    const auto xi = static_cast<uint32_t>(o->xform_index);
    const auto xg = static_cast<uint32_t>(o->xform_gen);
    PublishedPoses p;
    EXPECT_FALSE(p.is_open());
    EXPECT_EQ(p.pose_for(xi, xg), nullptr);  // never published
    p.publish(w.m, w.store, {a}, 1);
    p.close();
    EXPECT_FALSE(p.is_open());
    EXPECT_EQ(p.pose_for(xi, xg), nullptr);
    EXPECT_EQ(p.find(a)->pos[0], 1.0);  // the rows themselves stay
    p.publish(w.m, w.store, {a}, 2);
    p.clear();
    EXPECT_FALSE(p.is_open());
    EXPECT_EQ(p.pose_for(xi, xg), nullptr);
}

TEST(PublishedPoses, StaleGenerationReturnsNull) {
    World w;
    const int64_t a = w.ship(1.0, 0.0);
    const int64_t b = w.ship(2.0, 0.0);  // published, a different slot
    const ObjectRow* o = w.m.object(a);
    const auto xi = static_cast<uint32_t>(o->xform_index);
    const auto xg = static_cast<uint32_t>(o->xform_gen);
    PublishedPoses p;
    p.publish(w.m, w.store, {a, b}, 1);
    ASSERT_NE(p.pose_for(xi, xg), nullptr);
    EXPECT_EQ(p.pose_for(xi, xg + 1), nullptr);  // the slot, reused
    w.store.free(xi, xg);
    auto [ri, rg] = w.store.alloc();
    ASSERT_EQ(ri, xi);
    EXPECT_EQ(p.pose_for(ri, rg), nullptr);
}

TEST(PublishedPoses, PublishReopens) {
    World w;
    const int64_t a = w.ship(1.0, 0.0);
    const int64_t b = w.ship(2.0, 0.0);
    const ObjectRow* oa = w.m.object(a);
    const ObjectRow* ob = w.m.object(b);
    PublishedPoses p;
    p.publish(w.m, w.store, {a}, 1);
    p.close();
    w.store.set_position(static_cast<uint32_t>(oa->xform_index),
                         static_cast<uint32_t>(oa->xform_gen), 9.0, 0.0, 0.0);
    p.publish(w.m, w.store, {b}, 2);
    EXPECT_TRUE(p.is_open());
    // Replaced: a is no longer published, b is.
    EXPECT_EQ(p.pose_for(static_cast<uint32_t>(oa->xform_index),
                         static_cast<uint32_t>(oa->xform_gen)),
              nullptr);
    const TransformStore::Transform* t =
        p.pose_for(static_cast<uint32_t>(ob->xform_index),
                   static_cast<uint32_t>(ob->xform_gen));
    ASSERT_NE(t, nullptr);
    EXPECT_EQ(t->pos[0], 2.0);
}
