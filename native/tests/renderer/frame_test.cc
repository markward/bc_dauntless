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

TEST_F(FrameTest, OpaquePassWithRimEnabledRunsWithoutGLError) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);

    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_rim_eligible(iid, true);
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
    renderer::Lighting lighting;
    submitter.submit_opaque_in_pass(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting, scenegraph::Pass::Space);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(FrameTest, GlowContributesWithZeroAmbient) {
    // Galaxy.nif's NiImages reference "Ent-D_*_glow.tga" files directly
    // (BC's AddLOD "_glow" suffix convention). model_build.cc detects the
    // suffix and routes those textures into Material::StageSlot::Glow.
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);

    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting zero_lighting;
    zero_lighting.ambient           = glm::vec3(0.0f);
    zero_lighting.directional_count = 0;
    submitter.submit_opaque(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, zero_lighting);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // Scan a 5×5 grid across the saucer section; at least one pixel must be
    // non-zero to prove the glow pass contributed.  Clear colour is black so
    // background pixels are also 0 — only glow raises a pixel above 0.
    int max_total = 0;
    for (int dx = -40; dx <= 40; dx += 20) {
        for (int dy = -40; dy <= 40; dy += 20) {
            unsigned char px[4] = {0};
            glReadPixels(128 + dx, 128 + dy, 1, 1,
                         GL_RGBA, GL_UNSIGNED_BYTE, px);
            int t = px[0] + px[1] + px[2];
            if (t > max_total) max_total = t;
        }
    }
    EXPECT_GT(max_total, 0)
        << "Expected glow to contribute to at least one pixel with zero "
           "ambient lighting; all sampled pixels were black.";
}

TEST_F(FrameTest, SpecularShipRendersWithDirectionalLight) {
    // Render a ship known to ship with _specular textures (Keldon).
    // Asserts:
    //   1) The opaque pass completes without GL errors after binding
    //      the spec uniforms.
    //   2) A directional light + non-zero specular term produce at
    //      least one non-black pixel near screen center.
    // Smoke test only — does not isolate the specular contribution
    // numerically; the binding test in material_build_test.cc and the
    // mapping test in lighting_test.cc cover those layers.
    const std::filesystem::path keldon_nif =
        kProjectRoot / "game" / "data" / "Models" / "Ships" / "Keldon" / "Keldon.nif";
    const std::filesystem::path keldon_tex =
        kProjectRoot / "game" / "data" / "Models" / "SharedTextures" / "CardShips" / "High";
    if (!std::filesystem::is_regular_file(keldon_nif)) {
        GTEST_SKIP() << "BC asset not available at " << keldon_nif;
    }
    if (!std::filesystem::is_directory(keldon_tex)) {
        GTEST_SKIP() << "BC texture dir not available at " << keldon_tex;
    }

    auto model_h = cache->load(keldon_nif, keldon_tex);

    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 800.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    lighting.ambient            = glm::vec3(0.1f, 0.1f, 0.1f);
    lighting.directional_count  = 1;
    lighting.directional_dir_ws[0] = glm::vec3(0.0f, 0.0f, 1.0f);
    lighting.directional_color[0]  = glm::vec3(1.0f, 1.0f, 1.0f);
    submitter.submit_opaque(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    int max_total = 0;
    for (int dx = -40; dx <= 40; dx += 20) {
        for (int dy = -40; dy <= 40; dy += 20) {
            unsigned char px[4] = {0};
            glReadPixels(128 + dx, 128 + dy, 1, 1,
                         GL_RGBA, GL_UNSIGNED_BYTE, px);
            int t = px[0] + px[1] + px[2];
            if (t > max_total) max_total = t;
        }
    }
    EXPECT_GT(max_total, 0)
        << "Expected the Keldon to render at all (non-zero pixels under a "
           "directional light) — this is a pipeline smoke test, not a proof "
           "that the specular term contributes. See test docstring.";
}

}  // namespace
