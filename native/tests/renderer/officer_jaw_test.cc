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
#include <renderer/window.h>

#include <filesystem>
#include <memory>
#include <string>

namespace {

namespace fs = std::filesystem;

const fs::path kRoot = fs::path(__FILE__)
    .parent_path().parent_path().parent_path().parent_path();
const fs::path kChars = kRoot / "game" / "data" / "Models" / "Characters";

// The bone that skins the mouth/chin cluster in every bridge-character head.
constexpr const char* kJawBoneName = "Bip01 Ponytail1";

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
