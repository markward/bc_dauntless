// SP3 jaw characterization: BC has no dedicated jaw bone. Every bridge-character
// head mesh skins a small (~18-29 vertex) front-lower-centre mouth/chin cluster
// to the repurposed biped bone "Bip01 Ponytail1" (none of these characters has a
// real ponytail). The three global mouth-viseme clips
// (MouthClosed/MouthOpenPartly/MouthOpen) hold "Bip01 Ponytail1" at rest / rest+5
// / rest+10 degrees about the bone-local +Z axis (head bind rest = 111.481deg),
// giving a 10deg jaw-drop. Task 10 will rotate this bone per openness; the exact
// rest axis/angle constants are recorded in task-8-report.md.
//
// This test pins the COMPOSITION invariant Task 10 depends on: when a real
// officer (body + head) is composed onto one shared skeleton, "Bip01 Ponytail1"
// survives as a drivable bone AND grafted head-mesh (mouth) vertices still carry
// non-zero weight to it. If a future compose refactor dropped or renamed the
// bone, or severed the mouth-vert weights, driving it would silently move
// nothing -- this test catches that.
//
// Character model units (~78/body height), not GU. Skips without game/ assets or
// a GL context (compose_officer_model uploads GL meshes), same as
// head_weld_seam_test.cc.
#include <gtest/gtest.h>

#include <assets/model.h>
#include <assets/model_compose.h>
#include <renderer/bone_palette.h>
#include <renderer/window.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <cmath>
#include <cstddef>
#include <cstdio>
#include <filesystem>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;

const fs::path kRoot = fs::path(__FILE__)
    .parent_path().parent_path().parent_path().parent_path();
const fs::path kChars = kRoot / "game" / "data" / "Models" / "Characters";

// The bone that skins the mouth/chin cluster in every bridge-character head.
constexpr const char* kJawBoneName = "Bip01 Ponytail1";

// CPU-skin one vertex through `palette` — the shader's exact blend
// (skinned_bridge.vert): sum of w * (pal[b] * v).
glm::vec3 skin_vertex(const assets::MeshCpu::Vertex& v,
                      const std::vector<glm::mat4>& palette) {
    glm::vec4 sp(0.0f);
    for (int k = 0; k < 4; ++k) {
        const float w = v.bone_weights[k] / 255.0f;
        if (w <= 0.0f) continue;
        const int b = v.bone_indices[k];
        if (b < static_cast<int>(palette.size()))
            sp += w * (palette[b] * glm::vec4(v.position, 1.0f));
    }
    return glm::vec3(sp);
}

int bone_index_named(const assets::Skeleton& sk, const char* name) {
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        if (sk.bones[i].name == name) return static_cast<int>(i);
    return -1;
}

// The skeleton's bind locals — the base pose we compose the jaw onto (mirrors
// head_weld_seam_test's bent_neck_palette base).
std::vector<glm::mat4> rest_locals_of(const assets::Skeleton& sk) {
    std::vector<glm::mat4> locals(sk.bones.size());
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        locals[i] = sk.bones[i].local_transform;
    return locals;
}

class OfficerJawTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;

    void SetUp() override {
        if (!fs::is_regular_file(kChars / "Heads/HeadMiguel/miguel_head.NIF") ||
            !fs::is_regular_file(kChars / "Bodies/BodyMaleS/BodyMaleS.NIF"))
            GTEST_SKIP() << "character NIFs not installed";
        try {
            w = std::make_unique<renderer::Window>(64, 64, "jaw-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
    }
};

}  // namespace

TEST_F(OfficerJawTest, Ponytail1BoneSurvivesCompositionCarryingMouthWeights) {
    // BodyMaleS + miguel_head is the matched-bind pair (see head_weld_seam_test):
    // "Bip01 Ponytail1" welds onto the shared skeleton under its own name.
    assets::Model m = assets::compose_officer_model(
        kChars / "Bodies/BodyMaleS/BodyMaleS.NIF", /*body_tex=*/{},
        kChars / "Heads/HeadMiguel/miguel_head.NIF", /*head_tex=*/{},
        "Bip01 Head");

    // The grafted head meshes must exist as a distinct trailing range.
    ASSERT_GE(m.head_mesh_begin, 0)
        << "composition produced no grafted head meshes";

    // (1) The jaw bone survived composition as a named, drivable bone.
    int jaw_idx = -1;
    for (std::size_t i = 0; i < m.skeleton.bones.size(); ++i)
        if (m.skeleton.bones[i].name == kJawBoneName)
            jaw_idx = static_cast<int>(i);
    ASSERT_GE(jaw_idx, 0)
        << "'" << kJawBoneName << "' bone missing from the composed skeleton "
           "-- Task 10 would have nothing to rotate";

    // (2) At least one grafted head-mesh (mouth) vertex weights to it, so
    // rotating the bone actually moves mouth geometry.
    std::size_t mouth_verts = 0;
    for (std::size_t mi = static_cast<std::size_t>(m.head_mesh_begin);
         mi < m.meshes.size(); ++mi) {
        const auto& cpu = m.meshes[mi].cpu_data();
        if (!cpu) continue;
        for (const auto& v : cpu->vertices)
            for (int k = 0; k < 4; ++k)
                if (static_cast<int>(v.bone_indices[k]) == jaw_idx &&
                    v.bone_weights[k] > 0)
                    ++mouth_verts;
    }
    EXPECT_GT(mouth_verts, 0u)
        << "no grafted head vertex weights to '" << kJawBoneName
        << "' -- driving the jaw bone would move nothing";
}

