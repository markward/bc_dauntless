#include <gtest/gtest.h>

#include <assets/model_compose.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/skeleton.h>
#include <assets/texture.h>

#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <filesystem>

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

// Head Model shaped like a real BC head NIF (e.g. liu_head): a "Bip01 Head"
// node exists in the hierarchy but carries NO renderable mesh — the actual
// head/face mesh is a skinned shape parented higher up (under "Bip01 Spine1").
// A subtree-walk anchored on the "Bip01 Head" node would graft nothing.
assets::Model make_head_mesh_not_under_attach_node() {
    assets::Model m;

    m.textures.emplace_back(/*id=*/0, 1, 1, false);
    assets::Material mat;
    mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)]
        .texture_index = 0;
    m.materials.push_back(mat);

    assets::MeshCpu head_cpu;
    head_cpu.vertices.resize(4);
    head_cpu.indices = {0, 1, 2, 0, 2, 3};
    head_cpu.material_index = 0;
    assets::Mesh head_mesh(/*vao=*/0, /*vbo=*/0, /*ebo=*/0, 6,
                           head_cpu.material_index, /*node_index=*/1);
    head_mesh.set_cpu_data(head_cpu);
    m.meshes.push_back(std::move(head_mesh));

    // Node 0: "Bip01 Head" (the attach bone's node) — empty, no meshes.
    // Node 1: "Bip01 Spine1" — carries the real head mesh (index 0).
    assets::Node head_node;  head_node.name = "Bip01 Head";   head_node.parent_index = -1;
    assets::Node spine_node; spine_node.name = "Bip01 Spine1"; spine_node.parent_index = -1;
    m.nodes = {head_node, spine_node};
    m.root_node = 0;
    m.nodes[1].meshes.push_back(0);

    return m;
}

}  // namespace

// Regression: the head/face mesh of a real BC head NIF is NOT parented under
// the "Bip01 Head" node (it's a skinned shape under "Bip01 Spine1"). The graft
// must still pull it onto the body. A node-subtree walk anchored on the attach
// bone grafts nothing here and leaves the officer headless. graft_head_cpu must
// graft the head model's (visible) mesh regardless of which node it hangs off.
TEST(GraftHeadCpu, GraftsHeadMeshNotParentedUnderAttachNode) {
    assets::Model body = make_body();
    assets::Model head = make_head_mesh_not_under_attach_node();

    std::vector<assets::MeshCpu> grafted =
        assets::graft_head_cpu(body, head, "Bip01 Head");

    ASSERT_EQ(grafted.size(), 1u);  // the real head mesh, not an empty subtree

    const int kAttachBone = 1;  // body's "Bip01 Head" bone index
    for (const auto& v : grafted[0].vertices) {
        EXPECT_EQ(v.bone_indices.x, kAttachBone);
        EXPECT_EQ(v.bone_weights.x, 255);
    }
}

