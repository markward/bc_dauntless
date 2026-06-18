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

    // Root node with two NiTriShapes: one visible (flags bit0 clear) and one
    // HIDDEN (flags bit0 set, 0x0005 — exactly how BC character NIFs flag their
    // 3ds Max "Biped Object" skeleton-placeholder boxes). The hidden one must
    // never enter the built model.
    nif::File file_with_hidden_and_visible_shapes() {
        nif::File f;
        // Block 0: root NiNode, children -> 1 (visible), 3 (hidden)
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1, 3};
        f.blocks.push_back(root);
        f.block_ids.push_back(0);

        // Block 1: VISIBLE NiTriShape (flags default 0 -> bit0 clear)
        nif::NiTriShape vis;
        vis.av.obj.name = "RealMesh";
        vis.data_link = 2;
        f.blocks.push_back(vis);
        f.block_ids.push_back(1);

        // Block 2: data for the visible shape
        nif::NiTriShapeData dv;
        dv.num_vertices = 3;
        dv.has_vertices = true;
        dv.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
        dv.num_triangles = 1;
        dv.triangles.push_back({0, 1, 2});
        f.blocks.push_back(dv);
        f.block_ids.push_back(2);

        // Block 3: HIDDEN NiTriShape ("Biped Object"), flags 0x0005 (bit0 set)
        nif::NiTriShape hid;
        hid.av.obj.name = "Biped Object";
        hid.av.flags = 0x0005;
        hid.data_link = 4;
        f.blocks.push_back(hid);
        f.block_ids.push_back(3);

        // Block 4: data for the hidden shape
        nif::NiTriShapeData dh;
        dh.num_vertices = 3;
        dh.has_vertices = true;
        dh.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
        dh.num_triangles = 1;
        dh.triangles.push_back({0, 1, 2});
        f.blocks.push_back(dh);
        f.block_ids.push_back(4);

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

// BC character NIFs carry ~30 hidden "Biped Object" skeleton-placeholder shapes
// (NiAVObject flags bit0 = 0x01 set) alongside the real skinned mesh. The stock
// engine never draws hidden shapes; we must skip them at build time, otherwise
// they render as a "lego skeleton" duplicate body. Only the visible shape may
// reach model.meshes / node.meshes / model.materials.
TEST_F(ModelBuildTest, HiddenShapesAreNotBuilt) {
    auto f = file_with_hidden_and_visible_shapes();
    auto model = assets::detail::build_model(f, make_ctx());

    EXPECT_EQ(model.meshes.size(), 1u);      // only the visible RealMesh
    EXPECT_EQ(model.materials.size(), 1u);   // hidden shape's material not built

    std::size_t attached = 0;
    for (const auto& n : model.nodes) attached += n.meshes.size();
    EXPECT_EQ(attached, 1u);                  // no node references the hidden box
}
