// FireScript's arithmetic (ai_fire.h) on hand-worked cases. Each expected
// answer is the SDK's statement worked on the same inputs with the engine's
// own TGPoint3 / TGMatrix3 (engine/appc/math.py) and
// ShipClass.GetPredictedPosition (engine/appc/ships.py), printed as
// float.hex(); the seeded call-by-call comparison against the real Python is
// tests/unit/test_native_fire_script.py.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <limits>

#include "dauntless/combat/ai_fire.h"

namespace cb = dauntless::combat;

namespace {

cb::FireVec v(double x, double y, double z) { return cb::FireVec{x, y, z}; }

// The SDK's `((self.iLastUpdate + 3) % (len(self.lWeapons) + 2)) - 2`,
// Python's floor modulo.
long long py_cycle(long long last, long long n) {
    long long a = last + 3;
    long long b = n + 2;
    long long r = a % b;
    if (r < 0) r += b;
    return r - 2;
}

}  // namespace

TEST(AiFire, CycleFormula) {
    // No weapons: -2 -> -1 -> 0 -> -2 (the Update's own len 0 return never
    // reaches the cycle, but a callback can empty the list first).
    EXPECT_EQ(cb::fire_cycle(-2, 0), -1);
    EXPECT_EQ(cb::fire_cycle(-1, 0), -2);
    // One weapon: -2, -1, 0, -2, ...
    EXPECT_EQ(cb::fire_cycle(-2, 1), -1);
    EXPECT_EQ(cb::fire_cycle(-1, 1), 0);
    EXPECT_EQ(cb::fire_cycle(0, 1), -2);
    // Three weapons: -2, -1, 0, 1, 2, -2, ...
    EXPECT_EQ(cb::fire_cycle(-2, 3), -1);
    EXPECT_EQ(cb::fire_cycle(-1, 3), 0);
    EXPECT_EQ(cb::fire_cycle(0, 3), 1);
    EXPECT_EQ(cb::fire_cycle(1, 3), 2);
    EXPECT_EQ(cb::fire_cycle(2, 3), -2);
    // A counter past the list (a weapon removed by a callback) and one a
    // mission set below -2: Python's floor modulo, never C's truncation.
    EXPECT_EQ(cb::fire_cycle(7, 3), py_cycle(7, 3));
    EXPECT_EQ(cb::fire_cycle(-9, 3), py_cycle(-9, 3));
    EXPECT_EQ(cb::fire_cycle(-9, 3), 2);
    EXPECT_EQ(cb::fire_cycle(-5, 0), py_cycle(-5, 0));
    for (long long n = 0; n < 6; ++n)
        for (long long last = -12; last < 12; ++last)
            EXPECT_EQ(cb::fire_cycle(last, n), py_cycle(last, n)) << last << " " << n;
}

TEST(AiFire, TargetInRangeIsTheSqrLengthTest) {
    // vDiff = target - ship; vDiff.SqrLength() <= fMaxFiringRange ** 2
    EXPECT_TRUE(cb::fire_in_range(v(3.0, 4.0, 0.0), v(0.0, 0.0, 0.0), 5.0));
    EXPECT_FALSE(cb::fire_in_range(v(3.0, 4.0, 0.0), v(0.0, 0.0, 0.0), 4.999999));
    EXPECT_TRUE(cb::fire_in_range(v(1.0, 2.0, 3.0), v(1.0, 2.0, 3.0), 0.0));
    EXPECT_TRUE(cb::fire_in_range(v(1.0e10, 0.0, 0.0), v(0.0, 0.0, 0.0), 1.0e20));
    // NaN never compares <=.
    const double nan = std::numeric_limits<double>::quiet_NaN();
    EXPECT_FALSE(cb::fire_in_range(v(nan, 0.0, 0.0), v(0.0, 0.0, 0.0), 1.0e20));
    EXPECT_FALSE(cb::fire_in_range(v(0.0, 0.0, 0.0), v(0.0, 0.0, 0.0), nan));
    // The boundary: an exactly representable 25 against 5 * 5, and the next
    // range down.
    EXPECT_TRUE(cb::fire_sqr_within(25.0, 5.0));
    EXPECT_FALSE(cb::fire_sqr_within(25.0, std::nextafter(5.0, 0.0)));
    EXPECT_TRUE(cb::fire_in_range(v(3.0, 4.0, 0.0), v(0.0, 0.0, 0.0), 5.0));
    EXPECT_FALSE(cb::fire_in_range(v(3.0, 4.0, 0.0), v(0.0, 0.0, 0.0),
                                   std::nextafter(5.0, 0.0)));
}

