#include <gtest/gtest.h>

#include <assets/model_compose.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/skeleton.h>
#include <assets/texture.h>

namespace {

// Minimal body Model: a 2-bone skeleton (root + "Bip01 Head"), one node, one
// material, one texture, and one already-uploaded(-stub) mesh with cpu_data.
assets::Model make_body() {
    assets::Model m;

    assets::Bone root;
    root.name = "Bip01";
    root.parent_index = -1;
    assets::Bone head;
    head.name = "Bip01 Head";
    head.parent_index = 0;
    m.skeleton.bones = {root, head};
    m.skeleton.root_bone_index = 0;

    assets::Node node;
    node.name = "Bip01";
    node.parent_index = -1;
    m.nodes = {node};
    m.root_node = 0;

    m.textures.emplace_back(/*id=*/0, 1, 1, false);  // body base texture
    m.materials.emplace_back();                       // body material

    // One body mesh with cpu_data (GL handles 0 — fine for CPU-only test).
    assets::MeshCpu body_cpu;
    body_cpu.vertices.resize(3);
    body_cpu.indices = {0, 1, 2};
    body_cpu.material_index = 0;
    body_cpu.node_index = 0;
    assets::Mesh body_mesh(/*vao=*/0, /*vbo=*/0, /*ebo=*/0, 3,
                           body_cpu.material_index, body_cpu.node_index);
    body_mesh.set_cpu_data(body_cpu);
    m.meshes.push_back(std::move(body_mesh));
    m.nodes[0].meshes.push_back(0);

    return m;
}

// Minimal head Model: one mesh (cpu_data), one material whose Base stage points
// at the head's single texture (index 0 within the head).
assets::Model make_head() {
    assets::Model m;

    m.textures.emplace_back(/*id=*/0, 1, 1, false);  // head texture

    assets::Material mat;
    mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)]
        .texture_index = 0;  // index into head.textures
    m.materials.push_back(mat);

    assets::MeshCpu head_cpu;
    head_cpu.vertices.resize(4);
    // Pre-fill with bogus bone bindings to prove graft overwrites them.
    for (auto& v : head_cpu.vertices) {
        v.bone_indices = {9, 9, 9, 9};
        v.bone_weights = {1, 2, 3, 4};
    }
    head_cpu.indices = {0, 1, 2, 0, 2, 3};
    head_cpu.material_index = 0;  // index into head.materials
    head_cpu.node_index = -1;
    assets::Mesh head_mesh(/*vao=*/0, /*vbo=*/0, /*ebo=*/0, 6,
                           head_cpu.material_index, head_cpu.node_index);
    head_mesh.set_cpu_data(head_cpu);
    m.meshes.push_back(std::move(head_mesh));

    assets::Node node;
    node.name = "head_root";
    m.nodes = {node};
    m.root_node = 0;
    m.nodes[0].meshes.push_back(0);

    return m;
}

}  // namespace

TEST(GraftHeadCpu, BindsGraftedVerticesToAttachBoneRigid) {
    assets::Model body = make_body();
    assets::Model head = make_head();
    const std::size_t head_tex_count = head.textures.size();
    const std::size_t head_mat_count = head.materials.size();

    const std::size_t body_tex_before = body.textures.size();   // 1
    const std::size_t body_mat_before = body.materials.size();  // 1

    int node_index = -999;
    std::vector<assets::MeshCpu> grafted =
        assets::graft_head_cpu(body, head, "Bip01 Head", &node_index);

    ASSERT_EQ(grafted.size(), 1u);

    // Attach bone is index 1 ("Bip01 Head").
    const int kAttachBone = 1;
    for (const auto& v : grafted[0].vertices) {
        EXPECT_EQ(v.bone_indices.x, kAttachBone);
        EXPECT_EQ(v.bone_indices.y, 0);
        EXPECT_EQ(v.bone_indices.z, 0);
        EXPECT_EQ(v.bone_indices.w, 0);
        EXPECT_EQ(v.bone_weights.x, 255);
        EXPECT_EQ(v.bone_weights.y, 0);
        EXPECT_EQ(v.bone_weights.z, 0);
        EXPECT_EQ(v.bone_weights.w, 0);
    }

    // Head texture appended after the body's.
    EXPECT_EQ(body.textures.size(), body_tex_before + head_tex_count);
    // Head material appended.
    ASSERT_EQ(body.materials.size(), body_mat_before + head_mat_count);

    // The grafted mesh references the newly-appended material.
    EXPECT_EQ(grafted[0].material_index,
              static_cast<int>(body_mat_before));  // 1

    // The appended material's Base stage texture_index was offset by the
    // original body texture count.
    const auto base = static_cast<std::size_t>(assets::Material::StageSlot::Base);
    EXPECT_EQ(body.materials[body_mat_before].stages[base].texture_index,
              static_cast<int>(body_tex_before) + 0);  // 1

    // The grafted mesh is attached to a real body node.
    EXPECT_GE(node_index, 0);
    EXPECT_EQ(grafted[0].node_index, node_index);
}

TEST(GraftHeadCpu, MissingBoneLeavesBodyUnchanged) {
    assets::Model body = make_body();
    assets::Model head = make_head();

    const std::size_t meshes_before = body.meshes.size();
    const std::size_t tex_before = body.textures.size();
    const std::size_t mat_before = body.materials.size();

    std::vector<assets::MeshCpu> grafted =
        assets::graft_head_cpu(body, head, "Bip01 NoSuchBone");

    EXPECT_TRUE(grafted.empty());
    EXPECT_EQ(body.meshes.size(), meshes_before);
    EXPECT_EQ(body.textures.size(), tex_before);
    EXPECT_EQ(body.materials.size(), mat_before);
}
