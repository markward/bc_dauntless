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

TEST(Lighting, RimStrengthFromMaterialPinnedValues) {
    using renderer::rim_strength_from_material;
    // No specular -> no rim, regardless of gloss.
    EXPECT_FLOAT_EQ(rim_strength_from_material({0.0f, 0.0f, 0.0f}, 0.0f), 0.0f);
    EXPECT_FLOAT_EQ(rim_strength_from_material({0.0f, 0.0f, 0.0f}, 1.0f), 0.0f);
    // Full white specular: gloss scales 0.25 (matte) -> 1.0 (glossy).
    EXPECT_FLOAT_EQ(rim_strength_from_material({1.0f, 1.0f, 1.0f}, 0.0f), 0.25f);
    EXPECT_FLOAT_EQ(rim_strength_from_material({1.0f, 1.0f, 1.0f}, 1.0f), 1.0f);
    // Mid specular, mid gloss: 0.5 * (0.25 + 0.75*0.5) = 0.3125.
    EXPECT_FLOAT_EQ(rim_strength_from_material({0.5f, 0.5f, 0.5f}, 0.5f), 0.3125f);
    // Strength uses the brightest specular channel (max), not luminance.
    EXPECT_FLOAT_EQ(rim_strength_from_material({0.2f, 0.8f, 0.1f}, 1.0f), 0.8f);
    // Clamp out-of-range BC outliers (gloss=4.0 appears in the corpus).
    EXPECT_FLOAT_EQ(rim_strength_from_material({2.0f, 2.0f, 2.0f}, 4.0f), 1.0f);
    // Clamp negatives.
    EXPECT_FLOAT_EQ(rim_strength_from_material({-1.0f, -1.0f, -1.0f}, -1.0f), 0.0f);
}

TEST(Lighting, RoughnessFromGlossinessPinnedValues) {
    using renderer::roughness_from_glossiness;
    // bias=0: linear inverse r = clamp(0.9 - 2*g, 0.04, 1).
    EXPECT_FLOAT_EQ(roughness_from_glossiness(0.00f, 0.0f), 0.9f);
    EXPECT_FLOAT_EQ(roughness_from_glossiness(0.12f, 0.0f), 0.66f);
    EXPECT_FLOAT_EQ(roughness_from_glossiness(0.30f, 0.0f), 0.30f);
    // g=1 -> 0.9-2 = -1.1 -> clamp to the 0.04 floor.
    EXPECT_FLOAT_EQ(roughness_from_glossiness(1.00f, 0.0f), 0.04f);
    // Positive bias mattes the hull (additive before clamp).
    EXPECT_FLOAT_EQ(roughness_from_glossiness(0.00f, -0.5f), 0.4f);
    // Clamp to 1.0 at the top.
    EXPECT_FLOAT_EQ(roughness_from_glossiness(0.00f, 0.5f), 1.0f);
    // Out-of-range BC gloss outlier (4.0) clamps like g=1 -> floor.
    EXPECT_FLOAT_EQ(roughness_from_glossiness(4.00f, 0.0f), 0.04f);
}