TEST(AiFire, FireAtLeastIsGreaterOrEqual) {
    // `fDot >= self.fFireDotThreshold`
    EXPECT_TRUE(cb::fire_at_least(0.5, 0.5));
    EXPECT_FALSE(cb::fire_at_least(0.5, std::nextafter(0.5, 1.0)));
    EXPECT_TRUE(cb::fire_at_least(std::nextafter(0.5, 1.0), 0.5));
    EXPECT_FALSE(cb::fire_at_least(std::numeric_limits<double>::quiet_NaN(), 0.0));
    EXPECT_FALSE(cb::fire_at_least(0.0, std::numeric_limits<double>::quiet_NaN()));
}

namespace {

cb::FireMat target_rot() {
    // MakeRotation(1.1, unit(0.2, -0.7, 0.4))
    return cb::FireMat{{0x1.f0eb111842b35p-2, -0x1.147d728e42612p-1, -0x1.60164cbf04d6cp-1,
                        0x1.45edf069ec527p-2, 0x1.aee91652806a6p-1, -0x1.bec72a1434b50p-2,
                        0x1.a0f56e169e1b4p-1, -0x1.d4afd43f0aaa0p-8, 0x1.291ce18dd44d1p-1}};
}

cb::FireMat our_rot() {
    // MakeRotation(-2.2, unit(0.6, 0.1, -0.3))
    return cb::FireMat{{0x1.4f316325cb8e8p-1, -0x1.341103822dd6cp-3, -0x1.7b494f54975fap-1,
                        0x1.212f637ffd978p-1, -0x1.1ba1c1d5ebfeep-1, 0x1.3928dbb8ac84cp-1,
                        -0x1.01381889bf05ep-1, -0x1.a33e6d086595ap-1, -0x1.1c5f5581ea7b4p-2}};
}

cb::PredictInputs predict_case() {
    cb::PredictInputs in{};
    in.target_pos = v(12.25, -431.5, 77.125);
    in.our_pos = v(-3.5, 9.75, 1.0e-3);
    in.speed = 7.3;
    in.physics = true;
    in.velocity = v(0.3, -2.7, 1.1);
    in.acceleration = v(-0.05, 0.2, 0.0125);
    in.subsystem = false;
    in.subsystem_pos = v(0.9, -2.25, 0.4);
    in.target_rot = target_rot();
    return in;
}

}  // namespace

TEST(AiFire, PredictTargetLocationMatchesTheSdk) {
    cb::PredictInputs in = predict_case();
    cb::FireVec out{};
    // A physics target, no subsystem: GetPredictedPosition at
    // fTime = |target - ours| / fSpeed.
    ASSERT_TRUE(cb::fire_predict_target_location(in, out));
    EXPECT_EQ(out.x, -0x1.fc9ed119fdcf5p+5);
    EXPECT_EQ(out.y, -0x1.b893fafc88724p+7);
    EXPECT_EQ(out.z, 0x1.5073d9bcde5d3p+7);

    // ... plus the subsystem's position rotated by the target's rotation.
    in.subsystem = true;
    ASSERT_TRUE(cb::fire_predict_target_location(in, out));
    EXPECT_EQ(out.x, -0x1.f19b4b089d099p+5);
    EXPECT_EQ(out.y, -0x1.bc24376496736p+7);
    EXPECT_EQ(out.z, 0x1.526a3277ccf5bp+7);

    // Not a physics object: the target's location as it is.
    in.physics = false;
    in.subsystem = false;
    ASSERT_TRUE(cb::fire_predict_target_location(in, out));
    EXPECT_EQ(out.x, 12.25);
    EXPECT_EQ(out.y, -431.5);
    EXPECT_EQ(out.z, 77.125);

    // fSpeed 0: the SDK's `fDistance / fSpeed` raises ZeroDivisionError.
    in.speed = 0.0;
    EXPECT_FALSE(cb::fire_predict_target_location(in, out));
    in.speed = -0.0;
    EXPECT_FALSE(cb::fire_predict_target_location(in, out));
}

