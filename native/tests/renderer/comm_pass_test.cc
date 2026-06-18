// native/tests/renderer/comm_pass_test.cc
#include <gtest/gtest.h>
#include "scenegraph/world.h"
#include "scenegraph/instance.h"

#include <renderer/bridge_pass.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <glad/glad.h>
#include <glm/gtc/matrix_transform.hpp>

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

// One suite for every comm-pass test. The pure-logic cases use only the
// scenegraph; the render case lazily brings up a GL context inside its body
// (and GTEST_SKIPs when no context/asset is available) so the logic tests never
// depend on GL. All three share the suite name so the focused filter
// `CommPass.*` covers them.
class CommPass : public ::testing::Test {
protected:
    static scenegraph::Camera frame_camera() {
        scenegraph::Camera cam;
        cam.eye    = glm::vec3(0.0f, 0.0f, 30.0f);
        cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
        cam.aspect = 1.0f;
        return cam;
    }

    static long foreground_count(const std::vector<unsigned char>& buf) {
        long count = 0;
        for (size_t i = 0; i < buf.size(); i += 4) {
            if (buf[i] + buf[i + 1] + buf[i + 2] > 6) ++count;
        }
        return count;
    }
};

}  // namespace

TEST_F(CommPass, InstanceCarriesCommSetIdAndPass) {
    scenegraph::World w;
    auto id = w.create_instance(0);
    w.set_pass(id, scenegraph::Pass::Comm);
    int count = 0;
    w.for_each_visible_in_pass(scenegraph::Pass::Comm,
        [&](const scenegraph::Instance&) { ++count; });
    EXPECT_EQ(count, 1);
}

TEST_F(CommPass, SetCommSetIdFiltersInstances) {
    scenegraph::World w;
    auto a = w.create_instance(0); w.set_pass(a, scenegraph::Pass::Comm);
    auto b = w.create_instance(0); w.set_pass(b, scenegraph::Pass::Comm);
    w.set_comm_set_id(a, 7);
    w.set_comm_set_id(b, 9);
    int only7 = 0;
    w.for_each_visible_in_pass(scenegraph::Pass::Comm,
        [&](const scenegraph::Instance& i){ if (i.comm_set_id == 7) ++only7; });
    EXPECT_EQ(only7, 1);
}

// ── Render-from-camera: a Pass::Comm instance, tagged with a comm_set_id and
// drawn through BridgePass::render(..., Pass::Comm, set_id), produces non-empty
// output. Mirrors SkinnedBridgeTest's offscreen-render + readback harness. The
// model is any loadable bridge-shaped NIF; here we reuse the skinned body asset
// the skinned test uses, since BridgePass draws it via the skinned sub-pass.
TEST_F(CommPass, RendersTaggedSetFromCamera) {
    if (!std::filesystem::is_regular_file(kBodyNif)) {
        GTEST_SKIP() << "BC asset not available at " << kBodyNif;
    }
    std::unique_ptr<renderer::Window> win;
    try {
        win = std::make_unique<renderer::Window>(kW, kH, "comm-pass-test", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }
    renderer::Pipeline p;
    assets::AssetCache cache;
    assets::ModelHandle model_h = cache.load(kBodyNif, kBodyTex);
    if (!model_h) {
        GTEST_SKIP() << "model failed to load";
    }

    constexpr std::uint32_t kSetId = 42;

    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.set_pass(iid, scenegraph::Pass::Comm);
    world.set_comm_set_id(iid, kSetId);

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
    pass.render(world, cam, p, lookup, lighting,
                scenegraph::Pass::Comm, kSetId);

    std::vector<unsigned char> buf(static_cast<size_t>(kW) * kH * 4);
    glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_GT(foreground_count(buf), 0)
        << "Pass::Comm instance tagged set " << kSetId
        << " produced no foreground pixels — it was not drawn from the camera "
           "by BridgePass::render(..., Pass::Comm, set_id).";
}
