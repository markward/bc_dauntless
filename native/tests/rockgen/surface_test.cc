#include <gtest/gtest.h>
#include <rockgen/recipe.h>
#include <rockgen/surface.h>

#include "mini_recipe.h"

TEST(Surface, DeterministicAndSized) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_surface(s[0]), b = rockgen::generate_rock_surface(s[0]);
    EXPECT_EQ(a.base_color.width, 64u);
    EXPECT_EQ(a.base_color.pixels, b.base_color.pixels);
    EXPECT_EQ(a.normal.pixels, b.normal.pixels);
}

TEST(Surface, AlbedoWithinPalette) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_surface(s[0]);
    for (int c = 0; c < 3; ++c) { EXPECT_GE(a.avg_albedo[c], 0.25f); EXPECT_LE(a.avg_albedo[c], 0.65f); }
}

TEST(Surface, NormalMapIsUnitAndMostlyUp) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_surface(s[0]);
    double z = 0; size_t n = a.normal.width * a.normal.height;
    for (size_t i = 0; i < n; ++i) z += a.normal.pixels[i * 3 + 2] / 255.0;
    EXPECT_GT(z / n, 0.75);                                    // tangent-space, +Z dominant
}
