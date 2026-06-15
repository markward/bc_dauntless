// native/tests/renderer/skinned_bridge_test.cc
//
// Offscreen GL verification that the bridge pass renders skinned characters,
// lit by the BRIDGE ambient (not space lighting), via the new skinned_bridge
// vertex stage paired with bridge.frag.
//
//   A (renders + lit): a skinned Pass::Bridge instance, with a non-black
//       Lighting::ambient, produces non-background pixels through
//       BridgePass::render — the character drew and was lit.
//   B (bridge-ambient drives it): the same render with ambient=(0,0,0) and no
//       emissive is black/background — proving the character is lit by the
//       BRIDGE ambient, not any space lighting.
//
// Both SKIP (not fail) when the BC asset or a GL context is unavailable.

#include <gtest/gtest.h>

#include <renderer/bridge_pass.h>
#include <renderer/bone_palette.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/world.h>
#include <scenegraph/instance.h>
#include <scenegraph/camera.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <renderer/pose_sampler.h>
#include <assets/animation.h>
#include <assets/model_compose.h>

#include <glad/glad.h>
#include <glm/gtc/matrix_transform.hpp>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "../../third_party/glfw/deps/stb_image_write.h"

#include <cstdlib>
#include <filesystem>
#include <memory>
#include <vector>

namespace {

const std::filesystem::path kProjectRoot =
    std::filesystem::path(__FILE__).parent_path().parent_path().parent_path().parent_path();
const std::filesystem::path kBodyNif =
    kProjectRoot / "game" / "data" / "Models" / "Characters" / "Bodies"
                 / "BodyMaleL" / "BodyMaleL.NIF";
const std::filesystem::path kBodyTex =
    kProjectRoot / "game" / "data" / "Models" / "Characters" / "Bodies"
                 / "BodyMaleL";

constexpr int kW = 256;
constexpr int kH = 256;

class SkinnedBridgeTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;
    assets::ModelHandle model_h;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kBodyNif)) {
            GTEST_SKIP() << "BC skinned asset not available at " << kBodyNif;
        }
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "skinned-bridge-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        cache = std::make_unique<assets::AssetCache>();
        model_h = cache->load(kBodyNif, kBodyTex);
        if (!model_h || model_h->skeleton.bones.empty()) {
            GTEST_SKIP() << "loaded model has no skeleton — not a skinned NIF";
        }
    }

    // Frame a camera so the whole model fits and is roughly centred. The model
    // sits at origin in its model units; pull the camera back along +Z.
    static scenegraph::Camera frame_camera() {
        scenegraph::Camera cam;
        cam.eye    = glm::vec3(0.0f, 0.0f, 30.0f);
        cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
        cam.aspect = 1.0f;
        return cam;
    }

    // Render one skinned Pass::Bridge instance through BridgePass::render with
    // the given ambient, and read back the framebuffer.
    std::vector<unsigned char> render_with_ambient(const glm::vec3& ambient) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);

        // ModelLookup over our single loaded model (handle is the Model*).
        renderer::BridgePass::ModelLookup lookup =
            [&](unsigned long long h) -> const assets::Model* {
                return reinterpret_cast<const assets::Model*>(h);
            };

        renderer::Lighting lighting;
        lighting.ambient = ambient;
        lighting.directional_count = 0;  // bridge: no space directional lights.

        scenegraph::Camera cam = frame_camera();

        glViewport(0, 0, kW, kH);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        renderer::BridgePass pass;
        pass.render(world, cam, *p, lookup, lighting);

        std::vector<unsigned char> buf(static_cast<size_t>(kW) * kH * 4);
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        return buf;
    }

    static long foreground_count(const std::vector<unsigned char>& buf) {
        long count = 0;
        for (size_t i = 0; i < buf.size(); i += 4) {
            if (buf[i] + buf[i + 1] + buf[i + 2] > 6) ++count;
        }
        return count;
    }

    // Render one skinned Pass::Bridge instance through BridgePass::render with
    // a bright bridge ambient and the given per-instance palette. An empty
    // palette exercises the bind-pose fallback; a non-empty palette is applied
    // verbatim via World::set_bone_palette. Reads back the framebuffer.
    std::vector<unsigned char> render_with_palette(
            const std::vector<glm::mat4>& palette) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);
        world.set_bone_palette(iid, palette);

        renderer::BridgePass::ModelLookup lookup =
            [&](unsigned long long h) -> const assets::Model* {
                return reinterpret_cast<const assets::Model*>(h);
            };

        renderer::Lighting lighting;
        lighting.ambient = glm::vec3(0.8f, 0.8f, 0.8f);
        lighting.directional_count = 0;

        scenegraph::Camera cam = frame_camera();

        glViewport(0, 0, kW, kH);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        renderer::BridgePass pass;
        pass.render(world, cam, *p, lookup, lighting);

        std::vector<unsigned char> buf(static_cast<size_t>(kW) * kH * 4);
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        return buf;
    }
};