// Degenerate heads (no skeleton — synthetic fixtures; real BC head NIFs are
// full character templates and always carry one) keep the old rigid bind to
// the attach bone. Also covers the material/texture append plumbing.
TEST(GraftHeadCpu, RigidFallbackWhenHeadModelHasNoSkeleton) {
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

// SP3 Task 6: set_base_texture must append a new texture and repoint the Base
// stage of every material referenced by the given meshes at it. Uses a stub
// loader so no GL context / real file is needed.
TEST(SetBaseTextureCpu, RepointsBaseStageToAppendedTexture) {
    assets::Model m = make_body();  // 1 texture, 1 material, 1 mesh (mat 0)
    const std::size_t tex_before = m.textures.size();   // 1
    const auto base =
        static_cast<std::size_t>(assets::Material::StageSlot::Base);
    // Body material starts with the default Base texture_index (-1 here, since
    // make_body's material is default-constructed).
    ASSERT_EQ(m.materials[0].stages[base].texture_index, -1);

    int loader_calls = 0;
    assets::TgaTextureLoaderFn stub =
        [&](const std::filesystem::path&) -> assets::Texture {
        ++loader_calls;
        return assets::Texture(/*id=*/0, 4, 4, false);
    };

    const int mesh_indices[] = {0};
    const bool ok = assets::set_base_texture(
        m, mesh_indices, "FedRed_body.tga", stub);

    EXPECT_TRUE(ok);
    EXPECT_EQ(loader_calls, 1);
    // One texture appended.
    ASSERT_EQ(m.textures.size(), tex_before + 1);
    // Body material's Base stage now points at the newly-appended texture.
    EXPECT_EQ(m.materials[0].stages[base].texture_index,
              static_cast<int>(tex_before));  // 1
}

// An empty path is a no-op (NIF default kept); a load failure is a no-op too.
TEST(SetBaseTextureCpu, EmptyPathAndLoadFailureAreNoOps) {
    assets::Model m = make_body();
    const std::size_t tex_before = m.textures.size();
    const auto base =
        static_cast<std::size_t>(assets::Material::StageSlot::Base);
    const int orig = m.materials[0].stages[base].texture_index;

    const int mesh_indices[] = {0};

    // Empty path: loader never invoked, model untouched.
    EXPECT_FALSE(assets::set_base_texture(m, mesh_indices, "", {}));
    EXPECT_EQ(m.textures.size(), tex_before);
    EXPECT_EQ(m.materials[0].stages[base].texture_index, orig);

    // Loader throws (simulating a missing/bad TGA): model untouched, no crash.
    assets::TgaTextureLoaderFn throwing =
        [](const std::filesystem::path&) -> assets::Texture {
        throw std::runtime_error("boom");
    };
    EXPECT_FALSE(
        assets::set_base_texture(m, mesh_indices, "missing.tga", throwing));
    EXPECT_EQ(m.textures.size(), tex_before);
    EXPECT_EQ(m.materials[0].stages[base].texture_index, orig);
}

// §3.5: a bind-height mismatch between body and head templates is absorbed by
// an ALIAS BONE carrying the head's inverse bind — vertex data is never
// touched (BC never moves verts; the translation-only rebase this replaces
// moved them and was only exact for single-bone bindings). Replaces
// RebasesHeadToBodyAttachBoneBindHeight.
TEST(GraftHeadCpu, BindMismatchUsesAliasBoneAndLeavesVertsUntouched) {
    const auto base_slot =
        static_cast<std::size_t>(assets::Material::StageSlot::Base);

    // Body: "Bip01 Head" bind-world at Z = 10.
    assets::Model body;
    assets::Bone broot; broot.name = "Bip01"; broot.parent_index = -1;
    assets::Bone bhead; bhead.name = "Bip01 Head"; bhead.parent_index = 0;
    bhead.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -10.0f));
    body.skeleton.bones = {broot, bhead};
    body.skeleton.root_bone_index = 0;
    assets::Node bnode; bnode.name = "Bip01 Head"; bnode.parent_index = -1;
    body.nodes = {bnode}; body.root_node = 0;
    body.textures.emplace_back(0, 1, 1, false);
    body.materials.emplace_back();

    // Head: "Bip01 Head" bind-world at Z = 4; one vertex at (1,2,3) authored
    // fully onto the head skeleton's "Bip01 Head" (index 1).
    assets::Model head;
    assets::Bone hroot; hroot.name = "Bip01"; hroot.parent_index = -1;
    assets::Bone hhead; hhead.name = "Bip01 Head"; hhead.parent_index = 0;
    hhead.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -4.0f));
    head.skeleton.bones = {hroot, hhead};
    head.skeleton.root_bone_index = 0;
    head.textures.emplace_back(0, 1, 1, false);
    assets::Material mat; mat.stages[base_slot].texture_index = 0;
    head.materials.push_back(mat);
    assets::MeshCpu hc; hc.vertices.resize(1);
    hc.vertices[0].position = glm::vec3(1.0f, 2.0f, 3.0f);
    hc.vertices[0].bone_indices = {1, 0, 0, 0};
    hc.vertices[0].bone_weights = {255, 0, 0, 0};
    hc.indices = {0, 0, 0}; hc.material_index = 0;
    assets::Mesh hm(0, 0, 0, 3, 0, -1); hm.set_cpu_data(hc);
    head.meshes.push_back(std::move(hm));
    assets::Node hn; hn.name = "head"; hn.parent_index = -1;
    head.nodes = {hn}; head.root_node = 0; head.nodes[0].meshes.push_back(0);

    std::vector<assets::MeshCpu> grafted =
        assets::graft_head_cpu(body, head, "Bip01 Head");
    ASSERT_EQ(grafted.size(), 1u);

    // Vertex position UNTOUCHED (no rebase).
    EXPECT_FLOAT_EQ(grafted[0].vertices[0].position.x, 1.0f);
    EXPECT_FLOAT_EQ(grafted[0].vertices[0].position.y, 2.0f);
    EXPECT_FLOAT_EQ(grafted[0].vertices[0].position.z, 3.0f);

    // Body skeleton gained the alias; the vertex points at it, weight kept.
    ASSERT_EQ(body.skeleton.bones.size(), 3u);
    EXPECT_EQ(body.skeleton.bones[2].name,
              std::string("Bip01 Head") +
                  std::string(assets::kHeadBindAliasSuffix));
    EXPECT_EQ(grafted[0].vertices[0].bone_indices.x, 2);
    EXPECT_EQ(grafted[0].vertices[0].bone_weights.x, 255);
}

