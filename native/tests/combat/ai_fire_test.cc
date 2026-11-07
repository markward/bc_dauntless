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

// ── Task 5: ChooseTargetSubsystem's and ChooseTorpType's arithmetic ─────────
// Expected values: the SDK statements (AI/Preprocessors.py:533-640, 959-1045)
// run in Python on the same inputs, printed as float.hex().

TEST(AiFire, SubsystemRatingMatchesTheSdk) {
    // A critical weapon system above its disabled line, DisableBeforeDestroy.
    cb::SubsystemRatingInputs a{1.0, 4000.0, 0.25, 2345.6789, 0.0, 1.0, 5.0, 1.0};
    EXPECT_EQ(cb::fire_subsystem_rating(a), 0x1.44f032cdb2a5ep+3);
    // The hull, disabled (condition under the line: no damage to disable).
    cb::SubsystemRatingInputs b{0.0, 1200.0, 0.5, 300.125, 1.0, 1.0, -200.0, 0.0};
    EXPECT_EQ(cb::fire_subsystem_rating(b), -0x1.8e4cd4fdf3b64p+7);
    // Partly hittable impulse engines, disabled, DisableBeforeDestroy.
    cb::SubsystemRatingInputs c{0.0, 900.0, 0.3, 0.1, 1.0, 0.7, 3.0, 1.0};
    EXPECT_EQ(cb::fire_subsystem_rating(c), 0x1.665fd8adab9f8p-1);
    // A NaN condition: `fCondition > fDisabledCondition` is false, the sum NaN.
    cb::SubsystemRatingInputs d = a;
    d.condition = std::numeric_limits<double>::quiet_NaN();
    EXPECT_TRUE(std::isnan(cb::fire_subsystem_rating(d)));
}

TEST(AiFire, SystemRatingTableIsTheSdkOrder) {
    // CT_WEAPON_SYSTEM, CT_WEAPON, CT_SHIELD_SUBSYSTEM, CT_CLOAKING_SUBSYSTEM,
    // CT_IMPULSE_ENGINE_SUBSYSTEM, CT_HULL_SUBSYSTEM; no match: 0.0.
    ASSERT_EQ(cb::kFireSystemRatingRows, 6);
    const double want[] = {5.0, 5.0, 5.0, 4.0, 3.0, -200.0};
    for (int i = 0; i < 6; ++i) EXPECT_EQ(cb::fire_system_rating(i), want[i]) << i;
    EXPECT_EQ(cb::fire_system_rating(-1), 0.0);
}

TEST(AiFire, PickRatingMatchesTheSdk) {
    EXPECT_EQ(cb::fire_pick_rating(1.0, 0.7312345, 0.0), 0x1.133743632c1f4p-2);
    EXPECT_EQ(cb::fire_pick_rating(0.0, 0.1, 1.0), -0x1.199999999999ap+0);
    EXPECT_EQ(cb::fire_pick_rating(0.0, 1.0, 0.0), -0x1.0000000000000p+0);
    // `0.0 + 0.0 * 1.0 + 0.0 * -1.0 + 0.0 * -1.0` keeps the SDK's signed zero.
    EXPECT_FALSE(std::signbit(cb::fire_pick_rating(0.0, 0.0, 0.0)));
}

TEST(AiFire, GreaterIsStrict) {
    EXPECT_FALSE(cb::fire_greater(1.5, 1.5));
    EXPECT_TRUE(cb::fire_greater(std::nextafter(1.5, 2.0), 1.5));
    EXPECT_TRUE(cb::fire_greater(-1.0e19, -1.0e20));
    EXPECT_FALSE(cb::fire_greater(std::numeric_limits<double>::quiet_NaN(), -1.0e20));
    EXPECT_FALSE(cb::fire_greater(-1.0e20, std::numeric_limits<double>::quiet_NaN()));
}

TEST(AiFire, TorpIdealsMatchTheSdk) {
    // Guided and moving: (launch, cost, damage, lifetime, turn).
    cb::TorpIdeals g = cb::fire_torp_ideals(19.0, 20.0, 500.0, 6.0, 0.15);
    EXPECT_EQ(g.dist_min, 0.0);
    EXPECT_EQ(g.dist_max, 0x1.c800000000000p+6);
    EXPECT_EQ(g.speed_min, 0.0);
    EXPECT_EQ(g.speed_max, 0x1.399999999999ap+4);
    EXPECT_EQ(g.rating, 0x1.e000000000000p+8);
    // Unguided and still: no ideal distance or speed at all.
    cb::TorpIdeals s = cb::fire_torp_ideals(0.0, 40.0, 1200.5, 0.0, 0.3);
    EXPECT_EQ(s.dist_max, 0.0);
    EXPECT_EQ(s.speed_max, 0.0);
    EXPECT_EQ(s.rating, 0x1.2220000000000p+10);
    // Unguided but moving: a speed ideal only.
    cb::TorpIdeals m = cb::fire_torp_ideals(12.5, 30.0, 875.0, 0.0, 0.25);
    EXPECT_EQ(m.dist_max, 0.0);
    EXPECT_EQ(m.speed_max, 0x1.b000000000000p+3);
    EXPECT_EQ(m.rating, 0x1.a680000000000p+9);
    // NaN lifetime: neither `> 0` holds, so only the launch speed decides.
    cb::TorpIdeals n =
        cb::fire_torp_ideals(0.0, 1.0, 2.0, std::numeric_limits<double>::quiet_NaN(), 1.0);
    EXPECT_EQ(n.dist_max, 0.0);
    EXPECT_EQ(n.speed_max, 0.0);
}

TEST(AiFire, TorpScoreAndBandsMatchTheSdk) {
    EXPECT_EQ(cb::fire_torp_score(480.0, 0.3333333333333333, 0.6666666666666667, 0.123, 0.0),
              0x1.66147ae147ae1p+7);
    EXPECT_EQ(cb::fire_torp_score(845.0, 0.0, 0.41, 0.77, 0.23), 0x1.d1ce666666666p+9);
    // The last FuzzyLogic threshold: `fMax * 1.5`, or `(fMax - fMin) * 1.5`
    // when fMin > 0.
    EXPECT_EQ(cb::fire_torp_far(0.0, 114.0), 0x1.5600000000000p+7);
    EXPECT_EQ(cb::fire_torp_far(-0.0, 114.0), 0x1.5600000000000p+7);
    EXPECT_EQ(cb::fire_torp_far(3.3, 114.0), 0x1.4c1999999999ap+7);
}
