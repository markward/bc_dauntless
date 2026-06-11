// native/tests/renderer/particle_pass_test.cc
//
// GL smoke tests for renderer::ParticlePass. Verifies that the pass renders
// without producing a GL error, both with a real emitter descriptor and with
// an empty emitter list. Tests are skipped when no offscreen GL context is
// available (headless CI) or when the required BC asset is absent.

#include <gtest/gtest.h>

#include <renderer/particle_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <renderer/frame.h>
#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <glad/glad.h>

#include <filesystem>
#include <memory>
#include <vector>

namespace {

class ParticlePassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(64, 64, "particle-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }
};

// Helper: derive the project root from __FILE__ (4 levels up from the test
// source, the same pattern used by hit_vfx_pass_test.cc and aabb_test.cc).
static std::filesystem::path project_root() {
    return std::filesystem::path(__FILE__)
        .parent_path()   // native/tests/renderer
        .parent_path()   // native/tests
        .parent_path()   // native
        .parent_path();  // project root
}

// ── Test 1: emitter with a real texture renders without GL error ────────────
TEST_F(ParticlePassTest, RendersWithoutGlError) {
    namespace fs = std::filesystem;

    // The texture path is relative to the project root (the renderer's CWD).
    // Use an absolute path here to be CWD-independent in the test harness.
    const fs::path tex_path = project_root()
        / "game" / "data" / "Textures" / "Effects" / "ExplosionB.tga";

    if (!fs::is_regular_file(tex_path)) {
        GTEST_SKIP() << "BC asset absent: " << tex_path;
    }

    renderer::ParticlePass pass;
    scenegraph::World world;
    scenegraph::Camera camera;
    camera.eye    = {0.0f, 0.0f, 100.0f};
    camera.target = {0.0f, 0.0f,   0.0f};
    camera.up     = {0.0f, 1.0f,   0.0f};
    camera.aspect = 1.0f;

    // Clear any pre-existing GL error state left by Pipeline construction.
    while (glGetError() != GL_NO_ERROR) {}

    // Build one emitter descriptor with the real texture and minimal keyframes.
    renderer::ParticleEmitterDescriptor e;
    e.texture_path       = tex_path.string();
    e.emit_pos           = {0.0f, 0.0f, 0.0f};
    e.emit_dir           = {0.0f, 1.0f, 0.0f};
    e.emit_vel_world     = {0.0f, 0.0f, 0.0f};
    e.inherit            = 0.0f;
    e.emit_velocity      = 1.0f;
    e.angle_variance     = 10.0f;
    e.emit_life          = 1.0f;
    e.emit_life_variance = 0.0f;
    e.emit_frequency     = 0.1f;
    e.effect_age         = 0.1f;
    e.stop_age           = 1.0e30f;
    e.draw_old_to_new    = 1;

    // One size key: size = 1 at t = 0.
    e.num_size_keys = 1;
    e.size_keys[0].t = 0.0f;
    e.size_keys[0].v = 1.0f;

    // One alpha key: alpha = 1 at t = 0.
    e.num_alpha_keys = 1;
    e.alpha_keys[0].t = 0.0f;
    e.alpha_keys[0].v = 1.0f;

    std::vector<renderer::ParticleEmitterDescriptor> emitters{e};
    pass.render(emitters, world, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // Empty list must also be clean.
    pass.render({}, world, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// ── Test 2: empty emitter list never touches GL state (early-return guard) ──
TEST_F(ParticlePassTest, EmptyListProducesNoGlError) {
    renderer::ParticlePass pass;
    scenegraph::World world;
    scenegraph::Camera camera;
    camera.eye    = {0.0f, 0.0f, 50.0f};
    camera.target = {0.0f, 0.0f,  0.0f};
    camera.aspect = 1.0f;

    while (glGetError() != GL_NO_ERROR) {}
    pass.render({}, world, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
