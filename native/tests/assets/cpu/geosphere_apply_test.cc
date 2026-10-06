// native/tests/assets/cpu/geosphere_apply_test.cc
#include <assets/cache.h>
#include <assets/geosphere.h>
#include <assets/model.h>

#include <gtest/gtest.h>
#include <glm/glm.hpp>

#include <cstdint>
#include <filesystem>

#include "support/content_root.h"

namespace fs = std::filesystem;

namespace {

assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(
        /*vao=*/0, /*vbo=*/0, /*ebo=*/0,
        static_cast<std::uint32_t>(cpu.indices.size()),
        cpu.material_index, cpu.node_index);
}

assets::AssetCache::Config cpu_config() {
    assets::AssetCache::Config cfg;
    cfg.texture_uploader = stub_texture;
    cfg.mesh_uploader = stub_mesh;
    cfg.keep_cpu_data = true;
    return cfg;
}

fs::path env_dir() { return test_support::game_root() / "data/Models/Environment"; }

}  // namespace

TEST(ApplyGeosphere, StockPlanetGetsFourLodsAroundTheMeasuredCenter) {
    const fs::path nif = env_dir() / "IcePlanet.NIF";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    assets::AssetCache cache(cpu_config());
    auto h = cache.load(nif, std::vector<fs::path>{env_dir()}, {}, {}, 1.0f, /*geosphere=*/true);
    ASSERT_TRUE(h->sphere_map.has_value());
    const auto& sm = *h->sphere_map;
    EXPECT_NEAR(sm.center_body.x, -0.736648f, 1e-3f);
    EXPECT_NEAR(sm.center_body.y, 0.368324f, 1e-3f);
    EXPECT_NEAR(sm.center_body.z, 0.0f, 1e-3f);
    EXPECT_NEAR(sm.radius, 90.0099f, 1e-2f);
    ASSERT_EQ(h->meshes.size(), 1u);
    EXPECT_EQ(sm.mesh_index, 0);
    // BC's own mesh is kept, untouched, in meshes[] (AABB / ray trace / other passes).
    EXPECT_EQ(h->meshes[0].index_count(), 1280u * 3u);
    for (std::size_t i = 0; i < 4; ++i) {
        const int level = assets::kGeosphereLevels[i];
        EXPECT_EQ(sm.lods[i].index_count(), 20u * (1u << (2 * level)) * 3u) << i;
        EXPECT_EQ(sm.lods[i].material_index(), h->meshes[0].material_index());
        EXPECT_EQ(sm.lods[i].node_index(), h->meshes[0].node_index());
    }
}

TEST(ApplyGeosphere, PlainLoadHasNoSphereMapAndIsADistinctHandle) {
    const fs::path nif = env_dir() / "IcePlanet.NIF";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    assets::AssetCache cache(cpu_config());
    auto plain = cache.load(nif, std::vector<fs::path>{env_dir()}, {}, {}, 1.0f, false);
    auto geo   = cache.load(nif, std::vector<fs::path>{env_dir()}, {}, {}, 1.0f, true);
    EXPECT_FALSE(plain->sphere_map.has_value());
    EXPECT_TRUE(geo->sphere_map.has_value());
    EXPECT_NE(plain.get(), geo.get());
}

TEST(ApplyGeosphere, LeavesNonSphereUntouched) {
    const fs::path nif = test_support::game_root() / "data/Models/Ships/Galaxy/Galaxy.nif";
    const fs::path tex = test_support::game_root() / "data/Models/SharedTextures/FedShips/High";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    assets::AssetCache cache(cpu_config());
    auto h = cache.load(nif, std::vector<fs::path>{tex}, {}, {}, 1.0f, true);
    EXPECT_FALSE(h->sphere_map.has_value());
}

TEST(ApplyGeosphere, LeavesMultiMeshModelUntouched) {
    // Build a stock planet model, then add a second mesh to it: the gate
    // requires exactly one mesh.
    const fs::path nif = env_dir() / "IcePlanet.NIF";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    assets::AssetCache cache(cpu_config());
    auto h = cache.load(nif, std::vector<fs::path>{env_dir()}, {}, {}, 1.0f, false);
    assets::Model m;   // a fresh model with two copies of the planet's CPU mesh
    m.nodes = h->nodes;
    m.root_node = h->root_node;
    for (int k = 0; k < 2; ++k) {
        assets::Mesh mesh = stub_mesh(*h->meshes[0].cpu_data());
        mesh.set_cpu_data(*h->meshes[0].cpu_data());
        m.meshes.push_back(std::move(mesh));
    }
    EXPECT_FALSE(assets::apply_geosphere(m, stub_mesh, true));
    EXPECT_FALSE(m.sphere_map.has_value());
}
