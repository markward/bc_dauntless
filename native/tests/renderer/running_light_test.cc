// Running lights: blink curve + size clamp (running-lights spec §4.4).
#include <gtest/gtest.h>

#include <cmath>
#include <limits>

#include "renderer/running_light_math.h"

using renderer::running_light_blink_alpha;
using renderer::running_light_world_size;

TEST(RunningLightBlink, StaticIsAlwaysOn) {
    for (float t : {0.0f, 0.3f, 1.7f, 2.9f, 100.0f})
        EXPECT_FLOAT_EQ(running_light_blink_alpha(t, 3.0f, 0.0f, 0.0f), 1.0f);
}

TEST(RunningLightBlink, DegenerateTimingIsAlwaysOnNeverNaN) {
    const float cases[][2] = {{0.0f, 1.0f}, {-3.0f, 1.0f}, {3.0f, 3.0f}, {3.0f, 5.0f},
                              {std::numeric_limits<float>::quiet_NaN(), 1.0f}};
    for (const auto& c : cases) {
        const float a = running_light_blink_alpha(1.25f, c[0], c[1], 0.0f);
        EXPECT_FALSE(std::isnan(a));
        EXPECT_FLOAT_EQ(a, 1.0f);
    }
}

TEST(RunningLightBlink, OnForDurationOffForRestWithTenPercentRamps) {
    // Period 3, Duration 1: ramp up over [0, 0.1], hold to 0.9, ramp down to 1.0.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.0f,  3.0f, 1.0f, 0.0f), 0.0f);
    EXPECT_NEAR    (running_light_blink_alpha(0.05f, 3.0f, 1.0f, 0.0f), 0.5f, 1e-4f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.5f,  3.0f, 1.0f, 0.0f), 1.0f);
    EXPECT_NEAR    (running_light_blink_alpha(0.95f, 3.0f, 1.0f, 0.0f), 0.5f, 1e-4f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(1.5f,  3.0f, 1.0f, 0.0f), 0.0f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(2.99f, 3.0f, 1.0f, 0.0f), 0.0f);
    // Next period repeats.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(3.5f,  3.0f, 1.0f, 0.0f), 1.0f);
}

TEST(RunningLightBlink, PhaseShiftsTheWindow) {
    // Phase 1.0 s: game time 2.5 reads as 3.5 -> 0.5 into the next period: on.
    EXPECT_FLOAT_EQ(running_light_blink_alpha(2.5f, 3.0f, 1.0f, 1.0f), 1.0f);
    EXPECT_FLOAT_EQ(running_light_blink_alpha(0.5f, 3.0f, 1.0f, 1.0f), 0.0f);
}

TEST(RunningLightBlink, LargePhaseAndTimeStayInRange) {
    const float a = running_light_blink_alpha(100000.25f, 3.0f, 1.0f, 999.0f);
    EXPECT_GE(a, 0.0f);
    EXPECT_LE(a, 1.0f);
}

TEST(RunningLightSize, WorldSizeWinsUpClose) {
    // proj11 = 1/tan(30 deg) for a 60 deg vertical fov; 1080 px tall.
    const float proj11 = 1.0f / std::tan(0.5236f);
    const float d = running_light_world_size(1.5f, 0.02f, 1.5f, 1.0f, proj11, 1080);
    EXPECT_NEAR(d, 0.03f, 1e-6f);
}

TEST(RunningLightSize, MinPixelFloorWinsFarAway) {
    const float proj11 = 1.0f / std::tan(0.5236f);
    const float dist = 500.0f;
    const float per_px = 2.0f * dist / (proj11 * 1080.0f);
    const float d = running_light_world_size(1.5f, 0.02f, 1.5f, dist, proj11, 1080);
    EXPECT_NEAR(d, 1.5f * per_px, 1e-4f);
    EXPECT_GT(d, 0.03f);
}

TEST(RunningLightSize, DegenerateViewportFallsBackToWorldSize) {
    EXPECT_NEAR(running_light_world_size(1.0f, 0.02f, 1.5f, 10.0f, 0.0f, 0), 0.02f, 1e-6f);
}
