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

// GPU timing is opt-in. With it on, the timer queries make the CPU wait for
// the GPU every frame on Apple's GL, adding about the GPU frame time
// (docs/engine/perf-register.md, M-6 / SIG-019), so a default capture must
// not issue them.
TEST(FrameTimerGpuTimer, GpuTimingIsOffByDefault) {
    FrameTimer t;
    EXPECT_FALSE(t.gpu_requested());
}

TEST(FrameTimerGpuTimer, NotRequestedMeansNoGpuTimerWhateverTheDriverOffers) {
    EXPECT_EQ(FrameTimer::select_gpu_timer(false, 64, 32), GpuTimer::None);
    EXPECT_EQ(FrameTimer::select_gpu_timer(false, 0, 32), GpuTimer::None);
}

TEST(FrameTimerGpuTimer, RequestedFollowsTheDriversCounterBits) {
    EXPECT_EQ(FrameTimer::select_gpu_timer(true, 64, 32), GpuTimer::Timestamp);
    EXPECT_EQ(FrameTimer::select_gpu_timer(true, 0, 32), GpuTimer::Elapsed);
    EXPECT_EQ(FrameTimer::select_gpu_timer(true, 0, 0), GpuTimer::None);
}

TEST(FrameTimerGpuTimer, RequestingGpuTimingIsRemembered) {
    FrameTimer t;
    t.set_gpu_requested(true);
    EXPECT_TRUE(t.gpu_requested());
    t.set_gpu_requested(false);
    EXPECT_FALSE(t.gpu_requested());
}

// M-1 (docs/engine/perf-register.md): GL_TIME_ELAPSED cannot nest, so on
// Apple's GL only the top-level passes get a GPU figure. A GPU FOCUS names
// nested scopes to time anyway: while one is open, its depth-1 ancestor's
// query is suspended and resumed after, so the ancestor still totals every
// segment, the focus scope included.
TEST(FrameTimerGpuFocus, NoFocusByDefault) {
    FrameTimer t;
    EXPECT_TRUE(t.gpu_focus().empty());
    EXPECT_FALSE(t.is_gpu_focus("space.opaque"));
}

TEST(FrameTimerGpuFocus, FocusNamesAreRememberedAndMatchedExactly) {
    FrameTimer t;
    t.set_gpu_focus({"space.opaque", "rock.puffs.draw"});
    EXPECT_EQ(t.gpu_focus().size(), 2u);
    EXPECT_TRUE(t.is_gpu_focus("space.opaque"));
    EXPECT_TRUE(t.is_gpu_focus("rock.puffs.draw"));
    EXPECT_FALSE(t.is_gpu_focus("space"));
    EXPECT_FALSE(t.is_gpu_focus("space.opaque.x"));
    t.set_gpu_focus({});
    EXPECT_FALSE(t.is_gpu_focus("space.opaque"));
}

TEST(FrameTimerGpuFocus, OnlyANestedFocusScopeWithNoFocusOpenSplitsTheQuery) {
    // depth 1 is already timed; depth 0 is the frame; a focus scope inside
    // another open focus scope stays untimed (its time is in the outer one).
    EXPECT_FALSE(FrameTimer::focus_splits(0, true, false));
    EXPECT_FALSE(FrameTimer::focus_splits(1, true, false));
    EXPECT_TRUE(FrameTimer::focus_splits(2, true, false));
    EXPECT_TRUE(FrameTimer::focus_splits(4, true, false));
    EXPECT_FALSE(FrameTimer::focus_splits(3, true, true));
    EXPECT_FALSE(FrameTimer::focus_splits(3, false, false));
}
