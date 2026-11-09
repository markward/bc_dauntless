#include <gtest/gtest.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <renderer/motion_blur_skip.h>

#include <cmath>
#include <limits>
#include <string>

#include "embedded_motion_blur_fs.h"

namespace {
constexpr int kW = 1280;
constexpr int kH = 720;

glm::mat4 proj() {
    return glm::perspective(glm::radians(60.0f),
                            static_cast<float>(kW) / kH, 0.1f, 10000.0f);
}

struct Cam {
    glm::mat4 view;
    glm::mat4 inv_proj;
    glm::mat3 rot;
    glm::vec3 pos;
};

Cam make_cam(float yaw_deg, const glm::vec3& pos) {
    Cam c;
    c.pos = pos;
    c.view = glm::rotate(glm::mat4(1.0f), glm::radians(-yaw_deg),
                         glm::vec3(0, 1, 0)) *
             glm::translate(glm::mat4(1.0f), -pos);
    c.inv_proj = glm::inverse(proj());
    c.rot = glm::mat3(glm::inverse(c.view));
    return c;
}
}  // namespace

TEST(MotionBlurSkip, IdenticalViewIsZero) {
    const Cam c = make_cam(0.0f, {1, 2, 3});
    const float px = renderer::motion_blur_max_px(
        c.inv_proj, c.rot, c.pos, proj() * c.view, 1.0f, kW, kH);
    EXPECT_LT(px, 1e-2f);
}

TEST(MotionBlurSkip, SmallYawExceedsThreshold) {
    const Cam prev = make_cam(0.0f, {0, 0, 0});
    const Cam cur = make_cam(0.2f, {0, 0, 0});
    const float px = renderer::motion_blur_max_px(
        cur.inv_proj, cur.rot, cur.pos, proj() * prev.view, 1.0f, kW, kH);
    EXPECT_GE(px, renderer::kMotionBlurSkipPx);
}

TEST(MotionBlurSkip, TinyJitterBelowThreshold) {
    const Cam prev = make_cam(0.0f, {0, 0, 0});
    const Cam cur = make_cam(0.0f, {0.0005f, 0, 0});
    const float px = renderer::motion_blur_max_px(
        cur.inv_proj, cur.rot, cur.pos, proj() * prev.view, 1.0f, kW, kH);
    EXPECT_LT(px, renderer::kMotionBlurSkipPx);
}

TEST(MotionBlurSkip, PointBehindPrevCameraIsInf) {
    const Cam cur = make_cam(0.0f, {0, 0, 0});
    const Cam prev = make_cam(180.0f, {0, 0, 0});
    const float px = renderer::motion_blur_max_px(
        cur.inv_proj, cur.rot, cur.pos, proj() * prev.view, 1.0f, kW, kH);
    EXPECT_TRUE(std::isinf(px));
}

TEST(MotionBlurSkip, NonFiniteIsInf) {
    const Cam c = make_cam(0.0f, {0, 0, 0});
    const float px = renderer::motion_blur_max_px(
        c.inv_proj, c.rot, c.pos, proj() * c.view,
        std::numeric_limits<float>::quiet_NaN(), kW, kH);
    EXPECT_TRUE(std::isinf(px));
}

TEST(MotionBlurSkip, ConstantsMatchShader) {
    const std::string fs = renderer::shader_src::motion_blur_fs;
    EXPECT_NE(fs.find("const float STRENGTH    = 0.7;"), std::string::npos);
    EXPECT_NE(fs.find("const float DISTANCE_GU = 100.0;"), std::string::npos);
    EXPECT_FLOAT_EQ(renderer::kMotionBlurStrength, 0.7f);
    EXPECT_FLOAT_EQ(renderer::kMotionBlurDistanceGu, 100.0f);
}
