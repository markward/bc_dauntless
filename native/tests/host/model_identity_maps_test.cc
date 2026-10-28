// native/tests/host/model_identity_maps_test.cc
//
// model_identity's per-mesh "maps" computation (spec 2026-10-09-bridge-pbr),
// tested against a hand-built assets::Model so an out-of-range
// material_index() -- which no NIF-loaded model produces, so the Python
// binding has no fixture for it -- is exercised directly instead of only by
// code review.
#include <gtest/gtest.h>

#include "model_identity_maps.h"
#include "model_build.h"

#include <assets/model.h>

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <system_error>
#include <vector>

namespace fs = std::filesystem;

namespace {

using S = assets::Material::StageSlot;

assets::Model model_with_one_material_with_roughness() {
    assets::Model model;
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(S::Roughness)].texture_index = 0;
    model.materials.push_back(mat);
    return model;
}

}  // namespace

TEST(SafeMaterialIndex, InRangeIndexPassesThrough) {
    assets::Model model = model_with_one_material_with_roughness();
    EXPECT_EQ(dauntless::safe_material_index(model, 0), 0);
}

TEST(SafeMaterialIndex, NegativeIndexStaysNegativeOne) {
    assets::Model model = model_with_one_material_with_roughness();
    EXPECT_EQ(dauntless::safe_material_index(model, -1), -1);
}

TEST(SafeMaterialIndex, IndexEqualToSizeIsOutOfRange) {
    // model.materials.size() == 1, so index 1 is one past the end --
    // material_or_default would read model.materials[1] with operator[],
    // out of bounds, if this were not clamped first.
    assets::Model model = model_with_one_material_with_roughness();
    EXPECT_EQ(dauntless::safe_material_index(model, 1), -1);
}

TEST(SafeMaterialIndex, FarOutOfRangeIndexIsClamped) {
    assets::Model model = model_with_one_material_with_roughness();
    EXPECT_EQ(dauntless::safe_material_index(model, 1000), -1);
}

TEST(SafeMaterialIndex, EmptyMaterialsListIndexZeroIsOutOfRange) {
    assets::Model model;  // model.materials is empty
    EXPECT_EQ(dauntless::safe_material_index(model, 0), -1);
}

TEST(MeshIdentityMaps, InRangeIndexReadsTheRealMaterialStages) {
    assets::Model model = model_with_one_material_with_roughness();
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, 0);
    EXPECT_TRUE(maps.roughness);
    EXPECT_FALSE(maps.metalness);
    EXPECT_FALSE(maps.normal);
}

TEST(MeshIdentityMaps, OutOfRangeIndexIsAllFalseNotAnOutOfBoundsRead) {
    // Regression test: before the bounds check was shared with
    // safe_material_index, this called assets::material_or_default(model, 1)
    // directly, which indexes model.materials[1] via operator[] with no
    // bounds check of its own -- an out-of-bounds read on a 1-element
    // vector. This pins the all-false fallback as the intended behaviour;
    // confirmed live by temporarily reverting mesh_identity_maps to the
    // unguarded call, which turned this into a read of whatever garbage
    // byte followed the vector's single element (see the task report).
    assets::Model model = model_with_one_material_with_roughness();
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, 1);
    EXPECT_FALSE(maps.roughness);
    EXPECT_FALSE(maps.metalness);
    EXPECT_FALSE(maps.normal);
}

TEST(MeshIdentityMaps, NoMaterialIndexIsAllFalse) {
    assets::Model model = model_with_one_material_with_roughness();
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, -1);
    EXPECT_FALSE(maps.roughness);
    EXPECT_FALSE(maps.metalness);
    EXPECT_FALSE(maps.normal);
}

TEST(MeshIdentityMaps, AllThreeStagesReadIndependently) {
    assets::Model model;
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(S::Roughness)].texture_index = 0;
    mat.stages[static_cast<std::size_t>(S::Metalness)].texture_index = 1;
    mat.stages[static_cast<std::size_t>(S::Bump)].texture_index = 2;
    model.materials.push_back(mat);
    const dauntless::MeshMaps maps = dauntless::mesh_identity_maps(model, 0);
    EXPECT_TRUE(maps.roughness);
    EXPECT_TRUE(maps.metalness);
    EXPECT_TRUE(maps.normal);
}

TEST(MeshIdentityMaps, ReportsAnEmissiveMap) {
    assets::Model model;
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(S::Emissive)].texture_index = 0;
    model.materials.push_back(mat);
    EXPECT_TRUE(dauntless::mesh_identity_maps(model, 0).emissive);
    EXPECT_FALSE(dauntless::mesh_identity_maps(model, -1).emissive);
    EXPECT_FALSE(dauntless::mesh_identity_maps(model_with_one_material_with_roughness(), 0).emissive);
}

