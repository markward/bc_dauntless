// native/tests/renderer/torpedo_pass_test.cc
//
// GL smoke tests for renderer::TorpedoPass, which renders BOTH BC
// projectile families from one descriptor list:
//
//   TORPEDO (Task 6): BC's audited billboard-root construction (spinning
//   camera-facing frame carrying two glow quads, a flare star, and a core
//   sprite -- weapon-firing-mechanics.md §5.5). Verifies the pass renders
//   without a GL error for (a) a photon-style descriptor (8 flares) and (b)
//   a zero-flare descriptor.
//
//   DISRUPTOR (Task 7): a procedural tapered-tube mesh re-oriented onto the
//   velocity vector every frame, drawn as two concentric uniform-color
//   sub-draws (shell + core). Verifies GL_NO_ERROR for a disruptor
//   descriptor, a mixed torpedo+disruptor list, the two degenerate
//   `bolt_align_rotation` forward directions (+Y/-Y) driven through the
//   full draw, and that a zero-length/zero-width bolt is skipped rather
//   than drawn degenerate. A separate pixel-readback test
//   (DisruptorBoltDrawsVisiblePixelAtBoltAxis) is the one test in this file
//   that is genuinely RED-able against the pre-Task-7 code: every
//   GL_NO_ERROR assertion above is trivially satisfied even by the old
//   `continue`-and-skip behaviour (skipping never raises a GL error), so
//   only a check that something was actually DRAWN can distinguish
//   "rendered" from "silently skipped".
//
// Follows the ParticlePass/DustPass GL-fixture pattern (skip when no
// offscreen GL context or when the BC sprite assets are absent).
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

#include <array>
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

