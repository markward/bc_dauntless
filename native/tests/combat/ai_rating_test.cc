// SelectTarget's candidate rating (ai_rating.h) on hand-worked cases. Each
// expected answer is the SDK's SelectTarget.GetTargetRating
// (AI/Preprocessors.py:1481-1608) worked by hand on the same inputs; the
// seeded differential against the real Python is
// tests/unit/test_native_target_rating.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>

#include "dauntless/combat/ai_rating.h"

using dauntless::combat::RatingInputs;
using dauntless::combat::target_rating;

namespace {

// Our ship at the origin facing +Y; the target 60 GU dead ahead; every factor
// but distance and angle zero, every weight 1.0.
RatingInputs ahead() {
    RatingInputs in{};
    in.our_forward[1] = 1.0;
    in.target_pos[1] = 60.0;
    in.min_full_good_distance = 30.0;
    for (double& w : in.weights) w = 1.0;
    return in;
}

}  // namespace

TEST(AiRating, SumsTheNineFactorsInSdkOrder) {
    // Distance 60: fDistanceGood = 30 / 60 = 0.5. Dead ahead: acos(1) = 0,
    // fAngleGood = 1.0. Everything else 0: 0.0 + 0.5 + 1.0 = 1.5.
    RatingInputs in = ahead();
    EXPECT_EQ(target_rating(in), 1.5);

    // Each factor is scaled by ITS weight (the SDK's list pairs them).
    in.is_target = 1.0;
    in.shield = 0.5;
    in.weapons_sum = 1.5;  // two systems at 0.75 and 0.75
    in.weapons_count = 2;
    in.hull = 0.25;
    in.damage = 2.0;
    in.priority = 3.0;
    in.popularity = 4.0;
    const double w[9] = {2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0};
    for (int i = 0; i < 9; ++i) in.weights[i] = w[i];
    // 0.5*2 + 1*4 + 1*8 + 0.5*16 + 0.75*32 + 0.25*64 + 2*128 + 3*256 + 4*512
    EXPECT_EQ(target_rating(in), 1.0 + 4.0 + 8.0 + 8.0 + 24.0 + 16.0 + 256.0 + 768.0 + 2048.0);

    // Left to right from 0.0, one rounding per term: with 1e16 in the
    // middle the small terms are rounded against it, so the order shows.
    in = ahead();
    in.damage = 1.0e16;
    in.priority = 1.0;
    in.popularity = -1.0e16;
    double sdk = 0.0;
    for (double t : {0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0e16, 1.0, -1.0e16}) sdk = sdk + t;
    EXPECT_EQ(target_rating(in), sdk);
    EXPECT_NE(sdk, 2.5);  // the exact sum: the order is observable
    double reversed = 0.0;
    for (double t : {-1.0e16, 1.0, 1.0e16, 0.0, 0.0, 0.0, 0.0, 1.0, 0.5}) reversed = reversed + t;
    EXPECT_NE(sdk, reversed);

    // The weapons average: the sum over the count, only when count > 0.
    in = ahead();
    in.weights[0] = 0.0;
    in.weights[1] = 0.0;
    in.weapons_sum = 0.1 + 0.2;
    in.weapons_count = 3;
    EXPECT_EQ(target_rating(in), (0.1 + 0.2) / 3.0);
    in.weapons_count = 0;  // fTotal 0: fWeaponsGood stays the (0.0) sum
    in.weapons_sum = 0.0;
    EXPECT_EQ(target_rating(in), 0.0);
}

TEST(AiRating, DistanceAndAngleEdgeCases) {
    // Zero distance: both fDistanceGood and fAngleGood stay 0.0.
    {
        RatingInputs in = ahead();
        in.target_pos[1] = 0.0;
        EXPECT_EQ(target_rating(in), 0.0);
    }
    // Inside the full-good distance: 30 / 10 = 3, capped at 1.0.
    {
        RatingInputs in = ahead();
        in.target_pos[1] = 10.0;
        EXPECT_EQ(target_rating(in), 2.0);
    }
    // Dead behind: acos(-1) = pi, 1 - pi/pi = 0.0; only distance remains.
    {
        RatingInputs in = ahead();
        in.target_pos[1] = -60.0;
        EXPECT_EQ(target_rating(in), 0.5);
    }
    // Abeam: acos(0) / pi = 0.5 exactly? acos(0) = pi/2 rounded; the SDK's
    // 1.0 - (acos(0.0) / pi) is the same libm expression.
    {
        RatingInputs in = ahead();
        in.target_pos[0] = 60.0;
        in.target_pos[1] = 0.0;
        EXPECT_EQ(target_rating(in), 0.5 + (1.0 - (std::acos(0.0) / M_PI)));
    }
    // A forward that is not a unit vector: the dot over the distance leaves
    // [-1, 1] and is clamped (2 -> 1 -> acos 0; -2 -> -1 -> acos pi).
    {
        RatingInputs in = ahead();
        in.our_forward[1] = 2.0;
        EXPECT_EQ(target_rating(in), 1.5);
        in.our_forward[1] = -2.0;
        EXPECT_EQ(target_rating(in), 0.5);
    }
    // The distance is the TGPoint3 length of target - ours, x*x + y*y + z*z
    // left to right, then sqrt.
    {
        RatingInputs in = ahead();
        in.our_pos[0] = 1.0;
        in.our_pos[1] = 2.0;
        in.our_pos[2] = 3.0;
        in.target_pos[0] = 0.1;
        in.target_pos[1] = 70.3;
        in.target_pos[2] = -4.7;
        const double dx = 0.1 - 1.0, dy = 70.3 - 2.0, dz = -4.7 - 3.0;
        const double d = std::sqrt(dx * dx + dy * dy + dz * dz);
        double a = (0.0 * dx + 1.0 * dy + 0.0 * dz) / d;
        const double want = (30.0 / d) + (1.0 - (std::acos(a) / M_PI));
        EXPECT_EQ(target_rating(in), want);
    }
    // NaN position: `fDistance > 0` is False, so both stay 0.0.
    {
        RatingInputs in = ahead();
        in.target_pos[1] = std::nan("");
        EXPECT_EQ(target_rating(in), 0.0);
    }
}
