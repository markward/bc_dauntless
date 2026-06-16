// native/tests/renderer/deform_pipeline_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/pipeline.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include <glm/glm.hpp>

#include "embedded_opaque_deform_vs.h"
#include "embedded_opaque_deform_tcs.h"
#include "embedded_opaque_deform_tes.h"
#include "embedded_opaque_fs.h"

namespace {

TEST(DeformPipeline, ProgramLinksWithOpaqueFragment) {
    try {
        renderer::Window w(64, 64, "deform-link-test", /*visible=*/false);
        // 410 tess stages + 330 opaque fragment: mixed-version program must
        // link, and the TES out-varyings must match opaque.frag in-varyings.
        renderer::Shader prog(renderer::shader_src::opaque_deform_vs,
                              renderer::shader_src::opaque_deform_tcs,
                              renderer::shader_src::opaque_deform_tes,
                              renderer::shader_src::opaque_fs);
        ASSERT_NE(prog.program(), 0u);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

TEST(DeformPipeline, PipelineExposesDeformShaderWhenTessellationAvailable) {
    try {
        renderer::Window w(64, 64, "deform-pipeline-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        // The test GL context is >= 4.1, so tessellation is available and the
        // deform program is built.
        EXPECT_TRUE(pipeline.tessellation_available());
        EXPECT_NE(pipeline.deform_shader().program(), 0u);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

TEST(DeformPipeline, IdentityPatchRasterizes) {
    try {
        renderer::Window w(64, 64, "deform-identity-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        // One triangle patch in NDC, fed straight through (identity model/view/
        // proj), crater count 0 -> no displacement. Attribute 0 = position;
        // attributes 1,2,7 default to 0 (unused by the identity output path).
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
        glm::mat4 I(1.0f);
        prog.set_mat4("u_model", I);
        prog.set_mat4("u_view", I);
        prog.set_mat4("u_proj", I);
        prog.set_int("u_crater_count", 0);
        while (glGetError() != GL_NO_ERROR) {}
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 3);

        unsigned char px[4] = {0, 0, 0, 0};
        glReadPixels(32, 24, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        EXPECT_EQ(px[3], 255);  // opaque.frag always writes alpha=1 at covered fragments

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