TEST(AiFire, PrimitivesFollowTheEngineMath) {
    // TGPoint3.Unitize: the length before; unchanged at or below 1e-12.
    cb::FireVec a = v(3.0, 0.0, 4.0);
    EXPECT_EQ(cb::fire_unitize(a), 5.0);
    EXPECT_EQ(a.x, 0.6);
    EXPECT_EQ(a.z, 0.8);
    cb::FireVec tiny = v(1.0e-13, 0.0, 0.0);
    EXPECT_EQ(cb::fire_unitize(tiny), 1.0e-13);
    EXPECT_EQ(tiny.x, 1.0e-13);
    // GetPredictedPosition: p + v*t + a*(0.5*t*t), left to right.
    cb::FireVec p = cb::fire_predicted_position(v(1.0, 2.0, 3.0), v(0.5, -1.0, 2.0),
                                                v(4.0, 0.0, -2.0), 3.0);
    EXPECT_EQ(p.x, 1.0 + 0.5 * 3.0 + 4.0 * (0.5 * 3.0 * 3.0));
    EXPECT_EQ(p.y, 2.0 - 3.0);
    EXPECT_EQ(p.z, 3.0 + 6.0 - 2.0 * 4.5);
    // Transpose then MultMatrixLeft: R^T * v.
    cb::FireMat r = cb::fire_transpose(cb::FireMat{{0, -1, 0, 1, 0, 0, 0, 0, 1}});
    cb::FireVec w = v(1.0, 2.0, 3.0);
    cb::fire_mult_matrix_left(w, r);
    EXPECT_EQ(w.x, 2.0);
    EXPECT_EQ(w.y, -1.0);
    EXPECT_EQ(w.z, 3.0);
}

TEST(AiFire, CheckGoodShotDotThreshold) {
    cb::PredictInputs in = predict_case();
    in.subsystem = true;
    cb::FireVec predicted{};
    ASSERT_TRUE(cb::fire_predict_target_location(in, predicted));
    // The predicted point in our model space, unitized (the SDK's own value).
    cb::FireVec local = cb::fire_to_local_unit(predicted, in.our_pos, our_rot());
    EXPECT_EQ(local.x, -0x1.bc94c4b156dd6p-1);
    EXPECT_EQ(local.y, -0x1.2307ae3283045p-8);
    EXPECT_EQ(local.z, -0x1.fbe2376c11f55p-2);

    // fFireDotThreshold = cos(10 degrees), and cos(50) for InaccurateTorps.
    const double accurate = 0x1.f838b8c811c17p-1;
    const double inaccurate = 0x1.491b7523c161dp-1;
    const cb::FireMat ours = our_rot();
    // A direction exactly along the target: dot == |local|^2, a good shot.
    cb::FireVec along = local;
    cb::FireVec dirs1[] = {v(0.0, 1.0, 0.0), along};
    EXPECT_EQ(cb::fire_good_shot_direction(predicted, in.our_pos, ours, dirs1, 2, accurate), 1);
    // The threshold itself passes (>=); a hair above it does not.
    const double d = cb::fire_dot(local, along);
    EXPECT_EQ(cb::fire_good_shot_direction(predicted, in.our_pos, ours, dirs1, 2, d), 1);
    EXPECT_EQ(cb::fire_good_shot_direction(predicted, in.our_pos, ours, dirs1, 2,
                                           std::nextafter(d, 2.0)),
              -1);
    // The first direction that passes wins.
    cb::FireVec dirs2[] = {along, along};
    EXPECT_EQ(cb::fire_good_shot_direction(predicted, in.our_pos, ours, dirs2, 2, accurate), 0);
    // 30 degrees off the line: inside 50, outside 10.
    const double c = std::cos(30.0 * (3.141592653589793 / 180.0));
    const double s = std::sin(30.0 * (3.141592653589793 / 180.0));
    // A unit vector perpendicular to `local` (local has a large x, z).
    cb::FireVec perp = v(-local.z, 0.0, local.x);
    cb::fire_unitize(perp);
    cb::FireVec off = v(c * local.x + s * perp.x, c * local.y + s * perp.y,
                        c * local.z + s * perp.z);
    cb::FireVec dirs3[] = {off};
    EXPECT_EQ(cb::fire_good_shot_direction(predicted, in.our_pos, ours, dirs3, 1, accurate), -1);
    EXPECT_EQ(cb::fire_good_shot_direction(predicted, in.our_pos, ours, dirs3, 1, inaccurate), 0);
    // NaN never passes.
    EXPECT_EQ(cb::fire_good_shot_direction(predicted, in.our_pos, ours, dirs1, 2,
                                           std::numeric_limits<double>::quiet_NaN()),
              -1);
}
