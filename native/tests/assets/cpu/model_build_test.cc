#include <gtest/gtest.h>
#include "model_build.h"

#include <nif/block.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>
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

    // Root node -> child node translated to (100, 0, 0) -> a NiTriShape whose
    // verts sit near the CHILD's origin ((0,0,0),(1,0,0),(0,1,0)). The
    // node->model bake must push the sampled surface points to ~(100, *, *),
    // proving they're in MODEL space, not node-local (which would be ~origin).
    nif::File file_with_translated_child_shape() {
        nif::File f;
        // Block 0: root NiNode -> child node (block 1)
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);
        f.block_ids.push_back(0);

        // Block 1: child NiNode translated +100 in X -> shape (block 2)
        nif::NiNode child;
        child.av.obj.name = "Offset";
        child.av.translation = {100.0f, 0.0f, 0.0f};
        child.child_links = {2};
        f.blocks.push_back(child);
        f.block_ids.push_back(1);

        // Block 2: NiTriShape parented to the translated child
        nif::NiTriShape sh;
        sh.av.obj.name = "OffsetMesh";
        sh.data_link = 3;
        f.blocks.push_back(sh);
        f.block_ids.push_back(2);

        // Block 3: data — verts near node origin
        nif::NiTriShapeData d;
        d.num_vertices = 3;
        d.has_vertices = true;
        d.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
        d.num_triangles = 1;
        d.triangles.push_back({0, 1, 2});
        f.blocks.push_back(d);
        f.block_ids.push_back(3);

        return f;
    }

    // Root -> NiTriShape carrying a NiMaterialProperty + a NiTextureProperty
    // whose external NiImage is `hull_ID.tga` (a registry-style name containing
    // "ID"). The image binds to the material's Base stage. Used to exercise the
    // BC ReplaceTexture swap. Identity link IDs (no block_ids) so links == index.
    nif::File file_with_textured_shape() {
        nif::File f;
        // Block 0: root NiNode -> shape (1)
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);
        // Block 1: NiTriShape, data (2), properties material(3) + texture(4)
        nif::NiTriShape tri;
        tri.av.obj.name = "Saucer";
        tri.data_link = 2;
        tri.av.property_links = {3, 4};
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
        // Block 3: NiMaterialProperty
        nif::NiMaterialProperty mp;
        f.blocks.push_back(mp);
        // Block 4: NiTextureProperty -> image (5)
        nif::NiTextureProperty tex;
        tex.image_link = 5;
        f.blocks.push_back(tex);
        // Block 5: external NiImage named with a registry "ID" substring.
        nif::NiImage img;
        img.use_external = 1;
        img.file_name = "hull_ID.tga";
        f.blocks.push_back(img);
        return f;
    }

    // Two textured shapes: "Saucer" bound to `hull_ID.tga` (uppercase registry
    // tag) and "Bridge" bound to `hull_bridge.tga` (lowercase "id" inside
    // "bridge"). A case-sensitive "ID" swap must touch ONLY the saucer; a
    // case-fold would wrongly paint the registry onto the bridge too (the real
    // Galaxy has `Ent-D_topdish_ID_glow.tga` AND `Ent-D_Bridge-n-Stuff_glow.tga`).
    nif::File file_with_id_and_bridge_shapes() {
        nif::File f;
        nif::NiNode root;               // block 0
        root.av.obj.name = "Root";
        root.child_links = {1, 6};
        f.blocks.push_back(root);

        auto add_textured_shape = [&](const char* shape_name,
                                      std::uint32_t data, std::uint32_t matp,
                                      std::uint32_t texp, std::uint32_t img,
                                      const char* tga) {
            nif::NiTriShape tri;
            tri.av.obj.name = shape_name;
            tri.data_link = data;
            tri.av.property_links = {matp, texp};
            f.blocks.push_back(tri);
            nif::NiTriShapeData d;
            d.num_vertices = 3;
            d.has_vertices = true;
            d.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
            d.has_uv = true;
            d.uv_sets.push_back({{0, 0}, {1, 0}, {0, 1}});
            d.num_triangles = 1;
            d.triangles.push_back({0, 1, 2});
            f.blocks.push_back(d);
            f.blocks.push_back(nif::NiMaterialProperty{});
            nif::NiTextureProperty tex;
            tex.image_link = img;
            f.blocks.push_back(tex);
            nif::NiImage im;
            im.use_external = 1;
            im.file_name = tga;
            f.blocks.push_back(im);
        };
        // blocks 1..5 (Saucer) and 6..10 (Bridge), identity link ids.
        add_textured_shape("Saucer", 2, 3, 4, 5, "hull_ID.tga");
        add_textured_shape("Bridge", 7, 8, 9, 10, "hull_bridge.tga");
        return f;
    }

    // Minimal valid 2x1 24-bit uncompressed TGA (see texture_decode_test).
    static std::vector<std::uint8_t> valid_tga() {
        return {0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1, 0, 24, 0,
                0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00};
    }
    void write_tga(const std::string& name) {
        auto bytes = valid_tga();
        std::ofstream out(tmp_dir / name, std::ios::binary);
        out.write(reinterpret_cast<const char*>(bytes.data()),
                  static_cast<std::streamsize>(bytes.size()));
    }

    // Index of the sole material's Base-stage texture, or -2 if no material.
    static int base_texture_index(const assets::Model& m) {
        if (m.materials.empty()) return -2;
        return base_index_of(m, 0);
    }
    // Base-stage texture index for material `i` (-2 if out of range).
    static int base_index_of(const assets::Model& m, std::size_t i) {
        if (i >= m.materials.size()) return -2;
        return m.materials[i]
            .stages[static_cast<std::size_t>(
                assets::Material::StageSlot::Base)]
            .texture_index;
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

// Surface points must be a non-empty sample for VFX anchoring, and the hidden
// shape must contribute none (it's skipped before sampling).
TEST_F(ModelBuildTest, SurfacePointsArePopulated) {
    auto f = trivial_file_with_one_trishape();
    auto model = assets::detail::build_model(f, make_ctx());
    EXPECT_FALSE(model.surface_points.empty());
}

// The sampled surface points must be in MODEL space: a shape parented to a node
// translated to (100,0,0) must produce points clustered near x≈100, NOT near
// the node-local origin. This is the regression guard against "all points at
// the origin" (which would re-cluster VFX at the ship core).
TEST_F(ModelBuildTest, SurfacePointsAreModelSpace) {
    auto f = file_with_translated_child_shape();
    auto model = assets::detail::build_model(f, make_ctx());
    ASSERT_FALSE(model.surface_points.empty());
    // Every sampled vert's model-space X should be in [100, 101] (verts are
    // 0..1 in node-local X, plus the node's +100 translation).
    for (const auto& p : model.surface_points) {
        EXPECT_GE(p.x, 99.5f) << "surface point not pushed by node->model bake";
        EXPECT_LE(p.x, 101.5f);
    }
}

// --- Federation registry / hull-name texture swap (BC ReplaceTexture) -------

// Baseline: with no replacements the textured shape binds its lone image to the
// Base stage (index 0), and exactly one texture is loaded.
TEST_F(ModelBuildTest, NoReplacementBindsOriginalTexture) {
    write_tga("hull_ID.tga");
    auto f = file_with_textured_shape();
    auto model = assets::detail::build_model(f, make_ctx());
    EXPECT_EQ(model.textures.size(), 1u);
    EXPECT_EQ(base_texture_index(model), 0);
}

// A shape's external NiImage that cannot be resolved on disk must NOT abort the
// whole model build. Aborting skips the ship entirely (invisible hull,
// GetRadius()==0, targeting reticle collapsed to a point). Instead a visible
// magenta/black checkerboard is substituted so geometry always renders.
TEST_F(ModelBuildTest, MissingExternalTextureFallsBackToCheckerboard) {
    // Deliberately do NOT write hull_ID.tga to tmp_dir.
    auto f = file_with_textured_shape();
    ASSERT_NO_THROW(assets::detail::build_model(f, make_ctx()));
    auto model = assets::detail::build_model(f, make_ctx());
    // The checkerboard is a real registered texture, bound to the Base stage.
    EXPECT_EQ(model.textures.size(), 1u);
    EXPECT_EQ(base_texture_index(model), 0);
}

// A replacement whose old-substring matches the NIF texture's basename appends
// the new texture and repoints the material stage to it.
TEST_F(ModelBuildTest, MatchingReplacementRepointsStage) {
    write_tga("hull_ID.tga");
    write_tga("Dauntless.tga");
    auto f = file_with_textured_shape();
    auto ctx = make_ctx();
    ctx.texture_replacements.push_back(
        {"ID", (tmp_dir / "Dauntless.tga").string()});
    auto model = assets::detail::build_model(f, ctx);

    // One appended texture; Base stage now points at it (not the original 0).
    ASSERT_EQ(model.textures.size(), 2u);
    EXPECT_EQ(base_texture_index(model), 1);
}

// A replacement matching no texture leaves the model byte-for-byte as if no
// replacement were requested (warn-and-skip, never crash a spawn).
TEST_F(ModelBuildTest, NonMatchingReplacementLeavesModelUntouched) {
    write_tga("hull_ID.tga");
    write_tga("Dauntless.tga");
    auto f = file_with_textured_shape();
    auto ctx = make_ctx();
    ctx.texture_replacements.push_back(
        {"NOPE", (tmp_dir / "Dauntless.tga").string()});
    auto model = assets::detail::build_model(f, ctx);

    EXPECT_EQ(model.textures.size(), 1u);
    EXPECT_EQ(base_texture_index(model), 0);
}

// A matching old-substring but an unloadable replacement path must also leave
// the model untouched rather than throwing.
TEST_F(ModelBuildTest, MissingReplacementFileLeavesModelUntouched) {
    write_tga("hull_ID.tga");
    auto f = file_with_textured_shape();
    auto ctx = make_ctx();
    ctx.texture_replacements.push_back(
        {"ID", (tmp_dir / "does_not_exist.tga").string()});
    auto model = assets::detail::build_model(f, ctx);

    EXPECT_EQ(model.textures.size(), 1u);
    EXPECT_EQ(base_texture_index(model), 0);
}

// The match is CASE-SENSITIVE: a "ID" swap repoints only `hull_ID.tga`
// (uppercase), never `hull_bridge.tga` (lowercase "id" in "bridge"). Guards the
// real-Galaxy bug where a case-fold painted the registry onto the bridge module.
TEST_F(ModelBuildTest, ReplacementMatchIsCaseSensitive) {
    write_tga("hull_ID.tga");
    write_tga("hull_bridge.tga");
    write_tga("Dauntless.tga");
    auto f = file_with_id_and_bridge_shapes();
    auto ctx = make_ctx();
    ctx.texture_replacements.push_back(
        {"ID", (tmp_dir / "Dauntless.tga").string()});
    auto model = assets::detail::build_model(f, ctx);

    ASSERT_EQ(model.materials.size(), 2u);
    // Original textures: hull_ID.tga=0 (Saucer), hull_bridge.tga=1 (Bridge).
    // Dauntless appended at 2; ONLY the Saucer's Base is repointed to it.
    const int saucer_base = base_index_of(model, 0);
    const int bridge_base = base_index_of(model, 1);
    EXPECT_EQ(saucer_base, 2) << "uppercase-ID texture must be swapped";
    EXPECT_EQ(bridge_base, 1) << "lowercase-id 'bridge' texture must be UNTOUCHED";
}
