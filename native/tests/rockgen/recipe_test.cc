#include <gtest/gtest.h>
#include <rockgen/recipe.h>

#include "mini_recipe.h"

#include <stdexcept>
#include <string>

TEST(Recipe, ExpandsIdsInOrder) {
    auto r = rockgen::parse_recipe(kMini);
    auto specs = rockgen::expand_recipe(r);
    ASSERT_EQ(specs.size(), 3u);
    EXPECT_EQ(specs[0].id, "majors/silicate_01");
    EXPECT_EQ(specs[1].id, "majors/silicate_02");
    EXPECT_EQ(specs[2].id, "fragments/silicate_01");
    EXPECT_TRUE(specs[2].fragment);
    EXPECT_NE(specs[0].seed, specs[1].seed);
}

TEST(Recipe, MissingKeyNamesIt) {
    try { rockgen::parse_recipe(R"({"tool_version":1})"); FAIL(); }
    catch (const std::runtime_error& e) { EXPECT_NE(std::string(e.what()).find("seed"), std::string::npos); }
}

TEST(Recipe, Fnv1a64KnownVectors) {
    // Published FNV-1a 64 test vectors: the committed catalogue's per-rock
    // seeds are derived from this hash, so it must be the standard one.
    EXPECT_EQ(rockgen::fnv1a64(""), 0xcbf29ce484222325ull);
    EXPECT_EQ(rockgen::fnv1a64("a"), 0xaf63dc4c8601ec8cull);
    EXPECT_EQ(rockgen::fnv1a64("foobar"), 0x85944171f73967e8ull);
}
