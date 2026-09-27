// Contract for the ONE shared BC-content-root helper every asset-backed C++
// test resolves its paths through (support/content_root.h,
// support/renderer_game_root.h). Before it existed each test file carried its
// own copy -- and the copies disagreed on whether DAUNTLESS_GAME_DIR="" means
// "unset".
#include <gtest/gtest.h>

#include <renderer/asset_path.h>

#include "support/content_root.h"
#include "support/renderer_game_root.h"

namespace fs = std::filesystem;

TEST(TestContentRoot, UnsetEnvFallsBackToTheLegacyInProjectRoot) {
    EXPECT_EQ(test_support::resolve_game_root(nullptr, "/proj"),
              fs::path("/proj") / "game");
}

// engine/paths.py treats an empty env var as unset; so must the tests, or an
// exported-but-empty DAUNTLESS_GAME_DIR resolves every asset against CWD.
TEST(TestContentRoot, EmptyEnvIsTreatedAsUnset) {
    EXPECT_EQ(test_support::resolve_game_root("", "/proj"),
              fs::path("/proj") / "game");
}

TEST(TestContentRoot, SetEnvWinsOverTheProjectRoot) {
    EXPECT_EQ(test_support::resolve_game_root("/opt/BC/game", "/proj"),
              fs::path("/opt/BC/game"));
}

TEST(TestContentRoot, ProjectRootIsTheCheckout) {
    EXPECT_TRUE(fs::exists(test_support::project_root() / "CMakeLists.txt"))
        << test_support::project_root();
}

// resolve_mods_root() mirrors resolve_game_root() above, just with a
// different env var and fallback leaf -- same three cases.
TEST(TestModsRoot, UnsetEnvFallsBackToTheProjectMods) {
    EXPECT_EQ(test_support::resolve_mods_root(nullptr, "/proj"),
              fs::path("/proj") / "mods");
}

// engine/mods.py treats an empty DAUNTLESS_MODS_DIR as unset too.
TEST(TestModsRoot, EmptyEnvIsTreatedAsUnset) {
    EXPECT_EQ(test_support::resolve_mods_root("", "/proj"),
              fs::path("/proj") / "mods");
}

TEST(TestModsRoot, SetEnvWinsOverTheProjectMods) {
    EXPECT_EQ(test_support::resolve_mods_root("/opt/mods", "/proj"),
              fs::path("/opt/mods"));
}

// With no env root the renderer keeps its default RELATIVE "game": the tests
// that emulate the runtime CWD rely on exactly that to exercise
// resolve_asset_path's relative branch.
TEST(RendererGameRootGuard, UnsetEnvLeavesTheRendererDefaultAlone) {
    const std::string before = renderer::game_root();
    {
        test_support::RendererGameRootGuard guard;
        guard.apply_env(nullptr);
        EXPECT_EQ(renderer::game_root(), before);
        guard.apply_env("");
        EXPECT_EQ(renderer::game_root(), before);
    }
    EXPECT_EQ(renderer::game_root(), before);
}

// The renderer game root is process-global and ctest runs a binary's cases in
// one process, so the guard must restore it on scope exit.
TEST(RendererGameRootGuard, SetEnvIsAppliedThenRestored) {
    const std::string before = renderer::game_root();
    {
        test_support::RendererGameRootGuard guard;
        guard.apply_env("/opt/BC/game");
        EXPECT_EQ(renderer::game_root(), "/opt/BC/game");
    }
    EXPECT_EQ(renderer::game_root(), before);
}