// The weld preserves authored multi-bone weights byte-for-byte, remapping only
// the INDICES by bone name (head skeleton bone order deliberately differs from
// the body's). Zero-weight slots are normalized to index 0.
TEST(GraftHeadCpu, RemapsMultiBoneWeightsByName) {
    const auto base_slot =
        static_cast<std::size_t>(assets::Material::StageSlot::Base);

    // Body skeleton: [Bip01, Bip01 Neck, Bip01 Head], identity binds.
    assets::Model body;
    assets::Bone b0; b0.name = "Bip01";      b0.parent_index = -1;
    assets::Bone b1; b1.name = "Bip01 Neck"; b1.parent_index = 0;
    assets::Bone b2; b2.name = "Bip01 Head"; b2.parent_index = 1;
    body.skeleton.bones = {b0, b1, b2};
    body.skeleton.root_bone_index = 0;
    assets::Node bnode; bnode.name = "Bip01 Head"; bnode.parent_index = -1;
    body.nodes = {bnode}; body.root_node = 0;
    body.textures.emplace_back(0, 1, 1, false);
    body.materials.emplace_back();

    // Head skeleton REVERSED: [Bip01 Head, Bip01 Neck, Bip01], identity binds.
    assets::Model head;
    assets::Bone h0; h0.name = "Bip01 Head"; h0.parent_index = 1;
    assets::Bone h1; h1.name = "Bip01 Neck"; h1.parent_index = 2;
    assets::Bone h2; h2.name = "Bip01";      h2.parent_index = -1;
    head.skeleton.bones = {h0, h1, h2};
    head.skeleton.root_bone_index = 2;
    head.textures.emplace_back(0, 1, 1, false);
    assets::Material mat; mat.stages[base_slot].texture_index = 0;
    head.materials.push_back(mat);
    assets::MeshCpu hc; hc.vertices.resize(1);
    // Authored: 2/3 head-skeleton "Bip01 Head" (idx 0), 1/3 "Bip01 Neck" (1).
    hc.vertices[0].bone_indices = {0, 1, 0, 0};
    hc.vertices[0].bone_weights = {170, 85, 0, 0};
    hc.indices = {0, 0, 0}; hc.material_index = 0;
    assets::Mesh hm(0, 0, 0, 3, 0, -1); hm.set_cpu_data(hc);
    head.meshes.push_back(std::move(hm));
    assets::Node hn; hn.name = "head"; hn.parent_index = -1;
    head.nodes = {hn}; head.root_node = 0; head.nodes[0].meshes.push_back(0);

    std::vector<assets::MeshCpu> grafted =
        assets::graft_head_cpu(body, head, "Bip01 Head");
    ASSERT_EQ(grafted.size(), 1u);
    ASSERT_EQ(body.skeleton.bones.size(), 3u);  // binds equal: no appends

    const auto& v = grafted[0].vertices[0];
    EXPECT_EQ(v.bone_indices.x, 2);   // head "Bip01 Head"(0) -> body 2
    EXPECT_EQ(v.bone_indices.y, 1);   // head "Bip01 Neck"(1) -> body 1
    EXPECT_EQ(v.bone_weights.x, 170); // weights byte-preserved
    EXPECT_EQ(v.bone_weights.y, 85);
    EXPECT_EQ(v.bone_weights.z, 0);
    EXPECT_EQ(v.bone_weights.w, 0);
}

