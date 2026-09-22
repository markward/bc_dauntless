#include <gtest/gtest.h>
#include <scenegraph/hull_carve.h>
using scenegraph::HullCarve;
using scenegraph::HullCarveField;

TEST(HullCarveField, AccumulatesStrengthOnMerge) {
    HullCarveField f;
    EXPECT_EQ(f.count(), 0u);
    HullCarve& a = f.add({0, 0, 0}, 2.0f, 100.0f, {0, 0, 1});
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(a.strength, 100.0f);
    // Within kMergeFactor*influ (0.5*2=1.0): merges, accumulates strength,
    // widens influ to the max, moves to the freshest centre.
    HullCarve& b = f.add({0.5f, 0, 0}, 3.0f, 250.0f, {0, 0, 1});
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(b.strength, 350.0f);     // 100 + 250
    EXPECT_FLOAT_EQ(b.influ_radius, 3.0f);   // widened to max
    // Center does NOT slide to the new hit — the carve deepens in place so a
    // swept beam leaves a gouge, not one sliding sphere.
    EXPECT_FLOAT_EQ(b.center_body.x, 0.0f);
    // Far apart: new slot.
    f.add({100, 0, 0}, 2.0f, 50.0f, {0, 0, 1});
    EXPECT_EQ(f.count(), 2u);
}

TEST(HullCarveField, EvictsSmallestRadiusWhenFull) {
    HullCarveField f;
    for (std::size_t i = 0; i < HullCarveField::kMaxCarves; ++i) {
        HullCarve& c = f.add({float(i) * 1000.f, 0, 0}, 5.0f, 10.0f, {0, 0, 1});
        c.radius = 5.0f;   // caller owns the visible radius
    }
    EXPECT_EQ(f.count(), HullCarveField::kMaxCarves);
    f.add({999000.f, 0, 0}, 5.0f, 10.0f, {0, 0, 1});  // far away -> evicts a slot
    EXPECT_EQ(f.count(), HullCarveField::kMaxCarves);  // still capped
}

TEST(HullCarveStrengthCurve, IsoGatesThenGrowsToAbsoluteClamp) {
    using scenegraph::hull_carve_strength_to_radius_gu;
    EXPECT_FLOAT_EQ(hull_carve_strength_to_radius_gu(0.0f), 0.0f);
    EXPECT_FLOAT_EQ(hull_carve_strength_to_radius_gu(149.0f), 0.0f);   // below iso: invisible
    // At the iso the carve emerges SMALL (no chunky pop), then grows.
    EXPECT_FLOAT_EQ(hull_carve_strength_to_radius_gu(150.0f),
                    scenegraph::kHullCarveRadiusAtIso);
    EXPECT_GT(hull_carve_strength_to_radius_gu(450.0f),
              hull_carve_strength_to_radius_gu(300.0f));               // monotonic growth
    // A full breach is an absolute clamp (game units), not ship-relative.
    EXPECT_FLOAT_EQ(hull_carve_strength_to_radius_gu(100000.0f),
                    scenegraph::kHullCarveRadiusMaxGu);
}

#include <scenegraph/instance.h>
TEST(Instance, HasCarveField) {
    scenegraph::Instance inst;
    EXPECT_EQ(inst.carve.count(), 0u);
    inst.carve.add({1, 2, 3}, 4.0f, 10.0f, {0, 0, 1});
    EXPECT_EQ(inst.carve.count(), 1u);
}

// ── birth_time: when the glow flicker around this breach started ──────────
//
// opaque.frag fades the flicker out over kGlowFlickerSecs from this value, so
// it has to be the carve's own clock, not the ring's.
TEST(HullCarveBirthTime, ADepositRecordsTheClockItArrivedOn) {
    scenegraph::HullCarveField f;
    const scenegraph::HullCarve& c =
        f.add(glm::vec3(0.0f), /*influ_radius=*/10.0f, /*strength=*/200.0f,
              glm::vec3(0, 0, 1), /*birth_time=*/42.5f);
    EXPECT_FLOAT_EQ(c.birth_time, 42.5f);
}

// A re-hit at the same place is a FRESH wound, so the flicker restarts with
// it -- the same reasoning `seq` is refreshed on a merge for. Without this a
// compartment breached once would stop flickering 60 s later and stay dark
// however many more times it was hit.
TEST(HullCarveBirthTime, AMergedReHitRefreshesIt) {
    scenegraph::HullCarveField f;
    f.add(glm::vec3(0.0f), 10.0f, 200.0f, glm::vec3(0, 0, 1), /*birth=*/5.0f);

    // Inside kMergeFactor * influ_radius, so this accumulates in place rather
    // than taking a new slot.
    const scenegraph::HullCarve& c =
        f.add(glm::vec3(1.0f, 0.0f, 0.0f), 10.0f, 200.0f, glm::vec3(0, 0, 1),
              /*birth=*/90.0f);

    ASSERT_EQ(f.count(), 1u) << "the second hit should have merged, not allocated";
    EXPECT_FLOAT_EQ(c.birth_time, 90.0f)
        << "a re-hit left the original birth time, so the flicker stays "
           "settled through fresh damage";
}

// Default 0: every existing caller and test that has no clock to offer keeps
// its current behaviour, because a birth of 0 against any positive decal time
// reads as long-settled.
TEST(HullCarveBirthTime, DefaultsToZeroForCallersWithNoClock) {
    scenegraph::HullCarveField f;
    const scenegraph::HullCarve& c =
        f.add(glm::vec3(0.0f), 10.0f, 200.0f, glm::vec3(0, 0, 1));
    EXPECT_FLOAT_EQ(c.birth_time, 0.0f);
}
