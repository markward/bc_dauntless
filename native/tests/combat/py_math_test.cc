// Hand-computed pins for the combat library's Python-exact math. The
// exhaustive native-vs-CPython comparison is
// tests/unit/test_native_combat_math.py; these cases fail fast in C++ alone.
#include <gtest/gtest.h>

#include <cmath>
#include <limits>
#include <stdexcept>

#include "dauntless/combat/nebula_density.h"
#include "dauntless/combat/profile_eval.h"
#include "dauntless/combat/py_math.h"

using namespace dauntless::combat;

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
constexpr double kInf = std::numeric_limits<double>::infinity();

// CPython's `x ** 0.5` is libm pow, which differs from sqrt by an ulp here;
// a helper that let the compiler fold pow(x, 0.5) to sqrt would fail.
TEST(PyMath, PyPowHalfIsLibmPowNotSqrt) {
    const double x = 0x1.73a804986b1acp+0;
    EXPECT_EQ(py_pow(x, 0.5), 0x1.3474490c86324p+0);  // Python: x ** 0.5
    EXPECT_NE(py_pow(x, 0.5), std::sqrt(x));          // sqrt: ...325p+0
    EXPECT_EQ(py_pow(0.0, 0.5), 0.0);
}

TEST(PyMath, Dist3OfThreeFourZeroIsFive) {
    const double a[3] = {3.0, 4.0, 0.0};
    const double b[3] = {0.0, 0.0, 0.0};
    EXPECT_EQ(dist3(a, b), 5.0);
}

TEST(PyMath, Dist3EdgesFollowVectorNorm) {
    const double o[3] = {0.0, 0.0, 0.0};
    const double neg0[3] = {-0.0, -0.0, -0.0};
    EXPECT_EQ(dist3(o, neg0), 0.0);
    EXPECT_FALSE(std::signbit(dist3(o, neg0)));
    // An infinity wins over a NaN (vector_norm tests max before found_nan).
    const double inf_nan[3] = {kInf, kNaN, 0.0};
    EXPECT_EQ(dist3(inf_nan, o), kInf);
    const double nan_pt[3] = {kNaN, 0.0, 0.0};
    EXPECT_TRUE(std::isnan(dist3(nan_pt, o)));
    // Subnormal differences take the divide-by-max branch.
    const double tiny[3] = {5e-324, 5e-324, 0.0};
    EXPECT_EQ(dist3(tiny, o), 5e-324);
}

TEST(PyMath, MinMaxFollowPythonArgumentOrder) {
    EXPECT_TRUE(std::isnan(py_min(kNaN, 1.0)));
    EXPECT_EQ(py_min(1.0, kNaN), 1.0);
    EXPECT_TRUE(std::isnan(py_max(kNaN, 1.0)));
    EXPECT_EQ(py_max(1.0, kNaN), 1.0);
    EXPECT_EQ(py_min(2.0, 1.0), 1.0);
    EXPECT_EQ(py_max(1.0, 2.0), 2.0);
    // Ties keep the first argument: max(0.0, -0.0) is 0.0, min(-0.0, 0.0) is -0.0.
    EXPECT_FALSE(std::signbit(py_max(0.0, -0.0)));
    EXPECT_TRUE(std::signbit(py_min(-0.0, 0.0)));
}

TEST(PyMath, SaturatePassesNaN) {
    EXPECT_EQ(saturate(-0.5), 0.0);
    EXPECT_EQ(saturate(1.5), 1.0);
    EXPECT_EQ(saturate(0.25), 0.25);
    EXPECT_TRUE(std::isnan(saturate(kNaN)));
}

TEST(PyMath, OcclusionPrimitivesAreStrict) {
    // A segment along x, a sphere of radius 3 centred 3 off it: touching only.
    EXPECT_FALSE(segment_hits(0, 0, 0, 10, 0, 0, 5, 3, 0, 3));
    EXPECT_TRUE(segment_hits(0, 0, 0, 10, 0, 0, 5, 2.9, 0, 3));
    // A degenerate segment is its start point.
    EXPECT_TRUE(segment_hits(1, 0, 0, 1, 0, 0, 0, 0, 0, 1.5));
    EXPECT_FALSE(contains(3, 0, 0, 0, 0, 0, 3));
    EXPECT_TRUE(contains(2.5, 0, 0, 0, 0, 0, 3));
}

