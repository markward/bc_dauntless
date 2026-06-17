// native/tests/renderer/hull_clip_test.cc
//
// Tests for the hull-breach hole clip (Path C / hull-breach-2b).
//
// The hull fragment shader discards a fragment iff it is inside ANY active
// carve sphere. No fill texture is sampled — the sphere IS the clip primitive.
//
//  u_carve_enabled == 0  OR  u_carve_count == 0  → stock path (no discard).
//  u_carve_enabled == 1  AND fragment inside a sphere  → discard.
//  u_carve_enabled == 1  AND fragment OUTSIDE all spheres → renders.
//
// Test strategy: two layers.
//
// Layer 1 — CPU-only invariant (always runs, no GL):
//   A default-constructed HullCarveField has zero active slots / count()==0.
//   frame.cc only enables the clip when count() > 0, so a fresh instance
//   keeps u_carve_enabled==0 / u_carve_count==0 → stock path.
//
// Layer 2 — GL compile + draw + readback (skips without a GL context):
//   Draw a fullscreen triangle through the Pipeline's opaque program, reading
//   back from the default FBO. With identity matrices p_body == a_position,
//   so the centre fragment maps to body (0,0,0). Tests:
//     A) u_carve_enabled = 0                               → renders (no clip)
//     B) enabled, u_carve_count = 0                        → renders (stock)
//     C) enabled, covering sphere (radius 2, centre origin)→ DISCARDED
//     D) enabled, sphere NOT covering origin (offset 10)   → renders

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <renderer/shader.h>
#include <renderer/carve_field_cache.h>

#include <scenegraph/hull_carve.h>
#include <scenegraph/instance.h>

// ── CPU invariant ──────────────────────────────────────────────────────────────

// Lock: a default-constructed HullCarveField has ALL slots inactive and
// count()==0.  frame.cc only enables the clip when count() > 0, so a fresh
// instance keeps the stock-BC path byte-identical (u_carve_enabled == 0).
TEST(HullCarveProductionPath, DefaultFieldHasNoActiveSlots) {
    scenegraph::HullCarveField f;
    for (const auto& s : f.slots()) {
        EXPECT_FALSE(s.active)
            << "default HullCarveField slot is active; frame.cc would enable the "
               "clip for a fresh instance, breaking the stock path";
    }
    EXPECT_EQ(f.count(), 0u)
        << "default HullCarveField count() must be 0 so the clip stays disabled";
}

// ── GL compile + draw + readback ───────────────────────────────────────────────

namespace {

static constexpr int kW = 64;
static constexpr int kH = 64;

class HullClipTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;
    GLuint vao_       = 0;
    GLuint vbo_       = 0;
    GLuint white_tex_ = 0;
    GLuint black_tex_ = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "hull-clip-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }

        pipeline = std::make_unique<renderer::Pipeline>();

        // Fullscreen triangle (CW, matching Pipeline's glFrontFace(GL_CW)).
        const float verts[9] = {
            -1.0f, -1.0f, 0.0f,   // CW: bottom-left
            -1.0f,  3.0f, 0.0f,   //     top-left
             3.0f, -1.0f, 0.0f,   //     bottom-right
        };
        glGenVertexArrays(1, &vao_);
        glGenBuffers(1, &vbo_);
        glBindVertexArray(vao_);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, nullptr);
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

    // Minimum uniforms opaque.frag needs. u_ship_world_inv = identity →
    // p_body == v_position_ws == a_position. Clip disabled by default.
    void set_uniforms(renderer::Shader& s) {
        s.use();
        s.set_mat4("u_view",  glm::mat4(1.0f));
        s.set_mat4("u_proj",  glm::mat4(1.0f));
        s.set_mat4("u_model", glm::mat4(1.0f));
        s.set_mat4("u_ship_world_inv", glm::mat4(1.0f));
        s.set_vec3("u_ambient_light",   glm::vec3(1.0f));
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
        s.set_int("u_decal_count",       0);
        s.set_float("u_decal_time",      0.0f);
        s.set_int("u_glow_region_count", 0);
        // Pure sphere clip: disabled by default.
        s.set_int("u_carve_enabled", 0);
        s.set_int("u_carve_count", 0);
        glActiveTexture(GL_TEXTURE0);
    }

    std::array<unsigned char, 4> read_center() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, 4> px{0, 0, 0, 0};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    void draw() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, kW, kH);
        glDisable(GL_DEPTH_TEST);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glBindVertexArray(vao_);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glBindVertexArray(0);
        glFinish();
    }
};

}  // namespace

// GL Test A: clip disabled (u_carve_enabled=0) → hull renders. Stock path.
TEST_F(HullClipTest, DisabledClipRendersHull) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);  // u_carve_enabled = 0
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in disabled-clip draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2] << ") — disabled clip must not discard";
}

// GL Test B: clip enabled but no spheres (u_carve_count=0) → hull renders.
// This is the whole-hull-erosion regression guard: no sphere = no discard,
// even if u_carve_enabled is set.
TEST_F(HullClipTest, EnabledClipNoSpheresRendersHull) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    prog.set_int("u_carve_enabled", 1);
    prog.set_int("u_carve_count",   0);  // no spheres → no clip
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in enabled/no-spheres draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — u_carve_count=0 must not discard (no whole-hull erosion)";
}

// GL Test C: clip enabled, covering sphere (radius 2, centre origin) →
// fragment at p_body=(0,0,0) is inside the sphere → DISCARDED.
TEST_F(HullClipTest, FragmentInsideSphereIsDiscarded) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    prog.set_int("u_carve_enabled", 1);
    // One sphere centred at origin with radius 2: covers p_body=(0,0,0).
    const glm::vec4 sphere(0.0f, 0.0f, 0.0f, 2.0f);
    prog.set_int("u_carve_count", 1);
    prog.set_vec4_array("u_carve_spheres", &sphere, 1);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in covering-sphere draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 64)
        << "Center pixel is bright (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — fragment inside carve sphere should be discarded (breach hole)";
}

// GL Test D: clip enabled, sphere offset far from origin → centre fragment
// p_body=(0,0,0) is OUTSIDE the sphere → hull renders.
TEST_F(HullClipTest, FragmentOutsideSphereRendersHull) {
    renderer::Shader& prog = pipeline->opaque_shader();
    set_uniforms(prog);
    prog.set_int("u_carve_enabled", 1);
    // Sphere centred at (10,10,10) with radius 1: nowhere near the origin.
    const glm::vec4 sphere(10.0f, 10.0f, 10.0f, 1.0f);
    prog.set_int("u_carve_count", 1);
    prog.set_vec4_array("u_carve_spheres", &sphere, 1);
    draw();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in non-covering-sphere draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 128 * 3 / 2)
        << "Center pixel is dark (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2]
        << ") — fragment outside carve sphere must NOT be discarded";
}
