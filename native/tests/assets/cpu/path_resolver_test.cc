#include <gtest/gtest.h>
#include <assets/path_resolver.h>

#include <filesystem>
#include <fstream>
#include <unistd.h>

namespace fs = std::filesystem;

namespace {

class PathResolverTest : public ::testing::Test {
protected:
    fs::path tmp_dir;

    void SetUp() override {
        auto base = fs::temp_directory_path() / "assets-resolver";
        for (int i = 0; ; ++i) {
            auto candidate = base;
            candidate += "-" + std::to_string(::getpid()) + "-" + std::to_string(i);
            if (!fs::exists(candidate)) { tmp_dir = candidate; break; }
        }
        fs::create_directories(tmp_dir);
    }

    void TearDown() override {
        std::error_code ec;
        fs::remove_all(tmp_dir, ec);
    }

    void create_file(const fs::path& p) {
        fs::create_directories(p.parent_path());
        std::ofstream(p) << "x";
    }
};

}  // namespace

TEST_F(PathResolverTest, ExactBasenameMatch) {
    create_file(tmp_dir / "Ent-D_wing.tga");
    assets::PathResolver r;
    EXPECT_EQ(r.resolve("Ent-D_wing.tga", tmp_dir), tmp_dir / "Ent-D_wing.tga");
}

TEST_F(PathResolverTest, CaseInsensitiveLookup) {
    create_file(tmp_dir / "Ent-D_wing.tga");
    assets::PathResolver r;
    EXPECT_EQ(r.resolve("ent-d_wing.tga", tmp_dir), tmp_dir / "Ent-D_wing.tga");
}

TEST_F(PathResolverTest, AppendsTgaWhenNoExtension) {
    create_file(tmp_dir / "hull.tga");
    assets::PathResolver r;
    EXPECT_EQ(r.resolve("hull", tmp_dir), tmp_dir / "hull.tga");
}

TEST_F(PathResolverTest, ThrowsTextureNotFoundOnMiss) {
    assets::PathResolver r;
    EXPECT_THROW(r.resolve("missing.tga", tmp_dir), assets::TextureNotFound);
}

TEST_F(PathResolverTest, RebuildsCacheAfterMiss) {
    assets::PathResolver r;
    EXPECT_THROW(r.resolve("late.tga", tmp_dir), assets::TextureNotFound);
    create_file(tmp_dir / "late.tga");
    EXPECT_EQ(r.resolve("late.tga", tmp_dir), tmp_dir / "late.tga");
}

TEST_F(PathResolverTest, NotFoundCarriesBasenameAndDir) {
    assets::PathResolver r;
    try {
        r.resolve("missing.tga", tmp_dir);
        FAIL() << "expected throw";
    } catch (const assets::TextureNotFound& e) {
        EXPECT_EQ(e.basename(), "missing.tga");
        EXPECT_EQ(e.searched_dir(), tmp_dir);
    }
}

// BC bridge NIFs (e.g. DBridge) reference some textures with a leading
// subpath like "DBridge/floor lm.tga" while others in the same NIF use
// bare names. The actual files live flat in the configured search_dir.
// The resolver strips any leading directory component from the basename
// before doing the case-insensitive filename lookup.
TEST_F(PathResolverTest, StripsLeadingSubpathFromBasename) {
    create_file(tmp_dir / "floor lm.tga");
    assets::PathResolver r;
    EXPECT_EQ(r.resolve("DBridge/floor lm.tga", tmp_dir),
              tmp_dir / "floor lm.tga");
}

TEST_F(PathResolverTest, StripsSubpathAndAppendsTga) {
    create_file(tmp_dir / "hull.tga");
    assets::PathResolver r;
    EXPECT_EQ(r.resolve("DBridge/hull", tmp_dir), tmp_dir / "hull.tga");
}
