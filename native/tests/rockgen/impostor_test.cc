#include <gtest/gtest.h>
#include <rockgen/impostor.h>
#include <rockgen/recipe.h>
#include <rockgen/shape.h>
#include <rockgen/surface.h>

#include "mini_recipe.h"

#include <glm/glm.hpp>

TEST(Impostor, SixteenFixedViews) {
    auto d = rockgen::impostor_view_dirs();
    ASSERT_EQ(d.size(), 16u);
    for (auto& v : d) EXPECT_NEAR(glm::length(v), 1.0f, 1e-5f);
    EXPECT_EQ(d, rockgen::impostor_view_dirs());
}

TEST(Impostor, CoverageInEveryCell) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);
    auto surf = rockgen::generate_rock_surface(s[0]);
    auto imp = rockgen::bake_impostor(lods[1], surf, 32);
    ASSERT_EQ(imp.albedo.width, 128u);
    for (int cell = 0; cell < 16; ++cell) {
        int cx = (cell % 4) * 32 + 16, cy = (cell / 4) * 32 + 16;   // cell centre is on the rock
        EXPECT_GT(imp.albedo.pixels[(cy * 128 + cx) * 4 + 3], 0) << cell;
        EXPECT_EQ(imp.albedo.pixels[((cell / 4) * 32 * 128 + (cell % 4) * 32) * 4 + 3], 0) << cell; // corner empty
    }
}

TEST(Impostor, Deterministic) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);
    auto surf = rockgen::generate_rock_surface(s[0]);
    auto a = rockgen::bake_impostor(lods[1], surf, 32);
    auto b = rockgen::bake_impostor(lods[1], surf, 32);
    EXPECT_EQ(a.albedo.pixels, b.albedo.pixels);
    EXPECT_EQ(a.normal.pixels, b.normal.pixels);
}
