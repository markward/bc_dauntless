// native/tests/renderer/lighting_test.cc
#include <gtest/gtest.h>

#include <renderer/lighting.h>

TEST(Lighting, GlossinessToSpecularPowerPinnedValues) {
    using renderer::glossiness_to_specular_power;
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.00f),   48.0f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.12f),  226.56f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.25f),  420.0f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.30f),  494.4f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(1.00f), 1536.0f);
    // Clamp on out-of-range BC outlier (gloss=4.0 appears in the corpus)
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(4.00f), 1536.0f);
    // Clamp on negative
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(-1.0f),  48.0f);
}

#include <glm/glm.hpp>
#include <cmath>

TEST(AmbientGradient, SingleStarPointsAtItAtFullStrength) {
    const glm::vec3 dirs[1]   = { glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f)) };
    const glm::vec3 colors[1] = { glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 1, 0.6f);
    EXPECT_NEAR(g.dir_ws.x, dirs[0].x, 1e-5f);
    EXPECT_NEAR(g.dir_ws.y, dirs[0].y, 1e-5f);
    EXPECT_NEAR(g.dir_ws.z, dirs[0].z, 1e-5f);
    // One light is perfectly coherent, so it gets the whole budget.
    EXPECT_NEAR(g.strength, 0.6f, 1e-5f);
}

TEST(AmbientGradient, TwoOpposedEqualStarsCancelToFlatAmbient) {
    // THE CASE THIS FUNCTION EXISTS FOR. With light arriving from both sides
    // there is no shadow side to fill, so the gradient must vanish -- and it
    // must do so by construction, not via a special case.
    const glm::vec3 dirs[2]   = { glm::vec3(1, 0, 0), glm::vec3(-1, 0, 0) };
    const glm::vec3 colors[2] = { glm::vec3(1.0f), glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 0.6f);
    EXPECT_NEAR(g.strength, 0.0f, 1e-5f);
}

TEST(AmbientGradient, TwoStarsSameSideAgreeOnDirection) {
    const glm::vec3 dirs[2] = { glm::normalize(glm::vec3(1, 1, 0)),
                                glm::normalize(glm::vec3(1, -1, 0)) };
    const glm::vec3 colors[2] = { glm::vec3(1.0f), glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 1.0f);
    // Symmetric about +X, so the sum lands on +X.
    EXPECT_NEAR(g.dir_ws.x, 1.0f, 1e-4f);
    EXPECT_NEAR(g.dir_ws.y, 0.0f, 1e-4f);
    // Partially coherent: less than a single light, more than nothing.
    EXPECT_GT(g.strength, 0.0f);
    EXPECT_LT(g.strength, 1.0f);
}

TEST(AmbientGradient, OpposedButUnequalFavoursTheBrighter) {
    const glm::vec3 dirs[2]   = { glm::vec3(1, 0, 0), glm::vec3(-1, 0, 0) };
    const glm::vec3 colors[2] = { glm::vec3(1.0f), glm::vec3(0.25f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 1.0f);
    EXPECT_NEAR(g.dir_ws.x, 1.0f, 1e-4f);
    EXPECT_GT(g.strength, 0.0f);
    EXPECT_LT(g.strength, 1.0f);
}

TEST(AmbientGradient, WeightsByLuminanceNotByCount) {
    // A dim red light must lose to a bright white one. Red is the lowest-
    // luminance primary (0.2126), so this also pins the coefficients.
    const glm::vec3 dirs[2]   = { glm::vec3(1, 0, 0), glm::vec3(-1, 0, 0) };
    const glm::vec3 colors[2] = { glm::vec3(0.2f, 0.0f, 0.0f), glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 1.0f);
    EXPECT_NEAR(g.dir_ws.x, -1.0f, 1e-4f);   // the white light wins
}

TEST(AmbientGradient, NoLightsGivesZeroStrength) {
    const auto g = renderer::ambient_gradient_from_lights(nullptr, nullptr, 0, 0.6f);
    EXPECT_NEAR(g.strength, 0.0f, 1e-6f);
}

TEST(AmbientGradient, BlackLightsGiveZeroStrengthWithoutDividingByZero) {
    // Total luminance 0 would be a divide-by-zero in the coherence term.
    const glm::vec3 dirs[1]   = { glm::vec3(1, 0, 0) };
    const glm::vec3 colors[1] = { glm::vec3(0.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 1, 0.6f);
    EXPECT_NEAR(g.strength, 0.0f, 1e-6f);
    EXPECT_TRUE(std::isfinite(g.dir_ws.x));
    EXPECT_TRUE(std::isfinite(g.dir_ws.y));
    EXPECT_TRUE(std::isfinite(g.dir_ws.z));
}

TEST(AmbientGradient, ZeroLengthDirectionIsSkippedNotNormalised) {
    // aggregate_for_renderer filters these, but a zero vector reaching
    // normalize() would produce NaN and poison the whole frame.
    const glm::vec3 dirs[2]   = { glm::vec3(0, 0, 0), glm::vec3(1, 0, 0) };
    const glm::vec3 colors[2] = { glm::vec3(1.0f), glm::vec3(1.0f) };
    const auto g = renderer::ambient_gradient_from_lights(dirs, colors, 2, 1.0f);
    EXPECT_TRUE(std::isfinite(g.strength));
    EXPECT_NEAR(g.dir_ws.x, 1.0f, 1e-4f);
}

TEST(AmbientGradient, StrengthIsClampedIntoZeroOne) {
    const glm::vec3 dirs[1]   = { glm::vec3(1, 0, 0) };
    const glm::vec3 colors[1] = { glm::vec3(1.0f) };
    EXPECT_NEAR(renderer::ambient_gradient_from_lights(dirs, colors, 1, 5.0f).strength,
                1.0f, 1e-6f);
    EXPECT_NEAR(renderer::ambient_gradient_from_lights(dirs, colors, 1, -2.0f).strength,
                0.0f, 1e-6f);
}
