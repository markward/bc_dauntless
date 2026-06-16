// native/tests/renderer/tess_program_test.cc
#include <gtest/gtest.h>

#include <glad/glad.h>

#include <renderer/shader.h>
#include <renderer/window.h>

#include "embedded_passthrough_tess_vs.h"
#include "embedded_passthrough_tess_tcs.h"
#include "embedded_passthrough_tess_tes.h"
#include "embedded_passthrough_tess_fs.h"

namespace {

TEST(TessProgram, EmbeddedPassthroughCompilesLinksAndDraws) {
    try {
        renderer::Window w(64, 64, "tess-program-test", /*visible=*/false);

        renderer::Shader prog(renderer::shader_src::passthrough_tess_vs,
                              renderer::shader_src::passthrough_tess_tcs,
                              renderer::shader_src::passthrough_tess_tes,
                              renderer::shader_src::passthrough_tess_fs);
        ASSERT_NE(prog.program(), 0u);

        // One triangle patch (3 control points) in NDC.
        const float verts[] = {
            -0.5f, -0.5f, 0.0f,
             0.5f, -0.5f, 0.0f,
             0.0f,  0.5f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);

        glViewport(0, 0, 64, 64);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        prog.use();
        // Drain any benign errors left by context/shader init so the
        // post-draw glGetError() check only sees errors from our draw.
        while (glGetError() != GL_NO_ERROR) {}
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 3);

        // The pass-through FS writes white. Sample an interior pixel (inside
        // the triangle on all three edges); it must be lit, proving the
        // tessellated patch rasterized.
        unsigned char px[4] = {0, 0, 0, 0};
        glReadPixels(32, 24, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);

        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        EXPECT_GT(px[0], 200);  // red channel ~white

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
