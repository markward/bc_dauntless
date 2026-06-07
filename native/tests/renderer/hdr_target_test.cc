// native/tests/renderer/hdr_target_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/hdr_target.h>
#include <renderer/window.h>
#include <memory>

namespace {

class HdrTargetTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64, 64, "hdr-test", false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

TEST_F(HdrTargetTest, CreatesCompleteFramebuffer) {
    renderer::HdrTarget t;
    t.resize(128, 96);
    EXPECT_EQ(t.width(), 128);
    EXPECT_EQ(t.height(), 96);
    EXPECT_NE(t.color_texture(), 0u);
    t.bind();
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(HdrTargetTest, ResizeReallocatesAndStaysComplete) {
    renderer::HdrTarget t;
    t.resize(100, 100);
    GLuint first = t.color_texture();
    t.resize(100, 100);                 // same size: no-op, keep texture
    EXPECT_EQ(t.color_texture(), first);
    t.resize(200, 150);                 // new size: reallocate
    t.bind();
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);
    EXPECT_EQ(t.width(), 200);
    EXPECT_EQ(t.height(), 150);
}

}  // namespace
