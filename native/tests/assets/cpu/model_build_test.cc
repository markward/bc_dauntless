#include <gtest/gtest.h>
#include "model_build.h"

#include <nif/block.h>

#include <cmath>
#include <filesystem>
#include <unistd.h>

namespace fs = std::filesystem;

namespace {

// Stubs return zero IDs so destructors short-circuit (no GL context here).
assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(
        /*vao=*/0, /*vbo=*/0, /*ebo=*/0,
        static_cast<std::uint32_t>(cpu.indices.size()),
        cpu.material_index, cpu.node_index);
}

class ModelBuildTest : public ::testing::Test {
protected:
    fs::path tmp_dir;
    assets::PathResolver resolver;

    void SetUp() override {
        auto base = fs::temp_directory_path() / "assets-mb";
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

    nif::File file_with_property_on_parent_node() {
        nif::File f;
        // Block 0: root NiNode with NO properties; child_link -> mid id 10
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {10};
        f.blocks.push_back(root);
        f.block_ids.push_back(0);

        // Block 1: mid NiNode that carries a NiMaterialProperty link.
        // child_link -> NiTriShape (id 20). property_link -> 30.
        nif::NiNode mid;
        mid.av.obj.name = "Mid";
        mid.child_links = {20};
        mid.av.property_links = {30};
        f.blocks.push_back(mid);
        f.block_ids.push_back(10);

        // Block 2: NiTriShape (id 20) with EMPTY property_links —
        // must inherit from Mid.
        nif::NiTriShape tri;
        tri.av.obj.name = "ChildShape";
        tri.data_link = 40;
        f.blocks.push_back(tri);
        f.block_ids.push_back(20);

        // Block 3: NiMaterialProperty (id 30) with distinguishable colors.
        nif::NiMaterialProperty mp;
        mp.diffuse = {0.25f, 0.5f, 0.75f};
        f.blocks.push_back(mp);
        f.block_ids.push_back(30);

        // Block 4: NiTriShapeData (id 40)
        nif::NiTriShapeData d;
        d.num_vertices = 3;
        d.has_vertices = true;
        d.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
        d.has_uv = true;
        d.uv_sets.push_back({{0, 0}, {1, 0}, {0, 1}});
        d.num_triangles = 1;
        d.triangles.push_back({0, 1, 2});
        f.blocks.push_back(d);
        f.block_ids.push_back(40);

        return f;
    }

    nif::File trivial_file_with_one_trishape() {
        nif::File f;
        // Block 0: root NiNode, child_link -> 1
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);
        // Block 1: NiTriShape, data_link -> 2
        nif::NiTriShape tri;
        tri.av.obj.name = "Saucer";
        tri.data_link = 2;
        f.blocks.push_back(tri);
        // Block 2: NiTriShapeData
        nif::NiTriShapeData d;
        d.num_vertices = 3;
        d.has_vertices = true;
        d.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
        d.has_uv = true;
        d.uv_sets.push_back({{0, 0}, {1, 0}, {0, 1}});
        d.num_triangles = 1;
        d.triangles.push_back({0, 1, 2});
        f.blocks.push_back(d);
        return f;
    }

    // A small top quad (z=0, normal +z, x/y in [0,10]) over a larger bottom
    // quad (z=-1, normal -z, x/y in [-5,15]). A ray straight down from a top
    // vertex lands in the bottom's interior at thickness 1 -> high crushability;
    // bottom corners cast up and miss the smaller top quad -> no_hit_value.
    // Mirrors the crushability_bake unit-test geometry.
    nif::File facing_quads_file() {
        nif::File f;
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);

        nif::NiTriShape tri;
        tri.av.obj.name = "Hull";
        tri.data_link = 2;
        f.blocks.push_back(tri);

        nif::NiTriShapeData d;
        d.num_vertices = 8;
        d.has_vertices = true;
        d.vertices = {
            {0, 0, 0}, {10, 0, 0}, {10, 10, 0}, {0, 10, 0},        // top
            {-5, -5, -1}, {15, -5, -1}, {15, 15, -1}, {-5, 15, -1}, // bottom
        };
        d.has_normals = true;
        d.normals = {
            {0, 0, 1}, {0, 0, 1}, {0, 0, 1}, {0, 0, 1},
            {0, 0, -1}, {0, 0, -1}, {0, 0, -1}, {0, 0, -1},
        };
        d.has_uv = true;
        d.uv_sets.push_back({
            {0, 0}, {1, 0}, {1, 1}, {0, 1},
            {0, 0}, {1, 0}, {1, 1}, {0, 1},
        });
        d.num_triangles = 4;
        d.triangles = {{0, 1, 2}, {0, 2, 3}, {4, 5, 6}, {4, 6, 7}};
        f.blocks.push_back(d);
        return f;
    }

    assets::detail::ModelBuildContext make_ctx() {
        assets::detail::ModelBuildContext ctx;
        ctx.resolver = &resolver;
        ctx.texture_search_paths = {tmp_dir};
        ctx.texture_uploader = stub_texture;
        ctx.mesh_uploader = stub_mesh;
        return ctx;
    }
};

}  // namespace

