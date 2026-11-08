// AvoidObstacles' per-object test (ai_avoid.h) on hand-worked cases. Each
// expected answer is the SDK's AvoidObstacles.NeedToAvoid
// (AI/Preprocessors.py:1769-1842) worked by hand on the same inputs; the
// random differential against the real Python is
// tests/unit/test_native_avoid_scan.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <limits>

#include "dauntless/combat/ai_avoid.h"

using dauntless::combat::AvoidInputs;
using dauntless::combat::need_to_avoid;

namespace {

AvoidInputs at_rest(double ox, double oy, double oz) {
    AvoidInputs in{};
    in.obj_pos[0] = ox;
    in.obj_pos[1] = oy;
    in.obj_pos[2] = oz;
    in.obj_radius = 1.0;
    in.is_physics = true;
    in.personal_space_radius = 2.5;
    in.prediction_time = 15.0;
    return in;
}

}  // namespace

TEST(AiAvoid, MatchesTheSdkFormulaOnKnownCases) {
    // Inside personal space: |d| = 3 < 2.5 + 1.
    {
        AvoidInputs in = at_rest(3.0, 0.0, 0.0);
        EXPECT_TRUE(need_to_avoid(in));
    }
    // Head-on: closing at 2 GU/s from 30 GU, radius sum 3.5:
    // a = 4, b = -120, c = 887.75, sqrt(196) = 14, t2 = 13.25 < 15.
    {
        AvoidInputs in = at_rest(0.0, 30.0, 0.0);
        in.ship_vel[1] = 1.0;
        in.obj_vel[1] = -1.0;
        EXPECT_TRUE(need_to_avoid(in));
        // From 50 GU: t2 = 23.25, past the prediction time.
        in.obj_pos[1] = 50.0;
        EXPECT_FALSE(need_to_avoid(in));
    }
    // Parallel: the same velocity, so a == 0 and nothing is converging.
    {
        AvoidInputs in = at_rest(10.0, 0.0, 0.0);
        in.ship_vel[0] = 1.0;
        in.ship_vel[1] = 2.0;
        in.ship_vel[2] = 3.0;
        in.obj_vel[0] = 1.0;
        in.obj_vel[1] = 2.0;
        in.obj_vel[2] = 3.0;
        EXPECT_FALSE(need_to_avoid(in));
    }
    // a == 0 because the object is not a physics object: its velocity is
    // never read (PhysicsObjectClass_Cast is None, the SDK zeroes it), and
    // the ship is at rest. The same velocity on a physics object closes.
    {
        AvoidInputs in = at_rest(10.0, 0.0, 0.0);
        in.obj_vel[0] = -5.0;
        in.is_physics = false;
        EXPECT_FALSE(need_to_avoid(in));
        in.is_physics = true;
        EXPECT_TRUE(need_to_avoid(in));
    }
    // Negative discriminant: passing 10 GU wide of a radius sum of 3.5.
    {
        AvoidInputs in = at_rest(20.0, 10.0, 0.0);
        in.ship_vel[0] = 1.0;
        in.obj_vel[0] = 0.0;
        EXPECT_FALSE(need_to_avoid(in));
    }
    // Both roots negative (receding): t1 = -16.5, t2 = -23.5, so the hit
    // time is t1 and it is in the past.
    {
        AvoidInputs in = at_rest(20.0, 0.0, 0.0);
        in.ship_vel[0] = -1.0;
        EXPECT_FALSE(need_to_avoid(in));
    }
    // t2 < 0 <= t1: exactly on the boundary (|d| == 5 is not < 5) and
    // receding. c == 0, t1 = 0, t2 = -10, so the hit time is t1 = 0, which
    // is >= 0 and < 15: avoid.
    {
        AvoidInputs in = at_rest(5.0, 0.0, 0.0);
        in.personal_space_radius = 4.0;
        in.ship_vel[0] = -1.0;
        EXPECT_TRUE(need_to_avoid(in));
    }
    // t2 >= 0 chosen: approaching the same boundary, t2 = 0.
    {
        AvoidInputs in = at_rest(5.0, 0.0, 0.0);
        in.personal_space_radius = 4.0;
        in.ship_vel[0] = 1.0;
        EXPECT_TRUE(need_to_avoid(in));
    }
    // Hit time exactly 15: radius sum 5, from 20 GU at 1 GU/s,
    // c = 375, sqrt(100) = 10, t2 = 15. `fHitTime < fPredictionTime` is
    // strict, so not a hazard; one more half second of prediction makes it
    // one.
    {
        AvoidInputs in = at_rest(20.0, 0.0, 0.0);
        in.personal_space_radius = 4.0;
        in.ship_vel[0] = 1.0;
        EXPECT_FALSE(need_to_avoid(in));
        in.prediction_time = 15.5;
        EXPECT_TRUE(need_to_avoid(in));
    }
    // NaN velocity: `a > 0` is False for NaN, so not a hazard.
    {
        AvoidInputs in = at_rest(20.0, 0.0, 0.0);
        in.ship_vel[0] = std::numeric_limits<double>::quiet_NaN();
        EXPECT_FALSE(need_to_avoid(in));
    }
    // NaN position: `fDist < ...` is False, then a > 0 and the discriminant
    // is NaN, so `fSqrtPart >= 0` is False and the hit time stays -1.
    {
        AvoidInputs in = at_rest(std::numeric_limits<double>::quiet_NaN(), 0.0, 0.0);
        in.ship_vel[0] = 1.0;
        EXPECT_FALSE(need_to_avoid(in));
    }
}
