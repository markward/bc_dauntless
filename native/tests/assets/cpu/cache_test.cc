#include <gtest/gtest.h>
#include <assets/cache.h>
#include <nif/file.h>

#include <filesystem>
#include "support/content_root.h"

#include <assets/mesh_fix.h>
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

namespace {

fs::path galaxy_path() {
    return test_support::game_root() / "data/Models/Ships/Galaxy/Galaxy.nif";
}
fs::path fed_high_path() {
    return test_support::game_root() / "data/Models/SharedTextures/FedShips/High";
}
fs::path fed_medium_path() {
    return test_support::game_root() / "data/Models/SharedTextures/FedShips/Medium";
}
fs::path dauntless_tga_path() {
    return test_support::game_root() / "data/Models/SharedTextures/FedShips/High/Dauntless.tga";
}
fs::path venture_tga_path() {
    return test_support::game_root() / "data/Models/SharedTextures/FedShips/High/Venture.tga";
}
bool game_data_present() {
    return fs::exists(galaxy_path());
}

assets::AssetCache::Config stub_config() {
    assets::AssetCache::Config cfg;
    cfg.texture_uploader = [](const assets::Image&, bool) {
        return assets::Texture(/*id=*/0, 1, 1, false);
    };
    cfg.mesh_uploader = [](assets::MeshCpu cpu) {
        return assets::Mesh(0, 0, 0,
            static_cast<std::uint32_t>(cpu.indices.size()),
            cpu.material_index, cpu.node_index);
    };
    return cfg;
}

}  // namespace

TEST(AssetCacheTest, LoadSamePathReturnsSameHandle) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache(stub_config());
    auto a = cache.load(galaxy_path(), fed_high_path());
    auto b = cache.load(galaxy_path(), fed_high_path());
    EXPECT_EQ(a.get(), b.get());
}

TEST(AssetCacheTest, DifferentSearchPathThrows) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache(stub_config());
    cache.load(galaxy_path(), fed_high_path());
    EXPECT_THROW(
        cache.load(galaxy_path(), fed_medium_path()),
        assets::AssetError);
}

TEST(AssetCacheTest, EvictDropsCachePin) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache(stub_config());
    auto handle = cache.load(galaxy_path(), fed_high_path());
    cache.evict(galaxy_path());
    // Outstanding handle still keeps the model alive.
    EXPECT_TRUE(handle != nullptr);
}

// --- Federation registry / hull-name variants (BC ReplaceTexture) -----------

// A registry replacement yields a DISTINCT model from the plain load, and swaps
// exactly one texture (the matched registry glow) -> one appended texture.
TEST(AssetCacheTest, RegistryReplacementProducesDistinctVariant) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    if (!fs::exists(dauntless_tga_path()))
        GTEST_SKIP() << "Dauntless.tga not installed";

    assets::AssetCache cache(stub_config());
    auto plain = cache.load(galaxy_path(), fed_high_path());
    std::vector<assets::TextureReplacement> reps{
        {"ID", dauntless_tga_path().string()}};
    auto variant = cache.load(galaxy_path(), {fed_high_path()}, reps);

    EXPECT_NE(plain.get(), variant.get());
    EXPECT_EQ(variant->textures.size(), plain->textures.size() + 1);
}

// Regression: BC's ReplaceTexture path OMITS the LOD subdir
// ("FedShips/Dauntless.tga" when the real file is FedShips/High/Dauntless.tga).
// The replacement must still resolve by basename against the search dirs — a
// direct open of the literal path would fail and silently skip the swap.
TEST(AssetCacheTest, RegistryReplacementResolvesBcStyleLodPath) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    if (!fs::exists(dauntless_tga_path()))
        GTEST_SKIP() << "Dauntless.tga not installed";

    assets::AssetCache cache(stub_config());
    auto plain = cache.load(galaxy_path(), fed_high_path());
    std::vector<assets::TextureReplacement> reps{
        {"ID", "Data/Models/SharedTextures/FedShips/Dauntless.tga"}};  // no /High
    auto variant = cache.load(galaxy_path(), {fed_high_path()}, reps);

    EXPECT_NE(plain.get(), variant.get());
    EXPECT_EQ(variant->textures.size(), plain->textures.size() + 1);
}

