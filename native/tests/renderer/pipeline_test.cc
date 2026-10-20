// native/tests/renderer/pipeline_test.cc
#include <gtest/gtest.h>

#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <glad/glad.h>

namespace {

class PipelineTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "pipeline-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
    }
};

TEST_F(PipelineTest, OpaqueShaderCompilesAndLinks) {
    renderer::Pipeline p;
    EXPECT_NE(p.opaque_shader().program(), 0u);
}

// SPIKE (damage redesign): the PLATING variant compiles and links, carries
// the compact damage list, and the stock program carries none of the
// plating layer (it is gated out of opaque.frag by #ifdef PLATING).
TEST_F(PipelineTest, PlatingShaderCompilesAndOnlyItHasThePlatingLayer) {
    renderer::Pipeline p;
    const GLuint plating = p.plating_shader().program();
    ASSERT_NE(plating, 0u);
    EXPECT_NE(plating, p.opaque_shader().program());
    EXPECT_GE(glGetUniformLocation(plating, "u_dmg_count"), 0);
    EXPECT_GE(glGetUniformLocation(plating, "u_dmg_a"), 0);
    EXPECT_GE(glGetUniformLocation(plating, "u_plating"), 0);
    const GLuint stock = p.opaque_shader().program();
    EXPECT_EQ(glGetUniformLocation(stock, "u_dmg_count"), -1);
    EXPECT_EQ(glGetUniformLocation(stock, "u_plating"), -1);
    EXPECT_EQ(glGetUniformLocation(stock, "u_plating_two_sided"), -1);
    EXPECT_EQ(glGetUniformLocation(stock, "u_part_count"), -1);
}

TEST_F(PipelineTest, SunShaderCompilesAndLinks) {
    renderer::Pipeline p;
    EXPECT_NE(p.sun_shader().program(), 0u);
}

TEST_F(PipelineTest, SkyboxShaderCompilesAndLinks) {
    renderer::Pipeline p;
    EXPECT_NE(p.skybox_shader().program(), 0u);
}

TEST_F(PipelineTest, BridgeShadersAvailable) {
    renderer::Pipeline p;
    EXPECT_NE(p.bridge_shader().program(), 0u);
    EXPECT_NE(p.skinned_bridge_shader().program(), 0u);
}

TEST_F(PipelineTest, GlStateMatchesBCConvention) {
    renderer::Pipeline p;

    EXPECT_EQ(glIsEnabled(GL_DEPTH_TEST), static_cast<GLboolean>(GL_TRUE));
    EXPECT_EQ(glIsEnabled(GL_CULL_FACE),  static_cast<GLboolean>(GL_TRUE));

    GLint cull_face = 0;
    glGetIntegerv(GL_CULL_FACE_MODE, &cull_face);
    EXPECT_EQ(cull_face, GL_BACK);

    // NIFs are CW-wound for front faces (Gamebryo/D3D convention). Ship model
    // matrices are right-handed (det>0, no reflection) post the 2026-06-18
    // un-mirror, so those CW triangles present CCW front faces in screen space.
    // If this ever reads GL_CW again, BC ships render mirror-imaged. See
    // docs/superpowers/plans/2026-06-18-render-handedness-unmirror.md.
    GLint front_face = 0;
    glGetIntegerv(GL_FRONT_FACE, &front_face);
    EXPECT_EQ(front_face, GL_CCW);

    GLint depth_func = 0;
    glGetIntegerv(GL_DEPTH_FUNC, &depth_func);
    EXPECT_EQ(depth_func, GL_LESS);
}

}  // namespace
