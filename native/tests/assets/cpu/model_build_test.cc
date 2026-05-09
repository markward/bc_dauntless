#include <gtest/gtest.h>
#include "model_build.h"

#include <nif/block.h>

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

    assets::detail::ModelBuildContext make_ctx() {
        assets::detail::ModelBuildContext ctx;
        ctx.resolver = &resolver;
        ctx.texture_search_path = tmp_dir;
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
