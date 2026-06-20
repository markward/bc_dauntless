#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include "renderer/shadow_light.h"

using renderer::ShadowFitParams;
using renderer::compute_light_matrix;

namespace {
glm::vec3 project_ndc(const glm::mat4& vp, const glm::vec3& p) {
    glm::vec4 c = vp * glm::vec4(p, 1.0f);
    return glm::vec3(c) / c.w; // ortho → w == 1, but keep general
}
}

TEST(LightMatrix, TexelWorldSizeMatchesHalfExtent) {
    ShadowFitParams pr;          // k=3, clamp [2,40], res 2048
    auto sl = compute_light_matrix({0, 0, 0}, 5.0f, glm::normalize(glm::vec3(0, 1, 0)), pr);
    // R = clamp(3*5, 2, 40) = 15 → texel = 2*15/2048
    EXPECT_NEAR(sl.texel_world_size, 30.0f / 2048.0f, 1e-4f);
}

TEST(LightMatrix, RadiusClampsToMax) {
    ShadowFitParams pr;
    auto sl = compute_light_matrix({0, 0, 0}, 1000.0f, glm::normalize(glm::vec3(0, 1, 0)), pr);
    EXPECT_NEAR(sl.texel_world_size, 2.0f * pr.radius_max_gu / pr.resolution, 1e-4f);
}

TEST(LightMatrix, RadiusClampsToMin) {
    ShadowFitParams pr;
    auto sl = compute_light_matrix({0, 0, 0}, 0.01f, glm::normalize(glm::vec3(0, 1, 0)), pr);
    EXPECT_NEAR(sl.texel_world_size, 2.0f * pr.radius_min_gu / pr.resolution, 1e-4f);
}

TEST(LightMatrix, PlayerCenterProjectsNearOrigin) {
    ShadowFitParams pr;
    glm::vec3 center(123.0f, -45.0f, 67.0f);
    auto sl = compute_light_matrix(center, 5.0f, glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f)), pr);
    glm::vec3 ndc = project_ndc(sl.view_proj, center);
    // After texel-snap the center sits within a couple of texels of the NDC origin.
    float tol = 4.0f / pr.resolution;
    EXPECT_LT(std::abs(ndc.x), tol);
    EXPECT_LT(std::abs(ndc.y), tol);
    EXPECT_GT(ndc.z, -1.0f);
    EXPECT_LT(ndc.z, 1.0f);
}

TEST(LightMatrix, CasterTowardSunIsInsideFrustum) {
    ShadowFitParams pr;
    glm::vec3 center(0, 0, 0);
    glm::vec3 L = glm::normalize(glm::vec3(0.2f, 1.0f, 0.1f));
    auto sl = compute_light_matrix(center, 5.0f, L, pr);
    // A caster halfway along the reach toward the sun must be captured.
    glm::vec3 caster = center + L * (pr.caster_reach_gu * 0.5f);
    glm::vec3 ndc = project_ndc(sl.view_proj, caster);
    EXPECT_GT(ndc.z, -1.0f);
    EXPECT_LT(ndc.z, 1.0f);
    EXPECT_LT(std::abs(ndc.x), 1.0f);
    EXPECT_LT(std::abs(ndc.y), 1.0f);
}
