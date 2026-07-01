#include <gtest/gtest.h>
#include <assets/cache.h>
#include <nif/file.h>

#include <filesystem>

namespace fs = std::filesystem;

namespace {

fs::path galaxy_path() {
    return fs::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Galaxy/Galaxy.nif";
}
fs::path fed_high_path() {
    return fs::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/SharedTextures/FedShips/High";
}
fs::path fed_medium_path() {
    return fs::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/SharedTextures/FedShips/Medium";
}
fs::path dauntless_tga_path() {
    return fs::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/SharedTextures/FedShips/High/Dauntless.tga";
}
fs::path venture_tga_path() {
    return fs::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/SharedTextures/FedShips/High/Venture.tga";
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
