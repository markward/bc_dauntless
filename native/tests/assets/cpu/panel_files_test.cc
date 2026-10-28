#include <gtest/gtest.h>

#include <assets/panel_files.h>

#include <filesystem>
#include <fstream>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace {

inline int current_pid() {
#ifdef _WIN32
    return _getpid();
#else
    return ::getpid();
#endif
}

class PanelFilesTest : public ::testing::Test {
protected:
    fs::path tmp_dir;

    void SetUp() override {
        tmp_dir = fs::temp_directory_path() /
            ("panel_files_test_" + std::to_string(current_pid()) + "_" +
             ::testing::UnitTest::GetInstance()->current_test_info()->name());
        fs::remove_all(tmp_dir);
        fs::create_directories(tmp_dir);
    }
    void TearDown() override { fs::remove_all(tmp_dir); }

    static void touch(const fs::path& p) {
        fs::create_directories(p.parent_path());
        std::ofstream(p) << "{}";
    }
};

}  // namespace

using assets::kPanelDefault;
using assets::kPanelRed;
using assets::kPanelSpecial;
using assets::kPanelYellow;

TEST_F(PanelFilesTest, FindsDefaultAndStates) {
    touch(tmp_dir / "hull.json");
    touch(tmp_dir / "hull_r.json");
    auto pf = assets::find_panel_files(tmp_dir / "hull.tga", {tmp_dir});
    EXPECT_EQ(pf.by_variant[kPanelDefault], tmp_dir / "hull.json");
    EXPECT_TRUE(pf.by_variant[kPanelYellow].empty());
    EXPECT_EQ(pf.by_variant[kPanelRed], tmp_dir / "hull_r.json");
    EXPECT_TRUE(pf.by_variant[kPanelSpecial].empty());
}

TEST_F(PanelFilesTest, MatchesSpacesAndCaseInsensitively) {
    touch(tmp_dir / "map 7.JSON");
    touch(tmp_dir / "MAP 7_Y.JSON");
    auto pf = assets::find_panel_files(tmp_dir / "Map 7.tga", {tmp_dir});
    EXPECT_FALSE(pf.by_variant[kPanelDefault].empty());
    EXPECT_FALSE(pf.by_variant[kPanelYellow].empty());
    EXPECT_TRUE(pf.by_variant[kPanelRed].empty());
    EXPECT_TRUE(pf.by_variant[kPanelSpecial].empty());
}

TEST_F(PanelFilesTest, StateFileWithoutDefaultIsIgnored) {
    touch(tmp_dir / "hull_y.json");
    auto pf = assets::find_panel_files(tmp_dir / "hull.tga", {tmp_dir});
    for (const auto& p : pf.by_variant) EXPECT_TRUE(p.empty());
}

TEST_F(PanelFilesTest, FirstDirWithDefaultWins) {
    touch(tmp_dir / "a" / "hull_r.json");
    touch(tmp_dir / "b" / "hull.json");
    auto pf = assets::find_panel_files(tmp_dir / "hull.tga",
                                       {tmp_dir / "a", tmp_dir / "b"});
    EXPECT_EQ(pf.by_variant[kPanelDefault], tmp_dir / "b" / "hull.json");
    EXPECT_TRUE(pf.by_variant[kPanelRed].empty());
}

TEST(PanelVariant, Chain) {
    using A = std::array<bool, assets::kPanelVariants>;
    const A a{true, true, false, false};
    const int expect_a[5] = {0, 1, 1, 0, 0};
    for (int s = 0; s < 5; ++s) EXPECT_EQ(assets::select_panel_variant(s, a), expect_a[s]) << s;
    const A b{true, false, true, true};
    EXPECT_EQ(assets::select_panel_variant(2, b), 2);
    EXPECT_EQ(assets::select_panel_variant(1, b), 0);
    EXPECT_EQ(assets::select_panel_variant(4, b), 3);
    const A c{false, false, true, false};
    EXPECT_EQ(assets::select_panel_variant(0, c), -1);
    EXPECT_EQ(assets::select_panel_variant(2, c), 2);
}
