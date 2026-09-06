// native/tests/renderer/cloak_pass_test.cc
//
// Pins the claim made at cloak_pass.cc's u_ambient_light call site: "Same
// lighting the opaque pass uses, so the cloaked hull shades identically
// (matched brightness -- no lit/unlit pop when the hull hands over)."
//
// Before this test, cloak_pass.cc pushed u_ambient_light only, never
// u_ambient_dir_ws / u_ambient_gradient, and cloak_refraction.frag had no
// ambient-gradient term at all. With the gradient on by default that made
// the comment false: the opaque hull's ambient dims on the shadow side of
// the ambient direction, but the cloak shell stayed flat -- a real
// brightness step at hand-over that nothing pinned.
//
// Strategy mirrors HullClipTest: draw a single oversized fullscreen triangle
// through each shader in turn with an explicit, controlled vertex normal (a
// disabled vertex attribute's "current value", like HullClipTest's a_normal)
// and read back the centre texel. u_frac is set to a small-but-nonzero value
// so CloakRefractionPass's `if (s.frac <= 0.0f) continue;` production gate
// isn't exercised here (this test drives the shader program directly, not
// through CloakRefractionPass::render), and so the shell's hull_alpha sits
// close enough to 1.0 (mix(1, cloaked_alpha, smoothstep(0,1,frac)) with
// frac == 0.001) that the composited pixel is dominated by the shaded
// surface term, not the refracted-background blend -- isolating the ambient
// computation this test actually cares about.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <renderer/pipeline.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include <array>
#include <memory>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

class CloakAmbientParityTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;
    GLuint vao_        = 0;
    GLuint vbo_        = 0;
    GLuint white_tex_  = 0;
    GLuint black_tex_  = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "cloak-ambient-parity-test",
                                                    false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }

        pipeline = std::make_unique<renderer::Pipeline>();

        // Oversized CCW triangle covering the whole viewport in clip space
        // (identity view/proj), matching HullClipTest's fixture.
        const float verts[9] = {
            -1.0f, -1.0f, 0.0f,
             3.0f, -1.0f, 0.0f,
            -1.0f,  3.0f, 0.0f,
        };
        glGenVertexArrays(1, &vao_);
        glGenBuffers(1, &vbo_);
        glBindVertexArray(vao_);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, nullptr);
        // a_normal (location 1) and a_uv (location 2) are left as disabled
        // arrays; both shaders under test then read the constant "current
        // value" set below instead of a per-vertex array.
        glVertexAttrib2f(2, 0.0f, 0.0f);
        glBindVertexArray(0);

        white_tex_ = make_tex(255, 255, 255);
        black_tex_ = make_tex(0, 0, 0);
    }

    void TearDown() override {
        if (vbo_)       { glDeleteBuffers(1, &vbo_);        vbo_       = 0; }
        if (vao_)       { glDeleteVertexArrays(1, &vao_);   vao_       = 0; }
        if (white_tex_) { glDeleteTextures(1, &white_tex_); white_tex_ = 0; }
        if (black_tex_) { glDeleteTextures(1, &black_tex_); black_tex_ = 0; }
    }

    static GLuint make_tex(unsigned char r, unsigned char g, unsigned char b) {
        GLuint t = 0;
        glGenTextures(1, &t);
        glBindTexture(GL_TEXTURE_2D, t);
        const unsigned char px[4] = {r, g, b, 255};
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, px);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        return t;
    }

    // Minimum uniforms opaque.frag/opaque.vert need for this fixture.
    void set_opaque_uniforms(renderer::Shader& s, const glm::vec3& normal,
                             const glm::vec3& ambient_dir, float gradient) {
        s.use();
        s.set_mat4("u_view",  glm::mat4(1.0f));
        s.set_mat4("u_proj",  glm::mat4(1.0f));
        s.set_mat4("u_model", glm::mat4(1.0f));
        s.set_mat4("u_ship_world_inv", glm::mat4(1.0f));
        s.set_vec3("u_ambient_light",    glm::vec3(1.0f));
        s.set_vec3("u_ambient_dir_ws",   ambient_dir);
        s.set_float("u_ambient_gradient", gradient);
        s.set_int("u_dir_light_count",  0);
        s.set_vec3("u_camera_pos_ws",   glm::vec3(0.0f, 0.0f, 1.0f));
        s.set_vec3("u_diffuse_color",   glm::vec3(1.0f));
        s.set_vec3("u_emissive_color",  glm::vec3(0.0f));
        s.set_float("u_emissive_scale", 1.0f);
        s.set_int("u_specular_enabled", 0);
        s.set_vec3("u_specular_color",  glm::vec3(0.0f));
        s.set_float("u_specular_power", 1.0f);
        s.set_float("u_rim_strength",   0.0f);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, white_tex_);
        s.set_int("u_base_color", 0);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, black_tex_);
        s.set_int("u_glow_map", 1);
        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_2D, black_tex_);
        s.set_int("u_specular_map", 2);
        s.set_int("u_shadows_enabled", 0);
        s.set_int("u_shadow_map", 5);
        s.set_int("u_decal_count",       0);
        s.set_float("u_decal_time",      0.0f);
        s.set_int("u_glow_region_count", 0);
        s.set_int("u_carve_enabled", 0);
        s.set_int("u_carve_count", 0);
        {
            std::array<glm::vec3, 24> normals;
            normals.fill(glm::vec3(0.0f, 0.0f, 1.0f));
            s.set_vec3_array("u_carve_normals", normals.data(),
                             static_cast<int>(normals.size()));
        }
        glActiveTexture(GL_TEXTURE0);
        glBindVertexArray(vao_);
        glVertexAttrib3f(1, normal.x, normal.y, normal.z);
    }

    // Minimum uniforms cloak_refraction.vert/frag need for this fixture.
    // Everything that would blend in the refracted background or add glow /
    // tint is zeroed so the composited pixel isolates the ambient term.
    void set_cloak_uniforms(renderer::Shader& s, const glm::vec3& normal,
                            const glm::vec3& ambient_dir, float gradient) {
        s.use();
        s.set_mat4 ("u_model",     glm::mat4(1.0f));
        s.set_mat4 ("u_view_proj", glm::mat4(1.0f));
        s.set_float("u_time",           0.0f);
        s.set_float("u_frac",           0.001f);  // near-0: shell reads ~opaque
        s.set_float("u_shimmer_speed",  0.0f);
        s.set_float("u_vertex_wobble",  0.0f);
        s.set_vec3 ("u_camera_pos",     glm::vec3(0.0f, 0.0f, 1.0f));
        s.set_vec2 ("u_viewport",       glm::vec2(float(kW), float(kH)));
        s.set_float("u_strength",       0.0f);   // no screen-space refraction
        s.set_float("u_dispersion",     0.0f);
        s.set_vec3 ("u_tint",           glm::vec3(0.0f));
        s.set_float("u_opacity_floor",  0.1f);
        s.set_float("u_opacity_ceiling",0.5f);
        s.set_float("u_shimmer_amp",    0.0f);
        s.set_float("u_normal_bias",    0.0f);
        s.set_vec3 ("u_diffuse_color",  glm::vec3(1.0f));
        s.set_vec3 ("u_ambient_light",    glm::vec3(1.0f));
        s.set_vec3 ("u_ambient_dir_ws",   ambient_dir);
        s.set_float("u_ambient_gradient", gradient);
        s.set_int  ("u_dir_light_count", 0);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, white_tex_);  // stand-in scene copy
        s.set_int("u_scene", 0);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, white_tex_);
        s.set_int("u_base_color", 1);
        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_2D, black_tex_);  // glow map: no glow contribution
        s.set_int("u_glow_map", 2);
        glActiveTexture(GL_TEXTURE0);
        glBindVertexArray(vao_);
        glVertexAttrib3f(1, normal.x, normal.y, normal.z);
    }

    std::array<unsigned char, 4> draw_and_read() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, kW, kH);
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_BLEND);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glBindVertexArray(0);
        glFinish();
        std::array<unsigned char, 4> px{0, 0, 0, 0};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }
};

}  // namespace

