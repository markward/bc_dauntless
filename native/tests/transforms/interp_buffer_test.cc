#include <gtest/gtest.h>
#include <cmath>

#include "dauntless/interp_buffer.h"

using dauntless::HandoverBlend;
using dauntless::InterpBuffer;
using dauntless::lerp_pose;
using dauntless::Pose;

namespace {

Pose at(double x, double y, double z) {
    Pose p{};
    p.pos[0] = x;
    p.pos[1] = y;
    p.pos[2] = z;
    p.rot[0] = p.rot[4] = p.rot[8] = 1.0;
    return p;
}

Pose z_rotation(double angle) {
    Pose p = at(0.0, 0.0, 0.0);
    const double c = std::cos(angle), s = std::sin(angle);
    p.rot[0] = c;  p.rot[1] = -s;
    p.rot[3] = s;  p.rot[4] = c;
    return p;
}

Pose zero_rotation() {
    Pose p{};
    return p;
}

double det(const Pose& p) {
    const double* a = p.rot;
    return a[0] * (a[4] * a[8] - a[5] * a[7])
         - a[1] * (a[3] * a[8] - a[5] * a[6])
         + a[2] * (a[3] * a[7] - a[4] * a[6]);
}

// Columns unit length and det = +1 (right-handed), as test_interpolate.py.
void expect_orthonormal(const Pose& p, double tol) {
    for (int c = 0; c < 3; ++c) {
        const double x = p.rot[c], y = p.rot[3 + c], z = p.rot[6 + c];
        EXPECT_NEAR(std::sqrt(x * x + y * y + z * z), 1.0, tol) << "col " << c;
    }
    EXPECT_NEAR(det(p), 1.0, tol);
}

}  // namespace

TEST(InterpBuffer, NewKeySeedsPrevEqualCur) {
    InterpBuffer b;
    EXPECT_FALSE(b.has(7));
    b.capture(7, at(4.0, 0.0, 0.0));
    EXPECT_TRUE(b.has(7));
    Pose out{};
    ASSERT_TRUE(b.sample(7, 0.0, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 4.0);
}

TEST(InterpBuffer, RollThenCaptureBlendsAcrossTheLastTick) {
    InterpBuffer b;
    b.capture(1, at(0.0, 0.0, 0.0));
    b.roll();
    b.capture(1, at(8.0, -4.0, 2.0));
    Pose out{};
    ASSERT_TRUE(b.sample(1, 0.25, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 2.0);
    EXPECT_DOUBLE_EQ(out.pos[1], -1.0);
    EXPECT_DOUBLE_EQ(out.pos[2], 0.5);
}

TEST(InterpBuffer, CaptureWithoutRollMovesOnlyCur) {
    InterpBuffer b;
    b.capture(1, at(0.0, 0.0, 0.0));
    b.roll();
    b.capture(1, at(4.0, 0.0, 0.0));
    // A per-frame writer moved it again with no tick: prev stays put.
    b.capture(1, at(8.0, 0.0, 0.0));
    Pose out{};
    ASSERT_TRUE(b.sample(1, 0.0, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 0.0);
    ASSERT_TRUE(b.sample(1, 1.0, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 8.0);
}

TEST(InterpBuffer, SetPreviousIgnoresUntracked) {
    InterpBuffer b;
    b.set_previous(3, at(1.0, 0.0, 0.0));
    EXPECT_FALSE(b.has(3));
    b.capture(3, at(10.0, 0.0, 0.0));
    b.set_previous(3, at(6.0, 0.0, 0.0));
    Pose out{};
    ASSERT_TRUE(b.sample(3, 0.5, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 8.0);
}

TEST(InterpBuffer, SnapSetsBoth) {
    InterpBuffer b;
    b.capture(2, at(0.0, 0.0, 0.0));
    b.roll();
    b.capture(2, at(5.0, 0.0, 0.0));
    b.snap(2, at(100.0, 0.0, 0.0));
    Pose out{};
    ASSERT_TRUE(b.sample(2, 0.0, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 100.0);
    ASSERT_TRUE(b.sample(2, 1.0, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 100.0);
}

TEST(InterpBuffer, EraseAndClear) {
    InterpBuffer b;
    b.capture(1, at(1.0, 0.0, 0.0));
    b.capture(2, at(2.0, 0.0, 0.0));
    b.erase(1);
    EXPECT_FALSE(b.has(1));
    EXPECT_TRUE(b.has(2));
    b.clear();
    EXPECT_FALSE(b.has(2));
    // A key captured after clear seeds afresh: no blend from the old pose.
    b.capture(2, at(9.0, 0.0, 0.0));
    Pose out{};
    ASSERT_TRUE(b.sample(2, 0.0, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 9.0);
}

TEST(InterpBuffer, SampleUnknownIsFalse) {
    InterpBuffer b;
    Pose out = at(3.0, 0.0, 0.0);
    EXPECT_FALSE(b.sample(42, 0.5, out));
    EXPECT_DOUBLE_EQ(out.pos[0], 3.0);
}

TEST(LerpPose, OrthonormalRightHanded) {
    const Pose a = z_rotation(0.3);
    const Pose b = z_rotation(1.1);
    const Pose out = lerp_pose(a, b, 0.4);
    expect_orthonormal(out, 1e-12);
}

TEST(LerpPose, ZeroMatrixDoesNotCrash) {
    const Pose z = zero_rotation();
    expect_orthonormal(lerp_pose(z, z, 0.0), 1e-12);
    expect_orthonormal(lerp_pose(z, z, 0.5), 1e-12);
}

TEST(LerpPose, DegenerateForwardFallsBackToEndpoint) {
    const Pose z = zero_rotation();
    const Pose ident = at(0.0, 0.0, 0.0);
    const Pose out = lerp_pose(z, ident, 0.0);
    expect_orthonormal(out, 1e-12);
    // Forward and up come from the cur endpoint (identity).
    EXPECT_DOUBLE_EQ(out.rot[4], 1.0);
    EXPECT_DOUBLE_EQ(out.rot[8], 1.0);
}

TEST(LerpPose, ZeroUpColumnOnly) {
    Pose m = at(0.0, 0.0, 0.0);
    m.rot[2] = m.rot[5] = m.rot[8] = 0.0;
    const Pose out = lerp_pose(m, m, 0.0);
    expect_orthonormal(out, 1e-12);
}

TEST(HandoverBlend, InactiveReturnsTruth) {
    HandoverBlend h;
    EXPECT_FALSE(h.active());
    const Pose out = h.blend(at(4.0, 5.0, 6.0));
    EXPECT_DOUBLE_EQ(out.pos[0], 4.0);
    EXPECT_DOUBLE_EQ(out.pos[2], 6.0);
}

TEST(HandoverBlend, StartsAtTheFrozenPoseAndEndsAtTruth) {
    HandoverBlend h;
    h.begin(at(10.0, 20.0, 30.0));
    EXPECT_TRUE(h.active());
    Pose out = h.blend(at(99.0, 99.0, 99.0));
    EXPECT_DOUBLE_EQ(out.pos[0], 10.0);
    h.advance(dauntless::kHandoverSeconds);
    EXPECT_FALSE(h.active());
    out = h.blend(at(99.0, 99.0, 99.0));
    EXPECT_DOUBLE_EQ(out.pos[0], 99.0);
}

TEST(HandoverBlend, CancelDropsTheFrozenPose) {
    HandoverBlend h;
    h.advance(0.1);  // no frozen pose: nothing to advance
    h.begin(at(0.0, 0.0, 0.0));
    EXPECT_TRUE(h.active());
    h.cancel();
    EXPECT_FALSE(h.active());
}