// Task 10 CRUX: driving Ponytail1 by openness moves the mouth verts, and the
// neck seam is INVARIANT to the jaw. Composes the matched-bind officer, finds a
// real mouth vertex (weighted to Bip01 Ponytail1) and a neck-seam vertex
// (weighted to Bip01 Neck, NOT to the jaw), then CPU-skins each through the
// palette that apply_jaw_rotation produces at openness 0 vs 1.
TEST_F(OfficerJawTest, OpennessRotatesMouthVertsSeamStable) {
    assets::Model m = assets::compose_officer_model(
        kChars / "Bodies/BodyMaleS/BodyMaleS.NIF", /*body_tex=*/{},
        kChars / "Heads/HeadMiguel/miguel_head.NIF", /*head_tex=*/{},
        "Bip01 Head");
    ASSERT_GE(m.head_mesh_begin, 0) << "composition produced no head meshes";

    const int jaw_idx  = bone_index_named(m.skeleton, kJawBoneName);
    const int neck_idx = bone_index_named(m.skeleton, "Bip01 Neck");
    ASSERT_GE(jaw_idx, 0)  << "'" << kJawBoneName << "' missing from skeleton";
    ASSERT_GE(neck_idx, 0) << "'Bip01 Neck' missing from skeleton";

    // Pick the head-mesh mouth vertex with the STRONGEST weight to the jaw bone
    // (the vertex that moves most, i.e. the clearest signal), and a neck-seam
    // vertex with strong Neck weight and ZERO jaw weight (must stay put).
    const assets::MeshCpu::Vertex* mouth_v = nullptr;
    const assets::MeshCpu::Vertex* neck_v  = nullptr;
    int best_jaw_w = 0, best_neck_w = 0;
    for (std::size_t mi = static_cast<std::size_t>(m.head_mesh_begin);
         mi < m.meshes.size(); ++mi) {
        const auto& cpu = m.meshes[mi].cpu_data();
        if (!cpu) continue;
        for (const auto& v : cpu->vertices) {
            int jw = 0, nw = 0;
            for (int k = 0; k < 4; ++k) {
                if (static_cast<int>(v.bone_indices[k]) == jaw_idx)
                    jw = v.bone_weights[k];
                if (static_cast<int>(v.bone_indices[k]) == neck_idx)
                    nw = v.bone_weights[k];
            }
            if (jw > best_jaw_w) { best_jaw_w = jw; mouth_v = &v; }
            if (jw == 0 && nw > best_neck_w) { best_neck_w = nw; neck_v = &v; }
        }
    }
    ASSERT_NE(mouth_v, nullptr) << "no head vertex weighted to the jaw bone";
    ASSERT_NE(neck_v, nullptr)  << "no jaw-free neck-seam vertex found";

    // Un-jawed rest build (nullptr => bind locals) and jaw-driven builds.
    const auto pal_rest = renderer::build_bone_palette(m.skeleton, nullptr);

    std::vector<glm::mat4> l0 = rest_locals_of(m.skeleton);
    renderer::apply_jaw_rotation(m, l0, 0.0f);
    const auto pal0 = renderer::build_bone_palette(m.skeleton, &l0);

    std::vector<glm::mat4> l1 = rest_locals_of(m.skeleton);
    renderer::apply_jaw_rotation(m, l1, 1.0f);
    const auto pal1 = renderer::build_bone_palette(m.skeleton, &l1);

    const glm::vec3 mouth_rest = skin_vertex(*mouth_v, pal_rest);
    const glm::vec3 mouth_0    = skin_vertex(*mouth_v, pal0);
    const glm::vec3 mouth_1    = skin_vertex(*mouth_v, pal1);
    const glm::vec3 neck_0     = skin_vertex(*neck_v, pal0);
    const glm::vec3 neck_1     = skin_vertex(*neck_v, pal1);

    const float mouth_move = glm::distance(mouth_1, mouth_0);
    std::printf("[OfficerJaw] mouth displacement @openness=1: %.5f units "
                "(jaw weight %d/255)\n", mouth_move, best_jaw_w);

    // openness==0 is an identity rotation ⇒ REST (no-op): the jaw-0 build must
    // put the mouth vertex exactly where the un-jawed rest build does.
    EXPECT_LT(glm::distance(mouth_0, mouth_rest), 1e-5f)
        << "openness=0 shifted the mouth off its rest position (not a no-op)";

    // The mouth MOVED under a full jaw drop.
    EXPECT_GT(mouth_move, 1e-2f)
        << "driving the jaw bone did not move the mouth vertex";

    // The neck seam is INVARIANT to the jaw (head_weld_seam_test's guarantee).
    EXPECT_LT(glm::distance(neck_1, neck_0), 1e-4f)
        << "neck-seam vertex moved under the jaw drive (jaw leaked into neck)";
}

#include "scenegraph/world.h"
TEST(OfficerJaw, SetOfficerJawStoresOpenness) {
    scenegraph::World w;
    auto id = w.create_instance(scenegraph::ModelHandle{});
    w.set_officer_jaw(id, 0.7f);
    const auto* in = w.get(id);
    ASSERT_TRUE(in->jaw_active);
    ASSERT_NEAR(in->jaw_openness, 0.7f, 1e-6f);
}
