// Round trip through independent libraries: rock_catalogue's writer.cc
// writes glTF JSON with nlohmann_json; the engine reads it back with cgltf
// (assets::gltf::load_cpu). A writer and reader from independent libraries
// make this meaningful -- see constraints.md deviation D7.
#include <gtest/gtest.h>
#include <assets/gltf.h>
#include <rockgen/recipe.h>
#include <rockgen/shape.h>
#include <rockgen/surface.h>
#include <voxel/dvox.h>
#include <voxel/voxelize.h>
#include <writer.h>

#include "mini_recipe.h"

#include <cstdlib>
#include <filesystem>
#include <vector>

namespace fs = std::filesystem;

namespace {

std::vector<voxel::Tri> mesh_to_tris(const assets::MeshCpu& m) {
    std::vector<voxel::Tri> tris;
    for (std::size_t i = 0; i + 2 < m.indices.size(); i += 3) {
        tris.push_back({m.vertices[m.indices[i]].position,
                         m.vertices[m.indices[i + 1]].position,
                         m.vertices[m.indices[i + 2]].position});
    }
    return tris;
}

}  // namespace

TEST(Catalogue, WrittenGltfLoadsInEngineReader) {
    auto r = rockgen::parse_recipe(kMini);
    auto specs = rockgen::expand_recipe(r);
    ASSERT_FALSE(specs.empty());
    const rockgen::RockSpec& spec = specs[0];

    auto lods = rockgen::generate_rock_lods(spec);
    ASSERT_FALSE(lods.empty());
    auto surf = rockgen::generate_rock_surface(spec);
    auto vol = voxel::voxelize_tris(mesh_to_tris(lods[0]), glm::ivec3(r.volume_dims));

    const fs::path dir = fs::temp_directory_path() /
                          "rock_catalogue_writer_test" / std::to_string(::testing::UnitTest::GetInstance()->random_seed());
    std::error_code ec;
    fs::create_directories(dir, ec);

    rock_catalogue::write_png(dir / "base.png", surf.base_color);
    rock_catalogue::write_png(dir / "normal.png", surf.normal);
    ASSERT_TRUE(voxel::write_dvox(dir / "volume.dvox", vol));
    rock_catalogue::write_gltf_lod(dir, 0, lods[0], "volume.dvox", r.tool_version);

    auto scene = assets::gltf::load_cpu(dir / "lod0.gltf");
    ASSERT_EQ(scene.meshes.size(), 1u);
    EXPECT_EQ(scene.meshes[0].vertices.size(), lods[0].vertices.size());
    EXPECT_EQ(scene.meshes[0].indices.size(), lods[0].indices.size());
    ASSERT_EQ(scene.materials.size(), 1u);
    EXPECT_EQ(scene.materials[0].base_color_image, dir / "base.png");
    EXPECT_EQ(scene.materials[0].normal_image, dir / "normal.png");
    EXPECT_EQ(scene.volume, dir / "volume.dvox");
}
