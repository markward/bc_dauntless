// native/tests/renderer/frame_timer_test.cc
//
// The GPU-timer choice and the GL_TIME_ELAPSED scope rule, without a GL
// context. The GL behaviour (spans actually measured, no timestamp query ever
// issued on a 0-bit driver, no stall) is covered by
// tests/host/test_frame_profiler_gl.py.
#include "renderer/frame_timer.h"

#include <gtest/gtest.h>

using renderer::FrameTimer;
using GpuTimer = renderer::FrameTimer::GpuTimer;

TEST(FrameTimerGpuTimer, TimestampWhenTheDriverDeclaresATimestampCounter) {
    EXPECT_EQ(FrameTimer::choose_gpu_timer(64, 32), GpuTimer::Timestamp);
    EXPECT_EQ(FrameTimer::choose_gpu_timer(36, 0), GpuTimer::Timestamp);
}

TEST(FrameTimerGpuTimer, ElapsedWhenTheTimestampCounterHasZeroBits) {
    // Apple's GL-over-Metal (measured 2026-10-08): GL_TIMESTAMP 0 bits,
    // GL_TIME_ELAPSED 32 bits.
    EXPECT_EQ(FrameTimer::choose_gpu_timer(0, 32), GpuTimer::Elapsed);
}

TEST(FrameTimerGpuTimer, NoneWhenNeitherCounterHasBits) {
    EXPECT_EQ(FrameTimer::choose_gpu_timer(0, 0), GpuTimer::None);
    // glGetQueryiv leaves its output untouched on error; the caller seeds -1.
    EXPECT_EQ(FrameTimer::choose_gpu_timer(-1, -1), GpuTimer::None);
}

TEST(FrameTimerGpuTimer, ElapsedTimesOnlyTheChildrenOfTheFrameScope) {
    // GL_TIME_ELAPSED cannot nest: one query active per target. The frame
    // scope (depth 0) encloses everything, so the queries go one level down,
    // where scopes are strictly sequential.
    EXPECT_FALSE(FrameTimer::elapsed_times_depth(0));
    EXPECT_TRUE(FrameTimer::elapsed_times_depth(1));
    EXPECT_FALSE(FrameTimer::elapsed_times_depth(2));
    EXPECT_FALSE(FrameTimer::elapsed_times_depth(5));
}

TEST(FrameTimerGpuTimer, ADisabledTimerHasNoGpuTimer) {
    FrameTimer t;
    EXPECT_EQ(t.gpu_timer(), GpuTimer::None);
}