// Test A — the skinned character renders through the bridge pass and is lit by
// a non-black bridge ambient.
TEST_F(SkinnedBridgeTest, SkinnedCharacterRendersLitByBridgeAmbient) {
    const std::vector<unsigned char> buf =
        render_with_ambient(glm::vec3(0.8f, 0.8f, 0.8f));
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_GT(foreground_count(buf), 0)
        << "skinned Pass::Bridge character produced no foreground pixels — "
           "it was not drawn (or not lit) by BridgePass::render.";
}

// Test B — with zero bridge ambient and no emissive, the character is black:
// it is the BRIDGE ambient driving its brightness, not space lighting.
TEST_F(SkinnedBridgeTest, DarkBridgeAmbientYieldsBlackCharacter) {
    const std::vector<unsigned char> buf =
        render_with_ambient(glm::vec3(0.0f, 0.0f, 0.0f));
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_EQ(foreground_count(buf), 0)
        << "character was non-black under zero bridge ambient — it is not lit "
           "by the bridge ambient (some other light source is leaking in).";
}

// Test C — PER-INSTANCE POSE: an empty palette renders the model's bind pose,
// while a non-identity per-instance palette (every bone translated, applied via
// World::set_bone_palette) changes the rendered silhouette. Proves the bridge
// sub-pass reads Instance::bone_palette instead of always rebuilding the bind
// pose. Mirrors SP1's SkinnedRenderTest.TranslatedPaletteShiftsSilhouette but
// drives the palette through the scenegraph instance, not draw_model directly.
TEST_F(SkinnedBridgeTest, PerInstancePaletteShiftsSilhouette) {
    // Bind-pose baseline via the empty-palette fallback path.
    const std::vector<unsigned char> buf0 = render_with_palette({});
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const long fg0 = foreground_count(buf0);
    ASSERT_GT(fg0, 0) << "bind-pose (empty palette) render produced no "
                         "silhouette";

    // Non-identity palette: translate every bone in world space. Pre-multiplying
    // each bind palette entry by a world-space translation moves every skinned
    // (and rigid-bound) vertex, so the whole silhouette shifts. The body NIF
    // fills most of the frame at bind pose, so a sizeable shift slides much of
    // the figure out of view — a large, unambiguous silhouette change.
    std::vector<glm::mat4> shifted =
        renderer::build_bone_palette(model_h->skeleton, /*local_pose=*/nullptr);
    ASSERT_FALSE(shifted.empty());
    const glm::mat4 T = glm::translate(glm::mat4(1.0f),
                                       glm::vec3(40.0f, 0.0f, 0.0f));
    for (auto& m : shifted) m = T * m;

    const std::vector<unsigned char> buf1 = render_with_palette(shifted);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const long fg1 = foreground_count(buf1);

    // Per-pixel difference between the two renders: the posed palette must
    // produce a materially different image from the bind pose. (If the bridge
    // sub-pass ignored Instance::bone_palette, both renders would be the bind
    // pose and these buffers would be identical.)
    long differing = 0;
    for (size_t i = 0; i < buf0.size(); ++i) {
        if (std::abs(static_cast<int>(buf0[i]) - static_cast<int>(buf1[i])) > 2)
            ++differing;
    }
    EXPECT_GT(differing, fg0 / 4)
        << "the per-instance posed palette did not change the silhouette "
           "(differing channels=" << differing << ", bind fg=" << fg0
           << ", posed fg=" << fg1 << ") — the bridge sub-pass is not using "
           "Instance::bone_palette.";
}