// Disruptor.py's actual SDK values (audited, brief-verbatim): shell/core
// colors, bolt_length, bolt_width, and forward. No textures -- disruptor
// bolts are untextured flat-shaded tube geometry.
renderer::TorpedoDescriptor make_disruptor_descriptor() {
    renderer::TorpedoDescriptor d;
    d.world_pos       = glm::vec3(0.0f, 0.0f, 0.0f);
    d.is_disruptor    = true;
    d.forward         = glm::vec3(0.0f, 0.0f, 1.0f);
    d.shell_color     = glm::vec4(0.0078f, 1.0f, 0.0078f, 1.0f);
    d.bolt_core_color = glm::vec4(0.639f,  1.0f, 0.639f,  1.0f);
    d.bolt_length     = 2.0f;
    d.bolt_width      = 0.2f;
    d.age             = 0.0f;
    d.id              = 7;
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

// Task 7: a disruptor descriptor now draws via the tapered-tube path
// (shell + core concentric sub-draws through the disruptor program) rather
// than being skipped. No BC sprite assets are needed -- disruptor bolts are
// untextured.
TEST_F(TorpedoPassTest, DisruptorDescriptorRendersWithoutGlError) {
    renderer::TorpedoDescriptor d = make_disruptor_descriptor();

    renderer::TorpedoPass pass;
    scenegraph::Camera camera;
    camera.eye    = glm::vec3(0.0f, 0.0f, 100.0f);
    camera.target = glm::vec3(0.0f, 0.0f,   0.0f);
    camera.up     = glm::vec3(0.0f, 1.0f,   0.0f);
    camera.aspect = 1.0f;

    while (glGetError() != GL_NO_ERROR) {}
    pass.render({d}, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // GL state left as the pass found it (mirrors the state the pass itself
    // restores at the end of render(), see torpedo_pass.cc).
    EXPECT_TRUE(glIsEnabled(GL_CULL_FACE));
    GLboolean depth_mask = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);
    EXPECT_TRUE(depth_mask);
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
}

// A mixed list exercises both program-switch sub-loops in the same render()
// call (torpedo sub-loop then disruptor sub-loop) without a per-entry
// program thrash bug corrupting either family's draw.
TEST_F(TorpedoPassTest, MixedTorpedoAndDisruptorListRendersWithoutGlError) {
    namespace fs = std::filesystem;
    const fs::path root = project_root();
    renderer::TorpedoDescriptor torpedo = make_photon_descriptor(root);
    if (!fs::is_regular_file(torpedo.core_texture) ||
        !fs::is_regular_file(torpedo.glow_texture) ||
        !fs::is_regular_file(torpedo.flares_texture)) {
        GTEST_SKIP() << "BC torpedo sprite assets absent under " << root;
    }
    renderer::TorpedoDescriptor disruptor = make_disruptor_descriptor();

    renderer::TorpedoPass pass;
    scenegraph::Camera camera;
    camera.eye    = glm::vec3(0.0f, 0.0f, 100.0f);
    camera.target = glm::vec3(0.0f, 0.0f,   0.0f);
    camera.up     = glm::vec3(0.0f, 1.0f,   0.0f);
    camera.aspect = 1.0f;

    while (glGetError() != GL_NO_ERROR) {}
    pass.render({torpedo, disruptor}, camera, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// bolt_align_rotation's two degenerate inputs (forward ~= +Y / forward ~= -Y)
// are pure-math lock-tested in torpedo_anim_test.cc; these two drive the SAME
// degenerate paths through the full GL draw (model matrix construction +
// upload + glDrawElements) to catch anything the pure-math test can't see
// (e.g. a NaN model matrix reaching the GPU).
TEST_F(TorpedoPassTest, DisruptorDegenerateForwardPlusYRendersWithoutGlError) {
    renderer::TorpedoDescriptor d = make_disruptor_descriptor();
    d.forward = glm::vec3(0.0f, 1.0f, 0.0f);

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

TEST_F(TorpedoPassTest, DisruptorDegenerateForwardMinusYRendersWithoutGlError) {
    renderer::TorpedoDescriptor d = make_disruptor_descriptor();
    d.forward = glm::vec3(0.0f, -1.0f, 0.0f);

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

TEST_F(TorpedoPassTest, DisruptorZeroLengthBoltIsSkippedWithoutGlError) {
    renderer::TorpedoDescriptor d = make_disruptor_descriptor();
    d.bolt_length = 0.0f;

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

TEST_F(TorpedoPassTest, DisruptorZeroWidthBoltIsSkippedWithoutGlError) {
    renderer::TorpedoDescriptor d = make_disruptor_descriptor();
    d.bolt_width = 0.0f;

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

// The one genuinely RED-able test in this file (see the file-top comment):
// a large, camera-crossing bolt MUST leave a non-background pixel at frame
// centre. Against the pre-Task-7 `continue`-and-skip code this pixel stays
// the clear color -- a real behavioral failure, not just a GL-error check.
TEST_F(TorpedoPassTest, DisruptorBoltDrawsVisiblePixelAtBoltAxis) {
    constexpr int kSize = 64;
    renderer::TorpedoDescriptor d = make_disruptor_descriptor();
    // Large and crossing the camera's view axis broadside (forward
    // perpendicular to the view direction) so the tube's silhouette is
    // guaranteed to cover the centre pixel regardless of the exact taper
    // profile -- this is a visibility smoke test, not a geometry-precision
    // test (that's torpedo_anim_test.cc's job).
    d.forward     = glm::vec3(1.0f, 0.0f, 0.0f);
    d.bolt_length = 4.0f;
    d.bolt_width  = 2.0f;

    renderer::TorpedoPass pass;
    scenegraph::Camera camera;
    camera.eye        = glm::vec3(0.0f, 0.0f, 5.0f);
    camera.target     = glm::vec3(0.0f, 0.0f, 0.0f);
    camera.up         = glm::vec3(0.0f, 1.0f, 0.0f);
    camera.fov_y_rad  = glm::radians(45.0f);
    camera.aspect     = 1.0f;
    camera.near       = 0.1f;
    camera.far        = 50.0f;

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, kSize, kSize);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    while (glGetError() != GL_NO_ERROR) {}
    pass.render({d}, camera, *pipeline);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    glFinish();

    std::array<unsigned char, 4> px{0, 0, 0, 0};
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    glReadPixels(kSize / 2, kSize / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
    // shell_color's green channel is 1.0 (0.639 for the core) -- either
    // sub-draw covering the centre pixel lights up G well above the black
    // clear color.
    EXPECT_GT(px[1], 40)
        << "centre pixel stayed near background -- disruptor bolt did not "
           "draw (g=" << static_cast<int>(px[1]) << ")";
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