TEST_F(ModelBuildTest, EmptyNifThrowsModelBuildError) {
    nif::File f;
    EXPECT_THROW(
        assets::detail::build_model(f, make_ctx()),
        assets::detail::ModelBuildError);
}

TEST_F(ModelBuildTest, TrivialFileProducesModel) {
    auto f = trivial_file_with_one_trishape();
    auto model = assets::detail::build_model(f, make_ctx());
    EXPECT_FALSE(model.nodes.empty());
    EXPECT_EQ(model.meshes.size(), 1u);
    EXPECT_EQ(model.materials.size(), 1u);
    EXPECT_EQ(model.textures.size(), 0u);
    EXPECT_EQ(model.skeleton.bones.size(), 0u);
    EXPECT_EQ(model.animations.size(), 0u);
    EXPECT_EQ(model.meshes[0].material_index(), 0);
}

TEST_F(ModelBuildTest, NodeAttachmentRecordsMeshIndex) {
    auto f = trivial_file_with_one_trishape();
    auto model = assets::detail::build_model(f, make_ctx());

    // Find the Root node — should have mesh 0 attached
    int root_node = -1;
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        if (model.nodes[i].name == "Root") {
            root_node = static_cast<int>(i);
            break;
        }
    }
    ASSERT_NE(root_node, -1);
    ASSERT_EQ(model.nodes[root_node].meshes.size(), 1u);
    EXPECT_EQ(model.nodes[root_node].meshes[0], 0);
}

TEST_F(ModelBuildTest, ChildShapeInheritsParentNodeProperty) {
    auto f = file_with_property_on_parent_node();
    auto model = assets::detail::build_model(f, make_ctx());
    ASSERT_EQ(model.materials.size(), 1u);
    EXPECT_FLOAT_EQ(model.materials[0].diffuse.x, 0.25f);
    EXPECT_FLOAT_EQ(model.materials[0].diffuse.y, 0.5f);
    EXPECT_FLOAT_EQ(model.materials[0].diffuse.z, 0.75f);
}

TEST_F(ModelBuildTest, ShipModelGetsBakedCrushability) {
    auto f = facing_quads_file();
    auto ctx = make_ctx();
    ctx.keep_cpu_data = true;  // ships retain CPU data; the bake runs for them
    auto model = assets::detail::build_model(f, ctx);

    ASSERT_FALSE(model.meshes.empty());
    const auto& cpu = model.meshes[0].cpu_data();
    ASSERT_TRUE(cpu.has_value());
    ASSERT_EQ(cpu->vertices.size(), 8u);

    // The bake must have changed at least one vertex away from the 0.5 default.
    bool any_non_default = false;
    for (const auto& v : cpu->vertices) {
        if (std::abs(v.crushability - 0.5f) > 1e-4f) any_non_default = true;
    }
    EXPECT_TRUE(any_non_default) << "bake_crushability did not run at load";

    // Top-quad vertices (0..3) hit the overhanging bottom at thickness 1 -> thin
    // -> crushability above the 0.5 fallback.
    for (int i = 0; i < 4; ++i) {
        EXPECT_GT(cpu->vertices[i].crushability, 0.5f)
            << "top vertex " << i << " should bake as thin/crushable";
    }
}

TEST_F(ModelBuildTest, NonRetainedModelHasNoCpuData) {
    // keep_cpu_data=false (the make_ctx default): no CPU data retained AND the
    // bake is skipped. We can't read crushability without cpu_data, so this
    // test just confirms the non-retained path still builds a model cleanly.
    auto f = facing_quads_file();
    auto model = assets::detail::build_model(f, make_ctx());  // keep_cpu_data=false
    ASSERT_FALSE(model.meshes.empty());
    EXPECT_FALSE(model.meshes[0].cpu_data().has_value());
}