// Four SDK characters (Admiral_Liu, Barel, CardCapt, Korbus) register their
// blink frame as "*_eyes_closed.tga", but no such file ships anywhere under
// game/data — the on-disk convention is "*_eyesclosed.tga" (28 heads) or
// "*_eyes_close.tga" (Brex). face_texture_candidates must yield the literal
// path first, then the spelling variants, then the "_head"-infix variant of
// each, so load_face_texture can resolve every real file with one loop.
TEST(FaceTextureCandidates, LiteralPathComesFirst) {
    const std::filesystem::path p = "/heads/HeadLiu/Liu_head_eyes_closed.tga";
    const auto cands = assets::face_texture_candidates(p);
    ASSERT_FALSE(cands.empty());
    EXPECT_EQ(cands.front(), p);
}

TEST(FaceTextureCandidates, RewritesEyesClosedToEyesclosed) {
    const auto cands = assets::face_texture_candidates(
        "/heads/HeadLiu/Liu_head_eyes_closed.tga");
    EXPECT_NE(std::find(cands.begin(), cands.end(),
                        std::filesystem::path(
                            "/heads/HeadLiu/Liu_head_eyesclosed.tga")),
              cands.end())
        << "'eyes_closed' -> 'eyesclosed' spelling variant missing";
}

TEST(FaceTextureCandidates, RewritesEyesClosedToEyesClose) {
    // Brex's on-disk spelling drops the trailing 'd'.
    const auto cands = assets::face_texture_candidates(
        "/heads/HeadBrex/Brex_head_eyes_closed.tga");
    EXPECT_NE(std::find(cands.begin(), cands.end(),
                        std::filesystem::path(
                            "/heads/HeadBrex/Brex_head_eyes_close.tga")),
              cands.end())
        << "'eyes_closed' -> 'eyes_close' (Brex) spelling variant missing";
}

TEST(FaceTextureCandidates, SpellingVariantComposesWithHeadInfix) {
    // Korbus stacks both quirks: "Korbus_eyes_closed.tga" must reach
    // "Korbus_head_eyesclosed.tga" (spelling rewrite + "_head" infix).
    const auto cands = assets::face_texture_candidates(
        "/heads/HeadKorbus/Korbus_eyes_closed.tga");
    EXPECT_NE(std::find(cands.begin(), cands.end(),
                        std::filesystem::path(
                            "/heads/HeadKorbus/Korbus_head_eyesclosed.tga")),
              cands.end())
        << "spelling variant did not compose with the '_head'-infix variant";
}

TEST(FaceTextureCandidates, KeepsExistingHeadInfixFallback) {
    // The pre-existing Felix quirk: literal + "_head"-infix variant only.
    const auto cands = assets::face_texture_candidates(
        "/heads/HeadFelix/Felix_blink1.tga");
    EXPECT_NE(std::find(cands.begin(), cands.end(),
                        std::filesystem::path(
                            "/heads/HeadFelix/Felix_head_blink1.tga")),
              cands.end());
}

TEST(FaceTextureCandidates, CanonicalNameYieldsOnlyTheLiteral) {
    // Already-canonical name with no eyes-closed token: no invented variants,
    // so a genuinely-missing file still fails (no false positives).
    const auto cands = assets::face_texture_candidates(
        "/heads/HeadFelix/Felix_head_nope.tga");
    ASSERT_EQ(cands.size(), 1u);
    EXPECT_EQ(cands.front(),
              std::filesystem::path("/heads/HeadFelix/Felix_head_nope.tga"));
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
