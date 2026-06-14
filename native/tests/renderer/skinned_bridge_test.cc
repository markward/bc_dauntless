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

#include <glad/glad.h>
#include <glm/gtc/matrix_transform.hpp>

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

}  // namespace
