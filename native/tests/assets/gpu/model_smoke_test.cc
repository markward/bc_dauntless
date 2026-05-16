#include <gtest/gtest.h>
#include <assets/cache.h>
#include <assets/material.h>
#include <glad/glad.h>

#include "gl_fixture.h"

#include <filesystem>

namespace fs = std::filesystem;

class ModelSmokeTest : public assets_test::GLContext {};

TEST_F(ModelSmokeTest, LoadsGalaxyEndToEnd) {
    fs::path root = OPEN_STBC_PROJECT_ROOT;
    fs::path galaxy   = root / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    fs::path fed_high = root / "game/data/Models/SharedTextures/FedShips/High";
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

    // At least one material's Base stage must reference a real texture.
    // Pre-2026-05-09 a link-ID-vs-block-index mismatch in load_all_textures
    // caused every material to come back with texture_index == -1, so the
    // renderer rendered all BC ships untextured (white-fallback). The
    // earlier assertions above all passed under that bug because they
    // didn't check materials → textures linkage.
    int materials_with_base_texture = 0;
    for (auto& mat : model->materials) {
        const auto& base =
            mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)];
        if (base.texture_index >= 0 &&
            base.texture_index < static_cast<int>(model->textures.size())) {
            ++materials_with_base_texture;
        }
    }
    EXPECT_GT(materials_with_base_texture, 0)
        << "no material on the Galaxy resolves a Base-stage texture; "
           "load_all_textures' map keys are likely out of sync with the NiImage link IDs";
}

// Regression fixture: pin Galaxy's observable material count and per-
// material Base-stage texture-index identity. Catches silent
// regressions when the property-link inheritance walk lands. If this
// test starts failing, the inheritance walk has changed Galaxy's
// rendering — investigate before allowing the change. (Ship sweep done
// in Task 1 of the bridge-lighting-materials plan confirmed Galaxy
// uses 100% direct property_links so the walk should be a no-op for
// it, but this guards against subtle ordering changes too.)
class GalaxyRegressionFixture : public assets_test::GLContext {};

TEST_F(GalaxyRegressionFixture, MaterialCountAndBaseTextureIdentity) {
    fs::path root = OPEN_STBC_PROJECT_ROOT;
    fs::path galaxy   = root / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    fs::path fed_high = root / "game/data/Models/SharedTextures/FedShips/High";
    if (!fs::exists(galaxy) || !fs::exists(fed_high))
        GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache;
    auto model = cache.load(galaxy, fed_high);
    ASSERT_NE(model, nullptr);

    const std::size_t mat_count = model->materials.size();
    std::vector<int> base_indices;
    for (const auto& mat : model->materials) {
        base_indices.push_back(
            mat.stages[static_cast<std::size_t>(
                assets::Material::StageSlot::Base)].texture_index);
    }

    std::fprintf(stderr, "Galaxy materials=%zu base_indices=[",
                 mat_count);
    for (std::size_t i = 0; i < base_indices.size(); ++i) {
        std::fprintf(stderr, "%s%d", i ? "," : "", base_indices[i]);
    }
    std::fprintf(stderr, "]\n");

    // Pinned values captured 2026-05-15 against main af5c616.
    EXPECT_EQ(mat_count, 10u);
    const std::vector<int> expected_bases = {0, 2, 4, 5, 6, 7, 8, 9, 10, 11};
    EXPECT_EQ(base_indices, expected_bases);
}

// End-to-end integration: DBridge.NIF should produce 145 materials, of
// which 17 are tagged Material::lightmap_pass=true and 128 are not.
// This exercises both the property-link inheritance walk (Task 3) and
// the lightmap-pass filename predicate (Task 4) against real assets.
class DBridgeIntegration : public assets_test::GLContext {};

TEST_F(DBridgeIntegration, MaterialLightmapPassDistribution) {
    fs::path root = OPEN_STBC_PROJECT_ROOT;
    fs::path nif = root / "game/data/Models/Sets/DBridge/Dbridge.NIF";
    fs::path tex = root / "game/data/Models/Sets/DBridge/High";
    if (!fs::is_regular_file(nif) || !fs::is_directory(tex)) {
        GTEST_SKIP() << "BC bridge asset not available";
    }
    assets::AssetCache cache;
    auto model = cache.load(nif, tex);
    ASSERT_NE(model, nullptr);

    int lm = 0, base_only = 0;
    int materials_with_dark = 0;
    for (const auto& m : model->materials) {
        if (m.lightmap_pass) ++lm;
        else                 ++base_only;
        const int dark_idx = m.stages[
            static_cast<std::size_t>(assets::Material::StageSlot::Dark)
        ].texture_index;
        if (dark_idx >= 0) ++materials_with_dark;
    }
    std::fprintf(stderr,
                 "DBridge: %d lightmap_pass materials, %d base-only, "
                 "%d with Dark-slot lightmap\n",
                 lm, base_only, materials_with_dark);
    EXPECT_EQ(model->materials.size(), 145u);
    // All 17 NiMultiTextureProperty shapes also inherit a diffuse via
    // NiTextureProperty; the multi-texture's lm.tga is now routed to
    // the Dark slot to preserve the diffuse in Base. lightmap_pass is
    // therefore 0 for the current asset; the renderer's two-texture
    // composite (base × dark) will handle lighting when implemented.
    EXPECT_EQ(lm, 0);
    EXPECT_EQ(base_only, 145);
    EXPECT_EQ(materials_with_dark, 17);

    // Every mesh must be attached to some node, otherwise the renderer
    // (which iterates nodes to find meshes to draw) silently drops it.
    int meshes_attached = 0;
    for (const auto& n : model->nodes) meshes_attached += n.meshes.size();
    int zero_index = 0;
    int zero_vao = 0;
    int no_material = 0;
    for (const auto& mesh : model->meshes) {
        if (mesh.index_count() == 0) ++zero_index;
        if (mesh.vao() == 0) ++zero_vao;
        if (mesh.material_index() < 0) ++no_material;
    }
    std::fprintf(stderr,
                 "DBridge: %zu meshes total, %d attached, %zu nodes; "
                 "%d zero-index, %d zero-vao, %d no-material\n",
                 model->meshes.size(), meshes_attached, model->nodes.size(),
                 zero_index, zero_vao, no_material);
    EXPECT_EQ(meshes_attached, static_cast<int>(model->meshes.size()));
}