// The property the cloak_pass.cc comment asserts: for the same normal and
// the same lighting (including the ambient-gradient pair), the cloak shell
// and the opaque hull shade to the same brightness. Checked on both the
// ambient-direction-facing normal and its opposite, so this would catch
// either a missing uniform (flat cloak ambient regardless of normal) or a
// sign/formula mismatch between the two shaders' amb/amb_d blocks.
TEST_F(CloakAmbientParityTest, MatchesOpaqueOnLitAndShadowSide) {
    const glm::vec3 ambient_dir(1.0f, 0.0f, 0.0f);
    constexpr float kGradient = 0.6f;

    for (glm::vec3 normal : {glm::vec3(1.0f, 0.0f, 0.0f),
                             glm::vec3(-1.0f, 0.0f, 0.0f)}) {
        renderer::Shader& opaque_prog = pipeline->opaque_shader();
        set_opaque_uniforms(opaque_prog, normal, ambient_dir, kGradient);
        auto opaque_px = draw_and_read();
        ASSERT_EQ(glGetError(), GL_NO_ERROR) << "GL error drawing opaque hull";

        renderer::Shader& cloak_prog = pipeline->cloak_refraction_shader();
        set_cloak_uniforms(cloak_prog, normal, ambient_dir, kGradient);
        auto cloak_px = draw_and_read();
        ASSERT_EQ(glGetError(), GL_NO_ERROR) << "GL error drawing cloak shell";

        for (int c = 0; c < 3; ++c) {
            EXPECT_NEAR(static_cast<int>(opaque_px[c]),
                       static_cast<int>(cloak_px[c]), 2)
                << "channel " << c << " mismatched for normal ("
                << normal.x << "," << normal.y << "," << normal.z
                << ") -- opaque=" << (int)opaque_px[c]
                << " cloak=" << (int)cloak_px[c]
                << " (cloak shell ambient no longer matches the opaque hull's)";
        }
    }
}

// Sanity companion: with the gradient OFF, both shaders must agree too (this
// already held before the fix, since neither shader's amb term touches
// u_ambient_dir_ws when the gradient is 0 -- confirms the fixture itself
// isn't the source of any pass/fail).
TEST_F(CloakAmbientParityTest, MatchesOpaqueWithGradientOff) {
    const glm::vec3 ambient_dir(1.0f, 0.0f, 0.0f);
    const glm::vec3 normal(1.0f, 0.0f, 0.0f);

    renderer::Shader& opaque_prog = pipeline->opaque_shader();
    set_opaque_uniforms(opaque_prog, normal, ambient_dir, 0.0f);
    auto opaque_px = draw_and_read();

    renderer::Shader& cloak_prog = pipeline->cloak_refraction_shader();
    set_cloak_uniforms(cloak_prog, normal, ambient_dir, 0.0f);
    auto cloak_px = draw_and_read();

    for (int c = 0; c < 3; ++c) {
        EXPECT_NEAR(static_cast<int>(opaque_px[c]),
                   static_cast<int>(cloak_px[c]), 2)
            << "channel " << c << " mismatched with gradient off";
    }
}
