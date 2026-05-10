// native/tests/renderer/frame_test.cc
#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <filesystem>

namespace {

const std::filesystem::path kProjectRoot =
    std::filesystem::path(__FILE__).parent_path().parent_path().parent_path().parent_path();
const std::filesystem::path kGalaxyNif =
    kProjectRoot / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif";
const std::filesystem::path kGalaxyTex =
    kProjectRoot / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High";

class FrameTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kGalaxyNif)) {
            GTEST_SKIP() << "BC asset not available at " << kGalaxyNif;
        }
        if (!std::filesystem::is_directory(kGalaxyTex)) {
            GTEST_SKIP() << "BC texture dir not available at " << kGalaxyTex;
        }
        try {
            w = std::make_unique<renderer::Window>(256, 256, "frame-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        cache = std::make_unique<assets::AssetCache>();
    }
};

TEST_F(FrameTest, OpaquePassRunsWithoutGLError) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);

    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    // Galaxy.nif is in BC units (~660 x 644 x 140). Place it at origin and
    // pull the camera back far enough that the saucer fits inside the 60-deg
    // vertical FOV and its body sits over the center pixel.
    glm::mat4 m(1.0f);
    world.set_world_transform(iid, m);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;  // default-constructed: matches the
                                  // pre-Phase-1 hardcoded values that the
                                  // existing pixel-litness assertion below
                                  // was tuned against.
    submitter.submit_opaque(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // Read center pixel; should be lit (non-black) — the Galaxy's saucer
    // covers the center of the viewport from this camera.
    unsigned char pixel[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    int total = pixel[0] + pixel[1] + pixel[2];
    EXPECT_GT(total, 0) << "center pixel was black; opaque pass produced nothing";
}

}  // namespace
