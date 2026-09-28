// native/tests/renderer/render_origin_precision_test.cc
//
// The floating render origin, end to end through the real opaque pass.
// A Galaxy at game scale drawn 1e6 GU from the system origin must render
// exactly as it does at the origin, PROVIDED the render origin follows it
// (World::resolve_render_space subtracts in double, then narrows). The
// counter-test draws the same far-out scene with the origin left at zero and
// must come out visibly wrong — otherwise the first test proves nothing.
#include <gtest/gtest.h>

#include <renderer/asset_path.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <vector>

namespace {

namespace fs = std::filesystem;

constexpr int kSize = 256;
// NIF units -> GU for a Galaxy (~660 model units long -> ~3.6 GU), so the
// camera sits at the distance a player's chase camera actually does and the
// test sees the precision a real ship sees.
constexpr float kScale = 0.0055f;
constexpr float kCameraDistGu = 1500.0f * kScale;
constexpr double kFar = 1e6;

// The BC install root: DAUNTLESS_GAME_DIR (engine/paths.py's env source),
// else renderer::game_root() anchored at the project root.
fs::path bc_root() {
    if (const char* env = std::getenv("DAUNTLESS_GAME_DIR")) return fs::path(env);
    const fs::path project =
        fs::path(__FILE__).parent_path().parent_path().parent_path().parent_path();
    fs::path root = renderer::game_root();
    return root.is_relative() ? project / root : root;
}

class RenderOriginPrecisionTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;
    fs::path nif, tex;

    void SetUp() override {
        nif = bc_root() / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif";
        tex = bc_root() / "data" / "Models" / "SharedTextures" / "FedShips" / "High";
        if (!fs::is_regular_file(nif)) GTEST_SKIP() << "BC asset not available at " << nif;
        if (!fs::is_directory(tex)) GTEST_SKIP() << "BC texture dir not available at " << tex;
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize, "render-origin-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        cache = std::make_unique<assets::AssetCache>();
    }

    // Draw one Galaxy whose VIEW-space translation is `ship`, with the camera
    // kCameraDistGu above it along +z, under render origin `origin`. The
    // camera is float (set_camera is unchanged by the floating origin), so it
    // is handed over in RENDER space: view-space minus the origin, narrowed.
    std::vector<unsigned char> render(const glm::dvec3& ship,
                                      const glm::dvec3& origin) {
        auto model_h = cache->load(nif, tex);
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
        world.set_world_transform_d(iid, glm::mat3(kScale), ship);
        world.resolve_render_space(origin);

        scenegraph::Camera cam;
        cam.eye = glm::vec3(ship + glm::dvec3(0.0, 0.0, kCameraDistGu) - origin);
        cam.target = glm::vec3(ship - origin);
        cam.aspect = 1.0f;
        cam.near = 0.01f;
        cam.far = 100.0f;

        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::FrameSubmitter submitter;
        renderer::Lighting lighting;
        submitter.submit_opaque(world, cam, *p,
            [](scenegraph::ModelHandle h) -> const assets::Model* {
                return reinterpret_cast<const assets::Model*>(h);
            }, lighting);
        EXPECT_EQ(glGetError(), GL_NO_ERROR);

        std::vector<unsigned char> px(kSize * kSize * 4);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }
};

int lit_pixels(const std::vector<unsigned char>& px) {
    int n = 0;
    for (std::size_t i = 0; i < px.size(); i += 4)
        if (px[i] + px[i + 1] + px[i + 2] > 0) ++n;
    return n;
}

int differing_pixels(const std::vector<unsigned char>& a,
                     const std::vector<unsigned char>& b, int tolerance) {
    int n = 0;
    for (std::size_t i = 0; i < a.size(); i += 4) {
        for (int c = 0; c < 3; ++c) {
            if (std::abs(int(a[i + c]) - int(b[i + c])) > tolerance) { ++n; break; }
        }
    }
    return n;
}

int max_channel_delta(const std::vector<unsigned char>& a,
                      const std::vector<unsigned char>& b) {
    int m = 0;
    for (std::size_t i = 0; i < a.size(); ++i)
        m = std::max(m, std::abs(int(a[i]) - int(b[i])));
    return m;
}

TEST_F(RenderOriginPrecisionTest, AMillionGUOutRendersByteIdenticalWhenTheOriginFollows) {
    const auto near = render(glm::dvec3(0.0), glm::dvec3(0.0));
    ASSERT_GT(lit_pixels(near), kSize * kSize / 50)
        << "the reference Galaxy barely rendered; the comparison would be empty";
    const auto far = render(glm::dvec3(kFar, 0.0, 0.0), glm::dvec3(kFar, 0.0, 0.0));
    EXPECT_EQ(differing_pixels(near, far, 0), 0);
}

TEST_F(RenderOriginPrecisionTest, AMillionGUOutWithTheOriginLeftAtZeroIsVisiblyWrong) {
    // Counter-test: the same far-out scene WITHOUT the origin subtraction.
    // Vertices and the eye round to float's 1/16 GU grid at 1e6 GU — a sixth
    // of the whole hull's width — so the picture must break up.
    const auto near = render(glm::dvec3(0.0), glm::dvec3(0.0));
    const auto broken = render(glm::dvec3(kFar, 0.0, 0.0), glm::dvec3(0.0));
    const int diff = differing_pixels(near, broken, 8);
    RecordProperty("differing_pixels", diff);
    RecordProperty("lit_pixels", lit_pixels(near));
    RecordProperty("max_channel_delta", max_channel_delta(near, broken));
    // Measured on the M-series dev Mac: 764 of the reference's 4468 lit
    // pixels (17%) differ by more than 8/255, max channel delta 255. Demand a
    // twentieth of the hull so the bound does not ride on one GPU's rounding.
    EXPECT_GT(diff, lit_pixels(near) / 20)
        << "a far-out render with no origin subtraction matched the reference; "
           "the byte-identical test above would not catch a missing origin";
}

}  // namespace