// Goldens pinned by tests/unit/test_nebula_density.py (there within 1e-9; the
// values are CPython's own repr, so here exactly).
TEST(NebulaDensity, MatchesPinnedPythonGoldens) {
    EXPECT_EQ(fbm(1.5, 2.5, 3.5), 0.43832942533588964);
    const Sphere s[1] = {{0.0, 0.0, 0.0, 100.0}};
    const double seed[3] = {0.0 * 0.013 + 11.7, 0.0 * 0.013 + 23.1,
                            0.0 * 0.013 + 47.3};
    EXPECT_EQ(density(20.0, 10.0, 5.0, s, 1, seed, 0.05, 1.6, 0.4, 0.0),
              0.20645526505610945);
    EXPECT_EQ(density(500.0, 0.0, 0.0, s, 1, seed, 0.05, 1.6, 0.4, 0.0), 0.0);
}

// Python's math.floor raises (ValueError on NaN, OverflowError on inf) when a
// non-finite value reaches fbm, i.e. a NaN/inf drift_t, freq, seed or sample
// coordinate at a point inside a sphere (bound > 0). Native throws
// std::invalid_argument there (ruling R5) so the caller falls back to the
// Python, which raises as it always did -- never a silent NaN.
TEST(NebulaDensity, NonFiniteNoiseInputThrows) {
    const Sphere s[1] = {{0.0, 0.0, 0.0, 100.0}};
    const double seed[3] = {11.7, 23.1, 47.3};
    EXPECT_THROW(density(20.0, 10.0, 5.0, s, 1, seed, 0.05, 1.6, 0.4, kNaN),
                 std::invalid_argument);
    EXPECT_THROW(density(20.0, 10.0, 5.0, s, 1, seed, 0.05, 1.6, 0.4, kInf),
                 std::invalid_argument);
    EXPECT_THROW(density(20.0, 10.0, 5.0, s, 1, seed, kInf, 1.6, 0.4, 0.0),
                 std::invalid_argument);
    const double nan_seed[3] = {11.7, kNaN, 47.3};
    EXPECT_THROW(density(20.0, 10.0, 5.0, s, 1, nan_seed, 0.05, 1.6, 0.4, 0.0),
                 std::invalid_argument);
    EXPECT_THROW(fbm(kNaN, 0.0, 0.0), std::invalid_argument);
    // Outside every sphere the bound is 0 and fbm is never reached.
    EXPECT_EQ(density(500.0, 0.0, 0.0, s, 1, seed, 0.05, 1.6, 0.4, kNaN), 0.0);
    // A NaN position has falloff 0 (Python returns 0.0, no raise).
    EXPECT_EQ(density(kNaN, 0.0, 0.0, s, 1, seed, 0.05, 1.6, 0.4, 0.0), 0.0);
    // Finite inputs never throw (a NaN gain/floor is applied AFTER fbm).
    EXPECT_NO_THROW(density(20.0, 10.0, 5.0, s, 1, seed, 0.05, 1.6, 0.4, 1e6));
    EXPECT_TRUE(std::isnan(
        density(20.0, 10.0, 5.0, s, 1, seed, 0.05, kNaN, 0.4, 0.0)));
}

TEST(ProfileEval, BreakpointsLerpAndNaN) {
    const ProfileRow rows[3] = {{0.0, 1.0}, {100.0, 0.2}, {200.0, 0.0}};
    EXPECT_EQ(evaluate_sensors(rows, 3, -5.0), 1.0);
    // An exact breakpoint is the stored value, not 1.0 + (0.2 - 1.0) * 1.0.
    EXPECT_EQ(evaluate_sensors(rows, 3, 100.0), 0.2);
    EXPECT_EQ(evaluate_sensors(rows, 3, 50.0), 1.0 + (0.2 - 1.0) * 0.5);
    EXPECT_EQ(evaluate_sensors(rows, 3, 1e9), 0.0);
    // NaN r falls through every compare to the last row.
    const ProfileRow up[2] = {{0.0, 0.0}, {10.0, 0.7}};
    EXPECT_EQ(evaluate_sensors(up, 2, kNaN), 0.7);
    EXPECT_EQ(evaluate_sensors(nullptr, 0, 5.0), 0.0);
}

}  // namespace
