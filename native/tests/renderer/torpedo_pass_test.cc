// native/tests/renderer/torpedo_pass_test.cc
//
// GL smoke tests for renderer::TorpedoPass's Task 6 rewrite: BC's audited
// billboard-root construction (spinning camera-facing frame carrying two
// glow quads, a flare star, and a core sprite -- weapon-firing-mechanics.md
// §5.5). Verifies the pass renders without a GL error for (a) a
// photon-style descriptor (8 flares), (b) a zero-flare descriptor, and (c)
// an is_disruptor descriptor, which must be skipped entirely -- disruptor
// bolts render via a dedicated tube-mesh pass added in Task 7. Follows the
// ParticlePass/DustPass GL-fixture pattern (skip when no offscreen GL
// context or when the BC sprite assets are absent).
//
// The flare phase de-phasing itself (hash01 varying by index for a fixed
// id) is generically locked by torpedo_anim_test.cc (Task 4,
// TorpedoAnimHash.DiffersAcrossIndex); the test below pins the SAME
// property at the specific salt (1u) the pass actually uses for the
// twinkle-phase offset, without duplicating the generic coverage.

#include <gtest/gtest.h>

#include <renderer/torpedo_pass.h>
#include <renderer/torpedo_anim.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <renderer/frame.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdint>
#include <filesystem>
#include <memory>
#include <vector>

namespace {

std::filesystem::path project_root() {
    return std::filesystem::path(__FILE__)
        .parent_path()   // native/tests/renderer
        .parent_path()   // native/tests
        .parent_path()   // native
        .parent_path();  // project root
}

renderer::TorpedoDescriptor make_photon_descriptor(const std::filesystem::path& root) {
    renderer::TorpedoDescriptor d;
    d.world_pos = glm::vec3(0.0f, 0.0f, 0.0f);
    d.core_texture   = (root / "game" / "data" / "Textures" / "Tactical" / "TorpedoCore.tga").string();
    d.core_color     = glm::vec4(1.0f);
    d.core_size_a    = 0.2f;
    d.core_size_b    = 1.2f;
    d.glow_texture   = (root / "game" / "data" / "Textures" / "Tactical" / "TorpedoGlow.tga").string();
    d.glow_color     = glm::vec4(1.0f);
    d.glow_size_a    = 3.0f;
    d.glow_size_b    = 0.3f;
    d.glow_size_c    = 0.6f;
    d.flares_texture = (root / "game" / "data" / "Textures" / "Tactical" / "TorpedoFlares.tga").string();
    d.flares_color   = glm::vec4(1.0f);
    d.num_flares     = 8;
    d.flares_size_a  = 0.7f;
    d.flares_size_b  = 0.4f;
    d.age            = 0.35f;
    d.id             = 42;
    d.is_disruptor   = false;
    return d;
}

class TorpedoPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(64, 64, "torpedo-test", false);
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

}  // namespace

TEST_F(TorpedoPassTest, PhotonStyleDescriptorRendersWithoutGlError) {
    namespace fs = std::filesystem;
    const fs::path root = project_root();
    renderer::TorpedoDescriptor d = make_photon_descriptor(root);
    if (!fs::is_regular_file(d.core_texture) || !fs::is_regular_file(d.glow_texture) ||
        !fs::is_regular_file(d.flares_texture)) {
        GTEST_SKIP() << "BC torpedo sprite assets absent under " << root;
    }

    renderer::TorpedoPass pass;
    scenegraph::Camera camera;
    camera.eye    = glm::vec3(0.0f, 0.0f, 100.0f);
    camera.target = glm::vec3(0.0f, 0.0f,   0.0f);
    camera.up     = glm::vec3(0.0f, 1.0f,   0.0f);
    camera.aspect = 1.0f;

    while (glGetError() != GL_NO_ERROR) {}
    pass.render({d}, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(TorpedoPassTest, ZeroFlareDescriptorRendersWithoutGlError) {
    namespace fs = std::filesystem;
    const fs::path root = project_root();
    renderer::TorpedoDescriptor d = make_photon_descriptor(root);
    d.num_flares = 0;
    if (!fs::is_regular_file(d.core_texture) || !fs::is_regular_file(d.glow_texture)) {
        GTEST_SKIP() << "BC torpedo sprite assets absent under " << root;
    }

    renderer::TorpedoPass pass;
    scenegraph::Camera camera;
    camera.eye    = glm::vec3(0.0f, 0.0f, 100.0f);
    camera.target = glm::vec3(0.0f, 0.0f,   0.0f);
    camera.up     = glm::vec3(0.0f, 1.0f,   0.0f);
    camera.aspect = 1.0f;

    while (glGetError() != GL_NO_ERROR) {}
    pass.render({d}, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(TorpedoPassTest, DisruptorDescriptorIsSkippedNotCrashed) {
    namespace fs = std::filesystem;
    const fs::path root = project_root();
    renderer::TorpedoDescriptor d = make_photon_descriptor(root);
    d.is_disruptor = true;
    if (!fs::is_regular_file(d.core_texture)) {
        GTEST_SKIP() << "BC torpedo sprite assets absent under " << root;
    }

    renderer::TorpedoPass pass;
    scenegraph::Camera camera;
    camera.eye    = glm::vec3(0.0f, 0.0f, 100.0f);
    camera.target = glm::vec3(0.0f, 0.0f,   0.0f);
    camera.aspect = 1.0f;

    while (glGetError() != GL_NO_ERROR) {}
    // Must not crash; the pass's `continue` on is_disruptor skips the whole
    // torpedo -- Task 7 renders disruptor bolts via a dedicated tube mesh.
    pass.render({d}, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(TorpedoPassTest, EmptyListProducesNoGlError) {
    renderer::TorpedoPass pass;
    scenegraph::Camera camera;
    camera.eye    = glm::vec3(0.0f, 0.0f, 50.0f);
    camera.target = glm::vec3(0.0f, 0.0f,  0.0f);
    camera.aspect = 1.0f;

    while (glGetError() != GL_NO_ERROR) {}
    pass.render({}, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// ─────────────────────────────────────────────────────────────────────────
// Pure-math: flare-phase de-phasing at the ACTUAL salt (1u) the pass uses
// for the per-flare twinkle-phase offset. torpedo_anim_test.cc (Task 4,
// TorpedoAnimHash.DiffersAcrossIndex) already locks hash01's general
// "differs across index" property; this pins it at the specific call site.
// ─────────────────────────────────────────────────────────────────────────
TEST(TorpedoPassFlarePhase, DePhasesAcrossFlareIndexForFixedId) {
    const uint32_t id = 42u;
    const float first = renderer::hash01(id, 0u, 1u);
    bool any_diff = false;
    for (uint32_t i = 1; i < 8u; ++i) {
        if (renderer::hash01(id, i, 1u) != first) { any_diff = true; break; }
    }
    EXPECT_TRUE(any_diff);
}
