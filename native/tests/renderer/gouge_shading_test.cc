// native/tests/renderer/gouge_shading_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/pipeline.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include <filesystem>

namespace {

GLuint make_solid_texture(unsigned char r, unsigned char g, unsigned char b) {
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    const unsigned char px[4] = {r, g, b, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    return tex;
}

TEST(GougeShading, DeepDisplacementShowsDamageTexture) {
    try {
        renderer::Window w(64, 64, "gouge-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        // CW-wound quad patches (matching Pipeline's glFrontFace(GL_CW)):
        //   Triangle 1: bottom-left, top-right, bottom-right   (CW signed area < 0)
        //   Triangle 2: bottom-left, top-left,  top-right      (CW signed area < 0)
        // These are front-facing and survive culling, giving a covered centre pixel.
        const float verts[] = {
            -0.9f, -0.9f, 0.0f,  0.9f,  0.9f, 0.0f,  0.9f, -0.9f, 0.0f,
            -0.9f, -0.9f, 0.0f, -0.9f,  0.9f, 0.0f,  0.9f,  0.9f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        glVertexAttrib1f(7, 1.0f);  // crushability = 1

        GLuint dmg = make_solid_texture(255, 0, 255);    // magenta interior
        GLuint white = make_solid_texture(255, 255, 255); // base
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, white);
        glActiveTexture(GL_TEXTURE3); glBindTexture(GL_TEXTURE_2D, dmg);

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
        prog.set_int("u_base_color", 0);
        prog.set_int("u_damage_texture", 3);
        prog.set_vec3("u_ambient_light", glm::vec3(1.0f));
        prog.set_int("u_dir_light_count", 0);
        prog.set_vec3("u_diffuse_color", glm::vec3(1.0f));
        prog.set_float("u_emissive_scale", 0.0f);
        prog.set_int("u_decal_count", 0);
        prog.set_int("u_glow_region_count", 0);
        prog.set_int("u_crater_count", 1);
        glm::vec4 ca(0.0f, 0.0f, 0.0f, 0.6f);   // point_body (0,0,0), depth 0.6 model units
        glm::vec4 cb(0.0f, 0.0f, -1.0f, 0.5f);  // impact_dir -z, radius 0.5
        prog.set_vec4_array("u_crater_a", &ca, 1);
        prog.set_vec4_array("u_crater_b", &cb, 1);

        while (glGetError() != GL_NO_ERROR) {}
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 6);

        unsigned char center[4] = {0, 0, 0, 0};
        glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        // Gouge fill pulls the centre toward magenta (G channel drops). Without
        // gouge the centre would be lit white (G high).
        EXPECT_LT(center[1], 200) << "centre should show gouge fill (G pulled down by magenta), not lit white; center=("
            << (int)center[0] << "," << (int)center[1] << "," << (int)center[2] << "," << (int)center[3] << ")";

        glDeleteTextures(1, &dmg);
        glDeleteTextures(1, &white);
        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

TEST(GougeShading, PipelineLoadsDamageTextureWhenPresent) {
    try {
        renderer::Window w(64, 64, "dmg-load-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        const bool asset_present =
            std::filesystem::exists("game/data/Textures/Effects/Damage.tga");
        if (asset_present) {
            EXPECT_NE(pipeline.damage_texture(), 0u)
                << "Damage.tga present but Pipeline did not load it";
        } else {
            GTEST_SKIP() << "Damage.tga not present (game/ absent) — load path "
                            "falls back; nothing to assert";
        }
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
