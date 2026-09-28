#include <gtest/gtest.h>
#include <renderer/motion_blur_shutter.h>

namespace {
constexpr double kRef = 1.0 / 60.0;
}

TEST(MotionBlurShutter, NoDashAtReferenceRateIsOne) {
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(kRef, kRef, 0.0f), 1.0f);
}

TEST(MotionBlurShutter, NoDashSlowFrameShrinksInProportion) {
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(2.0 * kRef, kRef, 0.0f),
                    0.5f);
}

TEST(MotionBlurShutter, NoDashFastFrameClampsToOne) {
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(0.5 * kRef, kRef, 0.0f),
                    1.0f);
}

TEST(MotionBlurShutter, ZeroDtIsOne) {
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(0.0, kRef, 0.0f), 1.0f);
}

// Live finding 2026-09-27: mid-dash the fixed-distance reprojection saturates
// MAX_UV over nearly the whole screen and smears the sun into a blob. The blur
// fades out with the dash intensity.
TEST(MotionBlurShutter, FullDashIsZero) {
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(kRef, kRef, 1.0f), 0.0f);
}

TEST(MotionBlurShutter, HalfDashHalvesTheShutter) {
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(kRef, kRef, 0.5f), 0.5f);
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(2.0 * kRef, kRef, 0.5f),
                    0.25f);
}

TEST(MotionBlurShutter, OutOfRangeDashIsClamped) {
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(kRef, kRef, 2.0f), 0.0f);
    EXPECT_FLOAT_EQ(renderer::motion_blur_shutter(kRef, kRef, -1.0f), 1.0f);
}
