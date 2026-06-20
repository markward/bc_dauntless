#include <gtest/gtest.h>
#include <memory>
#include "renderer/window.h"
#include "renderer/shadow_map_target.h"
#include <glad/glad.h>

class ShadowMapTargetTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> window;
    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(64, 64, "shadow-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
    }
};

TEST_F(ShadowMapTargetTest, ResizeAllocatesCompleteFramebuffer) {
    renderer::ShadowMapTarget t;
    t.resize(256, 256);
    EXPECT_NE(t.fbo(), 0u);
    EXPECT_NE(t.depth_texture(), 0u);
    EXPECT_EQ(t.width(), 256);
    glBindFramebuffer(GL_FRAMEBUFFER, t.fbo());
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}
