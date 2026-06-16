// native/tests/renderer/deform_pipeline_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/pipeline.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include <glm/glm.hpp>
#include <vector>

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
        prog.set_mat4("u_ship_world", I);
        prog.set_mat4("u_ship_world_inv", I);
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

TEST(DeformPipeline, CraterDisplacesGeometry) {
    try {
        renderer::Window w(64, 64, "deform-displace-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        // Two CW-wound triangle patches forming a quad at z=0.
        // Pipeline::Pipeline() calls glFrontFace(GL_CW) to match BC NIF winding;
        // these triangles must wind CW (negative signed area) to be front-facing
        // and not culled.
        const float verts[] = {
            -0.8f, -0.8f, 0.0f,  0.8f,  0.8f, 0.0f,  0.8f, -0.8f, 0.0f,
            -0.8f, -0.8f, 0.0f, -0.8f,  0.8f, 0.0f,  0.8f,  0.8f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        // crushability (loc 7) isn't in this VBO; force it to 1 via a constant
        // generic vertex attribute so displacement is non-zero.
        glVertexAttrib1f(7, 1.0f);

        auto render = [&](int crater_count) {
            glViewport(0, 0, 64, 64);
            // Clear to mid-gray so uncovered pixels differ from the black
            // fragment output; coverage changes then produce a != b.
            glClearColor(0.5f, 0.5f, 0.5f, 1.0f);
            glClear(GL_COLOR_BUFFER_BIT);
            prog.use();
            glm::mat4 I(1.0f);
            prog.set_mat4("u_model", I);
            prog.set_mat4("u_view", I);
            prog.set_mat4("u_proj", I);
            prog.set_mat4("u_ship_world", I);
            prog.set_mat4("u_ship_world_inv", I);
            prog.set_int("u_crater_count", crater_count);
            if (crater_count > 0) {
                glm::vec4 ca(0.0f, 0.0f, 0.0f, 0.6f);   // point_body, depth
                glm::vec4 cb(1.0f, 0.0f, 0.0f, 2.0f);   // impact_dir +x, radius
                prog.set_vec4_array("u_crater_a", &ca, 1);
                prog.set_vec4_array("u_crater_b", &cb, 1);
            }
            while (glGetError() != GL_NO_ERROR) {}
            glPatchParameteri(GL_PATCH_VERTICES, 3);
            glDrawArrays(GL_PATCHES, 0, 6);
        };

        std::vector<unsigned char> a(64 * 64 * 4), b(64 * 64 * 4);
        render(0);
        glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, a.data());
        render(1);
        glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, b.data());
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        EXPECT_NE(a, b) << "crater displacement did not change the rendered image";

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
