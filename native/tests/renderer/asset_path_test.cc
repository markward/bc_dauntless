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

// --- is_absolute_asset_path -------------------------------------------------
//
// Added when resolve_asset_path grew a Windows arm. The rules are deliberately
// asymmetric: on Windows a leading backslash or a drive qualifier names an
// absolute location, while on POSIX a backslash is an ordinary filename
// character and "C:" is a legal relative name. An earlier revision applied the
// Windows rules everywhere, which reclassified legitimate POSIX relative paths
// as absolute and skipped the "game/" prefix they needed.

using renderer::is_absolute_asset_path;

TEST(AssetPath, PosixRootIsAbsoluteOnEveryPlatform) {
    EXPECT_TRUE(is_absolute_asset_path("/abs/path.tga"));
    EXPECT_TRUE(is_absolute_asset_path("/"));
}

TEST(AssetPath, EmptyIsNotAbsolute) {
    EXPECT_FALSE(is_absolute_asset_path(""));
}

TEST(AssetPath, PlainRelativePathsAreNotAbsolute) {
    EXPECT_FALSE(is_absolute_asset_path("data/rough.tga"));
    EXPECT_FALSE(is_absolute_asset_path("rough.tga"));
}

TEST(AssetPath, WindowsShapesFollowThePlatformRule) {
    // Same inputs, opposite verdicts by platform -- that asymmetry IS the fix.
    const std::string drive = "C:/game/data/x.NIF";
    const std::string drive_backslash = std::string("C:") + renderer::kBackslash + "game";
    const std::string unc = std::string(1, renderer::kBackslash) + "server/share";
#ifdef _WIN32
    EXPECT_TRUE(is_absolute_asset_path(drive));
    EXPECT_TRUE(is_absolute_asset_path(drive_backslash));
    EXPECT_TRUE(is_absolute_asset_path(unc));
    // A drive letter with no separator is relative-to-CWD-on-that-drive; the
    // resolver does not claim to handle it, so it must not be called absolute.
    EXPECT_FALSE(is_absolute_asset_path("C:game"));
#else
    EXPECT_FALSE(is_absolute_asset_path(drive));
    EXPECT_FALSE(is_absolute_asset_path(drive_backslash));
    EXPECT_FALSE(is_absolute_asset_path(unc));
    // ...and because they are relative here, resolve_asset_path must prefix
    // them rather than hand back an unopenable path.
    EXPECT_EQ(resolve_asset_path(drive), "game/" + drive);
#endif
}

TEST(AssetPath, AlreadyPrefixedRequiresASeparatorNotJustThePrefix) {
    // "gameplay/..." starts with "game" but is not under game/.
    EXPECT_EQ(resolve_asset_path("gameplay/x.tga"), "game/gameplay/x.tga");
    // Bare "game" is a file named game, not the prefix.
    EXPECT_EQ(resolve_asset_path("game"), "game/game");
}
