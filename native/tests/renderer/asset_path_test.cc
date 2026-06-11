#include <renderer/asset_path.h>
#include <gtest/gtest.h>

using renderer::resolve_asset_path;

TEST(AssetPath, PrefixesSdkDataPath) {
    EXPECT_EQ(resolve_asset_path("data/Textures/Effects/ExplosionB.tga"),
              "game/data/Textures/Effects/ExplosionB.tga");
    EXPECT_EQ(resolve_asset_path("data/rough.tga"), "game/data/rough.tga");
}

TEST(AssetPath, IdempotentForAlreadyPrefixed) {
    EXPECT_EQ(resolve_asset_path("game/data/rough.tga"), "game/data/rough.tga");
}

TEST(AssetPath, LeavesAbsoluteAndEmptyUnchanged) {
    EXPECT_EQ(resolve_asset_path("/abs/path.tga"), "/abs/path.tga");
    EXPECT_EQ(resolve_asset_path(""), "");
}