// DIAGNOSTIC (not an assertion): render the body posed by the db_stand_t_l
// placement clip and dump a PNG so the actual GPU output can be inspected. No
// X-flip (identity world), culling already disabled in the skinned sub-pass, so
// this isolates the SKINNING itself. Output: /tmp/sp2_posed_officer.png
TEST_F(SkinnedBridgeTest, DISABLED_DumpPosedOfficerPNG) {
    // Render each of the 5 D-bridge officer configs (body + placement clip),
    // auto-framed on its posed centroid, to a PNG. Identifies which config(s)
    // produce the "brown skeleton" contortion.
    struct Cfg { const char* body; const char* clip; bool at_start; const char* out; };
    const Cfg cfgs[] = {
        {"BodyMaleL", "db_stand_t_l", false, "/tmp/sp2_tactical.png"},
        {"BodyFemM",  "db_stand_h_m", false, "/tmp/sp2_helm.png"},
        {"BodyFemM",  "db_stand_c_m", false, "/tmp/sp2_commander.png"},
        {"BodyMaleS", "db_StoL1_S",   true,  "/tmp/sp2_science.png"},
        {"BodyMaleS", "db_EtoL1_s",   true,  "/tmp/sp2_engineer.png"},
    };
    renderer::BridgePass::ModelLookup lookup =
        [&](unsigned long long h) { return reinterpret_cast<const assets::Model*>(h); };
    for (const Cfg& cfg : cfgs) {
        const std::filesystem::path bodyp =
            kProjectRoot / "game" / "data" / "Models" / "Characters" / "Bodies"
                         / cfg.body / (std::string(cfg.body) + ".NIF");
        const std::filesystem::path clipp =
            kProjectRoot / "game" / "data" / "animations" / (std::string(cfg.clip) + ".nif");
        if (!std::filesystem::is_regular_file(bodyp)) continue;
        assets::AssetCache lc;
        assets::ModelHandle mh = lc.load(bodyp, bodyp.parent_path());
        auto cl = assets::load_animation_clips(clipp);
        if (!mh || mh->skeleton.bones.empty() || cl.empty()) continue;
        const float t = cfg.at_start ? 0.0f : cl.front().duration_seconds;
        std::vector<glm::mat4> pose = renderer::sample_pose(cl.front(), mh->skeleton, t);
        std::vector<glm::mat4> pal = renderer::build_bone_palette(mh->skeleton, &pose);
        // Centroid = average posed bone origin (palette[b] applied to the bone's
        // origin = world_pose translation), so the camera always frames it.
        glm::vec3 cc(0.0f);
        for (const auto& M : pal) cc += glm::vec3(M[3]);
        if (!pal.empty()) cc /= static_cast<float>(pal.size());

        scenegraph::World w2;
        auto id = w2.create_instance(reinterpret_cast<scenegraph::ModelHandle>(mh.get()));
        w2.set_world_transform(id, glm::mat4(1.0f));
        w2.set_pass(id, scenegraph::Pass::Bridge);
        w2.set_bone_palette(id, pal);
        renderer::Lighting lt; lt.ambient = glm::vec3(0.9f); lt.directional_count = 0;
        scenegraph::Camera cm;
        cm.eye = cc + glm::vec3(95.0f, 95.0f, 30.0f);
        cm.target = cc; cm.up = glm::vec3(0, 0, 1); cm.aspect = 1.0f;
        glViewport(0, 0, kW, kH);
        glClearColor(0.15f, 0.15f, 0.2f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::BridgePass ps; ps.render(w2, cm, *p, lookup, lt);
        std::vector<unsigned char> b(static_cast<size_t>(kW) * kH * 4);
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, b.data());
        std::vector<unsigned char> fl(b.size());
        for (int y = 0; y < kH; ++y)
            std::copy_n(&b[static_cast<size_t>(kH - 1 - y) * kW * 4], kW * 4,
                        &fl[static_cast<size_t>(y) * kW * 4]);
        stbi_write_png(cfg.out, kW, kH, 4, fl.data(), kW * 4);
        std::fprintf(stderr, "[dump] %s (%s + %s) centroid=(%.0f %.0f %.0f)\n",
                     cfg.out, cfg.body, cfg.clip, cc.x, cc.y, cc.z);
    }

    // COMPOSED officer (body + grafted head) — the live path. This is what the
    // body-only renders above DON'T exercise: the grafted head. If the head
    // baked correctly, this is a coherent figure with a head; if not, the
    // skin-coloured head contorts (the "brown skeleton").
    {
        const std::filesystem::path body =
            kProjectRoot / "game/data/Models/Characters/Bodies/BodyMaleS/BodyMaleS.NIF";
        const std::filesystem::path head =
            kProjectRoot / "game/data/Models/Characters/Heads/HeadBrex/brex_head_no_mouth.nif";
        const std::filesystem::path clipp =
            kProjectRoot / "game/data/animations/db_EtoL1_s.nif";
        const std::filesystem::path body_tex =
            kProjectRoot / "game/data/Models/Characters/Bodies/BodyMaleM/FedGold_body.tga";
        const std::filesystem::path head_tex =
            kProjectRoot / "game/data/Models/Characters/Heads/HeadBrex/brex_head.tga";
        if (std::filesystem::is_regular_file(head)) {
            assets::Model composed = assets::compose_officer_model(
                body, body_tex, head, head_tex, "Bip01 Head");
            auto cl = assets::load_animation_clips(clipp);
            if (!composed.skeleton.bones.empty() && !cl.empty()) {
                auto pose = renderer::sample_pose(cl.front(), composed.skeleton,
                                                  cl.front().duration_seconds);
                auto pal = renderer::build_bone_palette(composed.skeleton, &pose);
                // True head position: skin the grafted head meshes' verts (the
                // last 2 meshes, material >= the body's count) and AABB them.
                glm::vec3 hlo(1e9f), hhi(-1e9f); std::size_t hn = 0;
                for (const auto& mesh : composed.meshes) {
                    if (!mesh.cpu_data()) continue;
                    int mat = mesh.material_index();
                    if (mat < 36) continue;  // 36/37 = grafted head materials
                    for (const auto& v : mesh.cpu_data()->vertices) {
                        glm::vec4 sp(0.0f);
                        for (int k = 0; k < 4; ++k) {
                            int bi = v.bone_indices[k];
                            float wv = v.bone_weights[k] / 255.0f;
                            if (wv > 0 && bi < (int)pal.size())
                                sp += wv * (pal[bi] * glm::vec4(v.position, 1.0f));
                        }
                        hlo = glm::min(hlo, glm::vec3(sp)); hhi = glm::max(hhi, glm::vec3(sp)); ++hn;
                    }
                }
                glm::vec3 cc = hn ? (hlo + hhi) * 0.5f : glm::vec3(0.0f);
                scenegraph::World w4;
                auto id4 = w4.create_instance(
                    reinterpret_cast<scenegraph::ModelHandle>(&composed));
                w4.set_world_transform(id4, glm::mat4(1.0f));
                w4.set_pass(id4, scenegraph::Pass::Bridge);
                w4.set_bone_palette(id4, pal);
                renderer::Lighting lt; lt.ambient = glm::vec3(0.9f); lt.directional_count = 0;
                scenegraph::Camera cm;
                cm.eye = cc + glm::vec3(0.0f, 30.0f, 3.0f);  // front of the head
                cm.target = cc; cm.up = glm::vec3(0, 0, 1); cm.aspect = 1.0f;
                glViewport(0, 0, kW, kH);
                glClearColor(0.15f, 0.15f, 0.2f, 1.0f);
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
                renderer::BridgePass ps; ps.render(w4, cm, *p, lookup, lt);
                std::vector<unsigned char> b(static_cast<size_t>(kW) * kH * 4);
                glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, b.data());
                std::vector<unsigned char> fl(b.size());
                for (int y = 0; y < kH; ++y)
                    std::copy_n(&b[static_cast<size_t>(kH - 1 - y) * kW * 4],
                                kW * 4, &fl[static_cast<size_t>(y) * kW * 4]);
                stbi_write_png("/tmp/sp2_composed.png", kW, kH, 4, fl.data(), kW * 4);
                std::fprintf(stderr, "[dump] /tmp/sp2_composed.png (body+head)\n");
            }
        }
    }
}

}  // namespace