// Same NIF + same registry dedupes to one handle; a DIFFERENT registry is a
// separate handle.
TEST(AssetCacheTest, SameRegistrySharesDifferentRegistryDistinct) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    if (!fs::exists(dauntless_tga_path()) || !fs::exists(venture_tga_path()))
        GTEST_SKIP() << "shared registry textures not installed";

    assets::AssetCache cache(stub_config());
    std::vector<assets::TextureReplacement> dauntless{
        {"ID", dauntless_tga_path().string()}};
    std::vector<assets::TextureReplacement> venture{
        {"ID", venture_tga_path().string()}};

    auto a = cache.load(galaxy_path(), {fed_high_path()}, dauntless);
    auto b = cache.load(galaxy_path(), {fed_high_path()}, dauntless);
    auto c = cache.load(galaxy_path(), {fed_high_path()}, venture);

    EXPECT_EQ(a.get(), b.get());   // same registry -> shared
    EXPECT_NE(a.get(), c.get());   // different registry -> distinct
}

// --- Mesh fixes (hull name-cut fix) -----------------------------------------

namespace {
std::string file_bytes(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss; ss << in.rdbuf(); return ss.str();
}
fs::path temp_fix_dir(const char* tag) {
    auto d = fs::temp_directory_path() / (std::string("dauntless_mesh_fix_") + tag);
    fs::remove_all(d); fs::create_directories(d); return d;
}
}  // namespace

TEST(AssetCacheMeshFix, EmptyFixFileAppliesAndChangesCacheKey) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto dir = temp_fix_dir("empty");
    std::ofstream(dir / (assets::fnv1a64_hex(file_bytes(galaxy_path())) + ".json"))
        << R"({"format":1,"merges":[]})";

    assets::AssetCache plain(stub_config());
    auto cfg = stub_config();
    cfg.mesh_fix_dir = [dir] { return dir; };
    assets::AssetCache fixed(cfg);
    auto a = plain.load(galaxy_path(), fed_high_path());
    auto b = fixed.load(galaxy_path(), fed_high_path());
    // An empty merge list changes nothing visible...
    EXPECT_EQ(a->meshes.size(), b->meshes.size());
    // ...and two loads through the fixed cache share one entry.
    EXPECT_EQ(b.get(), fixed.load(galaxy_path(), fed_high_path()).get());
}

TEST(AssetCacheMeshFix, RefusedFixLoadsUnpatched) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto dir = temp_fix_dir("refused");
    std::ofstream(dir / (assets::fnv1a64_hex(file_bytes(galaxy_path())) + ".json"))
        << R"({"format":1,"merges":[{"patch":{"block":0,"name":"nope"},
              "target":{"block":1,"name":"nope"},"uvs":[],"weld":[],"normals":null}]})";
    assets::AssetCache plain(stub_config());
    auto cfg = stub_config();
    cfg.mesh_fix_dir = [dir] { return dir; };
    assets::AssetCache fixed(cfg);
    EXPECT_EQ(plain.load(galaxy_path(), fed_high_path())->meshes.size(),
              fixed.load(galaxy_path(), fed_high_path())->meshes.size());
}

TEST(AssetCacheMeshFix, MalformedFixFileLoadsUnpatched) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto dir = temp_fix_dir("malformed");
    std::ofstream(dir / (assets::fnv1a64_hex(file_bytes(galaxy_path())) + ".json")) << "{ nope";
    auto cfg = stub_config();
    cfg.mesh_fix_dir = [dir] { return dir; };
    assets::AssetCache fixed(cfg);
    EXPECT_NO_THROW(fixed.load(galaxy_path(), fed_high_path()));
}

TEST(AssetCacheMeshFix, NoFixDirConfiguredIsTodayBehaviour) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto cfg = stub_config();
    cfg.mesh_fix_dir = [] { return fs::path(); };
    assets::AssetCache c(cfg);
    EXPECT_NO_THROW(c.load(galaxy_path(), fed_high_path()));
}

// Ruling 1: one cache, with a mutable mesh_fix_dir, keys fixed and unfixed
// loads of the SAME nif_path apart. The two-cache tests above can't show
// this -- they prove each cache is internally consistent, not that a single
// cache's key changes when the fix directory's contents change underneath
// it.
TEST(AssetCacheMeshFix, OneCacheKeysFixedAndUnfixedLoadsApart) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto dir = std::make_shared<fs::path>();  // empty => no fix dir configured

    auto cfg = stub_config();
    cfg.mesh_fix_dir = [dir] { return *dir; };
    assets::AssetCache cache(cfg);

    auto a = cache.load(galaxy_path(), fed_high_path());  // handle A: unfixed

    auto fix_dir = temp_fix_dir("one_cache");
    std::ofstream(fix_dir / (assets::fnv1a64_hex(file_bytes(galaxy_path())) + ".json"))
        << R"({"format":1,"merges":[]})";
    *dir = fix_dir;

    auto b = cache.load(galaxy_path(), fed_high_path());  // handle B: fixed
    EXPECT_NE(a.get(), b.get());

    auto c = cache.load(galaxy_path(), fed_high_path());  // same fix dir again
    EXPECT_EQ(b.get(), c.get());
}
