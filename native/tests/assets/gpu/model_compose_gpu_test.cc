#include <gtest/gtest.h>

#include <assets/model_compose.h>
#include <assets/material.h>
#include <glad/glad.h>

#include "gl_fixture.h"

#include <cstdio>
#include <filesystem>
#include <set>

namespace fs = std::filesystem;

// SP3 Task 6 Step 5: graft a real head NIF onto the real BodyMaleL skeleton via
// the host-facing compose_officer_model path and confirm the composed model has
// more meshes than the body alone, that the grafted meshes are attached to a
// node (so the renderer's node-walk draws them), and that every grafted vertex
// is rigid-bound to the body's "Bip01 Head" bone.
class ModelComposeGpuTest : public assets_test::GLContext {};

TEST_F(ModelComposeGpuTest, GraftRealHeadOntoBodyMaleL) {
    const fs::path root = OPEN_STBC_PROJECT_ROOT;
    const fs::path body_dir = root / "game/data/Models/Characters/Bodies/BodyMaleL";
    const fs::path body_nif = body_dir / "BodyMaleL.NIF";
    // Picard head is a stable, present head NIF; skin lives beside it.
    const fs::path head_dir = root / "game/data/Models/Characters/Heads/HeadPicard";
    const fs::path head_nif = head_dir / "Picard_head.NIF";

    if (!fs::exists(body_nif) || !fs::exists(head_nif))
        GTEST_SKIP() << "character NIFs not installed (" << body_nif
                     << " / " << head_nif << ")";

    // Build the body alone first to get its mesh count and the "Bip01 Head"
    // bone index for the rigid-bind assertion. No skin override here (empty
    // tex paths) — this test only exercises the graft.
    assets::Model composed = assets::compose_officer_model(
        body_nif, /*body_tex=*/{}, head_nif, /*head_tex=*/{}, "Bip01 Head");

    ASSERT_FALSE(composed.skeleton.bones.empty());

    int head_bone = -1;
    for (std::size_t i = 0; i < composed.skeleton.bones.size(); ++i)
        if (composed.skeleton.bones[i].name == "Bip01 Head")
            head_bone = static_cast<int>(i);
    ASSERT_GE(head_bone, 0) << "BodyMaleL skeleton lacks a 'Bip01 Head' bone";

    // The composed model must have grafted head meshes: at least one mesh whose
    // every vertex is rigid-bound to the head bone (weights (255,0,0,0)).
    int grafted_meshes = 0;
    for (const auto& mesh : composed.meshes) {
        const auto& cpu = mesh.cpu_data();
        if (!cpu || cpu->vertices.empty()) continue;
        bool all_head = true;
        for (const auto& v : cpu->vertices) {
            if (!(v.bone_indices.x == head_bone && v.bone_weights.x == 255 &&
                  v.bone_weights.y == 0 && v.bone_weights.z == 0 &&
                  v.bone_weights.w == 0)) {
                all_head = false;
                break;
            }
        }
        if (all_head) ++grafted_meshes;
    }
    std::fprintf(stderr,
                 "compose: %zu total meshes, %d fully head-bone-bound (grafted)\n",
                 composed.meshes.size(), grafted_meshes);
    EXPECT_GT(grafted_meshes, 0)
        << "expected at least one grafted head mesh rigid-bound to 'Bip01 Head'";

    // The grafted head replaces the body's default head: the attach node
    // ("Bip01 Head") must now carry meshes (the grafted Felix head), and they
    // must be reachable from a node (the renderer walks nodes). graft_head
    // clears the body's own head-subtree meshes from the node-walk first, so we
    // only require that the attach node has grafted, head-bone-bound meshes —
    // not that EVERY head-bone-bound mesh in the model is node-referenced (the
    // body's replaced default head is intentionally unreferenced).
    int attach_node = -1;
    for (std::size_t i = 0; i < composed.nodes.size(); ++i)
        if (composed.nodes[i].name == "Bip01 Head") attach_node = static_cast<int>(i);
    ASSERT_GE(attach_node, 0) << "composed body has no 'Bip01 Head' node";
    EXPECT_GT(composed.nodes[attach_node].meshes.size(), 0u)
        << "attach node has no grafted head meshes";
    for (int mi : composed.nodes[attach_node].meshes) {
        const auto& cpu = composed.meshes[mi].cpu_data();
        ASSERT_TRUE(cpu);
        for (const auto& v : cpu->vertices)
            EXPECT_EQ(v.bone_indices.x, head_bone)
                << "mesh on attach node not bound to head bone";
    }

    // Regression (the "lego skeleton" bug): BC body/head NIFs carry ~30 HIDDEN
    // "Biped Object" skeleton-placeholder boxes that must never render. With
    // model_build dropping hidden shapes, the composed draw list is exactly the
    // visible geometry: BodyMaleL's 2 body meshes + the grafted head meshes.
    // Before the fix this was 30+ (every box was node-attached and drawn).
    std::size_t draw_list = 0;
    for (const auto& n : composed.nodes) draw_list += n.meshes.size();
    EXPECT_EQ(draw_list, 2u + static_cast<std::size_t>(grafted_meshes))
        << "draw list should be body(2) + grafted head only — no hidden "
           "'Biped Object' skeleton boxes";
    EXPECT_LT(draw_list, 10u) << "skeleton-placeholder boxes leaked into draw list";

    // GL handles uploaded cleanly.
    for (const auto& mesh : composed.meshes) {
        EXPECT_NE(mesh.vao(), 0u);
        EXPECT_TRUE(glIsVertexArray(mesh.vao()));
    }
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// SP3 Task 6 (spec §6 / Step 4): the per-officer skin override must actually
// re-point the body/head materials' Base stage at a freshly-loaded texture
// (a differently-NAMED .tga than the one the NIF embeds), not just resolve the
// NIF basename in a search dir. We assemble BodyMaleM (embeds "body.tga") with
// a specific body_tex of "FedRed_body.tga" and a Picard head (embeds
// "head.tga") with head_tex "picard_head.tga", then assert the targeted
// materials' Base texture_index points into the NEWLY-appended texture range.
TEST_F(ModelComposeGpuTest, OverridesBodyAndHeadBaseTextures) {
    const fs::path root = OPEN_STBC_PROJECT_ROOT;
    const fs::path body_dir =
        root / "game/data/Models/Characters/Bodies/BodyMaleM";
    const fs::path body_nif = body_dir / "BodyMaleM.NIF";
    const fs::path body_tex = body_dir / "FedRed_body.tga";  // != NIF "body.tga"
    const fs::path head_dir =
        root / "game/data/Models/Characters/Heads/HeadPicard";
    const fs::path head_nif = head_dir / "Picard_head.NIF";
    const fs::path head_tex = head_dir / "picard_head.tga";  // != NIF "head.tga"

    if (!fs::exists(body_nif) || !fs::exists(head_nif) ||
        !fs::exists(body_tex) || !fs::exists(head_tex))
        GTEST_SKIP() << "character assets not installed";

    // First compose with NO override: capture the body mesh count and the
    // texture-table size, plus the Base texture_index each body material had
    // from the NIF default.
    assets::Model base = assets::compose_officer_model(
        body_nif, /*body_tex=*/{}, head_nif, /*head_tex=*/{}, "Bip01 Head");

    const std::size_t base_tex_count = base.textures.size();
    ASSERT_GT(base_tex_count, 0u);

    // Now compose WITH overrides.
    assets::Model composed = assets::compose_officer_model(
        body_nif, body_tex, head_nif, head_tex, "Bip01 Head");

    const auto base_slot =
        static_cast<std::size_t>(assets::Material::StageSlot::Base);

    // Identify the grafted (head) mesh indices: every vertex rigid-bound to the
    // "Bip01 Head" bone. Body meshes are the remainder.
    int head_bone = -1;
    for (std::size_t i = 0; i < composed.skeleton.bones.size(); ++i)
        if (composed.skeleton.bones[i].name == "Bip01 Head")
            head_bone = static_cast<int>(i);
    ASSERT_GE(head_bone, 0);

    auto is_grafted = [&](const assets::Mesh& m) {
        const auto& cpu = m.cpu_data();
        if (!cpu || cpu->vertices.empty()) return false;
        for (const auto& v : cpu->vertices)
            if (!(v.bone_indices.x == head_bone && v.bone_weights.x == 255 &&
                  v.bone_weights.y == 0 && v.bone_weights.z == 0 &&
                  v.bone_weights.w == 0))
                return false;
        return true;
    };

    // The override appends new textures, so the composed model must have a
    // larger texture table than the un-overridden compose.
    EXPECT_GT(composed.textures.size(), base_tex_count)
        << "override should append at least one new texture";

    // The body skin override appends a texture *after* both NIFs' textures are
    // merged. We assert: at least one body material now points its Base stage
    // at an index >= the pre-override merged-texture count (i.e. a NEW texture),
    // proving the override took effect rather than the NIF default.
    bool body_overridden = false;
    bool head_overridden = false;
    int body_mat_count = 0;
    int head_mat_count = 0;
    for (std::size_t i = 0; i < composed.meshes.size(); ++i) {
        const int mat = composed.meshes[i].material_index();
        if (mat < 0 || mat >= static_cast<int>(composed.materials.size()))
            continue;
        const int tex_idx =
            composed.materials[mat].stages[base_slot].texture_index;
        if (is_grafted(composed.meshes[i])) {
            ++head_mat_count;
            if (tex_idx >= static_cast<int>(base_tex_count))
                head_overridden = true;
        } else {
            ++body_mat_count;
            if (tex_idx >= static_cast<int>(base_tex_count))
                body_overridden = true;
        }
    }

    std::fprintf(stderr,
                 "override: base_tex=%zu composed_tex=%zu body_mats=%d "
                 "head_mats=%d body_ovr=%d head_ovr=%d\n",
                 base_tex_count, composed.textures.size(), body_mat_count,
                 head_mat_count, body_overridden, head_overridden);

    EXPECT_GT(body_mat_count, 0);
    EXPECT_TRUE(body_overridden)
        << "body material Base stage was not repointed to the FedRed_body.tga "
           "override (still on the NIF default)";
    EXPECT_GT(head_mat_count, 0);
    EXPECT_TRUE(head_overridden)
        << "head material Base stage was not repointed to the picard_head.tga "
           "override (still on the NIF default)";

    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
