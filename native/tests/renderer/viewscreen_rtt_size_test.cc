// native/tests/renderer/viewscreen_rtt_size_test.cc
//
// The bridge viewscreen feed is sized to the viewscreen's on-screen pixel
// footprint: projected box -> 16:9 height (rounded up, clamped) -> a sizer
// that grows at once and shrinks only after a delay.
#include <gtest/gtest.h>
#include <renderer/viewscreen_rtt_size.h>

#include <glm/gtc/matrix_transform.hpp>

#include <cmath>

using namespace renderer::viewscreen_rtt;

namespace {

constexpr int kFw = 1600;
constexpr int kFh = 1000;

// Eye at the origin looking down -Z, 60 degree vertical fov, kFw x kFh.
glm::mat4 view_proj() {
    const glm::mat4 proj = glm::perspective(glm::radians(60.0f),
        static_cast<float>(kFw) / static_cast<float>(kFh), 0.1f, 1000.0f);
    const glm::mat4 view = glm::lookAt(glm::vec3(0.0f), glm::vec3(0.0f, 0.0f, -1.0f),
                                       glm::vec3(0.0f, 1.0f, 0.0f));
    return proj * view;
}

// Pixel height of a 2-unit-tall flat box at distance d: 2 / (2 d tan30) * fh.
float expected_px(float d) {
    return kFh / (d * std::tan(glm::radians(30.0f)));
}

}  // namespace

TEST(ViewscreenRttSize, HeightCoversASmallScreenWithTheFloor) {
    EXPECT_EQ(height_for_extent({100.0f, 50.0f}), kMinHeight);
}

TEST(ViewscreenRttSize, HeightRoundsUpToTheStep) {
    EXPECT_EQ(height_for_extent({500.0f, 500.0f}), 540);
    EXPECT_EQ(height_for_extent({100.0f, 720.0f}), 720);
    EXPECT_EQ(height_for_extent({100.0f, 720.5f}), 810);
}

TEST(ViewscreenRttSize, AWideScreenTakesItsHeightFromItsWidth) {
    // 1600 wide at 16:9 needs 900 tall, more than the 400 it spans.
    EXPECT_EQ(height_for_extent({1600.0f, 400.0f}), 900);
}

TEST(ViewscreenRttSize, HeightIsCapped) {
    EXPECT_EQ(height_for_extent({4000.0f, 2000.0f}), kMaxHeight);
}

TEST(ViewscreenRttSize, WidthIsSixteenNinthsOfHeight) {
    EXPECT_EQ(width_for_height(360), 640);
    EXPECT_EQ(width_for_height(540), 960);
    EXPECT_EQ(width_for_height(1080), 1920);
}

TEST(ViewscreenRttSize, ProjectsABoxInFrontOfTheCamera) {
    const auto px = projected_extent_px(view_proj(), glm::mat4(1.0f),
        glm::vec3(-1.0f, -1.0f, -10.0f), glm::vec3(1.0f, 1.0f, -10.0f), kFw, kFh);
    ASSERT_TRUE(px.has_value());
    EXPECT_NEAR(px->h, expected_px(10.0f), 0.5f);
    // Square pixels: the box is as wide as it is tall on screen.
    EXPECT_NEAR(px->w, expected_px(10.0f), 0.5f);
}

TEST(ViewscreenRttSize, AppliesTheInstanceWorldMatrix) {
    const glm::mat4 world = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -10.0f))
                          * glm::scale(glm::mat4(1.0f), glm::vec3(2.0f));
    const auto px = projected_extent_px(view_proj(), world,
        glm::vec3(-1.0f, -1.0f, 0.0f), glm::vec3(1.0f, 1.0f, 0.0f), kFw, kFh);
    ASSERT_TRUE(px.has_value());
    EXPECT_NEAR(px->h, 2.0f * expected_px(10.0f), 0.5f);
}

TEST(ViewscreenRttSize, ClipsToTheViewport) {
    const auto px = projected_extent_px(view_proj(), glm::mat4(1.0f),
        glm::vec3(-50.0f, -50.0f, -10.0f), glm::vec3(50.0f, 50.0f, -10.0f), kFw, kFh);
    ASSERT_TRUE(px.has_value());
    EXPECT_FLOAT_EQ(px->w, static_cast<float>(kFw));
    EXPECT_FLOAT_EQ(px->h, static_cast<float>(kFh));
}

TEST(ViewscreenRttSize, ABoxBehindTheCameraIsNotOnScreen) {
    EXPECT_FALSE(projected_extent_px(view_proj(), glm::mat4(1.0f),
        glm::vec3(-1.0f, -1.0f, 5.0f), glm::vec3(1.0f, 1.0f, 10.0f), kFw, kFh).has_value());
}

TEST(ViewscreenRttSize, ABoxOutsideTheFrustumIsNotOnScreen) {
    EXPECT_FALSE(projected_extent_px(view_proj(), glm::mat4(1.0f),
        glm::vec3(100.0f, -1.0f, -10.0f), glm::vec3(102.0f, 1.0f, -10.0f), kFw, kFh).has_value());
}

TEST(ViewscreenRttSize, ABoxAcrossTheEyePlaneFillsTheViewport) {
    const auto px = projected_extent_px(view_proj(), glm::mat4(1.0f),
        glm::vec3(-1.0f, -1.0f, -5.0f), glm::vec3(1.0f, 1.0f, 5.0f), kFw, kFh);
    ASSERT_TRUE(px.has_value());
    EXPECT_FLOAT_EQ(px->w, static_cast<float>(kFw));
    EXPECT_FLOAT_EQ(px->h, static_cast<float>(kFh));
}

TEST(ViewscreenRttSizer, StartsAtTheFloor) {
    Sizer s;
    EXPECT_EQ(s.height(), kMinHeight);
}

TEST(ViewscreenRttSizer, GrowsAtOnce) {
    Sizer s;
    EXPECT_EQ(s.update(720, 0.0), 720);
}

TEST(ViewscreenRttSizer, ShrinksOnlyAfterTheDelay) {
    Sizer s;
    s.update(540, 0.0);
    EXPECT_EQ(s.update(360, 0.25), 540);
    EXPECT_EQ(s.update(360, 0.25 + kShrinkDelayS - 0.01), 540);
    EXPECT_EQ(s.update(360, 0.25 + kShrinkDelayS), 360);
}

TEST(ViewscreenRttSizer, ABriefGrowBackRestartsTheShrinkDelay) {
    Sizer s;
    s.update(540, 0.0);
    s.update(360, 0.25);
    s.update(540, 0.5);
    s.update(360, 0.625);
    EXPECT_EQ(s.update(360, 0.625 + kShrinkDelayS - 0.01), 540);
    EXPECT_EQ(s.update(360, 0.625 + kShrinkDelayS), 360);
}

TEST(ViewscreenRttSizer, KeepsItsSizeWhenTheScreenIsNotVisible) {
    Sizer s;
    s.update(720, 0.0);
    EXPECT_EQ(s.update(std::nullopt, 5.0), 720);
    // Off-screen time does not count toward a shrink.
    s.update(360, 6.0);
    EXPECT_EQ(s.update(360, 6.0 + kShrinkDelayS - 0.01), 720);
}
