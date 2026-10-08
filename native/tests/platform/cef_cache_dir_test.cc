// Two dauntless builds running at once (one per worktree) used to share one
// CEF root_cache_path, $TMPDIR/dauntless-cef-cache. Chromium allows one browser
// process per cache folder, so the second launch printed "Opening in existing
// browser session.", its CefInitialize failed, the running game opened a stray
// browser window, and the second game came up with no UI layer (confirmed
// 2026-10-08). The cache folder is now keyed on the executable's path.

#include "platform/exe_path.h"

#include <gtest/gtest.h>

#include <filesystem>
#include <string>

namespace {

using dauntless::platform::cef_cache_dir;
namespace fs = std::filesystem;

const fs::path kBase = "/tmp/base";

TEST(CefCacheDir, TwoBuildsGetTwoFolders) {
    EXPECT_NE(cef_cache_dir(kBase, "/proj/build/dauntless"),
              cef_cache_dir(kBase, "/proj/.claude/worktrees/x/build/dauntless"));
}

TEST(CefCacheDir, OneBuildKeepsOneFolderAcrossLaunches) {
    // Stable, so the GPU/shader cache persists between runs of a build.
    EXPECT_EQ(cef_cache_dir(kBase, "/proj/build/dauntless"),
              cef_cache_dir(kBase, "/proj/build/dauntless"));
}

TEST(CefCacheDir, SpellingsOfOnePathAreOneBuild) {
    EXPECT_EQ(cef_cache_dir(kBase, "/proj/build/../build/./dauntless"),
              cef_cache_dir(kBase, "/proj/build/dauntless"));
}

TEST(CefCacheDir, LivesUnderTheBaseWithARecognisableName) {
    const fs::path dir = cef_cache_dir(kBase, "/proj/build/dauntless");
    EXPECT_EQ(dir.parent_path(), kBase);
    const std::string name = dir.filename().string();
    EXPECT_EQ(name.rfind("dauntless-cef-cache-", 0), 0u) << name;
    EXPECT_EQ(name.size(), std::string("dauntless-cef-cache-").size() + 16) << name;
}

}  // namespace
