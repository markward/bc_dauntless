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
    // bone index for the rigid-bind assertion.
    assets::Model composed = assets::compose_officer_model(
        body_nif, {body_dir}, head_nif, {head_dir}, "Bip01 Head");

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

    // Every grafted mesh must be reachable from a node (renderer walks nodes).
    std::set<int> attached;
    for (const auto& n : composed.nodes)
        for (int mi : n.meshes) attached.insert(mi);
    for (std::size_t i = 0; i < composed.meshes.size(); ++i) {
        const auto& cpu = composed.meshes[i].cpu_data();
        if (!cpu) continue;
        bool grafted = !cpu->vertices.empty();
        for (const auto& v : cpu->vertices)
            if (!(v.bone_indices.x == head_bone && v.bone_weights.x == 255))
                grafted = false;
        if (grafted)
            EXPECT_TRUE(attached.count(static_cast<int>(i)))
                << "grafted mesh " << i << " is not on any node's mesh list";
    }

    // GL handles uploaded cleanly.
    for (const auto& mesh : composed.meshes) {
        EXPECT_NE(mesh.vao(), 0u);
        EXPECT_TRUE(glIsVertexArray(mesh.vao()));
    }
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
