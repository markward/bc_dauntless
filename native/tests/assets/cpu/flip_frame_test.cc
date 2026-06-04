// native/tests/assets/cpu/flip_frame_test.cc
//
// Tests for assets::compute_flip_frame_index — given a NiFlipController's
// timing parameters and a wall time, returns the active frame index for
// the looping animation. Pure function, no GL.
#include <gtest/gtest.h>

#include <assets/flip_frame.h>

using assets::compute_flip_frame_index;

namespace {
// EBridge.nif's actual values (LCARS Schematic Right animated material).
constexpr double kStart = 0.0;
constexpr double kFreq  = 1.0;
constexpr double kPhase = 0.0;
constexpr double kDelta = 1.0 / 6.0;  // 0.1667
constexpr int    kN     = 8;
}  // namespace

TEST(FlipFrame, StartTimeReturnsFrameZero) {
    EXPECT_EQ(compute_flip_frame_index(kStart, kStart, kFreq, kPhase, kDelta, kN), 0);
}

TEST(FlipFrame, AdvancesOneFramePerDelta) {
    EXPECT_EQ(compute_flip_frame_index(kDelta * 1.0, kStart, kFreq, kPhase, kDelta, kN), 1);
    EXPECT_EQ(compute_flip_frame_index(kDelta * 2.0, kStart, kFreq, kPhase, kDelta, kN), 2);
    EXPECT_EQ(compute_flip_frame_index(kDelta * 7.0, kStart, kFreq, kPhase, kDelta, kN), 7);
}

TEST(FlipFrame, WrapsAtFullCycle) {
    // t = num_sources * delta → wraps back to frame 0.
    EXPECT_EQ(compute_flip_frame_index(kDelta * kN, kStart, kFreq, kPhase, kDelta, kN), 0);
    EXPECT_EQ(compute_flip_frame_index(kDelta * (kN + 1), kStart, kFreq, kPhase, kDelta, kN), 1);
}

TEST(FlipFrame, MidFrameRoundsDown) {
    // 0.5 of a delta past frame 3 still reads as frame 3.
    EXPECT_EQ(compute_flip_frame_index(kDelta * 3.5, kStart, kFreq, kPhase, kDelta, kN), 3);
}

TEST(FlipFrame, FrequencyDoublesAdvanceRate) {
    // At freq=2, t=delta/2 should already be frame 1.
    EXPECT_EQ(compute_flip_frame_index(kDelta * 0.5, kStart, /*freq=*/2.0, kPhase, kDelta, kN), 1);
}

TEST(FlipFrame, NegativeLocalTimeWrapsForward) {
    // wall_time < start_time → negative local_t; should still resolve to
    // a non-negative frame within [0, num_sources).
    int f = compute_flip_frame_index(-0.01, kStart, kFreq, kPhase, kDelta, kN);
    EXPECT_GE(f, 0);
    EXPECT_LT(f, kN);
}

TEST(FlipFrame, PhaseShiftsStartingFrame) {
    // phase=delta should make t=start_time read as frame 1, not 0.
    EXPECT_EQ(compute_flip_frame_index(kStart, kStart, kFreq, /*phase=*/kDelta, kDelta, kN), 1);
}

TEST(FlipFrame, ZeroDeltaIsSafe) {
    // Defensive: divide-by-zero must not crash; return frame 0.
    EXPECT_EQ(compute_flip_frame_index(1.0, kStart, kFreq, kPhase, /*delta=*/0.0, kN), 0);
}

TEST(FlipFrame, ZeroSourcesIsSafe) {
    EXPECT_EQ(compute_flip_frame_index(1.0, kStart, kFreq, kPhase, kDelta, /*N=*/0), 0);
}