// A Lottie panel's static emissive maps are set aside at load, so the stage is
// empty and the editor's glow reads "no emissive" (engine/bridge_editor/glow.py
// reads maps["emissive"]). Built through the real loader (an interior load with
// `_emissive.tga` beside the albedo), with and without the panel's `.json`.
namespace {

// Stubs return zero IDs so destructors short-circuit (no GL context here).
assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(/*vao=*/0, /*vbo=*/0, /*ebo=*/0,
                        static_cast<std::uint32_t>(cpu.indices.size()),
                        cpu.material_index, cpu.node_index);
}

// Root -> NiTriShape with a NiTextureProperty whose external NiImage is
// `panel.tga` (identity link IDs: links == block index).
nif::File file_with_textured_shape() {
    nif::File f;
    nif::NiNode root;                 // 0
    root.av.obj.name = "Root";
    root.child_links = {1};
    f.blocks.push_back(root);
    nif::NiTriShape tri;              // 1
    tri.av.obj.name = "Panel";
    tri.data_link = 2;
    tri.av.property_links = {3, 4};
    f.blocks.push_back(tri);
    nif::NiTriShapeData d;            // 2
    d.num_vertices = 3;
    d.has_vertices = true;
    d.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
    d.has_uv = true;
    d.uv_sets.push_back({{0, 0}, {1, 0}, {0, 1}});
    d.num_triangles = 1;
    d.triangles.push_back({0, 1, 2});
    f.blocks.push_back(d);
    f.blocks.push_back(nif::NiMaterialProperty{});  // 3
    nif::NiTextureProperty tex;       // 4
    tex.image_link = 5;
    f.blocks.push_back(tex);
    nif::NiImage img;                 // 5
    img.use_external = 1;
    img.file_name = "panel.tga";
    f.blocks.push_back(img);
    return f;
}

// A 2x1 uncompressed 24-bit TGA.
void write_tga(const fs::path& p) {
    const std::vector<std::uint8_t> tga = {0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1, 0, 24, 0,
                                           0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00};
    std::ofstream(p, std::ios::binary)
        .write(reinterpret_cast<const char*>(tga.data()), static_cast<std::streamsize>(tga.size()));
}

class MeshIdentityMapsLottie : public ::testing::Test {
protected:
    fs::path tmp_dir;
    assets::PathResolver resolver;

    void SetUp() override {
        const auto* info = ::testing::UnitTest::GetInstance()->current_test_info();
        tmp_dir = fs::temp_directory_path() /
                  (std::string("host-identity-maps-") + info->name() + "-" +
                   std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        fs::create_directories(tmp_dir / "mod");
        fs::create_directories(tmp_dir / "stock");
        write_tga(tmp_dir / "mod" / "panel.tga");
        write_tga(tmp_dir / "mod" / "panel_emissive.tga");
    }
    void TearDown() override {
        std::error_code ec;
        fs::remove_all(tmp_dir, ec);
    }

    // An interior load of a mod albedo: its siblings are probed beside it.
    assets::Model build() {
        assets::detail::ModelBuildContext ctx;
        ctx.resolver = &resolver;
        ctx.texture_search_paths = {tmp_dir / "mod", tmp_dir / "stock"};
        ctx.texture_uploader = stub_texture;
        ctx.mesh_uploader = stub_mesh;
        ctx.interior_sibling_policy = true;
        return assets::detail::build_model(file_with_textured_shape(), ctx);
    }
};

}  // namespace

TEST_F(MeshIdentityMapsLottie, WithoutAJsonTheEmissiveSiblingReads) {
    const assets::Model model = build();
    ASSERT_EQ(model.meshes.size(), 1u);
    EXPECT_TRUE(dauntless::mesh_identity_maps(model, model.meshes[0].material_index()).emissive);
}

TEST_F(MeshIdentityMapsLottie, AJsonBesideTheAlbedoSetsItAside) {
    std::ofstream(tmp_dir / "mod" / "panel.json") << "{}";
    const assets::Model model = build();
    ASSERT_EQ(model.meshes.size(), 1u);
    const int mi = model.meshes[0].material_index();
    ASSERT_GE(mi, 0);
    EXPECT_EQ(model.materials[static_cast<std::size_t>(mi)].panel_index, 0);
    EXPECT_FALSE(dauntless::mesh_identity_maps(model, mi).emissive);
}
