#include <gtest/gtest.h>

#include <renderer/cubemap_target.h>
#include <renderer/window.h>

#include <glad/glad.h>

#include <memory>

TEST(CubemapTarget, AllocatesCompleteFboAndBindsAllFaces) {
    std::unique_ptr<renderer::Window> w;
    try {
        w = std::make_unique<renderer::Window>(64, 64, "cubemap-test", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }

    renderer::CubemapTarget cube;
    ASSERT_TRUE(cube.allocate(128));
    EXPECT_TRUE(cube.valid());
    EXPECT_EQ(cube.face_size(), 128);
    EXPECT_NE(cube.texture(), 0u);

    for (int i = 0; i < 6; ++i) {
        cube.bind_face(i);
        EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER), GL_FRAMEBUFFER_COMPLETE)
            << "cube face " << i << " incomplete";
    }
    cube.generate_mips();

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
