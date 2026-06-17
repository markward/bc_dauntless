#include <gtest/gtest.h>
#include "scenegraph/breach_events.h"

using scenegraph::BreachEvent;
using scenegraph::BreachEventRing;

namespace {
const BreachEvent* first_active(const BreachEventRing& ring) {
    for (const auto& e : ring.slots()) if (e.active) return &e;
    return nullptr;
}
} // namespace

TEST(BreachEventRing, PushCreatesOneActiveEvent) {
    BreachEventRing ring;
    ring.push({1.f, 2.f, 3.f}, 1.5f, 0.0f, 42u);
    EXPECT_EQ(ring.count(), 1u);
    const BreachEvent* e = first_active(ring);
    ASSERT_NE(e, nullptr);
    EXPECT_FLOAT_EQ(e->center_body.x, 1.f);
    EXPECT_FLOAT_EQ(e->radius, 1.5f);
    EXPECT_FLOAT_EQ(e->birth_time, 0.0f);
    EXPECT_EQ(e->seed, 42u);
    EXPECT_TRUE(e->active);
}

TEST(BreachEventRing, FullRingOverwritesOldest) {
    BreachEventRing ring;
    for (std::size_t i = 0; i < BreachEventRing::kMaxEvents; ++i) {
        ring.push({static_cast<float>(i), 0.f, 0.f}, 1.f,
                  static_cast<float>(i), static_cast<std::uint64_t>(i));
    }
    EXPECT_EQ(ring.count(), BreachEventRing::kMaxEvents);
    // One more push overwrites the oldest (center_body.x == 0).
    ring.push({999.f, 0.f, 0.f}, 1.f, 100.f, 999u);
    EXPECT_EQ(ring.count(), BreachEventRing::kMaxEvents);
    bool found_zero = false;
    for (const auto& e : ring.slots()) {
        if (e.active && e.center_body.x == 0.f) { found_zero = true; break; }
    }
    EXPECT_FALSE(found_zero) << "oldest event (x=0) should have been overwritten";
}

TEST(BreachEventRing, TickExpiresAtEventLife) {
    BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.0f, 1u);
    ring.tick(scenegraph::kEventLife - 0.001f);
    EXPECT_EQ(ring.count(), 1u)     << "must still be active before kEventLife";
    ring.tick(scenegraph::kEventLife + 0.001f);
    EXPECT_EQ(ring.count(), 0u)     << "must be deactivated at/past kEventLife";
}

TEST(BreachEventRing, SlotsAccessorReturnsAll) {
    BreachEventRing ring;
    EXPECT_EQ(ring.slots().size(), BreachEventRing::kMaxEvents);
}

TEST(BreachEventRing, CountsOnlyActiveSlots) {
    BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 1u);
    ring.push({1.f, 0.f, 0.f}, 1.f, 0.f, 2u);
    EXPECT_EQ(ring.count(), 2u);
    ring.tick(scenegraph::kEventLife + 1.f);
    EXPECT_EQ(ring.count(), 0u);
}

TEST(BreachEventRing, SeedIsStoredVerbatim) {
    BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 0xDEADBEEFull);
    EXPECT_EQ(first_active(ring)->seed, 0xDEADBEEFull);
}
