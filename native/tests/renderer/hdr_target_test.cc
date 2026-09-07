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

// The breach scoop stencil-tests against "was hull cut away here?", so the
// target must actually carry a stencil plane — and must still be complete and
// keep its 24-bit depth, since DOF and the volumetric nebula sample it.
TEST_F(HdrTargetTest, CarriesAStencilPlane) {
    renderer::HdrTarget t;
    t.resize(64, 64);
    t.bind();
    ASSERT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE);

    // GL_STENCIL_ATTACHMENT, not GL_STENCIL: the bare GL_DEPTH / GL_STENCIL
    // enums are only legal on the DEFAULT framebuffer and raise INVALID_ENUM
    // (and report 0 bits) against an FBO.
    GLint stencil_bits = 0;
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT,
                                          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE,
                                          &stencil_bits);
    EXPECT_GE(stencil_bits, 8)
        << "no stencil plane — the breach pass's stencil test would silently "
           "always pass, putting scoops back in open space";

    // The depth half must still read as depth: DEPTH_STENCIL_TEXTURE_MODE
    // defaults to GL_DEPTH_COMPONENT, so existing depth samplers are unaffected.
    GLint depth_bits = 0;
    glGetFramebufferAttachmentParameteriv(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                          GL_FRAMEBUFFER_ATTACHMENT_DEPTH_SIZE,
                                          &depth_bits);
    EXPECT_GE(depth_bits, 24);

    // A stencil write/clear round-trip proves the plane is live, not just sized.
    glStencilMask(0xFF);
    glClearStencil(3);
    glClear(GL_STENCIL_BUFFER_BIT);
    GLint got = 0;
    glGetIntegerv(GL_STENCIL_CLEAR_VALUE, &got);
    EXPECT_EQ(got, 3);
    glClearStencil(0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
