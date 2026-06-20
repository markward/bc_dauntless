#include <gtest/gtest.h>
#include <glad/glad.h>
#include <renderer/smaa_pass.h>
#include <renderer/window.h>
#include <memory>
#include <vector>

namespace {
class SmaaPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try { w = std::make_unique<renderer::Window>(64,64,"smaa-test",false); }
        catch (const std::runtime_error& e) { GTEST_SKIP() << "no GL: " << e.what(); }
    }
};

// A synthetic LDR input with a hard vertical edge, fed through SMAA, must
// produce GL-error-free non-black output in the backbuffer.
TEST_F(SmaaPassTest, RunsThreePassesErrorFreeAndProducesOutput) {
    // Build a 64x64 source texture: left half white, right half black.
    GLuint src = 0;
    glGenTextures(1, &src);
    glBindTexture(GL_TEXTURE_2D, src);
    std::vector<unsigned char> px(64*64*4, 0);
    for (int y = 0; y < 64; ++y)
        for (int x = 0; x < 32; ++x) {
            int i = (y*64 + x) * 4;
            px[i] = px[i+1] = px[i+2] = 255; px[i+3] = 255;
        }
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 64, 64, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, px.data());

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 64, 64);
    glClearColor(0,0,0,1);
    glClear(GL_COLOR_BUFFER_BIT);

    renderer::SmaaPass smaa;
    smaa.draw(src, /*dest_fbo=*/0, 64, 64);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    // The white half should still read white where unaffected by edge blending.
    unsigned char out[4] = {0,0,0,0};
    glReadPixels(8, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, out);
    EXPECT_GT(out[0], 200);  // non-black, ~white
    glDeleteTextures(1, &src);
}
}  // namespace
