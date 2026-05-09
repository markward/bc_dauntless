#include <gtest/gtest.h>
#include <assets/cache.h>
#include <glad/glad.h>

#include "gl_fixture.h"

#include <filesystem>

namespace fs = std::filesystem;

namespace {

fs::path resolve_or_main_repo(const fs::path& rel) {
    fs::path p = fs::path(OPEN_STBC_PROJECT_ROOT) / rel;
    if (fs::exists(p)) return p;
    return fs::path("/Users/mward/Documents/Projects/open_stbc") / rel;
}

}  // namespace

class ModelSmokeTest : public assets_test::GLContext {};

TEST_F(ModelSmokeTest, LoadsGalaxyEndToEnd) {
    auto galaxy = resolve_or_main_repo("game/data/Models/Ships/Galaxy/Galaxy.nif");
    auto fed_high = resolve_or_main_repo("game/data/Models/SharedTextures/FedShips/High");
    if (!fs::exists(galaxy) || !fs::exists(fed_high))
        GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache;  // default config: real GL uploaders
    auto model = cache.load(galaxy, fed_high);

    ASSERT_NE(model, nullptr);
    EXPECT_GT(model->meshes.size(), 0u);
    EXPECT_GT(model->materials.size(), 0u);
    EXPECT_GT(model->textures.size(), 0u);
    EXPECT_FALSE(model->nodes.empty());
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));

    for (auto& tex : model->textures) {
        EXPECT_NE(tex.id(), 0u);
        EXPECT_TRUE(glIsTexture(tex.id()));
    }
    for (auto& m : model->meshes) {
        EXPECT_NE(m.vao(), 0u);
        EXPECT_TRUE(glIsVertexArray(m.vao()));
    }
}
