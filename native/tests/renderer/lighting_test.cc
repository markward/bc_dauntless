// native/tests/renderer/lighting_test.cc
#include <gtest/gtest.h>

#include <renderer/lighting.h>

TEST(Lighting, GlossinessToSpecularPowerPinnedValues) {
    using renderer::glossiness_to_specular_power;
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.00f),   4.0f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.12f),  18.88f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.25f),  35.0f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(0.30f),  41.2f);
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(1.00f), 128.0f);
    // Clamp on out-of-range BC outlier (gloss=4.0 appears in the corpus)
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(4.00f), 128.0f);
    // Clamp on negative
    EXPECT_FLOAT_EQ(glossiness_to_specular_power(-1.0f),  4.0f);
}
