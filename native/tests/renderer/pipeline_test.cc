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

TEST_F(PipelineTest, SunShaderCompilesAndLinks) {
    renderer::Pipeline p;
    EXPECT_NE(p.sun_shader().program(), 0u);
}

TEST_F(PipelineTest, BridgeAndLightmapShadersAvailable) {
    renderer::Pipeline p;
    EXPECT_NE(p.bridge_shader().program(), 0u);
    EXPECT_NE(p.lightmap_shader().program(), 0u);
}

TEST_F(PipelineTest, GlStateMatchesBCConvention) {
    renderer::Pipeline p;

    EXPECT_EQ(glIsEnabled(GL_DEPTH_TEST), static_cast<GLboolean>(GL_TRUE));
    EXPECT_EQ(glIsEnabled(GL_CULL_FACE),  static_cast<GLboolean>(GL_TRUE));

    GLint cull_face = 0;
    glGetIntegerv(GL_CULL_FACE_MODE, &cull_face);
    EXPECT_EQ(cull_face, GL_BACK);

    // NIFs are CW-wound for front faces (Gamebryo/D3D convention). If this
    // assertion ever fails to GL_CCW, BC ships will render inside-out.
    GLint front_face = 0;
    glGetIntegerv(GL_FRONT_FACE, &front_face);
    EXPECT_EQ(front_face, GL_CW);

    GLint depth_func = 0;
    glGetIntegerv(GL_DEPTH_FUNC, &depth_func);
    EXPECT_EQ(depth_func, GL_LESS);
}

}  // namespace
